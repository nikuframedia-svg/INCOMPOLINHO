"""Machines today — Spec 11 §4.1.

5 lines, one per machine. Sorted by utilisation (descending).
"""

from __future__ import annotations

from backend.calendar import available_machine_capacity
from backend.config.loader import _min_to_time
from backend.config.types import FactoryConfig
from backend.scheduler.types import Segment
from backend.types import EngineData


def _get_client(seg: Segment, engine_data: EngineData) -> str:
    return next((op.client for op in engine_data.ops if op.sku == seg.sku), "")


def _planned_current_end(segs: list[Segment]) -> int | None:
    """End of the first planned production block, including split shifts."""

    if not segs:
        return None
    first = segs[0]
    end_min = first.end_min
    for seg in segs[1:]:
        same_production = (
            seg.sku == first.sku
            and seg.tool_id == first.tool_id
            and seg.run_id == first.run_id
            and seg.lot_id == first.lot_id
        )
        if not same_production or seg.start_min != end_min:
            break
        end_min = seg.end_min
    return end_min


def compute_machines_today(
    segments: list[Segment],
    engine_data: EngineData,
    config: FactoryConfig,
    day_idx: int = 0,
) -> dict:
    """Return machine summary for a given day.

    Keys: machines (list sorted by -util), total_setups, next_setup.
    """
    result = []

    for m in engine_data.machines:
        observed = next(
            (
                item
                for item in engine_data.current_machine_states
                if item.machine_id == m.id
            ),
            None,
        )
        segs = sorted(
            [s for s in segments if s.machine_id == m.id and s.day_idx == day_idx],
            key=lambda s: s.start_min,
        )
        used = sum(s.prod_min + s.setup_min for s in segs)
        capacity = available_machine_capacity(m.id, day_idx, engine_data, config)
        util = used / capacity if capacity > 0 else 0

        # Tool sequence (no consecutive repeats)
        tools: list[dict] = []
        for s in segs:
            if not tools or tools[-1]["id"] != s.tool_id:
                tools.append({"id": s.tool_id, "client": _get_client(s, engine_data)})

        setup_segs = [s for s in segs if s.setup_min > 0]
        runs = [
            {
                "run_id": s.run_id,
                "lot_id": s.lot_id,
                "tool_id": s.tool_id,
                "sku": s.sku,
                "qty": s.qty,
                "prod_min": round(s.prod_min, 1),
                "setup_min": round(s.setup_min, 1),
                "start_min": s.start_min,
                "end_min": s.end_min,
                "start": _min_to_time(s.start_min),
                "end": _min_to_time(s.end_min),
                "shift": s.shift,
                "is_continuation": s.is_continuation,
            }
            for s in segs
        ]

        # Next setup (first with start_min > shift_a_start)
        next_setup = None
        for s in setup_segs:
            prev_tool = None
            idx = segs.index(s)
            if idx > 0:
                prev_tool = segs[idx - 1].tool_id
            next_setup = {
                "time": _min_to_time(s.start_min),
                "from_tool": prev_tool,
                "to_tool": s.tool_id,
                "duration_min": round(s.setup_min, 1),
                "machine": m.id,
            }
            break  # only the first

        result.append(
            {
                "id": m.id,
                "group": config.machine_groups.get(m.id, m.group),
                "util": round(util, 2),
                "capacity_min": capacity,
                "tools": tools,
                "runs": runs,
                "current_state": observed.status if observed and day_idx == 0 else None,
                "current_sku": (
                    observed.sku
                    if observed and day_idx == 0 and observed.status == "producing"
                    else (segs[0].sku if segs else None)
                ),
                "current_tool": (
                    observed.tool_id
                    if observed and day_idx == 0 and observed.tool_id
                    else (tools[0]["id"] if tools else None)
                ),
                "eta_current": (
                    observed.expected_end
                    if observed and day_idx == 0 and observed.expected_end
                    else _planned_current_end(segs)
                ),
                "total_pcs": sum(s.qty for s in segs),
                "setup_count": len(setup_segs),
                "next_setup": next_setup,
            }
        )

    total_setups = sum(m["setup_count"] for m in result)
    next_global = min(
        (m["next_setup"] for m in result if m["next_setup"]),
        key=lambda s: s["time"],
        default=None,
    )

    return {
        "machines": sorted(result, key=lambda m: -m["util"]),
        "total_setups": total_setups,
        "next_setup": next_global,
    }
