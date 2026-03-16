# Tests for S-01: AddCircuit + sequence-dependent setup times
# Validates that same-tool consecutive ops get zero setup,
# different-tool ops get proper setup, and SetupCrew still works.

from __future__ import annotations

from src.domain.solver.cpsat_solver import CpsatSolver
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


def _solve(jobs, machines, use_circuit=True, setup_matrix=None, setup_crew=True):
    request = SolverRequest(
        jobs=jobs,
        machines=[MachineInput(id=m) for m in machines],
        config=SolverConfig(
            time_limit_s=10, objective="makespan", num_workers=1, use_circuit=use_circuit
        ),
        constraints=ConstraintConfigInput(
            setup_crew=setup_crew, tool_timeline=False, calco_timeline=False
        ),
        setup_matrix=setup_matrix,
    )
    return CpsatSolver().solve(request)


class TestSameToolZeroSetup:
    def test_same_tool_zero_setup(self):
        """2 jobs with same tool on same machine → second job has zero setup."""
        jobs = [
            _job("J1", 500, [_op("J1_O1", "M1", tool="BFP079", duration=50, setup=30)]),
            _job("J2", 500, [_op("J2_O1", "M1", tool="BFP079", duration=50, setup=30)]),
        ]
        result = _solve(jobs, ["M1"])
        assert result.status in ("optimal", "feasible")

        ops = sorted(result.schedule, key=lambda s: s.start_min)
        # First op: setup(30) + prod(50) = 80
        # Second op: zero setup + prod(50) = 50
        # Total: 130 (not 160 as with legacy)
        assert result.makespan_min <= 140  # some tolerance
        # Second op should start right after first ends (no setup gap)
        assert ops[1].start_min == ops[0].end_min

    def test_same_tool_three_ops(self):
        """3 jobs with same tool → only first pays setup."""
        jobs = [
            _job(f"J{i}", 1000, [_op(f"J{i}_O1", "M1", tool="T1", duration=100, setup=20)])
            for i in range(3)
        ]
        result = _solve(jobs, ["M1"])
        assert result.status in ("optimal", "feasible")
        # Expected: 20 (first setup) + 3×100 (prod) = 320
        assert result.makespan_min <= 330


class TestDifferentToolHasSetup:
    def test_different_tools_all_get_setup(self):
        """3 jobs with different tools → each tool change pays setup."""
        jobs = [
            _job("J1", 1000, [_op("J1_O1", "M1", tool="T1", duration=50, setup=20)]),
            _job("J2", 1000, [_op("J2_O1", "M1", tool="T2", duration=50, setup=20)]),
            _job("J3", 1000, [_op("J3_O1", "M1", tool="T3", duration=50, setup=20)]),
        ]
        result = _solve(jobs, ["M1"])
        assert result.status in ("optimal", "feasible")
        # Each tool change requires setup: 3 setups + 3 prods
        # Minimum: 3×20 (setup) + 3×50 (prod) = 210
        assert result.makespan_min >= 200

    def test_mixed_tools_partial_setup(self):
        """4 jobs: T1, T1, T2, T2 → optimal grouping saves 2 setups."""
        jobs = [
            _job("J1", 1000, [_op("J1_O1", "M1", tool="T1", duration=50, setup=20)]),
            _job("J2", 1000, [_op("J2_O1", "M1", tool="T1", duration=50, setup=20)]),
            _job("J3", 1000, [_op("J3_O1", "M1", tool="T2", duration=50, setup=20)]),
            _job("J4", 1000, [_op("J4_O1", "M1", tool="T2", duration=50, setup=20)]),
        ]
        result = _solve(jobs, ["M1"])
        assert result.status in ("optimal", "feasible")
        # Optimal grouping: T1,T1,T2,T2 → 2 setups (not 4)
        # Minimum: 2×20 (setup) + 4×50 (prod) = 240
        assert result.makespan_min <= 260


class TestSetupCrewWithCircuit:
    def test_setup_crew_serializes_setups(self):
        """First ops on different machines with different tools → setups serialized."""
        jobs = [
            _job("J1", 500, [_op("J1_O1", "M1", tool="T1", duration=50, setup=30)]),
            _job("J2", 500, [_op("J2_O1", "M2", tool="T2", duration=50, setup=30)]),
        ]
        result = _solve(jobs, ["M1", "M2"], setup_crew=True)
        assert result.status in ("optimal", "feasible")
        ops = {s.op_id: s for s in result.schedule}
        # One must start after the other's setup
        starts = sorted([ops["J1_O1"].start_min, ops["J2_O1"].start_min])
        assert starts[1] >= starts[0] + 30


class TestSetupMatrix:
    def test_setup_matrix_custom_times(self):
        """Custom setup matrix overrides default setup times."""
        setup_matrix = {
            "T1": {"T2": 10, "T3": 50},
            "T2": {"T1": 10, "T3": 50},
        }
        jobs = [
            _job("J1", 1000, [_op("J1_O1", "M1", tool="T1", duration=50, setup=30)]),
            _job("J2", 1000, [_op("J2_O1", "M1", tool="T2", duration=50, setup=30)]),
        ]
        result = _solve(jobs, ["M1"], setup_matrix=setup_matrix)
        assert result.status in ("optimal", "feasible")
        # T1→T2 setup = 10 (from matrix, not 30 from op)
        # First setup + prod + changeover + prod = 30 + 50 + 10 + 50 = 140
        assert result.makespan_min <= 150


class TestCircuitVsLegacy:
    def test_circuit_saves_capacity_vs_legacy(self):
        """Circuit mode uses less time than legacy when same tools are consecutive."""
        jobs = [
            _job(f"J{i}", 2000, [_op(f"J{i}_O1", "M1", tool="T1", duration=100, setup=30)])
            for i in range(5)
        ]

        circuit_result = _solve(jobs, ["M1"], use_circuit=True)
        legacy_result = _solve(jobs, ["M1"], use_circuit=False)

        assert circuit_result.status in ("optimal", "feasible")
        assert legacy_result.status in ("optimal", "feasible")

        # Circuit: 30 + 5×100 = 530. Legacy: 5×(100+30) = 650.
        assert circuit_result.makespan_min < legacy_result.makespan_min
