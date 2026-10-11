"""Improvement measured per delivery (plan of 10/10, Fase B3; policy v3).

An economic lot covering several deliveries releases each on its own ``R``
(AGENTS §2), so "earlier" is measured per (lot, output): the pieces of each
delivery, first in first out, ranked by the delivery's own priority. A lot
with one delivery per side keeps the lot measure of policy v2. Also covered:
proposals pruned before validation when no element of the improvement key
can win, the whole-lot machine move (owner rule 3), and the builder's
retention break judged by the same comparator as the evaluator.

Calendar (shared with ``test_quantity_campaigns``): day 0 = Wednesday
07/10/2026, weekends are holidays; a delivery on day 13 releases material on
day 6, one on day 20 on day 13.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from backend.scheduler.alternative_repair import lot_machine_proposals
from backend.scheduler.improvement import (
    Generator,
    Proposal,
    SetupSummary,
    delivery_cannot_improve,
    improve_plan,
    improvement_better,
)
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.policy import (
    POLICY_VERSION,
    anticipation_compare,
    anticipation_key,
    anticipation_order,
    output_windows,
    production_windows,
    tolerant_better,
)
from backend.scheduler.priority import lot_priority_key, output_priority_key
from backend.scheduler.quantity_dispatch import _break_accepted, _Placement, _Portion
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import validate_plan
from tests.test_quantity_campaigns import _config, _data, _op

DAY = 1440


def _segment(lot: Lot, day: int, start: int, end: int, qty: int, *, setup=0.0, twin=None):
    return Segment(
        lot_id=lot.id, run_id=f"run:{lot.id}:{day}", machine_id="M1", tool_id=lot.tool_id,
        day_idx=day, start_min=start, end_min=end, shift="A", qty=qty,
        prod_min=float(end - start - setup), setup_min=float(setup), sku=lot.sku,
        twin_outputs=twin, lot_qty=lot.qty,
    )


def _v2_key(segments, lots):
    """Policy v2, written out: one element per lot in ``lot_priority_key`` order."""

    windows = production_windows(segments)
    return tuple(
        (lot.id, *windows.get(lot.id, (float("inf"), float("inf"))))
        for lot in sorted(lots, key=lot_priority_key)
    )


def _two_deliveries():
    """A covers 100 pcs due day 13 (R 6) and 50 due day 20 (R 13); B one
    delivery due day 15, between them."""

    data = _data([
        _op("A", "TA", {13: 100, 20: 50}, eco_lot=150),
        _op("B", "TB", {15: 80}),
    ])
    lot_a, lot_b = sorted(create_lots(data), key=lambda lot: lot.op_id)
    return data, lot_a, lot_b


# ── the per-output measure ───────────────────────────────────────────────


def test_policy_version_names_the_per_output_measure():
    assert POLICY_VERSION.startswith("per-output-")
    assert POLICY_VERSION.endswith("-v3")


def test_each_delivery_of_a_lot_has_its_own_window_first_in_first_out():
    _data_, lot_a, lot_b = _two_deliveries()
    plan = [
        _segment(lot_a, 6, 420, 590, 100, setup=60),  # the 100 pcs of day 13
        _segment(lot_a, 13, 420, 480, 50),  # the 50 pcs of day 20
        _segment(lot_b, 8, 420, 560, 80, setup=60),
    ]
    windows = output_windows(plan, [lot_a, lot_b])
    assert windows[f"{lot_a.id}#0"] == (6 * DAY + 480, 6 * DAY + 590)
    assert windows[f"{lot_a.id}#1"] == (13 * DAY + 420, 13 * DAY + 480)
    assert windows[lot_b.id] == (8 * DAY + 480, 8 * DAY + 560)  # one delivery: the lot
    # Ranked by each delivery's own priority: A's day-13 delivery, then B
    # (day 15), then A's day-20 delivery; never the lot as a whole.
    key = anticipation_key(plan, [lot_b, lot_a])
    assert [item[0] for item in key] == [f"{lot_a.id}#0", lot_b.id, f"{lot_a.id}#1"]
    assert output_priority_key(lot_a, 0) < output_priority_key(lot_b) < output_priority_key(
        lot_a, 1,
    )


def test_pieces_are_assigned_by_cumulative_quantity_not_by_segment():
    """One segment may finish a delivery and start the next one."""

    _data_, lot_a, _lot_b = _two_deliveries()
    plan = [
        _segment(lot_a, 13, 420, 500, 80, setup=20),  # 80 of the first delivery
        _segment(lot_a, 13, 500, 570, 70),  # its last 20 and the second's 50
    ]
    windows = output_windows(plan, [lot_a])
    assert windows[f"{lot_a.id}#0"] == (13 * DAY + 440, 13 * DAY + 570)
    assert windows[f"{lot_a.id}#1"] == (13 * DAY + 500, 13 * DAY + 570)


def test_a_delivery_not_fully_produced_never_finishes():
    _data_, lot_a, _lot_b = _two_deliveries()
    windows = output_windows([_segment(lot_a, 6, 420, 520, 120)], [lot_a])
    assert windows[f"{lot_a.id}#0"] == (6 * DAY + 420, 6 * DAY + 520)
    assert windows[f"{lot_a.id}#1"] == (6 * DAY + 420, float("inf"))


def test_a_lot_with_one_delivery_and_surplus_ranks_exactly_as_policy_v2():
    """The economic surplus closes the delivery, as it closes the last
    material portion: the element is the whole lot, under the lot id."""

    data = _data([
        _op("A", "TA", {13: 100}, eco_lot=500),
        _op("B", "TB", {13: 300}),
        _op("C", "TC", {15: 80}),
    ])
    lots = create_lots(data)
    assert any(
        output.get("is_economic_surplus") for lot in lots for output in lot.output_milestones
    )
    by_op = {lot.op_id: lot for lot in lots}
    plan = [
        _segment(by_op["A"], 6, 420, 520, 100, setup=60),
        _segment(by_op["A"], 7, 420, 820, 400),
        _segment(by_op["B"], 8, 420, 760, 300, setup=40),
        _segment(by_op["C"], 9, 420, 560, 80, setup=60),
    ]
    assert anticipation_key(plan, lots) == _v2_key(plan, lots)


def test_the_measure_sees_a_delivery_gain_the_lot_window_hides():
    """The first delivery finishes two hours earlier while the lot starts
    and ends at the same minutes: v2 sees no change, v3 an improvement."""

    _data_, lot_a, _lot_b = _two_deliveries()
    reference = [
        _segment(lot_a, 6, 420, 600, 60, setup=60),
        _segment(lot_a, 6, 600, 1000, 40),  # first delivery done at 1000
        _segment(lot_a, 13, 420, 480, 50),
    ]
    candidate = [
        _segment(lot_a, 6, 420, 880, 100, setup=60),  # done at 880
        _segment(lot_a, 6, 880, 1000, 0),
        _segment(lot_a, 13, 420, 480, 50),
    ]
    assert _v2_key(candidate, [lot_a]) == _v2_key(reference, [lot_a])
    assert anticipation_compare(
        anticipation_key(candidate, [lot_a]), anticipation_key(reference, [lot_a]),
    ) < 0


def test_twin_sides_are_measured_per_delivery_of_each_side():
    """Side A covers two deliveries, side B one: A's are separate elements,
    B's single delivery spans the whole cycle."""

    outputs = [
        {"op_id": "A", "sku": "A", "qty": 100, "customer_delivery_day": 13,
         "production_due_day": 13, "internal_target_day": 13, "material_release_day": 6},
        {"op_id": "A", "sku": "A", "qty": 100, "customer_delivery_day": 20,
         "production_due_day": 20, "internal_target_day": 20, "material_release_day": 13},
        {"op_id": "B", "sku": "B", "qty": 200, "customer_delivery_day": 14,
         "production_due_day": 14, "internal_target_day": 14, "material_release_day": 7},
    ]
    for output in outputs:
        output["quantity_material_version"] = 2
    twin = Lot(
        id="LOT_TWIN", op_id="A", tool_id="TT", machine_id="M1", alt_machine_id=None,
        qty=200, prod_min=200.0, setup_min=60.0, edd=13, is_twin=True, sku="A",
        twin_outputs=[("A", "A", 200), ("B", "B", 200)], output_milestones=outputs,
    )
    plan = [
        _segment(twin, 7, 420, 580, 100, setup=60, twin=[("A", "A", 100), ("B", "B", 100)]),
        _segment(twin, 13, 420, 520, 100, twin=[("A", "A", 100), ("B", "B", 100)]),
    ]
    windows = output_windows(plan, [twin])
    assert windows["LOT_TWIN#0"] == (7 * DAY + 480, 7 * DAY + 580)
    assert windows["LOT_TWIN#1"] == (13 * DAY + 420, 13 * DAY + 520)
    assert windows["LOT_TWIN#2"] == (7 * DAY + 480, 13 * DAY + 520)
    assert [item[0] for item in anticipation_key(plan, [twin])] == [
        "LOT_TWIN#0", "LOT_TWIN#2", "LOT_TWIN#1",
    ]


def test_a_delivery_finishes_at_its_readiness_never_with_the_surplus():
    """The economic surplus belongs to no delivery: the last delivery
    finishes when its own pieces are made (``delivery_readiness``), so
    making the surplus later delays nothing."""

    from backend.scheduler.material_quantities import delivery_readiness

    data = _data([_op("A", "TA", {13: 100, 20: 50}, eco_lot=300)])
    (lot,) = create_lots(data)
    assert any(output.get("is_economic_surplus") for output in lot.output_milestones)
    plan = [
        _segment(lot, 6, 420, 590, 100, setup=60),
        _segment(lot, 13, 420, 480, 50),
        _segment(lot, 14, 420, 720, 150),  # the surplus, a day later
    ]
    windows = output_windows(plan, [lot])
    assert windows[f"{lot.id}#1"] == (13 * DAY + 420, 13 * DAY + 480)
    order = anticipation_order([lot])
    for record in delivery_readiness([lot], plan, data):
        if record.index in order.measured[lot.id]:
            finish = windows[f"{lot.id}#{record.index}"][1]
            assert int(finish - 1e-9) // DAY == record.factory_day
    surplus_later = [*plan[:2], replace(plan[2], day_idx=16)]
    assert anticipation_key(surplus_later, [lot]) == anticipation_key(plan, [lot])


def test_restricted_key_keeps_the_global_order():
    _data_, lot_a, lot_b = _two_deliveries()
    plan = [_segment(lot_a, 6, 420, 590, 100, setup=60), _segment(lot_a, 13, 420, 480, 50),
            _segment(lot_b, 8, 420, 560, 80, setup=60)]
    order = anticipation_order([lot_a, lot_b])
    full = anticipation_key(plan, [lot_a, lot_b], order=order)
    only_a = anticipation_key(plan, [lot_a, lot_b], order=order, lot_ids={lot_a.id})
    assert only_a == tuple(item for item in full if item[0].startswith(lot_a.id))


# ── pruning before validation ────────────────────────────────────────────


def _complete_plan():
    data = _data([_op("A", "TA", {13: 300, 20: 300}, eco_lot=600), _op("B", "TB", {15: 200})])
    config = _config()
    result = schedule_all(data, config=config)
    assert not validate_plan(result.segments, data, config, lots=result.lots)
    return data, config, result


def _delayed(segments, lot_id, days):
    return [replace(s, day_idx=s.day_idx + days) if s.lot_id == lot_id else replace(s)
            for s in segments]


def test_delivery_cannot_improve_when_no_piece_is_made_earlier():
    data, config, result = _complete_plan()
    later = _delayed(result.segments, result.lots[0].id, 1)
    late_score = {"otd": 90.0, "tardy_count": 1}
    assert delivery_cannot_improve(later, result.segments, late_score)
    assert not delivery_cannot_improve(result.segments, later, late_score)
    # Already complete on time: nothing can improve, whatever the plan.
    assert delivery_cannot_improve(result.segments, later, {"otd": 100.0, "otd_d": 100.0})
    # With operational-audit metrics in the score, never prune.
    assert not delivery_cannot_improve(
        later, result.segments, {"released_tool_priority_inversions": 1},
    )


def test_a_proposal_that_cannot_win_is_pruned_before_validation(monkeypatch):
    from backend.scheduler import improvement

    data, config, result = _complete_plan()
    lot_b = next(lot for lot in result.lots if lot.op_id == "B")
    worse = _delayed(result.segments, lot_b.id, 1)
    validations = []
    original = improvement._physically_valid

    def counted(*args, **kwargs):
        validations.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(improvement, "_physically_valid", counted)
    generator = Generator("later", lambda segments, lots: Proposal(worse, lots))
    _segments, _lots, report = improve_plan(
        result.segments, result.lots, data, config, generators=[generator],
    )
    assert report["proposals_pruned"] == 1
    assert report["pruned_by_scope"] == {"later": 1}
    assert report["candidates_evaluated"] == 0
    assert report["moves_accepted"] == 0
    assert len(validations) == 1  # the reference only, never the pruned proposal


def test_a_proposal_that_may_win_is_validated_not_pruned():
    data, config, result = _complete_plan()
    lot_b = next(lot for lot in result.lots if lot.op_id == "B")
    later = _delayed(result.segments, lot_b.id, 1)
    generator = Generator("earlier", lambda segments, lots: Proposal(result.segments, lots))
    _segments, _lots, report = improve_plan(
        later, result.lots, data, config, generators=[generator],
    )
    assert report["proposals_pruned"] == 0
    assert report["candidates_evaluated"] == 1
    assert report["moves_accepted"] == 1


# ── whole-lot machine move (owner rule 3) ────────────────────────────────


def _split_lot_on_busy_machine():
    """A (two deliveries, two runs) waits for B on M1 and is split by C; M2
    is free. A one-run move cannot leave A's other run behind."""

    ops = [
        _op("B", "TB", {13: 900}),
        _op("A", "TA", {13: 300, 20: 300}, eco_lot=600),
        _op("C", "TC", {17: 600}),
    ]
    data = _data(ops, machines=("M1", "M2"))
    config = _config(("M1", "M2"))
    result = schedule_all(data, config=config)
    lot_a = next(lot for lot in result.lots if lot.op_id == "A")
    assert {s.machine_id for s in result.segments} == {"M1"}
    assert len({s.run_id for s in result.segments if s.lot_id == lot_a.id}) == 2
    # M2 becomes eligible for A only now, so the plan has A on M1.
    data = _data([replace(op, alt="M2") if op.id == "A" else op for op in ops],
                 machines=("M1", "M2"))
    lots = [replace(lot, alt_machine_id="M2") if lot.id == lot_a.id else lot
            for lot in result.lots]
    return data, config, result.segments, lots, lot_a.id


def test_whole_lot_moves_to_another_machine_with_all_its_portions():
    data, config, segments, lots, lot_a = _split_lot_on_busy_machine()
    (proposal,) = [item for item in lot_machine_proposals(segments, lots, data, config)
                   if isinstance(item, Proposal)]
    assert proposal.subject["kind"] == "lot_machine"
    assert proposal.subject["to_machine"] == "M2"
    moved = [s for s in proposal.segments if s.lot_id == lot_a]
    assert {s.machine_id for s in moved} == {"M2"}  # never split between machines
    assert sum(s.qty for s in moved) == sum(s.qty for s in segments if s.lot_id == lot_a)
    assert next(lot for lot in proposal.lots if lot.id == lot_a).machine_id == "M2"
    others = [s for s in proposal.segments if s.lot_id != lot_a]
    assert others == [s for s in segments if s.lot_id != lot_a]
    assert not validate_plan(proposal.segments, data, config, lots=proposal.lots)
    before = anticipation_key(segments, lots)
    assert anticipation_compare(anticipation_key(proposal.segments, proposal.lots), before) < 0


def test_improvement_cycle_accepts_the_whole_lot_move():
    data, config, segments, lots, lot_a = _split_lot_on_busy_machine()
    improved, improved_lots, report = improve_plan(segments, lots, data, config)
    assert report["accepted_by_scope"].get("lot_machine") == 1
    assert {s.machine_id for s in improved if s.lot_id == lot_a} == {"M2"}
    assert not validate_plan(improved, data, config, lots=improved_lots)


def test_a_segment_of_an_unknown_lot_leaves_its_set_alone():
    """A plan that is already wrong (a segment whose lot is not in ``lots``)
    must not break the neighbourhood: that coupled set is skipped."""

    data, config, segments, lots, lot_a = _split_lot_on_busy_machine()
    host = next(s for s in segments if s.lot_id == lot_a)
    stray = replace(host, lot_id="GHOST", qty=0, prod_min=0.0)
    proposals = list(lot_machine_proposals([*segments, stray], lots, data, config))
    assert not any(
        isinstance(item, Proposal) and lot_a in item.subject["lot_ids"] for item in proposals
    )


def test_no_whole_lot_move_without_another_eligible_machine():
    data, config, segments, lots, lot_a = _split_lot_on_busy_machine()
    plain = _data([replace(op, alt=None) for op in data.ops], machines=("M1", "M2"))
    lots = [replace(lot, alt_machine_id=None) for lot in lots]
    assert not list(lot_machine_proposals(segments, lots, plain, config))


# ── builder and evaluator agree on urgency (rule 2) ──────────────────────


def _placed(lot_id, rank, start, end, setup=0.0):
    portion = _Portion(lot_id, 0, None, (rank,), None, None)
    return _Placement(portion, "M1", [], float(start), float(end), float(setup), (0,))


def _evaluator_accepts(pairs):
    """``improvement_better`` on the same moved portions: same delivery,
    anticipation in priority order, setups (count, minutes)."""

    ranked = sorted(pairs, key=lambda pair: pair[0].portion.key)

    def key(index):
        placements = [pair[index] for pair in ranked]
        setups = SetupSummary(
            sum(1 for p in placements if p.setup > 0), sum(p.setup for p in placements),
        )
        return (
            (0,), tuple((p.portion.lot_id, p.start, p.end) for p in placements),
            setups.count, setups.minutes, 0, 0, 0.0,
        )

    return improvement_better(key(1), key(0))


@pytest.mark.parametrize(("own", "others", "accepted"), [
    # Report case 1: the more urgent dependent D loses 90 min, the less
    # urgent X gains 120 min. Sizes said yes; the evaluator says no.
    (
        [(_placed("X", 2, 1000, 1100, 30), _placed("X", 2, 880, 980, 30))],
        [(_placed("D", 1, 1100, 1200), _placed("D", 1, 1190, 1290, 30))],
        False,
    ),
    # Report case 2: the more urgent X gains 60 min, the less urgent D loses
    # 600 min. Sizes said no; the evaluator says yes.
    (
        [(_placed("X", 1, 1000, 1100, 30), _placed("X", 1, 940, 1040, 30))],
        [(_placed("D", 2, 1100, 1200), _placed("D", 2, 1700, 1800, 30))],
        True,
    ),
    # Inside the tolerance the re-mounted tool decides: refused by both.
    (
        [(_placed("X", 1, 1000, 1100, 30), _placed("X", 1, 950, 1050, 30))],
        [(_placed("D", 2, 1100, 1200), _placed("D", 2, 1130, 1230, 30))],
        False,
    ),
])
def test_builder_break_and_evaluator_agree_on_urgency(own, others, accepted):
    assert _break_accepted(own, others) is accepted
    assert _evaluator_accepts([*own, *others]) is accepted
    after = tuple(new.window for _old, new in sorted(
        [*own, *others], key=lambda pair: pair[0].portion.key))
    before = tuple(old.window for old, _new in sorted(
        [*own, *others], key=lambda pair: pair[0].portion.key))
    if accepted:
        assert tolerant_better(after, before, (2, 60.0), (1, 30.0))


# ── local CP-SAT pre-check: the evaluator's per-delivery vector ──────────


def _cpsat_proposals(monkeypatch, reference, moved):
    """Run N4 on ``reference`` with the group {A's 2nd run, B's run} placed
    as ``moved`` (run id -> segment): the model and allocator are stubbed,
    only the pre-check decides."""

    from backend.scheduler import local_cpsat

    data, lot_a, lot_b = _two_deliveries()
    group = tuple(sorted(moved))
    monkeypatch.setattr(local_cpsat, "_eligible_machines", lambda *args, **kwargs: ["M1"])
    monkeypatch.setattr(local_cpsat, "_group_for", lambda *args: group)
    monkeypatch.setattr(local_cpsat, "_with_retained_successors", lambda group, *args: group)
    monkeypatch.setattr(local_cpsat, "_solve_group",
                        lambda *args: [(run_id, "M1") for run_id in group])
    monkeypatch.setattr(local_cpsat, "_schedule_run_earliest",
                        lambda run, machine_id, fixed, data, config, *, not_before_abs=None:
                        (run, [moved[run.id]]))
    return [item for item in local_cpsat.local_cpsat_proposals(
        reference, [lot_a, lot_b], data, _config(),
    ) if isinstance(item, Proposal)]


def _evaluator_compare(reference, moved):
    """The evaluator's verdict on the same move: -1 earlier, 1 later."""

    _data_, lot_a, lot_b = _two_deliveries()
    candidate = [moved.get(segment.run_id, segment) for segment in reference]
    return anticipation_compare(
        anticipation_key(candidate, [lot_a, lot_b]), anticipation_key(reference, [lot_a, lot_b]),
    )


def _cpsat_plan():
    _data_, lot_a, lot_b = _two_deliveries()
    first = _segment(lot_a, 6, 420, 590, 100, setup=60)  # A's day-13 delivery
    second = _segment(lot_a, 14, 420, 480, 50)  # A's day-20 delivery (R 13)
    b_run = _segment(lot_b, 9, 420, 560, 80, setup=60)  # B, day 15 (R 8)
    return first, second, b_run


def test_local_cpsat_precheck_ranks_each_delivery_on_its_own(monkeypatch):
    """B (day 15) gains a day, A's day-20 delivery loses three hours: the
    evaluator ranks B before that delivery and accepts. The whole-lot
    window (A ranked first by its day-13 delivery, finishing later) would
    have discarded the group before the evaluator saw it."""

    first, second, b_run = _cpsat_plan()
    moved = {
        second.run_id: replace(second, start_min=600, end_min=660),
        b_run.run_id: replace(b_run, day_idx=8),
    }
    assert _evaluator_compare([first, second, b_run], moved) < 0
    assert len(_cpsat_proposals(monkeypatch, [first, second, b_run], moved)) == 1


def test_local_cpsat_precheck_does_not_trade_a_more_urgent_delivery(monkeypatch):
    """The reverse: A's day-20 delivery gains a day while B, more urgent,
    loses one. The whole-lot window (A finishing earlier) would propose it;
    the evaluator would reject it, so the pre-check does too."""

    first, second, b_run = _cpsat_plan()
    reference = [first, replace(second), replace(b_run, day_idx=8)]
    moved = {
        second.run_id: replace(second, day_idx=13),
        b_run.run_id: replace(b_run, day_idx=9),
    }
    assert _evaluator_compare(reference, moved) > 0
    assert _cpsat_proposals(monkeypatch, reference, moved) == []


# ── one validation per candidate: generators never validate ─────────────


def test_an_invalid_placement_is_rejected_by_the_evaluator_not_the_generator(monkeypatch):
    """N1 no longer validates its proposals (one evaluator, AGENTS §6): an
    invalid one reaches the evaluator, which rejects it as ``physical`` with
    the violation kinds, and nothing else validates it."""

    import sys

    from backend.scheduler import alternative_repair, validation
    from backend.scheduler.alternative_repair import anticipation_proposals
    from tests.test_anticipation_neighbourhood import _on_time_plan

    segments, lots, data, config = _on_time_plan("A", "T1", blocked_m2={0})

    def place(self, run, machine_id, fixed, *, not_before_abs=None):
        # Day 0 on M2 is blocked: physically invalid, but earlier.
        return run, [replace(segment, machine_id=machine_id, day_idx=0)
                     for segment in segments if segment.run_id == run.id]

    monkeypatch.setattr(alternative_repair._PlacementSearch, "place", place)
    callers = []
    real = validation._validate_plan

    def spy(*args, **kwargs):
        frame = sys._getframe(1)
        while frame.f_code.co_filename.endswith("validation.py"):
            frame = frame.f_back
        callers.append(frame.f_code.co_name)
        return real(*args, **kwargs)

    monkeypatch.setattr(validation, "_validate_plan", spy)
    generator = Generator(
        "alternative_anticipation",
        lambda current, current_lots: anticipation_proposals(current, current_lots, data, config),
        proposal_limit=None,
    )
    improved, _lots, report = improve_plan(segments, lots, data, config, generators=[generator])

    assert improved == segments
    # One placement per eligible machine (M1 and M2), both on a blocked day.
    assert report["rejections"] == {"alternative_anticipation:physical": 2}
    assert report["skipped_by_scope"] == {}
    entries = list(report["proposal_log"].values())
    assert len(entries) == 2
    assert all(entry["reason"] == "physical" and entry["details"] for entry in entries)
    # The reference and each candidate, validated once each by the evaluator.
    assert callers == ["_physically_valid"] * 3
