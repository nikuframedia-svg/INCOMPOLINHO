# Solver API endpoints
# Conforme Contrato C4: CP-SAT Solver

from fastapi import APIRouter

from ...domain.solver.router_logic import SolverRouter
from ...domain.solver.schemas import SolverRequest, SolverResult

solver_router = APIRouter(prefix="/solver", tags=["solver"])

_router = SolverRouter()


@solver_router.post("/schedule", response_model=SolverResult)
async def schedule(request: SolverRequest):
    """
    Resolver problema de scheduling via CP-SAT ou heuristic fallback.

    Routing automático:
    - <50 ops: CP-SAT (até 120s, solução óptima)
    - 50-200 ops: CP-SAT (até 60s)
    - >200 ops: ATCS heuristic fallback
    """
    return _router.solve(request)
