"""Phase 5 — Scoring: Spec 02 v6 §7.

KPIs: OTD (lot-level), OTD-D (demand-unit cumulative), tardiness,
earliness, setup count, utilisation per machine.
"""

from __future__ import annotations

from collections import defaultdict

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import validate_plan_metrics
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
    lot_start: dict[str, int] = {}
    for seg in segments:
        if seg.setup_min > 0 and seg.qty == 0:
            continue
        lot_start[seg.lot_id] = min(lot_start.get(seg.lot_id, seg.day_idx), seg.day_idx)
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

    start_late_count = 0
    start_late_days = 0
    finish_late_count = 0
    finish_late_days = 0
    economic_warning_count = 0
    for lot in lots:
        completion = lot_completion.get(lot.id, engine_data.n_days)
        start_day = lot_start.get(lot.id, completion)
        if lot.target_start_day is not None and start_day > lot.target_start_day:
            start_late_count += 1
            start_late_days += start_day - lot.target_start_day
        if lot.internal_deadline is not None and completion > lot.internal_deadline:
            finish_late_count += 1
            finish_late_days += completion - lot.internal_deadline
        if lot.economic_warning:
            economic_warning_count += 1

    planning_penalty = (
        start_late_days * 2.0
        + finish_late_days * 25.0
        + economic_warning_count * 0.5
    )

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
    setup_time_min = round(sum(s.setup_min for s in segments), 1)
    prod_time_min = round(sum(s.prod_min for s in segments), 1)
    work_time_min = round(setup_time_min + prod_time_min, 1)

    # Utilisation per machine
    util: dict[str, float] = {}
    machine_work_min: dict[str, float] = {}
    day_cap = config.day_capacity_min if config else DAY_CAP
    n_holidays = len(set(getattr(engine_data, "holidays", []) or []))
    for m in engine_data.machines:
        used = sum(s.prod_min + s.setup_min for s in segments if s.machine_id == m.id)
        machine_work_min[m.id] = round(used, 1)
        total_available = (engine_data.n_days - n_holidays) * day_cap
        util[m.id] = round(used / total_available * 100, 1) if total_available > 0 else 0.0
    available_capacity_min = max(
        0,
        len(engine_data.machines) * (engine_data.n_days - n_holidays) * day_cap,
    )
    idle_capacity_min = round(max(0.0, available_capacity_min - work_time_min), 1)
    bottleneck_machine = ""
    if machine_work_min:
        bottleneck_machine = max(machine_work_min, key=machine_work_min.get)

    violations, physical_metrics = validate_plan_metrics(segments, engine_data, config)

    # Materials-window compliance (earliness_policy="window")
    early_window_violations = 0
    early_window_violation_days = 0
    if config is not None and getattr(config, "earliness_policy", "jit") == "window":
        holiday_set = set(getattr(engine_data, "holidays", []))
        release_days = config.material_release_days
        for lot in lots:
            start_day = lot_start.get(lot.id)
            if start_day is None:
                continue
            floor_day = _floor_day(lot.edd, release_days, holiday_set)
            if start_day < floor_day:
                early_window_violations += 1
                early_window_violation_days += floor_day - start_day

    return {
        "otd": otd,
        "otd_d": otd_d,
        "otd_d_failures": otd_d_failures,
        "early_window_violations": early_window_violations,
        "early_window_violation_days": early_window_violation_days,
        "earliness_avg_days": earliness_avg,
        "setups": setups,
        "setup_time_min": setup_time_min,
        "prod_time_min": prod_time_min,
        "work_time_min": work_time_min,
        "available_capacity_min": available_capacity_min,
        "idle_capacity_min": idle_capacity_min,
        "machine_work_min": machine_work_min,
        "bottleneck_machine": bottleneck_machine,
        "utilisation": util,
        "tardy_count": tardy_count,
        "max_tardiness": max_tardiness,
        "total_tardiness": total_tardiness,
        "total_segments": len(segments),
        "total_lots": n_lots,
        "sku_start_violations": start_late_count,
        "sku_start_late_days": start_late_days,
        "sku_finish_violations": finish_late_count,
        "sku_finish_late_days": finish_late_days,
        "economic_warning_count": economic_warning_count,
        "planning_penalty": round(planning_penalty, 1),
        "hard_violations": len(violations),
        **physical_metrics,
    }


def _floor_day(edd: int, release_days: int, holiday_set: set[int]) -> int:
    """Earliest allowed day: edd − N workdays, skipping holidays.

    Local copy of window._subtract_workdays — scoring cannot import jit/window
    (both import compute_score; would be circular).
    """
    current = edd
    remaining = release_days
    while remaining > 0 and current > 0:
        current -= 1
        if current not in holiday_set:
            remaining -= 1
    return max(0, current)


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
