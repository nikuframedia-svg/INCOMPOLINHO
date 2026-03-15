from __future__ import annotations

# Solver Router — routes to CP-SAT, lexicographic, or heuristic fallback
# Conforme CLAUDE.md Camada 3:
# <50 jobs: solução óptima (120s). 50-200: time limit 60s. >200: fallback ATCS.
# Lexicographic mode gets 180s default (3 phases × 60s each).
from .cpsat_solver import CpsatSolver
from .heuristic_fallback import HeuristicFallback
from .lexicographic import LexicographicSolver
from .schemas import SolverRequest, SolverResult


class SolverRouter:
    """
    Routes scheduling requests to the appropriate solver:
    - Lexicographic mode: 3-phase solver (tardiness→JIT→setups)
    - <50 ops: CP-SAT with 120s time limit (optimal)
    - 50-200 ops: CP-SAT with 60s time limit
    - >200 ops: ATCS heuristic fallback
    """

    def __init__(self):
        self.cpsat = CpsatSolver()
        self.heuristic = HeuristicFallback()
        self.lexicographic = LexicographicSolver()

    def solve(self, request: SolverRequest) -> SolverResult:
        n_ops = sum(len(j.operations) for j in request.jobs)

        if n_ops == 0:
            return self.cpsat.solve(request)

        # Lexicographic mode
        if request.config.objective_mode == "lexicographic":
            # Default to 180s for 3-phase if not explicitly set higher
            if request.config.time_limit_s <= 60:
                request.config.time_limit_s = 180
            return self.lexicographic.solve(request)

        if n_ops < 50:
            request.config.time_limit_s = min(request.config.time_limit_s, 120)
            return self.cpsat.solve(request)
        elif n_ops < 200:
            request.config.time_limit_s = min(request.config.time_limit_s, 60)
            return self.cpsat.solve(request)
        else:
            # Large problem — heuristic fallback
            return self.heuristic.solve(request)
