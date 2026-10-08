"""Priority repairs must see mounted protected production, not only reservations."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from backend.plans.frozen import (
    _install_frozen_reservations,
    _restore_frozen_reservations,
    improve_preserving_protected_lots,
)
from backend.scheduler.canonical import preserved_lot_proofs
from backend.scheduler.improvement import (
    Proposal,
    SkippedProposal,
    default_generators,
    no_loss_verdict,
    physical_setups,
    plan_facts,
)
from backend.scheduler.priority_normalization import repair_priority_inversions
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import ScheduleResult
from backend.scheduler.validation import validate_plan
from tests.test_transfer_consolidation import _config, _data, _lot, _op, _seg


def _case(prefix="BFP082"):
    urgent_op = _op(prefix, prefix, {0: 45}, rate=60, alt=None)
    later_op = _op(f"{prefix}-LATER", "OTHER", {0: 15}, rate=60, alt=None)
    head = _lot(urgent_op, f"{prefix}-HEAD", qty=30, prod_min=30, due=0)
    urgent = _lot(urgent_op, f"{prefix}-URGENT", qty=15, prod_min=15, due=0)
    urgent.original_edd = -1
    later = _lot(later_op, f"{prefix}-LATER", qty=15, prod_min=15, due=0)
    segments = [
        _seg(head, "HEAD", "M1", 0, 420, 480, setup=30, prod=30, qty=30),
        _seg(later, "LATER", "M1", 0, 480, 525, setup=30, prod=15, qty=15),
        _seg(urgent, "URGENT", "M1", 1, 420, 465, setup=30, prod=15, qty=15),
    ]
    lots = [head, later, urgent]
    data, config = _data([urgent_op, later_op]), _config()
    data.machine_blocked_intervals = {
        "M1": [{"start_day": 0, "end_day": 0, "start_min": 540, "end_min": 1440}],
    }
    data.preserved_lot_proofs = preserved_lot_proofs(segments[:1], lots[:1])
    assert not validate_plan(segments, data, config, lots=lots)
    return segments, lots, data, config


def _facts(segments, lots, data, config):
    return plan_facts(segments, lots, data, compute_score(segments, lots, data, config))


@pytest.mark.parametrize("prefix", ["BFP082", "RENAMED"])
def test_priority_witness_uses_the_retained_mount_to_keep_both_deliveries(prefix):
    segments, lots, data, config = _case(prefix)
    witness = [segments[0],
               replace(segments[2], day_idx=0, start_min=480, end_min=495, setup_min=0),
               replace(segments[1], start_min=495, end_min=540)]
    assert not validate_plan(witness, data, config, lots=lots)
    verdict = no_loss_verdict(_facts(witness, lots, data, config),
                             _facts(segments, lots, data, config))
    assert verdict.admissible, verdict.reasons
    assert physical_setups(witness).count == physical_setups(segments).count - 1
    repaired = repair_priority_inversions(segments, lots, data, config)
    assert [(s.day_idx, s.production_start_min) for s in repaired if s.run_id == "URGENT"] == [(0, 480)]


@pytest.mark.parametrize("prefix", ["BFP082", "RENAMED"])
def test_residual_priority_search_must_find_the_same_no_loss_witness(prefix):
    segments, lots, data, config = _case(prefix)
    before = copy.deepcopy((segments, lots, data, config))
    result = ScheduleResult(copy.deepcopy(segments), copy.deepcopy(lots),
                            compute_score(segments, lots, data, config), 0, [], [])
    improved, report = improve_preserving_protected_lots(
        result, data, copy.deepcopy(data), config, copy.deepcopy(segments[:1]),
        copy.deepcopy(lots[:1]), 0, time_budget_s=5,
    )
    assert [(s.day_idx, s.production_start_min) for s in improved.segments
            if s.run_id == "URGENT"] == [(0, 480)], report
    assert [s for s in improved.segments if s.run_id == "HEAD"] == segments[:1]
    assert not validate_plan(improved.segments, data, config, lots=improved.lots)
    assert no_loss_verdict(_facts(improved.segments, improved.lots, data, config),
                           _facts(segments, lots, data, config)).admissible
    assert (segments, lots, data, config) == before


@pytest.mark.parametrize("prefix", ["BFP082", "RENAMED"])
def test_priority_generator_preserves_the_same_context_as_canonical_compaction(prefix):
    segments, lots, data, config = _case(prefix)
    original_data = copy.deepcopy(data)
    original = copy.deepcopy((segments, lots, data, config))

    def complete_context(residual_segments, residual_lots):
        return ([*copy.deepcopy(segments[:1]), *residual_segments],
                [*copy.deepcopy(lots[:1]), *residual_lots], original_data)

    snapshot = _install_frozen_reservations(data, segments[:1], lots[:1], 0, config)
    try:
        generator = next(g for g in default_generators(data, config, evaluation_plan=complete_context)
                         if g.name == "priority_inversions")
        proposed = generator.propose(copy.deepcopy(segments[1:]), copy.deepcopy(lots[1:]))
        proposals = [proposed] if isinstance(proposed, Proposal) else list(proposed)
        assert any([(s.day_idx, s.production_start_min) for s in p.segments
                    if s.run_id == "URGENT"] == [(0, 480)] for p in proposals), proposals
        assert all(not any(s.run_id == "HEAD" for s in p.segments) for p in proposals)
    finally:
        _restore_frozen_reservations(data, snapshot)
    assert (segments, lots, data, config) == original


@pytest.mark.parametrize("scope", ["priority_inversions", "campaign_tail", "shift_exchange"])
@pytest.mark.parametrize("change", ["none", "allocation", "quantity"])
def test_all_reallocation_scopes_receive_and_preserve_protected_context(monkeypatch, scope, change):
    from backend.scheduler.campaign_tail import CampaignTailResult

    segments, lots, data, config = _case()
    original = copy.deepcopy((segments, lots, data, config))

    def attempt(complete_segments, complete_lots, complete_data, *_args, **kwargs):
        assert len(complete_segments) == len(segments)
        assert len(complete_lots) == len(lots)
        assert "BFP082-HEAD" in complete_data.preserved_lot_proofs
        assert not any(entry.get("id", "").startswith("frozen-prefix")
                       for entries in complete_data.machine_blocked_intervals.values()
                       for entry in entries)
        changed_segments, changed_lots = copy.deepcopy((complete_segments, complete_lots))
        if change == "allocation":
            changed_segments[0].start_min += 1
        elif change == "quantity":
            complete_lots[0].qty += 1
        if scope == "campaign_tail":
            return CampaignTailResult(changed_segments)
        if scope == "shift_exchange":
            kwargs["tradeoffs"].append({"kind": "private_test"})
        return changed_segments

    paths = {
        "priority_inversions": "backend.scheduler.priority_normalization.repair_priority_inversions",
        "campaign_tail": "backend.scheduler.campaign_tail.repair_short_runs_after_merged_campaigns",
        "shift_exchange": "backend.scheduler.shift_exchange.repair_shift_capacity_exchange",
    }
    monkeypatch.setattr(paths[scope], attempt)

    def complete_context(residual_segments, residual_lots):
        return ([*copy.deepcopy(segments[:1]), *residual_segments],
                [*copy.deepcopy(lots[:1]), *residual_lots], data)

    generator = next(g for g in default_generators(data, config, evaluation_plan=complete_context)
                     if g.name == scope)
    proposed = list(generator.propose(copy.deepcopy(segments[1:]), copy.deepcopy(lots[1:])))
    assert len(proposed) == 1
    if change == "none":
        assert isinstance(proposed[0], Proposal)
        assert proposed[0].segments == segments[1:]
        assert proposed[0].lots == lots[1:]
        if scope == "shift_exchange":
            assert proposed[0].tradeoffs == [{"kind": "private_test"}]
    else:
        assert isinstance(proposed[0], SkippedProposal)
        assert proposed[0].reason == "protected_context_changed"
    assert (segments, lots, data, config) == original
