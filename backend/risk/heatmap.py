"""Heatmap — Spec 06 §3.

Grid: machines × days. Each cell: utilisation + min slack of active lots.
"""

from __future__ import annotations

from collections import defaultdict

from backend.calendar import available_machine_capacity
from backend.config.types import FactoryConfig
from backend.scheduler.types import Segment
from backend.types import EngineData

from .types import HeatmapCell, LotRisk


def compute_heatmap(
    segments: list[Segment],
    lot_risks: list[LotRisk],
    engine_data: EngineData,
    config: FactoryConfig | None = None,
) -> list[HeatmapCell]:
    """Build risk heatmap grid.

    Risk levels:
      low:      util < 0.70 AND slack > 1440 min (24h)
      medium:   util 0.70-0.85 OR slack 480-1440 min
      high:     util 0.85-0.95 OR slack 120-480 min
      critical: util > 0.95 OR slack < 120 min (2h)
    """
    # Utilisation per (machine, day)
    used: dict[tuple[str, int], float] = defaultdict(float)
    for seg in segments:
        used[(seg.machine_id, seg.day_idx)] += seg.prod_min + seg.setup_min

    # Min slack per (machine, day) from lot risks
    risk_by_lot: dict[str, LotRisk] = {lr.lot_id: lr for lr in lot_risks}
    min_slack: dict[tuple[str, int], float] = {}
    for seg in segments:
        lr = risk_by_lot.get(seg.lot_id)
        if lr:
            key = (seg.machine_id, seg.day_idx)
            if key not in min_slack or lr.slack_min < min_slack[key]:
                min_slack[key] = lr.slack_min

    cells: list[HeatmapCell] = []
    for m in engine_data.machines:
        for d in range(engine_data.n_days):
            day_cap = available_machine_capacity(m.id, d, engine_data, config)
            load = used.get((m.id, d), 0)
            util = load / day_cap if day_cap > 0 else None if load > 0 else 0.0
            slack = min_slack.get((m.id, d), -1.0)

            if util is None or util > 0.95 or (slack >= 0 and slack < 120):
                level = "critical"
            elif util > 0.85 or (slack >= 0 and slack < 480):
                level = "high"
            elif util > 0.70 or (slack >= 0 and slack < 1440):
                level = "medium"
            else:
                level = "low"

            cells.append(
                HeatmapCell(
                    machine_id=m.id,
                    day_idx=d,
                    utilization=round(util, 3) if util is not None else None,
                    load_min=round(load, 1),
                    capacity_min=round(day_cap, 1),
                    min_slack_min=round(slack, 1),
                    risk_level=level,
                )
            )

    return cells
