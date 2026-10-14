"""Manual move of a lot that has not started (Incompol, 14/10/2026).

«Mover lote» for LOT_JTE001_PRM043_6800016767A.10_57 to Friday 04/12 at
15:30 on PRM043 answered «Verificação inconclusiva», and so did almost every
other move. The moved lot was handled as started work: credited as stock on
day 0, which broke the contract of its operation (an earlier lot of the same
operation no longer matched the ISOP) and switched the improvement off
(``reference_invalid``); its setup was dropped against a layout without the
other lots. Now the moved lot is pinned inside the same builder as the other
lots, keeps its setup unless production is glued to a started segment of the
same setup, and a move that cannot be made says why.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.plans.manual_move import (
    ManualMoveError,
    ManualMoveInconclusive,
    _materialize_target,
    move_lot,
)
from backend.scheduler.quantity_dispatch import schedule_quantity_releases
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.validation import validate_plan
from tests.test_quantity_campaigns import _config, _data, _op

LISBON = ZoneInfo("Europe/Lisbon")
# Before the first shift of the first day: nothing has started.
NOW = datetime(2026, 10, 7, 6, 0, tzinfo=LISBON)
EARLY, LATE, OTHER = "LOT_TA_M1_A_10", "LOT_TA_M1_A_24", "LOT_TB_M1_B_27"


def _plan():
    """Operation A has two economic lots (days 10 and 24); B is due day 27.

    Planned: A_10 on day 5, A_24 on day 19 (tool still mounted), B on day 20.
    """
    data = _data([_op("A", "TA", {10: 600, 24: 600}, eco_lot=600), _op("B", "TB", {27: 600})])
    config = _config()
    return data, config, schedule_all(data, config=config)


def _move(lot_id, day, start, plan=None):
    data, config, result = plan or _plan()
    return move_lot(
        result.segments, result.lots, result.score, data, config,
        lot_id=lot_id, target_day=day, target_start_min=start, now=NOW,
    )


def _own(segments, lot_id):
    return sorted((s for s in segments if s.lot_id == lot_id),
                  key=lambda s: (s.day_idx, s.start_min))


def _start(segments, lot_id):
    first = next(s for s in _own(segments, lot_id) if s.prod_min > 0)
    return first.day_idx, first.start_min + first.setup_min


def _one_production(segments, lot_id):
    own = _own(segments, lot_id)
    first, last = (own[0].day_idx, own[0].start_min), (own[-1].day_idx, own[-1].end_min)
    return (
        sum(1 for s in own if s.setup_min > 0) <= 1
        and len({s.run_id for s in own}) == 1
        and not any(
            s.lot_id != lot_id and s.machine_id == own[0].machine_id
            and first < (s.day_idx, s.start_min) < last
            for s in segments
        )
    )


def test_plan_of_the_scenario():
    _data_, _config_, result = _plan()
    assert {lot.id: _start(result.segments, lot.id)[0] for lot in result.lots} == {
        EARLY: 5, LATE: 19, OTHER: 20,
    }


def test_a_later_lot_of_an_operation_moves_and_the_rest_is_reorganised_around_it():
    """Was «Verificação inconclusiva»: day 20 is taken by B, and the move had
    to reorganise with A_24 credited as stock on day 0 (A_10 then failed its
    contract)."""
    data, config, result = plan = _plan()
    moved = _move(LATE, 20, 480, plan)

    assert _start(moved.segments, LATE) == (20, 480.0)
    own = _own(moved.segments, LATE)
    # A new setup: the tool was not kept mounted since day 5.
    assert own[0].setup_min == 60.0 and own[0].start_min == 420
    assert sum(s.qty for s in own) == 600
    for lot in moved.lots:
        assert _one_production(moved.segments, lot.id), lot.id
    # B goes after it, still on time; A_10 is untouched.
    assert _start(moved.segments, OTHER) >= (20, 1080)
    def place(segments):
        return [(s.day_idx, s.start_min, s.end_min, s.setup_min, s.qty)
                for s in _own(segments, EARLY)]

    assert place(moved.segments) == place(result.segments)
    assert not validate_plan(moved.segments, data, config, lots=moved.lots)
    assert moved.gate_report["physical_gate_passed"]
    assert moved.score["tardy_count"] == 0
    # The final improvement ran on a valid plan.
    assert moved.improvement_report["stop_reason"] != "reference_invalid"


def test_a_move_into_free_time_is_improved_on_a_valid_plan():
    """Free time on day 20 B / 21: the positions of the others stay; the
    improvement used to stop at ``reference_invalid`` (the moved lot was
    credited as stock)."""
    moved = _move(LATE, 21, 420)

    assert _start(moved.segments, LATE) == (21, 420.0)
    assert moved.improvement_report["stop_reason"] != "reference_invalid"


def test_a_move_that_cannot_fit_says_why():
    """The last day of the horizon has no room for the whole lot: a clear
    refusal, not «inconclusiva»."""
    with pytest.raises(ManualMoveError) as refused:
        _move(OTHER, 34, 1000)
    assert not isinstance(refused.value, ManualMoveInconclusive)
    assert "Não há capacidade física para iniciar" in str(refused.value)
    assert "inconclusiva" not in str(refused.value)


def test_a_move_before_the_material_release_is_still_refused():
    with pytest.raises(ManualMoveError, match="material deste lote só é libertado"):
        _move(LATE, 15, 420)


def test_the_builder_keeps_a_pinned_lot_and_places_the_others_around_it():
    data, config, result = _plan()
    pinned = [s for s in _move(LATE, 20, 480).segments if s.lot_id == LATE]

    segments, lots = schedule_quantity_releases(
        result.lots, data, config, pinned={LATE: ("M1", pinned)},
    )

    assert _own(segments, LATE) == sorted(pinned, key=lambda s: (s.day_idx, s.start_min))
    assert {lot.id for lot in lots} == {lot.id for lot in result.lots}
    assert _start(segments, OTHER) >= (20, 1080)
    assert not validate_plan(segments, data, config, lots=lots)


def test_a_gap_in_a_partial_layout_does_not_prove_the_tool_is_still_mounted():
    """Only started work is known when the moved lot is placed first: other
    lots may still go into the gap, so the setup stays (it was dropped, and
    the machine was then blocked until the moved lot as a «continuation»)."""
    data, config, result = _plan()
    started = _own(result.segments, EARLY)  # same tool, ends on day 5
    lot = next(item for item in result.lots if item.id == LATE)
    template = _own(result.segments, LATE)[0]

    whole = _materialize_target(started, lot, template, data, config, 20, "M1", 480)
    partial = _materialize_target(
        started, lot, template, data, config, 20, "M1", 480, partial_layout=True,
    )

    assert sum(s.setup_min for s in whole) == 0  # the whole plan proves it
    assert sum(s.setup_min for s in partial) == 60.0
    assert _start(partial, LATE) == (20, 480.0)


def test_an_improvement_that_moves_the_moved_lot_is_not_used(monkeypatch):
    from dataclasses import replace

    from backend.plans import frozen

    real = frozen.improve_preserving_protected_lots

    def shifts_the_moved_lot(result, *args, **kwargs):
        improved, report = real(result, *args, **kwargs)
        improved = replace(improved, segments=[
            replace(s, start_min=s.start_min + 1, end_min=s.end_min + 1)
            if s.lot_id == LATE and s.day_idx == 21 else s
            for s in improved.segments
        ])
        return improved, {**report, "moves_accepted": 1}

    monkeypatch.setattr(frozen, "improve_preserving_protected_lots", shifts_the_moved_lot)
    moved = _move(LATE, 21, 420)

    assert _start(moved.segments, LATE) == (21, 420.0)
    assert moved.improvement_report["stop_reason"] == "moved_lot_changed"
    assert moved.improvement_report["moves_accepted"] == 0


def test_a_refusal_of_the_final_validation_keeps_its_reason(monkeypatch):
    def refuses(*_args, **_kwargs):
        raise ManualMoveError("O movimento cria um conflito físico ou de quantidade.")

    monkeypatch.setattr("backend.plans.manual_move._finalize_move_candidate", refuses)
    with pytest.raises(ManualMoveError, match="conflito físico") as refused:
        _move(LATE, 21, 420)
    assert not isinstance(refused.value, ManualMoveInconclusive)


# ── Revision 142, the plan Incompol was moving at 17:00 on 14/10 ─────────


@pytest.fixture(scope="module")
def rev142():
    from tests.snapshot_fixture import load_snapshot

    snapshot = load_snapshot("rev142")
    assert snapshot.manifest["plan_revision"] == 142
    return snapshot


REV142_NOW = datetime(2026, 10, 14, 17, 0, tzinfo=LISBON)


def _move_rev142(snapshot, lot_id, day, machine, start):
    result = snapshot.result
    return move_lot(
        result.segments, result.lots, result.score, snapshot.data, snapshot.config,
        lot_id=lot_id, target_day=day, target_machine=machine, target_start_min=start,
        reason="teste", author="teste", now=REV142_NOW,
    )


def _no_improvement(monkeypatch):
    """The reorganisation alone (the final improvement has its own test)."""
    monkeypatch.setattr("backend.planning_control.improvement_time_budget", lambda _total: 0.0)


def _assert_applicable(snapshot, moved, lot_id, day, machine, start):
    result = snapshot.result
    first = next(s for s in _own(moved.segments, lot_id) if s.prod_min > 0)
    assert (first.day_idx, first.start_min + first.setup_min, first.machine_id) == (
        day, start, machine,
    )
    assert moved.gate_report["physical_gate_passed"]
    assert moved.gate_report["coverage_gate_passed"]
    assert {lot.id: lot.qty for lot in moved.lots} == {lot.id: lot.qty for lot in result.lots}
    for lot in moved.lots:
        assert _one_production(moved.segments, lot.id), lot.id
    # Started work (before 17:00 of 14/10) is exactly as it was.
    started = {(s.lot_id, s.machine_id, s.day_idx, s.start_min, s.end_min, s.qty)
               for s in result.segments
               if (s.day_idx, s.start_min) < (snapshot.freeze_day, 17 * 60)}
    assert started <= {(s.lot_id, s.machine_id, s.day_idx, s.start_min, s.end_min, s.qty)
                       for s in moved.segments}
    assert moved.score["tardy_count"] <= result.score["tardy_count"]


@pytest.mark.needs_private
@pytest.mark.slow
def test_rev142_jte001_moves_to_friday_04_12_at_15_30(rev142):
    """The reported case, with the final improvement as in production."""
    lot_id = "LOT_JTE001_PRM043_6800016767A.10_57"
    assert str(rev142.data.workdays[52])[:10] == "2026-12-04"

    moved = _move_rev142(rev142, lot_id, 52, "PRM043", 930)

    _assert_applicable(rev142, moved, lot_id, 52, "PRM043", 930)
    own = _own(moved.segments, lot_id)
    # Setup 14:30-15:30, production from 15:30 on Friday, rest on Monday 07/12
    # (the weekend and the 08/12 holiday are not working days), before the
    # 09/12 delivery.
    assert (own[0].day_idx, own[0].start_min, own[0].setup_min) == (52, 870, 60.0)
    assert {s.day_idx for s in own} == {52, 55}
    assert sum(s.qty for s in own) == 23040
    assert moved.improvement_report["stop_reason"] != "reference_invalid"


@pytest.mark.needs_private
@pytest.mark.parametrize(("lot_id", "day", "machine", "start"), [
    ("LOT_JTE001_PRM043_6800016767A.10_57", 52, "PRM043", 930),
    ("LOT_JTE003_PRM043_6800017267C.30_66", 52, "PRM043", 660),  # applied at 17:02
    ("LOT_BFP187_PRM043_3610299040_63", 57, "PRM043", 420),
    ("LOT_HAN002_PRM043_CF589MMA1A02.20_71", 59, "PRM043", 420),  # subcontracted
    ("LOT_BFP082_PRM019_1092262X100_21", 16, "PRM039", 420),  # alternative machine
    ("LOT_JTE001_PRM043_6800016767A.10_29", 24, "PRM043", 420),
    ("LOT_JDE002_PRM042_TP042173-0060-1_27", 21, "PRM042", 930),
    ("LOT_TWIN_BFP079_28", 22, "PRM031", 420),  # twin cycle
    ("LOT_BFP112_PRM039_1197914X050_28", 23, "PRM019", 420),  # alternative machine
    ("LOT_JTE001_PRM043_6800016767A.10_57", 51, "PRM043", 420),
])
def test_rev142_physically_possible_moves_are_applied(rev142, monkeypatch,
                                                      lot_id, day, machine, start):
    """Before: 9 of these 10 answered «Verificação inconclusiva»."""
    _no_improvement(monkeypatch)
    moved = _move_rev142(rev142, lot_id, day, machine, start)
    _assert_applicable(rev142, moved, lot_id, day, machine, start)


@pytest.mark.needs_private
@pytest.mark.parametrize(("lot_id", "day", "start", "reason"), [
    ("LOT_BFP187_PRM043_3610299040_63", 50, 420, "material deste lote só é libertado"),
    ("LOT_JTE001_PRM043_6800016767A.10_57", 56, 420, "calendário"),
])
def test_rev142_impossible_moves_are_refused_with_a_reason(rev142, lot_id, day, start, reason):
    with pytest.raises(ManualMoveError, match=reason) as refused:
        _move_rev142(rev142, lot_id, day, "PRM043", start)
    assert not isinstance(refused.value, ManualMoveInconclusive)
