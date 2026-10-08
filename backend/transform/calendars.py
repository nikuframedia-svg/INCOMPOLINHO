"""Project persistent factory calendars onto the engine timeline.

All runtime intervals are end-exclusive, timezone-aware at the configuration
boundary, and clipped to actual productive shifts. Machine/tool slices are
unioned before consumers see them; operator slices retain their individual
counts so cumulative capacity remains exact.
"""

from __future__ import annotations

import copy
from bisect import bisect_left, bisect_right
from datetime import date as dt_date
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.config.loader import _normalize_unavailability
from backend.config.shifts import merge_clock_intervals, shift_slices
from backend.config.types import FactoryConfig, ShiftConfig
from backend.types import EngineData


def _aware(value: object, timezone: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        try:
            result = datetime.combine(dt_date.fromisoformat(text), time.min)
        except ValueError:
            return None
    tz = ZoneInfo(timezone)
    if result.tzinfo is None:
        result = result.replace(tzinfo=tz)
    return result.astimezone(tz)


def _canonical_entry(
    entry: dict,
    timezone: str,
    *,
    operators: bool = False,
    kind: str = "resource",
) -> dict:
    normalized = _normalize_unavailability(
        [entry],
        operators=operators,
        timezone=timezone,
        kind=kind,
    )
    return normalized[0] if normalized else {}


def _day_bounds(day: dt_date, timezone: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone)
    return (
        datetime.combine(day, time.min, tzinfo=tz),
        datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz),
    )


def _minute_of_day(value: datetime, day: dt_date) -> int:
    if value.date() > day:
        return 1440
    return value.hour * 60 + value.minute


def _range_day_indices(
    entry: dict,
    workday_index: dict[str, int],
    timezone: str = "Europe/Lisbon",
) -> set[int]:
    """Return imported day indices touched by an end-exclusive interval."""

    if entry.get("from") and not entry.get("start_at") and not entry.get("to"):
        return set()
    canonical = _canonical_entry(entry, timezone, kind="range")
    start = _aware(canonical.get("start_at"), timezone)
    end = _aware(canonical.get("end_at"), timezone)
    if start is None:
        return set()
    indices: set[int] = set()
    for day_text, day_idx in workday_index.items():
        try:
            day = dt_date.fromisoformat(str(day_text)[:10])
        except ValueError:
            continue
        day_start, day_end = _day_bounds(day, timezone)
        if start < day_end and (end is None or day_start < end):
            indices.add(day_idx)
    return indices


def _selected_shift(config: FactoryConfig, shift_id: str) -> ShiftConfig | None:
    return next((shift for shift in config.shifts if shift.id == shift_id), None)


def _timeline_days(
    entries: list[dict],
    engine_data: EngineData,
    timezone: str,
    *,
    operators: bool,
    kind: str,
    canonical: bool = False,
) -> list[tuple[int, dt_date]]:
    """Return imported days plus every future day touched by a calendar entry."""

    imported: list[tuple[int, dt_date]] = []
    for day_idx, day_text in enumerate(engine_data.workdays):
        try:
            imported.append((day_idx, dt_date.fromisoformat(str(day_text)[:10])))
        except ValueError:
            continue
    if not imported:
        return []

    first_day = imported[0][1]
    future: set[int] = set()
    for raw_entry in entries:
        entry = raw_entry if canonical else _canonical_entry(
            raw_entry,
            timezone,
            operators=operators,
            kind=kind,
        )
        start = _aware(entry.get("start_at"), timezone)
        end = _aware(entry.get("end_at"), timezone)
        if start is not None:
            start_index = (start.date() - first_day).days
            end_index = (
                (end.date() - first_day).days
                if end
                else max(engine_data.n_days - 1, start_index + 1)
            )
            # Retain boundary markers for old consumers; interior days are
            # projected only when a calculation actually reaches that period.
            future.update(
                index
                for index in (start_index, min(start_index + 1, end_index), end_index)
                if index >= engine_data.n_days
            )

    seen = {day_idx for day_idx, _day in imported}
    imported.extend(
        (day_idx, first_day + timedelta(days=day_idx))
        for day_idx in future
        if day_idx not in seen
    )
    return sorted(imported)


def _project_intervals(
    entries: list[dict],
    engine_data: EngineData,
    config: FactoryConfig,
    *,
    resource_key: str,
    operators: bool = False,
    kind: str = "resource",
    canonical_entries: bool = False,
    timeline: list[tuple[int, dt_date]] | None = None,
) -> dict[str, list[dict]]:
    """Project intervals to per-day slices that contain productive minutes."""

    result: dict[str, list[dict]] = {}
    canonical = [
        raw
        if canonical_entries
        else _canonical_entry(raw, config.timezone, operators=operators, kind=kind)
        for raw in entries
        if not (raw.get("from") and not raw.get("start_at") and not raw.get("to"))
    ]
    if not canonical_entries:
        engine_data.calendar_sources[kind] = {
            "entries": canonical,
            "resource_key": resource_key,
            "operators": operators,
        }
    timeline = sorted(
        timeline
        if timeline is not None
        else _timeline_days(
            canonical, engine_data, config.timezone, operators=operators, kind=kind, canonical=True
        ),
        key=lambda item: item[1],
    )
    dates = [day for _index, day in timeline]
    for entry in canonical:
        from backend.planning_control import planning_checkpoint

        planning_checkpoint()
        resource = str(entry.get(resource_key, "")).strip()
        if operators and resource_key == "_resource":
            resource = f"{entry.get('group', '')}|{entry.get('shift', '')}"
        start = _aware(entry.get("start_at"), config.timezone)
        end = _aware(entry.get("end_at"), config.timezone)
        if not resource or start is None:
            continue
        selected_shift = (
            _selected_shift(config, str(entry.get("shift", "")))
            if operators
            else None
        )
        if operators and selected_shift is None:
            continue

        first = bisect_left(dates, start.date())
        last = bisect_right(dates, end.date()) if end else len(timeline)
        for day_idx, day in timeline[first:last]:
            day_start, day_end = _day_bounds(day, config.timezone)
            overlap_start = max(start, day_start)
            overlap_end = min(end or day_end, day_end)
            if overlap_start >= overlap_end:
                continue
            wall_start = max(0, _minute_of_day(overlap_start, day))
            wall_end = min(1440, _minute_of_day(overlap_end, day))
            slices = shift_slices(config, wall_start, wall_end)
            if selected_shift is not None:
                slices = [item for item in slices if item[0] == selected_shift.id]
            for shift_id, start_min, end_min in slices:
                projected = {
                    "id": str(entry.get("id", "")),
                    "start_day": day_idx,
                    "start_min": start_min,
                    "end_day": day_idx,
                    "end_min": end_min,
                    "shift": shift_id,
                    "start_at": start.isoformat(timespec="minutes"),
                    "end_at": end.isoformat(timespec="minutes") if end else "",
                    "open_end": end is None,
                    "category": str(entry.get("category", "Outra")),
                    "reason": str(entry.get("reason", "")),
                }
                if operators:
                    projected.update(
                        group=str(entry.get("group", "")),
                        count=max(0, int(entry.get("count", 1))),
                    )
                result.setdefault(resource, []).append(projected)
    return result


def _merge_resource_intervals(
    projected: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Union overlapping/touching fixed blocks for each resource and day."""

    result: dict[str, list[dict]] = {}
    for resource, entries in projected.items():
        by_day: dict[int, list[dict]] = {}
        for entry in entries:
            by_day.setdefault(int(entry.get("start_day", -1)), []).append(entry)
        merged_entries: list[dict] = []
        for day_idx, day_entries in sorted(by_day.items()):
            groups: list[tuple[int, int, list[dict]]] = []
            for entry in sorted(day_entries, key=lambda item: int(item["start_min"])):
                start, end = int(entry["start_min"]), int(entry["end_min"])
                if groups and start <= groups[-1][1]:
                    left, right, contributors = groups[-1]
                    contributors.append(entry)
                    groups[-1] = (left, max(right, end), contributors)
                else:
                    groups.append((start, end, [entry]))
            for start, end, contributors in groups:
                first = contributors[0]
                source_ids = list(
                    dict.fromkeys(str(entry.get("id", "")) for entry in contributors)
                )
                categories = list(
                    dict.fromkeys(str(entry.get("category", "Outra")) for entry in contributors)
                )
                reasons = list(
                    dict.fromkeys(
                        str(entry.get("reason", ""))
                        for entry in contributors
                        if entry.get("reason")
                    )
                )
                merged_entries.append(
                    {
                        **first,
                        "id": source_ids[0] if len(source_ids) == 1 else "+".join(source_ids),
                        "source_ids": source_ids,
                        "start_day": day_idx,
                        "start_min": start,
                        "end_day": day_idx,
                        "end_min": end,
                        "open_end": any(bool(entry.get("open_end")) for entry in contributors),
                        "category": categories[0] if len(categories) == 1 else "Outra",
                        "reason": "; ".join(reasons),
                    }
                )
        if merged_entries:
            result[resource] = merged_entries
    return result


def _full_productive_days(
    projected: dict[str, list[dict]],
    config: FactoryConfig,
) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}
    for resource, entries in projected.items():
        by_day: dict[int, list[tuple[int, int]]] = {}
        for entry in entries:
            by_day.setdefault(int(entry.get("start_day", -1)), []).append(
                (int(entry.get("start_min", 0)), int(entry.get("end_min", 0)))
            )
        for day_idx, intervals in by_day.items():
            covered = sum(end - start for start, end in merge_clock_intervals(intervals))
            if covered >= config.day_capacity_min:
                result.setdefault(resource, set()).add(day_idx)
    return result


def _extend_projected(
    target: dict[str, list[dict]],
    extra: dict[str, list[dict]],
) -> None:
    for resource, intervals in extra.items():
        target.setdefault(resource, []).extend(intervals)


def apply_calendars(engine_data: EngineData, config: FactoryConfig | None) -> EngineData:
    """Rebuild effective holidays and resource intervals in place."""

    if config is None:
        return engine_data
    engine_data.calendar_sources = {}
    engine_data.calendar_projection_end = len(engine_data.workdays) - 1
    engine_data.calendar_day_offset = 0

    workday_index = {str(day)[:10]: index for index, day in enumerate(engine_data.workdays)}
    try:
        first_day = dt_date.fromisoformat(str(engine_data.workdays[0])[:10])
    except (IndexError, ValueError):
        first_day = None

    def calendar_index(value: object) -> int | None:
        text = str(value)[:10]
        imported = workday_index.get(text)
        if imported is not None:
            return imported
        if first_day is None:
            return None
        try:
            return (dt_date.fromisoformat(text) - first_day).days
        except ValueError:
            return None

    if engine_data.calendar_base_holidays is None:
        engine_data.calendar_base_holidays = sorted(set(engine_data.holidays))

    holiday_set = set(engine_data.calendar_base_holidays)
    explicit_holidays: set[int] = set(engine_data.calendar_explicit_holidays)
    for holiday in config.holidays:
        index = calendar_index(holiday)
        if index is not None:
            holiday_set.add(index)
            explicit_holidays.add(index)
    extra_workdays: set[int] = set()
    for extra_day in config.extra_workdays:
        index = calendar_index(extra_day)
        if index is None or index in explicit_holidays:
            continue
        try:
            if dt_date.fromisoformat(str(extra_day)).weekday() >= 5:
                holiday_set.discard(index)
                extra_workdays.add(index)
        except ValueError:
            continue
    engine_data.holidays = sorted(holiday_set)
    engine_data.calendar_extra_workdays = sorted(extra_workdays)

    machine_projected = _project_intervals(
        config.machine_unavailability,
        engine_data,
        config,
        resource_key="resource",
        kind="machine",
    )
    tool_projected = _project_intervals(
        config.tool_unavailability,
        engine_data,
        config,
        resource_key="resource",
        kind="tool",
    )

    if engine_data.current_machine_states and engine_data.workdays:
        first_day = str(engine_data.workdays[0])[:10]
        shift_start = min(shift.start_min for shift in config.shifts)
        current_machine_entries: list[dict] = []
        current_tool_entries: list[dict] = []
        for current in engine_data.current_machine_states:
            if current.status == "idle":
                continue
            start_at = f"{first_day}T{shift_start // 60:02d}:{shift_start % 60:02d}"
            current_machine_entries.append(
                {
                    "id": f"current-machine-{current.machine_id}",
                    "resource": current.machine_id,
                    "start_at": start_at,
                    "end_at": current.expected_end or "",
                    "category": "Avaria" if current.status == "down" else "Outra",
                    "reason": current.note or f"Estado atual: {current.status}",
                }
            )
            if current.status in {"producing", "setup", "trial"} and current.tool_id:
                current_tool_entries.append(
                    {
                        "id": f"current-tool-{current.machine_id}",
                        "resource": current.tool_id,
                        "start_at": start_at,
                        "end_at": current.expected_end or "",
                        "category": "Outra",
                        "reason": current.note or f"Estado atual: {current.status}",
                    }
                )
        _extend_projected(
            machine_projected,
            _project_intervals(
                current_machine_entries,
                engine_data,
                config,
                resource_key="resource",
                kind="current-machine",
            ),
        )
        _extend_projected(
            tool_projected,
            _project_intervals(
                current_tool_entries,
                engine_data,
                config,
                resource_key="resource",
                kind="current-tool",
            ),
        )

    engine_data.machine_blocked_intervals = _merge_resource_intervals(machine_projected)
    engine_data.tool_blocked_intervals = _merge_resource_intervals(tool_projected)
    engine_data.machine_blocked_days = _full_productive_days(
        engine_data.machine_blocked_intervals,
        config,
    )
    engine_data.tool_blocked_days = _full_productive_days(
        engine_data.tool_blocked_intervals,
        config,
    )

    projected = _project_intervals(
        config.operator_unavailability,
        engine_data,
        config,
        resource_key="_resource",
        operators=True,
        kind="operator",
    )
    operator_projected = [block for blocks in projected.values() for block in blocks]
    engine_data.operator_blocked_intervals = sorted(
        operator_projected,
        key=lambda item: (
            int(item.get("start_day", -1)),
            int(item.get("start_min", 0)),
            str(item.get("group", "")),
            str(item.get("shift", "")),
            str(item.get("id", "")),
        ),
    )
    return engine_data


def calendar_window(
    data: EngineData, config: FactoryConfig | None, through_day: int, *, from_day: int | None = None
) -> EngineData:
    """Detached projection of a newly requested period, preserving temporary overlays."""
    if (
        config is None
        or not data.calendar_sources
        or through_day <= data.calendar_projection_end
        or not data.workdays
    ):
        return data
    first = max(data.calendar_projection_end + 1, from_day if from_day is not None else 0)
    from backend.calendar import _day_date

    timeline = [(day, _day_date(day, data)) for day in range(first, through_day + 1)]
    timeline = [
        (day, calendar_date) for day, calendar_date in timeline if calendar_date is not None
    ]
    projected_machine, projected_tool, projected_operator = {}, {}, {}
    for kind, source in data.calendar_sources.items():
        blocks = _project_intervals(
            source["entries"],
            data,
            config,
            resource_key=source["resource_key"],
            operators=source["operators"],
            kind=kind,
            canonical_entries=True,
            timeline=timeline,
        )
        target = (
            projected_operator
            if source["operators"]
            else projected_tool
            if "tool" in kind
            else projected_machine
        )
        _extend_projected(target, blocks)
    result = copy.copy(data)

    def merge(old, new):
        combined = {resource: list(blocks) for resource, blocks in old.items()}
        _extend_projected(combined, new)
        return _merge_resource_intervals(combined)

    result.machine_blocked_intervals = merge(data.machine_blocked_intervals, projected_machine)
    result.tool_blocked_intervals = merge(data.tool_blocked_intervals, projected_tool)
    for attribute, intervals in (
        ("machine_blocked_days", result.machine_blocked_intervals),
        ("tool_blocked_days", result.tool_blocked_intervals),
    ):
        days = {resource: set(values) for resource, values in getattr(data, attribute).items()}
        for resource, values in _full_productive_days(intervals, config).items():
            days.setdefault(resource, set()).update(values)
        setattr(result, attribute, days)
    result.operator_blocked_intervals = list(data.operator_blocked_intervals)
    # Boundary markers already projected by apply_calendars must not subtract
    # an absence twice. Distinct source records remain additive.
    import json
    from collections import Counter

    existing = Counter(
        json.dumps(block, sort_keys=True) for block in data.operator_blocked_intervals
    )
    for blocks in projected_operator.values():
        for block in blocks:
            key = json.dumps(block, sort_keys=True)
            if existing[key]:
                existing[key] -= 1
            else:
                result.operator_blocked_intervals.append(block)
    if first == data.calendar_projection_end + 1:
        result.calendar_projection_end = through_day
    return result
