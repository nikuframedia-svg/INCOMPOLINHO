"""A subcontracted economic lot goes out whole (Luís, 13/10/2026; AGENTS §2).

The whole economic lot goes to the subcontractor at once, when its last piece
is made, and every piece comes back together ``lead`` working days later. So
every delivery the lot serves is ready at ``lot end + lead``, and the lot has
to end by the latest dispatch day ``H`` of its first delivery. One evaluator
(``material_quantities.delivery_readiness`` / ``delivery_portions``) says it;
the gate, the score, the idle-capacity notice, the stock screen and the Gantt
read it. Until 13/10 each delivery left with its own pieces.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from backend.analytics.order_tracking import compute_segment_deliveries
from backend.analytics.stock_projection import compute_stock_projections
from backend.config.planning import apply_effective_planning_config
from backend.scheduler.gates import build_gate_report
from backend.scheduler.jit_policy import add_workdays
from backend.scheduler.lot_sizing import UPGRADED_MATERIAL_KEY, create_lots
from backend.scheduler.material_quantities import (
    delivery_portions,
    delivery_readiness,
    readiness_holidays,
)
from backend.scheduler.scoring import compute_score
from backend.types import EOp, EngineData, MachineInfo
from tests.test_subcontract_release import _config

N_DAYS = 30
LEAD = 5  # working days (``_config``)


def _data(demand: dict[int, int], *, eco_lot: int = 300) -> EngineData:
    first = date(2026, 9, 7)  # Monday
    workdays = [(first + timedelta(days=offset)).isoformat() for offset in range(N_DAYS)]
    d = [0] * N_DAYS
    for day, qty in demand.items():
        d[day] = qty
    op = EOp(
        id="T1_M1_SUB", sku="SUB", client="CLIENTE", designation="Peça", m="M1", t="T1",
        pH=100, sH=0, operators=1, eco_lot=eco_lot, alt=None, stk=0, backlog=0, d=d,
        oee=1.0, wip=0,
    )
    data = EngineData(
        ops=[op],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[],
        client_demands={},
        workdays=workdays,
        n_days=N_DAYS,
        holidays=[
            offset for offset in range(N_DAYS)
            if (first + timedelta(days=offset)).weekday() >= 5
        ],
    )
    apply_effective_planning_config(data, _config())
    return data


def _lot(data):
    (lot,) = create_lots(data, _config())
    return lot


def _segments(lot, parts: list[tuple[int, int]]):
    """One segment per ``(day, qty)``, 07:00 onwards (100 pieces an hour)."""
    from backend.scheduler.types import Segment

    return [
        Segment(
            lot_id=lot.id, run_id="RUN", machine_id="M1", tool_id="T1", day_idx=day,
            start_min=420, end_min=420 + qty * 60 // 100, shift="A", qty=qty,
            prod_min=qty * 60 / 100, setup_min=0, sku=lot.sku,
        )
        for day, qty in parts
    ]


def _two_deliveries():
    """300 pieces (economic lot) for 100 on Wed 16/09 (day 9) and 100 on Wed
    23/09 (day 16): the latest dispatches are day 2 and day 9."""
    data = _data({9: 100, 16: 100})
    lot = _lot(data)
    assert lot.qty == 300
    assert [
        (o["qty"], o["customer_delivery_day"], o["latest_subcontract_dispatch_day"],
         bool(o.get("is_economic_surplus")))
        for o in lot.output_milestones
    ] == [(100, 9, 2, False), (100, 16, 9, False), (100, 16, 9, True)]
    return data, lot


def test_the_lot_deadline_is_the_latest_dispatch_of_its_first_delivery():
    _data_, lot = _two_deliveries()
    assert lot.latest_subcontract_dispatch_day == 2
    assert lot.production_due_day == lot.edd == 2


def test_every_delivery_leaves_with_the_whole_lot_and_is_back_together():
    data, lot = _two_deliveries()
    # The first delivery's pieces are made on day 1, the lot ends on day 2.
    segments = _segments(lot, [(1, 150), (2, 150)])

    records = delivery_readiness([lot], segments, data)
    assert [(r.qty, r.factory_day, r.customer_ready_day, r.whole_lot_dispatch) for r in records] == [
        (100, 2, 9, True), (100, 2, 9, True), (100, 2, 9, True),
    ]
    portions = delivery_portions([lot], segments, data)
    assert [
        (p.qty, p.produced_qty, p.factory_day, p.customer_ready_day, p.whole_lot_dispatch)
        for p in portions
    ] == [(100, 100, 2, 9, True), (100, 100, 2, 9, True), (0, 100, 2, 9, True)]
    # Ready = lot end + lead in working days: Wed 9/9 + 5 = Wed 16/9.
    holidays = readiness_holidays([lot], segments, data)
    assert add_workdays(2, LEAD, holidays) == 9
    # Factory availability (stock made on the day) is unchanged.
    assert sorted((item.day_idx, item.qty) for p in portions for item in p.slices) == [
        (1, 50), (1, 100), (2, 50), (2, 100),
    ]


def test_a_lot_ending_after_the_first_dispatch_makes_only_that_delivery_late():
    data, lot = _two_deliveries()
    # The first delivery's pieces are done on day 1, but the lot ends on day
    # 3, after H = day 2: the whole lot leaves on day 3 and is back on day 10.
    segments = _segments(lot, [(1, 150), (3, 150)])
    portions = [p for p in delivery_portions([lot], segments, data) if p.is_demand]
    assert [(p.customer_delivery_day, p.factory_day, p.customer_ready_day) for p in portions] == [
        (9, 3, 10), (16, 3, 10),
    ]

    score = compute_score(segments, [lot], data)
    assert score["subcontract_dispatch_total"] == 2
    assert score["subcontract_dispatch_misses"] == 1
    gate = build_gate_report(segments, [lot], score, data, _config())
    (late,) = gate["subcontract_dispatch_detail"]
    assert (late["customer_delivery_day"], late["completion_day"], late["late_workdays"]) == (
        9, 3, 1,
    )
    assert late["whole_lot"] is True
    assert late["customer_ready_day"] == 10


def test_until_the_whole_lot_is_made_nothing_leaves():
    data, lot = _two_deliveries()
    # 250 of 300 pieces: both deliveries' pieces exist, the surplus does not.
    segments = _segments(lot, [(1, 150), (2, 100)])
    records = delivery_readiness([lot], segments, data, missing_day=N_DAYS)
    assert {(r.factory_day, r.whole_lot_dispatch) for r in records} == {(N_DAYS, True)}


def test_a_lot_taken_over_from_the_per_delivery_contract_keeps_its_old_dispatch():
    """A lot of versions 1-2 taken over as version 3 may still be several
    productions of its old contract: each delivery leaves with its own
    pieces until «Recalcular plano» sizes it again."""
    data, lot = _two_deliveries()
    upgraded = copy.deepcopy(lot)
    for output in upgraded.output_milestones:
        output[UPGRADED_MATERIAL_KEY] = 2
    segments = _segments(upgraded, [(1, 150), (2, 150)])
    records = delivery_readiness([upgraded], segments, data)
    assert [(r.factory_day, r.customer_ready_day, r.whole_lot_dispatch) for r in records] == [
        (1, 8, False), (2, 9, False), (2, 9, False),
    ]


def test_in_house_lots_are_ready_with_their_own_pieces():
    data = _data({9: 100, 16: 100})
    in_house = _config(subcontracted=False)
    data.ops[0].is_subcontracted = False
    data.ops[0].subcontract_company_id = None
    data.ops[0].subcontract_lead_time_days = 0
    apply_effective_planning_config(data, in_house)
    (lot,) = create_lots(data, in_house)
    segments = _segments(lot, [(1, 150), (2, 150)])
    records = delivery_readiness([lot], segments, data)
    assert [(r.factory_day, r.customer_ready_day, r.whole_lot_dispatch) for r in records] == [
        (1, 1, False), (2, 2, False), (2, 2, False),
    ]


def test_stock_screen_sends_the_whole_lot_when_it_ends_and_gets_it_back_together():
    data, lot = _two_deliveries()
    segments = _segments(lot, [(1, 150), (2, 150)])
    (projection,) = compute_stock_projections(segments, [lot], data)
    days = {day.day_idx: day for day in projection.days}
    assert [(day.day_idx, day.subcontract_sent) for day in projection.days
            if day.subcontract_sent] == [(2, 300)]
    assert [day.day_idx for day in projection.days if day.subcontract_returns] == [9]
    (back,) = days[9].subcontract_returns
    assert (back["qty"], back["stamped_from_day"], back["stamped_to_day"], back["machines"]) == (
        300, 1, 2, ["M1"],
    )
    assert days[9].produced == 300 and days[1].produced == days[2].produced == 0


def test_gantt_segments_show_one_trip_for_the_whole_lot():
    data, lot = _two_deliveries()
    segments = _segments(lot, [(1, 150), (2, 150)])
    trips = [row["subcontract_trips"] for row in compute_segment_deliveries(segments, [lot], data)]
    assert trips == [[{"sent_day": 2, "return_day": 9, "whole_lot": True}]] * 2


def _delivery_of_two_lots(*, first_upgraded=False):
    """Lot A (120: 100 for day 9, 20 for day 16) is made on day 4, lot B (240:
    180 for day 16, 60 surplus) on day 1. FIFO, B's pieces serve day 9 and
    part of day 16, whose other 60 pieces are A's: one delivery, two lots."""
    data = _data({9: 100, 16: 200}, eco_lot=120)
    first, second = create_lots(data, _config())
    assert (first.qty, second.qty) == (120, 240)
    if first_upgraded:
        for output in second.output_milestones:
            output[UPGRADED_MATERIAL_KEY] = 2
    segments = _segments(second, [(1, 240)]) + _segments(first, [(4, 120)])
    (mixed,) = [
        p for p in delivery_portions([first, second], segments, data)
        if p.is_demand and len(p.lot_ids) == 2
    ]
    assert mixed.customer_ready_day == 11  # day 4 + 5 working days
    return data, [first, second], segments


def test_gantt_trip_of_a_lot_is_its_own_when_a_delivery_waits_for_two_lots():
    """Review of 13/10/2026: B leaves whole on day 1 and is back on day 8,
    although the delivery it shares with A is ready only on day 11."""
    data, lots, segments = _delivery_of_two_lots()
    trips = [row["subcontract_trips"] for row in compute_segment_deliveries(segments, lots, data)]
    assert trips == [
        [{"sent_day": 1, "return_day": 8, "whole_lot": True}],
        [{"sent_day": 4, "return_day": 11, "whole_lot": True}],
    ]


def test_gantt_trip_of_a_per_delivery_lot_mixed_with_a_whole_lot():
    """B is taken over from the per-delivery contract: its pieces of the
    shared delivery leave when that delivery is complete (day 4, with A's),
    not on the day they were stamped; A still leaves whole."""
    data, lots, segments = _delivery_of_two_lots(first_upgraded=True)
    trips = [row["subcontract_trips"] for row in compute_segment_deliveries(segments, lots, data)]
    assert trips == [
        [
            {"sent_day": 1, "return_day": 8, "whole_lot": False},
            {"sent_day": 4, "return_day": 11, "whole_lot": False},
        ],
        [{"sent_day": 4, "return_day": 11, "whole_lot": True}],
    ]
    # The stock screen sends B's pieces on the days they were stamped.
    (projection,) = compute_stock_projections(segments, lots, data)
    assert [(day.day_idx, day.subcontract_sent) for day in projection.days
            if day.subcontract_sent] == [(1, 240), (4, 120)]


def test_idle_capacity_counts_the_rest_of_a_lot_that_goes_out_whole():
    """The lot ends on day 4, after H = day 2, with the machine idle on days
    0-2: a possible improvement. Its first delivery's pieces exist on day 0,
    but only the whole lot leaves, so the notice asks for the lot's rest."""
    from backend.config.types import FactoryConfig
    from backend.scheduler.idle_capacity import late_with_idle_capacity

    data, lot = _two_deliveries()
    segments = _segments(lot, [(0, 150), (4, 150)])
    config = FactoryConfig(machines=_config().machines)
    (case,) = late_with_idle_capacity(
        segments, [lot], data, config, planning_day=0,
        now=datetime(2026, 9, 1, 6, 0),
    )
    assert case["lot_id"] == lot.id
    assert case["subcontracted"] and case["lot_end_rule"]
    assert case["production_due_day"] == 2
    # The rest of the lot (150 pieces, 90 min) must fit by day 2.
    assert case["needed_min"] == pytest.approx(90.0)


# ── real plan (private fixture) ──────────────────────────────────────────


@pytest.mark.needs_private
def test_rev128_subcontracted_lots_go_out_whole():
    """ISOP of 13/10 (rev128), recalculated under the current contract. Every
    delivery of a subcontracted lot (HAN002 CF589MMA1A02.20, JTE003, the
    BFP178/BFP186 twins) is ready at its lot's end + 5 working days. Under
    the per-delivery rule a HAN002 lot covering the deliveries of two weeks
    sent the first week's pieces before the lot ended."""
    from backend.plans.serialize import deserialize_snapshot
    from backend.scheduler.scheduler import schedule_all
    from tests.snapshot_fixture import load_payload

    _manifest, payload = load_payload("rev128")
    restored = deserialize_snapshot(copy.deepcopy(payload))
    data, config = restored["engine_data"], restored["config"]
    result = schedule_all(copy.deepcopy(data), config=config)
    holidays = readiness_holidays(result.lots, result.segments, data)

    records = delivery_readiness(result.lots, result.segments, data)
    subcontracted = [r for r in records if r.is_subcontracted]
    assert {r.op_id.split("_")[0] for r in subcontracted} >= {"HAN002", "JTE003", "BFP178", "BFP186"}
    by_lot: dict[str, list] = {}
    for record in subcontracted:
        by_lot.setdefault(record.lot_id, []).append(record)
    lots = {lot.id: lot for lot in result.lots}
    changed = []
    for lot_id, lot_records in by_lot.items():
        end = max(s.day_idx for s in result.segments if s.lot_id == lot_id and s.qty > 0)
        assert {(r.factory_day, r.customer_ready_day, r.whole_lot_dispatch)
                for r in lot_records} == {(end, add_workdays(end, 5, holidays), True)}, lot_id
        # The lot's deadline is H of its first delivery.
        first = min((r for r in lot_records if r.is_demand),
                    key=lambda r: r.customer_delivery_day)
        assert lots[lot_id].latest_subcontract_dispatch_day == first.latest_subcontract_dispatch_day
        own_done = [max((item.day_idx for item in r.slices), default=end)
                    for r in lot_records if r.is_demand]
        if min(own_done) < end:
            changed.append(lot_id)
    # Some HAN002 lot really waits for its own end now.
    assert any("HAN002_PRM043_CF589MMA1A02.20" in lot_id for lot_id in changed)
    # The plan is still valid and the stock screen sends each lot whole.
    portions = delivery_portions(result.lots, result.segments, data, records=records)
    for portion in portions:
        if portion.is_subcontracted:
            assert portion.whole_lot_dispatch
            assert {item.available_day for item in portion.slices} <= {
                max(s.day_idx for s in result.segments if s.lot_id == item.lot_id and s.qty > 0)
                for item in portion.slices
            }


def test_twin_cycle_only_the_subcontracted_side_waits_for_the_lot():
    """A twin cycle with one subcontracted side: that side goes out whole at
    the lot end, the other side is ready with its own pieces."""
    from backend.types import TwinGroup

    data = _data({9: 100, 16: 100}, eco_lot=0)
    sub = data.ops[0]
    other = replace(sub, id="T1_M1_OWN", sku="OWN", d=list(sub.d))
    data.ops = [sub, other]
    data.twin_groups = [TwinGroup(
        tool_id="T1", machine_id="M1", op_id_1=sub.id, op_id_2=other.id,
        sku_1="SUB", sku_2="OWN", eco_lot_1=0, eco_lot_2=0,
    )]
    apply_effective_planning_config(data, _config())
    twins = [lot for lot in create_lots(data, _config()) if lot.is_twin]
    lot = twins[0]
    segments = _segments(lot, [(1, lot.qty // 2), (2, lot.qty - lot.qty // 2)])
    for segment in segments:
        segment.twin_outputs = [(sub.id, "SUB", segment.qty), (other.id, "OWN", segment.qty)]
    records = delivery_readiness([lot], segments, data)
    own = [r for r in records if r.op_id == other.id]
    subbed = [r for r in records if r.op_id == sub.id]
    assert subbed and {(r.factory_day, r.whole_lot_dispatch) for r in subbed} == {(2, True)}
    assert own and not any(r.whole_lot_dispatch for r in own)
