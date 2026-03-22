"""Schedule interaction endpoints — replan, what-if, optimize, CTP.

POST /v1/schedule/replan   — blocks + disruption → CP-SAT re-solve → new blocks
POST /v1/schedule/what-if  — scenario mutations → delta analysis
POST /v1/schedule/optimize — different objective weights → top-N alternatives
POST /v1/schedule/ctp      — capable-to-promise for new orders
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...core.logging import get_logger
from ...domain.nikufra.utils import nikufra_to_plan_state as _nikufra_to_plan_state
from ...domain.scheduling.transform import transform_plan_state

# Re-export helpers so copilot/engine.py can still import from this module
from .schedule_helpers import (
    _apply_mutations,  # noqa: F401
    _compute_delta,  # noqa: F401
    _solve_and_analyze,  # noqa: F401
)

logger = get_logger(__name__)

schedule_router = APIRouter(prefix="/schedule", tags=["schedule"])


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
        request.nikufra_data,
        request.settings,
        request.mutations,
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
    """Generate top-N schedule alternatives with different objective functions."""
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
            alternatives.append(
                OptimizeAlternative(
                    objective=obj,
                    blocks=result.get("blocks", []),
                    score=result.get("score"),
                    solve_time_s=result.get("solve_time_s", 0.0),
                    n_blocks=result.get("n_blocks", 0),
                )
            )
        except Exception as e:
            logger.warning("schedule.optimize.alt.error", objective=obj, error=str(e))
            alternatives.append(
                OptimizeAlternative(
                    objective=obj,
                    score={"error": str(e)},
                )
            )

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


# ── CTP endpoint ──────────────────────────────────────────────


class CTPRequest(BaseModel):
    nikufra_data: dict[str, Any]
    sku: str
    quantity: int
    target_day: int
    settings: dict[str, Any] = Field(default_factory=dict)


class CTPScenarioOut(BaseModel):
    id: str
    label: str
    machine: str
    feasible: bool
    earliest_feasible_day: int | None = None
    date_label: str | None = None
    required_min: int = 0
    available_min_on_day: int = 0
    capacity_slack: int = 0
    confidence: str = "low"
    reason: str = ""
    is_alt: bool = False
    capacity_timeline: list[dict] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class CTPResponse(BaseModel):
    scenarios: list[CTPScenarioOut] = Field(default_factory=list)
    solve_time_s: float = 0.0

    model_config = {"arbitrary_types_allowed": True}


@schedule_router.post("/ctp", response_model=CTPResponse)
async def ctp(request: CTPRequest) -> CTPResponse:
    """Capable-To-Promise: 3-scenario analysis for a new order."""
    from dataclasses import asdict

    from ...domain.scheduling.mrp.ctp import CTPInput, compute_ctp
    from ...domain.scheduling.mrp.mrp_ctp_sku import CTPSkuInput, compute_ctp_sku
    from ...domain.scheduling.mrp.mrp_engine import compute_mrp

    t0 = time.perf_counter()

    plan_state = _nikufra_to_plan_state(request.nikufra_data)
    engine = transform_plan_state(plan_state, demand_semantics="raw_np", order_based=True)

    # Compute MRP (needed for CTP)
    mrp = compute_mrp(engine)

    scenarios: list[CTPScenarioOut] = []

    # Find op + tool for this SKU
    op = next((o for o in engine.ops if o.sku == request.sku), None)
    tool = engine.tool_map.get(op.t) if op else None
    primary_machine = tool.m if tool else ""

    # Scenario 1: Best case via SKU-level CTP
    best = compute_ctp_sku(
        CTPSkuInput(sku=request.sku, quantity=request.quantity, target_day=request.target_day),
        mrp,
        engine,
    )
    if not best:
        return CTPResponse(solve_time_s=round(time.perf_counter() - t0, 3))

    best_date = (
        engine.dates[best.earliest_feasible_day]
        if best.earliest_feasible_day is not None and best.earliest_feasible_day < len(engine.dates)
        else None
    )

    if (
        best.feasible
        and best.earliest_feasible_day is not None
        and best.earliest_feasible_day <= request.target_day
    ):
        scenarios.append(
            CTPScenarioOut(
                id="best",
                label="Melhor caso",
                machine=best.machine,
                feasible=True,
                earliest_feasible_day=best.earliest_feasible_day,
                date_label=best_date,
                required_min=best.required_min,
                available_min_on_day=best.available_min_on_day,
                capacity_slack=best.capacity_slack,
                confidence=best.confidence,
                reason=best.reason,
                is_alt=best.machine != primary_machine,
                capacity_timeline=[asdict(c) for c in best.capacity_timeline],
            )
        )
    else:
        scenarios.append(
            CTPScenarioOut(
                id="best" if best.feasible else "infeasible",
                label="Melhor caso" if best.feasible else "Inviável — máquina principal",
                machine=best.machine,
                feasible=best.feasible,
                earliest_feasible_day=best.earliest_feasible_day,
                date_label=best_date,
                required_min=best.required_min,
                available_min_on_day=best.available_min_on_day,
                capacity_slack=best.capacity_slack,
                confidence=best.confidence,
                reason=best.reason,
                is_alt=best.machine != primary_machine,
                capacity_timeline=[asdict(c) for c in best.capacity_timeline],
            )
        )

        # Scenario 2: Try alt machine
        if tool and tool.alt and tool.alt != "-":
            alt_result = compute_ctp(
                CTPInput(
                    tool_code=tool.id, quantity=request.quantity, target_day=request.target_day
                ),
                mrp,
                engine,
            )
            if alt_result and alt_result.machine != primary_machine and alt_result.feasible:
                alt_date = (
                    engine.dates[alt_result.earliest_feasible_day]
                    if alt_result.earliest_feasible_day is not None
                    and alt_result.earliest_feasible_day < len(engine.dates)
                    else None
                )
                scenarios.append(
                    CTPScenarioOut(
                        id="tradeoff",
                        label="Com trade-off — máquina alternativa",
                        machine=alt_result.machine,
                        feasible=True,
                        earliest_feasible_day=alt_result.earliest_feasible_day,
                        date_label=alt_date,
                        required_min=alt_result.required_min,
                        available_min_on_day=alt_result.available_min_on_day,
                        capacity_slack=alt_result.capacity_slack,
                        confidence=alt_result.confidence,
                        reason=alt_result.reason,
                        is_alt=True,
                        capacity_timeline=[asdict(c) for c in alt_result.capacity_timeline],
                    )
                )

        # Try extended horizon
        if not best.feasible or (
            best.earliest_feasible_day is not None
            and best.earliest_feasible_day > request.target_day
        ):
            ext_day = min(request.target_day + 7, len(engine.dates) - 1)
            if ext_day > request.target_day:
                ext = compute_ctp_sku(
                    CTPSkuInput(sku=request.sku, quantity=request.quantity, target_day=ext_day),
                    mrp,
                    engine,
                )
                if ext and ext.feasible and ext.earliest_feasible_day is not None:
                    ext_date = (
                        engine.dates[ext.earliest_feasible_day]
                        if ext.earliest_feasible_day < len(engine.dates)
                        else None
                    )
                    scenarios.append(
                        CTPScenarioOut(
                            id="tradeoff",
                            label="Com trade-off — horizonte estendido",
                            machine=ext.machine,
                            feasible=True,
                            earliest_feasible_day=ext.earliest_feasible_day,
                            date_label=ext_date,
                            required_min=ext.required_min,
                            available_min_on_day=ext.available_min_on_day,
                            capacity_slack=ext.capacity_slack,
                            confidence=ext.confidence,
                            reason=ext.reason,
                            is_alt=ext.machine != primary_machine,
                            capacity_timeline=[asdict(c) for c in ext.capacity_timeline],
                        )
                    )

    elapsed = time.perf_counter() - t0
    logger.info(
        "schedule.ctp.done",
        sku=request.sku,
        n_scenarios=len(scenarios),
        elapsed_s=round(elapsed, 3),
    )
    return CTPResponse(scenarios=scenarios, solve_time_s=round(elapsed, 3))
