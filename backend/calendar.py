"""Factory calendar and real available capacity helpers."""

from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.config.shifts import merge_clock_intervals, productive_minutes_between
from backend.config.types import FactoryConfig, ShiftConfig
from backend.scheduler.constants import DAY_CAP, OPERATOR_CAP
from backend.scheduler.operators import effective_operator_capacity
from backend.types import EngineData


def current_factory_day(data: EngineData, config: FactoryConfig, *, now=None) -> int:
    today = (
        (now or datetime.now(ZoneInfo(config.timezone)))
        .astimezone(ZoneInfo(config.timezone))
        .date()
        .isoformat()
    )
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
