"""Simulator — Spec 04: What-If.

simulate() deepcopies EngineData, applies mutations, re-runs schedule_all(),
and compares BEFORE vs AFTER KPIs.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass

from backend.cpo import optimize
from backend.scheduler.gates import build_gate_report
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.transform.calendars import apply_calendars
from backend.types import EngineData

from .mutations import apply_mutation, reapply_calendar_mutations


@dataclass(slots=True)
class Mutation:
    type: str
    params: dict


@dataclass(slots=True)
class DeltaReport:
    otd_before: float
    otd_after: float
    otd_d_before: float
    otd_d_after: float
    setups_before: int
    setups_after: int
    earliness_before: float
    earliness_after: float
    tardy_before: int
    tardy_after: int
    early_window_before: int = 0
    early_window_after: int = 0
    utilization_before: float = 0.0
    utilization_after: float = 0.0
    subcontract_dispatch_before: int = 0
    subcontract_dispatch_after: int = 0
    subcontract_dispatch_late_workdays_before: int = 0
    subcontract_dispatch_late_workdays_after: int = 0


@dataclass(slots=True)
class SimulateResponse:
    segments: list[Segment]
    lots: list[Lot]
    score: dict
    delta: DeltaReport
    time_ms: float
    summary: list[str]
    gate_report: dict
    warnings: list[str]
    operator_alerts: list
    # Kept internal (the API serializes an explicit public response).  These
    # copies let a separately confirmed scenario become the new reality
    # without replaying mutations against a possibly changed dataset.
    mutated_data: EngineData
    mutated_config: object | None
    improvement_report: dict | None = None


def simulate(
    engine_data: EngineData,
    baseline_score: dict,
    mutations: list[Mutation],
    config=None,
    *,
    baseline_result: ScheduleResult | None = None,
    active_mutations: list[Mutation | dict] | None = None,
) -> SimulateResponse:
    from backend.cpo.optimizer import MODE_CONFIG
    from backend.planning_control import planning_scope

    with planning_scope(timeout_s=float(MODE_CONFIG["normal"]["time_budget_s"])):
        return _simulate(
            engine_data, baseline_score, mutations, config,
            baseline_result=baseline_result, active_mutations=active_mutations,
        )


def _simulate(
    engine_data, baseline_score, mutations, config=None, *, baseline_result=None,
    active_mutations=None,
) -> SimulateResponse:
    """Run what-if simulation.

    1. deepcopy(engine_data)
    2. Apply each mutation
    3. schedule_all(mutated)
    4. Build DeltaReport comparing baseline_score vs new score
    5. Generate Portuguese summary

    ``active_mutations`` contains already-applied mutations; only availability
    overlays are replayed after a calendar rebuild, never demand or overtime.
    ``baseline_result`` enables the shared whole-started-lot preservation path.
    """
    t0 = time.perf_counter()

    # 1. Deep copy data AND config (mutations may modify config.shifts)
    mutated = copy.deepcopy(engine_data)
    sim_config = copy.deepcopy(config) if config else None
    unchanged = baseline_result is not None and not mutations
    calendar_mutations = [
        {"type": mut.type, "params": dict(mut.params)}
        if isinstance(mut, Mutation) else copy.deepcopy(mut)
        for mut in (active_mutations or []) if not unchanged
    ]
    known_operator_blocks: list[dict] = []
    if not unchanged and sim_config is not None and active_mutations is not None:
        apply_calendars(mutated, sim_config)
        operator_count = len(mutated.operator_blocked_intervals)
        reapply_calendar_mutations(mutated, calendar_mutations, sim_config)
        known_operator_blocks = mutated.operator_blocked_intervals[operator_count:]

    # 2. Apply mutations (pass config so third_shift/overtime can modify shifts)
    summaries: list[str] = []
    for mut in mutations:
        from backend.planning_control import planning_checkpoint

        planning_checkpoint()
        operator_count = len(mutated.operator_blocked_intervals)
        msg = apply_mutation(mutated, mut.type, mut.params, config=sim_config)
        summaries.append(msg)
        if mut.type == "operator_shortage":
            known_operator_blocks.extend(mutated.operator_blocked_intervals[operator_count:])
        calendar_mutations.append({"type": mut.type, "params": dict(mut.params)})
        if sim_config is not None and mut.type in {"overtime", "rush_order", "delay_edd"}:
            # Day overlays may coincide with a persistent full-day block that
            # becomes partial after a shift change. Replay known operator
            # overlays once too: defaults follow shifts, explicit times do not.
            for block in known_operator_blocks:
                mutated.operator_blocked_intervals.remove(block)
            operator_count = len(mutated.operator_blocked_intervals)
            reapply_calendar_mutations(mutated, calendar_mutations, sim_config)
            known_operator_blocks = mutated.operator_blocked_intervals[operator_count:]

    # 3. Re-schedule with (possibly modified) config. Simulations use the
    # normal pipeline, not quick, because quick skips repair/optimization passes
    # that are needed to keep physical tool usage valid.
    if unchanged:
        result = copy.deepcopy(baseline_result)
        baseline_score = result.score
        gate_report = copy.deepcopy(result.gate_report or {})
        for key in ("solver_status", "feasibility"):
            value = getattr(result, key)
            if value is not None:
                gate_report.setdefault(key, copy.deepcopy(value))
    else:
        if baseline_result is None:
            result = optimize(mutated, mode="normal", config=sim_config)
        else:
            from backend.plans.frozen import optimize_preserving_started_lots

            result = optimize_preserving_started_lots(
                mutated, sim_config, baseline_result, mode="normal"
            )
        if result.preserved_lot_proofs is not None:
            mutated.preserved_lot_proofs = dict(result.preserved_lot_proofs)
        if not result.lots:
            result.score = compute_score(result.segments, result.lots, mutated, sim_config)
        gate_report = (
            copy.deepcopy(result.gate_report)
            if result.gate_report
            else build_gate_report(
                result.segments,
                result.lots,
                result.score,
                mutated,
                sim_config,
            )
        )
        for key in ("solver_status", "feasibility"):
            value = getattr(result, key)
            if value is not None:
                gate_report.setdefault(key, copy.deepcopy(value))
        if result.gate_report:
            for key in ("solver_status", "feasibility", "solver_trace"):
                if key in result.gate_report:
                    gate_report[key] = result.gate_report[key]

    # 4. Delta report
    delta = DeltaReport(
        otd_before=baseline_score.get("otd", 0.0),
        otd_after=result.score.get("otd", 0.0),
        otd_d_before=baseline_score.get("otd_d", 0.0),
        otd_d_after=result.score.get("otd_d", 0.0),
        setups_before=baseline_score.get("setups", 0),
        setups_after=result.score.get("setups", 0),
        earliness_before=baseline_score.get("earliness_avg_days", 0.0),
        earliness_after=result.score.get("earliness_avg_days", 0.0),
        tardy_before=baseline_score.get("tardy_count", 0),
        tardy_after=result.score.get("tardy_count", 0),
        early_window_before=baseline_score.get("early_window_violations", 0),
        early_window_after=result.score.get("early_window_violations", 0),
        utilization_before=_utilization(baseline_score),
        utilization_after=_utilization(result.score),
        subcontract_dispatch_before=baseline_score.get(
            "subcontract_dispatch_misses", 0
        ),
        subcontract_dispatch_after=result.score.get(
            "subcontract_dispatch_misses", 0
        ),
        subcontract_dispatch_late_workdays_before=baseline_score.get(
            "subcontract_dispatch_late_workdays", 0
        ),
        subcontract_dispatch_late_workdays_after=result.score.get(
            "subcontract_dispatch_late_workdays", 0
        ),
    )

    # 5. Summary
    summaries.append(_delta_summary(delta))

    elapsed = (time.perf_counter() - t0) * 1000

    return SimulateResponse(
        segments=result.segments,
        lots=result.lots,
        score=result.score,
        delta=delta,
        time_ms=round(elapsed, 1),
        summary=summaries,
        gate_report=gate_report,
        warnings=list(result.warnings),
        operator_alerts=list(result.operator_alerts),
        mutated_data=mutated,
        mutated_config=sim_config,
        improvement_report=copy.deepcopy(result.improvement_report),
    )


def _utilization(score: dict) -> float:
    capacity = float(score.get("available_capacity_min", 0) or 0)
    return 100.0 * float(score.get("work_time_min", 0) or 0) / capacity if capacity > 0 else 0.0


def _delta_summary(delta: DeltaReport) -> str:
    """Generate Portuguese summary of KPI changes."""
    parts: list[str] = []

    otd_diff = delta.otd_after - delta.otd_before
    if abs(otd_diff) > 0.05:
        direction = "subiu" if otd_diff > 0 else "desceu"
        parts.append(
            f"OTD {direction} {abs(otd_diff):.1f}% "
            f"({delta.otd_before:.1f}% → {delta.otd_after:.1f}%)"
        )

    otd_d_diff = delta.otd_d_after - delta.otd_d_before
    if abs(otd_d_diff) > 0.05:
        direction = "subiu" if otd_d_diff > 0 else "desceu"
        parts.append(f"OTD-D {direction} {abs(otd_d_diff):.1f}%")

    setup_diff = delta.setups_after - delta.setups_before
    if setup_diff != 0:
        direction = "+" if setup_diff > 0 else ""
        parts.append(
            f"Setups: {direction}{setup_diff} ({delta.setups_before} → {delta.setups_after})"
        )

    tardy_diff = delta.tardy_after - delta.tardy_before
    if tardy_diff != 0:
        direction = "+" if tardy_diff > 0 else ""
        parts.append(
            f"Atrasos: {direction}{tardy_diff} ({delta.tardy_before} → {delta.tardy_after})"
        )

    dispatch_diff = (
        delta.subcontract_dispatch_after - delta.subcontract_dispatch_before
    )
    if dispatch_diff != 0:
        direction = "+" if dispatch_diff > 0 else ""
        parts.append(
            "Envios de subcontratação em atraso: "
            f"{direction}{dispatch_diff} "
            f"({delta.subcontract_dispatch_before} → "
            f"{delta.subcontract_dispatch_after})"
        )

    if not parts:
        return "Sem alterações significativas nos KPIs."

    return "Resumo: " + "; ".join(parts) + "."
