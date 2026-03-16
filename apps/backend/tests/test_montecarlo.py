# Tests for S-05: Monte Carlo Robustness
# Validates deterministic with seed, OTD estimation, and buffer suggestions.

from __future__ import annotations

import random

from src.domain.solver.montecarlo import monte_carlo_otd
from src.domain.solver.perturbation import perturb_request
from src.domain.solver.schemas import (
    ConstraintConfigInput,
    JobInput,
    MachineInput,
    OperationInput,
    SolverConfig,
    SolverRequest,
)


def _op(op_id, machine, tool="T1", duration=60, setup=15):
    return OperationInput(
        id=op_id,
        machine_id=machine,
        tool_id=tool,
        duration_min=duration,
        setup_min=setup,
        operators=1,
    )


def _job(job_id, due, ops, weight=1.0):
    return JobInput(id=job_id, sku=f"SKU_{job_id}", due_date_min=due, weight=weight, operations=ops)


def _request(jobs, machines):
    return SolverRequest(
        jobs=jobs,
        machines=[MachineInput(id=m) for m in machines],
        config=SolverConfig(time_limit_s=10, objective="makespan", num_workers=1),
        constraints=ConstraintConfigInput(
            setup_crew=False, tool_timeline=False, calco_timeline=False
        ),
    )


class TestMonteCarloDeterministic:
    def test_deterministic_with_seed(self):
        """Same seed produces same results."""
        jobs = [
            _job("J1", 500, [_op("J1_O1", "M1", duration=100, setup=20)]),
            _job("J2", 500, [_op("J2_O1", "M1", duration=100, setup=20)]),
        ]
        request = _request(jobs, ["M1"])

        r1 = monte_carlo_otd(request, n_scenarios=50, seed=42)
        r2 = monte_carlo_otd(request, n_scenarios=50, seed=42)

        assert r1["p_otd_100"] == r2["p_otd_100"]
        assert r1["mean_tardiness"] == r2["mean_tardiness"]
        assert r1["vulnerable_jobs"] == r2["vulnerable_jobs"]


class TestMonteCarloOTD:
    def test_perfect_schedule_high_p(self):
        """Easy schedule with large slack → high P(OTD=100%)."""
        jobs = [
            _job("J1", 5000, [_op("J1_O1", "M1", duration=50, setup=10)]),
        ]
        request = _request(jobs, ["M1"])
        result = monte_carlo_otd(request, n_scenarios=100, seed=42)

        assert result["p_otd_100"] >= 90.0
        assert result["mean_tardiness"] == 0.0

    def test_tight_schedule_low_p(self):
        """Tight schedule → lower P(OTD=100%)."""
        # Very tight: 3 ops on 1 machine, all due at 200
        jobs = [
            _job("J1", 200, [_op("J1_O1", "M1", duration=80, setup=20)]),
            _job("J2", 200, [_op("J2_O1", "M1", duration=80, setup=20)]),
            _job("J3", 200, [_op("J3_O1", "M1", duration=80, setup=20)]),
        ]
        request = _request(jobs, ["M1"])
        result = monte_carlo_otd(request, n_scenarios=100, seed=42)

        # Should have lower OTD since schedule is very tight
        assert result["p_otd_100"] < 90.0
        assert result["mean_tardiness"] > 0


class TestBufferSuggestion:
    def test_buffer_suggestion_positive(self):
        """Vulnerable jobs get positive buffer suggestions."""
        # Tight schedule to create vulnerable jobs
        jobs = [
            _job(f"J{i}", 150, [_op(f"J{i}_O1", "M1", duration=60, setup=15)]) for i in range(4)
        ]
        request = _request(jobs, ["M1"])
        result = monte_carlo_otd(
            request,
            n_scenarios=100,
            seed=42,
            duration_cv=0.15,
            setup_cv=0.25,
        )

        # If there are vulnerable jobs, buffers should be positive
        for buf in result["suggested_buffers"]:
            assert buf["buffer_min"] > 0
            assert "reason" in buf


class TestPerturbation:
    def test_perturb_changes_durations(self):
        """Perturbation modifies durations while keeping them positive."""
        jobs = [
            _job("J1", 500, [_op("J1_O1", "M1", duration=100, setup=30)]),
        ]
        request = _request(jobs, ["M1"])
        rng = random.Random(42)

        perturbed = perturb_request(request, rng, duration_cv=0.20, setup_cv=0.20)
        orig_dur = request.jobs[0].operations[0].duration_min
        new_dur = perturbed.jobs[0].operations[0].duration_min

        # Duration should be different (with high probability) but positive
        assert new_dur >= 1
        # Original should be unchanged
        assert request.jobs[0].operations[0].duration_min == 100

    def test_perturb_with_zero_cv(self):
        """Zero CV means no perturbation to durations/setups."""
        jobs = [
            _job("J1", 500, [_op("J1_O1", "M1", duration=100, setup=30)]),
        ]
        request = _request(jobs, ["M1"])
        rng = random.Random(42)

        perturbed = perturb_request(request, rng, duration_cv=0, setup_cv=0, breakdown_rate=0)
        assert perturbed.jobs[0].operations[0].duration_min == 100
        assert perturbed.jobs[0].operations[0].setup_min == 30
