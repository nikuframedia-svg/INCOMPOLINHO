"""Segment destinations are the same allocations exposed by order tracking."""
import copy

from backend.analytics.order_tracking import compute_order_tracking, compute_segment_deliveries
from backend.types import ClientDemandEntry
from tests.test_risk import _engine, _eop, _lot, _seg


def demand(sku, day, qty, client="C"):
    return ClientDemandEntry(client, sku, day, f"2026-03-{5 + day:02d}", qty, -qty)


def test_later_continuation_does_not_inherit_satisfied_deadline():
    data = _engine()
    data.client_demands = {"SKU1": [demand("SKU1", 0, 100), demand("SKU1", 4, 250)]}
    segments = [_seg(day=0, qty=200), _seg(day=3, qty=300)]
    before = copy.deepcopy((segments, data))
    trace = compute_segment_deliveries(segments, [_lot(edd=0)], data)
    assert [x["delivery_day"] for x in trace[1]["delivery_allocations"]] == [4]
    assert trace[1]["delivery_allocations"][0]["qty"] == 150
    assert trace[1]["unallocated_output"] == [{"sku": "SKU1", "qty": 150}]
    assert (segments, data) == before


def test_segment_quantity_is_conserved_for_each_twin_output():
    data = _engine([_eop(), _eop(op_id="T1_M1_SKU2", sku="SKU2")])
    data.client_demands = {"SKU1": [demand("SKU1", 0, 100), demand("SKU1", 1, 100)],
                           "SKU2": [demand("SKU2", 1, 450)]}
    lot = _lot()
    lot.twin_outputs = [("T1_M1_SKU1", "SKU1", 500), ("T1_M1_SKU2", "SKU2", 500)]
    segments = [_seg(day=0, qty=200), _seg(day=1, qty=300)]
    for segment in segments:
        segment.twin_outputs = [(op, sku, segment.qty) for op, sku, _ in lot.twin_outputs]
    traces = compute_segment_deliveries(segments, [lot], data)
    for segment, trace in zip(segments, traces):
        for sku in ("SKU1", "SKU2"):
            assert sum(x["qty"] for x in trace["delivery_allocations"] + trace["unallocated_output"]
                       if x["sku"] == sku) == segment.qty
    assert traces[1]["delivery_allocations"] == [{
        "sku": "SKU2", "client": "C", "delivery_day": 1, "delivery_date": "2026-03-06",
        "qty": 250, "customer_ready_day": 1,
    }]


def test_actual_completion_time_beats_lot_id_and_input_order():
    data = _engine()
    data.client_demands = {"SKU1": [demand("SKU1", 0, 100)]}
    early = _seg(lot_id="Z", end=500, qty=100)
    late = _seg(lot_id="A", start=600, end=700, qty=100)
    lots = [_lot(lot_id="Z"), _lot(lot_id="A")]
    for segments in ([late, early], [early, late]):
        traces = compute_segment_deliveries(segments, lots, data)
        assigned = [s.lot_id for s, t in zip(segments, traces) if t["delivery_allocations"]]
        assert assigned == ["Z"]
        assert compute_order_tracking(segments, lots, data)[0].orders[0].lot_ids == ["Z"]


def test_repeated_orders_are_not_deduplicated():
    data = _engine()
    data.client_demands = {"SKU1": [demand("SKU1", 0, 100), demand("SKU1", 0, 100)]}
    trace = compute_segment_deliveries([_seg(qty=250)], [_lot()], data)[0]
    assert len(trace["delivery_allocations"]) == 2
    assert trace["unallocated_output"] == [{"sku": "SKU1", "qty": 50}]


def test_net_demand_does_not_deduct_stock_twice():
    data = _engine()
    data.ops[0].stk = 100
    data.client_demands = {"SKU1": [demand("SKU1", 0, 100)]}
    trace = compute_segment_deliveries([_seg(qty=200)], [_lot()], data)[0]
    assert trace["delivery_allocations"][0]["qty"] == 100


def test_subcontracted_parts_count_on_the_day_they_are_made():
    data = _engine()
    data.client_demands = {"SKU1": [demand("SKU1", 1, 100)]}
    lot = _lot()
    lot.sku = "SKU1"
    lot.is_subcontracted = True
    lot.subcontract_lead_time_days = 1
    trace = compute_segment_deliveries([_seg(day=0, qty=200)], [lot], data)[0]
    # Stock rule (14/10/2026): no return trip is added.
    assert trace["delivery_allocations"][0]["customer_ready_day"] == 0


def test_unavailable_order_detail_is_not_claimed_as_stock():
    data = _engine()
    trace = compute_segment_deliveries([_seg()], [_lot()], data)[0]
    assert trace["delivery_allocations"] is None
    assert trace["unallocated_output"] is None


def test_other_sku_orders_do_not_hide_missing_detail():
    data = _engine()
    data.client_demands = {"OTHER": [demand("OTHER", 0, 100)]}
    trace = compute_segment_deliveries([_seg()], [_lot()], data)[0]
    assert trace["delivery_allocations"] is None


def test_explicit_stock_credit_is_not_assigned_to_production():
    data = _engine()
    data.ops[0].stk = 100
    entry = demand("SKU1", 0, 200)
    entry.np_value = -100
    data.client_demands = {"SKU1": [entry]}
    trace = compute_segment_deliveries([_seg(qty=200)], [_lot()], data)[0]
    assert trace["delivery_allocations"][0]["qty"] == 100
    assert trace["unallocated_output"] == [{"sku": "SKU1", "qty": 100}]
