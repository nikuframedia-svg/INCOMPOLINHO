"""Campaign builder over material portions (plan of 10/10, Fase B1a).

Owner rules of 10/10: (1) when the next portion's material is already
released the mounted tool continues, without a new setup; (2) it continues
even if a more urgent lot wants the machine, as long as that lot loses less
than 60 min; (3) a machine change moves the whole lot. Portions of one lot
that run back to back share one run, and no segment is empty.

Calendar: day 0 = Wednesday 07/10/2026, weekends are holidays, so a delivery
on day 13 releases material on day 6 and one on day 14 on day 7.

Since 13/10/2026 (material version 3, AGENTS §2) a current lot is one
portion and one production; the per-portion cases run under version 2
(plans saved before, ``per_delivery_contract``) and the end of the file
asserts the same cases under the current contract.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.global_jit import _materialise_preemptive_lot
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.material_quantities import material_portions, released_quantity
from backend.scheduler.quantity_dispatch import (
    _break_accepted,
    _CampaignBuilder,
    _Placement,
    _Portion,
    _portion_lot,
)
from backend.scheduler.priority import lot_priority_key
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.setup_identity import segment_setup_identity
from backend.scheduler.types import ToolRun
from backend.scheduler.validation import validate_plan
from backend.types import EngineData, EOp, MachineInfo

N_DAYS = 35
DAY = 1440


def _pin_contract(monkeypatch, version):
    monkeypatch.setattr("backend.scheduler.lot_sizing.QUANTITY_MATERIAL_VERSION", version)
    monkeypatch.setattr("backend.scheduler.canonical.QUANTITY_MATERIAL_VERSION", version)


@pytest.fixture
def per_delivery_contract(monkeypatch):
    """Pin the per-delivery contract (material version 2, 08/10-13/10/2026).

    Since version 3 an economic lot is one portion and one production
    (AGENTS §2); the builder still plans the portions of lots saved under
    versions 1-2, which the cases marked with this fixture exercise. The
    same cases under the current contract are at the end of this file.
    """
    _pin_contract(monkeypatch, 2)


def _op(op_id, tool, demand_by_day, *, eco_lot=0, machine="M1", alt=None, sh=1.0, ph=60):
    demand = [0] * N_DAYS
    for day, qty in demand_by_day.items():
        demand[day] = qty
    return EOp(
        id=op_id, sku=op_id, client="CLIENT", designation=op_id, m=machine, t=tool,
        pH=ph, sH=sh, operators=1, eco_lot=eco_lot, alt=alt, stk=0, backlog=0,
        d=demand, oee=1.0, wip=0,
    )


def _data(ops, machines=("M1",)):
    days = [(date(2026, 10, 7) + timedelta(days=i)).isoformat() for i in range(N_DAYS)]
    return EngineData(
        ops=list(ops),
        machines=[MachineInfo(id=m, group="Grandes", day_capacity=1020) for m in machines],
        twin_groups=[],
        client_demands={},
        workdays=days,
        n_days=N_DAYS,
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )


def _config(machines=("M1",)):
    return FactoryConfig(machines={m: MachineConfig(id=m, group="Grandes") for m in machines})


def _abs(segment, end=False):
    return segment.day_idx * DAY + (segment.end_min if end else segment.start_min)


def _setups(segments, tool):
    return sum(1 for s in segments if s.tool_id == tool and s.setup_min > 0)


def _assert_clean(result, data, config):
    assert not validate_plan(result.segments, data, config, lots=result.lots)
    for segment in result.segments:
        assert segment.end_min > segment.start_min
        if segment.prod_min > 0:
            assert segment.qty > 0


# ── material portions ────────────────────────────────────────────────────


@pytest.mark.usefixtures("per_delivery_contract")
def test_portions_group_equal_releases_and_close_with_the_surplus():
    # Days 13 and 14 release on days 6 and 7; Saturday 17 and Monday 19 both
    # on day 12. The eco-lot surplus closes the last portion.
    data = _data([_op("A", "TA", {13: 100, 14: 50, 17: 30, 19: 20}, eco_lot=500)])
    (lot,) = create_lots(data)
    assert lot.qty == 500
    portions = material_portions(lot)
    assert [(p.qty, p.material_release_day) for p in portions] == [(100, 6), (50, 7), (350, 12)]
    assert sum(p.qty for p in portions) == lot.qty
    assert [len(p.outputs) for p in portions] == [1, 1, 3]


@pytest.mark.usefixtures("per_delivery_contract")
def test_portion_uses_its_own_delivery_window():
    data = _data([_op("A", "TA", {13: 100, 20: 50}, eco_lot=150)])
    (lot,) = create_lots(data)
    first, second = material_portions(lot)
    trial = _portion_lot(lot, second.qty, second.outputs, single=False)
    assert trial.qty == 50
    assert trial.material_release_day == second.material_release_day == 13
    assert trial.production_due_day == 20
    assert trial.target_start_day == 20 - lot.start_buffer_days
    assert lot_priority_key(trial) > lot_priority_key(lot)


# ── rule 2: the 60-minute veto ───────────────────────────────────────────


@pytest.mark.usefixtures("per_delivery_contract")
@pytest.mark.parametrize(("tail", "continues"), [(59, True), (60, False)])
def test_mounted_tool_continues_only_while_the_urgent_lot_loses_under_60_min(tail, continues):
    """A0 (1000 pcs, released day 6) runs into day 7, when A1 (``tail`` pcs,
    1 pc/min) is released. B is more urgent than A1 and waits for the machine:
    continuing A1 delays B by exactly ``tail`` minutes."""

    data = _data([
        _op("A", "TA", {13: 1000, 14: tail}, eco_lot=1000 + tail),
        _op("B", "TB", {13: 100}),
    ])
    config = _config()
    result = schedule_all(data, config=config)
    _assert_clean(result, data, config)
    b_start = min(
        _abs(s) + s.setup_min for s in result.segments if s.tool_id == "TB" and s.prod_min > 0
    )
    a_runs = {s.run_id for s in result.segments if s.tool_id == "TA"}
    if continues:
        assert _setups(result.segments, "TA") == 1
        assert len(a_runs) == 1
        a_end = max(_abs(s, end=True) for s in result.segments if s.tool_id == "TA")
        assert b_start == a_end + 60  # B waited exactly the 59 min plus its own setup
    else:
        assert _setups(result.segments, "TA") == 2
        assert len(a_runs) == 2
        a0_end = min(
            _abs(s, end=True) for s in result.segments
            if s.tool_id == "TA" and s.day_idx == 7
        )
        assert b_start == a0_end + 60  # B goes first, A1 is mounted again


# ── retained tool protection ─────────────────────────────────────────────


def _retention_case(setup_hours):
    """A0 (day 6) and A1 (released day 9) keep tool TA mounted across days
    7-8; X (released day 7) is placed afterwards, as the guard sees it."""

    data = _data([
        _op("A", "TA", {13: 300, 16: 300}, eco_lot=600, sh=setup_hours),
        _op("X", "TX", {14: 200}, sh=setup_hours),
    ])
    config = _config()
    builder = _CampaignBuilder(create_lots(data), data, config)
    a0, a1 = builder.portions["LOT_TA_M1_A_13"]
    builder.commit(builder.place(a0, "M1", builder.segments))
    retained = builder.place(a1, "M1", builder.segments)
    assert retained.setup == 0  # nothing else ran: A1 continues the mounting
    builder.commit(retained)
    (x,) = builder.portions["LOT_TX_M1_X_14"]
    blocked = builder.place(x, "M1", builder.segments)
    # The idle gap on days 7-8 belongs to the mounted tool.
    assert blocked.start >= retained.end
    return builder, blocked, retained


@pytest.mark.usefixtures("per_delivery_contract")
def test_retained_tool_yields_when_the_inserted_lot_gains_more_than_the_dependent_loses():
    """Rule 2 weighed both ways: A1 loses exactly 60 min (its new setup), X
    gains days. X waiting would lose far more than 60 min, so it passes."""

    builder, blocked, retained = _retention_case(setup_hours=1.0)
    assert builder.break_retention(blocked)
    a1 = builder.placed[("LOT_TA_M1_A_13", 1)]
    assert a1.start - retained.start == 60
    x = builder.placed[("LOT_TX_M1_X_14", 0)]
    assert blocked.start - x.start > 60


@pytest.mark.usefixtures("per_delivery_contract")
def test_retained_tool_yields_to_a_gain_of_60_min_when_the_dependent_loses_less():
    builder, blocked, retained = _retention_case(setup_hours=0.5)
    assert builder.break_retention(blocked)
    x_segments = [s for s in builder.segments if s.tool_id == "TX"]
    assert min(s.day_idx for s in x_segments) == 7
    a1 = builder.placed[("LOT_TA_M1_A_13", 1)]
    assert a1.setup == 30
    assert a1.start - retained.start == 30  # loses its setup, under 60 min
    assert a1.created[0].run_id != builder.placed[("LOT_TA_M1_A_13", 0)].created[0].run_id


def _at(start, end, delays=(0,), *, rank=1, setup=0.0, lot="X"):
    """A placement of a portion of priority ``rank`` (smaller is more urgent)."""

    portion = _Portion(lot, 0, None, (rank,), None, None)
    return _Placement(portion, "M1", [], float(start), float(end), float(setup), tuple(delays))


# X is the inserted lot, D the dependent one re-mounted by the break. The
# break is judged by the evaluator's comparator (contract v3) on the moved
# portions in priority order, never by comparing sizes.
@pytest.mark.parametrize(("own", "others", "accepted"), [
    # X gains 59 min and no delivery, D must be mounted again: the extra
    # setup decides inside the tolerance.
    (
        [(_at(1000, 1100, setup=30), _at(941, 1041, setup=30))],
        [(_at(1100, 1200, rank=0, lot="D"), _at(1100, 1200, rank=0, setup=30, lot="D"))],
        False,
    ),
    # D (more urgent) loses 30 min (under the tolerance): X gaining 100 decides.
    (
        [(_at(1000, 1100, setup=30), _at(900, 1000, setup=30))],
        [(_at(1100, 1200, rank=0, lot="D"), _at(1130, 1230, rank=0, setup=30, lot="D"))],
        True,
    ),
    # D (more urgent) loses 90 min while X gains 120: refused (D ranks first).
    (
        [(_at(1000, 1100, rank=2, setup=30), _at(880, 980, rank=2, setup=30))],
        [(_at(1100, 1200, rank=1, lot="D"), _at(1190, 1290, rank=1, setup=30, lot="D"))],
        False,
    ),
    # X (more urgent) gains 60 while D loses 600: accepted (X ranks first).
    (
        [(_at(1000, 1100, rank=1, setup=30), _at(940, 1040, rank=1, setup=30))],
        [(_at(1100, 1200, rank=2, lot="D"), _at(1700, 1800, rank=2, setup=30, lot="D"))],
        True,
    ),
    # Sizes do not decide: X gains as much as the more urgent D loses.
    (
        [(_at(1000, 1100, rank=2, setup=30), _at(800, 900, rank=2, setup=30))],
        [(_at(1100, 1200, rank=1, lot="D"), _at(1220, 1320, rank=1, setup=30, lot="D"))],
        False,
    ),
    # A later portion of the inserted lot gains a delivery: always accepted
    # once no delivery gets later, whatever the minutes.
    (
        [(_at(1000, 1100), _at(990, 1090)), (_at(5000, 9000, (2,)), _at(3000, 7000, (0,)))],
        [(_at(1100, 1200, rank=0, lot="D"), _at(1500, 1600, rank=0, lot="D"))],
        True,
    ),
])
def test_retention_break_weighs_rule_2_by_urgency(own, others, accepted):
    assert _break_accepted(own, others) is accepted


@pytest.mark.usefixtures("per_delivery_contract")
def test_retention_break_never_makes_an_unplaced_portion_of_the_tail_later(monkeypatch):
    """Deliveries first: the tail moved by the break ends up later; if a
    portion of that lot not placed yet would get a delivery later, the break
    is refused (here simulated)."""

    builder, blocked, _retained = _retention_case(setup_hours=0.5)
    calls = []
    original = _CampaignBuilder._unplaced

    def later(self, lot_id, machine, segments, cursor, *, start=None):
        calls.append(lot_id)
        if lot_id != "LOT_TA_M1_A_13":
            return original(self, lot_id, machine, segments, cursor, start=start)
        delay = (0,) if segments is self.segments else (1,)
        return [_at(0, 1, delay)]

    monkeypatch.setattr(_CampaignBuilder, "_unplaced", later)
    assert not builder.break_retention(blocked)
    assert calls == ["LOT_TA_M1_A_13", "LOT_TA_M1_A_13"]
    assert not [s for s in builder.segments if s.tool_id == "TX"]


# ── same lot in one run ──────────────────────────────────────────────────


@pytest.mark.usefixtures("per_delivery_contract")
def test_back_to_back_portions_of_a_lot_share_one_run_and_keep_their_boundaries():
    data = _data([_op("A", "TA", {13: 600, 14: 600, 15: 600}, eco_lot=1800)])
    config = _config()
    result = schedule_all(data, config=config)
    _assert_clean(result, data, config)
    assert len({s.run_id for s in result.segments}) == 1
    assert _setups(result.segments, "TA") == 1
    cumulative, boundaries = 0, set()
    for segment in sorted(result.segments, key=_abs):
        cumulative += segment.qty
        boundaries.add(cumulative)
    assert {600, 1200, 1800} <= boundaries
    (lot,) = result.lots
    for day in range(N_DAYS):
        produced = sum(s.qty for s in result.segments if s.day_idx <= day)
        assert produced <= released_quantity(lot, day)


# ── rule 3: machine chosen for the whole lot ─────────────────────────────


@pytest.mark.usefixtures("per_delivery_contract")
def test_machine_choice_looks_at_every_portion_and_moves_the_whole_lot():
    """The first portion is equally early on M1 and M2, but M1 is down when
    the second portion is released: the lot goes to M2, both portions."""

    data = _data(
        [_op("A", "TA", {13: 300, 16: 300}, eco_lot=600, alt="M2")],
        machines=("M1", "M2"),
    )
    data.machine_blocked_days = {"M1": set(range(9, 16))}
    config = _config(("M1", "M2"))
    result = schedule_all(data, config=config)
    _assert_clean(result, data, config)
    assert {s.machine_id for s in result.segments} == {"M2"}
    assert {lot.machine_id for lot in result.lots} == {"M2"}
    assert min(s.day_idx for s in result.segments if s.qty and s.day_idx >= 9) == 9


def test_without_a_difference_the_primary_machine_keeps_the_lot():
    data = _data(
        [_op("A", "TA", {13: 300, 16: 300}, eco_lot=600, alt="M2")],
        machines=("M1", "M2"),
    )
    config = _config(("M1", "M2"))
    result = schedule_all(data, config=config)
    assert {s.machine_id for s in result.segments} == {"M1"}


# ── no micro or zero segments ────────────────────────────────────────────


def test_every_productive_chunk_carries_pieces():
    data = _data([_op("A", "TA", {13: 3})])
    (lot,) = create_lots(data)
    run = ToolRun(id="R", tool_id="TA", machine_id="M1", alt_machine_id=None, lots=[lot],
                  setup_min=0, total_prod_min=100, total_min=100, edd=lot.edd)
    chunks = [(6, "A", 420, 421), (6, "A", 500, 501), (6, "B", 930, 1028)]
    segments = _materialise_preemptive_lot(
        run, lot, "M1", chunks, setup_start=None, setup_min=0, first_in_run=True,
    )
    assert [s.qty for s in segments] == [1, 1, 1]
    assert all(s.end_min > s.start_min for s in segments)


@pytest.mark.parametrize("version", [2, 3])
def test_small_releases_never_create_empty_segments(version, monkeypatch):
    _pin_contract(monkeypatch, version)
    data = _data([
        _op("A", "TA", {13: 7, 14: 3, 15: 1, 16: 2}, eco_lot=40, ph=7),
        _op("B", "TB", {14: 11, 15: 5}, eco_lot=30, ph=13),
    ])
    config = _config()
    result = schedule_all(data, config=config)
    _assert_clean(result, data, config)
    assert sum(s.qty for s in result.segments if s.tool_id == "TA") == 40
    assert sum(s.qty for s in result.segments if s.tool_id == "TB") == 30


# ── avoidable re-mounts ──────────────────────────────────────────────────


def _avoidable_remounts(segments, lots):
    """Independent count: a setup that mounts again a tool whose material was
    already released when the same mounting last ended, with no more urgent
    portion in between that a continuation would delay by 60 min or more."""

    portion_keys = {}
    bounds = {}
    for lot in lots:
        parts = material_portions(lot)
        total = 0
        bounds[lot.id] = []
        for part in parts:
            total += part.qty
            bounds[lot.id].append(total)
            trial = _portion_lot(lot, part.qty, part.outputs, single=len(parts) == 1)
            portion_keys[(lot.id, part.index)] = (lot_priority_key(trial), part.material_release_day)
    portion_of = {}
    for lot in lots:
        produced = 0
        for segment in sorted((s for s in segments if s.lot_id == lot.id),
                              key=lambda s: _abs(s, end=True)):
            index = next((i for i, b in enumerate(bounds[lot.id]) if produced < b),
                         len(bounds[lot.id]) - 1)
            portion_of[id(segment)] = (lot.id, index)
            produced += segment.qty
    by_machine = defaultdict(list)
    for segment in segments:
        by_machine[segment.machine_id].append(segment)
    avoidable = 0
    for machine_segments in by_machine.values():
        machine_segments.sort(key=_abs)
        for position, segment in enumerate(machine_segments):
            if segment.setup_min <= 0:
                continue
            identity = segment_setup_identity(segment)
            previous = [s for s in machine_segments[:position]
                        if segment_setup_identity(s) == identity and s.prod_min > 0]
            if not previous:
                continue
            last = previous[-1]
            key, release = portion_keys[portion_of[id(segment)]]
            if release is not None and release * DAY + 420 > _abs(last, end=True):
                continue
            between = [s for s in machine_segments
                       if _abs(last, end=True) <= _abs(s) < _abs(segment)]
            duration = sum(s.prod_min for s in machine_segments
                           if portion_of.get(id(s)) == portion_of[id(segment)])
            if duration >= 60 and any(portion_keys[portion_of[id(s)]][0] < key
                                      for s in between):
                continue
            avoidable += 1
    return avoidable


@pytest.mark.parametrize("version", [2, 3])
def test_no_avoidable_remount_in_a_mixed_campaign(version, monkeypatch):
    """Two tools sharing a machine, each lot with several releases: short
    released portions continue the mounting instead of being mounted again
    (version 2); under the current contract each lot is one production."""

    _pin_contract(monkeypatch, version)
    data = _data([
        _op("A", "TA", {13: 900, 14: 40, 15: 30, 16: 300}, eco_lot=1270),
        _op("B", "TB", {14: 500, 15: 20, 16: 400}, eco_lot=920),
        _op("C", "TC", {14: 200, 20: 150}, eco_lot=350),
    ])
    config = _config()
    result = schedule_all(data, config=config)
    _assert_clean(result, data, config)
    assert _avoidable_remounts(result.segments, result.lots) == 0
    for lot in result.lots:
        for day in range(N_DAYS):
            produced = sum(s.qty for s in result.segments
                           if s.lot_id == lot.id and s.day_idx <= day)
            assert produced <= released_quantity(lot, day)


@pytest.mark.usefixtures("per_delivery_contract")
def test_checker_detects_a_remount_the_builder_avoids():
    """The independent checker is not vacuous: a setup on a released
    continuation of the mounted tool counts as avoidable."""

    data = _data([
        _op("A", "TA", {13: 1000, 14: 30}, eco_lot=1030),
        _op("B", "TB", {20: 100}),
    ])
    config = _config()
    result = schedule_all(data, config=config)
    assert _avoidable_remounts(result.segments, result.lots) == 0
    segments = [replace(s) for s in result.segments]
    tail = [s for s in segments if s.tool_id == "TA" and s.setup_min == 0 and s.day_idx == 7
            and s.start_min > 420]
    assert tail
    tail[-1].setup_min = 60.0
    assert _avoidable_remounts(segments, result.lots) == 1


# ── rule 2 over a chain of continuations ─────────────────────────────────


@pytest.mark.usefixtures("per_delivery_contract")
def test_chained_continuations_never_add_up_past_the_tolerance():
    """A (3500 pcs) is followed by three small released portions of 40 pcs;
    B is more urgent than all three. Each continuation alone delays B by
    40 min, but the loss is measured against B's position before the chain
    started: the chain stops before B has lost 60 min in total."""

    data = _data([
        _op("A", "TA", {13: 3500, 14: 40, 15: 40, 16: 40}, eco_lot=3620),
        _op("B", "TB", {13: 100}),
    ])
    config = _config()
    result = schedule_all(data, config=config)
    _assert_clean(result, data, config)
    ordered = sorted((s for s in result.segments if s.tool_id == "TA"), key=_abs)
    produced, a0_end = 0, None
    for segment in ordered:
        produced += segment.qty
        if produced >= 3500:
            a0_end = _abs(segment, end=True)
            break
    b_start = min(
        _abs(s) + s.setup_min for s in result.segments if s.tool_id == "TB" and s.prod_min > 0
    )
    # Before the chain, B would start right after A0 and its own 60-min setup.
    assert b_start - (a0_end + 60) < 60
    assert _setups(result.segments, "TA") == 2


# ── deliveries before anticipation and setups ────────────────────────────


def _option(machine, windows, delays, setups=0):
    from backend.scheduler.quantity_dispatch import _MachineOption, _Placement

    placements = [
        _Placement(None, machine, [], start, end, 60.0 if index < setups else 0.0, (delay,))
        for index, ((start, end), delay) in enumerate(zip(windows, delays, strict=True))
    ]
    return _MachineOption(machine, placements)


def test_machine_choice_puts_deliveries_before_anticipation_and_setups():
    from backend.scheduler.quantity_dispatch import _machine_better

    early_but_late = _option("M1", [(0, 9000)], [1])
    later_on_time = _option("M2", [(600, 8000)], [0], setups=1)
    assert _machine_better(later_on_time, early_but_late, primary="M1")
    assert not _machine_better(early_but_late, later_on_time, primary="M1")
    # Same deliveries: the tolerant anticipation decides as before.
    assert _machine_better(_option("M2", [(0, 100)], [0]), _option("M1", [(600, 700)], [0]), "M1")


@pytest.mark.usefixtures("per_delivery_contract")
def test_a_continuation_is_vetoed_when_a_more_urgent_delivery_gets_later():
    """Inside the 60-min tolerance, a continuation still may not make a more
    urgent delivery late, or later (AGENTS §1.2 before rule 2)."""

    from backend.scheduler.quantity_dispatch import _Chain

    data = _data([
        _op("A", "TA", {13: 1000, 14: 30}, eco_lot=1030),
        _op("B", "TB", {13: 100}),
    ])
    lots = create_lots(data)
    builder = _CampaignBuilder(lots, data, _config())
    a0, a1 = builder.portions["LOT_TA_M1_A_13"]
    (b,) = builder.portions["LOT_TB_M1_B_13"]
    builder.commit(builder.place(a0, "M1", builder.segments))
    chain = _Chain(list(builder.segments))
    tail = builder.place(a1, "M1", builder.segments, not_before=builder.cursor[a0.lot_id])
    assert not builder.loses(b, tail, chain)  # 30 min: inside the tolerance
    before = chain.before(builder, b.lot_id)
    later = _option("M1", before.windows, [day + 1 for day in before.delays])
    builder.best_outlook = lambda *_args: later
    assert builder.loses(b, tail, chain)


@pytest.mark.usefixtures("per_delivery_contract")
def test_part_of_a_delivery_ranks_with_the_quantity_of_that_delivery():
    """Lot A_9 carries 100 of the 1000 pieces due on day 20 (the rest is in
    lot A_20). Ranked by its share it would wait behind C (950 due the same
    day); the delivery it serves is the larger one, so it goes first."""

    data = _data([_op("A", "TA", {9: 500, 20: 1000}, eco_lot=600), _op("C", "TC", {20: 950})])
    lots = create_lots(data)
    builder = _CampaignBuilder(lots, data, _config())
    share = builder.portions["LOT_TA_M1_A_9"][1]
    (other,) = builder.portions["LOT_TC_M1_C_20"]
    assert share.lot.qty == 100
    assert share.key[6] == -1000
    assert share.key < other.key
    assert lot_priority_key(share.lot) > lot_priority_key(other.lot)


@pytest.mark.usefixtures("per_delivery_contract")
def test_portion_ranks_only_with_deliveries_due_on_its_own_due_day():
    """The second portion of lot A_13 holds 30 pieces due on Saturday 17
    (production due Friday 16) and 900 of the 2000 due on Monday 19: both
    release on day 12. Its due day is 16, so the 2000 due later must not rank
    it; only its own quantity (930) and the day-16 delivery (30) count."""

    data = _data([_op("A", "TA", {13: 100, 17: 30, 19: 2000}, eco_lot=1030)])
    lots = create_lots(data)
    builder = _CampaignBuilder(lots, data, _config())
    _first, mixed = builder.portions["LOT_TA_M1_A_13"]
    assert mixed.lot.qty == 930
    assert mixed.key[0] == 16
    assert mixed.key[6] == -930


# ── fallback: a builder defect never fails the recalculation ─────────────


@pytest.mark.usefixtures("per_delivery_contract")
def test_builder_failure_falls_back_to_one_run_per_portion(monkeypatch):
    import backend.scheduler.quantity_dispatch as quantity_dispatch

    def broken(self, head):
        raise ValueError("defeito simulado")

    monkeypatch.setattr(quantity_dispatch._CampaignBuilder, "continue_campaign", broken)
    data = _data([
        _op("A", "TA", {13: 1000, 14: 30}, eco_lot=1030),
        _op("B", "TB", {13: 100}),
    ])
    config = _config()
    result = schedule_all(data, config=config)
    _assert_clean(result, data, config)
    a_runs = {s.run_id for s in result.segments if s.tool_id == "TA"}
    assert a_runs == {"quantity:LOT_TA_M1_A_13:0", "quantity:LOT_TA_M1_A_13:1"}
    assert sum(s.qty for s in result.segments if s.tool_id == "TA") == 1030
    # The planner sees the fallback with the plan, in plain Portuguese.
    # First, so the API's first-ten cut never hides it.
    assert result.warnings[0] == quantity_dispatch.FALLBACK_WARNING
    assert "setups" in quantity_dispatch.FALLBACK_WARNING
    monkeypatch.undo()
    assert quantity_dispatch.FALLBACK_WARNING not in schedule_all(data, config=config).warnings


def test_a_planning_timeout_is_never_hidden_by_the_fallback(monkeypatch):
    import backend.scheduler.quantity_dispatch as quantity_dispatch
    from backend.planning_control import PlanningTimeout

    def expired(self, head):
        raise PlanningTimeout("orçamento esgotado")

    monkeypatch.setattr(quantity_dispatch._CampaignBuilder, "continue_campaign", expired)
    data = _data([_op("A", "TA", {13: 1000, 14: 30}, eco_lot=1030)])
    with pytest.raises(PlanningTimeout):
        schedule_all(data, config=_config())


def test_twin_chunks_with_minutes_carry_pieces_on_every_side():
    data = _data([_op("A", "TA", {13: 3})])
    (lot,) = create_lots(data)
    twin = replace(lot, twin_outputs=[("A", "A", 3), ("A2", "A2", 3)])
    run = ToolRun(id="R", tool_id="TA", machine_id="M1", alt_machine_id=None, lots=[twin],
                  setup_min=0, total_prod_min=100, total_min=100, edd=lot.edd)
    chunks = [(6, "A", 420, 421), (6, "A", 500, 501), (6, "B", 930, 1028)]
    segments = _materialise_preemptive_lot(
        run, twin, "M1", chunks, setup_start=None, setup_min=0, first_in_run=True,
    )
    assert [s.qty for s in segments] == [1, 1, 1]
    for side in range(2):
        assert [s.twin_outputs[side][2] for s in segments] == [1, 1, 1]


@pytest.mark.usefixtures("per_delivery_contract")
def test_a_smaller_delivery_due_the_same_day_goes_first_when_it_costs_no_delivery(monkeypatch):
    """P (6500 pcs) ranks first by quantity among the deliveries due on day 13
    but is one day late whatever happens. Q and A, placed after it, would
    be late too; placed first, they are on time and P is still late by the
    same one day. Deliveries come before anticipation (AGENTS §1.2)."""

    import backend.scheduler.quantity_dispatch as quantity_dispatch

    ops = [
        _op("P", "TP", {13: 6500}),
        _op("Q", "TQ", {13: 100}),
        _op("A", "TA", {13: 300, 20: 300}, eco_lot=600),
    ]
    config = _config()

    def end_day(result, tool):
        return max(s.day_idx for s in result.segments if s.tool_id == tool and s.qty > 0)

    result = schedule_all(_data(ops), config=config)
    _assert_clean(result, _data(ops), config)
    assert end_day(result, "TQ") <= 13
    assert min(s.day_idx for s in result.segments if s.tool_id == "TA") <= 13
    assert end_day(result, "TP") == 14

    # Without the delivery-first swap, both smaller deliveries are late and
    # P is not earlier by a day: the swap costs no delivery.
    monkeypatch.setattr(quantity_dispatch._CampaignBuilder, "delivery_swap", lambda *_: None)
    plain = schedule_all(_data(ops), config=config)
    assert end_day(plain, "TQ") > 13
    assert end_day(plain, "TP") == 14


# ── material version 3 (13/10/2026): the same cases, one production per lot ──
#
# Since 13/10 an economic lot is one production (AGENTS §2): its whole
# material is released with its first delivery and it is mounted once. The
# per-portion rules above (tolerance, retention, portion ranking) then have
# nothing to split; these cases assert what replaces them.


def _ready(result, data):
    """Ready day of every delivery, ``(op, customer day) -> day``."""

    from backend.scheduler.material_quantities import delivery_portions

    return {
        (portion.op_id, portion.customer_delivery_day): portion.customer_ready_day
        for portion in delivery_portions(result.lots, result.segments, data)
        if portion.is_demand
    }


def _late(result, data):
    return {key: day for key, day in _ready(result, data).items() if day > key[1]}


def _assert_one_production_per_lot(result):
    by_machine = defaultdict(list)
    for segment in result.segments:
        by_machine[segment.machine_id].append(segment)
    for lot in result.lots:
        own = sorted((s for s in result.segments if s.lot_id == lot.id), key=_abs)
        assert sum(s.qty for s in own) == lot.qty
        assert len({s.run_id for s in own}) == 1, lot.id
        setups = sum(1 for s in own if s.setup_min > 0)
        if setups == 0:  # the tool is still mounted by the previous lot
            machine = sorted(by_machine[own[0].machine_id], key=_abs)
            assert machine[machine.index(own[0]) - 1].tool_id == own[0].tool_id, lot.id
        else:
            assert setups == 1 and own[0].setup_min > 0, lot.id
        assert [(p.qty, p.material_release_day) for p in material_portions(lot)] == [
            (lot.qty, lot.material_release_day)
        ]
        assert min(s.day_idx for s in own) >= lot.material_release_day
        first, last = _abs(own[0]), _abs(own[-1], end=True)
        assert not any(
            s.lot_id != lot.id and first < _abs(s) < last
            for s in by_machine[own[0].machine_id]
        ), f"{lot.id} split by another lot"


V3_CASES = {
    "tail_59": lambda: [
        _op("A", "TA", {13: 1000, 14: 59}, eco_lot=1059), _op("B", "TB", {13: 100}),
    ],
    "tail_60": lambda: [
        _op("A", "TA", {13: 1000, 14: 60}, eco_lot=1060), _op("B", "TB", {13: 100}),
    ],
    "retention_60": lambda: [
        _op("A", "TA", {13: 300, 16: 300}, eco_lot=600, sh=1.0), _op("X", "TX", {14: 200}, sh=1.0),
    ],
    "retention_30": lambda: [
        _op("A", "TA", {13: 300, 16: 300}, eco_lot=600, sh=0.5), _op("X", "TX", {14: 200}, sh=0.5),
    ],
    "back_to_back": lambda: [_op("A", "TA", {13: 600, 14: 600, 15: 600}, eco_lot=1800)],
    "mixed_campaign": lambda: [
        _op("A", "TA", {13: 900, 14: 40, 15: 30, 16: 300}, eco_lot=1270),
        _op("B", "TB", {14: 500, 15: 20, 16: 400}, eco_lot=920),
        _op("C", "TC", {14: 200, 20: 150}, eco_lot=350),
    ],
    "chain": lambda: [
        _op("A", "TA", {13: 3500, 14: 40, 15: 40, 16: 40}, eco_lot=3620),
        _op("B", "TB", {13: 100}),
    ],
    "share_of_a_delivery": lambda: [
        _op("A", "TA", {9: 500, 20: 1000}, eco_lot=600), _op("C", "TC", {20: 950}),
    ],
    "small_releases": lambda: [
        _op("A", "TA", {13: 7, 14: 3, 15: 1, 16: 2}, eco_lot=40, ph=7),
        _op("B", "TB", {14: 11, 15: 5}, eco_lot=30, ph=13),
    ],
}


@pytest.mark.parametrize("case", sorted(V3_CASES))
def test_current_contract_each_economic_lot_is_one_production(case):
    """Was: portions of one lot ran as separate productions whenever rule 2
    let another lot in between. Now every lot of every case is mounted
    once, from its first delivery's release, never split by another lot,
    and no delivery is late (capacity allows it in all these cases)."""

    data = _data(V3_CASES[case]())
    config = _config()
    result = schedule_all(data, config=config)
    _assert_clean(result, data, config)
    _assert_one_production_per_lot(result)
    assert _late(result, data) == {}


@pytest.mark.parametrize("tail", [59, 60])
def test_current_contract_keeps_the_tail_in_the_one_production(tail):
    """Was (version 2): with a tail of 60 min B went first and A's tail was
    mounted again (2 setups). Now the tail belongs to the lot's one
    production: B waits for it, whatever its length, and is still on time."""

    data = _data(V3_CASES[f"tail_{tail}"]())
    result = schedule_all(data, config=_config())
    assert _setups(result.segments, "TA") == 1
    a_end = max(_abs(s, end=True) for s in result.segments if s.tool_id == "TA")
    b_start = min(
        _abs(s) + s.setup_min for s in result.segments if s.tool_id == "TB" and s.prod_min > 0
    )
    assert b_start == a_end + 60
    assert _ready(result, data)[("B", 13)] <= 13


def test_current_contract_produces_the_whole_lot_before_the_inserted_one():
    """Was (version 2): A's second delivery waited for its own release (day
    9) and X went in between (two setups of TA). Now the whole lot runs on
    day 6, from its first release; X follows on day 7 when its material
    arrives, on time."""

    data = _data(V3_CASES["retention_60"]())
    result = schedule_all(data, config=_config())
    assert {s.day_idx for s in result.segments if s.tool_id == "TA"} == {6}
    assert min(s.day_idx for s in result.segments if s.tool_id == "TX") == 7
    assert _ready(result, data) == {("A", 13): 6, ("A", 16): 6, ("X", 14): 7}


def test_current_contract_has_one_portion_released_with_the_first_delivery():
    """Was: (100, 6), (50, 7), (350, 12) and the second portion of lot
    {13: 100, 20: 50} had its own window (day 13). Now one portion of the
    whole lot at the first delivery's release, and the portion is the lot."""

    data = _data([_op("A", "TA", {13: 100, 14: 50, 17: 30, 19: 20}, eco_lot=500)])
    (lot,) = create_lots(data)
    assert [(p.qty, p.material_release_day, len(p.outputs)) for p in material_portions(lot)] == [
        (500, 6, 5)
    ]
    data = _data([_op("A", "TA", {13: 100, 20: 50}, eco_lot=150)])
    (lot,) = create_lots(data)
    (whole,) = material_portions(lot)
    trial = _portion_lot(lot, whole.qty, whole.outputs, single=True)
    assert (trial.qty, trial.material_release_day, trial.production_due_day) == (150, 6, 13)


def test_current_contract_ranks_the_lot_with_its_first_delivery():
    """Was: a portion ranked with the delivery it served (A_9's 100 pieces
    for day 20, the 930 of lot A_13 due on day 16). Now the lot is one
    portion and ranks with its first delivery."""

    data = _data([_op("A", "TA", {9: 500, 20: 1000}, eco_lot=600), _op("C", "TC", {20: 950})])
    builder = _CampaignBuilder(create_lots(data), data, _config())
    (whole,) = builder.portions["LOT_TA_M1_A_9"]
    (other,) = builder.portions["LOT_TC_M1_C_20"]
    assert (whole.lot.qty, whole.key[0]) == (600, 9)
    assert whole.key < other.key
    data = _data([_op("A", "TA", {13: 100, 17: 30, 19: 2000}, eco_lot=1030)])
    builder = _CampaignBuilder(create_lots(data), data, _config())
    (whole,) = builder.portions["LOT_TA_M1_A_13"]
    assert (whole.lot.qty, whole.lot.material_release_day, whole.key[0]) == (1030, 6, 13)


def test_current_contract_machine_choice_keeps_the_lot_before_the_block():
    """Was (version 2): M1 was down when the second portion was released,
    so the whole lot moved to M2. Now the lot is released whole on day 6
    and runs at once on its primary machine, before the block."""

    data = _data(
        [_op("A", "TA", {13: 300, 16: 300}, eco_lot=600, alt="M2")], machines=("M1", "M2"),
    )
    data.machine_blocked_days = {"M1": set(range(9, 16))}
    config = _config(("M1", "M2"))
    result = schedule_all(data, config=config)
    _assert_clean(result, data, config)
    _assert_one_production_per_lot(result)
    assert {(s.machine_id, s.day_idx) for s in result.segments} == {("M1", 6)}


def test_current_contract_builder_failure_falls_back_to_one_run_per_lot(monkeypatch):
    """Was (version 2): one run per portion. Now the fallback still mounts
    each lot once."""

    import backend.scheduler.quantity_dispatch as quantity_dispatch

    def broken(self, head):
        raise ValueError("defeito simulado")

    monkeypatch.setattr(quantity_dispatch._CampaignBuilder, "continue_campaign", broken)
    data = _data(V3_CASES["tail_59"]())
    config = _config()
    result = schedule_all(data, config=config)
    _assert_clean(result, data, config)
    assert {s.run_id for s in result.segments} == {
        "quantity:LOT_TA_M1_A_13:0", "quantity:LOT_TB_M1_B_13:0",
    }
    assert result.warnings[0] == quantity_dispatch.FALLBACK_WARNING


def test_current_contract_a_lot_that_cannot_split_waits_rather_than_delay_more():
    """Capacity-bound case (P is late whatever happens). Was (version 2):
    A's first delivery (300 pieces) went before P as its own production and
    only P was one day late. Now A is one production of 600 (660 min):
    placed before P it would make P two days late, so the whole lot waits
    after P and A's first delivery is one day late. The rule of 13/10
    costs a delivery here; deliveries first still decides where the whole
    lot goes (AGENTS §1.2), and Q still goes first at no cost."""

    data = _data([
        _op("P", "TP", {13: 6500}),
        _op("Q", "TQ", {13: 100}),
        _op("A", "TA", {13: 300, 20: 300}, eco_lot=600),
    ])
    config = _config()
    result = schedule_all(data, config=config)
    _assert_clean(result, data, config)
    _assert_one_production_per_lot(result)
    assert _ready(result, data) == {("P", 13): 14, ("Q", 13): 6, ("A", 13): 14, ("A", 20): 15}
    # The alternative (the whole lot A before P) is two days for P.
    a_first = [s for s in result.segments if s.tool_id != "TA"]
    p_end = max(_abs(s, end=True) for s in a_first if s.tool_id == "TP")
    a_minutes = sum(s.end_min - s.start_min for s in result.segments if s.tool_id == "TA")
    assert (p_end + a_minutes) // DAY > 14
