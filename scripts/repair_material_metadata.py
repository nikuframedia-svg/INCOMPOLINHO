"""Offline, explicitly approved repair of legacy material dates; never reschedule."""

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
    value_fingerprint,
)
from backend.plans.store import PlansStore
from backend.scheduler.gates import build_gate_report
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.scoring import compute_score
from backend.scheduler.validation import validate_plan

APPROVED_DATES = {
    "LOT_BFP082_PRM019_1092262X100_8": (-2, 1),
    "LOT_BFP112_PRM039_1197914X050_8": (-2, 1),
    "LOT_TWIN_JTE004_11": (-1, 4),
    "LOT_JDE002_PRM042_TP042173-0040-1_11": (-1, 4),
    "LOT_HAN002_PRM043_CF589MMA1A02.20_19": (-1, 4),
}
OPERATION_ID = "repair-material-metadata-2026-09-23"


def without_material_dates(value):
    result = copy.deepcopy(value)
    result.pop("material_release_day", None)
    for output in result.get("output_milestones") or []:
        output.pop("material_release_day", None)
    return result


def execution_fingerprint(payload):
    return value_fingerprint({
        key: [without_material_dates(item) for item in payload[key]]
        for key in ("lots", "segments")
    })


def repair_payload(payload, approved_dates):
    assert_snapshot_integrity(payload)
    restored = deserialize_snapshot(payload)
    data, config = restored["engine_data"], restored["config"]
    if data.preserved_lot_proofs:
        raise ValueError("Historical proofs require a separate explicit review.")
    expected = {lot.id: _jsonable(lot) for lot in create_lots(data, config)}
    repaired = copy.deepcopy(payload)
    affected = {}
    for lot in repaired["lots"]:
        lot_id = lot["id"]
        if lot_id not in approved_dates:
            continue
        old_day, new_day = approved_dates[lot_id]
        canonical = expected.get(lot_id)
        if canonical is None or canonical["material_release_day"] != new_day:
            raise ValueError(f"Unconfirmed canonical material date: {lot_id}")
        canonical_outputs = canonical.get("output_milestones") or []
        old_outputs = lot.get("output_milestones") or []
        if not old_outputs or (
            [{k: v for k, v in item.items() if k != "material_release_day"} for item in old_outputs]
            != [{k: v for k, v in item.items() if k != "material_release_day"} for item in canonical_outputs]
        ):
            raise ValueError(f"Non-material output changes refused: {lot_id}")
        affected[lot_id] = 0
        for item in [lot, *[s for s in repaired["segments"] if s["lot_id"] == lot_id]]:
            allowed_days = (old_day,) if item is lot else (old_day, None)
            if item.get("material_release_day") not in allowed_days or item.get("output_milestones") != old_outputs:
                raise ValueError(f"Unexpected legacy material metadata: {lot_id}")
            if item.get("material_release_day") is not None:
                item["material_release_day"] = new_day
            item["output_milestones"] = copy.deepcopy(canonical_outputs)
            affected[lot_id] += 1
    if set(affected) != set(approved_dates) or any(count < 2 for count in affected.values()):
        raise ValueError("The approved lots and their segments must all be present.")
    if execution_fingerprint(repaired) != execution_fingerprint(payload):
        raise ValueError("Execution changes refused.")

    # Add only schema defaults, avoiding an extra identity change on first boot.
    normalized_engine = _jsonable(data)
    if any(normalized_engine.get(key) != value for key, value in payload["engine_data"].items()):
        raise ValueError("Planning input changes refused.")
    repaired["engine_data"] = normalized_engine
    _finalize_snapshot(repaired)
    result = deserialize_snapshot(repaired)["result"]
    violations = validate_plan(result.segments, data, config, lots=result.lots)
    if violations:
        raise ValueError(f"Unresolved plan violations: {json.dumps(violations, ensure_ascii=False)}")
    repaired["score"] = compute_score(result.segments, result.lots, data, config)
    repaired["score"]["robustness_evaluated_samples"] = 0
    repaired["gate_report"] = build_gate_report(
        result.segments, result.lots, repaired["score"], data, config,
    )
    if not all(repaired["gate_report"].get(key) for key in (
        "physical_gate_passed", "coverage_gate_passed", "jit_window_gate_passed",
    )):
        raise ValueError("The corrected schedule still fails physical/material/quantity validation.")
    repaired["plan_revision"] = int(payload["plan_revision"]) + 1
    _finalize_snapshot(repaired)
    assert_snapshot_integrity(repaired)
    return repaired, {
        "plan_revision": repaired["plan_revision"],
        "dataset_id": (payload.get("dataset_info") or {}).get("id"),
        "execution_fingerprint": execution_fingerprint(payload),
        "schedule_fingerprint": repaired["fingerprints"]["schedule"],
        "lots": {lot_id: {"old": approved_dates[lot_id][0], "new": approved_dates[lot_id][1],
                           "segments": count - 1} for lot_id, count in affected.items()},
        "physical_violations": len(violations),
    }


def repair_store(store, *, expected_revision, expected_schedule, approved_dates=APPROVED_DATES):
    fingerprint = value_fingerprint({"revision": expected_revision, "schedule": expected_schedule,
                                     "approved_dates": approved_dates})
    receipt = store.mutation_receipt(OPERATION_ID)
    if receipt:
        if receipt["fingerprint"] != fingerprint or receipt["status"] != "committed":
            raise ValueError("A different or interrupted repair requires review.")
        return receipt["response"]
    if store.pending_mutations():
        raise ValueError("Pending mutations must be recovered before the offline repair.")
    active = store.active()
    payload = active["payload"]
    if payload["plan_revision"] != expected_revision or payload["fingerprints"]["schedule"] != expected_schedule:
        raise ValueError("The active plan changed since approval; refusing to repair.")
    repaired, report = repair_payload(payload, approved_dates)
    store.prepare_mutation(OPERATION_ID, fingerprint, {
        "config_changed": False, "files": [], "old_active_snapshot": active["id"],
        "plan_revision": repaired["plan_revision"], "material_metadata_repair": report,
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
    parser.add_argument("--apply", action="store_true", help="Requires stopped application services and a backup.")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="incompolinho-material-review-") as directory:
        db = args.db
        if not args.apply:
            db = Path(directory) / "plans.db"
            with sqlite3.connect(f"{args.db.resolve().as_uri()}?mode=ro", uri=True) as source, sqlite3.connect(db) as target:
                source.backup(target)
        store = PlansStore(str(db))
        try:
            report = repair_store(store, expected_revision=args.expected_revision,
                                  expected_schedule=args.expected_schedule)
            print(json.dumps({"applied": args.apply, **report}, ensure_ascii=False, indent=2))
        finally:
            store.close()


if __name__ == "__main__":
    main()
