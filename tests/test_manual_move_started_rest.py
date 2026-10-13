"""Manual moves under AGENTS §2, rule 4: only what started is fixed.

Same reduced scenario as ``test_started_lot_rest``: lot L starts on day 0,
another tool (lot X) runs after it, and L's second portion later continues
without setup on the tool mounted by lot M. Moving M used to fail: the whole
started lot L stayed frozen, so its rest kept relying on M's moved mounting.
"""

from __future__ import annotations

import copy

import pytest

from backend.plans import frozen
from backend.plans.manual_move import (
    ManualMoveError,
    ManualMoveInconclusive,
    _keeps_frozen,
    _move_protection,
    _production_start,
    move_lot,
)
from backend.scheduler.improvement import _segment_physical_row
from backend.scheduler.lot_sizing import upgrade_lot_material
from backend.scheduler.material_quantities import next_release_day, releases_in_portions
from backend.scheduler.validation import assert_plan_valid
from backend.types import PlanAnchor
from tests.test_started_lot_rest import (
    SUPPLIED,
    _baseline,
    _config,
    _data,
    _recorded_productions,
    _without_recorded_productions,
)


def _rows(segments):
    return {_segment_physical_row(segment) for segment in segments}


def _move(baseline, data, config, lot_id, day, minute):
    return move_lot(
        baseline.segments, baseline.lots, baseline.score, data, config,
        lot_id=lot_id, target_day=day, target_machine="M1", target_start_min=minute,
    )


def test_rest_of_a_started_lot_follows_a_moved_mount(monkeypatch):
    data, config = _data(), _config()
    baseline, (lot_l, lot_m, lot_x) = _baseline(data, config, SUPPLIED)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)
    started = [baseline.segments[0], baseline.segments[1]]  # L and X on day 0
    original = copy.deepcopy(baseline)

    moved = _move(baseline, data, config, lot_m.id, 7, 420)

    assert _production_start(moved.segments, lot_m.id)[:2] == (7, 420.0)
    # What started is exactly as before; the rest of L was re-allocated.
    assert _rows(started) <= _rows(moved.segments)
    rest = [s for s in moved.segments if s.lot_id == lot_l.id and s.day_idx >= 1]
    assert _rows(rest).isdisjoint(_rows([baseline.segments[3]]))
    # The rest is never re-sized: same lots, every lot complete.
    # (The plan was saved under version 2: the move takes it over as version 3.)
    # A move result carries no history boundary: L's started part and its
    # rest count as two productions, as in the stored plan, and stay two.
    moved_l = {lot.id: lot for lot in moved.lots}[lot_l.id]
    assert _recorded_productions(moved_l) == {2}
    assert _without_recorded_productions(moved_l) == upgrade_lot_material(lot_l, data)
    produced = {lot.id: sum(s.qty for s in moved.segments if s.lot_id == lot.id)
                for lot in moved.lots}
    assert produced == {lot_l.id: 200, lot_m.id: 200, lot_x.id: 100}
    assert moved.gate_report["physical_gate_passed"]
    assert_plan_valid(moved.segments, data, config, lots=moved.lots)
    assert baseline == original


def test_started_part_never_moves(monkeypatch):
    """A candidate that changes started production is never accepted."""
    data, config = _data(), _config()
    baseline, (lot_l, lot_m, lot_x) = _baseline(data, config, SUPPLIED)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)

    def tampered(*_args, **_kwargs):
        result = copy.deepcopy(baseline)
        first = next(s for s in result.segments if s.lot_id == lot_l.id)
        first.start_min += 10
        first.end_min += 10
        return result

    def no_fixed_candidate(*_args, **_kwargs):
        raise ManualMoveError("posições fixas sem candidato")

    monkeypatch.setattr("backend.plans.manual_move._fixed_positions_move", no_fixed_candidate)
    monkeypatch.setattr("backend.plans.manual_move._allocate_existing_lots", tampered)
    monkeypatch.setattr("backend.plans.manual_move._replan_around_fixed_lot",
                        lambda *_args: None)

    with pytest.raises(ManualMoveInconclusive, match="o plano não foi alterado"):
        _move(baseline, data, config, lot_m.id, 7, 420)

    # The started part (and only it) is what the check protects.
    protection = _move_protection(baseline, 1, data, config, lot_m.id)
    assert [(s.lot_id, s.day_idx) for s in protection.segments] == [
        (lot_l.id, 0), (lot_x.id, 0),
    ]
    assert _keeps_frozen(baseline.segments, protection.segments)
    assert not _keeps_frozen(tampered().segments, protection.segments)


def test_started_lot_itself_is_still_refused(monkeypatch):
    data, config = _data(), _config()
    baseline, (lot_l, _lot_m, _lot_x) = _baseline(data, config, SUPPLIED)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)

    with pytest.raises(ManualMoveError, match="congelado"):
        _move(baseline, data, config, lot_l.id, 7, 420)


def test_mount_supplier_of_a_kept_continuation_is_kept(monkeypatch):
    """L is anchored (kept whole) and continues on M's mounting: moving X
    re-allocates the other lots, but M is kept exactly as it was."""
    data, config = _data(), _config()
    baseline, (lot_l, lot_m, lot_x) = _baseline(data, config, SUPPLIED)
    data.plan_anchors = [PlanAnchor(lot_l.id, "M1", "2026-03-02T07:30", "manual", "planeador")]
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 0)

    protection = _move_protection(baseline, 0, data, config, lot_x.id)
    assert sorted(lot.id for lot in protection.lots) == sorted([lot_l.id, lot_m.id])
    assert all(s.lot_id != lot_x.id for s in protection.segments)

    moved = _move(baseline, data, config, lot_x.id, 1, 420)

    assert _production_start(moved.segments, lot_x.id)[:2] == (1, 420.0)
    kept = [s for s in baseline.segments if s.lot_id in {lot_l.id, lot_m.id}]
    assert _rows(kept) <= _rows(moved.segments)
    assert_plan_valid(moved.segments, data, config, lots=moved.lots)


def test_move_before_the_first_material_portion_is_refused_clearly(monkeypatch):
    # M serves the deliveries of days 11 and 12: its material comes in portions.
    data, config = _data(later=((9, 100), (12, 100))), _config()
    later = [(0, 0, 420, 100, 30, 0), (2, 0, 510, 100, 30, 2),
             (1, 7, 420, 200, 30, 1), (0, 7, 570, 100, 0, 1)]
    baseline, (_lot_l, lot_m, _lot_x) = _baseline(data, config, later)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 0)
    assert releases_in_portions(lot_m)
    release = next_release_day(lot_m, -1)
    assert release is not None and release > 1

    with pytest.raises(ManualMoveError, match="material deste lote só é libertado no dia"):
        _move(baseline, data, config, lot_m.id, 1, 420)


def test_setup_before_the_material_release_is_refused_at_once(monkeypatch):
    """The setup, not only the production, must start after the material.

    M's material is released on day 4. Production at 07:00 on day 4 needs its
    30 min setup at the end of day 3, which the material gate refuses
    (``setup_before_material``): the move is refused before any planning.
    At 07:30 the setup fits on day 4 and the same move is accepted.
    """
    data, config = _data(), _config()
    baseline, (_lot_l, lot_m, _lot_x) = _baseline(data, config, SUPPLIED)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 0)
    release = next_release_day(lot_m, -1)
    assert release == 4 and lot_m.material_release_day == 4

    def no_planning(*_args, **_kwargs):
        raise AssertionError("refused before planning")

    with monkeypatch.context() as patched:
        for name in ("_fixed_positions_move", "_allocate_existing_lots",
                     "_replan_around_fixed_lot"):
            patched.setattr(f"backend.plans.manual_move.{name}", no_planning)
        with pytest.raises(ManualMoveError) as refused:
            _move(baseline, data, config, lot_m.id, release, 420)
    message = str(refused.value)
    assert "O material deste lote só é libertado no dia 4" in message
    assert "afinação de 30 min" in message and "começaria no dia 3" in message
    assert "23:30" in message

    moved = _move(baseline, data, config, lot_m.id, release, 450)
    assert _production_start(moved.segments, lot_m.id)[:2] == (4, 450.0)
    setups = [s for s in moved.segments if s.lot_id == lot_m.id and s.setup_min > 0]
    assert setups and min(s.day_idx for s in setups) >= 4
    assert moved.gate_report["physical_gate_passed"]
    assert_plan_valid(moved.segments, data, config, lots=moved.lots)


def _spy_reallocations(monkeypatch):
    """Record which reallocations a move runs; the fixed attempt always fails."""
    from backend.plans import manual_move

    calls = []
    original = manual_move._allocate_existing_lots

    def spy(*args, **kwargs):
        calls.append("whole plan" if kwargs.get("baseline_result") is not None else "around")
        return original(*args, **kwargs)

    def no_fixed_candidate(*_args, **_kwargs):
        raise ManualMoveError("posições fixas sem candidato")

    monkeypatch.setattr(manual_move, "_allocate_existing_lots", spy)
    monkeypatch.setattr(manual_move, "_fixed_positions_move", no_fixed_candidate)
    return calls


def test_quantity_releases_go_straight_to_the_fixed_lot_replan(monkeypatch):
    """L releases its material in portions: the reallocation of the whole plan
    uses the campaign builder, which ignores the anchor, so it is skipped and
    the lot is fixed first. The move succeeds through that attempt."""
    data, config = _data(), _config()
    baseline, (lot_l, _lot_m, lot_x) = _baseline(data, config, SUPPLIED)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 0)
    assert releases_in_portions(lot_l)
    calls = _spy_reallocations(monkeypatch)

    moved = _move(baseline, data, config, lot_x.id, 1, 420)

    assert calls == ["around"]
    assert _production_start(moved.segments, lot_x.id)[:2] == (1, 420.0)
    assert moved.gate_report["physical_gate_passed"]
    assert_plan_valid(moved.segments, data, config, lots=moved.lots)


def test_without_quantity_releases_the_whole_plan_reallocation_still_runs(monkeypatch):
    data, config = _data(), _config()
    baseline, (_lot_l, _lot_m, lot_x) = _baseline(data, config, SUPPLIED)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 0)
    monkeypatch.setattr(
        "backend.scheduler.quantity_dispatch.has_quantity_releases", lambda _lots: False,
    )
    calls = _spy_reallocations(monkeypatch)

    # The whole-plan reallocation is tried first. Was (version 2): it found
    # no candidate and the move ended inconclusive. The plan is now taken
    # over as version 3 (L released whole): that reallocation succeeds.
    moved = _move(baseline, data, config, lot_x.id, 1, 420)

    assert calls == ["whole plan"]
    assert _production_start(moved.segments, lot_x.id)[:2] == (1, 420.0)
    assert moved.gate_report["physical_gate_passed"]
    assert_plan_valid(moved.segments, data, config, lots=moved.lots)
