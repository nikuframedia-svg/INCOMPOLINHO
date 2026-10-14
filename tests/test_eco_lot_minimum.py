"""Economic lot = minimum, never multiples (Luís, 14/10/2026, material version 4).

«Produz-se pelo menos o lote económico; se a necessidade é maior, produz-se
essa quantidade, nunca o dobro do lote económico.» A lot is
``max(economic lot, need)``, need being the shortfall of the delivery that
opens it (after stock and the surplus of the lot before). Until 14/10 the
need was rounded up to a multiple of the economic lot (material versions
0-3): such a plan stays readable under its own rule, a replan keeps its
started lots as they are (rule 4) and «Recalcular plano» sizes it again.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from backend.api.data import stored_plan_needs_rebuild
from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler import lot_sizing
from backend.scheduler.canonical import result_validation_data, source_contract_violations
from backend.scheduler.lot_sizing import (
    MINIMUM_ECO_LOT_VERSION,
    WHOLE_LOT_MATERIAL_VERSION,
    create_lots,
    older_sizing_lots,
)
from backend.scheduler.material_quantities import lot_material_version
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.validation import demand_coverage_metrics, validate_plan
from backend.types import TwinGroup
from tests.test_material_quantity_windows import scenario

CONFIG = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})

# Sources where a per-SKU rule, not the economic lot, sets a larger quantity.
_CAMPAIGN_SOURCES = {"campaign_window", "min_campaign_qty", "min_campaign_prod_min"}


def assert_minimum_sizing(lots, data) -> None:
    """Every lot of the current sizing is ``max(eco, need)``, never more.

    A lot below its economic lot does not exist; a lot above it was sized to
    the need of its first delivery, so no economic surplus is left (twins:
    the side that asked for the cycle quantity has none).
    """
    eco = {op.id: int(op.eco_lot or 0) for op in data.ops}
    for lot in lots:
        if lot_material_version(lot) < MINIMUM_ECO_LOT_VERSION:
            continue
        if lot.planning_source in _CAMPAIGN_SOURCES:
            continue
        sides = lot.twin_outputs or [(lot.op_id, lot.sku, lot.qty)]
        floor = max(eco.get(str(op_id), 0) for op_id, _sku, _qty in sides)
        if not floor:
            continue
        assert lot.qty >= floor, (lot.id, lot.qty, floor)
        if lot.qty == floor:
            continue
        surplus_by_side = {
            str(op_id): sum(
                int(o["qty"]) for o in lot.output_milestones
                if o.get("op_id") == op_id
                and (o.get("is_economic_surplus") or o.get("is_coproduced_surplus"))
            )
            for op_id, _sku, _qty in sides
        }
        assert min(surplus_by_side.values()) == 0, (lot.id, lot.qty, surplus_by_side)


def assert_replan_sizes(
    before_payload, after_payload, freeze_day: int, now_min: int = 0,
) -> None:
    """A replan of a rounded plan (material versions 1-3): every lot that had
    started before ``(freeze_day, now_min)`` keeps its size (rule 4); the
    rest is sized under the current rule (``assert_minimum_sizing``)."""
    from backend.plans.serialize import deserialize_snapshot

    started = {
        segment["lot_id"] for segment in before_payload["segments"]
        if (segment["day_idx"], segment["start_min"]) < (freeze_day, now_min)
        and segment["end_min"] > segment["start_min"]
    }
    before = {lot["id"]: lot["qty"] for lot in before_payload["lots"]}
    after = {lot["id"]: lot["qty"] for lot in after_payload["lots"]}
    assert started
    assert {lot_id: after.get(lot_id) for lot_id in started} == {
        lot_id: before[lot_id] for lot_id in started
    }
    restored = deserialize_snapshot(copy.deepcopy(after_payload))
    lots = restored["result"].lots
    assert {lot_material_version(lot) for lot in lots if lot.id in started} == {3}
    assert_minimum_sizing([lot for lot in lots if lot.id not in started], restored["engine_data"])


def _single(demand: dict[int, int], eco_lot: int = 1000):
    data = scenario()
    days = [0] * data.n_days
    for day, qty in demand.items():
        days[day] = qty
    data.ops[0] = replace(data.ops[0], d=days, eco_lot=eco_lot)
    return data


def test_a_need_below_the_economic_lot_makes_the_economic_lot():
    (lot,) = create_lots(_single({13: 400}))
    assert lot.qty == 1000
    assert [(o["qty"], bool(o.get("is_economic_surplus"))) for o in lot.output_milestones] == [
        (400, False), (600, True),
    ]
    assert lot.planning_source == "eco_lot"


def test_a_need_above_the_economic_lot_is_made_as_it_is_never_a_multiple():
    """JTE001 shape: 27 641 with a lot of 23 040 makes 27 641, not 46 080."""
    (lot,) = create_lots(_single({13: 27641}, eco_lot=23040))
    assert lot.qty == 27641
    assert lot.planning_source == "exact_shortfall"
    assert not any(o.get("is_economic_surplus") for o in lot.output_milestones)
    (old,) = create_lots(_single({13: 27641}, eco_lot=23040), quantity_material=3)
    assert old.qty == 46080


def test_eco_plus_fifty_leaves_no_surplus_and_the_next_delivery_opens_a_lot():
    data = _single({13: 1050, 16: 300})
    lots = create_lots(data)
    assert [(lot.qty, lot.customer_delivery_day) for lot in lots] == [(1050, 13), (1000, 16)]
    assert not any(o.get("is_economic_surplus") for o in lots[0].output_milestones)
    assert {lot_material_version(lot) for lot in lots} == {MINIMUM_ECO_LOT_VERSION}
    assert_minimum_sizing(lots, data)
    # Rounded (version 3): one lot of 2 000 covered both deliveries.
    assert [lot.qty for lot in create_lots(data, quantity_material=3)] == [2000]


def test_carry_forward_still_covers_the_next_deliveries_below_the_lot():
    lots = create_lots(_single({13: 400, 16: 300, 19: 500}))
    assert [(lot.qty, lot.customer_delivery_day) for lot in lots] == [(1000, 13), (1000, 19)]


def _twins(need_a: int, need_b: int, eco_lot: int = 1000):
    data = scenario()
    base = data.ops[0]
    a = [0] * data.n_days
    b = [0] * data.n_days
    a[13], b[13] = need_a, need_b
    data.ops = [
        replace(base, id="TOOL_MACHINE_A", sku="A", d=a, eco_lot=eco_lot),
        replace(base, id="TOOL_MACHINE_B", sku="B", d=b, eco_lot=eco_lot),
    ]
    data.twin_groups = [TwinGroup(
        op_id_1="TOOL_MACHINE_A", op_id_2="TOOL_MACHINE_B", sku_1="A", sku_2="B",
        machine_id="MACHINE", tool_id="TOOL", eco_lot_1=eco_lot, eco_lot_2=eco_lot,
    )]
    return data


def test_twins_with_different_needs_run_the_larger_need_unrounded():
    data = _twins(1500, 800)
    (lot,) = create_lots(data)
    assert lot.is_twin and lot.qty == 1500
    assert sorted(lot.twin_outputs) == [("TOOL_MACHINE_A", "A", 1500), ("TOOL_MACHINE_B", "B", 1500)]
    surplus = {
        o["op_id"]: o["qty"] for o in lot.output_milestones if o.get("is_economic_surplus")
    }
    assert surplus == {"TOOL_MACHINE_B": 700}
    assert_minimum_sizing([lot], data)
    (old,) = create_lots(data, quantity_material=3)
    assert old.qty == 2000


def test_twins_below_the_lot_run_the_economic_lot():
    (lot,) = create_lots(_twins(300, 800))
    assert lot.qty == 1000


def _rounded_baseline(monkeypatch, data):
    """A plan made before 14/10/2026: lots rounded to eco-lot multiples."""
    with monkeypatch.context() as patch:
        patch.setattr(lot_sizing, "QUANTITY_MATERIAL_VERSION", WHOLE_LOT_MATERIAL_VERSION)
        baseline = schedule_all(copy.deepcopy(data), config=CONFIG)
    assert {lot_material_version(lot) for lot in baseline.lots} == {3}
    return baseline


def test_a_rounded_plan_stays_valid_under_its_own_rule(monkeypatch):
    data = _single({13: 1500, 16: 400, 27: 1500})
    baseline = _rounded_baseline(monkeypatch, data)
    assert [lot.qty for lot in baseline.lots] == [2000, 2000]
    assert not validate_plan(baseline.segments, data, CONFIG, lots=baseline.lots)
    assert not source_contract_violations(
        baseline.segments, baseline.lots, data, CONFIG, require_current_material=True,
    )
    assert demand_coverage_metrics(data, baseline.lots, CONFIG)["source_overproduced_qty"] == 0


def test_a_rounded_plan_is_rebuilt_by_recalcular(monkeypatch):
    data = _single({13: 1500, 16: 400, 27: 1500})
    baseline = _rounded_baseline(monkeypatch, data)
    assert stored_plan_needs_rebuild(data, baseline.segments, baseline.lots, CONFIG)
    current = schedule_all(copy.deepcopy(data), config=CONFIG)
    assert [lot.qty for lot in current.lots] == [1500, 1000, 1000]
    assert not stored_plan_needs_rebuild(data, current.segments, current.lots, CONFIG)


def test_a_started_rounded_lot_keeps_its_size_and_is_not_overproduction(monkeypatch):
    """Rule 4 across the change: the lot of day 13 (2 000, rounded) has
    started; a replan keeps it whole and sizes only what it leaves
    uncovered under the current rule (1 400 for day 27, not 2 000)."""
    from backend.plans import frozen
    from tests.snapshot_fixture import pin_factory_clock

    data = _single({13: 1500, 16: 400, 27: 1500})
    baseline = _rounded_baseline(monkeypatch, data)
    first = min(baseline.lots, key=lambda lot: lot.customer_delivery_day)
    start_day = min(s.day_idx for s in baseline.segments if s.lot_id == first.id)
    planning_day = start_day + 1
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_a, **_k: planning_day)
    pin_factory_clock(monkeypatch, data.workdays[planning_day])
    changed = copy.deepcopy(data)
    changed.machine_blocked_days = {"MACHINE": {planning_day + 1}}

    result = frozen.optimize_preserving_started_lots(changed, CONFIG, baseline, mode="quick")

    sizes = {lot.id: (lot.qty, lot_material_version(lot)) for lot in result.lots}
    assert sizes[first.id] == (2000, 3)
    assert sorted(sizes.values()) == [(1400, 4), (2000, 3)]
    view = result_validation_data(changed, result)
    assert not validate_plan(result.segments, view, CONFIG, lots=result.lots)
    assert [lot.id for lot in older_sizing_lots(result.lots, view)] == [first.id]
    coverage = demand_coverage_metrics(view, result.lots, CONFIG)
    assert coverage["source_overproduced_qty"] == coverage["source_missing_qty"] == 0
    assert not source_contract_violations(result.segments, result.lots, view, CONFIG)
    # Without the credit the rounded lot would be read as 600 extra pieces.
    plain = copy.copy(view)
    plain.preserved_lot_proofs = {}
    assert demand_coverage_metrics(plain, result.lots, CONFIG)["source_overproduced_qty"] == 0
    # «Recalcular plano» sizes it again.
    assert stored_plan_needs_rebuild(view, result.segments, result.lots, CONFIG)


@pytest.mark.parametrize("version", [0, 1, 2, 3])
def test_every_older_version_rounded_to_multiples(version):
    data = _single({13: 1500})
    (lot,) = create_lots(data, quantity_material=version)
    assert lot.qty == 2000


def test_subcontract_dispatch_is_judged_once_per_delivery_whatever_the_lots():
    """A delivery served by two lots (rounded sizing) or by one (minimum)
    has one dispatch key: before 14/10 a portion missing from the other
    sizing read as a delivery that never leaves, and the no-loss comparator
    refused a better replan (revision 127, HAN002 deliveries 35, 42, 70)."""
    from backend.scheduler.improvement import subcontract_lateness
    from tests.test_subcontract_whole_lot import _delivery_of_two_lots

    data, lots, segments = _delivery_of_two_lots()
    lateness = subcontract_lateness(segments, lots, data)
    op_id = data.ops[0].id
    assert sorted(lateness) == [(op_id, 9, 0), (op_id, 16, 0)]
