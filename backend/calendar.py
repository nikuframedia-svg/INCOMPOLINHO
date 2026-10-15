"""Factory calendar and real available capacity helpers."""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date as dt_date
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.config.shifts import merge_clock_intervals, productive_minutes_between
from backend.config.types import FactoryConfig, ShiftConfig
from backend.scheduler.constants import DAY_CAP, OPERATOR_CAP
from backend.scheduler.operators import effective_operator_capacity
from backend.types import EngineData

# Free shift time shorter than this is the gap between two segments, not
# capacity a run could use (rule 4 contiguity, idle-capacity check).
MIN_FREE_INTERVAL_MIN = 30


# The one "now" of the calculation running in this context (a replan job, a
# plan write), set by ``fixed_factory_clock``; ``None`` reads the clock.
_FIXED_NOW: ContextVar[datetime | None] = ContextVar("factory_fixed_now", default=None)


@contextmanager
def fixed_factory_clock(now: datetime | None) -> Iterator[datetime | None]:
    """Every ``factory_now`` inside reads ``now`` (AGENTS §2 rule 4, 13/10/2026).

    A replan job or a plan write captures one instant and calculates with
    it: the planning day, the minutes of today already gone, the rule-4
    protection, the idle-capacity check and the commit guard all agree.
    ``None`` changes nothing: an instant fixed outside stays in force.
    """
    if now is None:
        yield _FIXED_NOW.get()
        return
    token = _FIXED_NOW.set(now)
    try:
        yield now
    finally:
        _FIXED_NOW.reset(token)


def _wall_clock(zone: ZoneInfo) -> datetime:
    return datetime.now(zone)


def factory_now(config: FactoryConfig | str | None, *, now: datetime | None = None) -> datetime:
    """The current time in the factory's time zone.

    ``now`` replaces the clock, then the instant fixed for this calculation
    (``fixed_factory_clock``). ``config`` may be the time zone name.
    """

    name = config if isinstance(config, str) else getattr(config, "timezone", None)
    zone = ZoneInfo(str(name or "Europe/Lisbon"))
    return (now or _FIXED_NOW.get() or _wall_clock(zone)).astimezone(zone)


def wall_factory_now(config: FactoryConfig | str | None) -> datetime:
    """The real factory clock, whatever instant a calculation fixed.

    The commit guard reads the date of today here: a candidate is checked
    against the day it is applied on, never the day it was calculated on.
    """

    name = config if isinstance(config, str) else getattr(config, "timezone", None)
    zone = ZoneInfo(str(name or "Europe/Lisbon"))
    return _wall_clock(zone).astimezone(zone)


def elapsed_minutes(
    day_idx: int, data: EngineData, config: FactoryConfig | None, *, now: datetime | None = None,
) -> int:
    """Minutes of plan day ``day_idx`` already gone at ``now`` (factory time).

    The current minute of the day when ``day_idx`` is today, 0 on any other
    day: the days before the planning day are elapsed as a whole by the
    planning day itself, and a plan replayed on another date has no current
    minute.
    """

    day = _day_date(day_idx, data)
    current = factory_now(config, now=now)
    if day is None or day != current.date():
        return 0
    return current.hour * 60 + current.minute


def current_factory_day(data: EngineData, config: FactoryConfig, *, now=None) -> int:
    today = factory_now(config, now=now).date().isoformat()
    return next(
        (index for index, day in enumerate(data.workdays) if str(day)[:10] >= today),
        len(data.workdays),
    )


def _day_date(day_idx: int, data: EngineData) -> dt_date | None:
    if not data.workdays:
        return None
    day_idx -= data.calendar_day_offset
    try:
        if 0 <= day_idx < len(data.workdays):
            return dt_date.fromisoformat(str(data.workdays[day_idx])[:10])
        first = dt_date.fromisoformat(str(data.workdays[0])[:10])
        return first + timedelta(days=day_idx)
    except ValueError:
        return None


def _config_dates(values: list[str] | None) -> set[str]:
    return {str(value).split("T")[0] for value in values or []}


def _is_explicit_holiday(
    day_idx: int,
    day: dt_date | None,
    data: EngineData,
    config: FactoryConfig | None,
) -> bool:
    if day_idx in set(getattr(data, "calendar_explicit_holidays", []) or []):
        return True
    return bool(config and day and day.isoformat() in _config_dates(config.holidays))


def _is_extra_workday(day: dt_date | None, config: FactoryConfig | None) -> bool:
    return bool(config and day and day.isoformat() in _config_dates(config.extra_workdays))


def is_factory_workday(day_idx: int, data: EngineData, config: FactoryConfig | None = None) -> bool:
    """Return whether the factory should count this day as productive capacity."""
    if day_idx < 0:
        return False

    day = _day_date(day_idx, data)
    is_weekend = bool(day and day.weekday() >= 5)
    explicit = _is_explicit_holiday(day_idx, day, data, config)
    if explicit:
        return False

    if is_weekend:
        return _is_extra_workday(day, config)

    if day_idx in set(getattr(data, "holidays", []) or []):
        return False

    return True


def _machine_base_capacity(machine_id: str, data: EngineData, config: FactoryConfig | None) -> int:
    machine_cfg = config.machines.get(machine_id) if config else None
    if machine_cfg is not None and machine_cfg.day_capacity_min is not None:
        return int(machine_cfg.day_capacity_min)
    if config is not None:
        return int(config.day_capacity_min)
    machine = next((item for item in data.machines if item.id == machine_id), None)
    return int(getattr(machine, "day_capacity", DAY_CAP) or DAY_CAP)


def _machine_active(machine_id: str, config: FactoryConfig | None) -> bool:
    if config is None:
        return True
    machine_cfg = config.machines.get(machine_id)
    return bool(machine_cfg is None or machine_cfg.active)


def _blocked_minutes(
    intervals: list[dict[str, Any]],
    day_idx: int,
    start_min: int,
    end_min: int,
    config: FactoryConfig | None = None,
) -> int:
    relevant: list[tuple[int, int]] = []
    for interval in intervals:
        if int(interval.get("start_day", -1)) != day_idx:
            continue
        start = max(start_min, int(interval.get("start_min", 0)))
        end = min(end_min, int(interval.get("end_min", 1440)))
        if start < end:
            relevant.append((start, end))
    if config is None:
        return sum(end - start for start, end in merge_clock_intervals(relevant))
    return sum(
        productive_minutes_between(config, start, end)
        for start, end in merge_clock_intervals(relevant)
    )


def available_machine_capacity(
    machine_id: str,
    day_idx: int,
    data: EngineData,
    config: FactoryConfig | None = None,
) -> int:
    """Return real available machine minutes for one day."""
    from backend.transform.calendars import calendar_window

    data = calendar_window(data, config, day_idx, from_day=day_idx)
    if not _machine_active(machine_id, config):
        return 0
    if not is_factory_workday(day_idx, data, config):
        return 0
    if day_idx in data.machine_blocked_days.get(machine_id, set()):
        return 0

    base = _machine_base_capacity(machine_id, data, config)
    shift_start = config.shift_a_start if config else 420
    shift_end = config.shift_b_end if config else 1440
    blocked = _blocked_minutes(
        data.machine_blocked_intervals.get(machine_id, []),
        day_idx,
        shift_start,
        shift_end,
        config,
    )
    return max(0, int(base - min(base, blocked)))


def available_tool_capacity(
    tool_id: str,
    day_idx: int,
    data: EngineData,
    config: FactoryConfig | None = None,
) -> int:
    """Return real minutes for one physical tool on a factory day."""
    from backend.transform.calendars import calendar_window

    data = calendar_window(data, config, day_idx, from_day=day_idx)

    if not is_factory_workday(day_idx, data, config):
        return 0
    if day_idx in data.tool_blocked_days.get(tool_id, set()):
        return 0

    base = int(config.day_capacity_min) if config is not None else DAY_CAP
    shift_start = config.shift_a_start if config else 420
    shift_end = config.shift_b_end if config else 1440
    blocked = _blocked_minutes(
        data.tool_blocked_intervals.get(tool_id, []),
        day_idx,
        shift_start,
        shift_end,
        config,
    )
    return max(0, int(base - min(base, blocked)))


def _shift_duration(
    shift: ShiftConfig | str,
    config: FactoryConfig | None,
) -> tuple[str, int, int, int]:
    if isinstance(shift, ShiftConfig):
        return shift.id, shift.start_min, shift.end_min, shift.duration_min
    shift_id = str(shift)
    if config is not None:
        found = next((item for item in config.shifts if item.id == shift_id), None)
        if found is not None:
            return found.id, found.start_min, found.end_min, found.duration_min
    return shift_id, 420, 1440, DAY_CAP


def available_operator_capacity(
    group: str,
    shift: ShiftConfig | str,
    day_idx: int,
    data: EngineData,
    config: FactoryConfig | None = None,
) -> int:
    """Return real available operator minutes for one group/shift/day."""
    from backend.transform.calendars import calendar_window

    data = calendar_window(data, config, day_idx, from_day=day_idx)
    if not is_factory_workday(day_idx, data, config):
        return 0

    shift_id, shift_start, shift_end, duration = _shift_duration(shift, config)
    count = (
        effective_operator_capacity(data, config, day_idx, group, shift_id)
        if config is not None
        else OPERATOR_CAP.get((group, shift_id), 0)
    )
    capacity = max(0, count) * duration
    for block in data.operator_blocked_intervals:
        if (
            str(block.get("group", "")) == group
            and str(block.get("shift", "")) == shift_id
            and int(block.get("start_day", -1)) == day_idx
        ):
            overlap = max(
                0,
                min(shift_end, int(block.get("end_min", 0)))
                - max(shift_start, int(block.get("start_min", 0))),
            )
            capacity -= overlap * max(0, int(block.get("count", 1)))
    return max(0, int(capacity))


def total_machine_capacity(
    machine_id: str,
    day_indices: range | list[int],
    data: EngineData,
    config: FactoryConfig | None = None,
) -> int:
    return sum(
        available_machine_capacity(machine_id, day_idx, data, config)
        for day_idx in day_indices
    )


def _subtract_intervals(
    interval: tuple[int, int], busy: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    pieces = [interval]
    for left, right in busy:
        if right <= left:
            continue
        pieces = [
            part
            for start, end in pieces
            for part in ((start, min(end, left)), (max(start, right), end))
            if part[1] > part[0]
        ]
    return pieces


def free_shift_intervals(
    machine_id: str,
    tool_id: str,
    day_idx: int,
    data: EngineData,
    config: FactoryConfig,
    *,
    segments: list | tuple = (),
    required_operators: int = 1,
    start_min: float = 0,
    end_min: float = 1440,
) -> list[tuple[int, int]]:
    """Free shift time of a machine and tool on one day, within ``[start_min, end_min)``.

    Free: inside a shift of a factory working day; outside the machine and
    tool unavailabilities; not taken by a segment of ``segments`` (that day's
    plan) on the machine or with the tool on another machine; with
    ``required_operators`` operators of the machine's group still available
    (``operators.operator_free_windows``). Pieces shorter than
    ``MIN_FREE_INTERVAL_MIN`` are gaps, not usable time. The single
    definition of free time for rule 4 (``plans.frozen``) and the
    idle-capacity check (``scheduler.idle_capacity``).
    """
    from backend.config.shifts import ordered_shifts
    from backend.scheduler.operators import operator_free_windows
    from backend.transform.calendars import calendar_window

    view = calendar_window(data, config, day_idx, from_day=day_idx)
    if not is_factory_workday(day_idx, view, config):
        return []
    if (day_idx in view.machine_blocked_days.get(machine_id, set())
            or day_idx in view.tool_blocked_days.get(tool_id, set())):
        return []
    day_segments = [segment for segment in segments if segment.day_idx == day_idx]
    busy = [
        (int(block.get("start_min", 0)), int(block.get("end_min", 1440)))
        for block in [
            *view.machine_blocked_intervals.get(machine_id, []),
            *view.tool_blocked_intervals.get(tool_id, []),
        ]
        if int(block.get("start_day", -1)) == day_idx
    ]
    busy += [
        (math.floor(segment.start_min), math.ceil(segment.end_min))
        for segment in day_segments
        if segment.end_min > segment.start_min
        and (segment.machine_id == machine_id or segment.tool_id == tool_id)
    ]
    group = (
        config.machine_group(machine_id) if hasattr(config, "machine_group")
        else next((machine.group for machine in data.machines if machine.id == machine_id), None)
    )
    intervals: list[tuple[int, int]] = []
    for shift in ordered_shifts(config):
        low = math.ceil(max(float(start_min), float(shift.start_min)))
        high = math.floor(min(float(end_min), float(shift.end_min)))
        if high - low < MIN_FREE_INTERVAL_MIN:
            continue
        staffed = (
            operator_free_windows(
                day_segments, data, config, day=day_idx, shift=shift.id, group=group,
                required=max(1, int(required_operators)), start=low, end=high,
            )
            if group else [(low, high)]
        )
        for start, end in staffed:
            intervals.extend(
                (left, right) for left, right in _subtract_intervals((start, end), busy)
                if right - left >= MIN_FREE_INTERVAL_MIN
            )
    return intervals
