"""Schedule helpers — solve-and-analyze, mutations, delta computation, shared models.

Extracted from schedule.py to keep route handlers lean.
"""

from __future__ import annotations

import copy
from typing import Any

from ...core.logging import get_logger
from ...domain.nikufra.utils import nikufra_to_plan_state as _nikufra_to_plan_state
from ...domain.scheduling.analysis.cap_analysis import cap_analysis
from ...domain.scheduling.analysis.coverage_audit import audit_coverage
from ...domain.scheduling.analysis.late_delivery_analysis import analyze_late_deliveries
from ...domain.scheduling.analysis.score_schedule import score_schedule
from ...domain.scheduling.analysis.validate_schedule import validate_schedule
from ...domain.scheduling.transform import transform_plan_state
from ...domain.solver.bridge import engine_data_to_solver_request, solver_result_to_blocks
from ...domain.solver.post_solve import build_decisions, build_feasibility_report
from ...domain.solver.router_logic import SolverRouter

logger = get_logger(__name__)


def _get_solver() -> SolverRouter:
    """Create a fresh SolverRouter per request for thread safety."""
    return SolverRouter()


# ── Serialization helper ─────────────────────────────────────


def _to_dict(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(obj)
    return obj


# ── Core solve + analytics ───────────────────────────────────


def _solve_and_analyze(
    nikufra_data: dict[str, Any],
    settings_dict: dict[str, Any],
    solver_config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Transform → CP-SAT solve → analytics. Returns full response dict."""
    order_based = settings_dict.get("orderBased", True)
    demand_semantics = settings_dict.get("demandSemantics", "raw_np")

    plan_state = _nikufra_to_plan_state(nikufra_data)
    engine_data = transform_plan_state(
        plan_state,
        demand_semantics=demand_semantics,
        order_based=order_based,
    )

    # Build solver request with optional config overrides
    solver_request = engine_data_to_solver_request(engine_data, settings_dict)
    if solver_config_overrides:
        for k, v in solver_config_overrides.items():
            if hasattr(solver_request.config, k):
                setattr(solver_request.config, k, v)

    solver_result = _get_solver().solve(solver_request)
    blocks = solver_result_to_blocks(solver_result, engine_data)
    feasibility = build_feasibility_report(solver_result, len(engine_data.ops))
    decisions = build_decisions(solver_result)

    # Core analytics
    analytics: dict[str, Any] = {}
    try:
        analytics["score"] = _to_dict(
            score_schedule(
                blocks=blocks,
                ops=engine_data.ops,
                machines=engine_data.machines,
                n_days=engine_data.n_days,
            )
        )
    except Exception:
        logger.exception("score_schedule failed")
    try:
        analytics["validation"] = _to_dict(
            validate_schedule(
                blocks=blocks,
                machines=engine_data.machines,
                tool_map=engine_data.tool_map,
                ops=engine_data.ops,
                third_shift=engine_data.third_shift,
                n_days=engine_data.n_days,
            )
        )
    except Exception:
        logger.exception("validate_schedule failed")
    try:
        analytics["coverage"] = _to_dict(
            audit_coverage(
                blocks=blocks,
                ops=engine_data.ops,
                tool_map=engine_data.tool_map,
                twin_groups=engine_data.twin_groups,
            )
        )
    except Exception:
        logger.exception("audit_coverage failed")
    try:
        analytics["cap"] = cap_analysis(blocks=blocks, machines=engine_data.machines)
    except Exception:
        logger.exception("cap_analysis failed")
    try:
        analytics["late_deliveries"] = _to_dict(
            analyze_late_deliveries(
                blocks=blocks,
                ops=engine_data.ops,
                dates=engine_data.dates,
            )
        )
    except Exception:
        logger.exception("analyze_late_deliveries failed")

    return {
        "blocks": [_to_dict(b) for b in blocks],
        "decisions": [_to_dict(d) for d in decisions],
        "feasibility_report": _to_dict(feasibility),
        "solve_time_s": solver_result.solve_time_s,
        "solver_used": solver_result.solver_used,
        "n_blocks": len(blocks),
        "n_ops": len(engine_data.ops),
        **analytics,
    }


# ── What-If mutations ────────────────────────────────────────


def _apply_mutations(
    nikufra_data: dict[str, Any],
    settings: dict[str, Any],
    mutations: list,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply what-if mutations to a copy of nikufra_data + settings."""
    data = copy.deepcopy(nikufra_data)
    sett = copy.deepcopy(settings)

    for m in mutations:
        if m.type == "machine_down":
            m_st = sett.get("m_st", {})
            m_st[m.target_id] = "down"
            sett["m_st"] = m_st
        elif m.type == "add_demand":
            # Add demand to a specific operation
            ops = data.get("operations", [])
            for op in ops:
                if op.get("id") == m.target_id or op.get("sku") == m.target_id:
                    day_idx = m.params.get("day_idx", 0)
                    qty = m.params.get("qty", 0)
                    d = op.get("d", [])
                    while len(d) <= day_idx:
                        d.append(None)
                    current = d[day_idx] or 0
                    d[day_idx] = current - abs(qty)  # NP negative = demand
                    op["d"] = d
                    break
        elif m.type == "remove_demand":
            ops = data.get("operations", [])
            for op in ops:
                if op.get("id") == m.target_id or op.get("sku") == m.target_id:
                    day_idx = m.params.get("day_idx", 0)
                    d = op.get("d", [])
                    if day_idx < len(d):
                        d[day_idx] = None
                    op["d"] = d
                    break
        elif m.type == "rush_order":
            # Add a rush order (high priority demand at an early day)
            ops = data.get("operations", [])
            for op in ops:
                if op.get("id") == m.target_id or op.get("sku") == m.target_id:
                    day_idx = m.params.get("day_idx", 0)
                    qty = m.params.get("qty", 0)
                    d = op.get("d", [])
                    while len(d) <= day_idx:
                        d.append(None)
                    d[day_idx] = -abs(qty)
                    op["d"] = d
                    break

    return data, sett


# ── Delta computation ─────────────────────────────────────────


def _compute_delta(baseline: dict, scenario: dict) -> dict:
    """Compute delta between baseline and scenario score analytics."""
    delta: dict[str, Any] = {}
    bs = baseline.get("score") or {}
    ss = scenario.get("score") or {}

    for key in ("otdDelivery", "otdGlobal", "produced", "demanded", "tardyBlocks", "makespan"):
        bv = bs.get(key)
        sv = ss.get(key)
        if bv is not None and sv is not None:
            delta[key] = {"baseline": bv, "scenario": sv, "diff": sv - bv}

    delta["blocks_diff"] = scenario.get("n_blocks", 0) - baseline.get("n_blocks", 0)
    return delta
