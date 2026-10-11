"""Every comparison site uses the one contract-v3 comparator (AGENTS.md §1.3).

Rule 2 (10/10/2026): inside the 60-min tolerance fewer setups decide before
the exact minutes. A plan that saves one setup while a lot loses 30 min must
win at every site (evaluator, CPO rank, shift exchange and the pre-checks
before validation); one where the lot loses 70 min must lose at every site.

Shared scenario on one machine: A (tool T1) is followed by B (tool T2). The
reference installs B with a 30-min setup and B produces from 540. The
candidate keeps the machine without that setup (one fewer setup) and B
produces ``delta`` minutes later. The pre-check tests stub the placement
search so the comparison itself is what is under test.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from backend.cpo.optimizer import _is_better_candidate, _rank_better, _result_rank
from backend.scheduler import alternative_repair, local_cpsat
from backend.scheduler.alternative_repair import (
    anticipation_proposals,
    group_reinsertion_proposals,
)
from backend.scheduler.improvement import (
    Proposal,
    improvement_better,
    improvement_key,
    physical_setups,
    plan_facts,
    production_windows,
)
from backend.scheduler.policy import anticipation_better, anticipation_key, tolerant_better
from backend.scheduler.shift_exchange import _canonical_gain
from backend.scheduler.types import ScheduleResult

from tests.test_alternative_repair import _config, _data, _op, _run_and_segment

DAY = 2
WINS, LOSES = 30, 70
_SCORE = {
    "otd": 100.0,
    "otd_d": 100.0,
    "tardy_count": 0,
    "otd_d_failures": 0,
    "hard_violations": 0,
    "setups": 2,
    "setup_time_min": 60.0,
    "planning_penalty": 0.0,
}


def _scenario():
    op_a = _op("A", tool="T1", demand_day=3)
    op_b = _op("B", tool="T2", demand_day=3)
    run_a, lot_a, seg_a = _run_and_segment(op_a, machine="M1", day=DAY, due=3)
    run_b, lot_b, seg_b = _run_and_segment(op_b, machine="M1", day=DAY, due=3)
    seg_b = replace(seg_b, start_min=seg_a.end_min, end_min=seg_a.end_min + 90)
    data = _data([op_a, op_b])
    return (run_a, run_b), [lot_a, lot_b], [seg_a, seg_b], data, _config()


def _saving(segment, delta, **changes):
    """``segment`` without its setup, producing ``delta`` min later."""

    start = segment.start_min + int(segment.setup_min) + delta
    return replace(
        segment, setup_min=0.0, start_min=start,
        end_min=start + int(segment.prod_min), **changes,
    )


def _plans(delta):
    runs, lots, reference, data, config = _scenario()
    candidate = [reference[0], _saving(reference[1], delta)]
    return runs, lots, reference, candidate, data, config


def test_scenario_saves_one_setup_and_shifts_b_by_delta():
    _runs, lots, reference, candidate, _data_, _config_ = _plans(WINS)

    assert physical_setups(candidate).count == physical_setups(reference).count - 1
    before = production_windows(reference)[lots[1].id]
    after = production_windows(candidate)[lots[1].id]
    assert after[0] - before[0] == WINS
    # The pre-v3 rule (exact minutes only) preferred the reference.
    assert not anticipation_better(
        anticipation_key(candidate, lots), anticipation_key(reference, lots),
    )


@pytest.mark.parametrize(("delta", "wins"), [(WINS, True), (LOSES, False)])
def test_policy_comparator(delta, wins):
    _runs, lots, reference, candidate, _data_, _config_ = _plans(delta)
    cand, ref = physical_setups(candidate), physical_setups(reference)

    assert tolerant_better(
        anticipation_key(candidate, lots), anticipation_key(reference, lots),
        (cand.count, cand.minutes), (ref.count, ref.minutes),
    ) is wins


@pytest.mark.parametrize(("delta", "wins"), [(WINS, True), (LOSES, False)])
def test_improvement_evaluator(delta, wins):
    _runs, lots, reference, candidate, data, _config_ = _plans(delta)

    def key(segments):
        return improvement_key(
            plan_facts(segments, lots, data, _SCORE),
            transfers=0, changed_lots=0, displacement_min=0.0,
        )

    assert improvement_better(key(candidate), key(reference)) is wins
    assert improvement_better(key(reference), key(candidate)) is not wins


@pytest.mark.parametrize(("delta", "wins"), [(WINS, True), (LOSES, False)])
def test_cpo_rank(delta, wins):
    _runs, lots, reference, candidate, _data_, _config_ = _plans(delta)

    def result(segments):
        return ScheduleResult(
            segments=segments, lots=lots, score=dict(_SCORE), time_ms=0.0,
            warnings=[], operator_alerts=[],
        )

    assert _is_better_candidate(result(candidate), result(reference)) is wins
    assert _is_better_candidate(result(reference), result(candidate)) is not wins
    assert _rank_better(
        _result_rank(result(candidate)), _result_rank(result(reference)),
    ) is wins


@pytest.mark.parametrize(("delta", "wins"), [(WINS, True), (LOSES, False)])
def test_shift_exchange_applies_the_evaluator_order(delta, wins):
    _runs, lots, reference, candidate, data, _config_ = _plans(delta)

    assert _canonical_gain(
        candidate, reference,
        plan_facts(candidate, lots, data, _SCORE), plan_facts(reference, lots, data, _SCORE),
    ) is wins


def _stub_validation(monkeypatch, module):
    # The generators no longer validate (the evaluator does); only the
    # machine choice is stubbed.
    assert not hasattr(module, "validate_plan")
    monkeypatch.setattr(module, "_eligible_machines", lambda *args, **kwargs: ["M1"])


@pytest.mark.parametrize(("delta", "wins"), [(WINS, True), (LOSES, False)])
def test_alternative_anticipation_precheck(monkeypatch, delta, wins):
    runs, lots, reference, _candidate, data, config = _plans(delta)
    _stub_validation(monkeypatch, alternative_repair)

    def place(self, run, machine_id, fixed, *, not_before_abs=None):
        if run.id != runs[1].id:
            return None
        return run, [_saving(reference[1], delta)]

    monkeypatch.setattr(alternative_repair._PlacementSearch, "place", place)

    proposals = [item for item in anticipation_proposals(reference, lots, data, config)
                 if isinstance(item, Proposal)]

    assert bool(proposals) is wins
    if wins:
        assert physical_setups(proposals[0].segments).count == 1


@pytest.mark.parametrize(("delta", "wins"), [(WINS, True), (LOSES, False)])
def test_group_reinsertion_precheck(monkeypatch, delta, wins):
    runs, lots, reference, _candidate, data, config = _plans(delta)
    _stub_validation(monkeypatch, alternative_repair)
    placed = {runs[0].id: reference[0], runs[1].id: _saving(reference[1], delta)}

    def place(self, run, machine_id, fixed, *, not_before_abs=None):
        return run, [placed[run.id]]

    monkeypatch.setattr(alternative_repair._PlacementSearch, "place", place)

    proposals = [item for item in group_reinsertion_proposals(
        reference, lots, data, config, size=2,
    ) if isinstance(item, Proposal)]

    assert bool(proposals) is wins
    if wins:
        assert all(physical_setups(item.segments).count == 1 for item in proposals)


@pytest.mark.parametrize(("delta", "wins"), [(WINS, True), (LOSES, False)])
def test_local_cpsat_precheck(monkeypatch, delta, wins):
    runs, lots, reference, _candidate, data, config = _plans(delta)
    _stub_validation(monkeypatch, local_cpsat)
    group = tuple(sorted(run.id for run in runs))
    placed = {runs[0].id: reference[0], runs[1].id: _saving(reference[1], delta)}
    monkeypatch.setattr(local_cpsat, "_group_for", lambda *args: group)
    monkeypatch.setattr(local_cpsat, "_with_retained_successors", lambda group, *args: group)
    monkeypatch.setattr(
        local_cpsat, "_solve_group",
        lambda *args: [(runs[0].id, "M1"), (runs[1].id, "M1")],
    )

    def schedule(run, machine_id, fixed, data, config, *, not_before_abs=None):
        return run, [placed[run.id]]

    monkeypatch.setattr(local_cpsat, "_schedule_run_earliest", schedule)

    proposals = [item for item in local_cpsat.local_cpsat_proposals(
        reference, lots, data, config,
    ) if isinstance(item, Proposal)]

    assert bool(proposals) is wins
