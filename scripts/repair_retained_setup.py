"""Repair one legacy retained-tool setup without moving production."""

from __future__ import annotations

import argparse
import copy
import json
import sqlite3
import tempfile
from pathlib import Path

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
from backend.scheduler.scheduler import _remove_redundant_retained_tool_setups
from backend.scheduler.scoring import compute_score
from backend.scheduler.validation import validate_plan

LOT_ID = "LOT_BFP082_PRM019_1092262X100_8"
OPERATION_ID = "repair-retained-setup-bfp082-2026-09-27"


def production_fingerprint(segments):
    """Ignore only the accounting split between setup and idle time."""
    normalized = []
    for segment in segments:
        item = copy.deepcopy(segment)
        item["productive_start_min"] = float(item.pop("start_min")) + float(item.pop("setup_min"))
        item.pop("run_setup_min")
        normalized.append(item)
    return value_fingerprint(normalized)


def repair_payload(payload, *, lot_id=LOT_ID):
    assert_snapshot_integrity(payload)
    restored = deserialize_snapshot(payload)
    data, config, result = restored["engine_data"], restored["config"], restored["result"]
    target = next((lot for lot in result.lots if lot.id == lot_id), None)
    if target is None:
        raise ValueError(f"Lot not present: {lot_id}")
    old_segments = [segment for segment in result.segments if segment.lot_id == lot_id]
    old_proof = schedule_fingerprint(old_segments, [target])
    if data.preserved_lot_proofs.get(lot_id) != old_proof:
        raise ValueError("The historical lot proof is absent or no longer matches.")

    updated = _remove_redundant_retained_tool_setups(copy.deepcopy(result.segments))
    old_json, new_json = _jsonable(result.segments), _jsonable(updated)
    changes = [
        (before, after)
        for before, after in zip(old_json, new_json)
        if before != after
    ]
    if len(old_json) != len(new_json) or not changes or any(
        before["lot_id"] != lot_id or after["lot_id"] != lot_id
        for before, after in changes
    ):
        raise ValueError("The cleanup did not isolate the approved historical lot.")
    removed = sum(before["setup_min"] - after["setup_min"] for before, after in changes)
    if removed <= 0 or sum(after["setup_min"] for before, after in changes) != 0:
        raise ValueError("The approved setup was not removed exactly.")
    if production_fingerprint(old_json) != production_fingerprint(new_json):
        raise ValueError("Production, resources or obligations changed; refusing repair.")

    repaired = copy.deepcopy(payload)
    repaired["segments"] = new_json
    new_segments = [segment for segment in updated if segment.lot_id == lot_id]
    repaired["engine_data"]["preserved_lot_proofs"][lot_id] = schedule_fingerprint(
        new_segments, [target]
    )
    _finalize_snapshot(repaired)
    check = deserialize_snapshot(repaired)
    violations = validate_plan(
        check["result"].segments, check["engine_data"], check["config"],
        lots=check["result"].lots,
    )
    if violations:
        raise ValueError(f"Corrected plan is invalid: {json.dumps(violations, ensure_ascii=False)}")
    score = compute_score(updated, result.lots, check["engine_data"], config)
    for key in ("otd", "otd_d", "tardy_count"):
        if score[key] != payload["score"][key]:
            raise ValueError(f"Delivery indicator changed: {key}")
    score["robustness_evaluated_samples"] = 0
    repaired["score"] = score
    repaired["gate_report"] = build_gate_report(
        updated, result.lots, score, check["engine_data"], config,
    )
    if not all(repaired["gate_report"].get(key) for key in (
        "physical_gate_passed", "coverage_gate_passed", "jit_window_gate_passed",
    )):
        raise ValueError("Corrected plan fails physical, quantity or material gates.")
    repaired["plan_revision"] += 1
    _finalize_snapshot(repaired)
    assert_snapshot_integrity(repaired)
    return repaired, {
        "plan_revision": repaired["plan_revision"],
        "lot_id": lot_id,
        "removed_setup_min": removed,
        "production_fingerprint": production_fingerprint(old_json),
        "schedule_fingerprint": repaired["fingerprints"]["schedule"],
        "physical_violations": len(violations),
    }


def repair_store(store, *, expected_revision, expected_schedule, lot_id=LOT_ID):
    fingerprint = value_fingerprint({
        "revision": expected_revision, "schedule": expected_schedule, "lot_id": lot_id,
    })
    receipt = store.mutation_receipt(OPERATION_ID)
    if receipt:
        if receipt["fingerprint"] != fingerprint or receipt["status"] != "committed":
            raise ValueError("A different or interrupted repair requires review.")
        return receipt["response"]
    if store.pending_mutations():
        raise ValueError("Pending mutations must be recovered first.")
    active = store.active()
    payload = active["payload"]
    if (payload["plan_revision"] != expected_revision
            or payload["fingerprints"]["schedule"] != expected_schedule):
        raise ValueError("The active plan changed; refusing repair.")
    repaired, report = repair_payload(payload, lot_id=lot_id)
    store.prepare_mutation(OPERATION_ID, fingerprint, {
        "config_changed": False, "files": [], "old_active_snapshot": active["id"],
        "plan_revision": repaired["plan_revision"], "retained_setup_repair": report,
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
    parser.add_argument("--apply", action="store_true", help="Requires stopped backend and a backup.")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="incompolinho-setup-review-") as directory:
        db = args.db
        if not args.apply:
            db = Path(directory) / "plans.db"
            with sqlite3.connect(f"{args.db.resolve().as_uri()}?mode=ro", uri=True) as source, sqlite3.connect(db) as target:
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
