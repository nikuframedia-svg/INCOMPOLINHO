"""Machines today — Spec 11 §4.1.

5 lines, one per machine. Sorted by utilisation (descending).
"""

from __future__ import annotations

from backend.config.loader import _min_to_time
from backend.config.types import FactoryConfig
from backend.scheduler.types import Segment
from backend.types import EngineData


def _get_client(seg: Segment, engine_data: EngineData) -> str:
    return next((op.client for op in engine_data.ops if op.sku == seg.sku), "")


def compute_machines_today(
    segments: list[Segment],
    engine_data: EngineData,
    config: FactoryConfig,
    day_idx: int = 0,
) -> dict:
    """Return machine summary for a given day.

    Keys: machines (list sorted by -util), total_setups, next_setup.
    """
    day_cap = config.day_capacity_min
    result = []

    for m in engine_data.machines:
        segs = sorted(
            [s for s in segments if s.machine_id == m.id and s.day_idx == day_idx],
            key=lambda s: s.start_min,
        )
        used = sum(s.prod_min + s.setup_min for s in segs)
        util = used / day_cap if day_cap > 0 else 0

        # Tool sequence (no consecutive repeats)
        tools: list[dict] = []
        for s in segs:
            if not tools or tools[-1]["id"] != s.tool_id:
                tools.append({"id": s.tool_id, "client": _get_client(s, engine_data)})

        setup_segs = [s for s in segs if s.setup_min > 0]

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
                "util": round(util, 2),
                "tools": tools,
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
