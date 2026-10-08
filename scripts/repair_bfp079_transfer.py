"""Apply the verified local BFP079 transfer correction to one active revision."""

from __future__ import annotations

import argparse
import copy
import json
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path

from backend.guardian.guardian import validate_output
from backend.plans.serialize import (
    _finalize_snapshot,
    _jsonable,
    assert_snapshot_integrity,
    deserialize_snapshot,
    schedule_fingerprint,
    value_fingerprint,
)
from backend.plans.store import PlansStore
from backend.scheduler.gates import build_gate_report
from backend.scheduler.improvement import (
    no_loss_verdict,
    physical_setups,
    plan_facts,
    tool_transfers,
)
from backend.scheduler.scheduler import normalize_earliest_legal_plan
from backend.scheduler.scoring import compute_score
from backend.scheduler.transfer_consolidation import (
    Proposal,
    consolidation_proposals,
)
from backend.scheduler.validation import validate_plan

TARGET = "LOT_TWIN_BFP079_12"
AFFECTED = {
    TARGET,
    "LOT_BFP184_PRM031_1661546X070_12",
    "LOT_TWIN_BFP171_14",
    "LOT_TWIN_BFP162_14",
    "LOT_BFP114_PRM031_1694825X040_14",
}
OPERATION_ID = "repair-bfp079-local-stay-2026-10-01"


def _by_lot(segments):
    grouped = defaultdict(list)
    for segment in segments:
        grouped[segment.lot_id].append(segment)
    return {
        key: sorted(items, key=lambda item: (item.day_idx, item.start_min))
        for key, items in grouped.items()
    }


def repair_payload(payload):
    assert_snapshot_integrity(payload)
    restored = deserialize_snapshot(copy.deepcopy(payload))
    data, config, result = (
        restored["engine_data"], restored["config"], restored["result"]
    )
    original_by_lot = _by_lot(result.segments)
    original_lots = {lot.id: lot for lot in result.lots}
    if not AFFECTED <= original_by_lot.keys() or not AFFECTED <= original_lots.keys():
        raise ValueError("The five expected lots are not present.")
    first = original_by_lot[TARGET][0]
    if (first.day_idx, first.start_min, first.machine_id) != (7, 633, "PRM039"):
        raise ValueError("BFP079 no longer starts at the expected position.")
    for lot_id in AFFECTED:
        if data.preserved_lot_proofs.get(lot_id) != schedule_fingerprint(
            original_by_lot[lot_id], [original_lots[lot_id]]
        ):
            raise ValueError(f"Historical proof changed: {lot_id}")
    if validate_plan(result.segments, data, config, lots=result.lots):
        raise ValueError("The current plan is not a valid starting point.")

    detached = copy.copy(data)
    detached.preserved_lot_proofs = {
        key: proof for key, proof in data.preserved_lot_proofs.items()
        if key not in AFFECTED
    }
    original_facts = plan_facts(
        result.segments, result.lots, data,
        compute_score(result.segments, result.lots, data, config),
    )
    original_setups = physical_setups(result.segments)
    original_lot_payloads = {key: _jsonable(value) for key, value in original_lots.items()}
    original_segment_payloads = {
        key: _jsonable(value) for key, value in original_by_lot.items()
    }
    candidates = []
    for proposal in consolidation_proposals(result.segments, result.lots, detached, config):
        if not isinstance(proposal, Proposal):
            continue
        if TARGET not in proposal.subject.get("lot_ids", []):
            continue
        if proposal.subject.get("kind") != "local_stay":
            continue
        candidate_lots = {lot.id: lot for lot in proposal.lots}
        candidate_by_lot = _by_lot(proposal.segments)
        if candidate_by_lot.keys() != original_by_lot.keys():
            continue
        if any(
            _jsonable(candidate_by_lot[key]) != original_segment_payloads[key]
            or _jsonable(candidate_lots[key]) != original_lot_payloads[key]
            for key in original_by_lot.keys() - AFFECTED
        ):
            continue
        # Other lots are fixed during compaction; only the explicitly reviewed
        # historical group may change its position and machine.
        normalized = normalize_earliest_legal_plan(
            proposal.segments, proposal.lots, detached, config,
            annotate=False, protected_lot_ids=set(original_by_lot) - AFFECTED,
        )
        normalized_by_lot = _by_lot(normalized)
        if normalized_by_lot.keys() != original_by_lot.keys():
            continue
        if any(
            _jsonable(normalized_by_lot[key]) != original_segment_payloads[key]
            for key in original_by_lot.keys() - AFFECTED
        ):
            continue
        revised_first = normalized_by_lot[TARGET][0]
        if (revised_first.day_idx, revised_first.start_min, revised_first.machine_id) != (
            7, 633, "PRM031"
        ):
            continue
        if any(segment.setup_min for segment in normalized_by_lot[TARGET]):
            continue
        for lot_id in AFFECTED:
            before, after = original_by_lot[lot_id], normalized_by_lot[lot_id]
            if sum(item.qty for item in before) != sum(item.qty for item in after):
                raise ValueError(f"Quantity changed: {lot_id}")
            old_lot, new_lot = original_lot_payloads[lot_id], _jsonable(candidate_lots[lot_id])
            for key in old_lot.keys() - {"machine_id", "prod_min", "setup_min"}:
                if old_lot[key] != new_lot[key]:
                    raise ValueError(f"Lot identity or demand changed: {lot_id}/{key}")
        if validate_plan(normalized, detached, config, lots=proposal.lots):
            continue
        if validate_output(normalized, detached):
            continue
        score = compute_score(normalized, proposal.lots, detached, config)
        facts = plan_facts(normalized, proposal.lots, detached, score)
        verdict = no_loss_verdict(facts, original_facts)
        if not verdict.admissible:
            continue
        setup = physical_setups(normalized)
        if (setup.count, setup.minutes) >= (
            original_setups.count, original_setups.minutes
        ):
            continue
        changed = sum(
            _jsonable(normalized_by_lot[key]) != original_segment_payloads[key]
            for key in AFFECTED
        )
        candidates.append((
            (setup.count, setup.minutes, tool_transfers(normalized), changed),
            normalized, proposal.lots, score,
        ))
    if not candidates:
        raise ValueError("No complete, strictly better local alternative was verified.")
    _, candidate_segments, candidate_lots, score = min(candidates, key=lambda row: row[0])
    candidate_by_lot = _by_lot(candidate_segments)
    candidate_lot_by_id = {lot.id: lot for lot in candidate_lots}
    changed_lot_ids = {
        key for key in AFFECTED
        if _jsonable(candidate_by_lot[key]) != original_segment_payloads[key]
        or _jsonable(candidate_lot_by_id[key]) != original_lot_payloads[key]
    }
    # Keep every untouched lot byte-for-byte, including annotations that a
    # normalizer may otherwise refresh without any physical schedule change.
    updated = [
        segment for segment in result.segments
        if segment.lot_id not in changed_lot_ids
    ] + [
        segment for segment in candidate_segments
        if segment.lot_id in changed_lot_ids
    ]
    updated_lots = [
        candidate_lot_by_id[lot.id] if lot.id in changed_lot_ids else lot
        for lot in result.lots
    ]
    for lot_id in changed_lot_ids:
        detached.preserved_lot_proofs[lot_id] = schedule_fingerprint(
            candidate_by_lot[lot_id], [candidate_lot_by_id[lot_id]]
        )
    if validate_plan(updated, detached, config, lots=updated_lots):
        raise ValueError("The final merged plan violates physical constraints.")
    if validate_output(updated, detached):
        raise ValueError("The final merged plan fails guardian validation.")
    final_score = compute_score(updated, updated_lots, detached, config)
    if not no_loss_verdict(
        plan_facts(updated, updated_lots, detached, final_score), original_facts
    ).admissible:
        raise ValueError("The final merged plan worsens an order.")
    final_score["robustness_evaluated_samples"] = 0
    gate = build_gate_report(updated, updated_lots, final_score, detached, config)
    if not all(gate.get(key) for key in (
        "physical_gate_passed", "coverage_gate_passed", "jit_window_gate_passed"
    )):
        raise ValueError("A physical, coverage, or material gate failed.")
    repaired = copy.deepcopy(payload)
    repaired["segments"] = _jsonable(updated)
    repaired["lots"] = _jsonable(updated_lots)
    repaired["score"] = final_score
    repaired["gate_report"] = gate
    repaired["engine_data"]["preserved_lot_proofs"] = detached.preserved_lot_proofs
    repaired["dataset_info"]["n_segments"] = len(updated)
    repaired["plan_revision"] += 1
    _finalize_snapshot(repaired)
    assert_snapshot_integrity(repaired)
    return repaired, {
        "plan_revision": repaired["plan_revision"],
        "changed_lots": sorted(changed_lot_ids),
        "bfp079_machine": "PRM031",
        "bfp079_first_start": [7, 633],
        "setups_before": original_setups.count,
        "setups_after": physical_setups(updated).count,
        "setup_minutes_before": original_setups.minutes,
        "setup_minutes_after": physical_setups(updated).minutes,
        "transfers_before": tool_transfers(result.segments),
        "transfers_after": tool_transfers(updated),
        "other_lots_unchanged": len(original_by_lot) - len(changed_lot_ids),
        "schedule_fingerprint": repaired["fingerprints"]["schedule"],
    }


def repair_store(store, *, expected_revision, expected_schedule):
    fingerprint = value_fingerprint({
        "revision": expected_revision, "schedule": expected_schedule, "target": TARGET,
    })
    receipt = store.mutation_receipt(OPERATION_ID)
    if receipt:
        if receipt["fingerprint"] != fingerprint or receipt["status"] != "committed":
            raise ValueError("A different or interrupted correction requires review.")
        return receipt["response"]
    if store.pending_mutations():
        raise ValueError("Pending mutations must be recovered first.")
    active = store.active()
    if active is None or (
        active["payload"]["plan_revision"] != expected_revision
        or active["payload"]["fingerprints"]["schedule"] != expected_schedule
    ):
        raise ValueError("The active plan changed; refusing correction.")
    repaired, report = repair_payload(active["payload"])
    store.prepare_mutation(OPERATION_ID, fingerprint, {
        "config_changed": False, "files": [], "old_active_snapshot": active["id"],
        "plan_revision": repaired["plan_revision"], "bfp079_local_stay_repair": report,
    })
    try:
        store.commit_mutation(OPERATION_ID, repaired, report, source="auto")
    except Exception:
        receipt = store.mutation_receipt(OPERATION_ID)
        if receipt and receipt["status"] == "committed":
            return receipt["response"]
        store.abort_mutation(OPERATION_ID)
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--expected-schedule", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="incompolinho-bfp079-") as directory:
        db = args.db
        if not args.apply:
            db = Path(directory) / "plans.db"
            with sqlite3.connect(f"{args.db.resolve().as_uri()}?mode=ro", uri=True) as source:
                with sqlite3.connect(db) as target:
                    source.backup(target)
        store = PlansStore(db)
        try:
            report = repair_store(
                store, expected_revision=args.expected_revision,
                expected_schedule=args.expected_schedule,
            )
            print(json.dumps({"applied": args.apply, **report}, ensure_ascii=False, indent=2))
        finally:
            store.close()


if __name__ == "__main__":
    main()
