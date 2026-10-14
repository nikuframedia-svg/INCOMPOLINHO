"""Delivery risk follows allocated customer quantities, not economic lot tails."""

from backend.risk.slack_analytics import compute_lot_risks, select_top_risks
from backend.types import ClientDemandEntry
from tests.test_risk import _engine, _eop, _lot, _seg


def demand(sku, day, qty):
    return ClientDemandEntry("CLIENT", sku, day, "2026-03-05", qty, -qty)


def test_economic_tail_after_due_does_not_make_delivery_late():
    data = _engine()
    data.client_demands = {"SKU1": [demand("SKU1", 0, 100)]}
    risks = compute_lot_risks(
        [_seg(day=0, qty=200), _seg(day=1, qty=300)], [_lot(edd=0)], data,
    )
    assert risks[0].status == "at_limit"
    assert risks[0].completion_day == 0
    assert select_top_risks(risks, 1) == []


def test_real_shortfall_is_still_late():
    data = _engine()
    data.client_demands = {"SKU1": [demand("SKU1", 0, 400)]}
    risk = compute_lot_risks(
        [_seg(day=0, qty=200), _seg(day=1, qty=300)], [_lot(edd=0)], data,
    )[0]
    assert risk.status == "late"
    assert risk.slack_days == -1


def test_future_order_uses_surplus_without_inheriting_first_due_day():
    data = _engine()
    data.client_demands = {"SKU1": [demand("SKU1", 0, 100), demand("SKU1", 4, 300)]}
    risks = compute_lot_risks(
        [_seg(day=0, qty=200), _seg(day=1, qty=300)], [_lot(edd=0)], data,
    )
    assert risks[0].status != "late"


def test_twin_reports_the_output_whose_customer_is_late():
    data = _engine([_eop(), _eop(op_id="T1_M1_SKU2", sku="SKU2")])
    data.client_demands = {"SKU1": [demand("SKU1", 0, 100)],
                           "SKU2": [demand("SKU2", 0, 400)]}
    lot = _lot(edd=0)
    lot.is_twin = True
    lot.twin_outputs = [("T1_M1_SKU1", "SKU1", 500), ("T1_M1_SKU2", "SKU2", 500)]
    segments = [_seg(day=0, qty=200), _seg(day=1, qty=300)]
    for segment in segments:
        segment.twin_outputs = [(op, sku, segment.qty) for op, sku, _ in lot.twin_outputs]
    risk = compute_lot_risks(segments, [lot], data)[0]
    assert risk.sku == "SKU2"
    assert risk.status == "late"


def test_missing_quantity_is_not_reported_as_covered():
    data = _engine()
    data.client_demands = {"SKU1": [demand("SKU1", 0, 500)]}
    risk = compute_lot_risks([_seg(day=0, qty=200)], [_lot(edd=0)], data)[0]
    assert risk.status == "late"


def test_uncommitted_surplus_has_no_delivery_warning():
    data = _engine()
    data.client_demands = {"SKU1": [demand("SKU1", 0, 100)]}
    risks = compute_lot_risks(
        [_seg(day=0, qty=500), _seg(lot_id="L2", day=1, qty=500)],
        [_lot(edd=0), _lot(lot_id="L2", edd=0)], data,
    )
    assert [risk.lot_id for risk in risks] == ["L1"]


def test_subcontracted_delivery_is_judged_on_the_stock():
    """Luís, 14/10/2026: the subcontract lead is not added; a subcontracted
    delivery is late only when its pieces are not made by its day."""
    data = _engine()
    data.client_demands = {"SKU1": [demand("SKU1", 0, 100)]}
    lot = _lot(edd=0)
    lot.sku = "SKU1"
    lot.is_subcontracted = True
    lot.subcontract_lead_time_days = 1
    risk = compute_lot_risks([_seg(day=0, qty=500)], [lot], data)[0]
    assert risk.status != "late"
    assert risk.completion_day == 0
    late = compute_lot_risks([_seg(day=1, qty=500)], [lot], data)[0]
    assert late.status == "late"


def test_short_slack_uses_required_quantity_not_tail():
    data = _engine()
    data.client_demands = {"SKU1": [demand("SKU1", 2, 100)]}
    risk = compute_lot_risks(
        [_seg(day=0, qty=200), _seg(day=3, qty=300)], [_lot(edd=2)], data,
    )[0]
    assert risk.status == "short_slack"
    assert risk.slack_days == 2
