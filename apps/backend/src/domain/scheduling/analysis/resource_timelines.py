"""Resource Timelines — per-resource per-day-per-shift capacity maps.

Port of failures/failure-timeline.ts.
Converts FailureEvent[] into capacity timelines for machines and tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..constants import DAY_CAP, S0, S1, T1


@dataclass
class DayShiftCapacity:
    status: str = "running"  # "running" | "down" | "partial" | "degraded"
    capacity_factor: float = 1.0
    failure_ids: list[str] = field(default_factory=list)


# ResourceTimeline = list of day entries, each is dict of shift → DayShiftCapacity
# e.g. timelines[day_idx]["X"] = DayShiftCapacity(...)

SHIFTS_2 = ("X", "Y")
SHIFTS_3 = ("X", "Y", "Z")


def build_resource_timelines(
    failures: list[dict[str, Any]],
    n_days: int,
    third_shift: bool = False,
) -> dict[str, Any]:
    """Build per-resource per-day-per-shift capacity maps from failure events.

    Args:
        failures: List of FailureEvent dicts with keys:
            id, resourceType ("machine"|"tool"), resourceId,
            startDay, endDay, shift (optional), capacityFactor
        n_days: Planning horizon
        third_shift: Include Z shift (00:00-07:00)

    Returns:
        {
            "machine_timelines": {machine_id: [{shift: DayShiftCapacity}, ...]},
            "tool_timelines": {tool_id: [{shift: DayShiftCapacity}, ...]},
        }
    """
    shifts = SHIFTS_3 if third_shift else SHIFTS_2

    machine_timelines: dict[str, list[dict[str, DayShiftCapacity]]] = {}
    tool_timelines: dict[str, list[dict[str, DayShiftCapacity]]] = {}

    def _get_timeline(
        store: dict[str, list[dict[str, DayShiftCapacity]]],
        resource_id: str,
    ) -> list[dict[str, DayShiftCapacity]]:
        if resource_id not in store:
            store[resource_id] = [
                {s: DayShiftCapacity() for s in shifts} for _ in range(n_days)
            ]
        return store[resource_id]

    for failure in failures:
        fid = failure.get("id", "")
        resource_type = failure.get("resourceType", failure.get("resource_type", "machine"))
        resource_id = failure.get("resourceId", failure.get("resource_id", ""))
        start_day = failure.get("startDay", failure.get("start_day", 0))
        end_day = failure.get("endDay", failure.get("end_day", start_day))
        cap_factor = failure.get("capacityFactor", failure.get("capacity_factor", 0.0))
        failure_shift = failure.get("shift")  # Optional: restrict to specific shift

        store = machine_timelines if resource_type == "machine" else tool_timelines
        timeline = _get_timeline(store, resource_id)

        # Clamp to horizon
        start_day = max(0, start_day)
        end_day = min(end_day, n_days - 1)

        for day_idx in range(start_day, end_day + 1):
            if day_idx >= len(timeline):
                break

            for shift_id in shifts:
                # If failure specifies a shift, only affect that shift
                if failure_shift and shift_id != failure_shift:
                    continue

                slot = timeline[day_idx][shift_id]
                # Take minimum capacity (worst case for overlapping failures)
                slot.capacity_factor = min(slot.capacity_factor, cap_factor)
                if fid and fid not in slot.failure_ids:
                    slot.failure_ids.append(fid)
                # Derive status
                slot.status = _factor_to_status(slot.capacity_factor)

    # Convert to serializable dicts
    return {
        "machine_timelines": _serialize_timelines(machine_timelines),
        "tool_timelines": _serialize_timelines(tool_timelines),
    }


def _factor_to_status(factor: float) -> str:
    if factor <= 0:
        return "down"
    if factor < 0.7:
        return "partial"
    if factor < 1.0:
        return "degraded"
    return "running"


def _serialize_timelines(
    store: dict[str, list[dict[str, DayShiftCapacity]]],
) -> dict[str, list[dict[str, dict]]]:
    result: dict[str, list[dict[str, dict]]] = {}
    for resource_id, timeline in store.items():
        result[resource_id] = [
            {
                shift_id: {
                    "status": slot.status,
                    "capacity_factor": slot.capacity_factor,
                    "failure_ids": slot.failure_ids,
                }
                for shift_id, slot in day.items()
            }
            for day in timeline
        ]
    return result
