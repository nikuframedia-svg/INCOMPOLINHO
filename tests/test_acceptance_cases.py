"""Acceptance cases of plano-solver-2026-10-02 §8.1 on frozen historical plans.

Each case replays the snapshot of its time with the clock of its time
(protection recomputed for that date on a detached copy) and checks that the
current generic neighbourhoods reach what was once repaired by hand, or that
the explanation names the real reason. No rule depends on these identifiers.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from backend.plans.frozen import improve_preserving_protected_lots
from backend.scheduler.alternative_repair import anticipation_proposals
from backend.scheduler.canonical import result_validation_data
from backend.scheduler.improvement import (
    Proposal,
    no_loss_verdict,
    physical_setups,
    plan_facts,
    production_windows,
)
from backend.scheduler.operational_audit import build_operational_audit
from backend.scheduler.scoring import compute_score
from backend.scheduler.validation import plan_anchor_violations, validate_plan
from tests.snapshot_fixture import load_snapshot


def _first_rows(segments, lot_id):
    return sorted((s.day_idx, s.start_min, s.end_min, s.setup_min, s.machine_id)
                  for s in segments if s.lot_id == lot_id)


def _n1_for(snapshot, lot_id):
    view, floor = snapshot.complete_context()
    for proposal in anticipation_proposals(
        snapshot.result.segments, snapshot.result.lots, view, snapshot.config,
        not_before_abs=floor,
    ):
        if isinstance(proposal, Proposal) and any(
            s.lot_id == lot_id for s in proposal.segments
        ) and production_windows(proposal.segments)[lot_id] != production_windows(
            snapshot.result.segments)[lot_id]:
            assert not validate_plan(proposal.segments, view, snapshot.config,
                                     lots=proposal.lots)
            return proposal
    return None


# ── BFP082: retained mount, removed setup frees 75 minutes ───────────────

BFP082 = "LOT_BFP082_PRM019_1092262X100_8"
BFP082_PREDECESSOR = "LOT_BFP082_PRM019_1092262X100_0"


def test_bfp082_retained_mount_uses_the_75_minutes_when_movable():
    snapshot = load_snapshot("rev82", clock="2026-09-22")
    assert BFP082_PREDECESSOR in {lot.id for lot in snapshot.protected_lots}
    assert _first_rows(snapshot.result.segments, BFP082)[0][:2] == (5, 1124)

    proposal = _n1_for(snapshot, BFP082)

    assert proposal is not None
    rows = _first_rows(proposal.segments, BFP082)
    # Starts when the protected predecessor of the same mount ends; no setup.
    assert rows[0][:2] == (5, 1049)
    assert all(row[3] == 0 for row in rows)
    assert _first_rows(proposal.segments, BFP082_PREDECESSOR) == _first_rows(
        snapshot.result.segments, BFP082_PREDECESSOR)
    assert sum(s.qty for s in proposal.segments if s.lot_id == BFP082) == sum(
        s.qty for s in snapshot.result.segments if s.lot_id == BFP082)


def test_bfp082_historical_protection_stays_explicit():
    snapshot = load_snapshot("rev82")
    view, _floor = snapshot.complete_context()

    audit = build_operational_audit(
        snapshot.result.segments, snapshot.result.lots, view, snapshot.config,
    )

    assert BFP082 in {lot.id for lot in snapshot.protected_lots}
    assert not any(item["lot_id"] == BFP082 for item in audit["left_shift_detail"])
    assert {(item["lot_id"], item["protection"]) for item in audit["protected_left_shift_detail"]
            if item["lot_id"] == BFP082} == {(BFP082, "historical_lot_locked")}


# ── BFP112: machine free, crew free, production after setup ──────────────

BFP112 = "LOT_BFP112_PRM039_1197914X050_8"


def test_bfp112_starts_the_previous_day_when_machine_and_crew_allow():
    snapshot = load_snapshot("rev85", clock="2026-09-21")
    assert _first_rows(snapshot.result.segments, BFP112)[0][:2] == (5, 420)

    proposal = _n1_for(snapshot, BFP112)

    assert proposal is not None
    first = _first_rows(proposal.segments, BFP112)[0]
    # Setup at 11:50 on day 4 (crew), production 30 minutes later.
    assert first[:4] == (4, 710, 930, 30.0)
    machine_free = max(s.end_min for s in proposal.segments
                       if s.machine_id == "PRM039" and s.day_idx == 4 and s.lot_id != BFP112)
    assert machine_free <= 710


# ── BFP083: manual anchor is kept and named, not a resource shortage ─────

BFP083 = "LOT_TWIN_BFP083_15"


def test_bfp083_anchor_is_the_explanation_before_it_becomes_history():
    snapshot = load_snapshot("rev87", clock="2026-09-22")
    view, _floor = snapshot.complete_context()
    assert not plan_anchor_violations(snapshot.result.segments, view, snapshot.config)

    audit = build_operational_audit(
        snapshot.result.segments, snapshot.result.lots, view, snapshot.config,
    )

    reasons = {item["protection"] for item in audit["protected_left_shift_detail"]
               if item["lot_id"] == BFP083}
    assert reasons == {"manual_anchor"}


# ── BFP080 / BFP083 / D8: complete cycle on the plan of 01/10 ────────────


@pytest.fixture(scope="module")
def rev87_cycle():
    snapshot = load_snapshot("rev87", clock="2026-09-22")
    data, config, result = copy.deepcopy((snapshot.data, snapshot.config, snapshot.result))
    improved, report = improve_preserving_protected_lots(
        result, data, copy.deepcopy(data), config,
        copy.deepcopy(snapshot.protected_segments), copy.deepcopy(snapshot.protected_lots),
        snapshot.freeze_day, time_budget_s=120,
    )
    return snapshot, data, config, improved, report


def test_cycle_on_rev87_is_valid_keeps_history_anchor_and_every_order(rev87_cycle):
    snapshot, data, config, improved, _report = rev87_cycle
    view = result_validation_data(data, improved)
    assert not validate_plan(improved.segments, view, config, lots=improved.lots)
    assert not plan_anchor_violations(improved.segments, view, config)
    protected = {lot.id for lot in snapshot.protected_lots}
    assert sorted(_first_rows(improved.segments, lot_id) for lot_id in protected) == sorted(
        _first_rows(snapshot.result.segments, lot_id) for lot_id in protected)
    base_view = result_validation_data(snapshot.data, snapshot.result)
    before = plan_facts(snapshot.result.segments, snapshot.result.lots, base_view, compute_score(
        snapshot.result.segments, snapshot.result.lots, base_view, config,
        include_operational_audit=False))
    after = plan_facts(improved.segments, improved.lots, view, compute_score(
        improved.segments, improved.lots, view, config, include_operational_audit=False))
    assert no_loss_verdict(after, before).admissible
    assert after.anticipation < before.anticipation


def test_bfp080_uses_capacity_released_by_other_moves(rev87_cycle):
    snapshot, _data, _config, improved, report = rev87_cycle
    lot_id = "LOT_BFP080_PRM019_1065170X100_19"
    old = production_windows(snapshot.result.segments)[lot_id]
    new = production_windows(improved.segments)[lot_id]
    assert new < old
    assert report["moves_accepted"] > 1


# ── BFP079: stay or transfer, compared in the complete context ───────────


def test_bfp079_stay_and_transfer_are_compared_by_the_canonical_order():
    """The local stay found by hand on 01/10 keeps every order, saves a setup
    and starts the most urgent lots earlier; the canonical order prefers it
    over the transfer although three later lots start days later."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import gzip
    import json

    import repair_bfp079_transfer as repair

    from backend.plans.serialize import deserialize_snapshot

    snapshot = load_snapshot("rev87")
    raw = gzip.decompress(
        (Path(__file__).resolve().parents[1] / snapshot.manifest["private_fixture"]).read_bytes()
    )
    stay_payload, _receipt = repair.repair_payload(json.loads(raw))
    stay = deserialize_snapshot(stay_payload)["result"]
    data = copy.copy(snapshot.data)
    data.preserved_lot_proofs = {}

    def facts(plan):
        score = compute_score(plan.segments, plan.lots, data, snapshot.config,
                              include_operational_audit=False)
        return plan_facts(plan.segments, plan.lots, data, score)

    transfer_facts, stay_facts = facts(snapshot.result), facts(stay)
    assert no_loss_verdict(stay_facts, transfer_facts).admissible
    assert stay_facts.anticipation < transfer_facts.anticipation
    assert physical_setups(stay.segments).count == physical_setups(
        snapshot.result.segments).count - 1


# ── "Recalcular" from D0 after an OEE change (07/10/2026 review) ─────────


def test_recalculation_after_oee_change_rebuilds_instead_of_failing():
    from backend.plans.frozen import (
        compact_preserving_started_lots,
        optimize_preserving_started_lots,
    )
    from backend.scheduler.canonical import source_contract_violations
    from backend.scheduler.validation import PlanValidationError

    snapshot = load_snapshot("rev87")
    data, config, result = copy.deepcopy((snapshot.data, snapshot.config, snapshot.result))
    config.machines["PRM039"].oee = 0.44
    replanned = optimize_preserving_started_lots(data, config, result)
    current = result_validation_data(data, replanned)
    assert not validate_plan(replanned.segments, current, config, lots=replanned.lots)

    with pytest.raises(PlanValidationError) as failure:
        compact_preserving_started_lots(
            copy.deepcopy(current), config, copy.deepcopy(replanned),
            recalculate_from_start=True,
        )
    assert {item.get("kind") for item in failure.value.violations} == {"source_contract"}
    detached = copy.copy(current)
    detached.preserved_lot_proofs = {}
    assert source_contract_violations(replanned.segments, replanned.lots, detached, config)

    rebuilt = optimize_preserving_started_lots(
        copy.deepcopy(current), config, copy.deepcopy(replanned), recalculate_from_start=True,
    )
    rebuilt_view = result_validation_data(current, rebuilt)
    assert not validate_plan(rebuilt.segments, rebuilt_view, config, lots=rebuilt.lots)
