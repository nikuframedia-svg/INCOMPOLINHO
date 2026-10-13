"""Economic lot = one production (material version 3, AGENTS §2, 13/10/2026).

The whole economic lot is released at the ``R`` of the first delivery it
serves (twin cycles: ``R_ciclo``); the other covered deliveries and the
surplus inherit it. A lot is produced in one production (one setup) and is
never split, unless an outage or block forces resuming it.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.canonical import legacy_material_plan, source_contract_violations
from backend.scheduler.lot_sizing import (
    QUANTITY_MATERIAL_VERSION,
    UPGRADED_MATERIAL_KEY,
    create_lots,
    redate_lot_outputs,
    upgrade_lot_material,
    upgrade_plan_material,
)
from backend.scheduler.material_quantities import (
    material_portions,
    next_release_day,
    released_quantity,
)
from backend.scheduler.quantity_dispatch import has_quantity_releases
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.validation import validate_plan
from tests.test_material_quantity_windows import scenario

CONFIG = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})


def _with_other_tool(day: int = 14, qty: int = 1000):
    data = scenario()
    demand = [0] * data.n_days
    demand[day] = qty
    data.ops.append(replace(
        data.ops[0], id="OTHER_MACHINE_OTHER", sku="OTHER", t="OTHER", d=demand, eco_lot=0,
    ))
    return data


def test_current_contract_is_version_3():
    assert QUANTITY_MATERIAL_VERSION == 3


def test_every_output_inherits_the_first_delivery_release():
    # BFP082 shape: 32 000 pieces cover the deliveries of days 13, 16, 19, 20.
    lot = create_lots(scenario())[0]
    assert lot.qty == 32000
    assert lot.material_release_day == 6
    assert [
        (o["qty"], o["customer_delivery_day"], o["material_release_day"],
         o["delivery_material_release_day"], o["quantity_material_version"])
        for o in lot.output_milestones
    ] == [
        (5680, 13, 6, 6, 3),
        (14400, 16, 6, 9, 3),
        (2400, 19, 6, 12, 3),
        (9520, 20, 6, 13, 3),
    ]


def test_the_whole_lot_is_released_at_the_lot_r_in_one_portion():
    lot = create_lots(scenario())[0]
    assert released_quantity(lot, 5) == 0
    assert released_quantity(lot, 6) == 32000
    assert next_release_day(lot, 0) == 6
    assert next_release_day(lot, 6) is None
    assert [(p.qty, p.material_release_day) for p in material_portions(lot)] == [(32000, 6)]
    # Always planned by the quantity builder, never by the old engine.
    assert has_quantity_releases([lot])


def test_the_economic_lot_is_one_production_from_its_release():
    result = schedule_all(scenario(), config=CONFIG)
    segments = [s for s in result.segments if s.qty > 0 or s.setup_min > 0]
    assert sum(s.qty for s in segments) == 32000
    assert min(s.day_idx for s in segments if s.qty > 0) == 6
    assert len({s.run_id for s in segments}) == 1
    assert sum(1 for s in segments if s.setup_min > 0) == 1
    assert not validate_plan(result.segments, scenario(), CONFIG, lots=result.lots)


def test_another_order_moves_the_whole_lot_never_splits_it():
    # Before 13/10 the OTHER tool (released on day 7) went between two
    # portions and the economic lot needed two setups.
    data = _with_other_tool()
    result = schedule_all(data, config=CONFIG)
    sku = sorted(
        (s for s in result.segments if s.sku == "SKU"), key=lambda s: (s.day_idx, s.start_min),
    )
    assert sum(s.qty for s in sku) == 32000
    assert sum(1 for s in sku if s.setup_min > 0) == 1
    first, last = (sku[0].day_idx, sku[0].start_min), (sku[-1].day_idx, sku[-1].end_min)
    assert not any(
        s.sku == "OTHER" and first < (s.day_idx, s.start_min) < last
        for s in result.segments
    )
    assert not validate_plan(result.segments, data, CONFIG, lots=result.lots)


def _urgent_case(*, alternative):
    """A: one economic lot of 6000 pieces (about 6 days) for days 13 and 30,
    released on day 6. U: 1500 pieces due on day 14, released on day 7.
    A run whole from its release would make U late (day 15)."""
    from tests.test_quantity_campaigns import _data, _op

    machines = ("M1", "M2") if alternative else ("M1",)
    return _data([
        _op("A", "TA", {13: 1000, 30: 5000}, eco_lot=6000, alt="M2" if alternative else None),
        _op("U", "TU", {14: 1500}),
    ], machines=machines), machines


def _one_production(result, lot_id):
    own = sorted((s for s in result.segments if s.lot_id == lot_id),
                 key=lambda s: (s.day_idx, s.start_min))
    first, last = (own[0].day_idx, own[0].start_min), (own[-1].day_idx, own[-1].end_min)
    interleaved = [
        s for s in result.segments
        if s.lot_id != lot_id and s.machine_id == own[0].machine_id
        and first < (s.day_idx, s.start_min) < last
    ]
    return (
        sum(1 for s in own if s.setup_min > 0) == 1
        and len({s.run_id for s in own}) == 1
        and len({s.machine_id for s in own}) == 1
        and not interleaved
    )


@pytest.mark.parametrize("alternative", [False, True])
def test_an_urgent_order_moves_the_whole_lot_never_splits_it(alternative):
    """Was (version 2): A's first delivery (1000) ran on day 6 as its own
    production, U on days 7-8, A's rest later (two setups of A). Now A is
    never split: the whole lot goes after U (one machine) or to the other
    machine; nobody is late, since capacity allows it."""
    from tests.test_quantity_campaigns import _config, _late

    data, machines = _urgent_case(alternative=alternative)
    config = _config(machines)
    result = schedule_all(data, config=config)
    assert not validate_plan(result.segments, data, config, lots=result.lots)
    lot_a = next(lot for lot in result.lots if lot.op_id == "A")
    assert _one_production(result, lot_a.id)
    assert min(s.day_idx for s in result.segments if s.lot_id == lot_a.id) >= 6
    assert _late(result, data) == {}
    a_machine = next(s.machine_id for s in result.segments if s.lot_id == lot_a.id)
    u_end = max((s.day_idx, s.end_min) for s in result.segments if s.sku == "U")
    if alternative:
        assert a_machine == "M2"  # moved to the other machine, from its release
        assert min(s.day_idx for s in result.segments if s.lot_id == lot_a.id) == 6
    else:
        a_start = min((s.day_idx, s.start_min) for s in result.segments if s.lot_id == lot_a.id)
        assert a_start >= u_end  # the whole lot moved later


def test_the_same_urgent_case_split_the_lot_under_the_per_delivery_contract(monkeypatch):
    from tests.test_quantity_campaigns import _config, _pin_contract

    _pin_contract(monkeypatch, 2)
    data, machines = _urgent_case(alternative=False)
    result = schedule_all(data, config=_config(machines))
    lot_a = next(lot for lot in result.lots if lot.op_id == "A")
    assert not _one_production(result, lot_a.id)
    assert sum(1 for s in result.segments if s.lot_id == lot_a.id and s.setup_min > 0) == 2


def test_validator_rejects_a_second_production_of_one_lot():
    from backend.scheduler.validation import lot_split_violations

    data = _with_other_tool()
    result = schedule_all(data, config=CONFIG)
    sku = sorted(
        (s for s in result.segments if s.sku == "SKU"), key=lambda s: (s.day_idx, s.start_min),
    )
    other = next(s for s in result.segments if s.sku == "OTHER" and s.qty > 0)
    # Interleaved: OTHER between two segments of the lot on the machine.
    ordered = {"MACHINE": [sku[0], other, *sku[1:]]}
    lots = {lot.id: lot for lot in result.lots}
    violations = lot_split_violations(ordered, lots, data, CONFIG)
    assert [item["kind"] for item in violations] == ["lot_split"]
    assert "uma só vez" in violations[0]["message"]
    # A remount after the lot produced is a second production too.
    remount = copy.deepcopy(sku)
    remount[-1].setup_min = 60.0
    assert lot_split_violations({"MACHINE": remount}, lots, data, CONFIG)


def test_an_outage_between_the_two_productions_allows_the_new_setup():
    from backend.scheduler.validation import lot_split_violations

    data = _with_other_tool()
    result = schedule_all(data, config=CONFIG)
    sku = sorted(
        (s for s in result.segments if s.sku == "SKU"), key=lambda s: (s.day_idx, s.start_min),
    )
    other = next(s for s in result.segments if s.sku == "OTHER" and s.qty > 0)
    lots = {lot.id: lot for lot in result.lots}
    ordered = {"MACHINE": [sku[0], other, *sku[1:]]}
    blocked = copy.deepcopy(data)
    blocked.machine_blocked_days = {"MACHINE": {sku[0].day_idx}}
    assert not lot_split_violations(ordered, lots, blocked, CONFIG)
    blocked = copy.deepcopy(data)
    blocked.tool_blocked_intervals = {"TOOL": [{
        "start_day": sku[1].day_idx, "start_min": 0, "end_min": sku[1].start_min,
    }]}
    assert not lot_split_violations(ordered, lots, blocked, CONFIG)


def test_only_history_before_the_minute_boundary_may_precede_another_lot():
    """The earlier part of a split is history only when it started before the
    plan's boundary, the factory minute of the calculation (rule 4,
    ``scheduler.history``), never the day of the wall clock."""
    from backend.scheduler.validation import lot_split_violations

    data = _with_other_tool()
    result = schedule_all(data, config=CONFIG)
    sku = sorted(
        (s for s in result.segments if s.sku == "SKU"), key=lambda s: (s.day_idx, s.start_min),
    )
    other = next(s for s in result.segments if s.sku == "OTHER" and s.qty > 0)
    lots = {lot.id: lot for lot in result.lots}
    ordered = {"MACHINE": [sku[0], other, *sku[1:]]}
    day, start = sku[0].day_idx, int(sku[0].start_min)
    # No boundary (fresh plan, «Recalcular plano» from D0): judged whole.
    assert lot_split_violations(ordered, lots, data, CONFIG)
    started = copy.deepcopy(data)
    # Started at the calculation's minute or before it: history.
    for boundary in ([day, start + 1], [day + 1, 0]):
        started.history_boundary = boundary
        assert not lot_split_violations(ordered, lots, started, CONFIG), boundary
    # Not yet started at the boundary (same day): a second production.
    started.history_boundary = [day, start]
    assert lot_split_violations(ordered, lots, started, CONFIG)


@pytest.mark.parametrize("started", [
    [(1, 420, 100, 30), (3, 420, 100, 0)],   # 07:00-08:30, done before 10:00
    [(1, 540, 150, 30), (3, 420, 50, 0)],    # 09:00-11:00, running at 10:00
], ids=["done-this-morning", "running-at-now"])
def test_rule_4_cut_of_a_lot_started_today_lets_an_urgent_order_in(started):
    """Rule 4 contiguity: free shift time cuts the run of a lot started
    today at 07:00 or 09:00 (its rest was on day 3, after a removed outage).
    At 10:00 an order due today takes the machine and the rest of the lot
    follows it. The started part is history before the minute boundary, so
    this is the rest of a started lot, not a second production; with the
    day-level clock the plan was refused as ``lot_split``."""
    from backend.plans import frozen
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.improvement import _segment_physical_row
    from backend.scheduler.validation import assert_plan_valid
    from tests.test_now_boundary import _at, _plan
    from tests.test_now_boundary import _config as boundary_config
    from tests.test_now_boundary import _data as boundary_data

    config = boundary_config()
    data = boundary_data(second_due=1)
    baseline, lots = _plan(data, config, {"OP1": started, "OP2": [(3, 480, 200, 30)]})
    assert not validate_plan(baseline.segments, data, config, lots=baseline.lots)
    now = _at(1, 600)

    result = frozen.optimize_preserving_started_lots(
        copy.deepcopy(data), config, baseline, mode="quick", now=now,
    )

    assert result.history_boundary == [1, 600]
    assert_plan_valid(
        result.segments, result_validation_data(data, result), config, lots=result.lots,
    )
    first = baseline.segments[0]
    assert _segment_physical_row(first) in {_segment_physical_row(s) for s in result.segments}
    ordered = sorted(result.segments, key=lambda s: (s.day_idx, s.start_min))
    assert [s.lot_id for s in ordered] == [lots["OP1"].id, lots["OP2"].id, lots["OP1"].id]
    assert ordered[1].day_idx == 1 and ordered[1].start_min >= 600
    assert sum(s.qty for s in ordered if s.lot_id == lots["OP1"].id) == lots["OP1"].qty


def test_lots_of_older_contracts_are_not_judged_as_split():
    from backend.scheduler.validation import lot_split_violations

    data = _with_other_tool()
    result = schedule_all(data, config=CONFIG)
    sku = sorted(
        (s for s in result.segments if s.sku == "SKU"), key=lambda s: (s.day_idx, s.start_min),
    )
    other = next(s for s in result.segments if s.sku == "OTHER" and s.qty > 0)
    ordered = {"MACHINE": [sku[0], other, *sku[1:]]}
    upgraded = copy.deepcopy(result.lots)
    for lot in upgraded:
        for output in lot.output_milestones:
            output[UPGRADED_MATERIAL_KEY] = 2
    assert not lot_split_violations(ordered, {lot.id: lot for lot in upgraded}, data, CONFIG)
    legacy = copy.deepcopy(result.lots)
    for lot in legacy:
        for output in lot.output_milestones:
            output["quantity_material_version"] = 2
    assert not lot_split_violations(ordered, {lot.id: lot for lot in legacy}, data, CONFIG)


def test_production_before_the_lot_release_is_still_refused():
    data = scenario()
    result = schedule_all(data, config=CONFIG)
    early = copy.deepcopy(result.segments)
    for segment in early:
        segment.day_idx -= 1
    violations = validate_plan(early, data, CONFIG, lots=result.lots)
    assert any(item["kind"] == "setup_before_material" for item in violations)


@pytest.mark.parametrize("version", [0, 1, 2])
def test_plans_of_older_contracts_are_valid_and_never_ask_to_recalculate(version):
    from backend.scheduler.types import Segment

    data = scenario()
    lot = create_lots(data, quantity_material=version)[0]
    segment = Segment(
        lot_id=lot.id, run_id="R", machine_id="MACHINE", tool_id="TOOL",
        day_idx=13, start_min=420, end_min=1430, shift="A", qty=32000,
        prod_min=lot.prod_min, setup_min=lot.setup_min,
    )
    assert not legacy_material_plan([lot], data, CONFIG)
    assert not source_contract_violations(
        [segment], [lot], data, CONFIG, require_current_material=True,
    )


def test_a_version_2_lot_is_taken_over_as_the_current_lot():
    data = scenario()
    old = create_lots(data, quantity_material=2)[0]
    current = create_lots(data)[0]
    upgraded = upgrade_lot_material(old, data)
    assert all(o[UPGRADED_MATERIAL_KEY] == 2 for o in upgraded.output_milestones)
    stripped = [
        {k: v for k, v in o.items() if k != UPGRADED_MATERIAL_KEY}
        for o in upgraded.output_milestones
    ]
    assert stripped == current.output_milestones
    assert upgraded.material_release_day == current.material_release_day == 6
    # The old lot is not changed; a plan is upgraded whole.
    assert old.output_milestones[1]["material_release_day"] == 9
    assert upgrade_plan_material([old], data)[0].output_milestones == upgraded.output_milestones
    # Version 0 lots and current lots stay as they are.
    v0 = create_lots(data, quantity_material=0)
    assert upgrade_plan_material(v0, data) is v0
    assert upgrade_plan_material([current], data)[0] is current


def test_a_new_holiday_redates_the_deliveries_and_the_lot_release():
    data = scenario()
    lot = create_lots(data)[0]
    holiday = copy.deepcopy(data)
    holiday.holidays = sorted({*data.holidays, 9})
    redated = redate_lot_outputs(lot, holiday)
    assert redated.output_milestones == create_lots(holiday)[0].output_milestones
    assert {o["material_release_day"] for o in redated.output_milestones} == {
        redated.material_release_day,
    }


def test_the_rest_of_an_interrupted_lot_keeps_the_lot_release():
    from backend.plans.frozen import _remainder_lot

    data = scenario()
    result = schedule_all(data, config=CONFIG)
    lot = result.lots[0]
    started = sorted(result.segments, key=lambda s: (s.day_idx, s.start_min))[:1]
    rest = _remainder_lot(lot, started, data, CONFIG)
    assert rest.qty == lot.qty - started[0].qty
    assert rest.material_release_day == lot.material_release_day == 6
    assert released_quantity(rest, 6) == rest.qty


def test_an_outage_interrupting_a_started_lot_resumes_it_with_one_setup(monkeypatch):
    """The lot started on day 6 and would end on day 7; the machine breaks
    down on day 7. The rest keeps the lot R (day 6, already released),
    resumes after the outage with exactly one new setup (OTHER, released on
    day 7 and more urgent, goes first), and the plan is valid: the outage
    in between exempts the new setup from the one-production check."""
    from backend.plans import frozen
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.validation import lot_split_violations

    data = _with_other_tool()
    baseline = schedule_all(copy.deepcopy(data), config=CONFIG)
    (lot,) = [lot for lot in baseline.lots if lot.sku == "SKU"]
    assert {s.day_idx for s in baseline.segments if s.lot_id == lot.id} == {6, 7}
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_args, **_kw: 7)
    outage = copy.deepcopy(data)
    outage.machine_blocked_days = {"MACHINE": {7}}

    result = frozen.optimize_preserving_started_lots(outage, CONFIG, baseline, mode="quick")

    view = result_validation_data(outage, result)
    assert not validate_plan(result.segments, view, CONFIG, lots=result.lots)
    own = sorted((s for s in result.segments if s.lot_id == lot.id),
                 key=lambda s: (s.day_idx, s.start_min))
    assert sum(s.qty for s in own) == 32000
    started = [s for s in own if s.day_idx == 6]
    rest = [s for s in own if s.day_idx > 6]
    assert [(s.start_min, s.qty) for s in started] == [
        (s.start_min, s.qty) for s in baseline.segments if s.lot_id == lot.id and s.day_idx == 6
    ]
    assert min(s.day_idx for s in rest) == 8
    assert sum(1 for s in own if s.setup_min > 0) == 2  # the original one and one more
    (planned,) = [item for item in result.lots if item.id == lot.id]
    assert planned.material_release_day == lot.material_release_day == 6
    assert {o["material_release_day"] for o in planned.output_milestones} == {6}
    ordered = {"MACHINE": sorted(result.segments, key=lambda s: (s.day_idx, s.start_min))}
    by_id = {item.id: item for item in result.lots}
    assert not lot_split_violations(ordered, by_id, outage, CONFIG)
    # Without the outage, seen before the lot started, the same two
    # productions would be a split.
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_args, **_kw: 0)
    assert lot_split_violations(ordered, by_id, data, CONFIG)


def _twin_data():
    from tests.test_twin_per_delivery import _carry_forward

    return _carry_forward()


def test_twin_cycle_is_released_whole_at_the_cycle_release():
    data = _twin_data()
    for lot in create_lots(data):
        if not lot.is_twin:
            continue
        paired = [
            o["delivery_material_release_day"] for o in lot.output_milestones
            if "cycle_material_release_day" in o
        ]
        assert paired
        cycle = min(paired)
        assert lot.material_release_day == cycle
        assert {o["material_release_day"] for o in lot.output_milestones} == {cycle}
        assert released_quantity(lot, cycle) == lot.qty
        assert released_quantity(lot, cycle - 1) == 0
        assert len(material_portions(lot)) == 1


@pytest.mark.needs_private
@pytest.mark.parametrize(("revision", "upgraded"), [("rev124", True), ("rev121", False)])
def test_real_older_plans_stay_valid_and_per_delivery_ones_upgrade(revision, upgraded):
    """rev124 is version 2: every lot is taken over as version 3. rev121 is
    version 1 with whole twin cycles (outputs of another shape): it stays as
    it is. Both stay valid under the current contract without «Recalcular»."""
    from backend.plans.serialize import deserialize_snapshot
    from tests.snapshot_fixture import load_payload

    _manifest, payload = load_payload(revision)
    restored = deserialize_snapshot(copy.deepcopy(payload))
    data, config, result = restored["engine_data"], restored["config"], restored["result"]
    lots = upgrade_plan_material(result.lots, data)
    assert (lots is not result.lots) == upgraded
    if upgraded:
        assert all(
            o["quantity_material_version"] == 3 and o[UPGRADED_MATERIAL_KEY] == 2
            for lot in lots for o in lot.output_milestones
        )
    assert not legacy_material_plan(result.lots, data, config)
    assert not source_contract_violations(
        result.segments, lots, data, config, require_current_material=True,
    )


def test_independent_oracle_agrees_on_the_lot_release():
    from tests.oracle_delivery import oracle_window_violations

    data = scenario()
    result = schedule_all(data, config=CONFIG)
    assert oracle_window_violations(result.segments, result.lots, data) == []
    early = copy.deepcopy(result.segments)
    for segment in early:
        segment.day_idx -= 1
    assert oracle_window_violations(early, result.lots, data)


def test_the_rest_of_a_started_lot_may_continue_its_own_mounted_tool():
    """Rehearsal on the live plan (rev128, planning day 16/10, PRM043 outage):
    the rest of a started lot, released whole, resumes right after its
    started part without a new setup. The residual validation must see that
    started part (it is history), not take the previous tool as predecessor;
    a stale copy of a lot that is not a started rest still never bridges."""
    from tests.test_validation_protected_mounting import _data as protected_data
    from tests.test_validation_protected_mounting import _seg

    other = _seg("LOT_HAN", "HAN002", "CF589", 6, 420, 600, setup=60)
    started = _seg("LOT_JTE", "JTE003", "6800017267C.30", 6, 600, 900, setup=60)
    rest = _seg("LOT_JTE", "JTE003", "6800017267C.30", 7, 420, 500)
    data = protected_data([other, started])
    stale = validate_plan([rest], data)
    assert any(item["kind"] == "missing_tool_change_setup" for item in stale)
    data.residual_lot_remainders = [{"id": "LOT_JTE"}]
    assert not [
        item for item in validate_plan([rest], data)
        if item["kind"] in ("missing_tool_change_setup", "insufficient_tool_change_setup")
    ]


# ── real plans (private fixtures) ────────────────────────────────────────


def _setups_by_lot(result):
    from collections import Counter

    return Counter(s.lot_id for s in result.segments if s.setup_min > 0)


@pytest.mark.needs_private
def test_rev128_real_cases_are_one_production_per_lot():
    """ISOP of 13/10 (rev128, saved under version 2). Recalculated under the
    current contract every economic lot is one production: BFP114 went
    from 20 setups (7/6/6/1 for 4 lots) to 4, the twin BFP125 from 19 to
    3, JTE001 has one setup per lot, and lots of several economic lots
    (JDE002 28 000 = 2 x 14 000, HAN002 9 984 = 2 x 4 992) too."""
    from backend.plans.serialize import deserialize_snapshot
    from backend.scheduler.validation import lot_split_violations
    from tests.snapshot_fixture import load_payload

    _manifest, payload = load_payload("rev128")
    restored = deserialize_snapshot(copy.deepcopy(payload))
    data, config, stored = restored["engine_data"], restored["config"], restored["result"]
    before = _setups_by_lot(stored)

    def tool_setups(setups, lots, tool):
        return sorted(setups[lot.id] for lot in lots if lot.tool_id == tool)

    assert tool_setups(before, stored.lots, "BFP114") == [1, 6, 6, 7]
    assert sum(tool_setups(before, stored.lots, "BFP125")) == 19

    result = schedule_all(copy.deepcopy(data), config=config)
    after = _setups_by_lot(result)
    assert tool_setups(after, result.lots, "BFP114") == [1, 1, 1, 1]
    assert tool_setups(after, result.lots, "BFP125") == [1, 1, 1]
    assert set(tool_setups(after, result.lots, "JTE001")) == {1}
    eco = {op.id: op.eco_lot for op in data.ops}
    several = [lot for lot in result.lots if eco.get(lot.op_id) and lot.qty >= 2 * eco[lot.op_id]]
    assert {"LOT_JDE002_PRM042_TP042173-0060-1_20", "LOT_HAN002_PRM043_CF589MMA1A02.20_24"} <= {
        lot.id for lot in several
    }
    # One setup, or none when it continues the mounting of the lot before.
    assert all(after[lot.id] <= 1 for lot in several)
    # No lot of the plan has a second production, and none is split.
    assert max(after.values()) == 1
    assert not validate_plan(result.segments, data, config, lots=result.lots)
    by_machine = {}
    for segment in sorted(result.segments, key=lambda s: (s.day_idx, s.start_min)):
        by_machine.setdefault(segment.machine_id, []).append(segment)
    assert not lot_split_violations(by_machine, {lot.id: lot for lot in result.lots}, data, config)


def _real_change(case, data, config, baseline, freeze_day, started):
    """Apply one change of the rehearsal; returns (result, data, config, check)."""
    from backend.plans import frozen
    from backend.plans.manual_move import move_lot
    from backend.transform.calendars import apply_calendars

    if case == "outage":
        outage = copy.deepcopy(data)
        days = {freeze_day + 1, freeze_day + 2}
        outage.machine_blocked_days.setdefault("PRM043", set()).update(days)
        result = frozen.optimize_preserving_started_lots(outage, config, baseline, mode="quick")
        assert not any(s.machine_id == "PRM043" and s.day_idx in days and s.end_min > s.start_min
                       for s in result.segments)
        return result, outage, config
    if case == "holiday":
        holiday = "2026-10-23"
        changed = copy.deepcopy(config)
        changed.holidays = sorted({*changed.holidays, holiday})
        calendar = copy.deepcopy(data)
        apply_calendars(calendar, changed)
        result = frozen.optimize_preserving_started_lots(calendar, changed, baseline, mode="quick")
        day = calendar.workdays.index(holiday)
        assert day in calendar.holidays
        assert not any(s.day_idx == day and s.end_min > s.start_min for s in result.segments)
        return result, calendar, changed
    candidates = sorted(
        (s for s in baseline.segments
         if s.lot_id not in started and s.day_idx > freeze_day + 2 and s.setup_min > 0),
        key=lambda s: (s.day_idx, s.start_min),
    )
    target = candidates[{"rev124": 0, "rev128": 3}[case.split(":")[1]]]
    moved = move_lot(
        baseline.segments, baseline.lots, baseline.score, data, config, lot_id=target.lot_id,
        target_day=target.day_idx + 1, target_machine=target.machine_id, target_start_min=420,
    )
    start = min((s.day_idx, s.start_min) for s in moved.segments
                if s.lot_id == target.lot_id and s.qty > 0)
    assert start == (target.day_idx + 1, 420)
    return moved, data, config


@pytest.mark.needs_private
@pytest.mark.slow
@pytest.mark.parametrize(("revision", "clock", "case"), [
    ("rev124", None, "outage"),
    ("rev124", None, "holiday"),
    ("rev124", None, "move"),
    ("rev128", "2026-10-16", "outage"),
    # Was a strict xfail before the contiguity rule (13/10): the BFP082 run
    # started on 14/10 was frozen whole and kept lot _14 on the new holiday.
    ("rev128", "2026-10-16", "holiday"),
    ("rev128", "2026-10-16", "move"),
])
def test_started_version_2_lots_survive_a_change_on_real_plans(revision, clock, case, monkeypatch):
    """Rehearsal of 13/10: rev124 (as of 11/10, 10 started lots) and rev128
    (ISOP 13/10 on 16/10, 23 started lots), both saved under version 2. A
    PRM043 breakdown, a new holiday and a manual move each give a valid
    plan: the started history is unchanged, no lot is re-sized, every lot
    is taken over as version 3, and no lot that had not started has two
    productions."""
    from types import SimpleNamespace

    from backend.plans import frozen
    from backend.plans.serialize import deserialize_snapshot
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.material_quantities import lot_material_version
    from backend.scheduler.validation import assert_plan_valid
    from tests.snapshot_fixture import load_payload

    manifest, payload = load_payload(revision)
    restored = deserialize_snapshot(copy.deepcopy(payload))
    data, config, baseline = restored["engine_data"], restored["config"], restored["result"]
    freeze_day = data.workdays.index(clock) if clock else manifest["freeze_day"]
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_args, **_kw: freeze_day)
    assert {lot_material_version(lot) for lot in baseline.lots} == {2}
    started = {s.lot_id for s in baseline.segments
               if s.day_idx < freeze_day and s.end_min > s.start_min}
    assert len(started) == {"rev124": 10, "rev128": 23}[revision]

    label = f"move:{revision}" if case == "move" else case
    result, view_data, view_config = _real_change(
        label, data, config, baseline, freeze_day, started,
    )

    plan = SimpleNamespace(
        segments=result.segments, lots=result.lots, score=result.score,
        preserved_lot_proofs=getattr(result, "preserved_lot_proofs", None),
        history_boundary=getattr(result, "history_boundary", None),
    )
    assert_plan_valid(result.segments, result_validation_data(view_data, plan), view_config,
                      lots=result.lots)
    assert frozen.candidate_history_changes(
        payload, plan, view_data, view_config, freeze_day=freeze_day,
    ) == []
    assert {lot.id: lot.qty for lot in result.lots} == {lot.id: lot.qty for lot in baseline.lots}
    assert {lot_material_version(lot) for lot in result.lots} == {3}
    for lot in result.lots:
        assert {o["material_release_day"] for o in lot.output_milestones} == {
            lot.material_release_day
        }, lot.id
    setups = _setups_by_lot(result)
    assert [lot_id for lot_id, count in setups.items()
            if count > 1 and lot_id not in started] == []
