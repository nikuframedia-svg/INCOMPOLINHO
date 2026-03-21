# Tests for CP-SAT Solver + Heuristic Fallback + Router + Factory Constraints
# Conforme Contrato C4

from __future__ import annotations

from src.domain.solver.cpsat_solver import CpsatSolver
from src.domain.solver.router_logic import SolverRouter
from src.domain.solver.schemas import (
    ConstraintConfigInput,
    JobInput,
    MachineInput,
    OperationInput,
    ShiftConfig,
    SolverConfig,
    SolverRequest,
    TwinPairInput,
)


def _make_op(op_id, machine_id, tool_id="T1", duration=60, setup=15, calco=None):
    return OperationInput(
        id=op_id,
        machine_id=machine_id,
        tool_id=tool_id,
        duration_min=duration,
        setup_min=setup,
        operators=1,
        calco_code=calco,
    )


def _make_job(job_id, sku, due_date, weight, ops):
    return JobInput(id=job_id, sku=sku, due_date_min=due_date, weight=weight, operations=ops)


def _make_request(
    jobs,
    machines,
    objective="weighted_tardiness",
    time_limit=10,
    constraints=None,
    twin_pairs=None,
    shifts=None,
    workdays=None,
):
    return SolverRequest(
        jobs=jobs,
        machines=machines,
        config=SolverConfig(time_limit_s=time_limit, objective=objective, num_workers=1),
        constraints=constraints or ConstraintConfigInput(),
        twin_pairs=twin_pairs or [],
        shifts=shifts or ShiftConfig(),
        workdays=workdays or [],
    )


class TestCpsatSolver:
    def setup_method(self):
        self.solver = CpsatSolver()

    def test_small_problem_5_ops(self):
        """2 jobs × ~2 ops on 2 machines → optimal solution."""
        jobs = [
            _make_job(
                "J1",
                "SKU1",
                200,
                1.0,
                [
                    _make_op("J1_O1", "M1", duration=50, setup=10),
                    _make_op("J1_O2", "M2", duration=40, setup=10),
                ],
            ),
            _make_job(
                "J2",
                "SKU2",
                300,
                1.0,
                [
                    _make_op("J2_O1", "M2", duration=60, setup=10),
                    _make_op("J2_O2", "M1", duration=30, setup=10),
                ],
            ),
        ]
        machines = [MachineInput(id="M1"), MachineInput(id="M2")]
        request = _make_request(jobs, machines)

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        assert result.solver_used == "cpsat"
        assert result.n_ops == 4
        assert len(result.schedule) == 4

    def test_no_overlap_constraint(self):
        """All ops on same machine → no overlapping intervals."""
        jobs = [
            _make_job("J1", "SKU1", 500, 1.0, [_make_op("J1_O1", "M1", duration=100)]),
            _make_job("J2", "SKU2", 500, 1.0, [_make_op("J2_O1", "M1", duration=100)]),
            _make_job("J3", "SKU3", 500, 1.0, [_make_op("J3_O1", "M1", duration=100)]),
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(jobs, machines)

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        # Check no overlaps
        m1_ops = sorted(result.schedule, key=lambda s: s.start_min)
        for i in range(len(m1_ops) - 1):
            assert m1_ops[i].end_min <= m1_ops[i + 1].start_min, (
                f"Overlap: {m1_ops[i].op_id} ends at {m1_ops[i].end_min} but {m1_ops[i + 1].op_id} starts at {m1_ops[i + 1].start_min}"
            )

    def test_precedence_within_job(self):
        """Operations within a job must be in order."""
        jobs = [
            _make_job(
                "J1",
                "SKU1",
                500,
                1.0,
                [
                    _make_op("J1_O1", "M1", duration=50),
                    _make_op("J1_O2", "M2", duration=50),
                    _make_op("J1_O3", "M1", duration=50),
                ],
            ),
        ]
        machines = [MachineInput(id="M1"), MachineInput(id="M2")]
        request = _make_request(jobs, machines)

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        op_map = {s.op_id: s for s in result.schedule}
        assert op_map["J1_O1"].end_min <= op_map["J1_O2"].start_min
        assert op_map["J1_O2"].end_min <= op_map["J1_O3"].start_min

    def test_makespan_objective(self):
        """Makespan objective minimizes max completion time."""
        jobs = [
            _make_job(
                "J1", "SKU1", 1000, 1.0, [_make_op("J1_O1", "M1", "T1", duration=100, setup=0)]
            ),
            _make_job(
                "J2", "SKU2", 1000, 1.0, [_make_op("J2_O1", "M2", "T2", duration=100, setup=0)]
            ),
        ]
        machines = [MachineInput(id="M1"), MachineInput(id="M2")]
        request = _make_request(jobs, machines, objective="makespan")

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        # With 2 machines, 2 parallel jobs: makespan should be ~100
        assert result.makespan_min <= 110  # Allow small margin

    def test_tardiness_objective(self):
        """Tardiness objective tracks late jobs."""
        jobs = [
            _make_job("J1", "SKU1", 50, 1.0, [_make_op("J1_O1", "M1", duration=100, setup=0)]),
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(jobs, machines, objective="tardiness")

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        # Job takes 100min but due at 50min → 50min tardy
        assert result.total_tardiness_min == 50

    def test_weighted_tardiness(self):
        """Weighted tardiness uses job weights."""
        jobs = [
            _make_job("J1", "SKU1", 50, 2.0, [_make_op("J1_O1", "M1", duration=100, setup=0)]),
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(jobs, machines, objective="weighted_tardiness")

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        # 50min tardy × weight 2.0 = 100
        assert result.weighted_tardiness == 100.0

    def test_empty_input(self):
        """0 jobs → empty schedule."""
        request = _make_request([], [MachineInput(id="M1")])
        result = self.solver.solve(request)

        assert result.status == "optimal"
        assert result.n_ops == 0
        assert len(result.schedule) == 0
        assert result.makespan_min == 0

    def test_single_machine_sequential(self):
        """All ops on 1 machine → must be sequential."""
        jobs = [
            _make_job(
                f"J{i}", f"SKU{i}", 2000, 1.0, [_make_op(f"J{i}_O1", "M1", duration=50, setup=10)]
            )
            for i in range(5)
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(jobs, machines)

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        assert len(result.schedule) == 5
        # Circuit mode: all same tool T1, so only first op pays setup.
        # Total = 10 (first setup) + 5 × 50 (prod) = 260min
        # Must be at least 5 × 50 = 250 (pure production time)
        assert result.makespan_min >= 250


# ── SetupCrew Constraint Tests ──


class TestSetupCrewConstraint:
    def setup_method(self):
        self.solver = CpsatSolver()

    def test_setup_crew_no_concurrent_setups(self):
        """3 ops on different machines with setup → no two setups overlap."""
        jobs = [
            _make_job(
                "J1", "SKU1", 500, 1.0, [_make_op("J1_O1", "M1", "T1", duration=50, setup=30)]
            ),
            _make_job(
                "J2", "SKU2", 500, 1.0, [_make_op("J2_O1", "M2", "T2", duration=50, setup=30)]
            ),
            _make_job(
                "J3", "SKU3", 500, 1.0, [_make_op("J3_O1", "M3", "T3", duration=50, setup=30)]
            ),
        ]
        machines = [MachineInput(id="M1"), MachineInput(id="M2"), MachineInput(id="M3")]
        request = _make_request(
            jobs,
            machines,
            constraints=ConstraintConfigInput(setup_crew=True),
        )

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        # Extract setup windows: [start, start+setup_min)
        setup_windows = []
        for s in result.schedule:
            if s.setup_min > 0:
                setup_windows.append((s.start_min, s.start_min + s.setup_min, s.op_id))

        # Verify no two setup windows overlap
        setup_windows.sort()
        for i in range(len(setup_windows) - 1):
            _, end_i, id_i = setup_windows[i]
            start_j, _, id_j = setup_windows[i + 1]
            assert end_i <= start_j, (
                f"Setup overlap: {id_i} setup ends at {end_i} but {id_j} setup starts at {start_j}"
            )

    def test_setup_crew_delays_correctly(self):
        """2 ops with long setups on different machines → one must wait."""
        jobs = [
            _make_job(
                "J1", "SKU1", 500, 1.0, [_make_op("J1_O1", "M1", "T1", duration=10, setup=60)]
            ),
            _make_job(
                "J2", "SKU2", 500, 1.0, [_make_op("J2_O1", "M2", "T2", duration=10, setup=60)]
            ),
        ]
        machines = [MachineInput(id="M1"), MachineInput(id="M2")]
        request = _make_request(
            jobs,
            machines,
            constraints=ConstraintConfigInput(setup_crew=True),
        )

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        ops = {s.op_id: s for s in result.schedule}
        # One must start after the other's setup finishes (at least 60min apart)
        starts = sorted([ops["J1_O1"].start_min, ops["J2_O1"].start_min])
        assert starts[1] >= starts[0] + 60, (
            f"Second op should wait for setup crew: starts at {starts}"
        )

    def test_setup_crew_disabled(self):
        """With SetupCrew disabled, setups CAN overlap (parallel on different machines)."""
        jobs = [
            _make_job(
                "J1", "SKU1", 500, 1.0, [_make_op("J1_O1", "M1", "T1", duration=10, setup=60)]
            ),
            _make_job(
                "J2", "SKU2", 500, 1.0, [_make_op("J2_O1", "M2", "T2", duration=10, setup=60)]
            ),
        ]
        machines = [MachineInput(id="M1"), MachineInput(id="M2")]
        request = _make_request(
            jobs,
            machines,
            objective="makespan",
            constraints=ConstraintConfigInput(setup_crew=False),
        )

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        # Both can run in parallel: makespan should be ~70 (60 setup + 10 prod)
        assert result.makespan_min <= 75


# ── ToolTimeline Constraint Tests ──


class TestToolTimelineConstraint:
    def setup_method(self):
        self.solver = CpsatSolver()

    def test_tool_timeline_cross_machine(self):
        """Same tool on different machines → no time overlap."""
        jobs = [
            _make_job(
                "J1",
                "SKU1",
                500,
                1.0,
                [_make_op("J1_O1", "M1", "SHARED_TOOL", duration=80, setup=0)],
            ),
            _make_job(
                "J2",
                "SKU2",
                500,
                1.0,
                [_make_op("J2_O1", "M2", "SHARED_TOOL", duration=80, setup=0)],
            ),
        ]
        machines = [MachineInput(id="M1"), MachineInput(id="M2")]
        request = _make_request(
            jobs,
            machines,
            objective="makespan",
            constraints=ConstraintConfigInput(tool_timeline=True),
        )

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        ops = {s.op_id: s for s in result.schedule}
        # Must be sequential (tool can't be in two places)
        a, b = ops["J1_O1"], ops["J2_O1"]
        assert a.end_min <= b.start_min or b.end_min <= a.start_min, (
            f"Tool overlap: J1=[{a.start_min},{a.end_min}] J2=[{b.start_min},{b.end_min}]"
        )

    def test_tool_timeline_same_machine_ok(self):
        """Same tool on same machine → sequential anyway (machine constraint)."""
        jobs = [
            _make_job(
                "J1", "SKU1", 500, 1.0, [_make_op("J1_O1", "M1", "T1", duration=50, setup=0)]
            ),
            _make_job(
                "J2", "SKU2", 500, 1.0, [_make_op("J2_O1", "M1", "T1", duration=50, setup=0)]
            ),
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(
            jobs,
            machines,
            constraints=ConstraintConfigInput(tool_timeline=True),
        )

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        assert len(result.schedule) == 2

    def test_tool_timeline_disabled(self):
        """With ToolTimeline disabled, same tool CAN be on 2 machines at once."""
        jobs = [
            _make_job(
                "J1",
                "SKU1",
                500,
                1.0,
                [_make_op("J1_O1", "M1", "SHARED_TOOL", duration=80, setup=0)],
            ),
            _make_job(
                "J2",
                "SKU2",
                500,
                1.0,
                [_make_op("J2_O1", "M2", "SHARED_TOOL", duration=80, setup=0)],
            ),
        ]
        machines = [MachineInput(id="M1"), MachineInput(id="M2")]
        request = _make_request(
            jobs,
            machines,
            objective="makespan",
            constraints=ConstraintConfigInput(tool_timeline=False),
        )

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        # Both can run in parallel
        assert result.makespan_min <= 85


# ── CalcoTimeline Constraint Tests ──


class TestCalcoTimelineConstraint:
    def setup_method(self):
        self.solver = CpsatSolver()

    def test_calco_no_overlap(self):
        """Same calço on different machines → no overlap."""
        jobs = [
            _make_job(
                "J1",
                "SKU1",
                500,
                1.0,
                [
                    _make_op("J1_O1", "M1", "T1", duration=80, setup=0, calco="CALCO_A"),
                ],
            ),
            _make_job(
                "J2",
                "SKU2",
                500,
                1.0,
                [
                    _make_op("J2_O1", "M2", "T2", duration=80, setup=0, calco="CALCO_A"),
                ],
            ),
        ]
        machines = [MachineInput(id="M1"), MachineInput(id="M2")]
        request = _make_request(
            jobs,
            machines,
            objective="makespan",
            constraints=ConstraintConfigInput(calco_timeline=True),
        )

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        ops = {s.op_id: s for s in result.schedule}
        a, b = ops["J1_O1"], ops["J2_O1"]
        assert a.end_min <= b.start_min or b.end_min <= a.start_min, (
            f"Calco overlap: J1=[{a.start_min},{a.end_min}] J2=[{b.start_min},{b.end_min}]"
        )

    def test_calco_none_ignored(self):
        """Ops with calco_code=None have no calco constraint → parallel OK."""
        jobs = [
            _make_job(
                "J1", "SKU1", 500, 1.0, [_make_op("J1_O1", "M1", "T1", duration=80, setup=0)]
            ),
            _make_job(
                "J2", "SKU2", 500, 1.0, [_make_op("J2_O1", "M2", "T2", duration=80, setup=0)]
            ),
        ]
        machines = [MachineInput(id="M1"), MachineInput(id="M2")]
        request = _make_request(
            jobs,
            machines,
            objective="makespan",
            constraints=ConstraintConfigInput(calco_timeline=True),
        )

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        # No calco codes → parallel OK
        assert result.makespan_min <= 85


# ── OperatorPool (Advisory) Tests ──


class TestOperatorPoolAdvisory:
    def setup_method(self):
        self.solver = CpsatSolver()

    def test_operator_warnings_generated(self):
        """Schedule exceeding operator capacity → warnings in result, schedule still produced."""
        jobs = [
            _make_job(
                "J1",
                "SKU1",
                500,
                1.0,
                [
                    OperationInput(
                        id="J1_O1",
                        machine_id="M1",
                        tool_id="T1",
                        duration_min=100,
                        setup_min=0,
                        operators=5,
                    ),
                ],
            ),
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(
            jobs,
            machines,
            constraints=ConstraintConfigInput(operator_pool=True),
            shifts=ShiftConfig(
                shift_x_start=0,
                shift_change=500,
                shift_y_end=1000,
                operators_by_machine_shift={"M1": {"X": 3}},
            ),
        )

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        assert len(result.schedule) == 1  # Schedule still produced
        assert len(result.operator_warnings) > 0
        assert result.operator_warnings[0]["type"] == "OPERATOR_CAPACITY_WARNING"

    def test_operator_no_warnings_within_capacity(self):
        """Schedule within capacity → no warnings."""
        jobs = [
            _make_job(
                "J1",
                "SKU1",
                500,
                1.0,
                [
                    OperationInput(
                        id="J1_O1",
                        machine_id="M1",
                        tool_id="T1",
                        duration_min=100,
                        setup_min=0,
                        operators=2,
                    ),
                ],
            ),
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(
            jobs,
            machines,
            constraints=ConstraintConfigInput(operator_pool=True),
            shifts=ShiftConfig(operators_by_machine_shift={"M1": {"X": 6}}),
        )

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        assert len(result.operator_warnings) == 0


# ── Twin Co-Production Tests ──


class TestTwinCoProduction:
    def setup_method(self):
        self.solver = CpsatSolver()

    def test_twin_same_start(self):
        """Twin pair ops must start at the same time."""
        jobs = [
            _make_job(
                "J1", "SKU_LH", 500, 1.0, [_make_op("J1_O1", "M1", "T1", duration=60, setup=15)]
            ),
            _make_job(
                "J2", "SKU_RH", 500, 1.0, [_make_op("J2_O1", "M1", "T1", duration=40, setup=15)]
            ),
        ]
        machines = [MachineInput(id="M1")]
        twins = [TwinPairInput(op_id_a="J1_O1", op_id_b="J2_O1", machine_id="M1", tool_id="T1")]
        request = _make_request(jobs, machines, twin_pairs=twins)

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        ops = {s.op_id: s for s in result.schedule}
        assert ops["J1_O1"].start_min == ops["J2_O1"].start_min, (
            f"Twin starts differ: {ops['J1_O1'].start_min} vs {ops['J2_O1'].start_min}"
        )

    def test_twin_shared_setup(self):
        """Twin pair uses one shared setup, not doubled."""
        jobs = [
            _make_job(
                "J1", "SKU_LH", 500, 1.0, [_make_op("J1_O1", "M1", "T1", duration=60, setup=20)]
            ),
            _make_job(
                "J2", "SKU_RH", 500, 1.0, [_make_op("J2_O1", "M1", "T1", duration=40, setup=20)]
            ),
        ]
        machines = [MachineInput(id="M1")]
        twins = [TwinPairInput(op_id_a="J1_O1", op_id_b="J2_O1", machine_id="M1", tool_id="T1")]
        request = _make_request(jobs, machines, twin_pairs=twins)

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        ops = {s.op_id: s for s in result.schedule}
        # Both start at same time. The longer op (60min) + setup (20min) = 80min total
        # NOT 2×20 setup + 60 = 100min
        longer_end = max(ops["J1_O1"].end_min, ops["J2_O1"].end_min)
        twin_start = ops["J1_O1"].start_min
        assert longer_end - twin_start <= 80 + 5  # Allow small margin

    def test_twin_machine_time_max(self):
        """Machine time = max(dur_a, dur_b), not sum."""
        jobs = [
            _make_job(
                "J1", "SKU_LH", 500, 1.0, [_make_op("J1_O1", "M1", "T1", duration=100, setup=0)]
            ),
            _make_job(
                "J2", "SKU_RH", 500, 1.0, [_make_op("J2_O1", "M1", "T1", duration=60, setup=0)]
            ),
            _make_job(
                "J3", "SKU3", 500, 1.0, [_make_op("J3_O1", "M1", "T2", duration=50, setup=0)]
            ),
        ]
        machines = [MachineInput(id="M1")]
        twins = [TwinPairInput(op_id_a="J1_O1", op_id_b="J2_O1", machine_id="M1", tool_id="T1")]
        request = _make_request(jobs, machines, objective="makespan", twin_pairs=twins)

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        # Twin pair takes 100min (max). J3 takes 50min. Total = 150.
        # If sum were used it would be 100+60+50=210.
        assert result.makespan_min <= 155  # max(100,60) + 50 + small margin

    def test_twin_flags_in_result(self):
        """Twin ops have is_twin_production=True and twin_partner_op_id set."""
        jobs = [
            _make_job(
                "J1", "SKU_LH", 500, 1.0, [_make_op("J1_O1", "M1", "T1", duration=60, setup=0)]
            ),
            _make_job(
                "J2", "SKU_RH", 500, 1.0, [_make_op("J2_O1", "M1", "T1", duration=40, setup=0)]
            ),
        ]
        machines = [MachineInput(id="M1")]
        twins = [TwinPairInput(op_id_a="J1_O1", op_id_b="J2_O1", machine_id="M1", tool_id="T1")]
        request = _make_request(jobs, machines, twin_pairs=twins)

        result = self.solver.solve(request)

        ops = {s.op_id: s for s in result.schedule}
        assert ops["J1_O1"].is_twin_production is True
        assert ops["J1_O1"].twin_partner_op_id == "J2_O1"
        assert ops["J2_O1"].is_twin_production is True
        assert ops["J2_O1"].twin_partner_op_id == "J1_O1"


# ── Combined Constraints Test ──


class TestCombinedConstraints:
    def setup_method(self):
        self.solver = CpsatSolver()

    def test_all_constraints_active(self):
        """All 4 constraints + twins active simultaneously → valid schedule."""
        jobs = [
            _make_job(
                "J1",
                "SKU_LH",
                800,
                1.0,
                [
                    _make_op("J1_O1", "M1", "T1", duration=60, setup=20, calco="C1"),
                ],
            ),
            _make_job(
                "J2",
                "SKU_RH",
                800,
                1.0,
                [
                    _make_op("J2_O1", "M1", "T1", duration=40, setup=20, calco="C1"),
                ],
            ),
            _make_job(
                "J3",
                "SKU3",
                800,
                1.0,
                [
                    _make_op("J3_O1", "M2", "T2", duration=50, setup=15, calco="C1"),
                ],
            ),
        ]
        machines = [MachineInput(id="M1"), MachineInput(id="M2")]
        twins = [TwinPairInput(op_id_a="J1_O1", op_id_b="J2_O1", machine_id="M1", tool_id="T1")]
        request = _make_request(
            jobs,
            machines,
            constraints=ConstraintConfigInput(
                setup_crew=True,
                tool_timeline=True,
                calco_timeline=True,
                operator_pool=True,
            ),
            twin_pairs=twins,
            shifts=ShiftConfig(operators_by_machine_shift={"M1": {"X": 6}, "M2": {"X": 6}}),
        )

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        assert len(result.schedule) == 3

        # Verify twins start together
        ops = {s.op_id: s for s in result.schedule}
        assert ops["J1_O1"].start_min == ops["J2_O1"].start_min

        # Verify calco C1 no overlap: twin pair and J3 must not overlap
        twin_end = max(ops["J1_O1"].end_min, ops["J2_O1"].end_min)
        j3 = ops["J3_O1"]
        assert twin_end <= j3.start_min or j3.end_min <= ops["J1_O1"].start_min, (
            f"Calco overlap: twin=[{ops['J1_O1'].start_min},{twin_end}] J3=[{j3.start_min},{j3.end_min}]"
        )


# ── SAT-01: JIT Earliness Penalty Tests ──


class TestJITEarlinessPenalty:
    def setup_method(self):
        self.solver = CpsatSolver()

    def test_jit_produces_late(self):
        """Job with deadline day 10 should be scheduled near deadline, not day 0."""
        DAY_CAP = 1020
        jobs = [
            _make_job(
                "J1",
                "SKU1",
                10 * DAY_CAP,  # due end of day 10
                1.0,
                [_make_op("J1_O1", "M1", "T1", duration=100, setup=15)],
            ),
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(jobs, machines)

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        sop = result.schedule[0]
        # JIT: should schedule in last 2-3 days (day 8-10), not day 0
        sop_day = sop.start_min // DAY_CAP
        assert sop_day >= 8, (
            f"JIT failed: job scheduled on day {sop_day}, expected near deadline (day 8-10)"
        )
        assert result.total_tardiness_min == 0, "JIT must never cause tardiness"

    def test_jit_never_late(self):
        """Earliness penalty must never cause a job to be late."""
        DAY_CAP = 1020
        # 3 jobs on 1 machine, tight deadlines — JIT shouldn't push past deadline
        jobs = [
            _make_job(
                "J1",
                "SKU1",
                2 * DAY_CAP,
                1.0,
                [_make_op("J1_O1", "M1", "T1", duration=400, setup=30)],
            ),
            _make_job(
                "J2",
                "SKU2",
                3 * DAY_CAP,
                1.0,
                [_make_op("J2_O1", "M1", "T2", duration=400, setup=30)],
            ),
            _make_job(
                "J3",
                "SKU3",
                4 * DAY_CAP,
                1.0,
                [_make_op("J3_O1", "M1", "T3", duration=400, setup=30)],
            ),
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(jobs, machines)

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        # With 1000:1 weight ratio, tardiness dominates — 0 tardiness expected
        assert result.total_tardiness_min == 0, (
            f"JIT caused tardiness: {result.total_tardiness_min} min"
        )


# ── SAT-04: Day Capacity + Shift Boundary Tests ──


class TestDayShiftConstraints:
    def setup_method(self):
        self.solver = CpsatSolver()

    def test_no_shift_crossing(self):
        """No operation crosses the shift boundary at 510 min within a day."""
        # 4 ops of 200 min each on 1 machine — must fit within shifts
        jobs = [
            _make_job(
                f"J{i}",
                f"SKU{i}",
                4 * 1020,  # due end of day 4
                1.0,
                [_make_op(f"J{i}_O1", "M1", f"T{i}", duration=200, setup=30)],
            )
            for i in range(4)
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(jobs, machines)

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        DAY_CAP = 1020
        SHIFT_LEN = 510
        for sop in result.schedule:
            start_in_day = sop.start_min % DAY_CAP
            size = sop.end_min - sop.start_min
            if size <= SHIFT_LEN:
                # Must be entirely in shift X or entirely in shift Y
                end_in_day = start_in_day + size
                in_x = end_in_day <= SHIFT_LEN
                in_y = start_in_day >= SHIFT_LEN
                assert in_x or in_y, (
                    f"{sop.op_id} crosses shift boundary: start_in_day={start_in_day}, "
                    f"end_in_day={end_in_day}, size={size}"
                )

    def test_no_day_crossing(self):
        """No operation crosses a day boundary (DAY_CAP=1020)."""
        # 6 ops of 300 min each across 2 machines — force multi-day schedule
        jobs = [
            _make_job(
                f"J{i}",
                f"SKU{i}",
                5 * 1020,  # due end of day 5
                1.0,
                [_make_op(f"J{i}_O1", f"M{i % 2 + 1}", f"T{i}", duration=300, setup=30)],
            )
            for i in range(6)
        ]
        machines = [MachineInput(id="M1"), MachineInput(id="M2")]
        request = _make_request(jobs, machines)

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        DAY_CAP = 1020
        for sop in result.schedule:
            start_day = sop.start_min // DAY_CAP
            end_day = (sop.end_min - 1) // DAY_CAP if sop.end_min > 0 else start_day
            assert start_day == end_day, (
                f"{sop.op_id} crosses day boundary: starts day {start_day} "
                f"(min={sop.start_min}), ends day {end_day} (min={sop.end_min})"
            )

    def test_day_capacity_1020(self):
        """Max 1020 min of work per day per machine."""
        # 3 ops of 400 min each on 1 machine — can't all fit in 1 day (1200 > 1020)
        jobs = [
            _make_job(
                f"J{i}",
                f"SKU{i}",
                5 * 1020,
                1.0,
                [_make_op(f"J{i}_O1", "M1", f"T{i}", duration=400, setup=0)],
            )
            for i in range(3)
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(jobs, machines)

        result = self.solver.solve(request)

        assert result.status in ("optimal", "feasible")
        DAY_CAP = 1020
        # Group ops by day
        from collections import defaultdict

        day_load: dict[int, int] = defaultdict(int)
        for sop in result.schedule:
            day = sop.start_min // DAY_CAP
            size = sop.end_min - sop.start_min
            day_load[day] += size
        for day, load in day_load.items():
            assert load <= DAY_CAP, (
                f"Day {day} on M1 has {load} min of work, exceeds DAY_CAP={DAY_CAP}"
            )


# ── FINAL-01: Weekend Exclusion Tests ──


class TestWeekendExclusion:
    def setup_method(self):
        self.solver = CpsatSolver()

    def test_workdays_reduces_horizon(self):
        """With workdays=[0,1,2,3,4] (5 days), horizon = 5 × 1020 = 5100."""
        DAY_CAP = 1020
        workdays = [0, 1, 2, 3, 4]  # Mon-Fri, skip Sat(5), Sun(6)
        jobs = [
            _make_job(
                "J1",
                "SKU1",
                3 * DAY_CAP,
                1.0,
                [_make_op("J1_O1", "M1", "T1", duration=200, setup=30)],
            ),
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(jobs, machines, workdays=workdays)

        result = self.solver.solve(request)
        assert result.status in ("optimal", "feasible")
        # Job should be scheduled within workday range
        sop = result.schedule[0]
        assert sop.start_min < len(workdays) * DAY_CAP

    def test_no_weekend_scheduling(self):
        """With workdays skipping days 5,6 (weekend), no ops on solver day >= 5 in a 7-day calendar."""
        DAY_CAP = 1020
        # 7 calendar days, only 5 are workdays (skip Sat=5, Sun=6)
        workdays = [0, 1, 2, 3, 4]  # 5 workdays
        # 4 jobs need ~2 days of machine time total → fits in 5 workdays
        jobs = [
            _make_job(
                f"J{i}",
                f"SKU{i}",
                (i + 1) * DAY_CAP,  # due on workday 1,2,3,4
                1.0,
                [_make_op(f"J{i}_O1", "M1", f"T{i}", duration=200, setup=30)],
            )
            for i in range(4)
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(jobs, machines, workdays=workdays)

        result = self.solver.solve(request)
        assert result.status in ("optimal", "feasible")
        # All ops must be within workday slots (0..4)
        for sop in result.schedule:
            solver_day = sop.start_min // DAY_CAP
            assert solver_day < len(workdays), (
                f"{sop.op_id} scheduled on solver day {solver_day} "
                f"but only {len(workdays)} workdays available"
            )

    def test_workdays_backward_compat(self):
        """Empty workdays[] behaves same as before (all days working)."""
        DAY_CAP = 1020
        jobs = [
            _make_job(
                "J1",
                "SKU1",
                3 * DAY_CAP,
                1.0,
                [_make_op("J1_O1", "M1", "T1", duration=200, setup=30)],
            ),
        ]
        machines = [MachineInput(id="M1")]

        # With empty workdays (backward compat)
        request_old = _make_request(jobs, machines)
        result_old = self.solver.solve(request_old)

        # With explicit workdays covering same range
        # Should still work
        assert result_old.status in ("optimal", "feasible")
        assert result_old.total_tardiness_min == 0

    def test_weekend_capacity_correct(self):
        """With 10 calendar days (8 workdays), capacity = 8 × 1020 = 8160 per machine."""
        DAY_CAP = 1020
        # 10 calendar days, weekends on day 5,6 → 8 workdays
        workdays = [0, 1, 2, 3, 4, 7, 8, 9]
        # Need 7 workdays of machine time → fits in 8 but NOT in 5
        jobs = [
            _make_job(
                f"J{i}",
                f"SKU{i}",
                8 * DAY_CAP,  # due on last workday
                1.0,
                [_make_op(f"J{i}_O1", "M1", f"T{i}", duration=500, setup=30)],
            )
            for i in range(7)
        ]
        machines = [MachineInput(id="M1")]
        request = _make_request(jobs, machines, workdays=workdays)

        result = self.solver.solve(request)
        assert result.status in ("optimal", "feasible")
        # Verify no op exceeds workday range
        max_end = max(sop.end_min for sop in result.schedule)
        assert max_end <= len(workdays) * DAY_CAP


class TestSolverRouter:
    def setup_method(self):
        self.router = SolverRouter()

    def test_router_small_uses_cpsat(self):
        """<50 ops → CP-SAT."""
        jobs = [
            _make_job("J1", "SKU1", 500, 1.0, [_make_op("J1_O1", "M1", duration=60)])
            for _ in range(5)
        ]
        # Fix unique IDs
        for i, j in enumerate(jobs):
            j.id = f"J{i}"
            j.operations[0].id = f"J{i}_O1"

        machines = [MachineInput(id="M1")]
        request = _make_request(jobs, machines)

        result = self.router.solve(request)
        assert result.solver_used == "cpsat"

    def test_router_large_uses_cpsat(self):
        """>200 ops → CP-SAT with 60s time limit."""
        jobs = []
        for i in range(210):
            jobs.append(
                _make_job(
                    f"J{i}",
                    f"SKU{i}",
                    50000,
                    1.0,
                    [_make_op(f"J{i}_O1", f"M{i % 5}", duration=10, setup=2)],
                )
            )
        machines = [MachineInput(id=f"M{i}") for i in range(5)]
        request = _make_request(jobs, machines, time_limit=60)

        result = self.router.solve(request)
        assert result.solver_used == "cpsat"
        assert result.n_ops == 210

    def test_router_empty(self):
        """0 jobs → handled gracefully."""
        request = _make_request([], [MachineInput(id="M1")])
        result = self.router.solve(request)
        assert result.n_ops == 0
        assert result.status == "optimal"
