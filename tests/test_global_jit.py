"""Direct acceptance tests for the global APS constructor."""

from __future__ import annotations

import time

import pytest

from backend.analytics.capacity import compute_capacity
from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.dispatch import per_machine_dispatch
from backend.scheduler.gates import build_gate_report
from backend.scheduler.global_jit import (
    GlobalJITResult,
    HAS_ORTOOLS,
    _allowed_setup_starts,
    _effective_time_limit,
    materialise_fixed_run,
    solve_global_jit,
)
from backend.scheduler.setup_identity import segment_setup_identity
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.scheduler.validation import assert_plan_valid
from backend.transform.calendars import apply_calendars
from backend.types import EOp, EngineData, MachineInfo

pytestmark = pytest.mark.skipif(not HAS_ORTOOLS, reason="OR-Tools não instalado")


def _op(
    op_id: str,
    machine: str,
    tool: str,
    *,
    sku: str | None = None,
    demand: list[int] | None = None,
) -> EOp:
    return EOp(
        id=op_id,
        sku=sku or f"SKU-{op_id}",
        client="CLIENTE",
        designation="Peça",
        m=machine,
        t=tool,
        pH=100,
        sH=0.5,
        operators=1,
        eco_lot=0,
        alt=None,
        stk=0,
        backlog=0,
        d=demand or [0, 100, 0, 0, 0, 0, 0, 0, 0, 0],
        oee=1.0,
        wip=0,
    )


def _config(*machine_ids: str) -> FactoryConfig:
    config = FactoryConfig()
    config.machines = {
        machine_id: MachineConfig(
            id=machine_id,
            group="Medias" if machine_id == "M2" else "Grandes",
        )
        for machine_id in machine_ids
    }
    # A configured extra machine creates no capacity until it is in EngineData.
    config.machines.setdefault(
        "M20",
        MachineConfig(id="M20", group="Grandes", active=True),
    )
    return config


def _engine(ops: list[EOp], machine_ids: list[str], n_days: int = 12) -> EngineData:
    config = _config(*machine_ids)
    return EngineData(
        ops=ops,
        machines=[
            MachineInfo(
                id=machine_id,
                group=config.machines[machine_id].group,
                day_capacity=config.day_capacity_min,
            )
            for machine_id in machine_ids
        ],
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-07-{day + 1:02d}" for day in range(n_days)],
        n_days=n_days,
        holidays=[],
    )


def _run(
    op_id: str,
    machine: str,
    tool: str,
    *,
    sku: str | None = None,
    qty: int = 100,
    prod_min: float = 60,
    setup_min: float = 30,
    internal_deadline: int = 4,
    delivery_day: int = 4,
    planning_priority: int = 0,
) -> ToolRun:
    lot = Lot(
        id=f"LOT-{op_id}",
        op_id=op_id,
        sku=sku or f"SKU-{op_id}",
        tool_id=tool,
        machine_id=machine,
        alt_machine_id=None,
        qty=qty,
        prod_min=prod_min,
        setup_min=setup_min,
        edd=delivery_day,
        is_twin=False,
        internal_deadline=internal_deadline,
        delivery_day=delivery_day,
        planning_priority=planning_priority,
    )
    return ToolRun(
        id=f"RUN-{op_id}",
        tool_id=tool,
        machine_id=machine,
        alt_machine_id=None,
        lots=[lot],
        setup_min=setup_min,
        total_prod_min=prod_min,
        total_min=setup_min + prod_min,
        edd=internal_deadline,
    )


def test_extra_machine_is_used_when_the_isop_contains_its_operation():
    op = _op("OP20", "M20", "T20")
    data = _engine([op], ["M20"])
    result = solve_global_jit(
        [_run("OP20", "M20", "T20")],
        data,
        _config("M20"),
        time_limit_s=1.0,
    )

    assert result is not None and result.candidate_found
    assert {segment.machine_id for segment in result.segments} == {"M20"}


def test_extra_machine_master_data_does_not_create_ghost_capacity_when_absent():
    op = _op("OP1", "M1", "T1")
    data = _engine([op], ["M1"])
    config = _config("M1")
    result = solve_global_jit(
        [_run("OP1", "M1", "T1")],
        data,
        config,
        time_limit_s=1.0,
    )

    assert result is not None and result.candidate_found
    assert {segment.machine_id for segment in result.segments} == {"M1"}
    assert "M20" not in {
        row["machine_id"] for row in compute_capacity(result.segments, data, config)["items"]
    }


def test_exact_stop_preempts_long_run_and_preserves_day_zero_delivery():
    op = _op("OP1", "M1", "T1", demand=[100, 0, 0])
    op.pH, op.sH = 100 * 60 / 800, 0
    data = _engine([op], ["M1"], n_days=3)
    data.machine_blocked_intervals = {
        "M1": [
            {
                "id": "stop-10-12",
                "start_day": 0,
                "start_min": 600,
                "end_day": 0,
                "end_min": 720,
            }
        ]
    }
    config = _config("M1")
    run = _run(
        "OP1",
        "M1",
        "T1",
        qty=100,
        prod_min=800,
        setup_min=0,
        internal_deadline=0,
        delivery_day=0,
    )

    result = solve_global_jit([run], data, config, time_limit_s=2.0)

    assert result is not None and result.candidate_found
    produced = [segment for segment in result.segments if segment.prod_min > 0]
    assert {segment.day_idx for segment in produced} == {0}
    assert sum(segment.prod_min for segment in produced) == 800
    assert sum(segment.qty for segment in produced) == 100
    assert all(segment.end_min <= 600 or segment.start_min >= 720 for segment in produced)
    assert result.solver_status == "strict_feasible"
    assert result.feasibility["calendar_preemptions"] > 0
    assert_plan_valid(result.segments, data, config, lots=result.lots)


def test_calendar_gap_repair_batches_independent_moves(monkeypatch):
    import backend.scheduler.gap_filling as gaps
    from backend.scheduler.global_jit import _preempt_exact_calendar_gaps

    machines = [f"M{index}" for index in range(4)]
    ops = [_op(f"OP{index}", machine, f"T{index}") for index, machine in enumerate(machines)]
    data = _engine(ops, machines)
    data.machine_blocked_intervals = {
        "M0": [{"start_day": 2, "start_min": 600, "end_day": 2, "end_min": 720}]
    }
    config = _config(*machines)
    config.operators = {(group, shift): 10 for group in ("Grandes", "Medias") for shift in ("A", "B")}
    config.setup_crews = 4
    config.setup_crews_by_group = {"Grandes": 4, "Medias": 4}
    lots, segments = [], []
    for index, op in enumerate(ops):
        lot = _run(op.id, op.m, op.t, prod_min=60, setup_min=30).lots[0]
        lots.append(lot)
        segments.append(Segment(
            lot_id=lot.id, run_id=f"R{index}", machine_id=op.m, tool_id=op.t,
            day_idx=0, start_min=600, end_min=690, shift="A", qty=lot.qty,
            prod_min=60, setup_min=30, edd=lot.edd, sku=op.sku,
        ))
    scans = []
    original = gaps.find_gap_opportunities

    def counted(*args, **kwargs):
        scans.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(gaps, "find_gap_opportunities", counted)
    assert_plan_valid(segments, data, config, lots=lots)
    repaired, moved = _preempt_exact_calendar_gaps(segments, lots, data, config)
    assert moved == len(machines)
    assert len(scans) == 2
    assert all(segment.start_min == config.shift_a_start for segment in repaired)
    assert_plan_valid(repaired, data, config, lots=lots)


def test_global_jit_respects_machine_block_after_imported_horizon():
    op = _op("OP1", "M1", "T1", demand=[0, 0, 100])
    op.pH, op.sH = 100 * 60 / 1200, 0
    data = _engine([op], ["M1"], n_days=1)
    config = _config("M1")
    config.machine_unavailability = [
        {
            "id": "future-stop",
            "resource": "M1",
            "start_at": "2026-07-02T00:00:00+00:00",
            "end_at": "2026-07-03T00:00:00+00:00",
        }
    ]
    apply_calendars(data, config)
    run = _run(
        "OP1",
        "M1",
        "T1",
        qty=100,
        prod_min=1200,
        setup_min=0,
        internal_deadline=2,
        delivery_day=2,
    )

    result = solve_global_jit([run], data, config, time_limit_s=2.0)

    assert data.machine_blocked_days == {"M1": {1}}
    assert result is not None and result.candidate_found
    assert sum(segment.prod_min for segment in result.segments) == 1200
    assert all(segment.day_idx != 1 for segment in result.segments)
    assert_plan_valid(result.segments, data, config, lots=result.lots)


def test_recurring_stops_preempt_a_run_larger_than_every_contiguous_gap():
    first = _op("OP1", "M1", "T1", demand=[0, 0, 100, 0])
    second = _op("OP2", "M1", "T1", sku="SKU-OP2", demand=[0, 0, 100, 0])
    first.pH = second.pH = 100 * 60 / 1200
    data = _engine([first, second], ["M1"], n_days=4)
    data.machine_blocked_intervals = {
        "M1": [
            {
                "id": f"daily-stop-{day}",
                "start_day": day,
                "start_min": 600,
                "end_day": day,
                "end_min": 720,
            }
            for day in range(30)
        ]
    }
    config = _config("M1")
    run = _run(
        "OP1",
        "M1",
        "T1",
        qty=100,
        prod_min=1200,
        setup_min=30,
        internal_deadline=2,
        delivery_day=2,
    )
    run.lots[0].is_twin = True
    run.lots[0].twin_outputs = [
        ("OP1", "SKU-OP1", 100),
        ("OP2", "SKU-OP2", 100),
    ]

    result = solve_global_jit([run], data, config, time_limit_s=2.0)

    assert result is not None and result.candidate_found
    assert result.solver_status == "strict_feasible"
    assert result.feasibility["calendar_preemptive_fallback"] is True
    assert sum(segment.setup_min for segment in result.segments) == 30
    assert sum(segment.prod_min for segment in result.segments) == 1200
    assert sum(segment.qty for segment in result.segments) == 100
    assert {
        op_id: sum(
            qty
            for segment in result.segments
            for output_id, _sku, qty in segment.twin_outputs or []
            if output_id == op_id
        )
        for op_id in ("OP1", "OP2")
    } == {"OP1": 100, "OP2": 100}
    assert all(segment.end_min <= 600 or segment.start_min >= 720 for segment in result.segments)
    assert_plan_valid(result.segments, data, config, lots=result.lots)


def test_each_machine_prioritizes_its_earliest_rupture_before_lower_risk_work():
    data = _engine([], ["M1", "M2"], n_days=12)
    config = _config("M1", "M2")
    global_urgent = _run(
        "GLOBAL", "M1", "TG", prod_min=700, setup_min=0, internal_deadline=5, delivery_day=5
    )
    lower_risk = _run(
        "LOW", "M2", "TL", prod_min=700, setup_min=0, internal_deadline=6, delivery_day=6
    )
    machine_urgent = _run(
        "URGENT", "M2", "TU", prod_min=700, setup_min=0, internal_deadline=6, delivery_day=6
    )
    # Same release/delivery window on M2. The input order deliberately puts
    # the lower-risk lot first, so the result must come from priority logic.
    global_urgent.lots[0].original_edd = 0
    lower_risk.lots[0].original_edd = 2
    machine_urgent.lots[0].original_edd = 1

    result = solve_global_jit(
        [global_urgent, lower_risk, machine_urgent], data, config, time_limit_s=1.0
    )

    assert result is not None and result.candidate_found
    starts = {
        lot_id: min(
            (segment.day_idx, segment.start_min)
            for segment in result.segments
            if segment.lot_id == lot_id and segment.prod_min > 0
        )
        for lot_id in ("LOT-LOW", "LOT-URGENT")
    }
    assert starts["LOT-URGENT"] < starts["LOT-LOW"]


def test_same_machine_rupture_due_now_starts_before_later_reference():
    """A day-zero rupture cannot wait behind a less urgent released lot."""

    data = _engine([], ["M1"], n_days=12)
    config = _config("M1")
    later = _run(
        "LATER", "M1", "TL", prod_min=700, setup_min=0, internal_deadline=7, delivery_day=7
    )
    rupture_now = _run(
        "NOW", "M1", "TN", prod_min=700, setup_min=0, internal_deadline=0, delivery_day=0
    )
    later.lots[0].original_edd = 7
    rupture_now.lots[0].original_edd = 0

    result = solve_global_jit([later, rupture_now], data, config, time_limit_s=1.0)

    assert result is not None and result.candidate_found
    starts = {
        lot_id: min(
            (segment.day_idx, segment.start_min)
            for segment in result.segments
            if segment.lot_id == lot_id and segment.prod_min > 0
        )
        for lot_id in ("LOT-LATER", "LOT-NOW")
    }
    assert starts["LOT-NOW"] < starts["LOT-LATER"]


def test_longer_urgent_run_precedes_shorter_later_run_when_both_are_released():
    """Processing time must not invert the customer's rupture priority."""

    data = _engine([], ["M1"], n_days=12)
    data.machine_blocked_days = {"M1": {0, 1, 2}}
    config = _config("M1")
    urgent = _run(
        "URGENT-LONG",
        "M1",
        "TU",
        prod_min=700,
        setup_min=0,
        internal_deadline=6,
        delivery_day=6,
    )
    later = _run(
        "LATER-SHORT",
        "M1",
        "TL",
        prod_min=100,
        setup_min=0,
        internal_deadline=8,
        delivery_day=8,
    )
    urgent.lots[0].original_edd = 6
    later.lots[0].original_edd = 8

    result = solve_global_jit([later, urgent], data, config, time_limit_s=1.0)

    assert result is not None and result.candidate_found
    starts = {
        lot_id: min(
            (segment.day_idx, segment.start_min)
            for segment in result.segments
            if segment.lot_id == lot_id and segment.prod_min > 0
        )
        for lot_id in ("LOT-URGENT-LONG", "LOT-LATER-SHORT")
    }
    assert starts["LOT-URGENT-LONG"] < starts["LOT-LATER-SHORT"]
    urgent_end = max(
        (segment.day_idx, segment.end_min)
        for segment in result.segments
        if segment.lot_id == "LOT-URGENT-LONG" and segment.prod_min > 0
    )
    later_start = min(
        (segment.day_idx, segment.start_min)
        for segment in result.segments
        if segment.lot_id == "LOT-LATER-SHORT"
    )
    assert urgent_end <= later_start


def test_ready_work_can_fill_machine_before_more_urgent_material_is_released():
    """Priority must not manufacture idle time before material availability."""

    data = _engine([], ["M1"], n_days=14)
    config = _config("M1")
    urgent = _run(
        "URGENT-LATER-RELEASE",
        "M1",
        "TU",
        prod_min=300,
        setup_min=0,
        internal_deadline=10,
        delivery_day=10,
    )
    ready = _run(
        "READY-NOW",
        "M1",
        "TR",
        prod_min=300,
        setup_min=0,
        internal_deadline=5,
        delivery_day=5,
    )
    # Operational rupture priority is deliberately earlier, but its material
    # release (delivery - five workdays) is later than READY-NOW's release.
    urgent.lots[0].original_edd = 4
    ready.lots[0].original_edd = 5

    result = solve_global_jit([urgent, ready], data, config, time_limit_s=1.0)

    assert result is not None and result.candidate_found
    starts = {
        lot_id: min(
            (segment.day_idx, segment.start_min)
            for segment in result.segments
            if segment.lot_id == lot_id and segment.prod_min > 0
        )
        for lot_id in ("LOT-URGENT-LATER-RELEASE", "LOT-READY-NOW")
    }
    assert starts["LOT-READY-NOW"] < starts["LOT-URGENT-LATER-RELEASE"]


def test_shared_tool_follows_released_rupture_priority_across_machines():
    """A later order cannot reserve a shared tool ahead of an urgent one."""

    data = _engine([], ["M1", "M2"], n_days=12)
    config = _config("M1")
    config.machines["M2"] = MachineConfig("M2", "Grandes")
    config.machine_groups["M2"] = "Grandes"
    urgent = _run(
        "URGENT-TOOL",
        "M1",
        "SHARED",
        prod_min=500,
        setup_min=0,
        internal_deadline=6,
        delivery_day=6,
    )
    later = _run(
        "LATER-TOOL",
        "M2",
        "SHARED",
        prod_min=100,
        setup_min=0,
        internal_deadline=8,
        delivery_day=8,
    )
    urgent.lots[0].original_edd = 6
    later.lots[0].original_edd = 8

    result = solve_global_jit([later, urgent], data, config, time_limit_s=1.0)

    assert result is not None and result.candidate_found
    urgent_end = max(
        (segment.day_idx, segment.end_min)
        for segment in result.segments
        if segment.lot_id == "LOT-URGENT-TOOL" and segment.prod_min > 0
    )
    later_start = min(
        (segment.day_idx, segment.start_min)
        for segment in result.segments
        if segment.lot_id == "LOT-LATER-TOOL"
    )
    assert urgent_end <= later_start


def test_same_machine_preserves_all_released_rupture_priorities():
    """The second-most urgent released lot cannot trail a lower-risk one."""

    data = _engine([], ["M1"], n_days=12)
    config = _config("M1")
    runs = []
    for op_id, rupture_day in (("LOW", 4), ("MID", 3), ("HIGH", 2)):
        run = _run(
            op_id,
            "M1",
            f"T-{op_id}",
            prod_min=350,
            setup_min=0,
            internal_deadline=7,
            delivery_day=7,
        )
        run.lots[0].original_edd = rupture_day
        runs.append(run)

    result = solve_global_jit(runs, data, config, time_limit_s=1.0)

    assert result is not None and result.candidate_found
    starts = {
        lot_id: min(
            (segment.day_idx, segment.start_min)
            for segment in result.segments
            if segment.lot_id == lot_id and segment.prod_min > 0
        )
        for lot_id in ("LOT-HIGH", "LOT-MID", "LOT-LOW")
    }
    assert starts["LOT-HIGH"] < starts["LOT-MID"] < starts["LOT-LOW"]


def test_explicit_reference_priority_breaks_equal_rupture_ties():
    """Client priority wins only after the real rupture date is equal."""

    data = _engine([], ["M1"], n_days=12)
    config = _config("M1")
    ordinary = _run(
        "0040-1",
        "M1",
        "JDE002",
        prod_min=500,
        setup_min=0,
        internal_deadline=7,
        delivery_day=7,
        planning_priority=0,
    )
    priority = _run(
        "0040-2",
        "M1",
        "JDE002",
        prod_min=500,
        setup_min=0,
        internal_deadline=7,
        delivery_day=7,
        planning_priority=100,
    )
    ordinary.lots[0].original_edd = 4
    priority.lots[0].original_edd = 4

    result = solve_global_jit([ordinary, priority], data, config, time_limit_s=1.0)

    assert result is not None and result.candidate_found
    starts = {
        lot_id: min(
            (segment.day_idx, segment.start_min)
            for segment in result.segments
            if segment.lot_id == lot_id and segment.prod_min > 0
        )
        for lot_id in ("LOT-0040-1", "LOT-0040-2")
    }
    assert starts["LOT-0040-2"] < starts["LOT-0040-1"]


def test_explicit_customer_priority_precedes_aggregate_otd_count():
    """A declared customer priority can displace several ordinary day-zero lots."""

    data = _engine([], ["M1"], n_days=12)
    config = _config("M1")
    priority = _run(
        "0040-2",
        "M1",
        "JDE002",
        prod_min=900,
        setup_min=0,
        internal_deadline=0,
        delivery_day=0,
        planning_priority=100,
    )
    ordinary_a = _run(
        "ORD-A", "M1", "TA", prod_min=100, setup_min=0, internal_deadline=0, delivery_day=0
    )
    ordinary_b = _run(
        "ORD-B", "M1", "TB", prod_min=100, setup_min=0, internal_deadline=0, delivery_day=0
    )
    for run in (priority, ordinary_a, ordinary_b):
        run.lots[0].original_edd = 0

    result = solve_global_jit([ordinary_a, ordinary_b, priority], data, config, time_limit_s=2.0)

    assert result is not None and result.candidate_found
    priority_end = max(
        (segment.day_idx, segment.end_min)
        for segment in result.segments
        if segment.lot_id == "LOT-0040-2" and segment.prod_min > 0
    )
    assert priority_end[0] == 0


def test_real_expedition_otd_precedes_an_ordinary_internal_buffer():
    """An internal checkpoint may not displace a recoverable customer delivery."""

    data = _engine([], ["M1"], n_days=8)
    config = _config("M1")
    urgent = _run(
        "URGENT",
        "M1",
        "T1",
        prod_min=900,
        setup_min=0,
        internal_deadline=0,
        delivery_day=0,
    )
    buffered = _run(
        "BUFFERED",
        "M1",
        "T2",
        prod_min=200,
        setup_min=0,
        internal_deadline=0,
        delivery_day=5,
    )

    result = solve_global_jit([buffered, urgent], data, config, time_limit_s=2.0)

    assert result is not None and result.candidate_found
    urgent_end = max(
        (segment.day_idx, segment.end_min)
        for segment in result.segments
        if segment.lot_id == "LOT-URGENT" and segment.prod_min > 0
    )
    assert urgent_end[0] == 0
    score = compute_score(result.segments, result.lots, data, config=config)
    assert score["tardy_count"] == 0


def test_setup_starts_at_material_release_and_is_attached_to_production():
    """A setup is part of the production commitment, not standalone work."""

    data = _engine([], ["M1"], n_days=12)
    config = _config("M1")
    run = _run(
        "RELEASED",
        "M1",
        "T1",
        prod_min=60,
        setup_min=30,
        internal_deadline=8,
        delivery_day=8,
    )

    result = solve_global_jit([run], data, config, time_limit_s=1.0)

    assert result is not None and result.candidate_found
    assert_plan_valid(result.segments, data, config)
    opening = min(result.segments, key=lambda segment: (segment.day_idx, segment.start_min))
    production = min(
        (segment for segment in result.segments if segment.prod_min > 0),
        key=lambda segment: (segment.day_idx, segment.start_min),
    )
    assert opening.day_idx == 3
    assert production.day_idx >= 3
    assert opening.setup_min == 30
    assert opening.prod_min > 0 or (
        opening.end_min == config.shift_b_end and production.day_idx == opening.day_idx + 1
    )


def test_setup_uses_the_release_of_the_first_lot_in_a_campaign():
    data = _engine([], ["M1"], n_days=14)
    config = _config("M1")
    run = _run(
        "FIRST",
        "M1",
        "T1",
        prod_min=1020,
        setup_min=30,
        internal_deadline=5,
        delivery_day=5,
    )
    first = run.lots[0]
    first.customer_delivery_day = 5
    first.production_due_day = 5
    first.material_reference_day = 5
    first.material_release_day = 5

    second = _run(
        "SECOND",
        "M1",
        "T1",
        prod_min=10,
        setup_min=0,
        internal_deadline=10,
        delivery_day=10,
    ).lots[0]
    second.customer_delivery_day = 10
    second.production_due_day = 10
    second.material_reference_day = 10
    second.material_release_day = 0
    run.lots.append(second)
    run.total_prod_min = first.prod_min + second.prod_min
    run.total_min = run.setup_min + run.total_prod_min
    run.production_due_day = 5

    result = solve_global_jit([run], data, config, time_limit_s=1.0)

    assert result is not None and result.candidate_found
    setup_segments = [segment for segment in result.segments if segment.setup_min > 0]
    assert setup_segments
    assert min(segment.day_idx for segment in setup_segments) >= 5


def test_best_effort_protects_customer_before_subcontract_buffer() -> None:
    data = _engine([], ["M1"], n_days=8)
    data.machine_blocked_days["M1"] = {0, 1, 3, 4, 5}
    config = _config("M1")

    normal = _run(
        "NORMAL",
        "M1",
        "TN",
        prod_min=1020,
        setup_min=0,
        internal_deadline=5,
        delivery_day=5,
    )
    normal_lot = normal.lots[0]
    normal_lot.customer_delivery_day = 5
    normal_lot.production_due_day = 5
    normal_lot.material_reference_day = 5
    normal_lot.material_release_day = 0
    normal_lot.output_milestones = [
        {
            "op_id": normal_lot.op_id,
            "sku": normal_lot.sku,
            "qty": normal_lot.qty,
            "is_subcontracted": False,
            "customer_delivery_day": 5,
            "latest_subcontract_dispatch_day": None,
            "subcontract_dispatch_day": None,
            "production_due_day": 5,
            "internal_target_day": 5,
            "material_reference_day": 5,
            "material_reference_kind": "customer_delivery",
            "material_release_day": 0,
        }
    ]

    subcontracted = _run(
        "SUB",
        "M1",
        "TS",
        prod_min=1020,
        setup_min=0,
        internal_deadline=2,
        delivery_day=7,
    )
    sub_lot = subcontracted.lots[0]
    sub_lot.edd = 2
    sub_lot.original_edd = 7
    sub_lot.customer_delivery_day = 7
    sub_lot.latest_subcontract_dispatch_day = 6
    sub_lot.subcontract_dispatch_day = 2
    sub_lot.production_due_day = 2
    sub_lot.material_reference_day = 2
    sub_lot.material_release_day = 0
    sub_lot.is_subcontracted = True
    sub_lot.subcontract_lead_time_days = 1
    sub_lot.subcontract_buffer_days = 2
    sub_lot.output_milestones = [
        {
            "op_id": sub_lot.op_id,
            "sku": sub_lot.sku,
            "qty": sub_lot.qty,
            "is_subcontracted": True,
            "subcontract_lead_time_days": 1,
            "subcontract_buffer_days": 2,
            "customer_delivery_day": 7,
            "latest_subcontract_dispatch_day": 6,
            "subcontract_dispatch_day": 2,
            "production_due_day": 2,
            "internal_target_day": 2,
            "material_reference_day": 2,
            "material_reference_kind": "subcontract_dispatch",
            "material_release_day": 0,
        }
    ]
    subcontracted.edd = 2
    subcontracted.production_due_day = 2

    result = solve_global_jit(
        [subcontracted, normal],
        data,
        config,
        time_limit_s=2.0,
    )

    assert result is not None and result.candidate_found
    completion = {
        lot_id: max(
            segment.day_idx
            for segment in result.segments
            if segment.lot_id == lot_id and segment.prod_min > 0
        )
        for lot_id in {normal_lot.id, sub_lot.id}
    }
    assert completion[normal_lot.id] <= 5
    assert completion[sub_lot.id] <= 6
    score = compute_score(result.segments, result.lots, data, config=config)
    assert score["tardy_count"] == 0
    assert score["subcontract_dispatch_misses"] == 1


def test_released_urgent_run_precedes_later_released_work_across_tool_runs():
    data = _engine([], ["M1"], n_days=16)
    config = _config("M1")
    urgent = _run(
        "URGENT",
        "M1",
        "TU",
        prod_min=900,
        setup_min=30,
        internal_deadline=10,
        delivery_day=10,
    )
    later = _run(
        "LATER",
        "M1",
        "TL",
        prod_min=120,
        setup_min=30,
        internal_deadline=12,
        delivery_day=12,
    )
    urgent.lots[0].original_edd = 10
    later.lots[0].original_edd = 12

    result = solve_global_jit([later, urgent], data, config, time_limit_s=1.0)

    assert result is not None and result.candidate_found
    urgent_end = max(
        (segment.day_idx, segment.end_min)
        for segment in result.segments
        if segment.lot_id == "LOT-URGENT"
    )
    later_start = min(
        (segment.day_idx, segment.start_min)
        for segment in result.segments
        if segment.lot_id == "LOT-LATER"
    )
    assert urgent_end <= later_start


def test_large_run_set_has_enough_budget_for_a_complete_global_candidate():
    assert _effective_time_limit([_run(str(i), "M1", f"T{i}") for i in range(49)], 0.4) == 0.4
    assert _effective_time_limit([_run(str(i), "M1", f"T{i}") for i in range(50)], 0.4) == 8.0
    assert (
        round(
            _effective_time_limit([_run(str(i), "M1", f"T{i}") for i in range(200)], 0.4),
            3,
        )
        == 26.667
    )


def test_setup_opens_a_meaningful_production_tranche():
    data = _engine([], ["M1"], n_days=12)
    config = _config("M1")
    run = _run(
        "LONG",
        "M1",
        "T1",
        prod_min=700,
        setup_min=75,
        internal_deadline=8,
        delivery_day=8,
    )

    result = solve_global_jit([run], data, config, time_limit_s=1.0)

    assert result is not None and result.candidate_found
    opening = min(result.segments, key=lambda segment: (segment.day_idx, segment.start_min))
    production = min(
        (segment for segment in result.segments if segment.prod_min > 0),
        key=lambda segment: (segment.day_idx, segment.start_min),
    )
    assert opening.setup_min == 75
    assert opening.prod_min >= 75 or (
        opening.end_min == config.shift_b_end and production.day_idx == opening.day_idx + 1
    )


def test_setup_can_finish_exactly_at_shift_end_for_next_factory_minute():
    starts = _allowed_setup_starts(
        [0, 1],
        latest_abs=2000,
        setup=60,
        day_cap=1020,
        shift_durations=[510, 510],
        holidays=set(),
        minimum_productive_run=75,
    )

    assert any(lo <= 450 <= hi for lo, hi in starts)
    assert any(lo <= 960 <= hi for lo, hi in starts)


def test_detached_twin_setup_preserves_physical_setup_identity():
    lot = Lot(
        id="LOT-TWIN",
        op_id="OP-A+OP-B",
        sku="SKU-A",
        tool_id="BFP079",
        machine_id="PRM039",
        alt_machine_id=None,
        qty=100,
        prod_min=75,
        setup_min=60,
        edd=1,
        is_twin=True,
        twin_outputs=[("OP-A", "SKU-A", 100), ("OP-B", "SKU-B", 120)],
    )
    run = ToolRun(
        id="RUN-TWIN",
        tool_id="BFP079",
        machine_id="PRM039",
        alt_machine_id=None,
        lots=[lot],
        setup_min=60,
        total_prod_min=75,
        total_min=135,
        edd=1,
    )

    segments = materialise_fixed_run(
        run,
        "PRM039",
        450,
        [0, 1],
        _config("PRM039"),
    )

    setup = next(segment for segment in segments if segment.setup_min > 0)
    production = next(segment for segment in segments if segment.prod_min > 0)
    assert setup.twin_outputs == [("OP-A", "SKU-A", 0), ("OP-B", "SKU-B", 0)]
    assert segment_setup_identity(setup) == segment_setup_identity(production)


def test_inactive_prm042_master_data_does_not_create_capacity():
    op = _op(
        "OP-PRM043-6800016767A.10",
        "PRM043",
        "BFP125",
        sku="6800016767A.10",
    )
    data = _engine([op], ["PRM043"])
    config = _config("PRM043")
    # No committed real fixture in this repo contains the referenced line; this
    # synthetic row keeps the industrial machine/SKU pair and the inactive
    # PRM042 condition that regressed before.
    config.machines["PRM042"] = MachineConfig(
        id="PRM042",
        group="Medias",
        active=False,
    )

    result = solve_global_jit(
        [_run(op.id, "PRM043", "BFP125", sku="6800016767A.10")],
        data,
        config,
        time_limit_s=1.0,
    )

    assert result is not None and result.candidate_found
    assert {segment.machine_id for segment in result.segments} == {"PRM043"}
    assert "PRM042" not in {
        row["machine_id"] for row in compute_capacity(result.segments, data, config)["items"]
    }


def test_prm043_and_prm019_real_sku_regression_keeps_shared_setup_physical():
    ops = [
        _op(
            "OP-PRM043-6800016767A.10",
            "PRM043",
            "BFP125",
            sku="6800016767A.10",
        ),
        _op(
            "OP-PRM019-1092262X100",
            "PRM019",
            "BFP179",
            sku="1092262X100",
        ),
    ]
    data = _engine(ops, ["PRM043", "PRM019"], n_days=6)
    config = _config("PRM043", "PRM019")
    config.setup_crews_by_group["Grandes"] = 1
    runs = [
        _run(
            ops[0].id,
            "PRM043",
            "BFP125",
            sku="6800016767A.10",
            prod_min=120,
            setup_min=90,
            delivery_day=3,
            internal_deadline=3,
        ),
        _run(
            ops[1].id,
            "PRM019",
            "BFP179",
            sku="1092262X100",
            prod_min=120,
            setup_min=90,
            delivery_day=3,
            internal_deadline=3,
        ),
    ]

    result = solve_global_jit(runs, data, config, time_limit_s=2.0)

    assert result is not None and result.candidate_found
    assert {segment.sku for segment in result.segments} == {
        "6800016767A.10",
        "1092262X100",
    }
    setup_segments = [segment for segment in result.segments if segment.setup_min > 0]
    assert len(setup_segments) == 2
    first, second = sorted(setup_segments, key=lambda item: (item.day_idx, item.start_min))
    first_end = first.day_idx * 1020 + first.start_min + first.setup_min
    second_start = second.day_idx * 1020 + second.start_min
    assert second_start >= first_end


def test_material_release_is_never_relaxed_for_an_earlier_internal_deadline():
    op = _op("OP1", "M1", "T1")
    data = _engine([op], ["M1"])
    # The five-workday material-release floor for delivery D9 is D4, while the
    # internal deadline is D3. The internal checkpoint may be missed, but the
    # customer delivery remains feasible and material must not be manufactured
    # before it is available.
    run = _run(
        "OP1",
        "M1",
        "T1",
        internal_deadline=3,
        delivery_day=9,
    )
    result = solve_global_jit([run], data, _config("M1"), time_limit_s=1.0)

    assert result is not None and result.candidate_found
    productive = [segment for segment in result.segments if segment.prod_min > 0]
    assert productive
    assert min(segment.day_idx for segment in productive) == 4
    assert result.solver_status == "strict_feasible"


def test_strict_infeasibility_returns_a_complete_best_effort_candidate():
    ops = [_op("OP1", "M1", "T1"), _op("OP2", "M1", "T2")]
    data = _engine(ops, ["M1"], n_days=3)
    runs = [
        _run(
            "OP1",
            "M1",
            "T1",
            prod_min=1000,
            setup_min=0,
            internal_deadline=0,
            delivery_day=0,
        ),
        _run(
            "OP2",
            "M1",
            "T2",
            prod_min=1000,
            setup_min=0,
            internal_deadline=0,
            delivery_day=0,
        ),
    ]
    result = solve_global_jit(runs, data, _config("M1"), time_limit_s=2.0)

    assert result is not None and result.candidate_found
    assert result.solver_status == "strict_infeasible_best_effort"
    assert {lot.id for lot in result.lots} == {"LOT-OP1", "LOT-OP2"}
    assert sum(segment.qty for segment in result.segments) == 200


def test_jde002_best_effort_produces_large_day_zero_shortage_before_future_work():
    large_id = "TP042173-0040-2"
    future_id = "TP042173-0040-1"
    ops = [
        _op(large_id, "M1", "JDE002", sku=large_id, demand=[10_000, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
        _op("SMALL-D0-A", "M1", "JDE002", demand=[100, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
        _op("SMALL-D0-B", "M1", "JDE002", demand=[100, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
        _op(future_id, "M1", "JDE002", sku=future_id, demand=[0, 0, 0, 0, 0, 0, 0, 14_000, 0, 0]),
    ]
    for op, qty, minutes in zip(ops, [10000, 100, 100, 14000], [1000, 100, 100, 400], strict=True):
        op.pH, op.sH = qty * 60 / minutes, 0
    data = _engine(ops, ["M1"], n_days=10)
    config = _config("M1")
    large = _run(
        large_id,
        "M1",
        "JDE002",
        sku=large_id,
        qty=10_000,
        prod_min=1000,
        setup_min=0,
        internal_deadline=0,
        delivery_day=0,
    )
    small_a = _run(
        "SMALL-D0-A",
        "M1",
        "JDE002",
        qty=100,
        prod_min=100,
        setup_min=0,
        internal_deadline=0,
        delivery_day=0,
    )
    small_b = _run(
        "SMALL-D0-B",
        "M1",
        "JDE002",
        qty=100,
        prod_min=100,
        setup_min=0,
        internal_deadline=0,
        delivery_day=0,
    )
    future = _run(
        future_id,
        "M1",
        "JDE002",
        sku=future_id,
        qty=14_000,
        prod_min=400,
        setup_min=0,
        internal_deadline=7,
        delivery_day=7,
    )

    result = solve_global_jit(
        [small_a, future, small_b, large],
        data,
        config,
        time_limit_s=3.0,
    )

    assert result is not None and result.candidate_found
    assert result.solver_status == "strict_infeasible_best_effort"
    starts = {
        lot_id: min(
            (segment.day_idx, segment.start_min)
            for segment in result.segments
            if segment.lot_id == f"LOT-{lot_id}"
        )
        for lot_id in [large_id, future_id]
    }
    assert starts[large_id] < starts[future_id]

    score = compute_score(result.segments, result.lots, data, config=config)
    old_segments, old_lots, _warnings = per_machine_dispatch(
        {"M1": [small_a, small_b, large, future]},
        data,
        config=config,
    )
    old_score = compute_score(old_segments, old_lots, data, config=config)

    assert score["otd_d_cumulative_shortfall_qty"] <= old_score["otd_d_cumulative_shortfall_qty"]
    assert score["tardy_count"] <= old_score["tardy_count"]
    assert_plan_valid(result.segments, data, config)
    assert score["hard_violations"] == 0
    assert score["machine_overlaps"] == 0
    assert score["tool_conflicts"] == 0
    assert score["missing_lots"] == 0
    assert score["missing_qty"] == 0
    assert score["overproduced_qty"] == 0
    gate_report = build_gate_report(
        result.segments,
        result.lots,
        score,
        data,
        config,
    )
    assert gate_report["physical_gate_passed"] is True
    assert gate_report["delivery_gate_passed"] is False


def test_no_global_candidate_falls_back_without_losing_quantity(monkeypatch):
    op = _op("OP1", "M1", "T1", demand=[0, 100, 0, 0])
    data = _engine([op], ["M1"], n_days=4)

    def no_candidate(*_args, **_kwargs):
        return GlobalJITResult(
            segments=[],
            lots=[],
            machine_runs={},
            run_gates={},
            solver_status="no_candidate",
            feasibility={"binding_constraints": []},
            warnings=["timeout"],
            candidate_found=False,
        )

    monkeypatch.setattr("backend.scheduler.jit.solve_global_jit", no_candidate)
    result = schedule_all(data, config=_config("M1"))

    assert result.score["missing_lots"] == 0
    assert result.score["missing_qty"] == 0
    assert sum(segment.qty for segment in result.segments) == 100
    assert result.solver_status == "no_candidate"


def test_global_jit_never_resurrects_negative_auto_buffer_days():
    op = _op("OP1", "M1", "T1", demand=[100, 0, 0, 0])
    data = _engine([op], ["M1"], n_days=4)
    config = _config("M1")
    config.auto_buffer = True
    config.global_jit_enabled = True

    result = schedule_all(data, config=config)

    assert result.score["buffer_days"] == 0
    assert result.segments
    assert min(segment.day_idx for segment in result.segments) >= 0


def test_global_solver_respects_one_shared_time_budget():
    ops = [_op(f"OP{index}", "M1", f"T{index}") for index in range(8)]
    data = _engine(ops, ["M1"], n_days=5)
    runs = [
        _run(
            op.id,
            "M1",
            op.t,
            prod_min=500,
            internal_deadline=1,
            delivery_day=1,
        )
        for op in ops
    ]

    started = time.monotonic()
    result = solve_global_jit(runs, data, _config("M1"), time_limit_s=0.05)
    elapsed = time.monotonic() - started

    assert result is not None
    # Includes Python model construction; the solver phases and diagnostic
    # lower-bound searches themselves share the configured 50 ms deadline.
    assert elapsed < 0.30
