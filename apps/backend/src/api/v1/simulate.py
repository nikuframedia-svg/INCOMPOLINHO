"""Simulate endpoint — unified replan + what-if.

POST /v1/schedule/simulate
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...core.logging import get_logger
from ...domain.nikufra.utils import nikufra_to_plan_state as _nikufra_to_plan_state
from ...domain.scheduler.simulator import SimMutation, simulate
from ...domain.scheduling.transform import transform_plan_state
from .schedule_helpers import _to_dict

logger = get_logger(__name__)

simulate_router = APIRouter(prefix="/schedule", tags=["simulate"])


# ── Request / Response models ──


class MutationIn(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class SimulateRequest(BaseModel):
    nikufra_data: dict[str, Any]
    mutations: list[MutationIn]
    settings: dict[str, Any] = Field(default_factory=dict)


class SimulateResponse(BaseModel):
    blocks: list[dict] = Field(default_factory=list)
    score: dict | None = None
    time_ms: float = 0.0
    delta: dict | None = None
    mutation_impacts: list[dict] = Field(default_factory=list)
    block_changes: list[dict] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


# ── Endpoint ──


@simulate_router.post("/simulate", response_model=SimulateResponse)
async def simulate_endpoint(request: SimulateRequest) -> SimulateResponse:
    """Run scenario simulation with one or more mutations."""
    t0 = time.perf_counter()

    # 1. Build EngineData from nikufra_data
    order_based = request.settings.get("orderBased", True)
    demand_semantics = request.settings.get("demandSemantics", "raw_np")

    plan_state = _nikufra_to_plan_state(request.nikufra_data)
    engine_data = transform_plan_state(
        plan_state,
        demand_semantics=demand_semantics,
        order_based=order_based,
    )

    # 2. Convert mutations
    mutations = [SimMutation(type=m.type, params=m.params) for m in request.mutations]

    # 3. Simulate
    result = simulate(engine_data, mutations, request.settings)

    elapsed = time.perf_counter() - t0

    logger.info(
        "schedule.simulate.done",
        extra={
            "n_mutations": len(mutations),
            "otd_d_before": result.delta.otd_d_before,
            "otd_d_after": result.delta.otd_d_after,
            "blocks_changed": result.delta.blocks_changed,
            "elapsed_ms": round(elapsed * 1000),
        },
    )

    return SimulateResponse(
        blocks=[_to_dict(b) for b in result.blocks],
        score=result.score,
        time_ms=result.time_ms,
        delta=asdict(result.delta),
        mutation_impacts=[asdict(imp) for imp in result.mutation_impacts],
        block_changes=[asdict(bc) for bc in result.block_changes],
        summary=result.summary,
    )
