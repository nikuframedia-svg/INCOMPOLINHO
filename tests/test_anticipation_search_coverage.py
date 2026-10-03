"""Finite anticipation search must not discard later eligible placements."""

import copy
import math
from threading import Event

import pytest

from backend.planning_control import PlanningCancelled, planning_scope
from backend.scheduler import alternative_repair
from backend.scheduler.improvement import (
    MAX_PROPOSALS_PER_CALL,
    MAX_SKIPPED_PER_CALL,
    Proposal,
    SkippedProposal,
    default_generators,
    improve_plan,
    production_windows,
)
from backend.scheduler.validation import assert_plan_valid
from tests.test_anticipation_neighbourhood import _on_time_plan

FINITE_SCOPES = [
    ("alternative_anticipation", "anticipation_proposals"),
    ("pair_reinsertion", "group_reinsertion_proposals"),
    ("triple_reinsertion", "group_reinsertion_proposals"),
]


@pytest.mark.parametrize("prefix", ["duplicates", "physical", "contract", "skipped"])
@pytest.mark.parametrize("name", ["BFP186", "RENAMED"])
@pytest.mark.parametrize(("scope", "function"), FINITE_SCOPES)
def test_later_anticipation_is_not_lost_to_the_generic_proposal_cap(
    monkeypatch, prefix, name, scope, function,
):
    segments, lots, data, config = _on_time_plan(name, "TOOL")
    original = copy.deepcopy((segments, lots, data, config))
    candidate = next(item for item in alternative_repair.anticipation_proposals(
        segments, lots, data, config,
    ) if isinstance(item, Proposal))

    def hypotheses(*_args, **_kwargs):
        limit = MAX_SKIPPED_PER_CALL if prefix == "skipped" else MAX_PROPOSALS_PER_CALL
        for index in range(limit + 1):
            if prefix == "skipped":
                yield SkippedProposal({"key": f"skip:{index}"}, "physical")
            elif prefix == "duplicates":
                yield Proposal(copy.deepcopy(segments), copy.deepcopy(lots))
            else:
                broken = copy.deepcopy(candidate.segments)
                if prefix == "contract":
                    for segment in broken:
                        segment.day_idx = 4 + index * 7
                else:
                    broken[0].qty += index + 1
                yield Proposal(broken, candidate.lots)
        yield candidate

    monkeypatch.setattr(alternative_repair, function, hypotheses)
    generator = next(item for item in default_generators(data, config)
                     if item.name == scope)
    improved, improved_lots, report = improve_plan(
        segments, lots, data, config, generators=[generator], time_budget_s=2,
    )

    assert report["moves_accepted"] == 1
    assert report["accepted_by_scope"] == {scope: 1}
    assert {segment.machine_id for segment in improved} == {"M2"}
    assert not report["limited_by_scope"]
    assert_plan_valid(improved, data, config, lots=improved_lots)
    assert (segments, lots, data, config) == original


def test_on_time_anticipation_preserves_a_manual_anchor():
    from backend.types import PlanAnchor

    segments, lots, data, config = _on_time_plan("A", "TOOL")
    data.plan_anchors = [PlanAnchor(lots[0].id, "M1", "2026-09-16T07:30")]
    assert_plan_valid(segments, data, config, lots=lots)
    proposals = list(alternative_repair.anticipation_proposals(segments, lots, data, config))
    assert not any(isinstance(item, Proposal) for item in proposals)


def test_on_time_anticipation_respects_the_material_release():
    segments, lots, data, config = _on_time_plan("A", "TOOL")
    lots[0].material_release_day = 1
    candidate = next(item for item in alternative_repair.anticipation_proposals(
        segments, lots, data, config,
    ) if isinstance(item, Proposal))
    assert min(segment.day_idx for segment in candidate.segments) == 1
    assert_plan_valid(candidate.segments, data, config, lots=candidate.lots)


@pytest.mark.parametrize(("scope", "function"), FINITE_SCOPES)
def test_finite_anticipation_still_obeys_cancellation(monkeypatch, scope, function):
    segments, lots, data, config = _on_time_plan("A", "TOOL")
    original = copy.deepcopy((segments, lots, data, config))
    event = Event()

    def hypotheses(*_args, **_kwargs):
        for index in range(MAX_SKIPPED_PER_CALL + 5):
            if index == MAX_SKIPPED_PER_CALL + 1:
                event.set()
            yield SkippedProposal({"key": str(index)}, "physical")

    monkeypatch.setattr(alternative_repair, function, hypotheses)
    generator = next(item for item in default_generators(data, config)
                     if item.name == scope)

    with pytest.raises(PlanningCancelled), planning_scope(timeout_s=2, cancel_event=event):
        improve_plan(segments, lots, data, config, generators=[generator])
    assert (segments, lots, data, config) == original


@pytest.mark.parametrize(("scope", "function"), FINITE_SCOPES)
def test_finite_anticipation_still_obeys_the_shared_deadline(monkeypatch, scope, function):
    segments, lots, data, config = _on_time_plan("A", "TOOL")
    original = copy.deepcopy((segments, lots, data, config))
    clock = [0.0]

    def hypotheses(*_args, **_kwargs):
        for index in range(MAX_SKIPPED_PER_CALL + 5):
            if index == MAX_SKIPPED_PER_CALL + 1:
                clock[0] = 2.0
            yield SkippedProposal({"key": str(index)}, "physical")

    monkeypatch.setattr(alternative_repair, function, hypotheses)
    generator = next(item for item in default_generators(data, config)
                     if item.name == scope)
    with planning_scope(timeout_s=2, clock=lambda: clock[0], check_on_exit=False):
        improved, improved_lots, report = improve_plan(
            segments, lots, data, config, generators=[generator],
        )
    assert report["status"] == "partial"
    assert report["stop_reason"] == "budget"
    assert (improved, improved_lots) == (segments, lots)
    assert (segments, lots, data, config) == original


@pytest.mark.parametrize("kind", ["machine", "tool", "operators"])
def test_on_time_anticipation_respects_resource_outages_and_their_removal(kind):
    segments, lots, data, config = _on_time_plan("A", "TOOL")
    config.operators = {("Grandes", shift): 1 for shift in ("A", "B")}
    block = {"start_day": 0, "end_day": 0, "start_min": 420, "end_min": 600}
    if kind == "operators":
        data.operator_blocked_intervals = [{**block, "group": "Grandes", "shift": "A", "count": 1}]
    else:
        getattr(data, f"{kind}_blocked_intervals")["M2" if kind == "machine" else "TOOL"] = [block]
    original = copy.deepcopy((segments, lots, data, config))
    with planning_scope(timeout_s=2):
        candidates = [item for item in alternative_repair.anticipation_proposals(
            segments, lots, data, config,
        ) if isinstance(item, Proposal)]
        assert candidates
        before = production_windows(candidates[0].segments)[lots[0].id][0]
        # An operator absence blocks production only; a resource outage also blocks setup.
        assert before == (600 if kind == "operators" else 630)
        assert_plan_valid(candidates[0].segments, data, config, lots=candidates[0].lots)
        assert (segments, lots, data, config) == original
        resource = "operator" if kind == "operators" else kind
        getattr(data, f"{resource}_blocked_intervals").clear()
        released = [item for item in alternative_repair.anticipation_proposals(
            segments, lots, data, config,
        ) if isinstance(item, Proposal)]
        assert production_windows(released[0].segments)[lots[0].id][0] == 450
        assert_plan_valid(released[0].segments, data, config, lots=released[0].lots)


@pytest.mark.parametrize("oee", [.44, .66, 1.0])
def test_on_time_anticipation_rebinds_destination_duration(oee):
    segments, lots, data, config = _on_time_plan("A", "TOOL")
    config.machines["M2"].oee = oee
    candidate = next(item for item in alternative_repair.anticipation_proposals(
        segments, lots, data, config,
    ) if isinstance(item, Proposal))
    assert sum(segment.prod_min for segment in candidate.segments) == math.ceil(60 / oee)
    assert sum(segment.qty for segment in candidate.segments) == lots[0].qty
    assert {segment.lot_id for segment in candidate.segments} == {lots[0].id}
    assert_plan_valid(candidate.segments, data, config, lots=candidate.lots)
