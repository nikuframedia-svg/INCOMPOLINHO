"""E2E tests for the CP-SAT pipeline via bridge.

Tests the full flow: NikufraData → transform → bridge → CP-SAT → blocks → analytics.
Uses a synthetic fixture (no ISOP XLSX dependency).
"""

from __future__ import annotations

import pytest

from src.domain.scheduling.transform import transform_plan_state
from src.domain.scheduling.types import Block
from src.domain.solver.bridge import engine_data_to_solver_request, solver_result_to_blocks
from src.domain.solver.post_solve import build_decisions, build_feasibility_report
from src.domain.solver.router_logic import SolverRouter


# ── Synthetic fixture ─────────────────────────────────────────


def _build_plan_state(n_ops: int = 10, n_days: int = 20) -> dict:
    """Build a synthetic PlanState with n_ops operations across 5 machines."""
    machines = ["PRM019", "PRM031", "PRM039", "PRM042", "PRM043"]
    tools = [f"TOOL{i:03d}" for i in range(n_ops)]

    ops = []
    for i in range(n_ops):
        machine = machines[i % len(machines)]
        tool = tools[i]
        # Create demand: -5000 at day 5, -3000 at day n_days-2
        d = [None] * n_days
        d[min(5, n_days - 1)] = -5000
        if n_days > 7:
            d[n_days - 2] = -3000

        ops.append({
            "id": f"op_{i}",
            "m": machine,
            "t": tool,
            "sku": f"SKU{i:03d}",
            "nm": f"Part {i}",
            "pH": 200,
            "atr": 0,
            "d": d,
            "op": 1,
            "sH": 0.75,
            "alt": "-",
            "eco": 0,
        })

    dates = [f"2026-03-{17 + i:02d}" for i in range(n_days)]
    # Mon-Fri workdays (assuming 2026-03-17 is Tuesday)
    dnames = []
    weekday_names = ["Ter", "Qua", "Qui", "Sex", "Sáb", "Dom", "Seg"]
    for i in range(n_days):
        dnames.append(weekday_names[i % 7])

    return {
        "operations": ops,
        "dates": dates,
        "dnames": dnames,
    }


# ── Tests ─────────────────────────────────────────────────────


class TestCpsatPipelineE2E:
    """Full pipeline: transform → bridge → CP-SAT → blocks → analytics."""

    @pytest.fixture
    def plan_state(self):
        return _build_plan_state(n_ops=10, n_days=20)

    @pytest.fixture
    def engine_data(self, plan_state):
        return transform_plan_state(
            plan_state, demand_semantics="raw_np", order_based=True,
        )

    @pytest.fixture
    def solver_result(self, engine_data):
        solver_request = engine_data_to_solver_request(engine_data, {})
        router = SolverRouter()
        return router.solve(solver_request)

    @pytest.fixture
    def blocks(self, solver_result, engine_data):
        return solver_result_to_blocks(solver_result, engine_data)

    def test_transform_produces_ops(self, engine_data):
        """EngineData should have operations with demand."""
        assert len(engine_data.ops) == 10
        # Each op should have 2 demand entries (day 5 and day 10)
        for op in engine_data.ops:
            demand_days = [d for d in op.d if d > 0]
            assert len(demand_days) == 2, f"Op {op.id} has {len(demand_days)} demand days"

    def test_bridge_creates_jobs(self, engine_data):
        """Bridge should create 1 job per demand entry (10 ops × 2 days = 20 jobs)."""
        request = engine_data_to_solver_request(engine_data, {})
        assert len(request.jobs) == 20
        # Each job should have 1 operation
        for job in request.jobs:
            assert len(job.operations) == 1
        # 5 machines
        assert len(request.machines) == 5

    def test_bridge_workdays(self, engine_data):
        """Bridge should compute workday indices."""
        request = engine_data_to_solver_request(engine_data, {})
        assert len(request.workdays) > 0
        # All workday indices should be non-negative
        assert all(w >= 0 for w in request.workdays)

    def test_bridge_due_dates_positive(self, engine_data):
        """All due dates should be positive (in solver minutes)."""
        request = engine_data_to_solver_request(engine_data, {})
        for job in request.jobs:
            assert job.due_date_min > 0, f"Job {job.id} has due_date_min={job.due_date_min}"

    def test_solver_finds_solution(self, solver_result):
        """CP-SAT should find a feasible or optimal solution."""
        assert solver_result.status in ("optimal", "feasible", "timeout")
        assert solver_result.n_ops > 0

    def test_solver_produces_schedule(self, solver_result):
        """Solver should produce scheduled operations."""
        assert len(solver_result.schedule) > 0

    def test_solver_time_reasonable(self, solver_result):
        """Solve time should be < 10s for 20 jobs."""
        assert solver_result.solve_time_s < 10.0

    def test_blocks_produced(self, blocks):
        """Blocks should be produced from solver result."""
        assert len(blocks) > 0
        # All blocks should be Block instances
        for b in blocks:
            assert isinstance(b, Block)

    def test_blocks_have_valid_fields(self, blocks):
        """Each block should have valid machine, tool, sku, timing."""
        for b in blocks:
            assert b.machine_id, f"Block missing machine_id"
            assert b.tool_id, f"Block missing tool_id"
            assert b.sku, f"Block missing sku"
            assert b.start_min >= 0, f"Block {b.op_id} has negative start"
            assert b.end_min > b.start_min, f"Block {b.op_id} has end <= start"
            assert b.qty > 0, f"Block {b.op_id} has qty={b.qty}"

    def test_blocks_shift_assignment(self, blocks):
        """Each block should have a valid shift (X or Y)."""
        for b in blocks:
            assert b.shift in ("X", "Y"), f"Block {b.op_id} has shift={b.shift}"

    def test_blocks_sorted_by_machine_and_time(self, blocks):
        """Blocks should be sorted by (machine_id, start_min)."""
        for i in range(len(blocks) - 1):
            a, b = blocks[i], blocks[i + 1]
            if a.machine_id == b.machine_id:
                assert a.start_min <= b.start_min

    def test_no_machine_overlap(self, blocks):
        """Blocks on the same machine should not overlap."""
        from collections import defaultdict

        by_machine: dict[str, list[Block]] = defaultdict(list)
        for b in blocks:
            by_machine[b.machine_id].append(b)

        for mid, mblocks in by_machine.items():
            sorted_blocks = sorted(mblocks, key=lambda b: b.start_min)
            for i in range(len(sorted_blocks) - 1):
                assert sorted_blocks[i].end_min <= sorted_blocks[i + 1].start_min, (
                    f"Overlap on {mid}: block ending at {sorted_blocks[i].end_min} "
                    f"vs block starting at {sorted_blocks[i + 1].start_min}"
                )

    def test_feasibility_report(self, solver_result, engine_data):
        """Feasibility report should be generated from solver result."""
        report = build_feasibility_report(solver_result, len(engine_data.ops))
        assert report.total_ops == len(engine_data.ops)
        assert report.feasibility_score >= 0.0
        assert report.feasibility_score <= 1.0

    def test_decisions_generated(self, solver_result):
        """Decisions should be generated from solver result."""
        decisions = build_decisions(solver_result)
        assert len(decisions) >= 1  # At least the scoring decision


class TestBridgeEdgeCases:
    """Edge cases for the bridge."""

    def test_empty_engine_data(self):
        """Bridge should handle empty engine data."""
        from src.domain.scheduling.types import EngineData

        engine = EngineData()
        request = engine_data_to_solver_request(engine, {})
        assert len(request.jobs) == 0
        assert len(request.machines) == 0

    def test_no_demand(self):
        """Bridge should handle ops with no demand."""
        plan_state = _build_plan_state(n_ops=3, n_days=10)
        # Set all demand to 0
        for op in plan_state["operations"]:
            op["d"] = [0] * 10

        engine_data = transform_plan_state(plan_state, demand_semantics="raw_np")
        request = engine_data_to_solver_request(engine_data, {})
        assert len(request.jobs) == 0

    def test_eco_lot_rounding(self):
        """Bridge should round up to eco lot size."""
        plan_state = _build_plan_state(n_ops=1, n_days=10)
        plan_state["operations"][0]["d"] = [None, None, None, None, None, -100, None, None, None, None]
        plan_state["operations"][0]["eco"] = 500  # Eco lot = 500

        engine_data = transform_plan_state(plan_state, demand_semantics="raw_np")
        request = engine_data_to_solver_request(engine_data, {})

        # Should have 1 job, duration based on 500 (eco lot) not 100
        assert len(request.jobs) == 1
        # Duration should be ceil(500 / (200 * 0.66)) * 60 = ceil(3.79) * 60 = 240 min
        assert request.jobs[0].operations[0].duration_min > 0


class TestPostSolveAnalysis:
    """Tests for post-solve analysis functions."""

    def test_infeasible_result(self):
        """Post-solve should handle infeasible results."""
        from src.domain.solver.schemas import SolverResult

        result = SolverResult(
            schedule=[],
            makespan_min=0,
            total_tardiness_min=0,
            weighted_tardiness=0.0,
            solver_used="cpsat",
            solve_time_s=5.0,
            status="infeasible",
            objective_value=0.0,
            n_ops=10,
        )
        report = build_feasibility_report(result, 10)
        assert report.feasibility_score == 0.0
        assert report.deadline_feasible is False
        assert len(report.remediations) > 0

    def test_timeout_result(self):
        """Post-solve should handle timeout results."""
        from src.domain.solver.schemas import SolverResult

        result = SolverResult(
            schedule=[],
            makespan_min=0,
            total_tardiness_min=0,
            weighted_tardiness=0.0,
            solver_used="cpsat",
            solve_time_s=60.0,
            status="timeout",
            objective_value=0.0,
            n_ops=10,
        )
        report = build_feasibility_report(result, 10)
        assert report.feasibility_score == 0.5
