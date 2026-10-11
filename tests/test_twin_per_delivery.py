"""Twin cycles per delivery (plan of 10/10, Fase B2; owner decision).

A twin tool makes one piece of each side per cycle, in one execution. The
economic lot is sized once (eco lot HARD per SKU, AGENTS §3); with carry-
forward a cycle also makes pieces for later deliveries. Each delivery keeps
its own material release ``R`` (AGENTS §2): only the two deliveries that
formed the cycle share ``R_ciclo = min(R)``. On day ``d`` the cycle may make
as many cycles as the larger of its two sides' released quantities (the other
side's pieces are co-produced).

Calendar: day 0 = Monday 12/10/2026, weekends are holidays. Deliveries on
days 14, 15, 28 and 30 release material on days 7, 8, 21 and 23.
"""

from __future__ import annotations

import copy
import dataclasses
import gzip
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.analytics.order_tracking import compute_order_tracking, compute_segment_deliveries
from backend.analytics.stock_projection import compute_stock_projections
from backend.config.types import FactoryConfig, MachineConfig
from backend.plans.serialize import serialize_result_snapshot
from backend.plans.store import LegacyMaterialPlanError, PlansStore, _assert_activatable_payload
from backend.scheduler.canonical import (
    QUANTITY_MATERIAL_VERSION,
    legacy_material_plan,
    source_contract_violations,
)
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.material_quantities import (
    delivery_readiness,
    material_portions,
    released_quantity,
)
from backend.scheduler.quantity_dispatch import has_quantity_releases
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import ScheduleResult, Segment
from backend.types import ClientDemandEntry, EngineData, EOp, MachineInfo, TwinGroup
from tests.oracle_delivery import (
    WorkCalendar,
    oracle_coverage,
    oracle_lot_order,
    oracle_first_rupture,
    oracle_lot_releases,
    oracle_orders,
    oracle_otd_d_failures,
    oracle_window_violations,
)
from tests.oracle_delivery import _released as _oracle_released

START = date(2026, 10, 12)  # Monday
N_DAYS = 40
PH = 1500  # pieces per hour on each side: 3000 cycles = 120 min
CONFIG = FactoryConfig(machines={"M1": MachineConfig(id="M1", group="Grandes")})
A_ID, B_ID = "TT_M1_A", "TT_M1_B"


def _op(op_id, sku, demand_by_day, *, eco_lot=3000, ph=PH):
    demand = [0] * N_DAYS
    for day, qty in demand_by_day.items():
        demand[day] = qty
    return EOp(
        id=op_id, sku=sku, client="CLIENTE", designation=sku, m="M1", t="TT", pH=ph,
        sH=0.5, operators=1, eco_lot=eco_lot, alt=None, stk=0, backlog=0, d=demand,
        oee=1.0, wip=0,
    )


def _data(a_demand, b_demand, *, extra_ops=(), b_ph=PH, eco_lot=3000):
    days = [(START + timedelta(days=i)).isoformat() for i in range(N_DAYS)]
    a = _op(A_ID, "A", a_demand, eco_lot=eco_lot)
    b = _op(B_ID, "B", b_demand, ph=b_ph, eco_lot=eco_lot)
    return EngineData(
        ops=[a, b, *extra_ops],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[TwinGroup("TT", "M1", A_ID, B_ID, "A", "B", eco_lot, eco_lot)],
        client_demands={
            sku: [ClientDemandEntry("CLIENTE", sku, day, days[day], qty, -qty)
                  for day, qty in sorted(demand.items())]
            for sku, demand in (("A", a_demand), ("B", b_demand))
        },
        workdays=days,
        n_days=N_DAYS,
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )


def _carry_forward():
    """A: 1000 (day 14) + 1500 (day 28). B: 2500 (day 15) + 400 (day 30).

    One cycle of 3000 (eco lot) formed by A day 14 and B day 15. A's 2000
    extra pieces cover its day-28 delivery (1500) and 500 surplus; B's 500
    extra cover its day-30 delivery (400) and 100 surplus.
    """

    return _data({14: 1000, 28: 1500}, {15: 2500, 30: 400})


def _outputs(lot, op_id):
    return [
        (o["customer_delivery_day"], o["qty"], o["material_release_day"],
         o.get("cycle_material_release_day"), bool(o.get("is_economic_surplus")))
        for o in lot.output_milestones if o["op_id"] == op_id
    ]


# ── lot sizing: one output per covered delivery, eco lot conserved ───────


def test_each_side_records_one_output_per_covered_delivery():
    (lot,) = create_lots(_carry_forward(), CONFIG)
    assert lot.is_twin and lot.qty == 3000
    assert lot.twin_outputs == [(A_ID, "A", 3000), (B_ID, "B", 3000)]
    # Only the pair that formed the cycle (A day 14, B day 15) shares min(R) = 7.
    assert _outputs(lot, A_ID) == [
        (14, 1000, 7, 7, False), (28, 1500, 21, None, False), (28, 500, 21, None, True),
    ]
    assert _outputs(lot, B_ID) == [
        (15, 2500, 8, 7, False), (30, 400, 23, None, False), (30, 100, 23, None, True),
    ]
    assert {o["quantity_material_version"] for o in lot.output_milestones} == {
        QUANTITY_MATERIAL_VERSION
    } == {2}
    assert lot.material_release_day == 7


def test_eco_lot_is_conserved_per_side_and_never_counted_twice():
    data = _data({3: 1000, 5: 1000, 20: 700}, {1: 800, 4: 800, 25: 2600}, )
    lots = create_lots(data, CONFIG)
    for side, op in ((0, data.ops[0]), (1, data.ops[1])):
        made = sum(lot.twin_outputs[side][2] for lot in lots)
        recorded = sum(o["qty"] for lot in lots for o in lot.output_milestones
                       if o["op_id"] == op.id)
        demand = sum(o["qty"] for lot in lots for o in lot.output_milestones
                     if o["op_id"] == op.id and not o.get("is_economic_surplus")
                     and not o.get("is_coproduced_surplus"))
        assert made == recorded  # every piece belongs to one output
        assert demand == sum(op.d)  # each delivery covered exactly once
    for lot in lots:
        assert lot.qty % 3000 == 0  # eco lot HARD
        for _op_id, _sku, qty in lot.twin_outputs:
            assert qty == lot.qty  # equal pieces of each side per cycle


def test_twin_time_is_one_execution():
    # B is twice as slow: the cycle takes B's time, never the sum.
    (lot,) = create_lots(_data({14: 1000}, {15: 2500}, b_ph=750), CONFIG)
    assert lot.prod_min == pytest.approx(3000 / 750 * 60)


# ── release curve and portions ───────────────────────────────────────────


def test_release_curve_is_the_larger_side_with_the_pair_at_min_r():
    (lot,) = create_lots(_carry_forward(), CONFIG)
    assert released_quantity(lot, 6) == 0
    # Day 7 (pair R): A 1000, B 2500 -> 2500 cycles (A's extra 1500 co-produced).
    assert released_quantity(lot, 7) == 2500
    assert released_quantity(lot, 20) == 2500
    assert released_quantity(lot, 21) == 3000  # A's day-28 delivery and surplus
    portions = material_portions(lot)
    assert [(p.qty, p.material_release_day) for p in portions] == [(2500, 7), (500, 21)]
    first, second = portions
    assert sorted((o["op_id"], o["qty"]) for o in first.outputs) == [
        (A_ID, 1000), (A_ID, 1500), (B_ID, 2500),
    ]
    assert sorted((o["op_id"], o["qty"]) for o in second.outputs) == [
        (A_ID, 500), (B_ID, 100), (B_ID, 400),
    ]
    assert has_quantity_releases([lot])


def test_twin_released_at_once_stays_one_portion():
    (lot,) = create_lots(_data({14: 1000}, {15: 2500}), CONFIG)
    assert [(p.qty, p.material_release_day) for p in material_portions(lot)] == [(3000, 7)]
    assert not has_quantity_releases([lot])


# ── the plan respects every delivery's window ────────────────────────────


def test_no_twin_piece_before_its_own_delivery_release():
    data = _carry_forward()
    result = schedule_all(data, config=CONFIG)
    assert oracle_window_violations(result.segments, result.lots, data) == []
    (lot,) = result.lots
    segments = sorted((s for s in result.segments if s.lot_id == lot.id),
                      key=lambda s: (s.day_idx, s.start_min))
    by_day = {}
    for segment in segments:
        by_day[segment.day_idx] = by_day.get(segment.day_idx, 0) + segment.qty
    assert min(by_day) >= 7
    assert sum(q for day, q in by_day.items() if day < 21) == 2500
    assert sum(by_day.values()) == 3000
    # One execution: the productive minutes are the lot's, split by cycles.
    assert sum(s.prod_min for s in segments) == pytest.approx(lot.prod_min)
    for segment in segments:
        assert [q for *_side, q in segment.twin_outputs] == [segment.qty, segment.qty]
    assert not source_contract_violations(result.segments, result.lots, data, CONFIG,
                                          require_current_material=True)


def test_oracle_flags_the_whole_cycle_made_at_the_pair_release():
    data = _carry_forward()
    (lot,) = create_lots(data, CONFIG)
    whole = [_segment(lot, 7, 420, 570, 3000, setup=30)]
    violations = oracle_window_violations(whole, [lot], data)
    assert [(v.day, v.produced, v.allowed) for v in violations] == [(7, 3000, 2500)]
    contract = source_contract_violations(whole, [lot], data, CONFIG)
    assert [item["field"] for item in contract] == ["material_quantity"]


def _segment(lot, day, start, end, qty, *, setup=0, run="R"):
    return Segment(
        lot_id=lot.id, run_id=run, machine_id="M1", tool_id="TT", day_idx=day,
        start_min=start, end_min=end, shift="A" if end <= 930 else "B", qty=qty,
        prod_min=float(end - start - setup), setup_min=float(setup), edd=lot.edd, sku=lot.sku,
        twin_outputs=[(op_id, sku, qty) for op_id, sku, _qty in lot.twin_outputs],
        lot_qty=lot.qty, output_milestones=lot.output_milestones,
    )


# ── surplus and co-produced stock never release early (review of B2) ─────


def _surplus_on_the_paired_side():
    """A: 1000 (day 10), 2000 (day 20), 8000 (day 25). B: 600 (day 15).

    One cycle of 12000 (eco lot) formed by A day 10 and B day 15 (R 3 and 8).
    B's 11400 extra pieces are surplus after its paired delivery: they take
    that delivery's own R (8), never the cycle R (3).
    """

    return _data({10: 1000, 20: 2000, 25: 8000}, {15: 600}, eco_lot=12000)


def test_surplus_takes_its_own_delivery_r_not_the_cycle_r():
    data = _surplus_on_the_paired_side()
    (lot,) = create_lots(data, CONFIG)
    assert _outputs(lot, B_ID) == [(15, 600, 8, 3, False), (15, 11400, 8, None, True)]
    assert _outputs(lot, A_ID)[0] == (10, 1000, 3, 3, False)
    # Day 3: only the pair (A 1000, B 600). Day 8: B's surplus (12000 pieces).
    assert [released_quantity(lot, day) for day in (2, 3, 7, 8)] == [0, 1000, 1000, 12000]
    assert [(p.qty, p.material_release_day) for p in material_portions(lot)] == [
        (1000, 3), (11000, 8),
    ]
    whole = [_segment(lot, 3, 420, 930, 12000, setup=30)]
    assert [(v.day, v.produced, v.allowed) for v in oracle_window_violations(
        whole, [lot], data)] == [(3, 12000, 1000)]
    result = schedule_all(data, config=CONFIG)
    assert oracle_window_violations(result.segments, result.lots, data) == []
    assert not source_contract_violations(result.segments, result.lots, data, CONFIG,
                                          require_current_material=True)


def test_oracle_does_not_trust_a_cycle_r_written_on_the_surplus():
    data = _surplus_on_the_paired_side()
    (lot,) = create_lots(data, CONFIG)
    forged = copy.deepcopy(lot)
    for output in forged.output_milestones:
        if output.get("is_economic_surplus"):
            output["cycle_material_release_day"] = 3  # the defect B2 review found
    whole = [_segment(forged, 3, 420, 930, 12000, setup=30)]
    assert [(v.day, v.allowed) for v in oracle_window_violations(whole, [forged], data)] == [
        (3, 1000),
    ]


def test_oracle_ignores_a_cycle_pair_claim():
    data = _carry_forward()
    (lot,) = create_lots(data, CONFIG)
    forged = copy.deepcopy(lot)
    # A's day-28 delivery claims the pair: the oracle never reads the claim.
    # It rebuilds the pair itself (A day 14, B day 15: R 7) and still allows
    # only 2500 cycles on day 7.
    for output in forged.output_milestones:
        if output["op_id"] == A_ID and output["customer_delivery_day"] == 28:
            output["cycle_material_release_day"] = 7
    segments = [_segment(forged, 7, 420, 550, 3000, setup=30)]
    assert [(v.day, v.produced, v.allowed)
            for v in oracle_window_violations(segments, [forged], data)] == [(7, 3000, 2500)]


def _relabel(lot, op_id, day, **fields):
    forged = copy.deepcopy(lot)
    for output in forged.output_milestones:
        if output["op_id"] == op_id and output["customer_delivery_day"] == day \
                and not output.get("is_economic_surplus"):
            output.update(fields)
    return forged


@pytest.mark.parametrize("forge", [
    # A's day-28 delivery flagged as surplus (it would take A day 14's R).
    lambda lot: _relabel(lot, A_ID, 28, is_economic_surplus=True),
    # A's day-28 delivery moved to customer day 14.
    lambda lot: _relabel(lot, A_ID, 28, customer_delivery_day=14),
    # Its quantity moved onto the day-14 delivery.
    lambda lot: _relabel(_relabel(lot, A_ID, 28, qty=0), A_ID, 14, qty=2500),
    # Every output marked co-produced, every release day rewritten.
    lambda lot: _relabel(_relabel(
        _relabel(_relabel(lot, A_ID, 28, material_release_day=0, is_coproduced_surplus=True),
                 A_ID, 14, material_release_day=0),
        B_ID, 15, material_release_day=0), B_ID, 30, material_release_day=0),
])
def test_relabelling_the_lot_never_hides_a_window_violation(forge):
    """Review of B2 (probe_oracle): the coverage of each side is rebuilt from
    the ISOP demand and the pieces each side makes, never from the lot's own
    delivery, surplus or quantity labels."""

    data = _carry_forward()
    (lot,) = create_lots(data, CONFIG)
    whole = [_segment(lot, 7, 420, 570, 3000, setup=30)]
    honest = [(v.day, v.produced, v.allowed)
              for v in oracle_window_violations(whole, [lot], data)]
    assert honest == [(7, 3000, 2500)]
    forged = forge(lot)
    assert [(v.day, v.produced, v.allowed)
            for v in oracle_window_violations(whole, [forged], data)] == honest


def test_oracle_coverage_counts_earlier_lots_of_the_operation():
    """Two cycles of side A: the second one covers what the first leaves."""

    data = _data({14: 3000, 16: 1000, 28: 2000}, {15: 3000}, eco_lot=3000)
    lots = create_lots(data, CONFIG)
    coverage = oracle_coverage(lots, data)
    assert [coverage[lot.id][A_ID] for lot in lots] == [[(14, 3000)], [(16, 1000), (28, 2000)]]
    later = lots[1]
    # Alone, the second cycle would look like it covers A's day 14.
    assert oracle_lot_releases(later, data)[0][2] == 7
    # B's only delivery is covered by the first cycle: here B is co-produced
    # stock and never drives the release.
    assert coverage[later.id][B_ID] == [(None, 3000)]
    assert oracle_lot_releases(later, data, lots=lots) == [(A_ID, 1000, 9), (A_ID, 2000, 21)]


def test_oracle_lot_order_breaks_ties_on_the_lot_index_as_a_number():
    """``…_10`` comes after ``…_9`` (review B3 finding 4), and a duplicate
    twin id (``…_3_12``) after its first cycle (``…_3``)."""

    data = _data({14: 3000}, {15: 3000})
    (lot,) = create_lots(data, CONFIG)
    named = [
        dataclasses.replace(lot, id=name)
        for name in ("LOT_TWIN_T_10", "LOT_TWIN_T_9", "LOT_TWIN_T_3_12", "LOT_TWIN_T_3")
    ]
    assert [item.id for item in oracle_lot_order(named, data)] == [
        "LOT_TWIN_T_3", "LOT_TWIN_T_3_12", "LOT_TWIN_T_9", "LOT_TWIN_T_10",
    ]


def test_oracle_lot_order_never_follows_the_list_order():
    data = _data({14: 3000, 16: 1000, 28: 2000}, {15: 3000}, eco_lot=3000)
    lots = create_lots(data, CONFIG)
    assert [lot.id for lot in oracle_lot_order(lots[::-1], data)] == [lot.id for lot in lots]
    assert oracle_coverage(lots[::-1], data) == oracle_coverage(lots, data)


def test_co_produced_stock_never_drives_the_release():
    """A: 1000 (day 10), 1000 (day 24), 500 (day 30). B: no demand.

    B's 3000 pieces are co-produced stock; the cycle follows A's deliveries
    (R 3, 17 and 23), never all at the first one.
    """

    data = _data({10: 1000, 24: 1000, 30: 500}, {})
    (lot,) = create_lots(data, CONFIG)
    (coproduced,) = [o for o in lot.output_milestones if o["op_id"] == B_ID]
    assert coproduced["is_coproduced_surplus"] and coproduced["qty"] == 3000
    assert [released_quantity(lot, day) for day in (3, 16, 17, 22, 23)] == [
        1000, 1000, 2000, 2000, 3000,
    ]
    assert [(p.qty, p.material_release_day) for p in material_portions(lot)] == [
        (1000, 3), (1000, 17), (1000, 23),
    ]
    whole = [_segment(lot, 3, 420, 570, 3000, setup=30)]
    assert [(v.day, v.produced, v.allowed) for v in oracle_window_violations(
        whole, [lot], data)] == [(3, 3000, 1000)]
    assert [item["field"] for item in source_contract_violations(whole, [lot], data, CONFIG)] \
        == ["material_quantity"]
    result = schedule_all(data, config=CONFIG)
    assert oracle_window_violations(result.segments, result.lots, data) == []
    assert not source_contract_violations(result.segments, result.lots, data, CONFIG,
                                          require_current_material=True)


def test_reinserted_twin_tranche_starts_when_the_curve_reaches_it():
    """A tranche moved by the alternative repair keeps the lot's release curve:
    its first cycle is released when the curve passes the cycles made before
    it, not on the earliest date of its slices (here the co-produced side)."""

    from backend.scheduler.alternative_repair import _resolve_runs

    data = _data({10: 1000, 24: 1000, 30: 500}, {})
    (lot,) = create_lots(data, CONFIG)
    segments = [
        _segment(lot, 3, 420, 490, 1000, setup=30, run="R0"),
        _segment(lot, 17, 420, 490, 1000, setup=30, run="R1"),
        _segment(lot, 23, 420, 490, 1000, setup=30, run="R2"),
    ]
    runs = _resolve_runs(segments, [lot], None)
    assert [runs[run].lots[0].material_release_day for run in ("R0", "R1", "R2")] == [
        3, 17, 23,
    ]


def test_manual_move_allocation_of_a_twin_follows_its_release_curve():
    """Review of B2: the allocator of manual moves used to send a twin cycle
    with a release curve to the contiguous model with one release day, and
    made all 3000 cycles on day 7 (the curve allows 2500 until day 21)."""

    from backend.plans.manual_move import _allocate_existing_lots

    data = _carry_forward()
    lots = schedule_all(copy.deepcopy(data), CONFIG).lots
    (lot,) = [lot for lot in lots if lot.is_twin]
    assert has_quantity_releases([lot])
    result = _allocate_existing_lots(
        copy.deepcopy(data), source_lots=copy.deepcopy(lots), config=CONFIG, time_budget_s=10,
    )
    assert result is not None
    made = [s for s in result.segments if s.lot_id == lot.id and s.qty > 0]
    assert sum(s.qty for s in made) == lot.qty
    for day in range(N_DAYS):
        cycles = sum(s.qty for s in made if s.day_idx <= day)
        assert cycles <= released_quantity(lot, day), (day, cycles)
    assert source_contract_violations(result.segments, result.lots, data, CONFIG) == []
    assert oracle_window_violations(result.segments, result.lots, data) == []


# ── real data (private fixtures; skipped when absent) ────────────────────

_PRIVATE = Path(__file__).parent / "fixtures" / "private"


def _fixture(name):
    path = _PRIVATE / f"{name}.json.gz"
    if not path.exists():
        pytest.skip(f"private fixture {path.name} absent")
    from backend.plans.serialize import deserialize_snapshot

    restored = deserialize_snapshot(json.loads(gzip.decompress(path.read_bytes())))
    return restored["engine_data"], restored["config"]


def _curve(lot, n_days):
    return [(day, released_quantity(lot, day)) for day in range(n_days)
            if released_quantity(lot, day) != released_quantity(lot, day - 1)]


@pytest.mark.parametrize(("name", "lot_id", "curve"), [
    # Surplus of the paired side (10267 pieces, own R 63) used to be
    # released at the cycle R 56: 10880 cycles on day 56.
    ("rev121", "LOT_TWIN_BFP083_66", [(56, 2066), (63, 10880)]),
    # Co-produced side (4800 pieces dated R 61) used to release every
    # cycle on day 61.
    ("rev90", "LOT_TWIN_BFP162_68", [(61, 669), (64, 1149), (70, 4800)]),
])
def test_real_twin_cycles_follow_each_delivery_release(name, lot_id, curve):
    data, config = _fixture(name)
    lots = create_lots(data, config)
    lot = next(lot for lot in lots if lot.id == lot_id)
    assert _curve(lot, data.n_days) == curve
    assert not [o for o in lot.output_milestones
                if o.get("is_economic_surplus") and "cycle_material_release_day" in o]
    # Never more than the oracle's independent curve, for every twin cycle.
    calendar = WorkCalendar(data)
    for twin in (lot for lot in lots if lot.is_twin):
        releases = oracle_lot_releases(twin, data, calendar, lots)
        for day in range(data.n_days):
            assert released_quantity(twin, day) <= _oracle_released(twin, releases, day), (
                twin.id, day)
    result = schedule_all(copy.deepcopy(data), config=config)
    assert oracle_window_violations(result.segments, result.lots, data) == []


def _creation_order(data, config, version, monkeypatch):
    """Lots in the order ``create_lots`` makes them, and the lots it returns."""
    import backend.scheduler.lot_sizing as lot_sizing

    made = []
    original = lot_sizing.Lot

    def record(*args, **kwargs):
        made.append(original(*args, **kwargs))
        return made[-1]

    monkeypatch.setattr(lot_sizing, "Lot", record)
    lots = create_lots(data, config, quantity_material=version)
    assert {lot.id for lot in made} == {lot.id for lot in lots}
    return made, lots


def _sides(lot):
    if lot.is_twin and lot.twin_outputs:
        return [str(op_id) for op_id, _sku, _qty in lot.twin_outputs]
    return [str(lot.op_id)]


@pytest.mark.parametrize("version", [True, 1, 0])
@pytest.mark.parametrize("name", ["rev82", "rev85", "rev87", "rev90", "rev121"])
def test_oracle_lot_order_is_the_lot_sizing_order_on_every_side(name, version, monkeypatch):
    """Each side of each operation consumes its deliveries in creation order;
    the oracle rebuilds exactly that order from a shuffled list."""

    data, config = _fixture(name)
    made, lots = _creation_order(data, config, version, monkeypatch)
    shuffled = lots[1::2] + lots[::2]
    ordered = oracle_lot_order(shuffled, data)
    for side in {side for lot in made for side in _sides(lot)}:
        truth = [lot.id for lot in made if side in _sides(lot)]
        assert [lot.id for lot in ordered if side in _sides(lot)] == truth, side
    if version is True:
        # And it rebuilds the coverage lot sizing recorded, lot by lot.
        coverage = oracle_coverage(shuffled, data)
        for lot in lots:
            recorded: dict[str, list] = {}
            for output in lot.output_milestones:
                surplus = output.get("is_economic_surplus") or output.get("is_coproduced_surplus")
                recorded.setdefault(str(output["op_id"]), []).append(
                    (None if surplus else int(output["customer_delivery_day"]), int(output["qty"]))
                )
            assert coverage[lot.id] == recorded, lot.id


def test_rev90_released_twin_portion_fills_a_retained_gap_to_save_its_deliveries():
    """Regression (B2 review): the corrected BFP162 curve has a step on day
    70, so its tool stays retained over the idle PRM031 days 64-69. The
    released BFP079 portion (day-71 FAURECIA deliveries) must take that gap:
    the dependent portion only loses minutes, no delivery gets later, and the
    inserted lot saves its deliveries (AGENTS §2, "Ferramenta retida")."""

    data, config = _fixture("rev90")
    result = schedule_all(copy.deepcopy(data), config=copy.deepcopy(config))
    records = [
        record for record in delivery_readiness(result.lots, result.segments, data)
        if record.is_demand and record.customer_delivery_day == 71
        and record.sku in {"1064169X100", "1064186X100", "1694825X040"}
    ]
    assert {record.sku for record in records} == {"1064169X100", "1064186X100", "1694825X040"}
    late = [(r.lot_id, r.sku, r.factory_day, r.production_due_day)
            for r in records if r.factory_day > r.production_due_day]
    assert late == []


# ── readiness per side and views that agree ──────────────────────────────


def test_readiness_is_per_side_and_per_delivery():
    data = _carry_forward()
    (lot,) = create_lots(data, CONFIG)
    segments = [_segment(lot, 7, 420, 550, 2500, setup=30), _segment(lot, 21, 420, 440, 500)]
    records = delivery_readiness([lot], segments, data)
    ready = [(r.op_id, r.customer_delivery_day, r.qty, r.factory_day, r.is_demand)
             for r in records]
    assert sorted(ready) == sorted([
        (A_ID, 14, 1000, 7, True), (A_ID, 28, 1500, 7, True), (A_ID, 28, 500, 21, False),
        (B_ID, 15, 2500, 7, True), (B_ID, 30, 400, 21, True), (B_ID, 30, 100, 21, False),
    ])
    assert not any(r.cycle_rule for r in records)


def test_views_agree_with_the_oracle_for_twins():
    data = _carry_forward()
    (lot,) = create_lots(data, CONFIG)
    # B's day-30 delivery slips to day 31 (late); every other one is on time.
    segments = [_segment(lot, 7, 420, 550, 2500, setup=30), _segment(lot, 31, 420, 440, 500)]
    oracle = oracle_orders(segments, [lot], data)
    assert [(o.sku, o.due_day, o.ready_day) for o in oracle] == [
        ("A", 14, 7), ("A", 28, 7), ("B", 15, 7), ("B", 30, 31),
    ]
    orders = {(o.sku, o.delivery_day): o for c in compute_order_tracking(segments, [lot], data)
              for o in c.orders}
    for expected in oracle:
        order = orders[(expected.sku, expected.due_day)]
        assert order.customer_ready_day == expected.ready_day
        assert (order.status == "ready") == (not expected.late)
    score = compute_score(segments, [lot], data, CONFIG, include_operational_audit=False)
    assert score["otd_d_failures"] == oracle_otd_d_failures(segments, [lot], data) == 1
    assert {p.op_id: p.stockout_day for p in compute_stock_projections(segments, [lot], data)} \
        == oracle_first_rupture(segments, [lot], data)
    tooltip = sorted(
        (index, item["sku"], item["delivery_day"], item["qty"])
        for index, trace in enumerate(compute_segment_deliveries(segments, [lot], data))
        for item in trace["delivery_allocations"] or [])
    assert tooltip == sorted(
        (index, o.sku, o.due_day, qty) for o in oracle for index, qty in o.allocations)


# ── legacy plans (material version 1) are rebuilt ────────────────────────


def _legacy_scenario():
    solo = EOp(
        id="TS_M1_S", sku="S", client="CLIENTE", designation="S", m="M1", t="TS", pH=PH,
        sH=0.5, operators=1, eco_lot=0, alt=None, stk=0, backlog=0,
        d=[0] * 25 + [600] + [0] * (N_DAYS - 26), oee=1.0, wip=0,
    )
    return _data({14: 1000, 28: 1500}, {15: 2500, 30: 400}, extra_ops=(solo,))


def _payload(data, segments, lots):
    score = compute_score(segments, lots, data, config=CONFIG, include_operational_audit=False)
    result = ScheduleResult(segments=segments, lots=lots, score=score, time_ms=0.0,
                            warnings=[], operator_alerts=[])
    return serialize_result_snapshot(
        data, CONFIG, result, plan_revision=9,
        dataset_info={"id": "isop-twin", "filename": "isop.xlsx"},
    )


def test_version_1_plan_with_the_whole_cycle_is_rebuilt_not_rejected(tmp_path):
    data = _legacy_scenario()
    lots = create_lots(data, CONFIG, quantity_material=1)
    twin = next(lot for lot in lots if lot.is_twin)
    solo = next(lot for lot in lots if not lot.is_twin)
    # Version 1: twin outputs carry no version and the cycle is released whole.
    assert not any(o.get("quantity_material_version") for o in twin.output_milestones)
    assert released_quantity(twin, 7) == 3000
    segments = [
        _segment(twin, 7, 420, 570, 3000, setup=30),
        Segment(lot_id=solo.id, run_id="RS", machine_id="M1", tool_id="TS", day_idx=22,
                start_min=420, end_min=474, shift="A", qty=600, prod_min=24.0,
                setup_min=30.0, edd=solo.edd, sku="S", lot_qty=600,
                output_milestones=solo.output_milestones),
    ]
    # Readable under its recorded model ...
    assert not source_contract_violations(segments, lots, data, CONFIG)
    # ... but its twin pieces for later deliveries break the current windows.
    assert legacy_material_plan(lots, data, CONFIG)
    with pytest.raises(LegacyMaterialPlanError) as caught:
        _assert_activatable_payload(_payload(data, segments, lots))
    # Version 1 already released single parts per delivery: only twins changed.
    assert "peças gémeas" in str(caught.value)

    rebuilt = schedule_all(data, config=CONFIG)
    assert not legacy_material_plan(rebuilt.lots, data, CONFIG)
    store = PlansStore(str(tmp_path / "plans.db"))
    try:
        payload = _payload(data, rebuilt.segments, rebuilt.lots)
        saved = store.save(name="Reconstruído", source="user", origin="isop.xlsx", note="",
                           payload=payload, score=payload["score"], gate_report=None,
                           is_auto=False, activate=True)
        assert store.active()["id"] == saved["id"]
    finally:
        store.close()


def test_version_1_plan_without_twin_carry_forward_is_not_legacy():
    data = _data({14: 3000}, {15: 3000})
    lots = create_lots(data, CONFIG, quantity_material=1)
    assert not legacy_material_plan(copy.deepcopy(lots), data, CONFIG)
