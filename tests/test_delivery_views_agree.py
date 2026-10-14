"""Every view reads delivery readiness from one evaluator (plan Fase A, A1/A2/A6).

Score, gate, orders, tooltip, stock, late report, risks and subcontracting
must agree, order by order, with the independent oracle in
``tests/oracle_delivery.py``. Fixtures follow the failing pattern found in
revision 121: an economic lot covering several deliveries (F1), the same lot
subcontracted with the shape of 6800017267C.30 (F2), with economic surplus
(F3) and with opening stock and a committed supply (F5).

Since 14/10/2026 a subcontracted delivery is late only when the stock shown
on Entregas (pieces on the day they are made) is short on its day, like any
reference (AGENTS §2). Its subcontract dispatch (the planner's aim, never
lateness) still follows the lot: a subcontracted economic lot of the current
contract goes out whole when it ends (13/10/2026, F2-whole); F2, F3 and F5
keep the per-delivery dispatch of a lot taken over from an older plan
(``material_upgraded_from``). F2-late misses the stock on the 26th.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.analytics.late_delivery import analyze_late_deliveries
from backend.analytics.order_tracking import compute_order_tracking, compute_segment_deliveries
from backend.analytics.stock_projection import compute_stock_projections
from backend.config.types import FactoryConfig, MachineConfig
from backend.risk.slack_analytics import compute_lot_risks
from backend.scheduler.gates import build_gate_report
from backend.scheduler.improvement import subcontract_lateness
from backend.scheduler.lot_sizing import UPGRADED_MATERIAL_KEY, create_lots
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Segment
from backend.types import ClientDemandEntry, CommittedSupply, EngineData, EOp, MachineInfo
from tests.oracle_delivery import (
    WorkCalendar,
    oracle_checkpoints,
    oracle_first_rupture,
    oracle_orders,
    oracle_otd_d_failures,
)

ROOT = Path(__file__).resolve().parents[1]
START = date(2026, 10, 9)  # Friday; day 12 = 21/10, as in revision 121.
N_DAYS = 45
OP_ID = "JTE003_M1_SKU"
CONFIG = FactoryConfig(machines={"M1": MachineConfig(id="M1", group="Grandes")})


def _entry(client: str, day: int, qty: int, np_value: int | None = None) -> ClientDemandEntry:
    return ClientDemandEntry(
        client, "SKU", day, (START + timedelta(days=day)).isoformat(), qty,
        -(qty if np_value is None else np_value),
    )


def _data(*, subcontracted: bool, eco_lot: int, entries: list[ClientDemandEntry],
          stk: int = 0, supplies: tuple[CommittedSupply, ...] = ()) -> EngineData:
    days = [(START + timedelta(days=i)).isoformat() for i in range(N_DAYS)]
    demand = [0] * N_DAYS
    for entry in entries:
        demand[entry.day_idx] += abs(entry.np_value)
    op = EOp(
        id=OP_ID, sku="SKU", client="ACURION", designation="Peça", m="M1", t="TOOL",
        pH=1500, sH=0.5, operators=1, eco_lot=eco_lot, alt=None, stk=stk, backlog=0,
        d=demand, oee=1.0, wip=0, is_subcontracted=subcontracted,
        subcontract_company_id="SUB" if subcontracted else None,
        subcontract_lead_time_days=5 if subcontracted else 0,
    )
    return EngineData(
        ops=[op],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[],
        client_demands={"SKU": list(entries)},
        workdays=days,
        n_days=N_DAYS,
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
        committed_supplies=list(supplies),
    )


def _segments(lot, blocks) -> list[Segment]:
    return [
        Segment(
            lot_id=lot.id, run_id=f"R{day}", machine_id="M1", tool_id="TOOL", day_idx=day,
            start_min=start, end_min=end, shift="A" if end <= 930 else "B", qty=qty,
            prod_min=float(end - start), edd=lot.edd, sku="SKU",
        )
        for day, start, end, qty in blocks
    ]


# 6800017267C.30 in revision 121: 362 + 2175 + 73 of one economic lot, made
# on days 3, 7 (two blocks) and 13. Input order is shuffled on purpose.
SHAPE = [(13, 814, 880, 73), (7, 835, 930, 461), (3, 1276, 1364, 362), (7, 930, 1060, 1714)]
SHAPE_LATE = [(28, 814, 880, 73), (7, 835, 930, 461), (3, 1276, 1364, 362), (7, 930, 1060, 1714)]
ONE_CLIENT = [_entry("ACURION", 12, 362), _entry("ACURION", 19, 2175), _entry("ACURION", 26, 73)]
TWO_CLIENTS = [_entry("A", 12, 362), _entry("A", 19, 1000), _entry("B", 19, 1175),
               _entry("B", 26, 73)]


def f1(blocks=SHAPE):
    data = _data(subcontracted=False, eco_lot=2610, entries=TWO_CLIENTS)
    lots = create_lots(data)
    return _segments(lots[0], blocks), lots, data


def _taken_over(lots):
    """Lots taken over from a per-delivery plan: each delivery leaves alone."""
    for lot in lots:
        for output in lot.output_milestones:
            output[UPGRADED_MATERIAL_KEY] = 2
    return lots


def f2(blocks=SHAPE):
    data = _data(subcontracted=True, eco_lot=2610, entries=ONE_CLIENT)
    lots = _taken_over(create_lots(data))
    return _segments(lots[0], blocks), lots, data


def f2_whole(blocks=SHAPE):
    data = _data(subcontracted=True, eco_lot=2610, entries=ONE_CLIENT)
    lots = create_lots(data)
    return _segments(lots[0], blocks), lots, data


def f3(blocks=(*SHAPE, (13, 880, 950, 390))):
    data = _data(subcontracted=True, eco_lot=3000, entries=ONE_CLIENT)
    lots = _taken_over(create_lots(data))
    return _segments(lots[0], blocks), lots, data


def f5(blocks=((7, 835, 930, 461), (7, 930, 1060, 1714), (13, 814, 880, 73),
               (13, 880, 1100, 752))):
    supply = CommittedSupply(OP_ID, "SKU", 362, (START + timedelta(days=2)).isoformat(), 2,
                             "M1", "TOOL")
    # 500 ordered, of which 138 already in stock (NP -362), served by the supply.
    entries = [_entry("ACURION", 12, 500, 362), *ONE_CLIENT[1:]]
    data = _data(subcontracted=True, eco_lot=3000, entries=entries, stk=138, supplies=(supply,))
    lots = _taken_over(create_lots(data))
    return _segments(lots[0], list(blocks)), lots, data


def f2_late():
    return f2(SHAPE_LATE)


def f1_late():
    return f1([(20, 835, 930, 461), (3, 1276, 1364, 362), (20, 930, 1060, 1714),
               (13, 814, 880, 73)])


FIXTURES = {"F1": f1, "F1-late": f1_late, "F2": f2, "F2-late": f2_late, "F2-whole": f2_whole,
            "F3": f3, "F5": f5}


def _views(segments, lots, data):
    score = compute_score(segments, lots, data, CONFIG)
    return {
        "score": score,
        "gate": build_gate_report(segments, lots, score, data, CONFIG),
        "orders": [o for client in compute_order_tracking(segments, lots, data)
                   for o in client.orders],
        "tooltip": compute_segment_deliveries(segments, lots, data),
        "stock": compute_stock_projections(segments, lots, data),
        "late": analyze_late_deliveries(segments, lots, data, CONFIG),
        "risks": compute_lot_risks(segments, lots, data, CONFIG),
        "subcontract": subcontract_lateness(segments, lots, data),
    }


def _order_key(client, day, qty):
    return client, int(day), int(qty)


# ── Oracle anchors (the oracle itself must be right) ─────────────────────


def test_oracle_subcontracted_orders_are_ready_when_their_pieces_are_made():
    segments, lots, data = f2()
    ready = [(o.due_day, o.factory_day, o.ready_day) for o in oracle_orders(segments, lots, data)]
    # Stock rule (14/10/2026): no return trip is added.
    assert ready == [(12, 3, 3), (19, 7, 7), (26, 13, 13)]
    assert WorkCalendar(data).add(3, 5) == 10


def test_oracle_marks_only_the_slipped_portion_late():
    segments, lots, data = f2_late()
    assert [o.late for o in oracle_orders(segments, lots, data)] == [False, False, True]


def test_oracle_sends_a_current_lot_whole_when_it_ends():
    """The same lot under the current contract: everything leaves for the
    subcontractor on day 13, the lot's last day (the planner's aim), but no
    order is late: the stock covers each one on its day."""
    segments, lots, data = f2_whole()
    ready = [(o.due_day, o.factory_day, o.ready_day, o.late)
             for o in oracle_orders(segments, lots, data)]
    assert ready == [(12, 3, 3, False), (19, 7, 7, False), (26, 13, 13, False)]
    (dispatch,) = oracle_checkpoints(segments, lots, data, dispatch=True).values()
    assert [(c.due_day, c.factory_day) for c in dispatch] == [(12, 13), (19, 13), (26, 13)]
    # Not all made (the day-13 block missing): the lot never leaves, and only
    # the order whose pieces are missing is late.
    assert [o.late for o in oracle_orders(segments[1:], lots, data)] == [False, False, True]
    (dispatch,) = oracle_checkpoints(segments[1:], lots, data, dispatch=True).values()
    assert all(c.factory_day is None for c in dispatch)


# ── T1: all views agree with the oracle, order by order ──────────────────


@pytest.mark.parametrize("name", FIXTURES)
def test_every_view_agrees_with_the_oracle(name):
    segments, lots, data = FIXTURES[name]()
    oracle = oracle_orders(segments, lots, data)
    late = [o for o in oracle if o.late]
    views = _views(segments, lots, data)
    score, gate = views["score"], views["gate"]

    # Orders (Entregas), gate order metrics and late-order detail.
    by_key = {_order_key(o.client, o.delivery_day, o.order_qty): o for o in views["orders"]}
    assert len(by_key) == len(oracle)
    for expected in oracle:
        order = by_key[_order_key(expected.client, expected.due_day, expected.qty)]
        assert order.customer_ready_day == expected.ready_day, expected
        assert (order.status == "ready") == (not expected.late), expected
        if expected.allocations:
            assert order.factory_ready_day == expected.factory_day, expected
    assert gate["metrics"]["orders_late"] == len(late)
    assert sorted((row["client"], row["due_day"], row["ready_day"])
                  for row in gate["late_order_detail"]) == sorted(
        (o.client, o.due_day, o.ready_day) for o in late)

    # Lot-level score (one lot per fixture) and the late-delivery report.
    assert score["tardy_count"] == int(bool(late))
    assert score["max_tardiness"] == max((o.delay for o in late), default=0)
    assert views["late"].tardy_count == score["tardy_count"]
    assert [a.delay_days for a in views["late"].analyses] == (
        [score["max_tardiness"]] if late else [])

    # OTD-D (customer availability) and stock ruptures (the stock grid).
    assert score["otd_d_failures"] == oracle_otd_d_failures(segments, lots, data)
    ruptures = {p.op_id: p.stockout_day for p in views["stock"]}
    assert ruptures == oracle_first_rupture(segments, lots, data)

    # Risks: a lot is late exactly when one of its orders is.
    assert [r.status == "late" for r in views["risks"]] == [bool(late)]

    # Subcontract dispatch: the planner's aim (score, no-loss comparator),
    # never an approval reason or a list (14/10/2026).
    calendar = WorkCalendar(data)
    portions = [c for c in oracle_checkpoints(segments, lots, data, dispatch=True)[OP_ID]
                if c.subcontracted and c.allocations]
    late_dispatch = [c for c in portions if c.factory_day > calendar.subtract(c.due_day, 5)]
    assert "subcontract_dispatch_detail" not in gate
    assert "subcontract_dispatch_risk" not in gate["approval_reasons"]
    assert score["subcontract_dispatch_misses"] == len(late_dispatch)
    assert score["subcontract_dispatch_total"] == len(portions)
    assert sorted(views["subcontract"].values()) == sorted(
        float(max(0, c.factory_day - calendar.subtract(c.due_day, 5))) for c in portions)

    # Tooltip: each segment's quantity goes to the orders the oracle serves.
    tooltip = sorted(
        (index, item["client"], item["delivery_day"], item["qty"])
        for index, trace in enumerate(views["tooltip"])
        for item in trace["delivery_allocations"] or [])
    assert tooltip == sorted(
        (index, o.client, o.due_day, qty) for o in oracle for index, qty in o.allocations)


# ── T2: no consumer reports late when the oracle says on time ────────────


@pytest.mark.parametrize("name", ["F1", "F2", "F3", "F5"])
def test_on_time_plan_is_on_time_everywhere(name):
    segments, lots, data = FIXTURES[name]()
    assert not any(o.late for o in oracle_orders(segments, lots, data))
    views = _views(segments, lots, data)
    score, gate = views["score"], views["gate"]
    for key in ("tardy_count", "otd_d_failures", "production_due_misses",
                "subcontract_dispatch_misses"):
        assert score[key] == 0, key
    assert gate["metrics"]["orders_late"] == 0
    assert gate["late_order_detail"] == []
    assert "delivery_risk" not in gate["approval_reasons"]
    assert "subcontract_dispatch_risk" not in gate["approval_reasons"]
    assert views["late"].analyses == []
    assert all(r.status != "late" for r in views["risks"])
    assert all(p.stockout_day is None for p in views["stock"])
    assert all(o.status == "ready" for o in views["orders"])
    assert set(views["subcontract"].values()) <= {0.0}


# ── Cross-lot: pieces of a SKU are fungible, deliveries are judged per order


def _cross_lot(subcontracted: bool):
    """Two lots of 400, for days 12 and 14; the day-14 lot is made first.

    The day-12 lot finishes after its own delivery, but the day-14 lot's
    pieces serve the day-12 order in time and the day-12 lot's pieces still
    reach the day-14 order: no order is late. In-house: made on days 13 and
    7. Subcontracted: made on days 6 and 3, so the day-12 lot alone would
    miss its dispatch (5 working days before the delivery) while the day-14
    lot's pieces leave in time for it.
    """

    data = _data(subcontracted=subcontracted, eco_lot=400,
                 entries=[_entry("A", 12, 400), _entry("A", 14, 400)])
    first_due, second_due = create_lots(data)
    assert [lot.output_milestones[0]["customer_delivery_day"]
            for lot in (first_due, second_due)] == [12, 14]
    day_first, day_second = (6, 3) if subcontracted else (13, 7)
    segments = (_segments(first_due, [(day_first, 420, 700, 400)])
                + _segments(second_due, [(day_second, 420, 700, 400)]))
    return segments, [first_due, second_due], data


@pytest.mark.parametrize("subcontracted", [False, True], ids=["in-house", "subcontracted"])
def test_cross_lot_on_time_orders_are_no_delivery_risk(subcontracted):
    segments, lots, data = _cross_lot(subcontracted)
    oracle = oracle_orders(segments, lots, data)
    assert not any(o.late for o in oracle)
    views = _views(segments, lots, data)
    score, gate = views["score"], views["gate"]

    # The lot metric ("Lotes no prazo") still sees the in-house day-12 lot
    # finishing after its own delivery; it informs, it does not decide
    # approval. The subcontracted lots are made before their deliveries.
    tardy = 0 if subcontracted else 1
    assert score["tardy_count"] == views["late"].tardy_count == tardy
    assert [a.lot_id for a in views["late"].analyses] == [lots[0].id] * tardy

    # Every order view agrees with the oracle: nothing is late.
    assert gate["metrics"]["orders_late"] == 0
    assert gate["late_order_detail"] == []
    assert score["otd_d_failures"] == oracle_otd_d_failures(segments, lots, data) == 0
    assert gate["delivery_gate_passed"] is True
    assert "delivery_risk" not in gate["approval_reasons"]
    by_key = {_order_key(o.client, o.delivery_day, o.order_qty): o for o in views["orders"]}
    for expected in oracle:
        order = by_key[_order_key(expected.client, expected.due_day, expected.qty)]
        assert order.status == "ready"
        assert order.customer_ready_day == expected.ready_day
        assert order.factory_ready_day == expected.factory_day
    assert {p.op_id: p.stockout_day for p in views["stock"]} == oracle_first_rupture(
        segments, lots, data)
    assert all(r.status != "late" for r in views["risks"])
    tooltip = sorted(
        (index, item["client"], item["delivery_day"], item["qty"])
        for index, trace in enumerate(views["tooltip"])
        for item in trace["delivery_allocations"] or [])
    assert tooltip == sorted(
        (index, o.client, o.due_day, qty) for o in oracle for index, qty in o.allocations)

    # Subcontract dispatch is judged per delivery too: each one leaves in time.
    assert score["subcontract_dispatch_misses"] == 0
    assert "subcontract_dispatch_risk" not in gate["approval_reasons"]
    assert set(views["subcontract"].values()) <= {0.0}
    assert len(views["subcontract"]) == (2 if subcontracted else 0)


def test_cross_lot_late_order_is_still_a_delivery_risk():
    # Same lots, both made after day 12: the day-12 order is really late.
    data = _data(subcontracted=False, eco_lot=400,
                 entries=[_entry("A", 12, 400), _entry("A", 14, 400)])
    first_due, second_due = create_lots(data)
    segments = (_segments(first_due, [(14, 420, 700, 400)])
                + _segments(second_due, [(13, 420, 700, 400)]))
    lots = [first_due, second_due]
    late = [o for o in oracle_orders(segments, lots, data) if o.late]
    assert [(o.due_day, o.ready_day) for o in late] == [(12, 13)]
    views = _views(segments, lots, data)
    assert views["gate"]["metrics"]["orders_late"] == 1
    assert "delivery_risk" in views["gate"]["approval_reasons"]
    assert views["score"]["otd_d_failures"] == oracle_otd_d_failures(segments, lots, data)


def test_readiness_requires_the_factory_calendar():
    from backend.scheduler.material_quantities import (
        delivery_portions,
        delivery_readiness,
        factory_readiness,
    )

    segments, lots, data = f2()
    with pytest.raises(ValueError):
        delivery_readiness(lots, segments, None)
    with pytest.raises(ValueError):
        delivery_portions(lots, segments, None)
    # Without a calendar only factory days exist; the customer day is absent
    # instead of being counted on calendar days.
    factory = factory_readiness(lots, segments, missing_day=N_DAYS)
    assert all(record.customer_ready_day is None for record in factory)
    with_calendar = delivery_readiness(lots, segments, data)
    assert [r.factory_day for r in factory] == [r.factory_day for r in with_calendar]
    # 21/10 (day 12) portion made on Monday 12/10 (day 3): ready that day,
    # the stock shown on Entregas (14/10/2026).
    assert with_calendar[0].customer_ready_day == 3


# Lot-end readiness ("the order is ready when the economic lot ends", plus the
# lead time) must only exist in the shared evaluator.
_CONSUMERS = [
    "backend/analytics/stock_projection.py",
    "backend/analytics/order_tracking.py",
    "backend/analytics/late_delivery.py",
    "backend/analytics/expedition.py",
    "backend/analytics/coverage_audit.py",
    "backend/analytics/replan_proposals.py",
    "backend/analytics/ctp.py",
    "backend/risk/robustness.py",
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "backend/console").glob("*.py")),
    "backend/scheduler/scoring.py",
    "backend/scheduler/improvement.py",
    "backend/scheduler/gates.py",
    "backend/scheduler/stress.py",
    "backend/risk/slack_analytics.py",
    "backend/api/console.py",
    "backend/cpo/optimizer.py",
    "backend/cpo/cpsat_polish.py",
]
_LOT_END = re.compile(
    r"\badd_workdays\(|\b(lot_completion|completion_by_lot|lot_end|external_completion"
    r"|subcontracted_completion|output_by_lot_op|output_completion_days)\b"
)


# Working-day arithmetic that is not readiness: robustness delays material
# by whole working days and measures a ten-working-day window.
_NOT_READINESS = {"backend/risk/robustness.py": {"add_workdays("}}


@pytest.mark.parametrize("path", _CONSUMERS)
def test_lot_end_readiness_only_in_the_shared_evaluator(path):
    source = (ROOT / path).read_text(encoding="utf-8")
    allowed = _NOT_READINESS.get(path, set())
    assert not [m.group(0) for m in _LOT_END.finditer(source)
                if m.group(0) not in allowed], path


def test_robustness_replay_reads_the_shared_evaluator():
    source = (ROOT / "backend/risk/robustness.py").read_text(encoding="utf-8")
    assert source.count("add_workdays(") == 2  # material delay and window end
    assert "delivery_readiness(" in source


# ── T3/T4: tooltip chronology and reconciliation with orders ─────────────


@pytest.mark.parametrize("name", FIXTURES)
def test_tooltip_follows_absolute_time(name):
    segments, lots, data = FIXTURES[name]()
    traces = compute_segment_deliveries(segments, lots, data)
    served = [
        item["delivery_day"]
        for index in sorted(range(len(segments)),
                            key=lambda i: (segments[i].day_idx * 1440 + segments[i].end_min, i))
        for item in traces[index]["delivery_allocations"] or []
    ]
    assert served == sorted(served)


def test_minute_of_day_counterexample_serves_the_first_delivery_first():
    # Day 13 ends at 880, earlier in the day than day 3 (1364) and day 7 (930):
    # sorting by minute of day would send the day-13 pieces to the 21/10 order.
    segments, lots, data = f2()
    traces = compute_segment_deliveries(segments, lots, data)
    by_day = {segments[i].day_idx: [] for i in range(len(segments))}
    for segment, trace in zip(segments, traces):
        by_day[segment.day_idx] += [(x["delivery_day"], x["qty"]) for x in
                                    trace["delivery_allocations"]]
    assert by_day == {3: [(12, 362)], 7: [(19, 461), (19, 1714)], 13: [(26, 73)]}
    ready = {x["delivery_day"]: x["customer_ready_day"]
             for trace in traces for x in trace["delivery_allocations"]}
    assert ready == {12: 3, 19: 7, 26: 13}


@pytest.mark.parametrize("name", FIXTURES)
def test_tooltip_reconciles_with_orders(name):
    segments, lots, data = FIXTURES[name]()
    traces = compute_segment_deliveries(segments, lots, data)
    orders = [o for c in compute_order_tracking(segments, lots, data) for o in c.orders]
    oracle = {(o.client, o.due_day): sum(q for _i, q in o.allocations)
              for o in oracle_orders(segments, lots, data)}
    for order in orders:
        items = [x for trace in traces for x in trace["delivery_allocations"] or []
                 if (x["client"], x["delivery_day"]) == (order.client, order.delivery_day)]
        production = sum(x["qty"] for x in items)
        assert production == oracle[(order.client, order.delivery_day)]
        assert production <= order.allocated_qty == order.order_qty - order.shortfall_qty
        if items and order.customer_ready_day is not None:
            assert max(x["customer_ready_day"] for x in items) <= order.customer_ready_day
            if production == order.order_qty:
                assert max(x["customer_ready_day"] for x in items) == order.customer_ready_day
    for segment, trace in zip(segments, traces):
        total = sum(x["qty"] for x in trace["delivery_allocations"] + trace["unallocated_output"])
        assert total == segment.qty


# ── T12: demand without production still shows as a risk ────────────────


def test_lot_with_demand_but_no_segments_is_a_risk():
    segments, lots, data = f2()
    risks = compute_lot_risks([], lots, data, CONFIG)
    assert [(r.lot_id, r.status) for r in risks] == [(lots[0].id, "late")]
    assert risks[0].edd == 12
    score = compute_score([], lots, data, CONFIG, include_operational_audit=False)
    assert score["tardy_count"] == analyze_late_deliveries([], lots, data, CONFIG).tardy_count == 1


# ── T13: each order shows its own portion's dispatch ─────────────────────


def test_each_order_shows_its_own_portion_dispatch():
    segments, lots, data = f2()
    calendar = WorkCalendar(data)
    orders = sorted((o for c in compute_order_tracking(segments, lots, data) for o in c.orders),
                    key=lambda o: o.delivery_day)
    assert [(o.delivery_day, o.factory_ready_day, o.customer_ready_day,
             o.subcontract_dispatch_day) for o in orders] == [
        (due, made, made, calendar.subtract(due, 5))
        for due, made in ((12, 3), (19, 7), (26, 13))
    ]
    assert all(o.is_subcontracted and o.status == "ready" for o in orders)


def test_economic_surplus_is_never_an_order():
    segments, lots, data = f3()
    traces = compute_segment_deliveries(segments, lots, data)
    assert traces[-1]["delivery_allocations"] == []
    assert traces[-1]["unallocated_output"] == [{"sku": "SKU", "qty": 390}]


def test_legacy_twin_cycle_keeps_completing_with_the_lot():
    """Material version 1 twin cycles (plans saved before Fase B2) are read
    under their recorded rule: every output completes with the lot."""

    from backend.scheduler.material_quantities import delivery_readiness

    segments, lots, data = f1()
    outputs = [{**output, "quantity_material_version": 1}
               for output in lots[0].output_milestones]
    lot = replace(lots[0], is_twin=True, output_milestones=outputs)
    days = {r.index: r.factory_day for r in delivery_readiness([lot], segments, data)}
    assert set(days.values()) == {13}


@pytest.mark.parametrize("slip", [False, True], ids=["on-time", "late-side"])
def test_twin_sides_agree_with_the_oracle_order_by_order(slip):
    """Fase B2: each side of a twin cycle is served per delivery; every view
    reads the same readiness as the oracle (orders, gate, OTD-D, stock,
    late report, risks, tooltip)."""

    from tests.test_twin_per_delivery import CONFIG as TWIN_CONFIG
    from tests.test_twin_per_delivery import _carry_forward, _segment

    data = _carry_forward()
    (lot,) = create_lots(data, TWIN_CONFIG)
    segments = [_segment(lot, 7, 420, 550, 2500, setup=30),
                _segment(lot, 31 if slip else 21, 420, 440, 500)]
    oracle = oracle_orders(segments, [lot], data)
    late = [o for o in oracle if o.late]
    assert [(o.sku, o.due_day) for o in late] == ([("B", 30)] if slip else [])
    score = compute_score(segments, [lot], data, TWIN_CONFIG)
    gate = build_gate_report(segments, [lot], score, data, TWIN_CONFIG)
    orders = {(o.sku, o.delivery_day): o for c in compute_order_tracking(segments, [lot], data)
              for o in c.orders}
    assert len(orders) == len(oracle)
    for expected in oracle:
        order = orders[(expected.sku, expected.due_day)]
        assert order.customer_ready_day == expected.ready_day, expected
        assert (order.status == "ready") == (not expected.late), expected
    assert gate["metrics"]["orders_late"] == len(late)
    assert score["otd_d_failures"] == oracle_otd_d_failures(segments, [lot], data)
    assert {p.op_id: p.stockout_day for p in compute_stock_projections(segments, [lot], data)} \
        == oracle_first_rupture(segments, [lot], data)
    # The lot is late exactly when one of its deliveries is.
    assert score["tardy_count"] == int(bool(late))
    assert analyze_late_deliveries(segments, [lot], data, TWIN_CONFIG).tardy_count == int(bool(late))
    assert [r.status == "late" for r in compute_lot_risks(segments, [lot], data, TWIN_CONFIG)] \
        == [bool(late)]
    tooltip = sorted(
        (index, item["sku"], item["delivery_day"], item["qty"])
        for index, trace in enumerate(compute_segment_deliveries(segments, [lot], data))
        for item in trace["delivery_allocations"] or [])
    assert tooltip == sorted(
        (index, o.sku, o.due_day, qty) for o in oracle for index, qty in o.allocations)


# ── F6: frozen revision 121 (private, skipped when absent) ───────────────


@pytest.fixture(scope="module")
def rev121():
    from tests.snapshot_fixture import load_snapshot

    snapshot = load_snapshot("rev121")
    assert snapshot.manifest["plan_revision"] == 121
    return snapshot.data, snapshot.config, snapshot.result


@pytest.mark.needs_private
def test_rev121_views_agree(rev121):
    data, config, result = rev121
    segments, lots = result.segments, result.lots
    stock = {p.op_id: p for p in compute_stock_projections(segments, lots, data)}
    for sku in ("CF589MMA1A02.20", "6800017267C.30"):
        (op,) = [op for op in data.ops if op.sku == sku]
        assert stock[op.id].stockout_day is None, sku

    score = compute_score(segments, lots, data, config, include_operational_audit=False)
    gate = build_gate_report(segments, lots, score, data, config,
                             operational_audit=_EMPTY_AUDIT)
    oracle = oracle_orders(segments, lots, data)
    oracle_late = [o for o in oracle if o.late]
    assert gate["metrics"]["orders_late"] == len(oracle_late)
    late_lots = {a.lot_id for a in analyze_late_deliveries(segments, lots, data, config).analyses}
    assert len(late_lots) == score["tardy_count"]
    # Tardy-based reading: every late order is served by a tardy lot, and
    # without late orders no lot is tardy.
    assert bool(oracle_late) == bool(score["tardy_count"])
    late_orders = {(o.sku, o.client, o.delivery_day) for c in
                   compute_order_tracking(segments, lots, data) for o in c.orders
                   if o.status != "ready"}
    assert late_orders == {(o.sku, o.client, o.due_day) for o in oracle_late}
    assert score["otd_d_failures"] == oracle_otd_d_failures(segments, lots, data)
    ruptures = oracle_first_rupture(segments, lots, data)
    assert {op_id: p.stockout_day for op_id, p in stock.items()} == ruptures
    assert "subcontract_dispatch_risk" not in gate["approval_reasons"]
    if not oracle_late:
        assert not any(r.status == "late" for r in compute_lot_risks(segments, lots, data, config))
        assert "delivery_risk" not in gate["approval_reasons"]


_EMPTY_AUDIT = {
    "left_shift_opportunities": 0,
    "lower_priority_campaign_interruptions": 0,
    "priority_order_anomalies": 0,
    "avoidable_priority_order_anomalies": 0,
    "released_tool_priority_inversions": 0,
    "left_shift_detail": [],
    "protected_left_shift_detail": [],
    "campaign_interruption_detail": [],
    "priority_order_detail": [],
}
