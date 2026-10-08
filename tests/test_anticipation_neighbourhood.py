"""Neighbourhood N1: earlier alternative placements for runs already on time.

Regression for the audited BFP186 case (plano-solver-2026-10-02 §2.1): the
delivery repair stopped as soon as delivery was complete, so an on-time run
that could start earlier on an eligible machine was never even a candidate.
Identifiers are parametrised: no rule may depend on a lot, tool or SKU name.
"""

from __future__ import annotations

import pytest

from backend.scheduler.alternative_repair import anticipation_proposals
from backend.scheduler.improvement import Proposal, improve_plan, production_windows
from backend.scheduler.validation import assert_plan_valid

from tests.test_alternative_repair import _config, _data, _op, _run_and_segment

NAMES = [("A", "T1"), ("BFP186", "BFP186"), ("Z9-renomeado", "FERR-77")]


def _on_time_plan(name: str, tool: str, *, blocked_m2: set[int] | None = None):
    op = _op(name, tool=tool, demand_day=3)
    _run, lot, segment = _run_and_segment(op, machine="M1", day=2, due=3)
    data = _data([op])
    data.machine_blocked_days = {"M1": {0, 1}, **({"M2": blocked_m2} if blocked_m2 else {})}
    config = _config()
    assert_plan_valid([segment], data, config, lots=[lot])
    return [segment], [lot], data, config


@pytest.mark.parametrize(("name", "tool"), NAMES)
def test_on_time_run_is_offered_an_earlier_alternative_machine(name, tool):
    segments, lots, data, config = _on_time_plan(name, tool)

    proposals = [item for item in anticipation_proposals(segments, lots, data, config)
                 if isinstance(item, Proposal)]

    assert [item.subject["to_machine"] for item in proposals] == ["M2"]
    moved = production_windows(proposals[0].segments)[lots[0].id]
    assert moved < production_windows(segments)[lots[0].id]
    assert_plan_valid(proposals[0].segments, data, config, lots=proposals[0].lots)


@pytest.mark.parametrize(("name", "tool"), NAMES)
def test_improvement_cycle_accepts_the_earlier_placement(name, tool):
    segments, lots, data, config = _on_time_plan(name, tool)

    improved, improved_lots, report = improve_plan(segments, lots, data, config)

    assert report["accepted_by_scope"].get("alternative_anticipation") == 1
    assert {segment.machine_id for segment in improved} == {"M2"}
    assert min(segment.day_idx for segment in improved) == 0
    assert sum(segment.qty for segment in improved) == sum(segment.qty for segment in segments)
    assert_plan_valid(improved, data, config, lots=improved_lots)


def test_no_proposal_before_the_replanning_boundary():
    segments, lots, data, config = _on_time_plan("A", "T1", blocked_m2={0})

    proposals = [item for item in anticipation_proposals(
        segments, lots, data, config, not_before_abs=1 * 1440,
    ) if isinstance(item, Proposal)]

    assert len(proposals) == 1
    assert min(segment.day_idx for segment in proposals[0].segments) == 1


def test_no_proposal_when_no_machine_is_earlier():
    segments, lots, data, config = _on_time_plan("A", "T1", blocked_m2={0, 1, 2, 3})

    assert not list(anticipation_proposals(segments, lots, data, config))


def test_protected_lot_is_never_moved():
    segments, lots, data, config = _on_time_plan("A", "T1")
    data.preserved_lot_proofs = {lots[0].id: "proof"}

    assert not list(anticipation_proposals(segments, lots, data, config))


# ── N2/N3: reinsertion of consecutive runs ───────────────────────────────


def _inverted_pair(first: str, second: str):
    """``first`` (due day 3) runs before the more urgent ``second`` (due day 1)
    on the only eligible machine; both released from day 0."""
    from dataclasses import replace

    late_op = _op(first, tool=f"T-{first}", alt=None, demand_day=3)
    urgent_op = _op(second, tool=f"T-{second}", alt=None, demand_day=1)
    _r1, late_lot, late_seg = _run_and_segment(late_op, machine="M1", day=0, due=3)
    _r2, urgent_lot, urgent_seg = _run_and_segment(urgent_op, machine="M1", day=0, due=1)
    urgent_seg = replace(urgent_seg, start_min=510, end_min=600)
    data, config = _data([late_op, urgent_op]), _config()
    segments, lots = [late_seg, urgent_seg], [late_lot, urgent_lot]
    assert_plan_valid(segments, data, config, lots=lots)
    return segments, lots, data, config


@pytest.mark.parametrize(("first", "second"), [("A", "B"), ("BFP202", "BFP188"), ("Z", "Y")])
def test_pair_reinsertion_puts_the_more_urgent_run_first(first, second):
    from backend.scheduler.alternative_repair import group_reinsertion_proposals

    segments, lots, data, config = _inverted_pair(first, second)

    proposals = [item for item in group_reinsertion_proposals(
        segments, lots, data, config, size=2,
    ) if isinstance(item, Proposal)]

    assert proposals
    best = proposals[0]
    windows = production_windows(best.segments)
    urgent, late = f"LOT-{second}", f"LOT-{first}"
    assert windows[urgent] < production_windows(segments)[urgent]
    assert windows[urgent][0] < windows[late][0]
    assert_plan_valid(best.segments, data, config, lots=best.lots)


def test_no_group_proposal_when_every_run_starts_at_its_floor():
    from dataclasses import replace

    from backend.scheduler.alternative_repair import group_reinsertion_proposals

    segments, lots, data, config = _inverted_pair("A", "B")
    # Consecutive on M1, each already starting at its own material release.
    lots[1].material_release_day = 1
    segments = [segments[0], replace(segments[1], day_idx=1, start_min=420, end_min=510)]
    assert_plan_valid(segments, data, config, lots=lots)

    assert not list(group_reinsertion_proposals(segments, lots, data, config, size=2))


def test_group_with_a_protected_run_is_never_moved():
    from backend.scheduler.alternative_repair import group_reinsertion_proposals

    segments, lots, data, config = _inverted_pair("A", "B")
    data.preserved_lot_proofs = {"LOT-A": "proof"}

    assert not list(group_reinsertion_proposals(segments, lots, data, config, size=2))


# ── N4: local CP-SAT over a coupled group ────────────────────────────────


@pytest.mark.parametrize(("first", "second"), [("A", "B"), ("Z", "Y")])
def test_local_cpsat_orders_the_coupled_group_by_priority(first, second):
    from backend.scheduler.local_cpsat import local_cpsat_proposals

    segments, lots, data, config = _inverted_pair(first, second)

    proposals = [item for item in local_cpsat_proposals(segments, lots, data, config)
                 if isinstance(item, Proposal)]

    assert proposals
    windows = production_windows(proposals[0].segments)
    assert windows[f"LOT-{second}"][0] < windows[f"LOT-{first}"][0]
    assert_plan_valid(proposals[0].segments, data, config, lots=proposals[0].lots)


def test_local_cpsat_stops_on_cancellation():
    from threading import Event

    from backend.planning_control import PlanningCancelled, planning_scope
    from backend.scheduler.local_cpsat import local_cpsat_proposals

    segments, lots, data, config = _inverted_pair("A", "B")
    cancelled = Event()
    with pytest.raises(PlanningCancelled), planning_scope(cancel_event=cancelled):
        # Cancelled after the scope started: only the neighbourhood's own
        # checkpoints can raise.
        cancelled.set()
        list(local_cpsat_proposals(segments, lots, data, config))
