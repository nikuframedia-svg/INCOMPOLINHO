"""Keep a tool on one machine unless moving it is justified (plan §2.3, §5.3)."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.canonical import preserved_lot_proofs
from backend.scheduler.improvement import (
    Generator,
    Proposal,
    SkippedProposal,
    improve_plan,
    no_loss_verdict,
    plan_facts,
    physical_setups,
    tool_transfers,
)
from backend.scheduler.transfer_consolidation import (
    SCOPE,
    consolidation_proposals,
    enumerate_transfer_hops,
    explain_remaining_transfers,
)
from backend.scheduler.types import Lot, Segment
from backend.scheduler.scoring import compute_score
from backend.scheduler.validation import validate_plan
from backend.types import EngineData, EOp, MachineInfo


def _config(*, oee_m1: float = 1.0, oee_m2: float = 1.0) -> FactoryConfig:
    config = FactoryConfig()
    config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes", oee=oee_m1),
        "M2": MachineConfig(id="M2", group="Grandes", oee=oee_m2),
    }
    return config


def _op(op_id: str, tool: str, demand: dict[int, int], *, alt: str | None = "M2",
        rate: float = 100.0, machine: str = "M1") -> EOp:
    d = [0, 0, 0, 0]
    for day, qty in demand.items():
        d[day] = qty
    return EOp(
        id=op_id, sku=f"SKU-{op_id}", client="CLIENT", designation="Part", m=machine, t=tool,
        pH=rate, sH=0.5, operators=1, eco_lot=0, alt=alt, stk=0, backlog=0, d=d,
        oee=1.0, wip=0,
    )


def _data(ops: list[EOp]) -> EngineData:
    return EngineData(
        ops=ops,
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Grandes", day_capacity=1020),
        ],
        twin_groups=[], client_demands={},
        workdays=["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17"], n_days=4,
    )


def _lot(op: EOp, lot_id: str, *, qty: int, prod_min: float, due: int) -> Lot:
    return Lot(
        id=lot_id, op_id=op.id, sku=op.sku, tool_id=op.t, machine_id=op.m,
        alt_machine_id=op.alt, qty=qty, prod_min=prod_min, setup_min=30.0, edd=due,
        is_twin=False, original_edd=due, internal_deadline=due, delivery_day=due,
        production_due_day=due, material_release_day=0,
    )


def _seg(lot: Lot, run_id: str, machine: str, day: int, start: int, end: int, *,
         setup: float, prod: float, qty: int) -> Segment:
    return Segment(
        lot_id=lot.id, run_id=run_id, machine_id=machine, tool_id=lot.tool_id,
        day_idx=day, start_min=start, end_min=end, shift="A" if start < 930 else "B",
        qty=qty, prod_min=prod, setup_min=setup, edd=lot.edd, sku=lot.sku,
        lot_qty=lot.qty, run_qty=lot.qty, run_setup_min=30.0, run_lot_count=1,
        production_due_day=lot.production_due_day, delivery_day=lot.delivery_day,
    )


def _ping_pong():
    """Tool T: M1 (P1) → M2 (P2) → M1 (P3); U sits on M1 between P1 and P3."""

    p = _op("P", "T", {3: 300})
    u = _op("U", "U", {3: 100})
    p1, p2, p3 = (_lot(p, f"LOT-P{i}", qty=100, prod_min=60, due=3) for i in (1, 2, 3))
    lot_u = _lot(u, "LOT-U", qty=100, prod_min=60, due=3)
    segments = [
        _seg(p1, "R1", "M1", 1, 420, 510, setup=30, prod=60, qty=100),
        _seg(lot_u, "RU", "M1", 1, 510, 600, setup=30, prod=60, qty=100),
        _seg(p2, "R2", "M2", 1, 600, 690, setup=30, prod=60, qty=100),
        _seg(p3, "R3", "M1", 2, 420, 510, setup=30, prod=60, qty=100),
    ]
    return segments, [p1, p2, p3, lot_u], _data([p, u]), _config()


def _only_consolidation(data, config):
    return [Generator(SCOPE, lambda segs, lots: consolidation_proposals(segs, lots, data, config))]


def test_same_speed_ping_pong_is_consolidated():
    segments, lots, data, config = _ping_pong()
    assert validate_plan(segments, data, config, lots=lots) == []
    assert tool_transfers(segments) == 2
    before_setups = physical_setups(segments)

    improved, improved_lots, report = improve_plan(
        segments, lots, data, config, generators=_only_consolidation(data, config),
    )

    assert report["accepted_by_scope"].get(SCOPE, 0) >= 1
    assert tool_transfers(improved) == 0
    after = physical_setups(improved)
    assert after.count < before_setups.count
    assert validate_plan(improved, data, config, lots=improved_lots) == []
    assert {s.machine_id for s in improved if s.tool_id == "T"} == {"M1"}


@pytest.mark.parametrize("prefix", ["LOT", "RENAMED"])
@pytest.mark.parametrize("preserve_orders", [True, False])
def test_lot_completion_is_not_proof_of_a_customer_delivery_loss(monkeypatch, prefix, preserve_orders):
    import backend.scheduler.transfer_consolidation as consolidation

    op = _op("P", "T", {0: 100, 1: 100, 3: 100})
    urgent_op = _op("U", "U", {0: 100})
    head = _lot(op, f"{prefix}-HEAD", qty=100, prod_min=60, due=0)
    tail = _lot(op, f"{prefix}-TAIL", qty=200, prod_min=120, due=1)
    tail.machine_id, tail.alt_machine_id = "M2", "M1"
    urgent = _lot(urgent_op, f"{prefix}-URGENT", qty=100, prod_min=60, due=0)
    data, config = _data([op, urgent_op]), _config()
    segments = [
        _seg(head, "R1", "M1", 0, 420, 510, setup=30, prod=60, qty=100),
        _seg(tail, "R2", "M2", 0, 600, 690, setup=30, prod=60, qty=100),
        _seg(tail, "R2", "M2", 2, 420, 480, setup=0, prod=60, qty=100),
        _seg(urgent, "RU", "M1", 2, 420, 510, setup=30, prod=60, qty=100),
    ]
    lots = [head, tail, urgent]
    candidate_lots = [head, replace(tail, machine_id="M1", alt_machine_id="M2"),
                      replace(urgent, machine_id="M2", alt_machine_id="M1")]
    candidate = [
        copy.deepcopy(segments[0]),
        replace(segments[1], machine_id="M1", start_min=510, end_min=570,
                setup_min=0, run_setup_min=0, day_idx=0 if preserve_orders else 2),
        replace(segments[2], machine_id="M1", day_idx=3, run_setup_min=0),
        replace(segments[3], machine_id="M2", day_idx=0, start_min=720, end_min=810),
    ]
    assert not validate_plan(segments, data, config, lots=lots)
    assert not validate_plan(candidate, data, config, lots=candidate_lots)
    assert no_loss_verdict(
        plan_facts(candidate, candidate_lots, data, compute_score(candidate, candidate_lots, data, config)),
        plan_facts(segments, lots, data, compute_score(segments, lots, data, config)),
    ).admissible == preserve_orders
    hop = next(h for h in enumerate_transfer_hops(segments, lots, data, config)
               if h.from_machine == "M2")
    monkeypatch.setattr(consolidation, "enumerate_transfer_hops", lambda *_: [hop])
    monkeypatch.setattr(consolidation, "_rebuild", lambda *_a, **_k: [
        (copy.deepcopy(candidate), copy.deepcopy(candidate_lots), (("R2", "M1"), ("RU", "M2"))),
    ])
    proposals = list(consolidation_proposals(segments, lots, data, config))
    assert any(isinstance(proposal, Proposal) for proposal in proposals), proposals
    improved, improved_lots, report = improve_plan(
        segments, lots, data, config, generators=_only_consolidation(data, config),
    )
    assert report["moves_accepted"] == int(preserve_orders), report["rejections"]
    assert tool_transfers(improved) == (0 if preserve_orders else 1)
    if not preserve_orders:
        assert report["rejections"].get(f"{SCOPE}:contract") == 1
    assert not validate_plan(improved, data, config, lots=improved_lots)


def test_first_run_can_stay_when_later_runs_cannot_move():
    """A long block must not hide a local stay that saves a physical setup."""

    p1_op = _op("P1", "T", {3: 100}, alt=None)
    p2_op = _op("P2", "T", {3: 100})
    p2_op.sku = p1_op.sku
    p3_op = _op("P3", "T", {3: 100}, alt=None, machine="M2")
    u_op = _op("U", "U", {3: 100})
    p1 = _lot(p1_op, "LOT-P1", qty=100, prod_min=60, due=3)
    p2 = _lot(p2_op, "LOT-P2", qty=100, prod_min=60, due=3)
    p3 = _lot(p3_op, "LOT-P3", qty=100, prod_min=60, due=3)
    u = _lot(u_op, "LOT-U", qty=100, prod_min=60, due=3)
    for lot in (p1, p2, u):
        lot.material_release_day = 1
    p3.material_release_day = 2
    segments = [
        _seg(p1, "R1", "M1", 1, 420, 510, setup=30, prod=60, qty=100),
        _seg(u, "RU", "M1", 1, 510, 600, setup=30, prod=60, qty=100),
        _seg(p2, "R2", "M2", 1, 540, 630, setup=30, prod=60, qty=100),
        _seg(p3, "R3", "M2", 2, 420, 510, setup=30, prod=60, qty=100),
    ]
    lots = [p1, p2, p3, u]
    data, config = _data([p1_op, p2_op, p3_op, u_op]), _config()
    assert validate_plan(segments, data, config, lots=lots) == []

    local = [
        proposal for proposal in consolidation_proposals(segments, lots, data, config)
        if isinstance(proposal, Proposal)
        and proposal.subject.get("kind") == "local_stay"
    ]
    assert local
    assert any(
        {segment.machine_id for segment in proposal.segments if segment.lot_id == p2.id}
        == {"M1"}
        and {segment.machine_id for segment in proposal.segments if segment.lot_id == u.id}
        == {"M2"}
        and physical_setups(proposal.segments).count == 3
        for proposal in local
    )

    improved, improved_lots, report = improve_plan(
        segments, lots, data, config, generators=_only_consolidation(data, config),
    )
    assert report["accepted_by_scope"].get(SCOPE, 0) >= 1
    assert physical_setups(improved).count < physical_setups(segments).count
    assert validate_plan(improved, data, config, lots=improved_lots) == []
    assert {s.machine_id for s in improved if s.lot_id == p3.id} == {"M2"}


def test_skipped_hypotheses_do_not_hide_a_later_valid_candidate():
    segments, lots, data, config = _ping_pong()
    better, better_lots, _ = improve_plan(
        segments, lots, data, config, generators=_only_consolidation(data, config),
    )

    def proposals(_segments, _lots):
        for index in range(16):
            yield SkippedProposal({"key": f"skip-{index}"}, "not_eligible")
        yield Proposal(better, better_lots, subject={"key": "later-valid"})

    improved, _lots, report = improve_plan(
        segments, lots, data, config,
        generators=[Generator("later", proposals)],
    )
    assert report["skipped_by_scope"]["later"] >= 16
    assert report["accepted_by_scope"]["later"] == 1
    assert tool_transfers(improved) == 0


def test_default_generators_also_remove_the_ping_pong():
    segments, lots, data, config = _ping_pong()

    improved, _lots, report = improve_plan(segments, lots, data, config)

    assert tool_transfers(improved) == 0
    assert report["final"]["tool_transfers"] == 0
    assert report["reference"]["tool_transfers"] == 2


def test_consolidation_is_idempotent_and_independent_of_names_and_order():
    segments, lots, data, config = _ping_pong()
    improved, improved_lots, _ = improve_plan(segments, lots, data, config)
    again, _lots, second = improve_plan(improved, improved_lots, data, config)
    assert second["moves_accepted"] == 0
    assert [(s.lot_id, s.machine_id, s.day_idx, s.start_min) for s in again] == [
        (s.lot_id, s.machine_id, s.day_idx, s.start_min) for s in improved
    ]
    assert enumerate_transfer_hops(again, improved_lots, data, config) == []

    renamed = {"R1": "Z9", "R2": "Z8", "R3": "Z7", "RU": "Z6"}
    shuffled = [replace(s, run_id=renamed[s.run_id]) for s in reversed(segments)]
    other, _lots, _ = improve_plan(shuffled, lots, data, config)
    assert tool_transfers(other) == 0
    assert sorted((s.lot_id, s.machine_id) for s in other) == sorted(
        (s.lot_id, s.machine_id) for s in improved
    )


def test_protected_lot_is_never_moved_others_consolidate_around_it():
    segments, lots, data, config = _ping_pong()
    p2 = next(lot for lot in lots if lot.id == "LOT-P2")
    data.preserved_lot_proofs = preserved_lot_proofs(
        [s for s in segments if s.lot_id == "LOT-P2"], [p2],
    )

    # The hop that would move the protected block is skipped, with its reason.
    skipped = [
        item for item in consolidation_proposals(segments, lots, data, config)
        if isinstance(item, SkippedProposal)
    ]
    assert any(item.reason == "protected" and "LOT-P2" in item.subject["lot_ids"]
               for item in skipped)

    improved, improved_lots, _report = improve_plan(
        segments, lots, data, config, generators=_only_consolidation(data, config),
    )

    assert [s for s in improved if s.lot_id == "LOT-P2"] == [
        s for s in segments if s.lot_id == "LOT-P2"
    ]
    # The unprotected blocks join the protected one instead.
    assert tool_transfers(improved) == 0
    assert {s.machine_id for s in improved if s.tool_id == "T"} == {"M2"}
    assert validate_plan(improved, data, config, lots=improved_lots) == []


def test_transfer_justified_by_slower_machine_is_kept_with_reason():
    """P1 runs on slow M1, P2 on fast M2, both due day 1; both machines are
    otherwise full that day, so keeping the tool on either machine would make
    one order late. The transfer must stay and every attempt must be rejected.
    """

    config = _config(oee_m1=0.5, oee_m2=1.0)
    p = _op("P", "T", {1: 200})
    # U only runs on M1 and V only on M2 (both 1 piece per minute at OEE 1).
    u = _op("U", "U", {1: 400}, alt=None, rate=60.0)
    # U and V are due on day 1 as well: no machine has slack for the other P.
    v = _op("V", "V", {1: 800}, alt=None, rate=60.0, machine="M2")
    p1 = _lot(p, "LOT-P1", qty=100, prod_min=120, due=1)
    p2 = _lot(p, "LOT-P2", qty=100, prod_min=60, due=1)
    lot_u = _lot(u, "LOT-U", qty=400, prod_min=800, due=1)
    v1 = _lot(v, "LOT-V1", qty=150, prod_min=150, due=1)
    v2 = _lot(v, "LOT-V2", qty=650, prod_min=650, due=1)
    for lot in (p1, p2, lot_u, v1, v2):
        lot.material_release_day = 1  # day 0 is not available
    segments = [
        _seg(p1, "R1", "M1", 1, 420, 570, setup=30, prod=120, qty=100),
        _seg(lot_u, "RU", "M1", 1, 570, 930, setup=30, prod=330, qty=165),
        _seg(lot_u, "RU", "M1", 1, 930, 1400, setup=0, prod=470, qty=235),
        # M2 starts 30 min later: one setup crew for the group.
        _seg(v1, "RV1", "M2", 1, 450, 630, setup=30, prod=150, qty=150),
        _seg(p2, "R2", "M2", 1, 630, 720, setup=30, prod=60, qty=100),
        _seg(v2, "RV2", "M2", 1, 720, 930, setup=30, prod=180, qty=180),
        _seg(v2, "RV2", "M2", 1, 930, 1400, setup=0, prod=470, qty=470),
    ]
    lots = [p1, p2, lot_u, v1, v2]
    data = _data([p, u, v])
    assert validate_plan(segments, data, config, lots=lots) == []

    improved, _lots, report = improve_plan(
        segments, lots, data, config, generators=_only_consolidation(data, config),
    )

    assert tool_transfers(improved) == tool_transfers(segments) == 1
    assert report["moves_accepted"] == 0
    outcomes = list(report["proposal_log"].values())
    assert outcomes, "the transfer must have been examined"
    assert all(entry["outcome"] != "accepted" for entry in outcomes)
    # The complete per-order contract proves the loss, not the lot's end day.
    assert all(entry["reason"] == "contract" for entry in outcomes)
    assert any(
        "acabaria no dia" in " ".join(entry["details"]) or "atraso" in " ".join(entry["details"])
        for entry in outcomes
    )
    hops = enumerate_transfer_hops(improved, lots, data, config)
    assert any(abs(hop.duration_ratio - 2.0) < 0.01 for hop in hops)

    # The remaining transfer carries a current, readable reason.
    explained = explain_remaining_transfers(improved, lots, data, config, report)
    assert explained["remaining"] == 1
    to_m1 = next(item for item in explained["items"] if item["to_machine"] == "M1")
    assert to_m1["reason"] == "contract"
    assert to_m1["summary"].startswith("manter na M1 violaria o contrato sem perdas")
    assert "atraso" in to_m1["summary"] or "quantidade no prazo" in to_m1["summary"]
    assert "2,0× mais" in to_m1["summary"]


def test_explanation_of_an_older_plan_state_is_not_shown_as_current():
    segments, lots, data, config = _ping_pong()
    hop = enumerate_transfer_hops(segments, lots, data, config)[0]
    report = {
        "final_signature": "final-state",
        "stop_reason": "budget",
        "proposal_log": {hop.key: {"outcome": "rejected", "reason": "contract",
                                   "details": ["x"], "on_signature": "older-state"}},
    }

    explained = explain_remaining_transfers(segments, lots, data, config, report)

    reasons = {item["key"]: item["reason"] for item in explained["items"]}
    assert reasons[hop.key] == "not_reevaluated"
    assert all(reason in {"not_reevaluated", "not_evaluated"} for reason in reasons.values())
    assert any("budget" in item["summary"] for item in explained["items"]
               if item["reason"] == "not_evaluated")


def test_transfer_search_cap_is_not_reported_as_completed(monkeypatch):
    import backend.scheduler.transfer_consolidation as consolidation

    segments, lots, data, config = _ping_pong()
    assert len(enumerate_transfer_hops(segments, lots, data, config)) > 1
    monkeypatch.setattr(consolidation, "_MAX_HOPS", 1)
    monkeypatch.setattr(consolidation, "_first_run_stay_hop", lambda *_: None)
    monkeypatch.setattr(consolidation, "_rebuild", lambda *_a, **_k: [])

    improved, result_lots, report = improve_plan(
        segments, lots, data, config, generators=_only_consolidation(data, config),
    )

    assert report["status"] == "partial"
    assert report["stop_reason"] == "search_limit"
    assert report["limited_by_scope"] == {SCOPE: 1}
    assert improved == segments
    assert result_lots == lots
    explanation = explain_remaining_transfers(improved, lots, data, config, report)
    assert any(item["reason"] == "not_evaluated" and "search_limit" in item["summary"]
               for item in explanation["items"])


def test_oversized_transfer_block_respects_the_six_campaign_limit(monkeypatch):
    import backend.scheduler.transfer_consolidation as consolidation

    op = _op("P", "T", {3: 160})
    lots = [_lot(op, f"L{i}", qty=20, prod_min=12, due=3) for i in range(8)]
    segments = [_seg(lots[0], "R0", "M1", 1, 420, 462, setup=30, prod=12, qty=20)]
    for index, lot in enumerate(lots[1:]):
        start = 540 if index == 0 else 582 + (index - 1) * 12
        setup = 30 if index == 0 else 0
        segments.append(_seg(lot, f"R{index+1}", "M2", 1, start, start+setup+12,
                             setup=setup, prod=12, qty=20))
    data, config = _data([op]), _config()
    assert not validate_plan(segments, data, config, lots=lots)
    hop = next(h for h in enumerate_transfer_hops(segments, lots, data, config)
               if len(h.run_ids) == 7)
    monkeypatch.setattr(consolidation, "enumerate_transfer_hops", lambda *_: [hop])
    monkeypatch.setattr(consolidation, "_first_run_stay_hop", lambda *_: None)
    rebuilt = []

    def rebuild(h, *_a, **_k):
        rebuilt.append(len(h.run_ids))
        return []

    monkeypatch.setattr(consolidation, "_rebuild", rebuild)
    proposals = list(consolidation_proposals(segments, lots, data, config))
    assert rebuilt == []
    assert len(proposals) == 1
    assert proposals[0].reason == "group_too_large"
    assert proposals[0].scope_limited


def test_truncated_displaced_group_reports_an_incomplete_comparison(monkeypatch):
    import backend.scheduler.transfer_consolidation as consolidation

    segments, lots, data, config = _ping_pong()
    monkeypatch.setattr(consolidation, "_first_run_stay_hop", lambda *_: None)
    monkeypatch.setattr(consolidation, "_displaced_runs", lambda *_: ([], True))
    monkeypatch.setattr(consolidation, "_rebuild", lambda *_a, **_k: [])
    _, _, report = improve_plan(
        segments, lots, data, config, generators=_only_consolidation(data, config),
    )
    assert report["status"] == "partial"
    assert report["stop_reason"] == "search_limit"
    assert report["limited_by_scope"] == {SCOPE: 1}
    assert all(entry["reason"] == "scope_limited"
               for entry in report["proposal_log"].values())


@pytest.mark.parametrize("reason", ["scope_limited", "group_too_large"])
def test_limited_comparison_is_explained_without_claiming_impossibility(reason):
    segments, lots, data, config = _ping_pong()
    hop = enumerate_transfer_hops(segments, lots, data, config)[0]
    report = {"final_signature": "state", "stop_reason": "search_limit", "proposal_log": {
        hop.key: {"reason": reason, "on_signature": "state", "details": []},
    }}
    item = next(item for item in explain_remaining_transfers(segments, lots, data, config, report)["items"]
                if item["key"] == hop.key)
    assert "incompleta" in item["summary"]


def test_failed_heuristic_is_not_explained_as_a_physical_impossibility():
    segments, lots, data, config = _ping_pong()
    hop = enumerate_transfer_hops(segments, lots, data, config)[0]
    report = {"final_signature": "state", "stop_reason": "no_admissible_improvement", "proposal_log": {
        hop.key: {"reason": "unschedulable", "on_signature": "state", "details": []},
    }}
    item = next(item for item in explain_remaining_transfers(segments, lots, data, config, report)["items"]
                if item["key"] == hop.key)
    assert "não foi encontrada" in item["summary"]
    assert "não há espaço" not in item["summary"]


@pytest.mark.parametrize("reason", ["scope_limited", "group_too_large"])
def test_local_limits_are_propagated_to_the_coordinator(monkeypatch, reason):
    import backend.scheduler.transfer_consolidation as consolidation

    segments, lots, data, config = _ping_pong()
    hop = enumerate_transfer_hops(segments, lots, data, config)[0]
    run_map = consolidation._resolve_runs(segments, lots, None)
    monkeypatch.setattr(consolidation, "_local_displaced_runs", lambda *_: ([], reason))
    items = list(consolidation._local_stay_proposals(
        hop, segments, lots, run_map, set(), data, config, physical_setups(segments),
    ))
    assert len(items) == 1
    assert items[0].scope_limited
    assert items[0].reason == reason


def test_cached_truncated_group_remains_incomplete(monkeypatch):
    import backend.scheduler.transfer_consolidation as consolidation
    from backend.planning_control import planning_scope

    segments, lots, data, config = _ping_pong()
    monkeypatch.setattr(consolidation, "_first_run_stay_hop", lambda *_: None)
    monkeypatch.setattr(consolidation, "_displaced_runs", lambda *_: ([], True))
    calls = []

    def rebuild(*_a, **_k):
        calls.append(1)
        return []

    monkeypatch.setattr(consolidation, "_rebuild", rebuild)
    with planning_scope(timeout_s=60):
        first = list(consolidation_proposals(segments, lots, data, config))
        count = len(calls)
        second = list(consolidation_proposals(segments, lots, data, config))
    assert len(calls) == count > 0
    assert all(item.scope_limited for item in [*first, *second])
    assert all(item.reason == "scope_limited" for item in [*first, *second])


@pytest.mark.parametrize("detail", ["numero de setups aumenta", "minutos de setup aumentam"])
def test_setup_loss_is_not_explained_as_a_delivery_delay(detail):
    segments, lots, data, config = _ping_pong()
    hop = enumerate_transfer_hops(segments, lots, data, config)[0]
    report = {"final_signature": "state", "proposal_log": {
        hop.key: {"reason": "contract", "on_signature": "state", "details": [detail]},
    }}
    item = next(item for item in explain_remaining_transfers(segments, lots, data, config, report)["items"]
                if item["key"] == hop.key)
    assert detail in item["summary"]
    assert "atrasaria" not in item["summary"]
