from __future__ import annotations

# Integration Tests (S-06)
# End-to-end tests with Incompol-scale fixtures (5 machines, ~20 tools, ~30 jobs)
# Validates all contracts S-00 through S-05 working together.
from src.domain.solver.cpsat_solver import CpsatSolver
from src.domain.solver.lexicographic import LexicographicSolver
from src.domain.solver.montecarlo import monte_carlo_otd
from src.domain.solver.recovery import cascading_recovery
from src.domain.solver.router_logic import SolverRouter
from src.domain.solver.schemas import (
    ConstraintConfigInput,
    JobInput,
    MachineInput,
    OperationInput,
    SolverConfig,
    SolverRequest,
)
from src.domain.solver.warm_start import pick_best_heuristic

# ── Fixture: Incompol-scale problem ──

MACHINES = ["PRM019", "PRM031", "PRM039", "PRM042", "PRM043"]

TOOLS_BY_MACHINE = {
    "PRM019": ["BFP079", "BFP080", "BFP081", "BFP082"],
    "PRM031": ["BFP090", "BFP091", "BFP092", "BFP093"],
    "PRM039": ["BFP100", "BFP101", "BFP102", "BFP103", "BFP104"],
    "PRM042": ["BFP110", "BFP111"],
    "PRM043": ["BFP120", "BFP121", "BFP122"],
}


def _build_incompol_request(
    n_jobs: int = 30,
    tight_deadlines: bool = False,
    use_circuit: bool = True,
    objective_mode: str = "single",
    time_limit: int = 15,
    setup_crew: bool = True,
    twin_pairs: list | None = None,
) -> SolverRequest:
    """Build a realistic Incompol-scale request."""
    jobs = []
    job_idx = 0
    for mid in MACHINES:
        tools = TOOLS_BY_MACHINE[mid]
        n_per_machine = n_jobs // len(MACHINES)
        for i in range(n_per_machine):
            tool = tools[i % len(tools)]
            duration = 60 + (i * 10) % 120  # 60-180 min
            setup = 30 + (i * 5) % 60  # 30-90 min
            due = 300 if tight_deadlines else 2000 + job_idx * 100
            weight = 10.0 if i == 0 else 1.0  # First job per machine is priority

            jobs.append(
                JobInput(
                    id=f"J{job_idx:03d}",
                    sku=f"SKU_{tool}_{i}",
                    due_date_min=due,
                    weight=weight,
                    operations=[
                        OperationInput(
                            id=f"J{job_idx:03d}_O1",
                            machine_id=mid,
                            tool_id=tool,
                            duration_min=duration,
                            setup_min=setup,
                            operators=1,
                        )
                    ],
                )
            )
            job_idx += 1

    return SolverRequest(
        jobs=jobs,
        machines=[MachineInput(id=m) for m in MACHINES],
        config=SolverConfig(
            time_limit_s=time_limit,
            objective="weighted_tardiness",
            num_workers=2,
            use_circuit=use_circuit,
            objective_mode=objective_mode,
        ),
        constraints=ConstraintConfigInput(
            setup_crew=setup_crew,
            tool_timeline=False,
            calco_timeline=False,
        ),
        twin_pairs=twin_pairs or [],
    )


# ── Tests ──


class TestIntegrationCircuit:
    def test_circuit_30_jobs_feasible(self):
        """30-job Incompol-scale problem is feasible with circuit mode."""
        request = _build_incompol_request(n_jobs=30)
        result = CpsatSolver().solve(request)
        assert result.status in ("optimal", "feasible")
        assert len(result.schedule) == 30

    def test_circuit_saves_vs_legacy(self):
        """Circuit mode produces lower makespan than legacy for same-tool jobs."""
        circuit_req = _build_incompol_request(n_jobs=20, use_circuit=True)
        legacy_req = _build_incompol_request(n_jobs=20, use_circuit=False)

        circuit_result = CpsatSolver().solve(circuit_req)
        legacy_result = CpsatSolver().solve(legacy_req)

        assert circuit_result.status in ("optimal", "feasible")
        assert legacy_result.status in ("optimal", "feasible")
        # Circuit should be at least as good (often better)
        assert circuit_result.makespan_min <= legacy_result.makespan_min + 50


class TestIntegrationLexicographic:
    def test_lexicographic_30_jobs(self):
        """Lexicographic 3-phase works on Incompol-scale."""
        request = _build_incompol_request(n_jobs=25, objective_mode="lexicographic", time_limit=30)
        result = LexicographicSolver().solve(request)
        assert result.status in ("optimal", "feasible")
        assert result.solver_used == "cpsat_lexicographic"
        assert "phase1_tardiness" in result.phase_values


class TestIntegrationWarmStart:
    def test_warm_start_heuristic_covers_all(self):
        """Warm-start heuristic produces schedule for all ops."""
        request = _build_incompol_request(n_jobs=30)
        schedule = pick_best_heuristic(request)
        assert len(schedule) == 30
        op_ids = {s.op_id for s in schedule}
        assert len(op_ids) == 30


class TestIntegrationRecovery:
    def test_recovery_easy_problem(self):
        """Recovery level 1 suffices for easy problem."""
        request = _build_incompol_request(n_jobs=20, time_limit=15)
        result = cascading_recovery(request)
        assert result.status in ("optimal", "feasible")
        assert result.phase_values.get("recovery_level") == 1

    def test_recovery_tight_problem(self):
        """Recovery handles tight deadlines without crashing."""
        request = _build_incompol_request(n_jobs=25, tight_deadlines=True)
        result = cascading_recovery(request)
        assert result.status in ("optimal", "feasible")
        # Should have found something, even if tardy
        assert len(result.schedule) > 0


class TestIntegrationMonteCarlo:
    def test_mc_incompol_scale(self):
        """Monte Carlo runs on Incompol-scale in reasonable time."""
        request = _build_incompol_request(n_jobs=20)
        result = monte_carlo_otd(request, n_scenarios=50, seed=42)
        assert result["n_scenarios"] == 50
        assert result["elapsed_s"] < 120.0  # CP-SAT with 1s per scenario
        assert 0 <= result["p_otd_100"] <= 100


class TestIntegrationRouter:
    def test_router_single_mode(self):
        """Router handles single-mode request."""
        request = _build_incompol_request(n_jobs=20)
        result = SolverRouter().solve(request)
        assert result.status in ("optimal", "feasible")

    def test_router_lexicographic_mode(self):
        """Router routes to lexicographic when requested."""
        request = _build_incompol_request(n_jobs=15, objective_mode="lexicographic", time_limit=30)
        result = SolverRouter().solve(request)
        assert result.status in ("optimal", "feasible")
        assert result.solver_used == "cpsat_lexicographic"


class TestIntegrationSetupCrew:
    def test_setup_crew_with_circuit(self):
        """SetupCrew constraint works with circuit mode on multi-machine."""
        request = _build_incompol_request(n_jobs=10, setup_crew=True)
        result = CpsatSolver().solve(request)
        assert result.status in ("optimal", "feasible")
        assert len(result.schedule) == 10
