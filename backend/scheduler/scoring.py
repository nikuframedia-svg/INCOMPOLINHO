"""Phase 5 — Scoring: Spec 02 v6 §7.

KPIs: OTD (lot-level), OTD-D (demand-unit cumulative), tardiness,
earliness, setup count, utilisation per machine.
"""

from __future__ import annotations

from collections import defaultdict

from backend.calendar import available_machine_capacity
from backend.config.shifts import clock_to_productive_offset
from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.jit_policy import (
    add_workdays,
    calendar_holidays,
    expedition_day,
    lot_demand_output_milestones,
    lot_output_milestones,
    material_reference_day,
    production_due_day,
    productive_start_days,
    window_violation_details,
    workdays_between,
)
from backend.scheduler.operational_audit import build_operational_audit
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import coverage_metrics, validate_plan_metrics
from backend.types import EngineData


def compute_score(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    config: FactoryConfig | None = None,
    *,
    include_operational_audit: bool = True,
    operational_audit: dict | None = None,
) -> dict:
    """Compute all KPIs for a schedule.

    Candidate-repair loops may skip the expensive operational audit because
    they validate the proposed move directly. Public/final scores keep the
    audit enabled so the score contract and acceptance gate remain complete.
    """

    # Completion day per lot (sentinel must be below any possible day_idx)
    _NO_COMPLETION = -999
    lot_completion: dict[str, int] = {}
    lot_start: dict[str, int] = productive_start_days(segments)
    for seg in segments:
        if seg.setup_min > 0 and seg.qty == 0:
            continue
        prev = lot_completion.get(seg.lot_id, _NO_COMPLETION)
        if seg.day_idx > prev:
            lot_completion[seg.lot_id] = seg.day_idx

    min_calendar_day = min(
        [
            *(segment.day_idx for segment in segments),
            *(
                lot.material_release_day
                for lot in lots
                if lot.material_release_day is not None
            ),
            0,
        ]
    )
    max_external_lead = max(
        (
            int(output.get("subcontract_lead_time_days", 0) or 0)
            for lot in lots
            for output in lot_output_milestones(lot)
        ),
        default=0,
    )
    holiday_set = calendar_holidays(
        engine_data,
        min_calendar_day - 14,
        engine_data.n_days + max_external_lead * 2 + 14,
    )

    # OTD and tardiness
    n_lots = len(lots)
    tardy_count = 0
    max_tardiness = 0
    total_tardiness = 0
    priority_tardy_count = 0
    priority_tardy_weight = 0
    priority_tardiness_weighted = 0
    production_due_misses = 0
    production_due_late_workdays = 0
    subcontract_dispatch_total = 0
    subcontract_dispatch_misses = 0
    subcontract_dispatch_late_workdays = 0
    subcontract_dispatch_max_late_workdays = 0

    for lot in lots:
        completion = lot_completion.get(lot.id, engine_data.n_days)
        output_delays = [
            _customer_delay_for_output(output, completion, holiday_set)
            for output in lot_demand_output_milestones(lot)
        ]
        delay = max(output_delays, default=completion - expedition_day(lot))

        if delay > 0:
            tardy_count += 1
            total_tardiness += delay
            max_tardiness = max(max_tardiness, delay)
            priority = max(0, int(lot.planning_priority or 0))
            if priority > 0:
                priority_tardy_count += 1
                priority_tardy_weight += priority
                priority_tardiness_weighted += priority * delay

        controllable_due = production_due_day(lot, holiday_set)
        if completion > controllable_due:
            production_due_misses += 1
            production_due_late_workdays += workdays_between(
                controllable_due,
                completion,
                holiday_set,
            )

        for output in lot_demand_output_milestones(lot):
            if not bool(output.get("is_subcontracted")):
                continue
            subcontract_dispatch_total += 1
            dispatch_day = output.get("subcontract_dispatch_day")
            if dispatch_day is None:
                dispatch_day = output.get("production_due_day", controllable_due)
            dispatch_day = int(dispatch_day)
            if completion <= dispatch_day:
                continue
            late_workdays = workdays_between(
                dispatch_day,
                completion,
                holiday_set,
            )
            subcontract_dispatch_misses += 1
            subcontract_dispatch_late_workdays += late_workdays
            subcontract_dispatch_max_late_workdays = max(
                subcontract_dispatch_max_late_workdays,
                late_workdays,
            )

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
    otd_d_metrics = _compute_otd_d(segments, lots, engine_data, holiday_set)

    # Setups
    setups = len({s.run_id for s in segments if s.setup_min > 0})
    setup_time_min = round(sum(s.setup_min for s in segments), 1)
    prod_time_min = round(sum(s.prod_min for s in segments), 1)
    work_time_min = round(setup_time_min + prod_time_min, 1)
    temporal_day_capacity = config.day_capacity_min if config else DAY_CAP
    production_time_cost = 0.0
    for segment in segments:
        productive_minutes = max(0.0, float(segment.prod_min))
        if productive_minutes <= 0:
            continue
        offset = (
            clock_to_productive_offset(config, segment.start_min)
            if config is not None
            else max(0.0, float(segment.start_min) - 420)
        )
        productive_start = (
            int(segment.day_idx) * temporal_day_capacity
            + offset
            + max(0.0, float(segment.setup_min))
        )
        production_time_cost += (
            productive_minutes * productive_start
            + productive_minutes * productive_minutes / 2.0
        )

    # Utilisation per machine
    util: dict[str, float] = {}
    machine_work_min: dict[str, float] = {}
    day_cap = config.day_capacity_min if config else DAY_CAP
    available_capacity_min = 0
    for m in engine_data.machines:
        used = sum(s.prod_min + s.setup_min for s in segments if s.machine_id == m.id)
        machine_work_min[m.id] = round(used, 1)
        total_available = sum(
            available_machine_capacity(m.id, day_idx, engine_data, config)
            for day_idx in range(engine_data.n_days)
        )
        available_capacity_min += total_available
        util[m.id] = round(used / total_available * 100, 1) if total_available > 0 else 0.0
    idle_capacity_min = round(max(0.0, available_capacity_min - work_time_min), 1)
    bottleneck_machine = ""
    if machine_work_min:
        bottleneck_machine = max(machine_work_min, key=machine_work_min.get)

    violations, physical_metrics = validate_plan_metrics(
        segments,
        engine_data,
        config,
        lots=lots,
    )
    hard_violation_count = len(violations)
    coverage = coverage_metrics(segments, lots)

    # Fixed JIT-window compliance, measured from each material reference.
    window_violations = window_violation_details(segments, lots, holiday_set)
    early_window_violations = len(window_violations)
    early_window_violation_days = sum(
        int(item["excess_workdays"]) for item in window_violations
    )
    start_anticipations = [
        workdays_between(start_day, material_reference_day(lot, holiday_set), holiday_set)
        for lot in lots
        if (start_day := lot_start.get(lot.id)) is not None
    ]
    start_anticipation_avg = round(
        sum(start_anticipations) / max(len(start_anticipations), 1),
        2,
    )
    start_anticipation_max = max(start_anticipations, default=0)

    first_segments: dict[str, Segment] = {}
    for segment in segments:
        if segment.prod_min <= 0:
            continue
        previous = first_segments.get(segment.lot_id)
        current_key = (segment.day_idx, segment.start_min)
        previous_key = (
            (previous.day_idx, previous.start_min) if previous is not None else None
        )
        if previous_key is None or current_key < previous_key:
            first_segments[segment.lot_id] = segment

    latest_start_gaps: list[float] = []
    for lot in lots:
        first = first_segments.get(lot.id)
        if first is None:
            continue
        offset = (
            clock_to_productive_offset(config, first.start_min)
            if config is not None
            else max(0, first.start_min - 420)
        )
        actual_start_abs = first.day_idx * day_cap + offset + max(
            0.0,
            first.setup_min,
        )
        latest_start_abs = _latest_productive_start_abs(
            lot,
            holiday_set,
            day_cap,
        )
        latest_start_gaps.append(max(0.0, latest_start_abs - actual_start_abs))

    latest_start_gap_avg = round(
        sum(latest_start_gaps) / max(len(latest_start_gaps), 1),
        1,
    )
    latest_start_gap_max = round(max(latest_start_gaps, default=0.0), 1)
    # Operational quality is part of the score contract. In particular, a
    # partial legal gap must not disappear merely because explainability has
    # not yet annotated the candidate being inspected.
    audit_result = (
        operational_audit
        if operational_audit is not None
        else build_operational_audit(
            segments,
            lots,
            engine_data,
            config,
        )
        if include_operational_audit
        else {
            "left_shift_opportunities": 0,
            "lower_priority_campaign_interruptions": 0,
            "priority_order_anomalies": 0,
            "avoidable_priority_order_anomalies": 0,
            "released_tool_priority_inversions": 0,
        }
    )

    return {
        "otd": otd,
        **otd_d_metrics,
        "early_window_violations": early_window_violations,
        "early_window_violation_days": early_window_violation_days,
        "early_window_violation_workdays": early_window_violation_days,
        "start_anticipation_avg_workdays": start_anticipation_avg,
        "start_anticipation_max_workdays": start_anticipation_max,
        "latest_start_gap_avg_min": latest_start_gap_avg,
        "latest_start_gap_max_min": latest_start_gap_max,
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
        "production_due_misses": production_due_misses,
        "production_due_late_workdays": production_due_late_workdays,
        "subcontract_dispatch_total": subcontract_dispatch_total,
        "subcontract_dispatch_misses": subcontract_dispatch_misses,
        "subcontract_dispatch_late_workdays": subcontract_dispatch_late_workdays,
        "subcontract_dispatch_max_late_workdays": (
            subcontract_dispatch_max_late_workdays
        ),
        "subcontract_dispatch_otd": round(
            100.0
            * (
                1
                - subcontract_dispatch_misses
                / max(subcontract_dispatch_total, 1)
            ),
            1,
        ),
        "priority_tardy_count": priority_tardy_count,
        "priority_tardy_weight": priority_tardy_weight,
        "priority_tardiness_weighted": priority_tardiness_weighted,
        "max_tardiness": max_tardiness,
        "total_tardiness": total_tardiness,
        "total_segments": len(segments),
        "total_lots": n_lots,
        "production_time_cost": round(production_time_cost, 3),
        "sku_start_violations": start_late_count,
        "sku_start_late_days": start_late_days,
        "sku_finish_violations": finish_late_count,
        "sku_finish_late_days": finish_late_days,
        "economic_warning_count": economic_warning_count,
        "planning_penalty": round(planning_penalty, 1),
        "left_shift_opportunities": audit_result["left_shift_opportunities"],
        "lower_priority_campaign_interruptions": audit_result[
            "lower_priority_campaign_interruptions"
        ],
        "priority_order_anomalies": audit_result["priority_order_anomalies"],
        "avoidable_priority_order_anomalies": audit_result[
            "avoidable_priority_order_anomalies"
        ],
        "released_tool_priority_inversions": audit_result[
            "released_tool_priority_inversions"
        ],
        "hard_violations": hard_violation_count
        + int(coverage["missing_lots"] > 0)
        + int(coverage["missing_qty"] > 0)
        + int(coverage["unexpected_lots"] > 0)
        + int(coverage["overproduced_qty"] > 0)
        + int(coverage["duplicate_twin_output_qty"] > 0)
        + int(coverage["twin_output_mismatches"] > 0),
        **coverage,
        **physical_metrics,
    }


def _latest_productive_start_abs(
    lot: Lot,
    holidays: set[int],
    day_capacity_min: int,
) -> float:
    """Resource-independent latest start that can finish by the lot deadline."""

    day = production_due_day(lot, holidays)
    while day in holidays:
        day -= 1
    remaining = max(0.0, float(lot.prod_min))
    available = float(day_capacity_min)
    while remaining > available:
        remaining -= available
        day -= 1
        while day in holidays:
            day -= 1
        available = float(day_capacity_min)
    return day * day_capacity_min + available - remaining


def _compute_otd_d(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    holidays: set[int],
) -> dict[str, int | float]:
    """OTD-D: for each op, at each demand day, cum_prod >= cum_demand.

    Returns a bounded percentage plus explicit checkpoint and quantity deficits.
    """
    lots_by_id = {lot.id: lot for lot in lots}
    output_by_lot_op = {
        (lot.id, str(output.get("op_id", lot.op_id))): output
        for lot in lots
        for output in lot_output_milestones(lot)
    }

    # Production by (op_id, day)
    prod: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    subcontracted_qty: dict[tuple[str, str], int] = defaultdict(int)
    subcontracted_completion: dict[tuple[str, str], int] = {}
    for seg in segments:
        if seg.twin_outputs:
            for oid, _sku, qty in seg.twin_outputs:
                output = output_by_lot_op.get((seg.lot_id, oid), {})
                if bool(output.get("is_subcontracted")):
                    key = (seg.lot_id, oid)
                    subcontracted_qty[key] += qty
                    subcontracted_completion[key] = max(
                        subcontracted_completion.get(key, seg.day_idx),
                        seg.day_idx,
                    )
                else:
                    prod[oid][seg.day_idx] += qty
        else:
            lot = lots_by_id.get(seg.lot_id)
            op_id = lot.op_id if lot is not None else seg.lot_id
            output = output_by_lot_op.get((seg.lot_id, op_id), {})
            if bool(output.get("is_subcontracted")):
                key = (seg.lot_id, op_id)
                subcontracted_qty[key] += seg.qty
                subcontracted_completion[key] = max(
                    subcontracted_completion.get(key, seg.day_idx),
                    seg.day_idx,
                )
            else:
                prod[op_id][seg.day_idx] += seg.qty
    for key, qty in subcontracted_qty.items():
        lot_id, op_id = key
        output = output_by_lot_op.get(key, {})
        ready_day = add_workdays(
            subcontracted_completion[key],
            int(output.get("subcontract_lead_time_days", 0) or 0),
            holidays,
        )
        prod[op_id][ready_day] += qty
    for supply in engine_data.committed_supplies:
        prod[supply.op_id][supply.available_day] += supply.qty

    failures = 0
    checkpoints = 0
    cumulative_shortfall_qty = 0
    final_shortfall_qty = 0
    daily_shortfall_qty = [0] * engine_data.n_days
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

            checkpoints += 1
            cum_demand += demand
            if cum_produced < cum_demand:
                failures += 1
                shortfall = cum_demand - cum_produced
                cumulative_shortfall_qty += shortfall
                daily_shortfall_qty[day_idx] += shortfall

        final_shortfall_qty += max(0, cum_demand - cum_produced)

    passed = max(0, checkpoints - failures)
    otd_d = 100.0 if checkpoints == 0 else round(100.0 * passed / checkpoints, 1)
    return {
        "otd_d": min(100.0, max(0.0, otd_d)),
        "otd_d_daily_shortfall_qty": daily_shortfall_qty,
        "otd_d_checkpoints": checkpoints,
        "otd_d_failures": failures,
        "otd_d_cumulative_shortfall_qty": cumulative_shortfall_qty,
        "otd_d_final_shortfall_qty": final_shortfall_qty,
    }


def _customer_delay_for_output(
    output: dict[str, object],
    production_completion_day: int,
    holidays: set[int],
) -> int:
    customer_day = int(output.get("customer_delivery_day", production_completion_day))
    ready_day = int(production_completion_day)
    if bool(output.get("is_subcontracted")):
        ready_day = add_workdays(
            ready_day,
            int(output.get("subcontract_lead_time_days", 0) or 0),
            holidays,
        )
    return ready_day - customer_day
