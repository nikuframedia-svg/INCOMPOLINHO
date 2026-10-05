"""Regression on the frozen revision 90 (plano-solver-2026-10-02 §2.1, §10-11).

The reference plan is physically valid, the audited BFP186 anticipation is
found by the machine-aware neighbourhood, and the complete improvement cycle
applies it without any per-order loss. A renamed copy behaves identically.
"""

from __future__ import annotations

import copy

import pytest

from backend.plans.frozen import improve_preserving_protected_lots
from backend.scheduler.alternative_repair import anticipation_proposals
from backend.scheduler.canonical import result_validation_data
from backend.scheduler.improvement import (
    Proposal,
    anticipation_better,
    anticipation_key,
    no_loss_verdict,
    plan_facts,
    production_windows,
)
from backend.scheduler.jit_policy import calendar_holidays, window_violation_details
from backend.scheduler.scoring import compute_score
from backend.scheduler.validation import plan_anchor_violations, validate_plan
from tests.snapshot_fixture import load_snapshot, rename_lots_and_runs

BFP186_RUN = "run_BFP186_PRM039_1"
BFP186_LOT = "LOT_TWIN_BFP186_47"


@pytest.fixture(scope="module")
def rev90():
    return load_snapshot("rev90")


def test_reference_plan_is_valid_and_matches_the_manifest(rev90):
    view = result_validation_data(rev90.data, rev90.result)
    assert not validate_plan(rev90.result.segments, view, rev90.config, lots=rev90.result.lots)
    assert not plan_anchor_violations(rev90.result.segments, view, rev90.config)
    assert not window_violation_details(
        rev90.result.segments, rev90.result.lots,
        calendar_holidays(view, -14, view.n_days + 30),
    )
    assert len(rev90.protected_lots) == rev90.manifest["protected_lots"] == 49
    assert len(rev90.result.lots) - len(rev90.protected_lots) == 153


def _n1_gains(snapshot):
    view, floor = snapshot.complete_context()
    return {
        item.subject["run_id"]: (item.subject["to_machine"], item.subject["start_gain_min"])
        for item in anticipation_proposals(
            snapshot.result.segments, snapshot.result.lots, view, snapshot.config,
            not_before_abs=floor,
        )
        if isinstance(item, Proposal)
    }


def test_n1_finds_the_audited_bfp186_anticipation(rev90):
    gains = _n1_gains(rev90)
    assert gains[BFP186_RUN] == ("PRM039", 385.0)
    assert gains["run_BFP171_PRM031_0__replanned_1"] == ("PRM039", 0.0)


def test_n1_is_independent_of_lot_and_run_names(rev90):
    renamed, _lot_map, run_map = rename_lots_and_runs(rev90)
    expected = {run_map[run_id]: gain for run_id, gain in _n1_gains(rev90).items()}
    assert _n1_gains(renamed) == expected


def test_improvement_cycle_applies_bfp186_without_any_order_loss(rev90):
    data, config, result = copy.deepcopy((rev90.data, rev90.config, rev90.result))
    before = copy.deepcopy(result)
    improved, report = improve_preserving_protected_lots(
        result, data, copy.deepcopy(data), config,
        copy.deepcopy(rev90.protected_segments), copy.deepcopy(rev90.protected_lots),
        rev90.freeze_day, time_budget_s=60,
    )

    view = result_validation_data(data, improved)
    assert not validate_plan(improved.segments, view, config, lots=improved.lots)
    reference_view = result_validation_data(data, before)
    reference = plan_facts(before.segments, before.lots, reference_view, compute_score(
        before.segments, before.lots, reference_view, config, include_operational_audit=False))
    candidate = plan_facts(improved.segments, improved.lots, view, compute_score(
        improved.segments, improved.lots, view, config, include_operational_audit=False))
    assert no_loss_verdict(candidate, reference).admissible
    protected = {lot.id for lot in rev90.protected_lots}
    assert sorted(
        (s.lot_id, s.machine_id, s.day_idx, s.start_min, s.end_min, s.qty)
        for s in improved.segments if s.lot_id in protected
    ) == sorted(
        (s.lot_id, s.machine_id, s.day_idx, s.start_min, s.end_min, s.qty)
        for s in before.segments if s.lot_id in protected
    )
    old, new = production_windows(before.segments), production_windows(improved.segments)
    # The cycle must dominate the audited candidate (only BFP186 moved, -385
    # min) in the canonical order. BFP186 itself may yield a few minutes to a
    # more urgent lot.
    view, floor = rev90.complete_context()
    audited = next(
        item for item in anticipation_proposals(
            rev90.result.segments, rev90.result.lots, view, rev90.config, not_before_abs=floor,
        ) if isinstance(item, Proposal) and item.subject["run_id"] == BFP186_RUN
    )
    assert anticipation_better(candidate.anticipation,
                               anticipation_key(audited.segments, audited.lots))
    assert old[BFP186_LOT][0] - new[BFP186_LOT][0] > 0
    assert report["moves_accepted"] >= 5
    assert sum(s.qty for s in improved.segments) == sum(s.qty for s in before.segments)
