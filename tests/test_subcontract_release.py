"""Acceptance tests for subcontract-aware material and delivery milestones."""

from __future__ import annotations

from datetime import date, timedelta

from backend.analytics import compute_ctp, compute_expedition, compute_order_tracking
from backend.config.planning import apply_effective_planning_config
from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.gates import build_gate_report
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.scoring import compute_score
from backend.analytics.stock_projection import build_production_by_op
from backend.scheduler.tool_grouping import create_tool_runs
from backend.scheduler.types import Lot, Segment
from backend.scheduler.window import compute_window_gates
from backend.types import ClientDemandEntry, EOp, EngineData, MachineInfo, TwinGroup


def _op(*, sku: str = "SUB", delivery_day: int = 14) -> EOp:
    demand = [0] * 20
    demand[delivery_day] = 100
    return EOp(
        id=f"T1_M1_{sku}",
        sku=sku,
        client="CLIENTE",
        designation="Peça",
        m="M1",
        t="T1",
        pH=100,
        sH=0,
        operators=1,
        eco_lot=0,
        alt=None,
        stk=0,
        backlog=0,
        d=demand,
        oee=1.0,
        wip=0,
    )


def _config(*, subcontracted: bool = True, finish_buffer: int = 0) -> FactoryConfig:
    config = FactoryConfig(
        machines={"M1": MachineConfig(id="M1", group="Grandes")},
        sku_planning_rules={"SUB": {"finish_buffer_days": finish_buffer}},
    )
    if subcontracted:
        config.subcontract_companies = [
            {
                "id": "SUPPLIER",
                "name": "Supplier",
                "lead_time_workdays": 5,
            }
        ]
        config.sku_subcontracts = {
            "SUB": {
                "enabled": True,
                "company_id": "SUPPLIER",
                "lead_time_workdays": 5,
                "buffer_days": 0,
            }
        }
    return config


def _engine(op: EOp, *, with_client_demand: bool = False) -> EngineData:
    first = date(2026, 9, 7)  # Monday
    workdays = [(first + timedelta(days=offset)).isoformat() for offset in range(20)]
    holidays = [
        offset
        for offset in range(20)
        if (first + timedelta(days=offset)).weekday() >= 5
    ]
    client_demands = {}
    if with_client_demand:
        delivery_day = next(day for day, qty in enumerate(op.d) if qty > 0)
        client_demands = {
            op.sku: [
                ClientDemandEntry(
                    client=op.client,
                    sku=op.sku,
                    order_qty=100,
                    day_idx=delivery_day,
                    date=workdays[delivery_day],
                    np_value=-100,
                )
            ]
        }
    return EngineData(
        ops=[op],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[],
        client_demands=client_demands,
        workdays=workdays,
        n_days=len(workdays),
        holidays=holidays,
    )


def _twin_engine(first_op: EOp, second_op: EOp) -> EngineData:
    data = _engine(first_op)
    data.ops = [first_op, second_op]
    data.twin_groups = [
        TwinGroup(
            tool_id="T1",
            machine_id="M1",
            op_id_1=first_op.id,
            op_id_2=second_op.id,
            sku_1=first_op.sku,
            sku_2=second_op.sku,
            eco_lot_1=0,
            eco_lot_2=0,
        )
    ]
    return data


def _segment(lot: Lot, completion_day: int) -> Segment:
    return Segment(
        lot_id=lot.id,
        run_id="RUN-1",
        machine_id=lot.machine_id,
        tool_id=lot.tool_id,
        day_idx=completion_day,
        start_min=420,
        end_min=480,
        shift="A",
        qty=lot.qty,
        prod_min=60,
        setup_min=0,
        edd=lot.edd,
        sku=lot.sku,
        lot_qty=lot.qty,
        customer_delivery_day=lot.customer_delivery_day,
        subcontract_dispatch_day=lot.subcontract_dispatch_day,
        production_due_day=lot.production_due_day,
        material_reference_day=lot.material_reference_day,
        material_reference_kind=lot.material_reference_kind,
        material_release_day=lot.material_release_day,
        output_milestones=lot.output_milestones,
        twin_outputs=lot.twin_outputs,
        is_subcontracted=lot.is_subcontracted,
        subcontract_company_id=lot.subcontract_company_id,
        subcontract_lead_time_days=lot.subcontract_lead_time_days,
    )


def test_subcontract_release_is_anchored_to_dispatch_not_customer_delivery() -> None:
    op = _op(delivery_day=14)
    data = _engine(op)
    config = _config(finish_buffer=2)
    apply_effective_planning_config(data, config)

    lot = create_lots(data, config)[0]

    assert lot.customer_delivery_day == 14
    assert lot.latest_subcontract_dispatch_day == 7
    assert lot.subcontract_dispatch_day == 7
    assert lot.production_due_day == 7
    assert lot.internal_target_day == 3
    assert lot.material_reference_day == 7
    assert lot.material_reference_kind == "subcontract_dispatch"
    assert lot.material_release_day == 0
    assert lot.edd == lot.production_due_day


def test_near_horizon_subcontract_milestones_remain_negative() -> None:
    op = _op(delivery_day=7)
    data = _engine(op)
    config = _config()
    apply_effective_planning_config(data, config)

    lot = create_lots(data, config)[0]

    assert lot.subcontract_dispatch_day == 0
    assert lot.material_release_day == -7


def test_subcontract_buffer_moves_planned_dispatch_and_material_reference() -> None:
    op = _op(delivery_day=14)
    data = _engine(op)
    config = _config()
    config.sku_subcontracts["SUB"]["buffer_days"] = 2
    apply_effective_planning_config(data, config)

    lot = create_lots(data, config)[0]

    assert lot.latest_subcontract_dispatch_day == 7
    assert lot.subcontract_dispatch_day == 3
    assert lot.production_due_day == 3
    assert lot.material_reference_day == 3
    assert lot.material_release_day == -4


def test_normal_sku_keeps_customer_delivery_as_material_reference() -> None:
    op = _op(delivery_day=14)
    data = _engine(op)
    config = _config(subcontracted=False, finish_buffer=2)
    apply_effective_planning_config(data, config)

    lot = create_lots(data, config)[0]

    assert lot.customer_delivery_day == 14
    assert lot.production_due_day == 14
    assert lot.internal_target_day == 10
    assert lot.material_reference_day == 14
    assert lot.material_release_day == 7
    assert lot.subcontract_dispatch_day is None


def test_score_and_gate_distinguish_dispatch_from_customer_delivery() -> None:
    op = _op(delivery_day=14)
    data = _engine(op)
    config = _config()
    apply_effective_planning_config(data, config)
    lot = create_lots(data, config)[0]

    on_time_score = compute_score(
        [_segment(lot, 7)],
        [lot],
        data,
        config,
        include_operational_audit=False,
    )
    assert on_time_score["subcontract_dispatch_misses"] == 0
    assert on_time_score["tardy_count"] == 0
    assert on_time_score["otd"] == 100.0

    late_segments = [_segment(lot, 8)]
    late_score = compute_score(
        late_segments,
        [lot],
        data,
        config,
        include_operational_audit=False,
    )
    assert late_score["subcontract_dispatch_misses"] == 1
    assert late_score["subcontract_dispatch_late_workdays"] == 1
    assert late_score["tardy_count"] == 1

    gate = build_gate_report(late_segments, [lot], late_score, data, config)
    assert gate["subcontract_dispatch_gate_passed"] is False
    assert "subcontract_dispatch_risk" in gate["approval_reasons"]
    assert gate["subcontract_dispatch_detail"][0]["subcontract_dispatch_day"] == 7


def test_ctp_uses_release_to_dispatch_production_window() -> None:
    op = _op(delivery_day=14)
    data = _engine(op)
    config = _config()
    apply_effective_planning_config(data, config)

    result = compute_ctp("SUB", 100, 14, [], data, config)

    assert result.feasible is True
    assert result.material_release_day == 0
    assert result.material_reference_day == 7
    assert result.latest_day == 7
    assert result.latest_subcontract_dispatch_day == 7
    assert result.production_due_day == 7
    assert result.subcontract_dispatch_day == 7
    assert result.internal_target_day == 7
    assert result.customer_delivery_day == 14


def test_ctp_exposes_latest_and_planned_dispatch_when_buffered() -> None:
    op = _op(delivery_day=14)
    data = _engine(op)
    config = _config()
    config.sku_subcontracts["SUB"]["buffer_days"] = 2
    apply_effective_planning_config(data, config)

    result = compute_ctp("SUB", 100, 14, [], data, config)

    assert result.latest_subcontract_dispatch_day == 7
    assert result.subcontract_dispatch_day == 3
    assert result.production_due_day == 3
    assert result.material_reference_day == 3
    assert result.material_release_day == -4


def test_scheduler_finishes_subcontract_output_by_dispatch() -> None:
    op = _op(delivery_day=14)
    data = _engine(op)
    config = _config()

    result = schedule_all(data, config=config)
    lot = result.lots[0]
    productive = [
        segment
        for segment in result.segments
        if segment.lot_id == lot.id and segment.prod_min > 0
    ]

    assert productive
    assert min(segment.day_idx for segment in productive) >= lot.material_release_day
    assert max(segment.day_idx for segment in productive) <= lot.subcontract_dispatch_day


def test_legacy_backward_gate_also_uses_subcontract_dispatch_due() -> None:
    op = _op(delivery_day=14)
    data = _engine(op)
    config = _config()
    apply_effective_planning_config(data, config)
    lot = create_lots(data, config)[0]
    run = create_tool_runs([lot], config=config)[0]

    gates, _floors = compute_window_gates(
        {"M1": [run]},
        set(data.holidays),
        config,
        n_days=data.n_days,
    )

    latest_start = (lot.production_due_day + 1) * config.day_capacity_min - run.total_min
    assert gates[run.id] <= latest_start


def test_normal_twin_uses_urgent_outputs_shared_material_release() -> None:
    later = _op(sku="LATER", delivery_day=10)
    urgent = _op(sku="URGENT", delivery_day=7)
    data = _twin_engine(later, urgent)
    config = _config()
    apply_effective_planning_config(data, config)

    lot = create_lots(data, config)[0]
    milestones = {item["sku"]: item for item in lot.output_milestones or []}

    assert milestones["LATER"]["material_release_day"] == 3
    assert milestones["LATER"]["production_due_day"] == 10
    assert milestones["URGENT"]["material_release_day"] == 0
    assert milestones["URGENT"]["production_due_day"] == 7
    assert lot.material_reference_day == 7
    assert lot.material_release_day == 0
    assert lot.production_due_day == 7

    result = schedule_all(data, config=config)
    productive = [
        segment
        for segment in result.segments
        if segment.lot_id == lot.id and segment.prod_min > 0
    ]
    assert min(segment.day_idx for segment in productive) == 0


def test_mixed_twin_uses_earliest_shared_material_release() -> None:
    subcontracted = _op(sku="SUB", delivery_day=14)
    normal = _op(sku="NORMAL", delivery_day=14)
    data = _twin_engine(subcontracted, normal)
    config = _config()
    apply_effective_planning_config(data, config)

    lots = create_lots(data, config)

    assert len(lots) == 1
    lot = lots[0]
    milestones = {item["sku"]: item for item in lot.output_milestones or []}
    assert milestones["SUB"]["material_release_day"] == 0
    assert milestones["SUB"]["production_due_day"] == 7
    assert milestones["NORMAL"]["material_release_day"] == 7
    assert milestones["NORMAL"]["production_due_day"] == 14
    assert lot.material_reference_kind == "mixed"
    assert lot.material_reference_day == 7
    assert lot.material_release_day == 0
    assert lot.production_due_day == 7


def test_twin_demands_without_isolated_window_overlap_still_pair() -> None:
    subcontracted = _op(sku="SUB", delivery_day=7)
    normal = _op(sku="NORMAL", delivery_day=8)
    data = _twin_engine(subcontracted, normal)
    config = _config()
    apply_effective_planning_config(data, config)

    lots = create_lots(data, config)

    assert len(lots) == 1
    lot = lots[0]
    assert lot.planning_source == "twin_joint"
    assert lot.twin_outputs == [
        (subcontracted.id, "SUB", 100),
        (normal.id, "NORMAL", 100),
    ]
    milestones = {item["sku"]: item for item in lot.output_milestones or []}
    assert milestones["SUB"].get("is_coproduced_surplus") is not True
    assert milestones["NORMAL"].get("is_coproduced_surplus") is not True
    assert (lot.material_release_day, lot.production_due_day) == (-7, 0)


def test_synthetic_subcontract_twin_output_is_stock_not_fake_dispatch() -> None:
    normal = _op(sku="NORMAL", delivery_day=1)
    subcontracted = _op(sku="SUB", delivery_day=14)
    data = _twin_engine(normal, subcontracted)
    config = _config()
    apply_effective_planning_config(data, config)

    lot = create_lots(data, config)[0]
    segment = _segment(lot, 1)
    milestones = {item["sku"]: item for item in lot.output_milestones or []}

    assert milestones["SUB"]["is_coproduced_surplus"] is True
    score = compute_score([segment], [lot], data, config)
    assert score["subcontract_dispatch_total"] == 0
    assert score["subcontract_dispatch_misses"] == 0

    production = build_production_by_op([segment], [lot], data)
    assert production[subcontracted.id].get(1, 0) == 0
    assert sum(production[subcontracted.id].values()) == 100


def test_expedition_and_order_tracking_wait_for_external_lead() -> None:
    op = _op(delivery_day=14)
    data = _engine(op, with_client_demand=True)
    config = _config()
    apply_effective_planning_config(data, config)
    lot = create_lots(data, config)[0]
    segments = [_segment(lot, 8)]

    tracking = compute_order_tracking(segments, [lot], data)[0].orders[0]
    assert tracking.factory_ready_day == 8
    assert tracking.customer_ready_day == 15
    assert tracking.status == "at_subcontractor"

    expedition = compute_expedition(segments, [lot], data)
    entry = expedition.days[0].entries[0]
    assert entry.factory_produced_qty == 100
    assert entry.produced_qty == 0
    assert entry.status == "at_subcontractor"
    assert expedition.days[0].total_at_subcontractor == 1
