"""Acceptance and small-oracle tests for alternative-machine delivery repair."""

from __future__ import annotations

from dataclasses import replace
from itertools import product

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.alternative_repair import repair_alternative_machine_delivery
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.scheduler.validation import assert_plan_valid
from backend.types import EOp, EngineData, MachineInfo


def _config(*, oee_m1: float | None = None, oee_m2: float | None = None) -> FactoryConfig:
    config = FactoryConfig()
    config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes", oee=oee_m1),
        "M2": MachineConfig(id="M2", group="Grandes", oee=oee_m2),
    }
    return config


def _op(
    op_id: str,
    *,
    machine: str = "M1",
    alt: str | None = "M2",
    tool: str = "T1",
    demand_day: int = 0,
    qty: int = 100,
    rate: float = 100.0,
    setup_hours: float = 0.5,
    priority: int = 0,
) -> EOp:
    demand = [0, 0, 0, 0]
    demand[demand_day] = qty
    return EOp(
        id=op_id,
        sku=f"SKU-{op_id}",
        client="CLIENT",
        designation="Part",
        m=machine,
        t=tool,
        pH=rate,
        sH=setup_hours,
        operators=1,
        eco_lot=0,
        alt=alt,
        stk=0,
        backlog=0,
        d=demand,
        oee=1.0,
        wip=0,
        planning_priority=priority,
    )


def _data(ops: list[EOp]) -> EngineData:
    return EngineData(
        ops=ops,
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Grandes", day_capacity=1020),
        ],
        twin_groups=[],
        client_demands={},
        workdays=["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17"],
        n_days=4,
    )


def _run_and_segment(
    op: EOp,
    *,
    run_id: str | None = None,
    machine: str = "M1",
    day: int = 1,
    qty: int = 100,
    prod_min: int = 60,
    setup_min: int = 30,
    due: int = 0,
) -> tuple[ToolRun, Lot, Segment]:
    run_id = run_id or f"RUN-{op.id}"
    lot = Lot(
        id=f"LOT-{op.id}",
        op_id=op.id,
        sku=op.sku,
        tool_id=op.t,
        machine_id=op.m,
        alt_machine_id=op.alt,
        qty=qty,
        prod_min=float(prod_min),
        setup_min=float(setup_min),
        edd=due,
        is_twin=False,
        original_edd=due,
        internal_deadline=due,
        delivery_day=due,
        production_due_day=due,
        planning_priority=op.planning_priority,
    )
    run = ToolRun(
        id=run_id,
        tool_id=op.t,
        machine_id=op.m,
        alt_machine_id=op.alt,
        lots=[lot],
        setup_min=float(setup_min),
        total_prod_min=float(prod_min),
        total_min=float(setup_min + prod_min),
        edd=due,
        production_due_day=due,
    )
    segment = Segment(
        lot_id=lot.id,
        run_id=run.id,
        machine_id=machine,
        tool_id=op.t,
        day_idx=day,
        start_min=420,
        end_min=420 + setup_min + prod_min,
        shift="A",
        qty=qty,
        prod_min=float(prod_min),
        setup_min=float(setup_min),
        edd=due,
        sku=op.sku,
        lot_qty=qty,
        run_qty=qty,
        run_setup_min=float(setup_min),
        run_lot_count=1,
        original_edd=due,
        internal_deadline=due,
        delivery_day=due,
        production_due_day=due,
        planning_priority=op.planning_priority,
    )
    return run, lot, segment


def _oracle_day_zero_feasible(
    *,
    setup_min: int,
    prod_min: int,
    machine_blocks: dict[str, tuple[int, int] | None],
    tool_block: tuple[int, int] | None,
    operator_block: tuple[int, int] | None,
) -> bool:
    """Independent one-minute exhaustive oracle for the single-run fixture."""

    def open_at(minute: int, block: tuple[int, int] | None) -> bool:
        return block is None or not (block[0] <= minute < block[1])

    for machine_id in ("M1", "M2"):
        machine_block = machine_blocks[machine_id]
        for setup_start in range(420, 1440 - setup_min):
            setup_end = setup_start + setup_min
            if setup_start < 930 < setup_end:
                continue
            if not all(
                open_at(minute, machine_block) and open_at(minute, tool_block)
                for minute in range(setup_start, setup_end)
            ):
                continue
            if not (
                open_at(setup_end, machine_block)
                and open_at(setup_end, tool_block)
                and open_at(setup_end, operator_block)
            ):
                continue
            available_production = sum(
                open_at(minute, machine_block)
                and open_at(minute, tool_block)
                and open_at(minute, operator_block)
                for minute in range(setup_end, 1440)
            )
            if available_production >= prod_min:
                return True
    return False


@pytest.mark.parametrize("primary_down", [False, True])
@pytest.mark.parametrize("alternative_down", [False, True])
@pytest.mark.parametrize("tool_down", [False, True])
def test_outage_matrix_matches_closed_form_delivery_oracle(
    primary_down: bool,
    alternative_down: bool,
    tool_down: bool,
):
    """All 2x2x2 full-day outage combinations match the theoretical optimum."""

    op = _op("URGENT")
    data = _data([op])
    config = _config()
    run, lot, delayed = _run_and_segment(op)
    if primary_down:
        data.machine_blocked_days["M1"] = {0}
    if alternative_down:
        data.machine_blocked_days["M2"] = {0}
    if tool_down:
        data.tool_blocked_days["T1"] = {0}

    repaired = repair_alternative_machine_delivery(
        [delayed], [lot], data, config, runs=[run]
    )

    completion = max(segment.day_idx for segment in repaired.segments)
    theoretically_on_time = not tool_down and not (primary_down and alternative_down)
    assert (completion == 0) is theoretically_on_time
    assert repaired.after_score["tardy_count"] == (0 if theoretically_on_time else 1)
    if theoretically_on_time:
        chosen = {segment.machine_id for segment in repaired.segments}
        assert chosen <= {
            machine
            for machine, down in (("M1", primary_down), ("M2", alternative_down))
            if not down
        }
    assert_plan_valid(repaired.segments, data, config, lots=repaired.lots)


_PARTIAL_BLOCKS = (None, (420, 600), (600, 900), (420, 1440))


@pytest.mark.parametrize(
    "primary_block,alternative_block,tool_block,operator_block",
    list(product(_PARTIAL_BLOCKS, _PARTIAL_BLOCKS, (None, (600, 720)), (None, (420, 600)))),
)
def test_partial_unavailability_matrix_matches_minute_exhaustive_oracle(
    primary_block: tuple[int, int] | None,
    alternative_block: tuple[int, int] | None,
    tool_block: tuple[int, int] | None,
    operator_block: tuple[int, int] | None,
):
    op = _op("MATRIX", rate=20.0)
    data = _data([op])
    config = _config()
    config.operators[("Grandes", "A")] = 1
    config.operators[("Grandes", "B")] = 1
    run, lot, delayed = _run_and_segment(op, prod_min=300)

    for machine_id, block in (("M1", primary_block), ("M2", alternative_block)):
        if block is not None:
            data.machine_blocked_intervals[machine_id] = [
                {
                    "id": f"{machine_id}-stop",
                    "start_day": 0,
                    "start_min": block[0],
                    "end_day": 0,
                    "end_min": block[1],
                }
            ]
    if tool_block is not None:
        data.tool_blocked_intervals["T1"] = [
            {
                "id": "tool-stop",
                "start_day": 0,
                "start_min": tool_block[0],
                "end_day": 0,
                "end_min": tool_block[1],
            }
        ]
    if operator_block is not None:
        data.operator_blocked_intervals = [
            {
                "id": "operator-stop",
                "start_day": 0,
                "start_min": operator_block[0],
                "end_day": 0,
                "end_min": operator_block[1],
                "group": "Grandes",
                "shift": "A",
                "count": 1,
            }
        ]

    repaired = repair_alternative_machine_delivery(
        [delayed], [lot], data, config, runs=[run]
    )
    expected = _oracle_day_zero_feasible(
        setup_min=30,
        prod_min=300,
        machine_blocks={"M1": primary_block, "M2": alternative_block},
        tool_block=tool_block,
        operator_block=operator_block,
    )

    completion = max(segment.day_idx for segment in repaired.segments)
    assert (completion == 0) is expected
    assert repaired.after_score["tardy_count"] == (0 if expected else 1)
    assert_plan_valid(repaired.segments, data, config, lots=repaired.lots)


def test_partial_stop_is_preempted_and_still_finishes_on_the_due_day():
    op = _op("LONG", qty=100, rate=10.0)
    data = _data([op])
    config = _config()
    run, lot, delayed = _run_and_segment(op, prod_min=600)
    data.machine_blocked_intervals = {
        "M1": [
            {
                "id": "mid-shift-stop",
                "start_day": 0,
                "start_min": 600,
                "end_day": 0,
                "end_min": 720,
            }
        ]
    }
    data.machine_blocked_days["M2"] = {0}

    repaired = repair_alternative_machine_delivery(
        [delayed], [lot], data, config, runs=[run]
    )

    assert repaired.after_score["tardy_count"] == 0
    assert {segment.day_idx for segment in repaired.segments} == {0}
    assert sum(segment.prod_min for segment in repaired.segments) == 600
    assert all(
        segment.end_min <= 600 or segment.start_min >= 720
        for segment in repaired.segments
    )
    assert_plan_valid(repaired.segments, data, config, lots=repaired.lots)


def test_partial_tool_stop_is_preempted_on_an_eligible_machine():
    op = _op("TOOL-STOP", qty=100, rate=10.0)
    data = _data([op])
    config = _config()
    run, lot, delayed = _run_and_segment(op, prod_min=600)
    data.tool_blocked_intervals = {
        "T1": [
            {
                "id": "tool-maintenance",
                "start_day": 0,
                "start_min": 600,
                "end_day": 0,
                "end_min": 720,
            }
        ]
    }

    repaired = repair_alternative_machine_delivery(
        [delayed], [lot], data, config, runs=[run]
    )

    assert repaired.after_score["tardy_count"] == 0
    assert sum(segment.prod_min for segment in repaired.segments) == 600
    assert all(
        segment.end_min <= 600 or segment.start_min >= 720
        for segment in repaired.segments
    )
    assert_plan_valid(repaired.segments, data, config, lots=repaired.lots)


def test_operator_absence_delays_production_without_losing_due_day():
    op = _op("OPERATOR")
    data = _data([op])
    config = _config()
    config.operators[("Grandes", "A")] = 1
    config.operators[("Grandes", "B")] = 1
    data.operator_blocked_intervals = [
        {
            "id": "absence",
            "start_day": 0,
            "start_min": 420,
            "end_day": 0,
            "end_min": 600,
            "group": "Grandes",
            "shift": "A",
            "count": 1,
        }
    ]
    run, lot, delayed = _run_and_segment(op)

    repaired = repair_alternative_machine_delivery(
        [delayed], [lot], data, config, runs=[run]
    )

    first = min(repaired.segments, key=lambda segment: segment.start_min)
    assert first.start_min == 570
    assert first.start_min + first.setup_min == 600
    assert repaired.after_score["tardy_count"] == 0
    assert_plan_valid(repaired.segments, data, config, lots=repaired.lots)


def test_setup_crew_conflict_is_serialized_across_machines():
    urgent_op = _op("CREW-URGENT", tool="T1")
    fixed_op = _op("CREW-FIXED", machine="M2", alt=None, tool="T2", setup_hours=1.0)
    data = _data([urgent_op, fixed_op])
    config = _config()
    urgent_run, urgent_lot, delayed = _run_and_segment(urgent_op)
    _fixed_run, fixed_lot, fixed_segment = _run_and_segment(
        fixed_op,
        machine="M2",
        day=0,
        prod_min=60,
        setup_min=60,
        due=1,
    )

    repaired = repair_alternative_machine_delivery(
        [fixed_segment, delayed],
        [urgent_lot, fixed_lot],
        data,
        config,
        runs=[urgent_run],
    )

    urgent_first = min(
        (segment for segment in repaired.segments if segment.run_id == urgent_run.id),
        key=lambda segment: segment.start_min,
    )
    assert urgent_first.day_idx == 0
    assert urgent_first.start_min >= 480
    assert repaired.after_score["tardy_count"] == 0
    assert_plan_valid(repaired.segments, data, config, lots=repaired.lots)


def test_alternative_rebinds_machine_specific_oee_and_setup():
    op = _op("OEE", qty=60, rate=60.0, setup_hours=1.0)
    data = _data([op])
    config = _config(oee_m1=0.5, oee_m2=1.0)
    config.setup_overrides = [{"sku": op.sku, "machine": "M2", "hours": 0.25}]
    run, lot, delayed = _run_and_segment(
        op,
        qty=60,
        prod_min=120,
        setup_min=60,
    )
    data.machine_blocked_days["M1"] = {0}

    repaired = repair_alternative_machine_delivery(
        [delayed], [lot], data, config, runs=[run]
    )

    assert {segment.machine_id for segment in repaired.segments} == {"M2"}
    assert sum(segment.setup_min for segment in repaired.segments) == 15
    assert sum(segment.prod_min for segment in repaired.segments) == 60
    assert repaired.lots[0].setup_min == 15
    assert repaired.lots[0].prod_min == 60
    assert_plan_valid(repaired.segments, data, config, lots=repaired.lots)


def test_coordinated_reflow_prioritizes_urgent_run_over_machine_blocker():
    urgent_op = _op("URGENT", priority=10)
    blocker_op = _op(
        "BLOCKER",
        machine="M2",
        alt=None,
        tool="T2",
        demand_day=1,
        rate=100 * 60 / 990,
    )
    data = _data([urgent_op, blocker_op])
    config = _config()
    urgent_run, urgent_lot, urgent_segment = _run_and_segment(urgent_op)
    blocker_run, blocker_lot, blocker_segment = _run_and_segment(
        blocker_op,
        machine="M2",
        day=0,
        prod_min=990,
        setup_min=30,
        due=1,
    )
    data.machine_blocked_days["M1"] = {0}
    before_segments = [blocker_segment, urgent_segment]
    before_lots = [urgent_lot, blocker_lot]
    before_score = compute_score(before_segments, before_lots, data, config=config)

    repaired = repair_alternative_machine_delivery(
        before_segments,
        before_lots,
        data,
        config,
        runs=[urgent_run, blocker_run],
    )

    urgent_completion = max(
        segment.day_idx
        for segment in repaired.segments
        if segment.run_id == urgent_run.id
    )
    blocker_completion = max(
        segment.day_idx
        for segment in repaired.segments
        if segment.run_id == blocker_run.id
    )
    assert before_score["tardy_count"] == 1
    assert urgent_completion == 0
    assert blocker_completion == 1
    assert repaired.after_score["tardy_count"] == 0
    assert any(move["kind"] == "coordinated_runs" for move in repaired.moves)
    assert_plan_valid(repaired.segments, data, config, lots=repaired.lots)


def test_same_machine_reflow_places_earlier_order_before_later_order():
    urgent_op = _op("URGENT-SAME", alt=None, priority=10)
    blocker_op = _op(
        "LATER-SAME",
        alt=None,
        tool="T2",
        demand_day=1,
        rate=100 * 60 / 990,
    )
    data = _data([urgent_op, blocker_op])
    config = _config()
    urgent_run, urgent_lot, urgent_segment = _run_and_segment(
        urgent_op,
        day=1,
        due=0,
    )
    blocker_run, blocker_lot, blocker_segment = _run_and_segment(
        blocker_op,
        day=0,
        prod_min=990,
        setup_min=30,
        due=1,
    )
    before_segments = [blocker_segment, urgent_segment]
    before_lots = [urgent_lot, blocker_lot]

    repaired = repair_alternative_machine_delivery(
        before_segments,
        before_lots,
        data,
        config,
        runs=[urgent_run, blocker_run],
    )

    urgent_start = min(
        (segment.day_idx, segment.start_min)
        for segment in repaired.segments
        if segment.run_id == urgent_run.id
    )
    blocker_start = min(
        (segment.day_idx, segment.start_min)
        for segment in repaired.segments
        if segment.run_id == blocker_run.id
    )
    assert urgent_start < blocker_start
    assert urgent_start[0] == 0
    assert repaired.after_score["tardy_count"] == 0
    assert any(move["kind"] == "coordinated_runs" for move in repaired.moves)
    assert {segment.machine_id for segment in repaired.segments} == {"M1"}
    assert_plan_valid(repaired.segments, data, config, lots=repaired.lots)


def test_same_machine_reflow_can_move_only_trailing_blockers():
    """Preserve near-due work and move the tail that hides an idle window."""
    target_op = _op("TARGET-TAIL", alt=None, qty=100, rate=100 * 60 / 1500)
    first_op = _op("FIRST-FIXED", alt=None, tool="T2", demand_day=1, rate=100 * 60 / 980)
    second_op = _op("SECOND-FIXED", alt=None, tool="T3", demand_day=2, rate=100 * 60 / 980)
    tail_op = _op("TAIL-BLOCKER", alt=None, tool="T4", demand_day=3, rate=100 * 60 / 980)
    ops = [target_op, first_op, second_op, tail_op]
    data = _data(ops)
    data.workdays = [
        "2026-09-14",
        "2026-09-15",
        "2026-09-16",
        "2026-09-17",
        "2026-09-18",
        "2026-09-21",
        "2026-09-22",
    ]
    data.n_days = len(data.workdays)
    for op, due in zip(ops, [0, 1, 2, 5], strict=True):
        op.d = [0] * data.n_days
        op.d[due] = 100

    config = _config()
    target_run, target_lot, target_template = _run_and_segment(
        target_op,
        day=3,
        prod_min=1500,
        setup_min=30,
        due=0,
    )
    target_segments = [
        replace(
            target_template,
            day_idx=3,
            start_min=420,
            end_min=930,
            shift="A",
            qty=32,
            prod_min=480.0,
        ),
        replace(
            target_template,
            day_idx=3,
            start_min=930,
            end_min=1430,
            shift="B",
            qty=34,
            prod_min=500.0,
            setup_min=0.0,
            is_continuation=True,
        ),
        replace(
            target_template,
            day_idx=4,
            start_min=420,
            end_min=940,
            shift="A",
            qty=34,
            prod_min=520.0,
            setup_min=0.0,
            is_continuation=True,
        ),
    ]
    first_run, first_lot, first_segment = _run_and_segment(
        first_op,
        day=0,
        prod_min=980,
        setup_min=30,
        due=1,
    )
    second_run, second_lot, second_segment = _run_and_segment(
        second_op,
        day=1,
        prod_min=980,
        setup_min=30,
        due=2,
    )
    tail_run, tail_lot, tail_segment = _run_and_segment(
        tail_op,
        day=2,
        prod_min=980,
        setup_min=30,
        due=5,
    )

    def split_full_day(segment: Segment) -> list[Segment]:
        return [
            replace(
                segment,
                end_min=930,
                qty=49,
                prod_min=480.0,
            ),
            replace(
                segment,
                start_min=930,
                end_min=1430,
                shift="B",
                qty=51,
                prod_min=500.0,
                setup_min=0.0,
                is_continuation=True,
            ),
        ]

    before_segments = [
        *split_full_day(first_segment),
        *split_full_day(second_segment),
        *split_full_day(tail_segment),
        *target_segments,
    ]
    before_lots = [target_lot, first_lot, second_lot, tail_lot]
    before_score = compute_score(before_segments, before_lots, data, config=config)

    repaired = repair_alternative_machine_delivery(
        before_segments,
        before_lots,
        data,
        config,
        runs=[target_run, first_run, second_run, tail_run],
    )

    completion = {
        run_id: max(
            segment.day_idx
            for segment in repaired.segments
            if segment.run_id == run_id
        )
        for run_id in (target_run.id, first_run.id, second_run.id, tail_run.id)
    }
    coordinated = next(
        move for move in repaired.moves if move["kind"] == "coordinated_runs"
    )

    assert completion[target_run.id] < 4
    assert completion[first_run.id] <= 1
    assert completion[second_run.id] <= 2
    assert completion[tail_run.id] <= 5
    assert repaired.after_score["tardy_count"] == before_score["tardy_count"] == 1
    assert repaired.after_score["total_tardiness"] < before_score["total_tardiness"]
    assert set(coordinated["run_ids"]) == {target_run.id, tail_run.id}
    assert_plan_valid(repaired.segments, data, config, lots=repaired.lots)


def test_grouped_twin_lots_keep_all_output_quantities_after_machine_move():
    first_op = _op("TWIN-A", qty=200)
    second_op = _op("TWIN-B", qty=200)
    data = _data([first_op, second_op])
    config = _config()
    lots = []
    segments = []
    for index in range(2):
        lot = Lot(
            id=f"LOT-TWIN-{index}",
            op_id=first_op.id,
            sku=first_op.sku,
            tool_id="T1",
            machine_id="M1",
            alt_machine_id="M2",
            qty=100,
            prod_min=60.0,
            setup_min=30.0,
            edd=0,
            is_twin=True,
            twin_outputs=[
                (first_op.id, first_op.sku, 100),
                (second_op.id, second_op.sku, 100),
            ],
            original_edd=0,
            internal_deadline=0,
            delivery_day=0,
            production_due_day=0,
        )
        lots.append(lot)
        setup = 30 if index == 0 else 0
        start = 450 + index * 60
        segments.append(
            Segment(
                lot_id=lot.id,
                run_id="RUN-TWINS",
                machine_id="M1",
                tool_id="T1",
                day_idx=1,
                start_min=start - setup,
                end_min=start + 60,
                shift="A",
                qty=100,
                prod_min=60.0,
                setup_min=float(setup),
                is_continuation=index > 0,
                edd=0,
                sku=first_op.sku,
                twin_outputs=list(lot.twin_outputs or []),
                lot_qty=100,
                run_qty=200,
                run_setup_min=30.0,
                run_lot_count=2,
                original_edd=0,
                internal_deadline=0,
                delivery_day=0,
                production_due_day=0,
            )
        )
    run = ToolRun(
        id="RUN-TWINS",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id="M2",
        lots=lots,
        setup_min=30.0,
        total_prod_min=120.0,
        total_min=150.0,
        edd=0,
        production_due_day=0,
    )
    data.machine_blocked_days["M1"] = {0}

    repaired = repair_alternative_machine_delivery(
        segments, lots, data, config, runs=[run]
    )

    assert {segment.machine_id for segment in repaired.segments} == {"M2"}
    assert repaired.after_score["tardy_count"] == 0
    assert sum(segment.setup_min for segment in repaired.segments) == 30
    assert sum(segment.prod_min for segment in repaired.segments) == 120
    for op_id in (first_op.id, second_op.id):
        assert sum(
            qty
            for segment in repaired.segments
            for output_id, _sku, qty in segment.twin_outputs or []
            if output_id == op_id
        ) == 200
    assert_plan_valid(repaired.segments, data, config, lots=repaired.lots)


def test_tool_outage_reflows_urgent_run_and_retained_setup_chain_before_later_work():
    """The BFP079 failure mode is repaired across both eligible machines."""

    ops = [
        _op("URGENT", tool="T1", rate=15),
        _op("URGENT-SUCCESSOR", tool="T1", rate=15),
        _op("NOVEMBER-A", tool="T1", rate=15),
        _op("NOVEMBER-B", tool="T1", rate=15),
    ]
    data = _data(ops)
    data.workdays = [f"2027-01-{day:02d}" for day in range(4, 16)]
    data.n_days = len(data.workdays)
    data.tool_blocked_days["T1"] = {0, 1, 2}
    config = _config()
    config.setup_families = {"T1": [[op.sku for op in ops]]}
    family = "|".join(sorted(op.sku for op in ops))

    specifications = [
        (ops[0], "RUN-URGENT", 8, 3, 30),
        (ops[1], "RUN-URGENT-SUCCESSOR", 9, 4, 0),
        (ops[2], "RUN-NOVEMBER-A", 3, 6, 30),
        (ops[3], "RUN-NOVEMBER-B", 4, 7, 0),
    ]
    runs = []
    lots = []
    segments = []
    for op, run_id, scheduled_day, due, setup in specifications:
        # Canonical demand must match each lot's due day: the no-loss
        # contract checks every order individually.
        op.d = [0] * data.n_days
        op.d[due] = 100
        run, lot, segment = _run_and_segment(
            op,
            run_id=run_id,
            machine="M1" if "URGENT" in run_id else "M2",
            day=scheduled_day,
            prod_min=400,
            setup_min=setup,
            due=due,
        )
        lot.setup_family = segment.setup_family = family
        runs.append(run)
        lots.append(lot)
        segments.append(segment)

    before = compute_score(segments, lots, data, config=config)
    repaired = repair_alternative_machine_delivery(
        segments,
        lots,
        data,
        config,
        runs=runs,
    )

    starts = {
        run.id: min(
            (segment.day_idx, segment.start_min)
            for segment in repaired.segments
            if segment.run_id == run.id
        )
        for run in runs
    }
    ordered_ids = [item[1] for item in specifications]

    assert before["released_tool_priority_inversions"] > 0
    assert repaired.after_score["released_tool_priority_inversions"] == 0
    assert [starts[run_id] for run_id in ordered_ids] == sorted(
        starts[run_id] for run_id in ordered_ids
    )
    assert starts["RUN-URGENT"][0] == 3
    coordinated = next(
        move for move in repaired.moves if move["kind"] == "coordinated_runs"
    )
    assert set(coordinated["run_ids"]) == set(ordered_ids)
    assert_plan_valid(repaired.segments, data, config, lots=repaired.lots)
