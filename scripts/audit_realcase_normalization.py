"""Read-only repetition of normalization on an explicit, isolated snapshot.

Retrospective analysis removes execution proofs only from detached inputs;
manual anchors stay protected. This script has no production writer.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sqlite3
import statistics
import time
from pathlib import Path

from backend.planning_control import planning_scope
from backend.plans.serialize import deserialize_snapshot, schedule_fingerprint
from backend.scheduler.improvement import contract_verdict, physical_setups, physical_signature
from backend.scheduler.scheduler import normalize_earliest_legal_plan
from backend.scheduler.validation import coverage_violations, validate_plan


def read_active(database):
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as db:
        return db.execute(
            "SELECT p.payload_json FROM plans p JOIN plan_runtime r "
            "ON p.id=r.snapshot_id WHERE r.singleton=1"
        ).fetchone()[0]


def audit(database, *, retrospective=False, repetitions=1):
    original = read_active(database)
    payload = json.loads(original)
    elapsed, signature, summaries = [], None, []
    for _ in range(repetitions):
        restored = deserialize_snapshot(copy.deepcopy(payload))
        data, config, result = restored["engine_data"], restored["config"], restored["result"]
        protected = {anchor.lot_id for anchor in data.plan_anchors}
        if retrospective:
            data.preserved_lot_proofs = {}
            result.preserved_lot_proofs = {}
        else:
            protected |= set(data.preserved_lot_proofs)
        before = schedule_fingerprint(result.segments, result.lots)
        assert not validate_plan(result.segments, data, config, lots=result.lots)
        started = time.perf_counter()
        with planning_scope(timeout_s=60):
            candidate = normalize_earliest_legal_plan(
                result.segments, result.lots, data, config, annotate=False,
                protected_lot_ids=protected,
            )
            assert not validate_plan(candidate, data, config, lots=result.lots)
            assert not coverage_violations(candidate, result.lots)
            verdict = contract_verdict(candidate, result.segments, data, candidate_lots=result.lots)
            assert verdict.admissible, verdict.reasons
        elapsed.append(time.perf_counter() - started)
        assert schedule_fingerprint(result.segments, result.lots) == before
        protected_lots = [lot for lot in result.lots if lot.id in protected]
        assert physical_signature([s for s in candidate if s.lot_id in protected], protected_lots) == physical_signature(
            [s for s in result.segments if s.lot_id in protected], protected_lots,
        )
        current_signature = physical_signature(candidate, result.lots)
        assert signature is None or current_signature == signature
        signature = current_signature
        summaries = []
        for lot in result.lots:
            if lot.tool_id not in {"BFP079", "BFP080", "BFP082", "BFP112", "VUL195", "VUL174"}:
                continue
            if lot.edd >= 23:
                continue
            def position(items):
                productive = [s for s in items if s.lot_id == lot.id and s.prod_min > 0]
                first = min(productive, key=lambda s: (s.day_idx, s.production_start_min))
                return [first.machine_id, first.day_idx, first.production_start_min]
            summaries.append({"lot": lot.id, "before": position(result.segments),
                              "after": position(candidate)})
    assert read_active(database) == original
    return {
        "revision": restored["plan_revision"], "retrospective": retrospective,
        "snapshot_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "repetitions": repetitions, "seconds": elapsed,
        "p50_s": statistics.median(elapsed), "p95_s": sorted(elapsed)[max(0, int(.95 * len(elapsed) + .999) - 1)],
        "physics": "passed", "quantity": "passed", "no_loss": "passed",
        "protected_allocations": "unchanged", "source": "unchanged",
        "setups_before": str(physical_setups(result.segments)),
        "setups_after": str(physical_setups(candidate)), "lots": summaries,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--retrospective", action="store_true")
    parser.add_argument("--repetitions", type=int, default=1)
    arguments = parser.parse_args()
    if not 1 <= arguments.repetitions <= 10:
        parser.error("repetitions must be between 1 and 10")
    print(json.dumps(audit(arguments.database.resolve(), retrospective=arguments.retrospective,
                           repetitions=arguments.repetitions), indent=2))


if __name__ == "__main__":
    main()
