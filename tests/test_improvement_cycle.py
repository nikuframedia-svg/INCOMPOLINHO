"""Single no-loss improvement cycle (plan-melhoria §5, §8.2, §8.3)."""

from __future__ import annotations

import dataclasses
import copy

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.improvement import Generator, Proposal, improve_plan
from backend.scheduler.types import Lot, Segment
from backend.types import ClientDemandEntry, EngineData, EOp, MachineInfo


def _op(op_id: str, sku: str, tool: str, due: int) -> EOp:
    d = [0] * 8
    d[due] = 100
    return EOp(
        id=op_id, sku=sku, client="CLI", designation=sku, m="M1", t=tool,
        pH=100.0, sH=0.5, operators=1, eco_lot=0, alt=None, stk=0,
        backlog=0, d=d, oee=1.0, wip=0,
    )


@pytest.fixture
def plan():
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    data = EngineData(
        ops=[_op("OP-A", "A", "TA", 5), _op("OP-B", "B", "TB", 6)],
        machines=[MachineInfo("M1", "Grandes", 1020)],
        twin_groups=[],
        client_demands={
            "A": [ClientDemandEntry("X", "A", 5, "", 100, -100)],
            "B": [ClientDemandEntry("Y", "B", 6, "", 100, -100)],
        },
        workdays=[f"2026-10-{day:02d}" for day in (5, 6, 7, 8, 9, 12, 13, 14)],
        n_days=8,
    )
    lots = [
        Lot("LA", "OP-A", "TA", "M1", None, 100, 60, 30, 5, False, sku="A"),
        Lot("LB", "OP-B", "TB", "M1", None, 100, 60, 30, 6, False, sku="B"),
    ]
    segments = [
        Segment("LA", "RA", "M1", "TA", 3, 420, 510, "A", 100, 60, 30, sku="A"),
        Segment("LB", "RB", "M1", "TB", 4, 420, 510, "A", 100, 60, 30, sku="B"),
    ]
    return segments, lots, data, config


def _moved(segments, lot_id, **changes):
    return [
        dataclasses.replace(s, **changes) if s.lot_id == lot_id else dataclasses.replace(s)
        for s in segments
    ]


def _gen(name, fn):
    return Generator(name, lambda segments, lots: Proposal(fn(segments), lots))


def test_admissible_earlier_start_is_incorporated_and_cycle_is_idempotent(plan):
    segments, lots, data, config = plan
    earlier = _gen("earlier_b", lambda segs: _moved(segs, "LB", start_min=510, end_min=600, day_idx=3))

    improved, _lots, report = improve_plan(segments, lots, data, config, generators=[earlier])

    assert report["status"] == "completed"
    assert report["moves_accepted"] == 1
    assert [(s.lot_id, s.day_idx, s.start_min) for s in improved] == [
        ("LA", 3, 420), ("LB", 3, 510),
    ]
    again, _lots, second = improve_plan(improved, lots, data, config, generators=[earlier])
    assert second["moves_accepted"] == 0
    assert [(s.day_idx, s.start_min) for s in again] == [(s.day_idx, s.start_min) for s in improved]


def test_individual_order_loss_is_rejected_even_if_other_order_gains(plan):
    segments, lots, data, config = plan
    # A becomes earlier but B is pushed past its due day 6.
    swap = _gen("swap", lambda segs: [
        dataclasses.replace(segs[0], day_idx=2),
        dataclasses.replace(segs[1], day_idx=7),
    ])

    improved, _lots, report = improve_plan(segments, lots, data, config, generators=[swap])

    assert report["moves_accepted"] == 0
    assert report["rejections"] == {"swap:contract": 1}
    assert report["tradeoffs"]["count"] == 1
    assert improved == segments


def test_earlier_start_with_extra_setup_is_accepted(plan):
    """Decision of 02/10/2026 (AGENTS.md §1.5): a second setup does not veto
    an anticipation that keeps every order."""
    segments, lots, data, config = plan

    def split_with_second_setup(segs):
        if len(segs) != 2:
            return segs
        a, b = segs
        return [
            dataclasses.replace(a, end_min=465, qty=50, prod_min=15.0),
            dataclasses.replace(a, day_idx=2, run_id="RA2", qty=50, prod_min=45.0,
                                end_min=495),
            dataclasses.replace(b),
        ]

    improved, _lots, report = improve_plan(
        segments, lots, data, config, generators=[_gen("split", split_with_second_setup)],
    )
    assert report["moves_accepted"] == 1
    assert min(s.day_idx for s in improved if s.lot_id == "LA") == 2
    assert report["final"]["physical_setups"] == report["reference"]["physical_setups"] + 1



def test_physically_invalid_proposal_never_becomes_current(plan):
    segments, lots, data, config = plan
    overlap = _gen("overlap", lambda segs: _moved(segs, "LB", day_idx=3, start_min=450, end_min=540))

    improved, _lots, report = improve_plan(segments, lots, data, config, generators=[overlap])

    assert report["rejections"] == {"overlap:physical": 1}
    assert improved == segments


def test_rejected_attempt_cannot_mutate_the_current_candidate(plan):
    segments, lots, data, config = plan

    def vandal(segs):
        for segment in segs:
            segment.day_idx = 0  # mutates its own copy only
        segs[0].start_min = segs[1].start_min
        return segs

    improved, _lots, _report = improve_plan(
        segments, lots, data, config, generators=[_gen("vandal", vandal)],
    )
    assert [(s.day_idx, s.start_min) for s in improved] == [(3, 420), (4, 420)]
    assert [(s.day_idx, s.start_min) for s in segments] == [(3, 420), (4, 420)]


def test_rejected_attempt_cannot_mutate_nested_production_metadata(plan):
    segments, lots, data, config = plan
    lots[0].output_milestones = [{"qty": 100, "notes": ["original"]}]
    segments[0].output_milestones = copy.deepcopy(lots[0].output_milestones)
    expected_lots = copy.deepcopy(lots)
    expected_segments = copy.deepcopy(segments)

    def rejected(segs, candidate_lots):
        candidate_lots[0].output_milestones[0]["notes"].append("candidate")
        segs[0].output_milestones[0]["notes"].append("candidate")
        segs[1].day_idx = segs[0].day_idx
        return Proposal(segs, candidate_lots)

    improved, result_lots, report = improve_plan(
        segments, lots, data, config, generators=[Generator("rejected", rejected)],
    )

    assert report["moves_accepted"] == 0
    assert improved == expected_segments
    assert result_lots == expected_lots
    assert segments == expected_segments
    assert lots == expected_lots


def test_improvement_cannot_replace_production_id_even_with_earlier_service(plan):
    segments, lots, data, config = plan

    def renamed(segs, candidate_lots):
        segs[1].lot_id = candidate_lots[1].id = "NEW-LB"
        segs[1].day_idx = 3
        segs[1].start_min, segs[1].end_min = 510, 600
        return Proposal(segs, candidate_lots)

    improved, result_lots, report = improve_plan(
        segments, lots, data, config, generators=[Generator("renamed", renamed)],
    )

    assert report["moves_accepted"] == 0
    assert improved == segments
    assert result_lots == lots


def test_oscillating_generator_terminates(plan):
    segments, lots, data, config = plan
    states = [
        lambda segs: _moved(segs, "LB", day_idx=3, start_min=510, end_min=600),
        lambda segs: _moved(segs, "LB", day_idx=4, start_min=420, end_min=510),
    ]
    flip = {"n": 0}

    def oscillate(segs):
        flip["n"] += 1
        return states[(flip["n"] - 1) % 2](segs)

    _improved, _lots, report = improve_plan(
        segments, lots, data, config, generators=[_gen("oscillate", oscillate)],
    )
    assert report["status"] == "completed"
    assert report["moves_accepted"] == 1
    assert report["duplicates_skipped"] >= 1


def test_zero_budget_is_partial_and_keeps_the_valid_reference(plan):
    segments, lots, data, config = plan
    earlier = _gen("earlier_b", lambda segs: _moved(segs, "LB", day_idx=3, start_min=510, end_min=600))

    improved, _lots, report = improve_plan(
        segments, lots, data, config, generators=[earlier], time_budget_s=0.0,
    )
    assert report["status"] == "partial"
    assert report["stop_reason"] == "budget"
    assert improved == segments


def test_invalid_reference_is_not_evaluated(plan):
    segments, lots, data, config = plan
    broken = _moved(segments, "LB", day_idx=3, start_min=450, end_min=540)

    _improved, _lots, report = improve_plan(broken, lots, data, config, generators=[])
    assert report["status"] == "not_evaluated"
    assert report["stop_reason"] == "reference_invalid"


# ── Protected lots are never moved by an improvement (plan §4.1) ────────


def test_proposal_moving_a_preserved_lot_is_rejected(plan):
    from backend.scheduler.canonical import preserved_lot_proofs

    segments, lots, data, config = plan
    data.preserved_lot_proofs = preserved_lot_proofs(
        [s for s in segments if s.lot_id == "LB"], [lots[1]],
    )
    earlier = _gen("move_preserved", lambda segs: _moved(
        segs, "LB", day_idx=3, start_min=510, end_min=600,
    ))

    improved, _lots, report = improve_plan(segments, lots, data, config, generators=[earlier])

    assert report["moves_accepted"] == 0
    assert report["rejections"] == {"move_preserved:physical": 1}
    assert [(s.day_idx, s.start_min) for s in improved] == [(3, 420), (4, 420)]


def test_proposal_breaking_a_manual_anchor_is_rejected(plan):
    from backend.types import PlanAnchor

    segments, lots, data, config = plan
    # LB is anchored where it is: production at 07:30 on 2026-10-09 (day 4).
    data.plan_anchors = [PlanAnchor("LB", "M1", "2026-10-09T07:30")]
    earlier = _gen("move_anchor", lambda segs: _moved(
        segs, "LB", day_idx=3, start_min=510, end_min=600,
    ))

    improved, _lots, report = improve_plan(segments, lots, data, config, generators=[earlier])

    assert report["moves_accepted"] == 0
    assert report["rejections"] == {"move_anchor:physical": 1}
    assert [(s.day_idx, s.start_min) for s in improved] == [(3, 420), (4, 420)]


def test_other_lots_still_improve_next_to_protected_ones(plan):
    from backend.types import PlanAnchor

    segments, lots, data, config = plan
    data.plan_anchors = [PlanAnchor("LA", "M1", "2026-10-08T07:30")]
    earlier = _gen("earlier_b", lambda segs: _moved(
        segs, "LB", day_idx=3, start_min=510, end_min=600,
    ))

    _improved, _lots, report = improve_plan(segments, lots, data, config, generators=[earlier])

    assert report["moves_accepted"] == 1


# ── Several proposals per generator (plan §5.3) ─────────────────────────


def _iterable(name, factories):
    from backend.scheduler.improvement import Proposal

    def propose(segments, lots):
        for key, factory in factories:
            item = factory(segments)
            if not isinstance(item, list):
                yield item
            else:
                yield Proposal(item, lots, subject={"key": key})

    return Generator(name, propose)


def test_iterable_generator_second_proposal_accepted_after_first_rejected(plan):
    segments, lots, data, config = plan
    swap = lambda segs: [dataclasses.replace(segs[0], day_idx=2),  # noqa: E731
                         dataclasses.replace(segs[1], day_idx=7)]
    earlier = lambda segs: _moved(segs, "LB", day_idx=3, start_min=510, end_min=600)  # noqa: E731

    _improved, _lots, report = improve_plan(
        segments, lots, data, config,
        generators=[_iterable("multi", [("bad", swap), ("good", earlier)])],
    )

    assert report["moves_accepted"] == 1
    assert report["proposal_log"]["bad"]["outcome"] == "rejected"
    assert report["proposal_log"]["bad"]["reason"] == "contract"
    assert report["proposal_log"]["good"]["outcome"] == "accepted"
    assert report["evaluations_by_scope"]["multi"] >= 2


def test_skipped_proposal_is_logged_not_evaluated(plan):
    from backend.scheduler.improvement import SkippedProposal

    segments, lots, data, config = plan
    skip = lambda _segs: SkippedProposal({"key": "hop-1"}, "protected", ("lote iniciado",))  # noqa: E731

    _improved, _lots, report = improve_plan(
        segments, lots, data, config, generators=[_iterable("multi", [("x", skip)])],
    )

    assert report["candidates_evaluated"] == 0
    assert report["skipped_by_scope"] == {"multi": 1}
    assert report["proposal_log"]["hop-1"]["reason"] == "protected"


def test_proposals_per_call_are_capped(plan):
    from backend.scheduler.improvement import MAX_SKIPPED_PER_CALL, SkippedProposal

    segments, lots, data, config = plan
    pulled = {"n": 0}

    def propose(_segments, _lots):
        while True:
            pulled["n"] += 1
            yield SkippedProposal({"key": f"k{pulled['n']}"}, "unschedulable")

    _, _, report = improve_plan(segments, lots, data, config, generators=[Generator("endless", propose)])

    assert pulled["n"] <= MAX_SKIPPED_PER_CALL + 1
    assert report["status"] == "partial"
    assert report["stop_reason"] == "search_limit"
    assert report["limited_by_scope"] == {"endless": 1}


def test_proposal_limit_does_not_claim_all_hypotheses_were_checked(plan):
    from backend.scheduler.improvement import MAX_PROPOSALS_PER_CALL

    segments, lots, data, config = plan

    def many(segs, candidate_lots):
        for _ in range(MAX_PROPOSALS_PER_CALL):
            yield Proposal(copy.deepcopy(segs), candidate_lots)
        yield Proposal(_moved(segs, "LB", day_idx=3, start_min=510, end_min=600), candidate_lots)

    improved, _, report = improve_plan(
        segments, lots, data, config, generators=[Generator("many", many)],
    )
    assert improved == segments
    assert report["status"] == "partial"
    assert report["stop_reason"] == "search_limit"
    assert report["limited_by_scope"] == {"many": 1}


def test_limited_scope_does_not_prevent_other_scopes_improving(plan):
    from backend.scheduler.improvement import MAX_SKIPPED_PER_CALL, SkippedProposal

    segments, lots, data, config = plan

    def many(_segs, _lots):
        for index in range(MAX_SKIPPED_PER_CALL + 1):
            yield SkippedProposal({"key": str(index)}, "unschedulable")

    earlier = _gen("earlier", lambda segs: _moved(segs, "LB", day_idx=3, start_min=510, end_min=600))
    improved, _, report = improve_plan(
        segments, lots, data, config,
        generators=[_gen("compact", lambda segs: segs), Generator("limited", many), earlier],
    )
    assert next(s.day_idx for s in improved if s.lot_id == "LB") == 3
    assert report["moves_accepted"] == 1
    assert report["status"] == "partial"


def test_evaluation_limit_stops_as_partial(plan):
    segments, lots, data, config = plan
    earlier = lambda segs: _moved(segs, "LB", day_idx=3, start_min=510, end_min=600)  # noqa: E731

    improved, _lots, report = improve_plan(
        segments, lots, data, config, generators=[_gen("earlier_b", earlier)],
        max_evaluations=0,
    )

    assert report["status"] == "partial"
    assert report["stop_reason"] == "evaluation_limit"
    assert improved == segments


def test_explicit_incomplete_scope_does_not_hide_later_hypotheses(plan):
    from backend.scheduler.improvement import SkippedProposal

    segments, lots, data, config = plan

    def alternatives(segs, candidate_lots):
        yield SkippedProposal({"key": "bounded"}, "scope_limited", scope_limited=True)
        yield Proposal(_moved(segs, "LB", day_idx=3, start_min=510, end_min=600), candidate_lots)

    improved, _, report = improve_plan(
        segments, lots, data, config,
        generators=[_gen("compact", lambda segs: segs), Generator("alternatives", alternatives)],
    )
    assert report["moves_accepted"] == 1
    assert next(s.day_idx for s in improved if s.lot_id == "LB") == 3
    assert report["status"] == "partial"
    assert report["stop_reason"] == "search_limit"


def test_limit_of_an_old_state_does_not_mark_the_new_state_incomplete(plan):
    from backend.scheduler.improvement import SkippedProposal

    segments, lots, data, config = plan

    def limited_only_before_move(segs, candidate_lots):
        if next(s.day_idx for s in segs if s.lot_id == "LB") == 4:
            return SkippedProposal({"key": "old-limit"}, "scope_limited", scope_limited=True)
        return Proposal(segs, candidate_lots)

    earlier = _gen("earlier", lambda segs: _moved(segs, "LB", day_idx=3, start_min=510, end_min=600))
    _, _, report = improve_plan(
        segments, lots, data, config,
        generators=[_gen("compact", lambda segs: segs),
                    Generator("limited", limited_only_before_move), earlier],
    )
    assert report["moves_accepted"] == 1
    assert report["limited_by_scope"] == {"limited": 1}
    assert report["status"] == "completed"


def test_incomplete_closing_pass_keeps_the_validated_move_and_is_partial(plan):
    """Every accepted move is validated in full: a closing compaction that
    cannot complete its scope never discards it, it only marks the search
    partial (§5.6, §9.3)."""
    from backend.scheduler.improvement import SkippedProposal

    segments, lots, data, config = plan

    def closing(segs, candidate_lots):
        if next(s.day_idx for s in segs if s.lot_id == "LB") == 3:
            return SkippedProposal({"key": "closing-limit"}, "scope_limited", scope_limited=True)
        return Proposal(segs, candidate_lots)

    earlier = _gen("earlier", lambda segs: _moved(segs, "LB", day_idx=3, start_min=510, end_min=600))
    improved, _, report = improve_plan(
        segments, lots, data, config, generators=[Generator("compact", closing), earlier],
    )
    assert next(s.day_idx for s in improved if s.lot_id == "LB") == 3
    assert report["moves_accepted"] == 1
    assert "rolled_back_moves" not in report
    assert report["limited_by_scope"] == {"compact": 1}
    assert report["closing_compaction"] == "no_gain"
    assert report["status"] == "partial"
    assert report["stop_reason"] == "search_limit"


def test_log_is_bound_to_the_state_it_was_judged_on(plan):
    segments, lots, data, config = plan
    earlier = lambda segs: _moved(segs, "LB", day_idx=3, start_min=510, end_min=600)  # noqa: E731

    _improved, _lots, report = improve_plan(
        segments, lots, data, config,
        generators=[_iterable("multi", [("good", earlier)])],
    )

    # Judged on the reference state, which is no longer the final one.
    assert report["proposal_log"]["good"]["on_signature"] != report["final_signature"]
    assert report["final"]["tool_transfers"] == 0


def test_compaction_runs_once_when_the_search_stops_not_after_every_move(plan):
    """The compaction is costly: accepted moves follow one another and the
    compaction closes the search once, on the final candidate."""

    segments, lots, data, config = plan
    calls = []

    def compact(segs, candidate_lots):
        calls.append(sorted((s.lot_id, s.day_idx, s.start_min) for s in segs))
        return Proposal(segs, candidate_lots)

    def steps(segs, candidate_lots):
        lb = next(s for s in segs if s.lot_id == "LB")
        if (lb.day_idx, lb.start_min) == (4, 600):
            return Proposal(_moved(segs, "LB", start_min=420, end_min=510), candidate_lots)
        if lb.day_idx == 4:
            return Proposal(_moved(segs, "LB", day_idx=3, start_min=510, end_min=600),
                            candidate_lots)
        return Proposal(segs, candidate_lots)

    shifted = _moved(segments, "LB", start_min=600, end_min=690)
    improved, _, report = improve_plan(
        shifted, lots, data, config,
        generators=[Generator("compact", compact), Generator("steps", steps)],
    )
    assert next(s.day_idx for s in improved if s.lot_id == "LB") == 3
    assert report["accepted_by_scope"] == {"steps": 2}
    assert report["compactions"] == 1
    assert calls == [[("LA", 3, 420), ("LB", 3, 510)]]
    assert report["closing_compaction"] == "no_gain"
    assert report["status"] == "completed"


def test_accepted_closing_compaction_resumes_the_search(plan):
    """Time released by the compaction is searched again; the result is
    completed only when neither the generators nor the compaction gain."""

    segments, lots, data, config = plan

    def compact(segs):
        if next(s for s in segs if s.lot_id == "LA").day_idx == 2:
            return _moved(segs, "LB", day_idx=3, start_min=420, end_min=510)
        return [dataclasses.replace(s) for s in segs]

    def after_compaction(segs):
        lb = next(s for s in segs if s.lot_id == "LB")
        if (lb.day_idx, lb.start_min) == (3, 420):
            return _moved(segs, "LB", day_idx=2, start_min=510, end_min=600)
        return _moved(segs, "LA", day_idx=2)

    improved, _, report = improve_plan(
        segments, lots, data, config,
        generators=[_gen("compact", compact), _gen("group", after_compaction)],
    )
    assert [(s.lot_id, s.day_idx) for s in improved] == [("LA", 2), ("LB", 2)]
    assert report["accepted_by_scope"] == {"group": 2, "compact": 1}
    assert report["compactions"] == 2
    assert report["status"] == "completed"


def test_compaction_every_k_accepted_moves(plan):
    segments, lots, data, config = plan
    calls = []

    def compact(segs, candidate_lots):
        calls.append(next(s.start_min for s in segs if s.lot_id == "LB"))
        return Proposal(segs, candidate_lots)

    def steps(segs, candidate_lots):
        lb = next(s for s in segs if s.lot_id == "LB")
        if lb.day_idx == 4 and lb.start_min > 420:
            return Proposal(_moved(segs, "LB", start_min=lb.start_min - 30,
                                   end_min=lb.end_min - 30), candidate_lots)
        return Proposal(segs, candidate_lots)

    shifted = _moved(segments, "LB", start_min=600, end_min=690)
    _, _, report = improve_plan(
        shifted, lots, data, config,
        generators=[Generator("compact", compact), Generator("steps", steps)],
        compaction_every=2,
    )
    assert report["accepted_by_scope"] == {"steps": 6}
    # After the 2nd, 4th and 6th accepted move; the closing pass finds the
    # last plan already compacted.
    assert calls == [540, 480, 420]


def test_group_move_is_compacted_before_the_plan_is_returned(plan):
    """§5.6: time released by a group move is used before the plan is returned."""

    segments, lots, data, config = plan

    def compact(segs):
        if next(s for s in segs if s.lot_id == "LA").day_idx == 2:
            return _moved(segs, "LB", day_idx=3, start_min=420, end_min=510)
        return [dataclasses.replace(s) for s in segs]

    group = lambda segs: _moved(segs, "LA", day_idx=2)  # noqa: E731

    improved, _lots, report = improve_plan(
        segments, lots, data, config,
        generators=[_gen("compact", compact), _gen("group", group)],
        max_evaluations=2,
    )

    # The evaluation limit stops the search one evaluation early; the
    # closing compaction still runs on the accepted group move, inside the
    # limit (the compaction's evaluation counts).
    assert report["stop_reason"] == "evaluation_limit"
    assert report["accepted_by_scope"] == {"group": 1, "compact": 1}
    assert report["candidates_evaluated"] == 2
    assert [(s.lot_id, s.day_idx) for s in improved] == [("LA", 2), ("LB", 3)]


@pytest.mark.parametrize("limit", [0, 1, 2, 3])
def test_compaction_never_exceeds_the_evaluation_limit(plan, limit):
    """``max_evaluations`` bounds every evaluated candidate, the closing
    compaction's included (it keeps one evaluation of the limit)."""

    segments, lots, data, config = plan

    def compact(segs):
        if next(s for s in segs if s.lot_id == "LA").day_idx == 2:
            return _moved(segs, "LB", day_idx=3, start_min=420, end_min=510)
        return [dataclasses.replace(s) for s in segs]

    group = lambda segs: _moved(segs, "LA", day_idx=2)  # noqa: E731

    _improved, _lots, report = improve_plan(
        segments, lots, data, config,
        generators=[_gen("compact", compact), _gen("group", group)],
        max_evaluations=limit,
    )

    assert report["candidates_evaluated"] <= limit
    if limit >= 2:
        assert report["accepted_by_scope"] == {"group": 1, "compact": 1}


def test_interrupted_compaction_keeps_the_last_validated_candidate(plan):
    from backend.planning_control import PlanningTimeout

    segments, lots, data, config = plan

    def compact(segs):
        raise PlanningTimeout("budget ended during compaction")

    group = lambda segs: _moved(segs, "LA", day_idx=2)  # noqa: E731

    improved, _lots, report = improve_plan(
        segments, lots, data, config,
        generators=[_gen("compact", compact), _gen("group", group)],
    )

    assert report["stop_reason"] == "budget"
    assert report["status"] == "partial"
    assert report["closing_compaction"] == "interrupted"
    assert "rolled_back_moves" not in report
    assert report["moves_accepted"] == 1
    assert report["accepted_by_scope"] == {"group": 1}
    assert [(s.day_idx, s.start_min) for s in improved] == [(2, 420), (4, 420)]


def test_search_keeps_a_reserve_for_the_closing_compaction(plan, monkeypatch):
    """When the search part of the budget is spent the compaction still
    runs, inside the reserve, on the last accepted candidate."""
    from backend.scheduler import improvement as module

    segments, lots, data, config = plan
    clock = {"now": 0.0}
    monkeypatch.setattr(module, "CLOSING_COMPACTION_SHARE", 0.5)

    import time as time_module
    monkeypatch.setattr(time_module, "monotonic", lambda: clock["now"])
    compacted = []

    def compact(segs, candidate_lots):
        compacted.append(next(s.day_idx for s in segs if s.lot_id == "LB"))
        return Proposal(segs, candidate_lots)

    def earlier(segs, candidate_lots):
        clock["now"] += 4.0  # the search part (10 s of 20 s) ends in the third call
        lb = next(s for s in segs if s.lot_id == "LB")
        return Proposal(_moved(segs, "LB", day_idx=lb.day_idx - 1, start_min=510, end_min=600),
                        candidate_lots)

    shifted = _moved(segments, "LB", day_idx=6)
    _, _, report = improve_plan(
        shifted, lots, data, config,
        generators=[Generator("compact", compact), Generator("earlier", earlier)],
        time_budget_s=20.0,
    )
    assert report["stop_reason"] == "budget"
    # Two moves, the compaction inside the reserve; it took no time on this
    # clock, so the search resumed with the time left and made one more move
    # before the phase ended (that last plan is not compacted).
    assert report["accepted_by_scope"] == {"earlier": 3}
    assert compacted == [4]
    assert report["compactions"] == 1
    assert report["closing_compaction"] == "not_run"


def test_leading_generator_opens_every_round(plan):
    """A ``leading`` generator (the priority rotations) is tried first in
    every round, also after another generator succeeded."""

    segments, lots, data, config = plan
    calls: list[str] = []

    def leading(segs, candidate_lots):
        calls.append("leading")
        return iter(())

    def earlier(segs, candidate_lots):
        calls.append("earlier")
        return Proposal(_moved(segs, "LB", day_idx=3, start_min=510, end_min=600), candidate_lots)

    _improved, _lots, report = improve_plan(
        segments, lots, data, config,
        generators=[
            _gen("compact", lambda segs: segs),
            Generator("earlier", earlier),
            Generator("leading", leading, leading=True),
        ],
    )

    assert report["accepted_by_scope"] == {"earlier": 1}
    assert calls[:4] == ["leading", "earlier", "leading", "earlier"]
