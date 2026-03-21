"""Schedule interaction endpoints — replan, what-if, optimize.

POST /v1/schedule/replan   — blocks + disruption → CP-SAT re-solve → new blocks
POST /v1/schedule/what-if  — scenario mutations → delta analysis
POST /v1/schedule/optimize — different objective weights → top-N alternatives
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...core.logging import get_logger
from ...domain.scheduling.analysis.coverage_audit import audit_coverage
from ...domain.scheduling.analysis.late_delivery_analysis import analyze_late_deliveries
from ...domain.scheduling.analysis.score_schedule import score_schedule
from ...domain.scheduling.analysis.validate_schedule import validate_schedule
from ...domain.scheduling.overflow.overflow_helpers import cap_analysis
from ...domain.scheduling.transform import transform_plan_state
from ...domain.scheduling.types import Block
from ...domain.solver.bridge import engine_data_to_solver_request, solver_result_to_blocks
from ...domain.solver.post_solve import build_decisions, build_feasibility_report
from ...domain.solver.router_logic import SolverRouter

logger = get_logger(__name__)

schedule_router = APIRouter(prefix="/schedule", tags=["schedule"])

_solver = SolverRouter()


# ── Shared helpers ─────────────────────────────────────────────


def _to_dict(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(obj)
    return obj


def _nikufra_to_plan_state(nikufra_data: dict[str, Any]) -> dict[str, Any]:
    """Convert parsed NikufraData into dict for transform_plan_state."""
    operations = nikufra_data.get("operations", [])
    tools = nikufra_data.get("tools", [])
    tool_lookup: dict[str, dict[str, Any]] = {t["id"]: t for t in tools}

    enriched_ops: list[dict[str, Any]] = []
    for op in operations:
        tool_info = tool_lookup.get(op.get("t", ""), {})
        enriched_ops.append({
            "id": op.get("id", ""),
            "m": op.get("m", ""),
            "t": op.get("t", ""),
            "sku": op.get("sku", ""),
            "nm": op.get("nm", ""),
            "pH": op.get("pH", 100),
            "atr": op.get("atr", 0),
            "d": op.get("d", []),
            "op": op.get("op", 1),
            "sH": op.get("s", tool_info.get("s", 0.75)),
            "alt": tool_info.get("alt", "-"),
            "eco": tool_info.get("lt", 0),
            "twin": op.get("twin"),
            "cl": op.get("cl"),
            "clNm": op.get("clNm"),
            "pa": op.get("pa"),
            "ltDays": op.get("ltDays"),
        })

    return {
        "operations": enriched_ops,
        "dates": nikufra_data.get("dates", []),
        "dnames": nikufra_data.get("days_label", []),
    }


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
        plan_state, demand_semantics=demand_semantics, order_based=order_based,
    )

    # Build solver request with optional config overrides
    solver_request = engine_data_to_solver_request(engine_data, settings_dict)
    if solver_config_overrides:
        for k, v in solver_config_overrides.items():
            if hasattr(solver_request.config, k):
                setattr(solver_request.config, k, v)

    solver_result = _solver.solve(solver_request)
    blocks = solver_result_to_blocks(solver_result, engine_data)
    feasibility = build_feasibility_report(solver_result, len(engine_data.ops))
    decisions = build_decisions(solver_result)

    # Core analytics
    analytics: dict[str, Any] = {}
    try:
        analytics["score"] = _to_dict(score_schedule(
            blocks=blocks, ops=engine_data.ops,
            machines=engine_data.machines, n_days=engine_data.n_days,
        ))
    except Exception:
        pass
    try:
        analytics["validation"] = _to_dict(validate_schedule(
            blocks=blocks, machines=engine_data.machines,
            tool_map=engine_data.tool_map, ops=engine_data.ops,
            third_shift=engine_data.third_shift, n_days=engine_data.n_days,
        ))
    except Exception:
        pass
    try:
        analytics["coverage"] = _to_dict(audit_coverage(
            blocks=blocks, ops=engine_data.ops,
            tool_map=engine_data.tool_map, twin_groups=engine_data.twin_groups,
        ))
    except Exception:
        pass
    try:
        analytics["cap"] = cap_analysis(blocks=blocks, machines=engine_data.machines)
    except Exception:
        pass
    try:
        analytics["late_deliveries"] = _to_dict(analyze_late_deliveries(
            blocks=blocks, ops=engine_data.ops, dates=engine_data.dates,
        ))
    except Exception:
        pass

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


# ── Replan endpoint ────────────────────────────────────────────


class DisruptionEvent(BaseModel):
    type: str = Field(..., description="machine_down | tool_down | demand_change")
    resource_id: str
    start_day: int = 0
    end_day: int = 0
    capacity_factor: float = Field(0.0, ge=0.0, le=1.0)


class ReplanRequest(BaseModel):
    nikufra_data: dict[str, Any]
    disruption: DisruptionEvent
    settings: dict[str, Any] = Field(default_factory=dict)


class ReplanResponse(BaseModel):
    blocks: list[dict] = Field(default_factory=list)
    decisions: list[dict] = Field(default_factory=list)
    feasibility_report: dict | None = None
    solve_time_s: float = 0.0
    solver_used: str = "cpsat"
    n_blocks: int = 0
    n_ops: int = 0
    score: dict | None = None
    validation: dict | None = None
    coverage: dict | None = None
    cap: dict[str, list] | None = None
    late_deliveries: dict | None = None
    delta: dict | None = None

    model_config = {"arbitrary_types_allowed": True}


@schedule_router.post("/replan", response_model=ReplanResponse)
async def replan(request: ReplanRequest) -> ReplanResponse:
    """Re-solve schedule with a disruption event.

    Applies the disruption to NikufraData (e.g., marks machine down for days),
    then re-solves via CP-SAT. Returns new blocks + delta from original.
    """
    t0 = time.perf_counter()
    nikufra_data = request.nikufra_data
    settings_dict = request.settings
    disruption = request.disruption

    # Apply disruption to settings (machine/tool status)
    if disruption.type == "machine_down":
        m_st = settings_dict.get("m_st", {})
        m_st[disruption.resource_id] = "down"
        settings_dict["m_st"] = m_st
    elif disruption.type == "tool_down":
        t_st = settings_dict.get("t_st", {})
        t_st[disruption.resource_id] = "down"
        settings_dict["t_st"] = t_st

    try:
        result = _solve_and_analyze(nikufra_data, settings_dict)
    except Exception as e:
        logger.error("schedule.replan.error", error=str(e))
        return ReplanResponse(
            decisions=[{"type": "ERROR", "detail": str(e)}],
        )

    elapsed = time.perf_counter() - t0
    result["solve_time_s"] = round(elapsed, 3)

    logger.info(
        "schedule.replan.done",
        disruption_type=disruption.type,
        resource=disruption.resource_id,
        n_blocks=result["n_blocks"],
        elapsed_s=round(elapsed, 3),
    )

    return ReplanResponse(**result)


# ── What-If endpoint ───────────────────────────────────────────


class WhatIfMutation(BaseModel):
    type: str = Field(..., description="add_demand | remove_demand | machine_down | rush_order")
    target_id: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class WhatIfRequest(BaseModel):
    nikufra_data: dict[str, Any]
    mutations: list[WhatIfMutation]
    settings: dict[str, Any] = Field(default_factory=dict)


class WhatIfResponse(BaseModel):
    baseline: dict | None = None
    scenario: dict | None = None
    delta: dict | None = None
    solve_time_s: float = 0.0

    model_config = {"arbitrary_types_allowed": True}


def _apply_mutations(
    nikufra_data: dict[str, Any],
    settings: dict[str, Any],
    mutations: list[WhatIfMutation],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply what-if mutations to a copy of nikufra_data + settings."""
    import copy
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


@schedule_router.post("/what-if", response_model=WhatIfResponse)
async def what_if(request: WhatIfRequest) -> WhatIfResponse:
    """What-if scenario analysis.

    1. Solve baseline (original data)
    2. Apply mutations to data
    3. Solve scenario (mutated data)
    4. Return both + delta
    """
    t0 = time.perf_counter()

    try:
        baseline = _solve_and_analyze(request.nikufra_data, request.settings)
    except Exception as e:
        logger.error("schedule.whatif.baseline.error", error=str(e))
        return WhatIfResponse(delta={"error": f"Baseline solve failed: {e}"})

    mutated_data, mutated_settings = _apply_mutations(
        request.nikufra_data, request.settings, request.mutations,
    )

    try:
        scenario = _solve_and_analyze(mutated_data, mutated_settings)
    except Exception as e:
        logger.error("schedule.whatif.scenario.error", error=str(e))
        return WhatIfResponse(
            baseline=baseline,
            delta={"error": f"Scenario solve failed: {e}"},
        )

    delta = _compute_delta(baseline, scenario)
    elapsed = time.perf_counter() - t0

    logger.info(
        "schedule.whatif.done",
        n_mutations=len(request.mutations),
        elapsed_s=round(elapsed, 3),
    )

    return WhatIfResponse(
        baseline=baseline,
        scenario=scenario,
        delta=delta,
        solve_time_s=round(elapsed, 3),
    )


# ── Optimize endpoint ──────────────────────────────────────────


class OptimizeRequest(BaseModel):
    nikufra_data: dict[str, Any]
    objective_weights: dict[str, float] = Field(
        default_factory=lambda: {"tardiness": 1.0, "makespan": 0.1, "setups": 0.05},
    )
    n_alternatives: int = Field(3, ge=1, le=5)
    settings: dict[str, Any] = Field(default_factory=dict)


class OptimizeAlternative(BaseModel):
    objective: str
    blocks: list[dict] = Field(default_factory=list)
    score: dict | None = None
    solve_time_s: float = 0.0
    n_blocks: int = 0

    model_config = {"arbitrary_types_allowed": True}


class OptimizeResponse(BaseModel):
    alternatives: list[OptimizeAlternative] = Field(default_factory=list)
    solve_time_s: float = 0.0

    model_config = {"arbitrary_types_allowed": True}


@schedule_router.post("/optimize", response_model=OptimizeResponse)
async def optimize(request: OptimizeRequest) -> OptimizeResponse:
    """Generate top-N schedule alternatives with different objective functions.

    Solves the same problem with different CP-SAT objectives:
    - weighted_tardiness (default)
    - makespan
    - tardiness (unweighted)
    """
    t0 = time.perf_counter()
    objectives = ["weighted_tardiness", "makespan", "tardiness"]
    n = min(request.n_alternatives, len(objectives))

    alternatives: list[OptimizeAlternative] = []
    for obj in objectives[:n]:
        try:
            result = _solve_and_analyze(
                request.nikufra_data,
                request.settings,
                solver_config_overrides={"objective": obj},
            )
            alternatives.append(OptimizeAlternative(
                objective=obj,
                blocks=result.get("blocks", []),
                score=result.get("score"),
                solve_time_s=result.get("solve_time_s", 0.0),
                n_blocks=result.get("n_blocks", 0),
            ))
        except Exception as e:
            logger.warning("schedule.optimize.alt.error", objective=obj, error=str(e))
            alternatives.append(OptimizeAlternative(
                objective=obj,
                score={"error": str(e)},
            ))

    elapsed = time.perf_counter() - t0

    logger.info(
        "schedule.optimize.done",
        n_alternatives=len(alternatives),
        elapsed_s=round(elapsed, 3),
    )

    return OptimizeResponse(
        alternatives=alternatives,
        solve_time_s=round(elapsed, 3),
    )
