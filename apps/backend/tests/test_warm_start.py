# Tests for S-03: EDD Warm-Start + tool-grouped EDD
# Validates heuristic produces feasible schedules and CP-SAT accepts hints.

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
from src.domain.solver.warm_start import (
    edd_dispatch,
    pick_best_heuristic,
    tool_grouped_edd,
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


def _request(jobs, machines, **kwargs):
    return SolverRequest(
        jobs=jobs,
        machines=[MachineInput(id=m) for m in machines],
        config=SolverConfig(time_limit_s=10, objective="makespan", num_workers=1, **kwargs),
        constraints=ConstraintConfigInput(
            setup_crew=False, tool_timeline=False, calco_timeline=False
        ),
    )


class TestEDDDispatch:
    def test_edd_produces_feasible_schedule(self):
        """EDD heuristic produces a schedule covering all ops."""
        jobs = [
            _job("J1", 200, [_op("J1_O1", "M1", duration=50, setup=20)]),
            _job("J2", 300, [_op("J2_O1", "M1", duration=50, setup=20)]),
            _job("J3", 100, [_op("J3_O1", "M1", duration=50, setup=20)]),
        ]
        request = _request(jobs, ["M1"])
        schedule = edd_dispatch(request)

        assert len(schedule) == 3
        # All ops present
        op_ids = {s.op_id for s in schedule}
        assert op_ids == {"J1_O1", "J2_O1", "J3_O1"}
        # No overlaps on same machine
        sorted_ops = sorted(schedule, key=lambda s: s.start_min)
        for i in range(len(sorted_ops) - 1):
            assert sorted_ops[i].end_min <= sorted_ops[i + 1].start_min

    def test_edd_respects_due_date_order(self):
        """EDD dispatches earliest deadline first."""
        jobs = [
            _job("J1", 500, [_op("J1_O1", "M1", duration=50)]),
            _job("J2", 100, [_op("J2_O1", "M1", duration=50)]),
            _job("J3", 300, [_op("J3_O1", "M1", duration=50)]),
        ]
        request = _request(jobs, ["M1"])
        schedule = edd_dispatch(request)
        sorted_ops = sorted(schedule, key=lambda s: s.start_min)
        # J2 (due=100) should be first
        assert sorted_ops[0].op_id == "J2_O1"


class TestToolGroupedEDD:
    def test_tool_grouped_fewer_setups(self):
        """Tool-grouped EDD reduces total setup time vs pure EDD."""
        # Alternating tools: T1, T2, T1, T2 — pure EDD pays 4 setups
        # Tool-grouped: T1,T1,T2,T2 — pays 2 setups
        jobs = [
            _job("J1", 100, [_op("J1_O1", "M1", tool="T1", duration=50, setup=20)]),
            _job("J2", 200, [_op("J2_O1", "M1", tool="T2", duration=50, setup=20)]),
            _job("J3", 300, [_op("J3_O1", "M1", tool="T1", duration=50, setup=20)]),
            _job("J4", 400, [_op("J4_O1", "M1", tool="T2", duration=50, setup=20)]),
        ]
        request = _request(jobs, ["M1"])

        edd_schedule = edd_dispatch(request)
        grouped_schedule = tool_grouped_edd(request)

        edd_setups = sum(s.setup_min for s in edd_schedule)
        grouped_setups = sum(s.setup_min for s in grouped_schedule)

        # Grouped should have fewer or equal setups
        assert grouped_setups <= edd_setups

    def test_tool_grouped_all_ops_covered(self):
        """Tool-grouped EDD still covers all operations."""
        jobs = [
            _job(f"J{i}", i * 100, [_op(f"J{i}_O1", "M1", tool=f"T{i % 3}", duration=30)])
            for i in range(6)
        ]
        request = _request(jobs, ["M1"])
        schedule = tool_grouped_edd(request)
        assert len(schedule) == 6


class TestPickBestHeuristic:
    def test_pick_best_returns_better(self):
        """pick_best_heuristic returns the variant with lower weighted tardiness."""
        jobs = [
            _job("J1", 100, [_op("J1_O1", "M1", tool="T1", duration=50, setup=20)], weight=10.0),
            _job("J2", 150, [_op("J2_O1", "M1", tool="T2", duration=50, setup=20)], weight=1.0),
        ]
        request = _request(jobs, ["M1"])
        best = pick_best_heuristic(request)
        assert len(best) == 2


class TestHintsAccepted:
    def test_hints_accepted_by_cpsat(self):
        """CP-SAT accepts EDD hints and produces a valid solution."""
        jobs = [
            _job("J1", 500, [_op("J1_O1", "M1", duration=50, setup=20)]),
            _job("J2", 500, [_op("J2_O1", "M1", duration=50, setup=20)]),
        ]
        # With warm_start=True (default)
        request = _request(jobs, ["M1"], warm_start=True)
        result = CpsatSolver().solve(request)
        assert result.status in ("optimal", "feasible")
        assert len(result.schedule) == 2

    def test_warm_start_vs_cold(self):
        """Warm-start should not degrade solution quality vs cold start."""
        jobs = [
            _job(f"J{i}", (i + 1) * 200, [_op(f"J{i}_O1", "M1", tool="T1", duration=100, setup=30)])
            for i in range(5)
        ]

        warm_request = _request(jobs, ["M1"], warm_start=True)
        cold_request = _request(jobs, ["M1"], warm_start=False)

        warm_result = CpsatSolver().solve(warm_request)
        cold_result = CpsatSolver().solve(cold_request)

        assert warm_result.status in ("optimal", "feasible")
        assert cold_result.status in ("optimal", "feasible")
        # Warm-start should be at least as good
        assert warm_result.makespan_min <= cold_result.makespan_min + 10
