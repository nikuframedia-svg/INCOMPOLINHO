"""Focused interval-level explainability regressions."""

from __future__ import annotations

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.explainability import annotate_left_shift_blockers
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData, EOp, MachineInfo


def _op(
    *,
    op_id: str,
    sku: str,
    machine: str,
    tool: str,
    operators: int = 1,
) -> EOp:
    return EOp(
        id=op_id,
        sku=sku,
        client="CLIENT",
        designation="Test",
        m=machine,
        t=tool,
        pH=100,
        sH=0.5,
        operators=operators,
        eco_lot=0,
        alt=None,
        stk=0,
        backlog=0,
        d=[0] * 10,
        oee=0.66,
        wip=0,
    )


def _data(ops: list[EOp], *, holidays: list[int] | None = None) -> EngineData:
    machine_ids = sorted({op.m for op in ops})
    return EngineData(
        ops=ops,
        machines=[
            MachineInfo(id=machine_id, group="Grandes", day_capacity=1020)
            for machine_id in machine_ids
        ],
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-03-{day:02d}" for day in range(2, 12)],
        n_days=10,
        holidays=holidays or [],
    )


def _lot(
    lot_id: str,
    *,
    op_id: str,
    machine: str,
    tool: str,
    edd: int,
    setup: float = 30,
    priority: int = 0,
) -> Lot:
    return Lot(
        id=lot_id,
        op_id=op_id,
        tool_id=tool,
        machine_id=machine,
        alt_machine_id=None,
        qty=100,
        prod_min=300,
        setup_min=setup,
        edd=edd,
        is_twin=False,
        planning_priority=priority,
    )


def _segment(
    lot: Lot,
    *,
    day: int,
    start: int = 420,
    end: int = 720,
    setup: float = 0,
    run: str | None = None,
) -> Segment:
    return Segment(
        lot_id=lot.id,
        run_id=run or f"run-{lot.id}",
        machine_id=lot.machine_id,
        tool_id=lot.tool_id,
        day_idx=day,
        start_min=start,
        end_min=end,
        shift="A",
        qty=100,
        prod_min=max(1, end - start - setup),
        setup_min=setup,
        sku=lot.op_id.split("_")[-1],
    )


def _details(segment: Segment, code: str) -> list[str]:
    return [
        reason
        for reason in segment.left_shift_blockers
        if reason.startswith(f"{code}|")
    ]


def test_machine_unavailability_has_exact_date_interval_and_reason():
    op = _op(op_id="T1_M1_TARGET", sku="TARGET", machine="M1", tool="T1")
    lot = _lot("target", op_id=op.id, machine="M1", tool="T1", edd=8)
    target = _segment(lot, day=4)
    data = _data([op])
    data.machine_blocked_intervals = {
        "M1": [
            {
                "start_day": 3,
                "start_min": 420,
                "end_day": 3,
                "end_min": 1440,
                "category": "Avaria",
                "reason": "Motor",
            }
        ]
    }

    annotate_left_shift_blockers([target], [lot], data, FactoryConfig())

    assert "blocked_by_machine_busy" in target.left_shift_blockers
    assert _details(target, "blocked_by_machine_busy") == [
        "blocked_by_machine_busy|day=3|date=2026-03-05|interval=07:00-00:00"
        "|source=unavailability|category=Avaria|reason=Motor|machine=M1"
    ]


def test_tool_conflict_names_machine_lot_and_exact_interval():
    target_op = _op(op_id="T1_M1_TARGET", sku="TARGET", machine="M1", tool="T1")
    other_op = _op(op_id="T1_M2_OTHER", sku="OTHER", machine="M2", tool="T1")
    target_lot = _lot("target", op_id=target_op.id, machine="M1", tool="T1", edd=8)
    other_lot = _lot("other", op_id=other_op.id, machine="M2", tool="T1", edd=8)
    target = _segment(target_lot, day=4)
    other = _segment(other_lot, day=3, end=1440)

    annotate_left_shift_blockers(
        [other, target], [other_lot, target_lot], _data([target_op, other_op]), FactoryConfig()
    )

    assert "blocked_by_tool_busy" in target.left_shift_blockers
    detail = _details(target, "blocked_by_tool_busy")[0]
    assert "day=3|date=2026-03-05|interval=07:00-00:00" in detail
    assert "lot=other|sku=OTHER" in detail
    assert "tool=T1|machine=M2" in detail


def test_setup_crew_conflict_reports_saturated_interval():
    target_op = _op(op_id="T1_M1_TARGET", sku="TARGET", machine="M1", tool="T1")
    other_op = _op(op_id="T2_M2_OTHER", sku="OTHER", machine="M2", tool="T2")
    target_lot = _lot("target", op_id=target_op.id, machine="M1", tool="T1", edd=8)
    other_lot = _lot("other", op_id=other_op.id, machine="M2", tool="T2", edd=8, setup=1020)
    target = _segment(target_lot, day=4, setup=30)
    other = _segment(other_lot, day=3, end=1440, setup=1020)

    annotate_left_shift_blockers(
        [other, target], [other_lot, target_lot], _data([target_op, other_op]), FactoryConfig()
    )

    assert "blocked_by_setup_crew" in target.left_shift_blockers
    detail = _details(target, "blocked_by_setup_crew")[0]
    assert "interval=07:00-07:30" in detail
    assert "group=Grandes|capacity=1|occupied=1" in detail
    assert "competing_lots=other|competing_machines=M2" in detail


def test_operator_conflict_reports_capacity_usage_and_competing_lot():
    target_op = _op(
        op_id="T1_M1_TARGET", sku="TARGET", machine="M1", tool="T1", operators=1
    )
    other_op = _op(
        op_id="T2_M2_OTHER", sku="OTHER", machine="M2", tool="T2", operators=6
    )
    target_lot = _lot("target", op_id=target_op.id, machine="M1", tool="T1", edd=8)
    other_lot = _lot("other", op_id=other_op.id, machine="M2", tool="T2", edd=8)
    target = _segment(target_lot, day=4)
    other_a = _segment(other_lot, day=3, end=930)
    other_b = _segment(other_lot, day=3, start=930, end=1440)
    other_b.shift = "B"

    annotate_left_shift_blockers(
        [other_a, other_b, target],
        [other_lot, target_lot],
        _data([target_op, other_op]),
        FactoryConfig(),
    )

    assert "blocked_by_operator_capacity" in target.left_shift_blockers
    detail = _details(target, "blocked_by_operator_capacity")[0]
    assert "day=3|date=2026-03-05|interval=07:00-12:00" in detail
    assert "group=Grandes|shift=A|capacity=6|unavailable=0|occupied=6|required=1" in detail
    assert "competing_lots=other" in detail


def test_calendar_blocker_identifies_the_non_working_day():
    op = _op(op_id="T1_M1_TARGET", sku="TARGET", machine="M1", tool="T1")
    lot = _lot("target", op_id=op.id, machine="M1", tool="T1", edd=8)
    target = _segment(lot, day=4, setup=30)

    annotate_left_shift_blockers([target], [lot], _data([op], holidays=[3]), FactoryConfig())

    assert target.left_shift_blockers[0] == "left_shift_available"
    assert "day=2" in target.left_shift_blockers[1]
    assert _details(target, "blocked_by_holiday") == []


def test_free_gap_is_reported_as_exact_left_shift_opportunity():
    op = _op(op_id="T1_M1_TARGET", sku="TARGET", machine="M1", tool="T1")
    lot = _lot("target", op_id=op.id, machine="M1", tool="T1", edd=8)
    target = _segment(lot, day=4, setup=30)

    annotate_left_shift_blockers([target], [lot], _data([op]), FactoryConfig())

    assert target.left_shift_blockers[0] == "left_shift_available"
    assert _details(target, "left_shift_available") == [
        "left_shift_available|day=3|date=2026-03-05|interval=07:00-12:00"
        "|machine=M1|tool=T1|includes_setup=True"
    ]


def test_intervening_tool_change_blocks_a_false_campaign_opportunity():
    target_op = _op(op_id="T1_M1_TARGET", sku="TARGET", machine="M1", tool="T1")
    other_op = _op(op_id="T2_M1_OTHER", sku="OTHER", machine="M1", tool="T2")
    target_lot = _lot("target", op_id=target_op.id, machine="M1", tool="T1", edd=8)
    other_lot = _lot("other", op_id=other_op.id, machine="M1", tool="T2", edd=8)
    opening = _segment(target_lot, day=4)
    continuation = _segment(target_lot, day=5)
    other_before = _segment(other_lot, day=3, start=720, end=1440)
    other_between = _segment(other_lot, day=4, start=720, end=1440)

    annotate_left_shift_blockers(
        [other_before, opening, other_between, continuation],
        [other_lot, target_lot],
        _data([target_op, other_op]),
        FactoryConfig(),
    )

    assert "left_shift_available" not in opening.left_shift_blockers
    assert "blocked_by_intervening_tool_change" in opening.left_shift_blockers
    detail = _details(opening, "blocked_by_intervening_tool_change")[0]
    assert "day=3|date=2026-03-05|interval=12:00-00:00" in detail
    assert "machine=M1|tool=T2" in detail


def test_inactive_machine_is_an_exact_full_day_blocker():
    op = _op(op_id="T1_M1_TARGET", sku="TARGET", machine="M1", tool="T1")
    lot = _lot("target", op_id=op.id, machine="M1", tool="T1", edd=8)
    target = _segment(lot, day=4)
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes", active=False)})

    annotate_left_shift_blockers([target], [lot], _data([op]), config)

    assert "blocked_by_inactive_machine" in target.left_shift_blockers
    assert _details(target, "blocked_by_inactive_machine")[0].endswith("|machine=M1")
