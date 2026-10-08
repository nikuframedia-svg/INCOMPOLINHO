"""One-time, revision-bound repair of the preserved BFP082 production gap."""

from __future__ import annotations

import argparse
import copy
import json
import math
import sqlite3
import tempfile
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
from backend.scheduler.explainability import annotate_left_shift_blockers
from backend.scheduler.gap_filling import apply_partial_gap_move
from backend.scheduler.gates import build_gate_report
from backend.scheduler.operational_audit import actionable_gap_opportunities
from backend.scheduler.scoring import compute_score
from backend.scheduler.validation import validate_plan

LOT_ID = "LOT_BFP082_PRM019_1092262X100_8"
OPERATION_ID = "repair-bfp082-idle-2026-09-28"
FIRST_GAP = (5, 1049, 1124, 5, 1124)


def _physical_totals(segments):
    return (
        sum(segment.qty for segment in segments),
        sum(segment.prod_min for segment in segments),
        sum(segment.setup_min for segment in segments),
    )


def repair_payload(payload, *, lot_id=LOT_ID, first_gap=FIRST_GAP):
    assert_snapshot_integrity(payload)
    restored = deserialize_snapshot(copy.deepcopy(payload))
    data, config, result = (
        restored["engine_data"], restored["config"], restored["result"]
    )
    lot = next((item for item in result.lots if item.id == lot_id), None)
    if lot is None:
        raise ValueError(f"Lot not present: {lot_id}")
    original = [segment for segment in result.segments if segment.lot_id == lot_id]
    proof = data.preserved_lot_proofs.get(lot_id)
    if not proof or proof != schedule_fingerprint(original, [lot]):
        raise ValueError("The historical lot proof is absent or no longer matches.")
    if validate_plan(result.segments, data, config, lots=result.lots):
        raise ValueError("The active plan is not a valid starting point.")

    others = [segment for segment in result.segments if segment.lot_id != lot_id]
    shifted = copy.deepcopy(original)
    move_data = copy.copy(data)
    move_data.preserved_lot_proofs = {
        key: value for key, value in data.preserved_lot_proofs.items()
        if key != lot_id
    }
    moves = 0
    for _ in range(8):
        candidates = [
            item for item in actionable_gap_opportunities(
                others + shifted, result.lots, data, config
            ) if item.lot_id == lot_id
        ]
        if not candidates:
            break
        opportunity = min(candidates, key=lambda item: (
            item.gap_day, item.gap_start_min, item.source_day, item.source_start_min
        ))
        if moves == 0 and (
            opportunity.gap_day, opportunity.gap_start_min, opportunity.gap_end_min,
            opportunity.source_day, opportunity.source_start_min,
        ) != first_gap:
            raise ValueError("The expected retained-tool gap has changed.")
        next_segments = apply_partial_gap_move(shifted, opportunity, config, move_data)
        if schedule_fingerprint(next_segments, [lot]) == schedule_fingerprint(shifted, [lot]):
            raise ValueError("The gap repair made no progress.")
        shifted = next_segments
        moves += 1
    else:
        raise ValueError("The gap repair did not reach a stable schedule.")
    if moves == 0 or len(shifted) != len(original):
        raise ValueError("The target lot was not compacted without new segments.")
    before_qty, before_prod, before_setup = _physical_totals(original)
    after_qty, after_prod, after_setup = _physical_totals(shifted)
    if before_qty != after_qty or not math.isclose(before_prod, after_prod, abs_tol=1e-6):
        raise ValueError("The repair changed the target quantity or production duration.")
    if before_setup != after_setup or after_setup != 0:
        raise ValueError("The repair changed setup time.")

    replacements = iter(sorted(shifted, key=lambda item: (item.day_idx, item.start_min)))
    updated = [
        next(replacements) if segment.lot_id == lot_id else segment
        for segment in result.segments
    ]
    annotated = copy.deepcopy(updated)
    annotate_left_shift_blockers(annotated, result.lots, data, config)
    for index, segment in enumerate(updated):
        if segment.lot_id == lot_id:
            segment.left_shift_blockers = annotated[index].left_shift_blockers
    revised_target = [segment for segment in updated if segment.lot_id == lot_id]
    data.preserved_lot_proofs[lot_id] = schedule_fingerprint(revised_target, [lot])
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
        "moves": moves,
        "first_start": list(min((s.day_idx, s.start_min) for s in revised_target)),
        "last_end": list(max((s.day_idx, s.end_min) for s in revised_target)),
        "quantity": after_qty,
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
        "plan_revision": repaired["plan_revision"], "bfp082_idle_repair": report,
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
    with tempfile.TemporaryDirectory(prefix="incompolinho-bfp082-idle-") as directory:
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
