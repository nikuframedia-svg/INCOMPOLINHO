"""Operator capacity by group and shift."""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.config.types import FactoryConfig
from backend.scheduler.constants import MACHINE_GROUP, OPERATOR_CAP
from backend.scheduler.types import OperatorAlert, Segment
from backend.types import EngineData


@dataclass(frozen=True, slots=True)
class OperatorPeak:
    """Exact peak staffing state for one day, group and shift."""

    day_idx: int
    group: str
    shift: str
    required: int
    available: int
    deficit: int
    peak_required: int
    min_available: int


def effective_operator_capacity(
    engine_data: EngineData,
    config: FactoryConfig | None,
    day_idx: int,
    group: str,
    shift: str,
) -> int:
    """Return configured headcount; exact absences live on the engine timeline."""

    del engine_data, day_idx
    return (
        config.operators.get((group, shift), 0) if config else OPERATOR_CAP.get((group, shift), 0)
    )


def segment_operator_demand(segment: Segment, engine_data: EngineData) -> int:
    """Return simultaneous ISOP headcount required by one production segment."""

    ops_by_id = {op.id: op for op in engine_data.ops}
    if segment.twin_outputs:
        return max(
            (
                max(1, int(getattr(ops_by_id.get(op_id), "operators", 1) or 1))
                for op_id, _sku, _qty in segment.twin_outputs
            ),
            default=1,
        )

    op = next(
        (
            candidate
            for candidate in engine_data.ops
            if candidate.sku == segment.sku
            and candidate.m == segment.machine_id
            and candidate.t == segment.tool_id
        ),
        None,
    )
    if op is None:
        op = next(
            (
                candidate
                for candidate in engine_data.ops
                if candidate.sku == segment.sku and candidate.t == segment.tool_id
            ),
            None,
        )
    return max(1, int(getattr(op, "operators", 1) or 1))


def operator_free_windows(
    segments: list[Segment],
    data: EngineData,
    config: FactoryConfig,
    *,
    day: int,
    shift: str,
    group: str,
    required: int,
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    """Minute-grid windows contained in exact staffing availability."""
    from backend.transform.calendars import calendar_window

    data = calendar_window(data, config, day, from_day=day)
    capacity = max(0, effective_operator_capacity(data, config, day, group, shift))
    if required > capacity or end <= start:
        return []
    intervals = [
        (max(start, segment.production_start_min), min(end, segment.end_min),
         segment_operator_demand(segment, data))
        for segment in segments
        if segment.day_idx == day and segment.prod_min > 0
        and config.machine_groups.get(segment.machine_id, "Grandes") == group
    ]
    intervals.extend(
        (max(start, float(block.get("start_min", 0))),
         min(end, float(block.get("end_min", 1440))),
         max(0, int(block.get("count", 1))))
        for block in data.operator_blocked_intervals
        if int(block.get("start_day", -1)) == day
        and block.get("group") == group and block.get("shift") == shift
    )
    deltas: dict[float, int] = {float(start): 0, float(end): 0}
    for left, right, count in intervals:
        if right <= left:
            continue
        deltas[left] = deltas.get(left, 0) + count
        deltas[right] = deltas.get(right, 0) - count
    available: list[tuple[float, float]] = []
    used = 0
    points = sorted(deltas)
    for left, right in zip(points, points[1:]):
        used += deltas[left]
        if used + required > capacity:
            continue
        if available and available[-1][1] == left:
            available[-1] = (available[-1][0], right)
        else:
            available.append((left, right))
    # Merge exact slices before rounding, so irrelevant fractional events do
    # not cut an otherwise continuous free minute out of the search domain.
    return [(math.ceil(left), math.floor(right)) for left, right in available
            if math.ceil(left) < math.floor(right)]


def operator_peaks(
    segments: list[Segment],
    engine_data: EngineData,
    config: FactoryConfig | None = None,
    *,
    include_keys: set[tuple[int, str, str]] | None = None,
) -> dict[tuple[int, str, str], OperatorPeak]:
    """Return exact concurrent demand and absence capacity for each timeline key.

    ``required`` and ``available`` describe the interval with the largest
    deficit.  When there is no deficit they describe the interval with peak
    production demand, so dashboards never compare values from different
    moments of the shift.
    """
    from backend.transform.calendars import calendar_window

    last_day = max([*(s.day_idx for s in segments), *(key[0] for key in include_keys or ()), 0])
    engine_data = calendar_window(engine_data, config, last_day)

    machine_group = config.machine_groups if config else MACHINE_GROUP
    configured_shifts = (
        [(shift.id, int(shift.start_min), int(shift.end_min)) for shift in config.shifts]
        if config is not None
        else [("A", 420, 930), ("B", 930, 1440)]
    )
    production_events: dict[tuple[int, str, str], list[tuple[float, int]]] = {}
    for segment in segments:
        if segment.prod_min <= 0:
            continue
        group = machine_group.get(segment.machine_id, "Grandes")
        required = segment_operator_demand(segment, engine_data)
        production_start = segment.production_start_min
        for shift_id, shift_start, shift_end in configured_shifts:
            overlap_start = max(production_start, shift_start)
            overlap_end = min(int(segment.end_min), shift_end)
            if overlap_start >= overlap_end:
                continue
            key = (segment.day_idx, group, shift_id)
            production_events.setdefault(key, []).extend(
                [(overlap_start, required), (overlap_end, -required)]
            )

    unavailable_events: dict[tuple[int, str, str], list[tuple[float, int]]] = {}
    for block in engine_data.operator_blocked_intervals:
        key = (
            int(block.get("start_day", -1)),
            str(block.get("group", "")),
            str(block.get("shift", "")),
        )
        count = max(0, int(block.get("count", 1)))
        start = float(block.get("start_min", 0))
        end = float(block.get("end_min", 0))
        if count and start < end:
            unavailable_events.setdefault(key, []).extend(
                [(start, count), (end, -count)]
            )

    keys = set(production_events) | set(unavailable_events) | set(include_keys or set())
    peaks: dict[tuple[int, str, str], OperatorPeak] = {}
    for day_idx, group, shift in sorted(keys):
        base = max(
            0,
            int(effective_operator_capacity(engine_data, config, day_idx, group, shift)),
        )
        deltas: dict[float, list[int]] = {}
        for minute, delta in production_events.get((day_idx, group, shift), []):
            deltas.setdefault(minute, [0, 0])[0] += delta
        for minute, delta in unavailable_events.get((day_idx, group, shift), []):
            deltas.setdefault(minute, [0, 0])[1] += delta

        required_now = 0
        unavailable_now = 0
        peak_required = 0
        min_available = base
        selected_required = 0
        selected_available = base
        selected_deficit = 0
        selected_rank = (-1, -1, 0)
        minutes = sorted(deltas)
        for index, minute in enumerate(minutes):
            required_delta, unavailable_delta = deltas[minute]
            required_now += required_delta
            unavailable_now += unavailable_delta
            next_minute = minutes[index + 1] if index + 1 < len(minutes) else minute
            if next_minute <= minute:
                continue
            available_now = max(0, base - unavailable_now)
            deficit_now = max(0, required_now - available_now)
            peak_required = max(peak_required, required_now)
            min_available = min(min_available, available_now)
            rank = (deficit_now, required_now, -available_now)
            if rank > selected_rank:
                selected_rank = rank
                selected_required = required_now
                selected_available = available_now
                selected_deficit = deficit_now

        peaks[(day_idx, group, shift)] = OperatorPeak(
            day_idx=day_idx,
            group=group,
            shift=shift,
            required=max(0, selected_required),
            available=max(0, selected_available),
            deficit=max(0, selected_deficit),
            peak_required=max(0, peak_required),
            min_available=max(0, min_available),
        )
    return peaks


def compute_operator_alerts(
    segments: list[Segment],
    engine_data: EngineData,
    config: FactoryConfig | None = None,
) -> list[OperatorAlert]:
    """Check peak simultaneous ISOP operator demand per group/shift."""
    alerts: list[OperatorAlert] = []
    for peak in operator_peaks(segments, engine_data, config).values():
        if peak.deficit > 0:
            date = ""
            if 0 <= peak.day_idx < len(engine_data.workdays):
                date = engine_data.workdays[peak.day_idx]
            alerts.append(
                OperatorAlert(
                    day_idx=peak.day_idx,
                    date=date,
                    shift=peak.shift,
                    machine_group=peak.group,
                    required=peak.required,
                    available=peak.available,
                    deficit=peak.deficit,
                )
            )

    return sorted(alerts, key=lambda a: (a.day_idx, a.machine_group, a.shift))
