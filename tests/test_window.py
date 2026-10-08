"""Regressions for the immutable five-working-day JIT policy."""

from __future__ import annotations

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.explainability import annotate_left_shift_blockers
from backend.scheduler.gates import build_gate_report
from backend.scheduler.scoring import compute_score
from backend.scheduler.jit_policy import calendar_holidays
from backend.scheduler.scheduler import (
    _compact_segments,
    _fix_day_overlaps,
    _interrupts_higher_priority_campaign,
    _left_shift_lots_into_empty_workdays,
    _sanitize_segments,
    schedule_all,
)
from backend.scheduler.types import Lot, Segment
from backend.scheduler.window import (
    compute_lot_floor,
    compute_window_gates,
    effective_earliness_target,
)
from backend.types import EngineData, EOp, MachineInfo


def _eop(
    op_id: str = "T1_M1_SKU1",
    sku: str = "SKU1",
    machine: str = "M1",
    tool: str = "T1",
    d: list[int] | None = None,
    pH: float = 100.0,
    sH: float = 0.5,
    oee: float = 0.66,
    alt: str | None = None,
) -> EOp:
    return EOp(
        id=op_id,
        sku=sku,
        client="CLIENT",
        designation="Test",
        m=machine,
        t=tool,
        pH=pH,
        sH=sH,
        operators=1,
        eco_lot=0,
        alt=alt,
        stk=0,
        backlog=0,
        d=d or [0] * 12,
        oee=oee,
        wip=0,
    )


def _engine(ops: list[EOp], n_days: int = 12, holidays: list[int] | None = None) -> EngineData:
    machine_ids: list[str] = []
    for op in ops:
        if op.m not in machine_ids:
            machine_ids.append(op.m)
        if op.alt and op.alt not in machine_ids:
            machine_ids.append(op.alt)
    machines = [MachineInfo(id=m, group="Grandes", day_capacity=DAY_CAP) for m in machine_ids]
    return EngineData(
        ops=ops,
        machines=machines,
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-03-{i + 2:02d}" for i in range(n_days)],
        n_days=n_days,
        holidays=holidays or [],
    )


def _lot(lot_id: str = "L1", edd: int = 8, prod_min: float = 300.0) -> Lot:
    return Lot(
        id=lot_id,
        op_id="T1_M1_SKU1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=prod_min,
        setup_min=30.0,
        edd=edd,
        is_twin=False,
    )


class TestFloorArithmetic:
    def test_floor_simple(self):
        assert compute_lot_floor(_lot(edd=8), set(), 5) == 3

    def test_floor_skips_holidays(self):
        # Holidays at 5 and 6 → need 2 extra days back
        assert compute_lot_floor(_lot(edd=8), {5, 6}, 5) == 1

    def test_floor_can_precede_visible_horizon(self):
        assert compute_lot_floor(_lot(edd=3), set(), 5) == -2

    def test_lot_bigger_than_window_never_relaxes_floor(self):
        config = FactoryConfig(earliness_policy="window", material_release_days=2)
        big = _lot(edd=8, prod_min=3 * 1020.0)
        run_gates, lot_floors = compute_window_gates(
            {"M1": [_run_of(big)]}, set(), config
        )
        assert lot_floors[big.id] == (8 - 5) * 1020.0
        assert run_gates[_run_of(big).id] >= lot_floors[big.id] - big.setup_min


class TestLeftShiftExplainability:
    def test_gap_repair_cannot_interrupt_a_more_urgent_open_campaign(self):
        urgent = _lot("urgent", edd=8, prod_min=200)
        later = _lot("later", edd=10, prod_min=100)
        urgent_segments = [
            Segment(
                lot_id=urgent.id,
                run_id="urgent-run",
                machine_id="M1",
                tool_id="T1",
                day_idx=3,
                start_min=420,
                end_min=520,
                shift="A",
                qty=50,
                prod_min=100,
            ),
            Segment(
                lot_id=urgent.id,
                run_id="urgent-run",
                machine_id="M1",
                tool_id="T1",
                day_idx=7,
                start_min=420,
                end_min=520,
                shift="A",
                qty=50,
                prod_min=100,
                is_continuation=True,
            ),
        ]

        assert _interrupts_higher_priority_campaign(
            urgent_segments,
            {urgent.id: urgent, later.id: later},
            later,
            machine_id="M1",
            day_idx=5,
            start_min=420,
            end_min=550,
        )

    def test_gap_repair_may_use_capacity_after_urgent_campaign_finishes(self):
        urgent = _lot("urgent", edd=8, prod_min=100)
        later = _lot("later", edd=10, prod_min=100)
        urgent_segment = Segment(
            lot_id=urgent.id,
            run_id="urgent-run",
            machine_id="M1",
            tool_id="T1",
            day_idx=3,
            start_min=420,
            end_min=520,
            shift="A",
            qty=100,
            prod_min=100,
        )

        assert not _interrupts_higher_priority_campaign(
            [urgent_segment],
            {urgent.id: urgent, later.id: later},
            later,
            machine_id="M1",
            day_idx=5,
            start_min=420,
            end_min=550,
        )

    def test_first_permitted_day_reports_jit_floor(self):
        lot = _lot(edd=8)
        segment = Segment(
            lot_id=lot.id, run_id="run", machine_id="M1", tool_id="T1",
            day_idx=3, start_min=420, end_min=720, shift="A", qty=100,
            prod_min=300, sku="SKU1",
        )

        annotate_left_shift_blockers([segment], [lot], _engine([_eop()]), FactoryConfig())

        assert segment.left_shift_blockers[0] == "blocked_by_material_release"
        assert (
            "blocked_by_material_release|day=3|date=2026-03-05|interval=07:00-07:00"
            in segment.left_shift_blockers
        )
        assert segment.material_release_day == 3
        assert segment.release_delay_workdays == 0

    def test_higher_risk_lot_explains_occupied_previous_day(self):
        urgent = _lot("urgent", edd=7)
        later = _lot("later", edd=8)
        urgent_segment = Segment(
            lot_id=urgent.id, run_id="urgent-run", machine_id="M1", tool_id="T2",
            day_idx=3, start_min=420, end_min=1440, shift="A", qty=100,
            prod_min=1020, sku="SKU1",
        )
        later_segment = Segment(
            lot_id=later.id, run_id="later-run", machine_id="M1", tool_id="T1",
            day_idx=4, start_min=420, end_min=720, shift="A", qty=100,
            prod_min=300, sku="SKU1",
        )
        data = _engine([_eop(tool="T1"), _eop(op_id="T2_M1_URGENT", tool="T2")])

        annotate_left_shift_blockers(
            [urgent_segment, later_segment], [urgent, later], data, FactoryConfig()
        )

        assert "blocked_by_priority_higher_risk_lot" in later_segment.left_shift_blockers
        assert "blocked_by_machine_busy" in later_segment.left_shift_blockers
        assert any(
            reason.startswith("blocked_by_priority_higher_risk_lot|day=3|")
            and "interval=07:00-00:00" in reason
            and "lot=urgent" in reason
            and "target_rupture=8" in reason
            and "competing_rupture=7" in reason
            for reason in later_segment.left_shift_blockers
        )

    def test_later_campaign_lot_does_not_jump_higher_risk_opening_lot(self):
        opening = _lot("opening", edd=7)
        continuation = _lot("continuation", edd=8)
        opening_segment = Segment(
            lot_id=opening.id,
            run_id="shared-run",
            machine_id="M1",
            tool_id="T1",
            day_idx=4,
            start_min=900,
            end_min=1000,
            shift="B",
            qty=100,
            prod_min=70,
            setup_min=30,
            sku="SKU1",
        )
        continuation_segment = Segment(
            lot_id=continuation.id,
            run_id="shared-run",
            machine_id="M1",
            tool_id="T1",
            day_idx=4,
            start_min=1000,
            end_min=1100,
            shift="B",
            qty=100,
            prod_min=100,
            sku="SKU1",
        )

        annotate_left_shift_blockers(
            [opening_segment, continuation_segment],
            [opening, continuation],
            _engine([_eop()]),
            FactoryConfig(),
        )

        assert (
            continuation_segment.left_shift_blockers[0]
            == "blocked_by_priority_higher_risk_lot"
        )
        assert "left_shift_available" not in continuation_segment.left_shift_blockers
        assert any(
            reason.startswith("blocked_by_priority_higher_risk_lot|day=4|")
            and "lot=opening" in reason
            and "target_rupture=8" in reason
            and "competing_rupture=7" in reason
            for reason in continuation_segment.left_shift_blockers
        )

    def test_partial_downtime_uses_the_remaining_same_day_gap(self):
        lot = _lot(edd=8, prod_min=100)
        segment = Segment(
            lot_id=lot.id,
            run_id="run",
            machine_id="M1",
            tool_id="T1",
            day_idx=4,
            start_min=420,
            end_min=520,
            shift="A",
            qty=100,
            prod_min=100,
            sku="SKU1",
        )
        data = _engine([_eop()], n_days=12)
        data.machine_blocked_intervals = {
            "M1": [{"start_day": 3, "start_min": 420, "end_day": 3, "end_min": 480}]
        }

        segments = [segment]
        _left_shift_lots_into_empty_workdays(
            segments, [lot], data, FactoryConfig(), calendar_holidays(data, -7, data.n_days + 7)
        )

        shifted = segments[0]
        assert (shifted.day_idx, shifted.start_min, shifted.end_min) == (3, 480, 580)

        annotate_left_shift_blockers([shifted], [lot], data, FactoryConfig())
        assert "blocked_by_machine_busy" in shifted.left_shift_blockers
        assert "interval=07:00-08:00" in shifted.left_shift_blockers[1]
        assert "source=unavailability" in shifted.left_shift_blockers[1]

    def test_large_lot_uses_empty_release_day_without_breaking_its_setup(self):
        lot = _lot(edd=8, prod_min=1210)
        segments = [
            Segment(
                lot_id=lot.id, run_id="run", machine_id="M1", tool_id="T1",
                day_idx=4, start_min=1239, end_min=1440, shift="B", qty=171,
                prod_min=171, setup_min=30, sku="SKU1",
            ),
            Segment(
                lot_id=lot.id, run_id="run", machine_id="M1", tool_id="T1",
                day_idx=5, start_min=420, end_min=930, shift="A", qty=510,
                prod_min=510, sku="SKU1", is_continuation=True,
            ),
            Segment(
                lot_id=lot.id, run_id="run", machine_id="M1", tool_id="T1",
                day_idx=5, start_min=930, end_min=1440, shift="B", qty=510,
                prod_min=510, sku="SKU1", is_continuation=True,
            ),
            Segment(
                lot_id=lot.id, run_id="run", machine_id="M1", tool_id="T1",
                day_idx=6, start_min=420, end_min=439, shift="A", qty=19,
                prod_min=19, sku="SKU1", is_continuation=True,
            ),
        ]
        data = _engine([_eop()], n_days=12)
        config = FactoryConfig()

        _left_shift_lots_into_empty_workdays(
            segments, [lot], data, config, calendar_holidays(data, -7, data.n_days + 7)
        )

        first = min(
            (segment for segment in segments if segment.prod_min > 0),
            key=lambda segment: (segment.day_idx, segment.start_min),
        )
        assert (first.day_idx, first.start_min, first.end_min) == (3, 420, 1440)
        assert first.setup_min == 30
        assert sum(segment.prod_min for segment in segments) == 1210
        assert sum(segment.qty for segment in segments) == 1210

    def test_left_shift_gives_empty_release_day_to_higher_rupture_priority(self):
        urgent = _lot("urgent", edd=7, prod_min=100)
        later = _lot("later", edd=7, prod_min=100)
        urgent.original_edd = 1
        later.original_edd = 2
        segments = [
            Segment(
                lot_id=later.id,
                run_id="later-run",
                machine_id="M1",
                tool_id="T1",
                day_idx=5,
                start_min=420,
                end_min=550,
                shift="A",
                qty=100,
                prod_min=100,
                setup_min=30,
                sku="SKU1",
            ),
            Segment(
                lot_id=urgent.id,
                run_id="urgent-run",
                machine_id="M1",
                tool_id="T2",
                day_idx=6,
                start_min=420,
                end_min=550,
                shift="A",
                qty=100,
                prod_min=100,
                setup_min=30,
                sku="SKU1",
            ),
        ]

        _left_shift_lots_into_empty_workdays(
            segments,
            [later, urgent],
            _engine([_eop()]),
            FactoryConfig(),
            set(),
        )

        starts = {segment.lot_id: (segment.day_idx, segment.start_min) for segment in segments}
        assert starts[urgent.id] < starts[later.id]


def _run_of(lot: Lot):
    from backend.scheduler.types import ToolRun

    return ToolRun(
        id=f"run_{lot.id}",
        tool_id=lot.tool_id,
        machine_id=lot.machine_id,
        alt_machine_id=None,
        lots=[lot],
        setup_min=lot.setup_min,
        total_prod_min=lot.prod_min,
        total_min=lot.setup_min + lot.prod_min,
        edd=lot.edd,
    )


class TestWindowPolicy:
    def test_final_schedule_is_repeatable_and_has_no_unapplied_left_shift(self):
        ops = [
            _eop(
                op_id="T1_M1_A",
                sku="A",
                tool="T1",
                d=[0, 0, 0, 0, 0, 0, 600, 0, 400, 0, 0, 0],
            ),
            _eop(
                op_id="T2_M1_B",
                sku="B",
                tool="T2",
                d=[0, 0, 0, 0, 0, 0, 0, 700, 0, 500, 0, 0],
            ),
        ]
        config = FactoryConfig(compact_enabled=True)

        first = schedule_all(_engine(ops), config=config)
        second = schedule_all(_engine(ops), config=FactoryConfig(compact_enabled=True))
        first_signature = sorted(
            (
                segment.lot_id,
                segment.machine_id,
                segment.tool_id,
                segment.day_idx,
                segment.start_min,
                segment.end_min,
                segment.qty,
            )
            for segment in first.segments
        )
        second_signature = sorted(
            (
                segment.lot_id,
                segment.machine_id,
                segment.tool_id,
                segment.day_idx,
                segment.start_min,
                segment.end_min,
                segment.qty,
            )
            for segment in second.segments
        )

        assert first_signature == second_signature
        assert not any(
            reason.startswith("left_shift_available")
            for segment in first.segments
            if segment.prod_min > 0
            for reason in segment.left_shift_blockers
        )
        assert first.score["left_shift_opportunities"] == 0
        assert first.score["lower_priority_campaign_interruptions"] == 0
        assert first.gate_report["operational_gate_passed"] is True

    def test_legacy_policy_values_cannot_change_jit(self):
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 500, 0, 300, 0, 0, 0])]
        r_default = schedule_all(_engine(ops))
        r_explicit = schedule_all(_engine(ops), config=FactoryConfig(earliness_policy="jit"))
        assert r_default.score == r_explicit.score

    def test_starts_at_material_release_day(self):
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 0, 0, 500, 0, 0, 0])]  # demand at day 8
        config = FactoryConfig(
            earliness_policy="window",
            material_release_days=5,
            jit_buffer_pct=0,
        )
        result = schedule_all(_engine(ops), config=config)

        assert result.score["otd"] == 100.0
        assert result.score["tardy_count"] == 0
        prod_days = [s.day_idx for s in result.segments if s.qty > 0]
        assert prod_days, "expected production segments"
        # Day 3 is the first of the five working days before delivery day 8.
        assert min(prod_days) == 3
        assert result.score["early_window_violations"] == 0

    def test_legacy_window_and_jit_are_identical(self):
        # No setup here: this fixture isolates the production-window gate.
        # Setup-before-material is a separate hard invariant.
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 0, 0, 500, 0, 0, 0], sH=0)]
        r_jit = schedule_all(_engine(ops), config=FactoryConfig(earliness_policy="jit"))
        r_win = schedule_all(
            _engine(ops),
            config=FactoryConfig(earliness_policy="window", material_release_days=5),
        )
        jit_start = min(s.day_idx for s in r_jit.segments if s.qty > 0)
        win_start = min(s.day_idx for s in r_win.segments if s.qty > 0)
        assert win_start == jit_start == 3

    def test_window_respects_holidays(self):
        """Floor is measured in workdays: holidays push it earlier."""
        # No setup here: this fixture isolates the production-window gate.
        # Setup-before-material is a separate hard invariant.
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 0, 0, 500, 0, 0, 0], sH=0)]
        config = FactoryConfig(earliness_policy="window", material_release_days=5)
        result = schedule_all(_engine(ops, holidays=[5, 6]), config=config)
        assert result.score["otd"] == 100.0
        prod_days = [s.day_idx for s in result.segments if s.qty > 0]
        # Days 5 and 6 are closed, so the fifth preceding workday is day 1.
        assert min(prod_days) == 1
        assert 5 not in prod_days and 6 not in prod_days

    def test_day_zero_is_the_earliest_schedulable_day(self):
        ops = [_eop(d=[0, 0, 0, 5600, 0, 0, 0, 0, 0, 0, 0, 0])]
        result = schedule_all(_engine(ops), config=FactoryConfig())
        prod_days = [segment.day_idx for segment in result.segments if segment.prod_min > 0]
        assert min(prod_days) == 0
        assert result.score["start_anticipation_max_workdays"] <= 5
        assert result.score["early_window_violations"] == 0
        assert result.score["missing_lots"] == 0

    def test_infeasible_candidate_never_drops_lots(self):
        ops = [
            _eop(op_id="T1_M1_A", sku="A", d=[0, 9000, 0, 0, 0, 0, 0, 0]),
            _eop(op_id="T2_M1_B", sku="B", tool="T2", d=[0, 9000, 0, 0, 0, 0, 0, 0]),
        ]
        result = schedule_all(_engine(ops, n_days=8), config=FactoryConfig())

        assert result.score["missing_lots"] == 0
        assert result.score["missing_qty"] == 0
        assert result.score["early_window_violations"] == 0
        assert result.gate_report["coverage_gate_passed"] is True
        assert result.solver_status == "strict_infeasible_best_effort"

    def test_window_keeps_otd_on_tight_demand(self):
        """Demand at day 1 (inside window width) still delivers on time."""
        ops = [_eop(d=[0, 800, 0, 0, 0, 0, 500, 0, 0, 0, 0, 0])]
        config = FactoryConfig(earliness_policy="window", material_release_days=5)
        result = schedule_all(_engine(ops), config=config)
        assert result.score["otd"] == 100.0
        assert result.score["otd_d"] == 100.0
        assert result.score["tardy_count"] == 0

    def test_earlier_stock_requirement_is_scheduled_before_later_requirement(self):
        """Release-first order prevents a later reference passing a rupture risk."""
        urgent = _eop(
            op_id="T1_M1_0040-2",
            sku="0040-2",
            tool="T1",
            d=[0, 0, 0, 0, 0, 800, 0, 0, 0, 0],
        )
        later = _eop(
            op_id="T2_M1_0040-1",
            sku="0040-1",
            tool="T2",
            d=[0, 0, 0, 0, 0, 0, 800, 0, 0, 0],
        )
        result = schedule_all(_engine([urgent, later], n_days=10), config=FactoryConfig())

        starts = {
            lot.sku: min(
                (segment.day_idx, segment.start_min)
                for segment in result.segments
                if segment.lot_id == lot.id and segment.prod_min > 0
            )
            for lot in result.lots
        }
        assert starts["0040-2"] < starts["0040-1"]
        assert starts["0040-2"][0] == 0
        assert starts["0040-1"][0] >= 1

    def test_rupture_priority_beats_a_less_urgent_internal_buffer(self):
        """A later buffer must not pass a reference that ruptures first."""
        urgent = _eop(
            op_id="T1_M1_0040-2",
            sku="0040-2",
            tool="T1",
            d=[0, 0, 0, 0, 0, 800, 0, 0, 0, 0],
        )
        buffered = _eop(
            op_id="T2_M1_0040-1",
            sku="0040-1",
            tool="T2",
            d=[0, 0, 0, 0, 0, 0, 800, 0, 0, 0],
        )
        buffered.finish_buffer_days = 3
        result = schedule_all(_engine([urgent, buffered], n_days=10), config=FactoryConfig())

        starts = {
            lot.sku: min(
                (segment.day_idx, segment.start_min)
                for segment in result.segments
                if segment.lot_id == lot.id and segment.prod_min > 0
            )
            for lot in result.lots
        }
        assert starts["0040-2"] < starts["0040-1"]

    def test_fallback_dispatch_uses_the_same_release_first_policy(self):
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 0, 0, 500, 0, 0, 0])]
        config = FactoryConfig(global_jit_enabled=False)
        result = schedule_all(_engine(ops), config=config)

        productive = [segment for segment in result.segments if segment.prod_min > 0]
        assert min(segment.day_idx for segment in productive) == 3
        assert not [
            segment
            for segment in result.segments
            if segment.setup_min > 0 and segment.prod_min <= 0
        ]
        assert result.score["early_window_violations"] == 0

    def test_ghost_repair_cannot_cross_material_release_floor(self):
        """A later safety-net repair must not reintroduce early production."""
        lot = _lot(edd=8, prod_min=60.0)
        ghost = Segment(
            lot_id=lot.id,
            run_id="run_L1",
            machine_id="M1",
            tool_id="T1",
            day_idx=8,
            start_min=1440,
            end_min=1440,
            shift="B",
            qty=100,
            prod_min=60.0,
            setup_min=0.0,
            edd=8,
        )

        # Days 4--7 are occupied. Day 3 is the first legal recovery slot;
        # days 0--2 are deliberately free but outside material release.
        blockers = [
            Segment(
                lot_id=f"blocker-{day}",
                run_id=f"blocker-{day}",
                machine_id="M1",
                tool_id=f"blocker-tool-{day}",
                day_idx=day,
                start_min=420,
                end_min=1440,
                shift="A",
                qty=0,
                prod_min=1020.0,
            )
            for day in range(4, 8)
        ]
        repaired = _sanitize_segments(
            [*blockers, ghost], FactoryConfig(), holidays=set(), lots=[lot]
        )

        repaired_ghost = next(segment for segment in repaired if segment.lot_id == lot.id)
        assert repaired_ghost.day_idx == 3
        assert repaired_ghost.start_min == 420

    def test_overlap_repair_moves_complete_work_past_edd_instead_of_clipping(self):
        blocker = Segment(
            lot_id="blocker",
            run_id="blocker",
            machine_id="M1",
            tool_id="T0",
            day_idx=0,
            start_min=420,
            end_min=1380,
            shift="A",
            qty=100,
            prod_min=960.0,
            edd=0,
        )
        displaced = Segment(
            lot_id="target",
            run_id="target",
            machine_id="M1",
            tool_id="T1",
            day_idx=0,
            start_min=1320,
            end_min=1440,
            shift="B",
            qty=123,
            prod_min=60.0,
            setup_min=60.0,
            edd=0,
            twin_outputs=[("op-a", "A", 123), ("op-b", "B", 246)],
        )

        repaired = _fix_day_overlaps([blocker, displaced], FactoryConfig(), set())

        target = next(segment for segment in repaired if segment.lot_id == "target")
        assert (target.day_idx, target.start_min, target.end_min) == (1, 420, 540)
        assert (target.setup_min, target.prod_min, target.qty) == (60.0, 60.0, 123)
        assert target.twin_outputs == [("op-a", "A", 123), ("op-b", "B", 246)]

    def test_sanitize_never_scales_a_truncated_segment(self):
        segment = Segment(
            lot_id="target",
            run_id="target",
            machine_id="M1",
            tool_id="T1",
            day_idx=0,
            start_min=1400,
            end_min=1440,
            shift="B",
            qty=123,
            prod_min=60.0,
            setup_min=60.0,
            edd=0,
            twin_outputs=[("op-a", "A", 123), ("op-b", "B", 246)],
        )

        repaired = _sanitize_segments([segment], FactoryConfig(), holidays=set())

        assert len(repaired) == 1
        target = repaired[0]
        assert (target.day_idx, target.start_min, target.end_min) == (1, 420, 540)
        assert (target.setup_min, target.prod_min, target.qty) == (60.0, 60.0, 123)
        assert target.twin_outputs == [("op-a", "A", 123), ("op-b", "B", 246)]

    def test_compaction_stays_inside_release_window_and_keeps_setup_attached(self):
        lot = _lot(edd=8, prod_min=1070.0)
        source = [
            Segment(
                lot_id=lot.id,
                run_id="run_L1",
                machine_id="M1",
                tool_id="T1",
                day_idx=5,
                start_min=420,
                end_min=1440,
                shift="A",
                qty=900,
                prod_min=990.0,
                setup_min=30.0,
                edd=8,
            ),
            Segment(
                lot_id=lot.id,
                run_id="run_L1",
                machine_id="M1",
                tool_id="T1",
                day_idx=6,
                start_min=420,
                end_min=500,
                shift="A",
                qty=100,
                prod_min=80.0,
                setup_min=0.0,
                edd=8,
                is_continuation=True,
            ),
        ]

        compacted = _compact_segments(
            source,
            FactoryConfig(),
            holidays=set(),
            lots=[lot],
        )

        compacted.sort(key=lambda segment: (segment.day_idx, segment.start_min))
        assert [(segment.day_idx, segment.start_min, segment.end_min) for segment in compacted] == [
            (3, 420, 1440),
            (4, 420, 500),
        ]
        assert [segment.setup_min for segment in compacted] == [30.0, 0.0]
        assert sum(segment.prod_min for segment in compacted) == 1070.0


class TestWindowMetricsAndGates:
    def _early_plan(self, enforcement: str):
        """Construct a physically valid but deliberately too-early candidate."""
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 0, 0, 500, 0, 0, 0], sH=0)]
        engine = _engine(ops)
        config = FactoryConfig(
            earliness_policy="window",
            material_release_days=5,
            early_window_enforcement=enforcement,
            jit_enabled=False,  # baseline ASAP → starts day 0, floor is 3
        )
        result = schedule_all(engine, config=config)
        for segment in result.segments:
            segment.day_idx = 0
        result.score = compute_score(result.segments, result.lots, engine, config)
        return result, engine, config

    def test_legacy_soft_value_cannot_disable_gate(self):
        result, engine, config = self._early_plan("soft")
        assert result.score["early_window_violations"] > 0
        report = build_gate_report(
            result.segments, result.lots, result.score, engine, config
        )
        assert report["physical_gate_passed"] is True
        assert report["jit_window_gate_passed"] is False
        assert report["hard_gate_passed"] is True
        assert report["status"] == "jit_window_blocked"
        assert report["apply_decision"] == "blocked"
        assert len(report["jit_window_detail"]) == result.score["early_window_violations"]
        violation = report["jit_window_detail"][0]
        assert violation["increment_workdays"] == violation["excess_workdays"]
        assert violation["allowed_anticipation_workdays"] == 5
        assert violation["anticipation_workdays"] > 5
        assert violation["reason_code"] in {
            "campaign_span",
            "non_workday_start",
            "twin_sequence",
            "early_sequence",
        }
        assert violation["reason"]
        assert violation["start_date"]
        assert violation["delivery_date"]
        assert violation["earliest_allowed_start_date"]

    def test_legacy_hard_value_cannot_turn_jit_into_a_physical_gate(self):
        result, engine, config = self._early_plan("hard")
        report = build_gate_report(
            result.segments, result.lots, result.score, engine, config
        )
        assert report["material_gate_passed"] is True
        assert report["status"] == "jit_window_blocked"
        assert report["apply_decision"] == "blocked"
        assert report["physical_gate_passed"] is True
        assert report["hard_gate_passed"] is True

    def test_jit_policy_has_zero_window_metrics(self):
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 500, 0, 0, 0, 0, 0])]
        result = schedule_all(_engine(ops), config=FactoryConfig())
        assert result.score["early_window_violations"] == 0


class TestEarlinessTarget:
    def test_target_is_not_recalibrated_by_legacy_window(self):
        c = FactoryConfig(
            earliness_policy="window", material_release_days=5, jit_earliness_target=5.5
        )
        assert effective_earliness_target(c) == 5.5

    def test_target_unchanged_under_jit(self):
        c = FactoryConfig(earliness_policy="jit", jit_earliness_target=5.5)
        assert effective_earliness_target(c) == 5.5
