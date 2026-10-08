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


def test_incomplete_closing_pass_returns_the_last_settled_candidate(plan):
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
    assert improved == segments
    assert report["moves_accepted"] == 0
    assert report["rolled_back_moves"] == 1
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


def test_rolled_back_group_move_is_not_logged_as_an_applied_move(plan):
    from backend.scheduler.improvement import SkippedProposal

    segments, lots, data, config = plan

    def closing(segs, candidate_lots):
        if next(s.day_idx for s in segs if s.lot_id == "LB") == 3:
            return SkippedProposal({"key": "closing-limit"}, "scope_limited", scope_limited=True)
        return Proposal(segs, candidate_lots)

    def earlier(segs, candidate_lots):
        return Proposal(_moved(segs, "LB", day_idx=3, start_min=510, end_min=600),
                        candidate_lots, subject={"key": "group"})

    after, _, report = improve_plan(
        segments, lots, data, config,
        generators=[Generator("compact", closing), Generator("group", earlier)],
    )
    assert after == segments
    assert report["moves_accepted"] == 0
    assert report["rolled_back_moves"] == 1
    assert not any(entry["outcome"] == "accepted" for entry in report["proposal_log"].values())


def test_group_move_is_immediately_compacted(plan):
    """§5.6: time released by a group move is used before anything else."""

    segments, lots, data, config = plan

    def compact(segs):
        if next(s for s in segs if s.lot_id == "LA").day_idx == 2:
            return _moved(segs, "LB", day_idx=3, start_min=420, end_min=510)
        return [dataclasses.replace(s) for s in segs]

    group = lambda segs: _moved(segs, "LA", day_idx=2)  # noqa: E731

    improved, _lots, report = improve_plan(
        segments, lots, data, config,
        generators=[_gen("compact", compact), _gen("group", group)],
        max_evaluations=1,
    )

    # The evaluation limit stops the search, but only after the compaction
    # that follows the accepted group move.
    assert report["stop_reason"] == "evaluation_limit"
    assert report["accepted_by_scope"] == {"group": 1, "compact": 1}
    assert [(s.lot_id, s.day_idx) for s in improved] == [("LA", 2), ("LB", 3)]


def test_interrupted_compaction_rolls_back_to_the_settled_plan(plan):
    from backend.planning_control import PlanningTimeout

    segments, lots, data, config = plan
    calls = {"compact": 0}

    def compact(segs):
        calls["compact"] += 1
        if calls["compact"] > 1:
            raise PlanningTimeout("budget ended during compaction")
        return [dataclasses.replace(s) for s in segs]

    group = lambda segs: _moved(segs, "LA", day_idx=2)  # noqa: E731

    improved, _lots, report = improve_plan(
        segments, lots, data, config,
        generators=[_gen("compact", compact), _gen("group", group)],
    )

    assert report["stop_reason"] == "budget"
    assert report["rolled_back_moves"] == 1
    assert report["moves_accepted"] == 0
    assert report["accepted_by_scope"] == {}
    assert [(s.day_idx, s.start_min) for s in improved] == [(3, 420), (4, 420)]
