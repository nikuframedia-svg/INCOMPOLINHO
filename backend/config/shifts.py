"""Shared shift normalization and productive-time helpers.

The planner uses a compressed time axis: only configured shift minutes exist
on that axis.  Keeping the conversions here prevents calendar consumers from
silently treating a closed gap between shifts as productive time.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from .types import FactoryConfig, ShiftConfig


def ordered_shifts(config: FactoryConfig) -> list[ShiftConfig]:
    """Return shifts in wall-clock order without mutating the configuration."""

    return sorted(config.shifts, key=lambda shift: (int(shift.start_min), shift.id))


def shift_slices(
    config: FactoryConfig,
    start_min: int | float,
    end_min: int | float,
) -> list[tuple[str, int, int]]:
    """Intersect one wall-clock interval with the factory's productive shifts."""

    start = int(start_min)
    end = int(end_min)
    if end <= start:
        return []
    result: list[tuple[str, int, int]] = []
    for shift in ordered_shifts(config):
        overlap_start = max(start, int(shift.start_min))
        overlap_end = min(end, int(shift.end_min))
        if overlap_start < overlap_end:
            result.append((shift.id, overlap_start, overlap_end))
    return result


def productive_minutes_between(
    config: FactoryConfig,
    start_min: int | float,
    end_min: int | float,
) -> int:
    """Return productive minutes in ``[start_min, end_min)``."""

    return sum(end - start for _shift, start, end in shift_slices(config, start_min, end_min))


def interval_is_productive(
    config: FactoryConfig,
    start_min: int | float,
    end_min: int | float,
) -> bool:
    """Whether every wall-clock minute in the interval belongs to a shift."""

    start = int(start_min)
    end = int(end_min)
    return end > start and productive_minutes_between(config, start, end) == end - start


def clock_to_productive_offset(config: FactoryConfig, minute: int | float) -> int:
    """Map a wall-clock minute to the compressed productive-day axis.

    Minutes in a closed gap collapse to the same boundary.  Callers that need
    to reject such a minute must first use :func:`interval_is_productive` or
    :func:`shift_slices`.
    """

    value = int(minute)
    elapsed = 0
    shifts = ordered_shifts(config)
    if not shifts:
        return 0
    for shift in shifts:
        start = int(shift.start_min)
        end = int(shift.end_min)
        if value <= start:
            return elapsed
        if value < end:
            return elapsed + value - start
        elapsed += max(0, end - start)
        if value == end:
            return elapsed
    return elapsed


def productive_offset_to_clock(
    config: FactoryConfig,
    offset: int | float,
    *,
    boundary: Literal["start", "end"] = "start",
) -> int:
    """Map a productive offset back to a wall-clock minute.

    At a boundary separated by a closed gap, a start belongs to the following
    shift while an end belongs to the preceding shift.
    """

    shifts = ordered_shifts(config)
    if not shifts:
        return 0
    target = max(0, min(int(offset), sum(max(0, s.end_min - s.start_min) for s in shifts)))
    elapsed = 0
    for index, shift in enumerate(shifts):
        duration = max(0, int(shift.end_min) - int(shift.start_min))
        next_elapsed = elapsed + duration
        if target < next_elapsed:
            return int(shift.start_min) + target - elapsed
        if target == next_elapsed:
            if boundary == "end" or index == len(shifts) - 1:
                return int(shift.end_min)
            return int(shifts[index + 1].start_min)
        elapsed = next_elapsed
    return int(shifts[-1].end_min)


def merge_clock_intervals(
    intervals: Iterable[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Return the union of valid end-exclusive wall-clock intervals."""

    merged: list[list[int]] = []
    for start, end in sorted((int(start), int(end)) for start, end in intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _minute(value: object, *, field: str, shift_id: str) -> int:
    from backend.validation import strict_int

    try:
        minute = strict_int(value, field)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Turno {shift_id}: {field} inválido.") from exc
    return minute


def normalize_shift_updates(raw_shifts: object) -> list[ShiftConfig]:
    """Normalize public API shift payloads to planner-safe minutes.

    HTML time inputs represent midnight as 00:00, which arrives as minute 0.
    In the factory calendar, a shift ending at midnight means end-of-day 1440.
    Accepting 0 literally makes the turno B look like 15:30→00:00 and causes
    validation/replan rollback. Start times keep 00:00 as minute 0.
    """

    if not isinstance(raw_shifts, list):
        raise ValueError("shifts deve ser uma lista.")

    shifts: list[ShiftConfig] = []
    seen_ids: set[str] = set()
    for raw in raw_shifts:
        if not isinstance(raw, dict):
            raise ValueError("Cada turno deve ser um objeto.")
        shift_id = str(raw.get("id", "")).strip()
        if not shift_id:
            raise ValueError("Turno sem ID.")
        if shift_id in seen_ids:
            raise ValueError(f"Turno repetido: {shift_id}.")
        seen_ids.add(shift_id)

        start_min = _minute(raw.get("start_min"), field="início", shift_id=shift_id)
        end_min = _minute(raw.get("end_min"), field="fim", shift_id=shift_id)
        if not 0 <= start_min < 1440:
            raise ValueError(f"Turno {shift_id}: início deve estar entre 00:00 e 23:59.")
        if not 0 <= end_min <= 1440:
            raise ValueError(f"Turno {shift_id}: fim deve estar entre 00:00 e 24:00.")
        if end_min == 0:
            end_min = 1440
        if end_min <= start_min:
            raise ValueError(f"Turno {shift_id}: início deve ser anterior ao fim.")

        shifts.append(
            ShiftConfig(
                shift_id,
                start_min,
                end_min,
                str(raw.get("label", "")),
            )
        )

    return sorted(shifts, key=lambda shift: (shift.start_min, shift.id))


def clear_legacy_common_machine_capacity_overrides(
    config: object,
    previous_day_capacity_min: int,
) -> None:
    """Drop machine capacity overrides that only duplicated old common shifts.

    Older persisted configs can contain ``day_capacity_min: 1020`` per machine.
    The current product uses one factory calendar; if shifts are edited, those
    old duplicate values must not block validation as stale machine-specific
    capacities.
    """

    for machine in getattr(config, "machines", {}).values():
        if getattr(machine, "day_capacity_min", None) == previous_day_capacity_min:
            machine.day_capacity_min = None
