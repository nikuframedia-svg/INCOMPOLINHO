"""One-time, revision-bound repair of the preserved BFP112 early-start gap."""

from __future__ import annotations

import argparse
import copy
import json
import math
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
from backend.scheduler.scheduler import normalize_earliest_legal_plan
from backend.scheduler.scoring import compute_score
from backend.scheduler.validation import validate_plan

LOT_ID = "LOT_BFP112_PRM039_1197914X050_8"
OPERATION_ID = "repair-bfp112-early-start-2026-09-30"
EXPECTED_OLD_FIRST = (5, 420)
EXPECTED_NEW_FIRST = (4, 710)
RECOMPUTED_METADATA = {"left_shift_blockers", "material_release_day", "release_delay_workdays"}


def _by_lot(segments):
    grouped = defaultdict(list)
    for segment in segments:
        grouped[segment.lot_id].append(segment)
    return {
        lot_id: sorted(items, key=lambda item: (item.day_idx, item.start_min))
        for lot_id, items in grouped.items()
    }


def _target_totals(segments):
    return (
        sum(segment.qty for segment in segments),
        sum(segment.prod_min for segment in segments),
        sum(segment.setup_min for segment in segments),
    )


def repair_payload(payload, *, lot_id=LOT_ID):
    assert_snapshot_integrity(payload)
    restored = deserialize_snapshot(copy.deepcopy(payload))
    data, config, result = (
        restored["engine_data"], restored["config"], restored["result"]
    )
    lot = next((item for item in result.lots if item.id == lot_id), None)
    if lot is None:
        raise ValueError(f"Lot not present: {lot_id}")
    original_by_lot = _by_lot(result.segments)
    original = original_by_lot[lot_id]
    if (original[0].day_idx, original[0].start_min) != EXPECTED_OLD_FIRST:
        raise ValueError("The target lot no longer has the expected starting position.")
    if data.preserved_lot_proofs.get(lot_id) != schedule_fingerprint(original, [lot]):
        raise ValueError("The target historical lot proof is absent or invalid.")
    if validate_plan(result.segments, data, config, lots=result.lots):
        raise ValueError("The active plan is not a valid starting point.")

    move_data = copy.copy(data)
    move_data.preserved_lot_proofs = {
        key: value for key, value in data.preserved_lot_proofs.items()
        if key != lot_id
    }
    normalized = normalize_earliest_legal_plan(
        result.segments, result.lots, move_data, config,
    )
    normalized_by_lot = _by_lot(normalized)
    revised = normalized_by_lot[lot_id]
    if (revised[0].day_idx, revised[0].start_min) != EXPECTED_NEW_FIRST:
        raise ValueError("The target lot did not reach its verified earlier start.")
    if original_by_lot.keys() != normalized_by_lot.keys():
        raise ValueError("Normalization changed the set of lots.")
    for other_id, original_segments in original_by_lot.items():
        if other_id == lot_id:
            continue
        recalculated = normalized_by_lot[other_id]
        if len(original_segments) != len(recalculated):
            raise ValueError(f"Normalization changed another lot: {other_id}")
        for old, new in zip(original_segments, recalculated):
            old_fields = _jsonable(old)
            new_fields = _jsonable(new)
            if any(
                old_fields[key] != new_fields[key]
                for key in old_fields.keys() - RECOMPUTED_METADATA
            ):
                raise ValueError(f"Normalization changed another lot: {other_id}")
    old_qty, old_prod, old_setup = _target_totals(original)
    new_qty, new_prod, new_setup = _target_totals(revised)
    if old_qty != new_qty or not math.isclose(old_prod, new_prod, abs_tol=1e-6):
        raise ValueError("The target quantity or production duration changed.")
    if not math.isclose(old_setup, new_setup, abs_tol=1e-6):
        raise ValueError("The target setup duration changed.")

    updated = []
    inserted = False
    for segment in result.segments:
        if segment.lot_id == lot_id:
            if not inserted:
                updated.extend(revised)
                inserted = True
        else:
            updated.append(segment)

    data.preserved_lot_proofs[lot_id] = schedule_fingerprint(revised, [lot])
    violations = validate_plan(updated, data, config, lots=result.lots)
    output_issues = validate_output(updated, data)
    if violations or output_issues:
        raise ValueError(f"Corrected plan is invalid: {violations}; {output_issues}")
    score = compute_score(updated, result.lots, data, config)
    for key in ("otd", "otd_d", "tardy_count"):
        if score[key] != payload["score"][key]:
            raise ValueError(f"Delivery indicator changed: {key}")
    score["robustness_evaluated_samples"] = 0
    gate = build_gate_report(updated, result.lots, score, data, config)
    if not all(gate.get(key) for key in (
        "physical_gate_passed", "coverage_gate_passed", "jit_window_gate_passed"
    )):
        raise ValueError("The corrected plan fails a physical, coverage or material gate.")

    repaired = copy.deepcopy(payload)
    repaired["segments"] = _jsonable(updated)
    repaired["engine_data"]["preserved_lot_proofs"][lot_id] = data.preserved_lot_proofs[lot_id]
    repaired["score"] = score
    repaired["gate_report"] = gate
    repaired["dataset_info"]["n_segments"] = len(updated)
    repaired["plan_revision"] += 1
    _finalize_snapshot(repaired)
    assert_snapshot_integrity(repaired)
    check = deserialize_snapshot(repaired)
    if validate_plan(
        check["result"].segments, check["engine_data"], check["config"],
        lots=check["result"].lots,
    ):
        raise ValueError("The serialized correction is not physically valid.")
    return repaired, {
        "plan_revision": repaired["plan_revision"],
        "lot_id": lot_id,
        "first_start": list(EXPECTED_NEW_FIRST),
        "last_end": [revised[-1].day_idx, revised[-1].end_min],
        "quantity": new_qty,
        "segments": len(updated),
        "other_lots_unchanged": len(original_by_lot) - 1,
        "schedule_fingerprint": repaired["fingerprints"]["schedule"],
    }


def repair_store(store, *, expected_revision, expected_schedule):
    fingerprint = value_fingerprint({
        "revision": expected_revision, "schedule": expected_schedule, "lot_id": LOT_ID,
    })
    receipt = store.mutation_receipt(OPERATION_ID)
    if receipt:
        if receipt["fingerprint"] != fingerprint or receipt["status"] != "committed":
            raise ValueError("A different or interrupted repair requires review.")
        return receipt["response"]
    if store.pending_mutations():
        raise ValueError("Pending mutations must be recovered first.")
    active = store.active()
    if active is None or (
        active["payload"]["plan_revision"] != expected_revision
        or active["payload"]["fingerprints"]["schedule"] != expected_schedule
    ):
        raise ValueError("The active plan changed; refusing repair.")
    repaired, report = repair_payload(active["payload"])
    store.prepare_mutation(OPERATION_ID, fingerprint, {
        "config_changed": False, "files": [], "old_active_snapshot": active["id"],
        "plan_revision": repaired["plan_revision"], "bfp112_early_start_repair": report,
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
    with tempfile.TemporaryDirectory(prefix="incompolinho-bfp112-early-") as directory:
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
