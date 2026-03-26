"""Phase 5 — Scoring: Spec 02 v6 §7.

KPIs: OTD (lot-level), OTD-D (demand-unit cumulative), tardiness,
earliness, setup count, utilisation per machine.
"""

from __future__ import annotations

from collections import defaultdict

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData


def compute_score(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    config: FactoryConfig | None = None,
) -> dict:
    """Compute all KPIs for a schedule."""

    # Completion day per lot (sentinel must be below any possible day_idx)
    _NO_COMPLETION = -999
    lot_completion: dict[str, int] = {}
    for seg in segments:
        if seg.setup_min > 0 and seg.qty == 0:
            continue
        prev = lot_completion.get(seg.lot_id, _NO_COMPLETION)
        if seg.day_idx > prev:
            lot_completion[seg.lot_id] = seg.day_idx

    # OTD and tardiness
    n_lots = len(lots)
    tardy_count = 0
    max_tardiness = 0
    total_tardiness = 0

    for lot in lots:
        completion = lot_completion.get(lot.id, engine_data.n_days)
        delay = completion - lot.edd

        if delay > 0:
            tardy_count += 1
            total_tardiness += delay
            max_tardiness = max(max_tardiness, delay)

    otd = round((1 - tardy_count / max(n_lots, 1)) * 100, 1)

    # Earliness: average gap between last production day and EDD per run
    by_run: dict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        by_run[seg.run_id].append(seg)

    run_gaps: list[int] = []
    for run_segs in by_run.values():
        last_day = max(s.day_idx for s in run_segs)
        edd = max(s.edd for s in run_segs)
        run_gaps.append(max(0, edd - last_day))

    earliness_avg = round(sum(run_gaps) / max(len(run_gaps), 1), 1)

    # OTD-D: cumulative demand check
    otd_d_failures = _compute_otd_d(segments, lots, engine_data)
    otd_d = 100.0 if otd_d_failures == 0 else round(100 - otd_d_failures, 1)

    # Setups
    setups = sum(1 for s in segments if s.setup_min > 0)

    # Utilisation per machine
    util: dict[str, float] = {}
    for m in engine_data.machines:
        used = sum(
            s.prod_min + s.setup_min
            for s in segments
            if s.machine_id == m.id
        )
        day_cap = config.day_capacity_min if config else DAY_CAP
        total_available = engine_data.n_days * day_cap
        util[m.id] = round(used / total_available * 100, 1) if total_available > 0 else 0.0

    return {
        "otd": otd,
        "otd_d": otd_d,
        "otd_d_failures": otd_d_failures,
        "earliness_avg_days": earliness_avg,
        "setups": setups,
        "utilisation": util,
        "tardy_count": tardy_count,
        "max_tardiness": max_tardiness,
        "total_tardiness": total_tardiness,
        "total_segments": len(segments),
        "total_lots": n_lots,
    }


def _compute_otd_d(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
) -> int:
    """OTD-D: for each op, at each demand day, cum_prod >= cum_demand.

    Returns number of failures.
    """
    # Map lot_id → op_id
    lot_to_op: dict[str, str] = {}
    for lot in lots:
        lot_to_op[lot.id] = lot.op_id

    # Production by (op_id, day)
    prod: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for seg in segments:
        if seg.twin_outputs:
            for oid, sku, qty in seg.twin_outputs:
                prod[oid][seg.day_idx] += qty
        else:
            op_id = lot_to_op.get(seg.lot_id, seg.lot_id)
            prod[op_id][seg.day_idx] += seg.qty

    failures = 0
    for op in engine_data.ops:
        cum_demand = 0
        cum_produced = 0

        # Pre-accumulate production from negative days (buffer unshift)
        op_prod = prod[op.id]
        for neg_day, qty in op_prod.items():
            if neg_day < 0:
                cum_produced += qty

        for day_idx in range(engine_data.n_days):
            demand = op.d[day_idx] if day_idx < len(op.d) else 0
            cum_produced += op_prod.get(day_idx, 0)

            if demand <= 0:
                continue

            cum_demand += demand
            if cum_produced < cum_demand:
                failures += 1

    return failures
