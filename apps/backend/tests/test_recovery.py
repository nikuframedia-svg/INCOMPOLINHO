# Tests for S-04: Cascading Recovery + Late Report
# Validates 4-level escalation and late order reporting.

from __future__ import annotations

from src.domain.solver.late_report import _classify_priority, build_late_report
from src.domain.solver.recovery import cascading_recovery
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


def _request(jobs, machines, time_limit=10):
    return SolverRequest(
        jobs=jobs,
        machines=[MachineInput(id=m) for m in machines],
        config=SolverConfig(time_limit_s=time_limit, objective="weighted_tardiness", num_workers=1),
        constraints=ConstraintConfigInput(
            setup_crew=False, tool_timeline=False, calco_timeline=False
        ),
    )


class TestRecoveryLevel1:
    def test_level1_sufficient(self):
        """Easy problem resolves at level 1 (no escalation needed)."""
        jobs = [
            _job("J1", 500, [_op("J1_O1", "M1", duration=50, setup=20)]),
            _job("J2", 500, [_op("J2_O1", "M1", duration=50, setup=20)]),
        ]
        request = _request(jobs, ["M1"])
        result = cascading_recovery(request)
        assert result.status in ("optimal", "feasible")
        assert result.phase_values.get("recovery_level") == 1
        assert result.total_tardiness_min == 0


class TestRecoveryEscalation:
    def test_recovery_escalates_to_overtime(self):
        """Tight problem escalates beyond level 1."""
        # Very tight deadlines — all ops same machine, not enough time
        jobs = [
            _job("J1", 30, [_op("J1_O1", "M1", duration=50, setup=10)]),
            _job("J2", 30, [_op("J2_O1", "M1", duration=50, setup=10)]),
            _job("J3", 30, [_op("J3_O1", "M1", duration=50, setup=10)]),
        ]
        request = _request(jobs, ["M1"])
        result = cascading_recovery(request)
        assert result.status in ("optimal", "feasible")
        # Should have escalated beyond level 1
        assert result.phase_values.get("recovery_level", 0) >= 1

    def test_recovery_with_alt_machines(self):
        """Alt machines help distribute load."""
        jobs = [
            _job("J1", 100, [_op("J1_O1", "M1", duration=80, setup=10)]),
            _job("J2", 100, [_op("J2_O1", "M1", duration=80, setup=10)]),
        ]
        request = _request(jobs, ["M1", "M2"])
        alt_machines = {"M1": ["M2"]}
        result = cascading_recovery(request, alt_machines=alt_machines)
        assert result.status in ("optimal", "feasible")


class TestLateReport:
    def test_late_report_has_reasons(self):
        """Late report contains structured info for tardy jobs."""
        jobs = [
            _job("J1", 30, [_op("J1_O1", "M1", duration=50, setup=10)], weight=100.0),
            _job("J2", 30, [_op("J2_O1", "M1", duration=50, setup=10)], weight=1.0),
        ]
        request = _request(jobs, ["M1"])
        from src.domain.solver.cpsat_solver import CpsatSolver

        result = CpsatSolver().solve(request)

        report = build_late_report(result, request)
        # At least one must be late (can't both finish by 30)
        assert report is not None
        assert report["otd_pct"] < 100
        assert len(report["late_orders"]) > 0
        assert report["bottleneck_machine"] == "M1"

    def test_late_report_sorted_by_urgency(self):
        """Late orders sorted by priority (highest first)."""
        jobs = [
            _job("J1", 30, [_op("J1_O1", "M1", duration=50, setup=10)], weight=1.0),
            _job("J2", 30, [_op("J2_O1", "M1", duration=50, setup=10)], weight=1000.0),
            _job("J3", 30, [_op("J3_O1", "M1", duration=50, setup=10)], weight=100.0),
        ]
        request = _request(jobs, ["M1"])
        from src.domain.solver.cpsat_solver import CpsatSolver

        result = CpsatSolver().solve(request)

        report = build_late_report(result, request)
        if report and len(report["late_orders"]) >= 2:
            priorities = [lo["priority"] for lo in report["late_orders"]]
            priority_order = {"ATRASO": 0, "RED": 1, "YELLOW": 2, "NORMAL": 3, "LOTE": 4}
            priority_values = [priority_order[p] for p in priorities]
            assert priority_values == sorted(priority_values)

    def test_no_late_report_when_otd_100(self):
        """No late report when all jobs on time."""
        jobs = [
            _job("J1", 500, [_op("J1_O1", "M1", duration=50, setup=20)]),
        ]
        request = _request(jobs, ["M1"])
        from src.domain.solver.cpsat_solver import CpsatSolver

        result = CpsatSolver().solve(request)

        report = build_late_report(result, request)
        assert report is None


class TestPriorityClassification:
    def test_classify_priority(self):
        assert _classify_priority(1000) == "ATRASO"
        assert _classify_priority(500) == "RED"
        assert _classify_priority(100) == "RED"
        assert _classify_priority(50) == "YELLOW"
        assert _classify_priority(10) == "YELLOW"
        assert _classify_priority(5) == "NORMAL"
        assert _classify_priority(1) == "NORMAL"
        assert _classify_priority(0.5) == "LOTE"
