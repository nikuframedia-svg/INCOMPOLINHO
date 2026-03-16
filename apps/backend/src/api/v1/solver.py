# Solver API endpoints
# Conforme Contrato C4: CP-SAT Solver


from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...domain.solver.montecarlo import monte_carlo_otd
from ...domain.solver.recovery import cascading_recovery
from ...domain.solver.router_logic import SolverRouter
from ...domain.solver.schemas import SolverRequest, SolverResult

solver_router = APIRouter(prefix="/solver", tags=["solver"])

_router = SolverRouter()


class RecoveryRequest(BaseModel):
    """Request for cascading recovery solver."""

    solver_request: SolverRequest
    frozen_ops: list[str] = Field(default_factory=list, description="Op IDs already started")
    alt_machines: dict[str, list[str]] | None = Field(
        None, description="Machine ID -> list of alternative machine IDs"
    )


class RobustnessRequest(BaseModel):
    """Request for Monte Carlo robustness analysis."""

    solver_request: SolverRequest
    n_scenarios: int = Field(200, ge=10, le=5000)
    seed: int = Field(42)
    duration_cv: float = Field(0.10, ge=0, le=0.5)
    setup_cv: float = Field(0.20, ge=0, le=0.5)
    breakdown_rate: float = Field(0.005, ge=0, le=0.1)


@solver_router.post("/schedule", response_model=SolverResult)
async def schedule(request: SolverRequest):
    """
    Resolver problema de scheduling via CP-SAT ou heuristic fallback.

    Routing automatico:
    - <50 ops: CP-SAT (ate 120s, solucao optima)
    - 50-200 ops: CP-SAT (ate 60s)
    - >200 ops: ATCS heuristic fallback
    """
    return _router.solve(request)


@solver_router.post("/recover", response_model=SolverResult)
async def recover(request: RecoveryRequest):
    """
    Cascading recovery: 4-level escalation to handle infeasibility.

    Level 1: Hard deadlines (strict)
    Level 2: Alternative machines
    Level 3: Overtime (extended capacity)
    Level 4: Soft deadlines (relaxed weights)
    """
    return cascading_recovery(
        request=request.solver_request,
        frozen_ops=request.frozen_ops or None,
        alt_machines=request.alt_machines,
    )


@solver_router.post("/robustness")
async def robustness(request: RobustnessRequest):
    """
    Monte Carlo robustness analysis: N perturbed scenarios using heuristic solver.

    Returns P(OTD=100%), vulnerable jobs, and buffer suggestions.
    """
    return monte_carlo_otd(
        request=request.solver_request,
        n_scenarios=request.n_scenarios,
        seed=request.seed,
        duration_cv=request.duration_cv,
        setup_cv=request.setup_cv,
        breakdown_rate=request.breakdown_rate,
    )
