"""Canonical resource capacity and order-specific diagnostics."""

from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.risk import compute_risk
from backend.transform.calendars import apply_calendars
from tests.test_risk import _engine, _seg
from tests.test_console import _engine as console_engine, _eop
from backend.scheduler.types import Lot, Segment


def two_orders():
    data = console_engine(ops=[_eop(d=[0, 100, 0, 0, 0, 0, 0, 200, 0, 0])])
    lots = [Lot("early", data.ops[0].id, "T1", "M1", None, 100, 60, 30, 1, False, sku="SKU1"),
            Lot("later", data.ops[0].id, "T1", "M1", None, 200, 120, 30, 7, False, sku="SKU1")]
    segments = [Segment(lot.id, lot.id, "M1", "T1", day, 420, 450 + lot.prod_min, "A", lot.qty, lot.prod_min, setup_min=30, sku="SKU1") for lot, day in zip(lots, (3, 9))]
    return data, lots, segments


def test_eta_is_for_the_order_not_the_last_production_for_the_sku():
    from backend.analytics.expedition import compute_expedition
    from backend.console.expedition_today import _estimate_eta
    from backend.console.action_items import _diagnose_why_short

    data, lots, segments = two_orders()
    order = compute_expedition(segments, lots, data).days[0].entries[0]
    assert _estimate_eta(order, segments, lots, data) == data.workdays[3]
    assert "2 dias" in _diagnose_why_short(order, segments, lots, data)


def test_expedition_risk_window_moves_and_retires_fulfilled_backlog():
    from backend.analytics.expedition import compute_expedition

    data, lots, segments = two_orders()
    assert compute_expedition(segments, lots, data, start_day=0).at_risk_count == 1
    assert compute_expedition(segments, lots, data, start_day=2).at_risk_count == 1
    assert compute_expedition(segments, lots, data, start_day=5).at_risk_count == 1
    assert compute_expedition(segments, lots, data, start_day=9).at_risk_count == 0
    assert compute_expedition([], lots, data, start_day=9).at_risk_count == 2


def test_workforce_window_starts_at_selected_day():
    from backend.analytics.workforce_forecast import forecast_workforce

    data, _, segments = two_orders()
    forecast = forecast_workforce(segments, data, FactoryConfig(), window=2, start_day=7)
    assert {day.day_idx for day in forecast.daily} == {7, 8}
    assert forecast.peak_day >= 7


def test_tracking_allocates_actual_chronological_production_not_lot_deadlines():
    from backend.analytics.order_tracking import compute_order_tracking, compute_order_readiness

    data, lots, segments = two_orders()
    segments[0].day_idx = 9
    segments[1].day_idx = 2
    tracked = compute_order_tracking(segments, lots, data)[0].orders
    readiness = compute_order_readiness(segments, lots, data)["SKU1"]
    assert tracked[0].lot_ids == ["later"]
    assert tracked[0].ready_day == readiness[0].ready_day == 2
    assert tracked[1].ready_day == readiness[1].ready_day == 9


def test_tracking_does_not_wait_for_unused_tail_of_a_lot():
    from backend.analytics.order_tracking import compute_order_tracking

    data, lots, segments = two_orders()
    lots[0].qty = 300
    segments[1].lot_id = lots[0].id
    tracked = compute_order_tracking(segments, lots[:1], data)[0].orders
    assert tracked[0].ready_day == 3
    assert tracked[0].production_days == [3]
    assert tracked[1].ready_day == 9
    assert tracked[1].surplus_used == 200


def test_tracking_never_promises_an_unscheduled_lot():
    from backend.analytics.order_tracking import compute_order_tracking

    data, lots, _ = two_orders()
    assert all(order.ready_day is None and order.shortfall_qty == order.order_qty
               for order in compute_order_tracking([], lots, data)[0].orders)


def test_console_window_retains_only_unfulfilled_backlog():
    from backend.console.action_items import compute_action_items

    data, lots, segments = two_orders()
    actions = compute_action_items(segments, lots, data, FactoryConfig(), day_idx=5)
    delivery = [a for a in actions if a.category == "delivery"]
    assert delivery
    assert data.workdays[7] in delivery[0].body
    assert data.workdays[1] not in delivery[0].body


def test_loaded_work_on_closed_machine_is_critical_not_zero_utilization():
    data = _engine()
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes", active=False)})
    risk = compute_risk([_seg(day=0)], [], data, config=config)
    cell = next(c for c in risk.heatmap if c.machine_id == "M1" and c.day_idx == 0)
    assert cell.load_min > 0 and cell.capacity_min == 0
    assert cell.utilization is None
    assert cell.risk_level == "critical"
    assert risk.machine_risks[0].peak_utilization is None


def test_extra_saturday_uses_effective_capacity_in_state_analytics():
    from backend.copilot.state import CopilotState

    data = _engine()
    config = FactoryConfig(
        shifts=[ShiftConfig("A", 420, 900, "A")],
        extra_workdays=[data.workdays[2]],
        machines={"M1": MachineConfig("M1", "Grandes")},
    )
    apply_calendars(data, config)
    live = CopilotState(engine_data=data, config=config, segments=[_seg(day=2, prod_min=240, setup_min=0)])
    live._refresh_analytics()
    cell = next(c for c in live.risk_result.heatmap if c.day_idx == 2)
    assert cell.capacity_min == 480
    assert cell.utilization == 0.5
