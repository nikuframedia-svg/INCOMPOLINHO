"""Subcontracted deliveries are judged on the stock shown on Entregas.

Luís, 14/10/2026: a subcontracted delivery is late only when pieces are
missing in the stock of the Entregas screen (every piece on the day it is
made), the same rule as for any reference, in the whole system: late orders,
OTD/OTD-D, the gate's approval reasons, the Hoje risks and actions, the
late-delivery report and the idle-capacity notice. The planner still aims to
finish the production five working days before the delivery (the subcontract
dispatch, ``production_due_day``); missing it is never shown as lateness.

Real case: CF589MMA1A02.20, 829 pieces for 16/10 made on 13/10, was «1 de
640 encomendas atrasada» with an approval reason and a Hoje action.
"""

from __future__ import annotations

import copy

from backend.analytics.late_delivery import analyze_late_deliveries
from backend.analytics.order_tracking import compute_order_tracking
from backend.analytics.stock_projection import compute_stock_projections
from backend.console.action_items import compute_action_items
from backend.risk.slack_analytics import compute_lot_risks
from backend.scheduler.gates import build_gate_report
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.scoring import compute_score
from tests.oracle_delivery import oracle_first_rupture, oracle_orders
from tests.test_delivery_views_agree import CONFIG, _data, _entry, _segments

# START is Friday 09/10/2026: day 4 = Tue 13/10, day 7 = Fri 16/10.
MADE, DUE = 4, 7


def _cf589(made_day: int):
    data = _data(subcontracted=True, eco_lot=1000, entries=[_entry("HANON", DUE, 829)])
    (lot,) = create_lots(data)
    assert lot.is_subcontracted and lot.production_due_day < made_day
    segments = _segments(lot, [(made_day, 420, 1000, 1000)])
    return segments, [lot], data


def _views(segments, lots, data, today: int):
    score = compute_score(segments, lots, data, CONFIG)
    return {
        "score": score,
        "gate": build_gate_report(segments, lots, score, data, CONFIG),
        "orders": [o for c in compute_order_tracking(segments, lots, data) for o in c.orders],
        "stock": compute_stock_projections(segments, lots, data),
        "late": analyze_late_deliveries(segments, lots, data, CONFIG),
        "risks": compute_lot_risks(segments, lots, data, CONFIG),
        "actions": compute_action_items(segments, lots, data, CONFIG, day_idx=today),
    }


def test_cf589_made_three_days_before_its_delivery_is_on_time_everywhere():
    segments, lots, data = _cf589(MADE)
    assert not any(o.late for o in oracle_orders(segments, lots, data))
    views = _views(segments, lots, data, today=MADE + 1)
    score, gate = views["score"], views["gate"]

    # «Encomendas a tempo 1 de 1», OTD and OTD-D.
    assert gate["metrics"]["orders_late"] == 0
    assert gate["metrics"]["orders_total"] == 1
    assert gate["late_order_detail"] == []
    assert score["tardy_count"] == 0 and score["otd"] == 100.0 and score["otd_d"] == 100.0
    # No approval for it, and no list of late subcontract dispatches.
    assert not {"delivery_risk", "subcontract_dispatch_risk"} & set(gate["approval_reasons"])
    assert "subcontract_dispatch_detail" not in gate
    assert gate["idle_capacity_late"] == []
    # Entregas, late report, risks and Hoje agree.
    (order,) = views["orders"]
    assert (order.status, order.customer_ready_day) == ("ready", MADE)
    assert all(p.stockout_day is None for p in views["stock"])
    assert views["late"].analyses == []
    assert all(r.status != "late" for r in views["risks"])
    assert not [a for a in views["actions"] if a.category == "delivery"]
    assert not any("turno noite" in " ".join(a.actions).lower() for a in views["actions"])
    # The planner's aim (finish five working days before) is still measured.
    assert score["subcontract_dispatch_misses"] == 1


def test_a_real_stock_shortfall_is_still_late_everywhere():
    segments, lots, data = _cf589(DUE + 1)
    (late,) = [o for o in oracle_orders(segments, lots, data) if o.late]
    assert (late.due_day, late.ready_day) == (DUE, DUE + 1)
    views = _views(segments, lots, data, today=DUE - 1)
    gate = views["gate"]
    assert gate["metrics"]["orders_late"] == 1
    assert "delivery_risk" in gate["approval_reasons"]
    assert "subcontract_dispatch_risk" not in gate["approval_reasons"]
    assert views["score"]["otd_d"] < 100.0
    (order,) = views["orders"]
    assert order.status != "ready" and order.customer_ready_day == DUE + 1
    assert {p.op_id: p.stockout_day for p in views["stock"]} == oracle_first_rupture(
        segments, lots, data) == {lots[0].op_id: DUE}
    assert [a.lot_id for a in views["late"].analyses] == [lots[0].id]
    assert [r.status for r in views["risks"]] == ["late"]
    assert "delivery" in [a.category for a in views["actions"]]


def test_the_engine_still_finishes_subcontracted_production_before_the_dispatch():
    """With free capacity the plan ends the subcontracted lot by its
    production due day (C minus 5 working days), not just before C."""
    from backend.cpo import optimize

    data = _data(subcontracted=True, eco_lot=1000, entries=[_entry("HANON", 30, 829)])
    result = optimize(copy.deepcopy(data), mode="quick", config=CONFIG)
    (lot,) = result.lots
    last = max(s.day_idx for s in result.segments if s.lot_id == lot.id and s.qty > 0)
    assert lot.production_due_day < 30
    assert last <= lot.production_due_day
    assert result.score["subcontract_dispatch_misses"] == 0
