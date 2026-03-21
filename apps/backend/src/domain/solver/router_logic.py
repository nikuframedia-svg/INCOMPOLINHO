from __future__ import annotations

# Solver Router — routes to CP-SAT or lexicographic (CP-SAT is the ONLY solver)
# PERF-02: Auto-detect time limits based on problem size.
# <100 ops: 5s (Incompol ~94 SKUs). 100-200: 30s. >200: 60s.
# Lexicographic mode gets 180s default (3 phases × 60s each).
from .cpsat_solver import CpsatSolver
from .lexicographic import LexicographicSolver
from .schemas import SolverRequest, SolverResult


class SolverRouter:
    """
    Routes scheduling requests to the appropriate solver:
    - Lexicographic mode: 3-phase solver (tardiness→JIT→setups)
    - <100 ops: CP-SAT with 5s time limit (Incompol ~94 ops)
    - 100-200 ops: CP-SAT with 30s time limit
    - >200 ops: CP-SAT with 60s time limit
    """

    def __init__(self):
        self.cpsat = CpsatSolver()
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

        # PERF-02: Auto-detect time limits (CP-SAT for all sizes)
        if n_ops < 100:
            request.config.time_limit_s = min(request.config.time_limit_s, 5)
        elif n_ops <= 200:
            request.config.time_limit_s = min(request.config.time_limit_s, 30)
        else:
            request.config.time_limit_s = min(request.config.time_limit_s, 60)

        return self.cpsat.solve(request)
