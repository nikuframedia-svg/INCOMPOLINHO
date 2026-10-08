from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.scheduler.gap_filling import (
    PartialGapOpportunity,
    apply_partial_gap_move,
    build_legal_interval_context,
    evaluate_legal_interval,
    find_internal_continuation_opportunities,
    find_opening_gap_opportunities,
    split_production_at_shift_boundaries,
)
from backend.scheduler.operators import compute_operator_alerts
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import coverage_metrics
from backend.types import EngineData, MachineInfo


def _config(*, operators: int = 6) -> FactoryConfig:
    return FactoryConfig(
        machines={
            "M1": MachineConfig("M1", "Grandes"),
            "M2": MachineConfig("M2", "Grandes"),
        },
        operators={
            ("Grandes", "A"): operators,
            ("Grandes", "B"): operators,
        },
    )


def _data() -> EngineData:
    return EngineData(
        ops=[],
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Grandes", day_capacity=1020),
        ],
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-09-{day:02d}" for day in range(1, 15)],
        n_days=14,
        holidays=[],
    )


def _lot(*, twin: bool = False) -> Lot:
    return Lot(
        id="L1",
        op_id="OP1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=101,
        prod_min=170,
        setup_min=30,
        edd=5,
        original_edd=5,
        is_twin=twin,
        twin_outputs=[("OP1", "SKU1", 101), ("OP2", "SKU2", 101)] if twin else None,
    )


def test_fast_interval_search_matches_detailed_resource_checks():
    from dataclasses import replace

    config, data = _config(operators=1), _data()
    source = Segment(
        lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
        day_idx=3, start_min=600, end_min=800, shift="A", qty=101,
        prod_min=170, setup_min=30,
    )
    segments = [
        source,
        replace(source, lot_id="L2", run_id="R2", tool_id="T2", day_idx=0),
        replace(source, lot_id="L3", run_id="R3", machine_id="M2", day_idx=1),
        replace(source, lot_id="L4", run_id="R4", machine_id="M2", tool_id="T3", day_idx=2),
    ]
    data.machine_blocked_intervals = {"M1": [{"start_day": 1, "start_min": 420, "end_min": 500}]}
    data.tool_blocked_intervals = {"T1": [{"start_day": 2, "start_min": 420, "end_min": 500}]}
    data.operator_blocked_intervals = [
        {"start_day": 3, "start_min": 420, "end_min": 500, "group": "Grandes", "shift": "A", "count": 1}
    ]
    context = build_legal_interval_context(segments, [_lot()], data, config)
    outcomes = set()
    for day in range(4):
        for start in range(400, 1441, 20):
            for duration in (30, 90, 540):
                for setup in (0, 30):
                    args = (segments, source, data, config, day, start, start + duration)
                    detailed = evaluate_legal_interval(*args, setup_min=setup, context=context)
                    fast = evaluate_legal_interval(*args, setup_min=setup, context=context, explain=False)
                    assert (fast.allowed, fast.shift_id) == (detailed.allowed, detailed.shift_id)
                    outcomes.add(fast.allowed)
    assert outcomes == {True, False}


def test_shift_split_conserves_primary_and_twin_outputs_exactly():
    source = Segment(
        lot_id="L1",
        run_id="R1",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=800,
        end_min=1000,
        shift="A",
        qty=101,
        prod_min=170,
        setup_min=30,
        twin_outputs=[("OP1", "SKU1", 101), ("OP2", "SKU2", 101)],
    )

    result = split_production_at_shift_boundaries([source], _config())

    assert [(segment.start_min, segment.end_min) for segment in result] == [
        (800, 930),
        (930, 1000),
    ]
    assert [segment.shift for segment in result] == ["A", "B"]
    assert [segment.setup_min for segment in result] == [30, 0]
    assert sum(segment.prod_min for segment in result) == 170
    assert sum(segment.qty for segment in result) == 101
    assert {
        op_id: sum(
            qty
            for segment in result
            for current_op_id, _sku, qty in segment.twin_outputs or []
            if current_op_id == op_id
        )
        for op_id in ("OP1", "OP2")
    } == {"OP1": 101, "OP2": 101}


def test_shift_split_preserves_existing_adjacent_fragments():
    """An unrelated move cannot rewrite a started lot's segment identity."""
    from backend.plans.serialize import schedule_fingerprint

    first = Segment(
        lot_id="HISTORY", run_id="H", machine_id="M2", tool_id="T2",
        day_idx=0, start_min=420, end_min=480, shift="A", qty=60,
        prod_min=60, setup_min=0,
    )
    second = Segment(
        lot_id="HISTORY", run_id="H", machine_id="M2", tool_id="T2",
        day_idx=0, start_min=480, end_min=540, shift="A", qty=60,
        prod_min=60, setup_min=0,
    )
    crossing = Segment(
        lot_id="OTHER", run_id="O", machine_id="M1", tool_id="T1",
        day_idx=0, start_min=900, end_min=960, shift="A", qty=60,
        prod_min=60, setup_min=0,
    )

    before = schedule_fingerprint([first, second], [])
    data = _data()
    data.preserved_lot_proofs = {"HISTORY": "preserved"}
    result = split_production_at_shift_boundaries([first, second, crossing], _config(), data)
    history = [segment for segment in result if segment.lot_id == "HISTORY"]

    assert history == [first, second]
    assert schedule_fingerprint(history, []) == before
    assert [(s.start_min, s.end_min, s.shift) for s in result if s.lot_id == "OTHER"] == [
        (900, 930, "A"), (930, 960, "B"),
    ]


def test_shift_split_skips_a_closed_gap_without_losing_output():
    config = FactoryConfig(
        shifts=[
            ShiftConfig("A", 420, 720),
            ShiftConfig("B", 780, 1020),
        ]
    )
    source = Segment(
        lot_id="L1",
        run_id="R1",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=700,
        end_min=800,
        shift="A",
        qty=100,
        prod_min=100,
        setup_min=0,
    )

    result = split_production_at_shift_boundaries([source], config)

    assert [
        (segment.day_idx, segment.start_min, segment.end_min, segment.shift)
        for segment in result
    ] == [(0, 700, 720, "A"), (0, 780, 860, "B")]
    assert sum(segment.prod_min for segment in result) == 100
    assert sum(segment.qty for segment in result) == 100


def test_setup_crossing_shift_is_split_without_moving_physical_work():
    lot = _lot(twin=True)
    lot.prod_min = 442
    lot.setup_min = 60
    source = Segment(
        lot_id="L1",
        run_id="R1",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=919,
        end_min=1421,
        shift="A",
        qty=101,
        prod_min=442,
        setup_min=60,
        twin_outputs=list(lot.twin_outputs or []),
    )

    result = split_production_at_shift_boundaries(
        [source],
        _config(),
        _data(),
        [lot],
    )

    assert [
        (segment.start_min, segment.end_min, segment.shift)
        for segment in result
    ] == [(919, 930, "A"), (930, 1421, "B")]
    assert [segment.setup_min for segment in result] == [11, 49]
    assert [segment.prod_min for segment in result] == [0, 442]
    assert sum(segment.qty for segment in result) == 101
    assert {
        op_id: sum(
            qty
            for segment in result
            for current_op_id, _sku, qty in segment.twin_outputs or []
            if current_op_id == op_id
        )
        for op_id in ("OP1", "OP2")
    } == {"OP1": 101, "OP2": 101}


def test_setup_crossing_shift_does_not_move_other_setup_work():
    lot = _lot()
    lot.prod_min = 442
    lot.setup_min = 60
    source = Segment(
        lot_id="L1",
        run_id="R1",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=919,
        end_min=1421,
        shift="A",
        qty=101,
        prod_min=442,
        setup_min=60,
    )
    competing_setup = Segment(
        lot_id="OTHER",
        run_id="R2",
        machine_id="M2",
        tool_id="T2",
        day_idx=0,
        start_min=870,
        end_min=930,
        shift="A",
        qty=0,
        prod_min=0,
        setup_min=60,
    )

    result = split_production_at_shift_boundaries(
        [source, competing_setup],
        _config(),
        _data(),
        [lot],
    )

    moved = [segment for segment in result if segment.lot_id == "L1"]
    assert [(segment.start_min, segment.end_min) for segment in moved] == [
        (919, 930),
        (930, 1421),
    ]
    assert sum(segment.setup_min for segment in moved) == 60
    assert sum(segment.prod_min for segment in moved) == 442


def test_partial_move_conserves_twin_outputs_and_closes_only_the_legal_gap():
    lot = _lot(twin=True)
    first = Segment(
        lot_id="L1",
        run_id="R1",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=420,
        end_min=520,
        shift="A",
        qty=0,
        prod_min=0,
        setup_min=30,
    )
    source = Segment(
        lot_id="L1",
        run_id="R1",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=700,
        end_min=870,
        shift="A",
        qty=101,
        prod_min=170,
        is_continuation=True,
        twin_outputs=list(lot.twin_outputs or []),
    )
    opportunity = PartialGapOpportunity(
        lot_id="L1",
        machine_id="M1",
        tool_id="T1",
        gap_day=0,
        gap_start_min=520,
        gap_end_min=600,
        movable_prod_min=80,
        source_day=0,
        source_start_min=700,
        source_end_min=870,
        source_qty=101,
    )

    result = apply_partial_gap_move([first, source], opportunity, _config())

    assert any(
        segment.start_min == 520 and segment.end_min == 600 for segment in result
    )
    assert sum(segment.prod_min for segment in result) == 170
    assert coverage_metrics(result, [lot])["missing_qty"] == 0
    assert coverage_metrics(result, [lot])["overproduced_qty"] == 0
    assert coverage_metrics(result, [lot])["twin_output_mismatches"] == 0


def test_partial_opening_move_carries_every_contiguous_setup_fragment():
    lot = _lot()
    lot.prod_min = 40
    setup_a = Segment(
        lot_id="L1",
        run_id="R1",
        machine_id="M1",
        tool_id="T1",
        day_idx=1,
        start_min=900,
        end_min=930,
        shift="A",
        qty=0,
        prod_min=0,
        setup_min=30,
    )
    source = Segment(
        lot_id="L1",
        run_id="R1",
        machine_id="M1",
        tool_id="T1",
        day_idx=1,
        start_min=930,
        end_min=1000,
        shift="B",
        qty=101,
        prod_min=40,
        setup_min=30,
    )
    opportunity = PartialGapOpportunity(
        lot_id="L1",
        machine_id="M1",
        tool_id="T1",
        gap_day=0,
        gap_start_min=420,
        gap_end_min=500,
        movable_prod_min=20,
        source_day=1,
        source_start_min=930,
        source_end_min=1000,
        source_qty=101,
        movable_setup_min=60,
    )

    result = apply_partial_gap_move(
        [setup_a, source],
        opportunity,
        _config(),
        _data(),
    )

    assert sum(segment.setup_min for segment in result) == 60
    assert sum(segment.prod_min for segment in result) == 40
    assert sum(segment.qty for segment in result) == 101
    assert not any(segment.day_idx == 1 and segment.start_min == 900 for segment in result)
    moved = min(result, key=lambda segment: (segment.day_idx, segment.start_min))
    assert (moved.day_idx, moved.start_min, moved.end_min) == (0, 420, 500)


def test_complete_opening_block_can_overlap_the_position_it_replaces():
    data = _data()
    lot = _lot()
    lot.edd = 6
    lot.original_edd = 6
    lot.prod_min = 90
    competing_setup = Segment(
        lot_id="OTHER",
        run_id="R2",
        machine_id="M2",
        tool_id="T2",
        day_idx=1,
        start_min=420,
        end_min=580,
        shift="A",
        qty=0,
        prod_min=0,
        setup_min=160,
    )
    source = Segment(
        lot_id="L1",
        run_id="R1",
        machine_id="M1",
        tool_id="T1",
        day_idx=1,
        start_min=600,
        end_min=720,
        shift="A",
        qty=101,
        prod_min=90,
        setup_min=30,
    )

    opportunities = find_opening_gap_opportunities(
        [competing_setup, source],
        [lot],
        data,
        _config(),
    )

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert (opportunity.gap_start_min, opportunity.gap_end_min) == (580, 700)
    assert opportunity.movable_prod_min == 90


def test_opening_move_does_not_break_setup_for_following_campaign():
    data = _data()
    config = _config()
    config.shifts = [ShiftConfig("A", 420, 595)]

    source_lot = _lot()
    source_lot.id = "VUL"
    source_lot.op_id = "OP_VUL"
    source_lot.tool_id = "T_VUL"
    source_lot.sku = "VUL199"
    source_lot.prod_min = 12
    source_lot.setup_min = 30

    following_lot = _lot()
    following_lot.id = "BFP_NEXT"
    following_lot.op_id = "OP_BFP"
    following_lot.tool_id = "T_BFP"
    following_lot.sku = "BFP112"
    following_lot.prod_min = 80
    following_lot.setup_min = 30

    segments = [
        Segment(
            lot_id="BFP_PREVIOUS",
            run_id="R_BFP_PREVIOUS",
            machine_id="M1",
            tool_id="T_BFP",
            day_idx=0,
            start_min=420,
            end_min=500,
            shift="A",
            qty=100,
            prod_min=50,
            setup_min=30,
            sku="BFP112",
        ),
        Segment(
            lot_id="BFP_NEXT",
            run_id="R_BFP_NEXT",
            machine_id="M1",
            tool_id="T_BFP",
            day_idx=1,
            start_min=420,
            end_min=500,
            shift="A",
            qty=101,
            prod_min=80,
            setup_min=0,
            run_setup_min=30,
            sku="BFP112",
            is_continuation=True,
        ),
        Segment(
            lot_id="FILLER",
            run_id="R_FILLER",
            machine_id="M1",
            tool_id="T_FILLER",
            day_idx=1,
            start_min=500,
            end_min=523,
            shift="A",
            qty=23,
            prod_min=23,
            sku="FILLER",
        ),
        Segment(
            lot_id="VUL",
            run_id="R_VUL",
            machine_id="M1",
            tool_id="T_VUL",
            day_idx=1,
            start_min=523,
            end_min=565,
            shift="A",
            qty=101,
            prod_min=12,
            setup_min=30,
            run_setup_min=30,
            sku="VUL199",
        ),
    ]

    opportunities = find_opening_gap_opportunities(
        segments,
        [source_lot, following_lot],
        data,
        config,
    )

    assert [
        opportunity for opportunity in opportunities if opportunity.lot_id == "VUL"
    ] == []


def test_continuation_gap_is_not_available_while_tool_is_on_another_machine():
    data = _data()
    lot = _lot()
    segments = [
        Segment(
            lot_id="L1",
            run_id="R1",
            machine_id="M1",
            tool_id="T1",
            day_idx=0,
            start_min=420,
            end_min=520,
            shift="A",
            qty=50,
            prod_min=80,
            setup_min=20,
        ),
        Segment(
            lot_id="OTHER",
            run_id="R2",
            machine_id="M2",
            tool_id="T1",
            day_idx=0,
            start_min=520,
            end_min=700,
            shift="A",
            qty=1,
            prod_min=180,
        ),
        Segment(
            lot_id="L1",
            run_id="R1",
            machine_id="M1",
            tool_id="T1",
            day_idx=0,
            start_min=700,
            end_min=790,
            shift="A",
            qty=51,
            prod_min=90,
            is_continuation=True,
        ),
    ]

    assert find_internal_continuation_opportunities(
        segments,
        [lot],
        data,
        _config(),
    ) == []


def test_continuation_gap_is_not_available_without_operators():
    data = _data()
    lot = _lot()
    segments = [
        Segment(
            lot_id="L1",
            run_id="R1",
            machine_id="M1",
            tool_id="T1",
            day_idx=0,
            start_min=420,
            end_min=520,
            shift="A",
            qty=50,
            prod_min=80,
            setup_min=20,
        ),
        Segment(
            lot_id="L1",
            run_id="R1",
            machine_id="M1",
            tool_id="T1",
            day_idx=0,
            start_min=700,
            end_min=790,
            shift="A",
            qty=51,
            prod_min=90,
            is_continuation=True,
        ),
    ]

    assert find_internal_continuation_opportunities(
        segments,
        [lot],
        data,
        _config(operators=0),
    ) == []


def test_same_tool_next_lot_can_use_partial_gap_without_another_setup():
    data = _data()
    first_lot = _lot()
    next_lot = _lot()
    next_lot.id = "L2"
    next_lot.op_id = "OP2"
    next_lot.qty = 120
    next_lot.prod_min = 120
    next_lot.edd = 6
    next_lot.original_edd = 6
    first_lot.sku = "SHARED"
    next_lot.sku = "SHARED"
    segments = [
        Segment(
            lot_id="L1",
            run_id="R1",
            machine_id="M1",
            tool_id="T1",
            day_idx=1,
            start_min=420,
            end_min=520,
            shift="A",
            qty=101,
            prod_min=80,
            setup_min=20,
            sku="SHARED",
        ),
        Segment(
            lot_id="L2",
            run_id="R2",
            machine_id="M1",
            tool_id="T1",
            day_idx=1,
            start_min=700,
            end_min=820,
            shift="A",
            qty=120,
            prod_min=120,
            is_continuation=True,
            sku="SHARED",
        ),
    ]

    opportunities = find_internal_continuation_opportunities(
        segments,
        [first_lot, next_lot],
        data,
        _config(),
    )

    assert len(opportunities) == 1
    assert opportunities[0].lot_id == "L2"
    assert opportunities[0].gap_start_min == 520
    assert opportunities[0].movable_prod_min == 120


def test_lower_priority_lot_cannot_interrupt_higher_priority_campaign():
    data = _data()
    urgent = _lot()
    urgent.qty = 160
    urgent.prod_min = 160
    later = _lot()
    later.id = "L2"
    later.op_id = "OP2"
    later.edd = 8
    later.original_edd = 8
    segments = [
        Segment(
            lot_id="L1",
            run_id="R1",
            machine_id="M1",
            tool_id="T1",
            day_idx=0,
            start_min=420,
            end_min=500,
            shift="A",
            qty=50,
            prod_min=60,
            setup_min=20,
        ),
        Segment(
            lot_id="L2",
            run_id="R2",
            machine_id="M1",
            tool_id="T1",
            day_idx=0,
            start_min=600,
            end_min=660,
            shift="A",
            qty=100,
            prod_min=60,
            is_continuation=True,
        ),
        Segment(
            lot_id="L1",
            run_id="R1",
            machine_id="M1",
            tool_id="T1",
            day_idx=0,
            start_min=700,
            end_min=800,
            shift="A",
            qty=110,
            prod_min=100,
            is_continuation=True,
        ),
    ]

    opportunities = find_internal_continuation_opportunities(
        segments,
        [urgent, later],
        data,
        _config(),
    )

    assert not any(opportunity.lot_id == "L2" for opportunity in opportunities)


def test_operator_alert_splits_a_cross_shift_segment_by_clock_time():
    segment = Segment(
        lot_id="L1",
        run_id="R1",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=900,
        end_min=960,
        shift="A",
        qty=100,
        prod_min=60,
    )
    config = _config(operators=1)
    config.operators[("Grandes", "B")] = 0

    alerts = compute_operator_alerts([segment], _data(), config)

    assert [(alert.shift, alert.required, alert.available) for alert in alerts] == [
        ("B", 1, 0)
    ]
