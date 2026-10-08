"""Phase 4 — JIT material-release scheduling.

Goal: a lot cannot start before material release. The reference is customer
delivery for normal output and subcontract dispatch for subcontracted output.
Once released, the lot should start as soon as shared resources allow.

The global solver is preferred because it sees every shared resource.  The
deterministic fallback follows the same release-first policy instead of the
old backward gates that intentionally delayed work to the latest possible
minute.

Kept: compute_lst() and compute_paced_lst() for reference/tests.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP, LST_SAFETY_BUFFER
from backend.scheduler.dispatch import (
    assign_machines,
    per_machine_dispatch,
)
from backend.scheduler.global_jit import solve_global_jit
from backend.scheduler.jit_policy import (
    lot_floor_minutes,
    production_due_day,
)
from backend.scheduler.priority import (
    delivery_is_complete,
    run_priority_key,
)
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment, ToolRun, ToolTimeline
from backend.types import EngineData

logger = logging.getLogger(__name__)

# Minimum slack (days) to consider a run for delay
_MIN_SLACK = 2


def compute_lst(
    run: ToolRun,
    holiday_set: set[int],
    safety_buffer: int = LST_SAFETY_BUFFER,
    config: FactoryConfig | None = None,
) -> int:
    """Compute basic Latest Start Time for a run.

    LST = EDD - days_needed - safety_buffer, skipping holidays.
    """
    day_cap = config.day_capacity_min if config else DAY_CAP
    days_needed = math.ceil(run.total_min / day_cap)
    remaining = days_needed + safety_buffer
    current_day = run.edd

    while remaining > 0 and current_day > 0:
        current_day -= 1
        if current_day not in holiday_set:
            remaining -= 1

    return max(0, current_day)


def compute_paced_lst(
    run: ToolRun,
    holiday_set: set[int],
    safety_buffer: int = LST_SAFETY_BUFFER,
    config: FactoryConfig | None = None,
) -> int:
    """Compute demand-paced LST: tightest constraint from internal lots.

    For each lot in the run, compute: lot.edd - cumulative_days_needed.
    Return min of basic LST and paced LST.
    """
    day_cap = config.day_capacity_min if config else DAY_CAP
    lst_basic = compute_lst(run, holiday_set, safety_buffer, config=config)

    cum_time = run.setup_min
    tightest = run.edd

    for lot in run.lots:
        cum_time += lot.prod_min
        cum_days = math.ceil(cum_time / day_cap)
        latest_for_this = lot.edd - cum_days
        tightest = min(tightest, latest_for_this)

    lst_paced = max(0, tightest)
    return min(lst_basic, lst_paced)


# ─── Compatibility helpers for minute-precise latest starts ───────────


def _subtract_open_minutes(
    end_abs: float,
    duration_min: float,
    holiday_set: set[int],
    day_cap: int,
) -> float:
    """Move backwards by productive minutes on the indexed factory calendar."""

    cursor = float(end_abs)
    remaining = max(0.0, float(duration_min))
    while remaining > 0.001:
        day = math.floor((cursor - 0.001) / day_cap)
        day_start = float(day * day_cap)
        if day in holiday_set:
            cursor = day_start
            continue
        available = max(0.0, cursor - day_start)
        if available <= 0.001:
            cursor = day_start
            continue
        used = min(available, remaining)
        cursor -= used
        remaining -= used
    return cursor


def _latest_run_start_abs(
    run: ToolRun,
    holiday_set: set[int],
    day_cap: int = DAY_CAP,
    reserve_pct: float = 0.0,
    reserve_workdays: int = 0,
) -> float:
    """Latest run start satisfying every lot deadline, to the minute."""

    cumulative = float(run.setup_min)
    latest = float("inf")
    for lot in run.lots:
        cumulative += float(lot.prod_min)
        deadline_end = float((production_due_day(lot, holiday_set) + 1) * day_cap)
        latest = min(
            latest,
            _subtract_open_minutes(
                deadline_end,
                cumulative * (1.0 + max(0.0, reserve_pct))
                + max(0, reserve_workdays) * day_cap,
                holiday_set,
                day_cap,
            ),
        )
    if math.isinf(latest):
        deadline_end = float((run.edd + 1) * day_cap)
        latest = _subtract_open_minutes(
            deadline_end,
            run.total_min,
            holiday_set,
            day_cap,
        )
    return latest


def _max_gate(run: ToolRun, holiday_set: set[int], day_cap: int = DAY_CAP) -> int:
    """Compatibility day index for the minute-precise latest run start."""

    return math.floor(_latest_run_start_abs(run, holiday_set, day_cap) / day_cap)


def _compute_run_timing(
    segments: list[Segment],
) -> tuple[dict[str, int], dict[str, int]]:
    """Extract start/end day per run from baseline segments."""
    run_days: dict[str, list[int]] = defaultdict(list)
    for seg in segments:
        run_days[seg.run_id].append(seg.day_idx)

    run_start: dict[str, int] = {}
    run_end: dict[str, int] = {}
    for run_id, days in run_days.items():
        run_start[run_id] = min(days)
        run_end[run_id] = max(days)

    return run_start, run_end


def _subtract_workdays(from_day: int, workdays: int, holiday_set: set[int]) -> int:
    """Subtract N workdays from a day, skipping holidays."""
    current = from_day
    remaining = workdays
    while remaining > 0 and current > 0:
        current -= 1
        if current not in holiday_set:
            remaining -= 1
    return max(0, current)


def _backward_stack_gates(
    machine_runs: dict[str, list[ToolRun]],
    holiday_set: set[int],
    n_days: int,
    config: FactoryConfig | None = None,
) -> dict[str, float]:
    """Compute per-run gates via backward stacking per machine.

    For each machine (runs in EDD-ascending order):
    - Last run: latest minute that satisfies every internal lot deadline.
    - Each preceding run: latest of its own constraint and the next reservation.
    """
    day_cap = config.day_capacity_min if config else DAY_CAP
    reserve_pct = max(0.0, float(config.jit_buffer_pct)) if config else 0.05
    reserve_workdays = (
        max(0, min(5, int(config.robustness_reserve_workdays))) if config else 0
    )

    gates: dict[str, float] = {}
    for m_id, m_runs in machine_runs.items():
        if not m_runs:
            continue

        next_start_abs: float = float(n_days * day_cap)

        for i in range(len(m_runs) - 1, -1, -1):
            run = m_runs[i]
            mg_abs = _latest_run_start_abs(
                run,
                holiday_set,
                day_cap=day_cap,
                reserve_pct=reserve_pct,
                reserve_workdays=reserve_workdays,
            )
            candidate_abs = _subtract_open_minutes(
                next_start_abs,
                run.total_min * (1.0 + reserve_pct),
                holiday_set,
                day_cap,
            )
            gate_abs = min(mg_abs, candidate_abs)

            gates[run.id] = gate_abs
            next_start_abs = gate_abs

    return gates


def jit_dispatch(
    runs: list[ToolRun],
    engine_data: EngineData,
    baseline_segments: list[Segment],
    baseline_lots: list[Lot],
    baseline_score: dict,
    audit_logger: object | None = None,
    config: FactoryConfig | None = None,
) -> tuple[
    list[Segment],
    list[Lot],
    list[str],
    dict[str, list[ToolRun]] | None,
    dict[str, float] | None,
    dict | None,
]:
    """Schedule from material release with delivery-first run ordering.

    Returns (segments, lots, warnings, machine_runs, gates).
    machine_runs and gates are None when JIT reverts to baseline.
    """
    config = config or FactoryConfig()
    global_diagnostics: dict | None = None
    if config.global_jit_enabled:
        global_result = solve_global_jit(
            runs,
            engine_data,
            config,
            baseline_segments=baseline_segments,
            time_limit_s=config.global_jit_time_limit_s,
        )
        if global_result is not None and global_result.candidate_found:
            return (
                global_result.segments,
                global_result.lots,
                global_result.warnings,
                global_result.machine_runs,
                global_result.run_gates,
                {
                    "solver_status": global_result.solver_status,
                    "feasibility": global_result.feasibility,
                    "global_constructor": True,
                },
            )
        if global_result is not None:
            global_diagnostics = {
                "solver_status": global_result.solver_status,
                # The reason travels with the result: a "no_candidate" status
                # means the valid plan came from the deterministic fallback.
                "feasibility": {
                    **(global_result.feasibility or {}),
                    "fallback_reason": "global_no_candidate",
                },
                "global_constructor": False,
                "fallback_reason": "global_no_candidate",
            }

    day_cap = config.day_capacity_min
    holiday_set = set(getattr(engine_data, "holidays", []))

    # Phase 1: Assign machines (same load balancing)
    jit_machine_runs = assign_machines(runs, engine_data, audit_logger=audit_logger, config=config)

    # Phase 2: deadline sort with deterministic quantity priority.
    for m_id in jit_machine_runs:
        jit_machine_runs[m_id].sort(key=run_priority_key)

    # Material release is the only start gate in the deterministic fallback.
    # Starting at an LST/backward gate made the fallback deliberately leave
    # capacity idle inside the permitted five-day window.
    current_gate: dict[str, float] = {}
    lot_floors = lot_floor_minutes(jit_machine_runs, holiday_set, day_cap)
    gated_count = len(lot_floors)
    logger.info("JIT release-first fallback: %d lot floor(s)", gated_count)

    # Log release floors for auditability.
    if audit_logger:
        for run in runs:
            if not run.lots:
                continue
            floor = min(lot_floors.get(lot.id, 0.0) for lot in run.lots)
            audit_logger.log_gate(run.id, floor, floor, run.edd, "material_release")

    # Phase 4: Dispatch each machine independently with gates.
    # Per-machine dispatch avoids crew serialization blocking gated runs.
    # Crew mutex is enforced in post-processing (_serialize_crew_setups).
    jit_segs: list[Segment] = []
    jit_lots: list[Lot] = []
    jit_warns: list[str] = []
    shared_tool_timeline = ToolTimeline()
    for m_id, m_runs in jit_machine_runs.items():
        m_segs, m_lots, m_warns = per_machine_dispatch(
            {m_id: m_runs},
            engine_data,
            lst_gate=current_gate,
            config=config,
            lot_floors=lot_floors,
            tool_tl=shared_tool_timeline,
        )
        jit_segs.extend(m_segs)
        jit_lots.extend(m_lots)
        jit_warns.extend(m_warns)
    jit_score = compute_score(jit_segs, jit_lots, engine_data, config=config)
    best_jit = (
        jit_segs,
        jit_lots,
        jit_warns,
        dict(current_gate),
        jit_score,
    )

    jit_segs, jit_lots, jit_warns, current_gate, jit_score = best_jit

    # Never revert to an ASAP baseline: it may violate the fixed JIT window.
    # Return the infeasible candidate transparently so the hard gates reject it.
    if not delivery_is_complete(jit_score):
        dispatch_misses = int(jit_score.get("subcontract_dispatch_misses", 0) or 0)
        logger.warning(
            "JIT hard window: best effort has %d late delivery lot(s) and "
            "%d late subcontract dispatch(es)",
            jit_score["tardy_count"],
            dispatch_misses,
        )
        jit_warns.append(
            f"JIT firme: {jit_score['tardy_count']} entrega(s) e "
            f"{dispatch_misses} envio(s) para subcontratação em atraso; "
            "a janela de material de 5 dias úteis não foi relaxada"
        )

    logger.info(
        "JIT v3: earliness %.1f → %.1f days",
        baseline_score.get("earliness_avg_days", 0),
        jit_score.get("earliness_avg_days", 0),
    )

    warnings = [
        f"JIT: {gated_count} lotes com libertação de material, "
        f"antecipação {baseline_score.get('earliness_avg_days', 0):.1f}"
        f" → {jit_score.get('earliness_avg_days', 0):.1f}d",
    ]
    warnings.extend(jit_warns)

    diagnostics = global_diagnostics or {
        "solver_status": "legacy_fallback",
        "feasibility": None,
        "global_constructor": False,
    }
    return jit_segs, jit_lots, warnings, jit_machine_runs, current_gate, diagnostics
