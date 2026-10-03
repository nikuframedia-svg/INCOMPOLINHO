"""Repeat an exact move on a read-only snapshot; never apply a candidate."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import time
from unittest.mock import patch


sys.path.insert(0, os.environ.get("CODE_ROOT", str(Path(__file__).resolve().parents[1])))

from backend.plans.manual_move import _production_start, move_lot
from backend.plans.serialize import assert_snapshot_integrity, deserialize_snapshot, schedule_fingerprint
from backend.scheduler.canonical import production_lot_obligations
from backend.scheduler.improvement import physical_signature
from backend.scheduler.validation import coverage_violations, validate_plan
from backend.simulator.mutations import reapply_calendar_mutations
from backend.transform.calendars import apply_calendars
from benchmark_improvement import process_peak_rss_mib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--lot", required=True)
    parser.add_argument("--day", type=int, required=True)
    parser.add_argument("--minute", type=int, required=True)
    parser.add_argument("--machine", required=True)
    parser.add_argument("--freeze-day", type=int, required=True)
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    with sqlite3.connect(f"{args.database.resolve().as_uri()}?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT p.payload_json FROM plans p JOIN plan_runtime r ON r.snapshot_id=p.id "
            "WHERE r.singleton=1"
        ).fetchone()
    if row is None:
        raise ValueError("No explicit active plan")
    payload = json.loads(row[0])
    assert_snapshot_integrity(payload)
    report = {"revision": payload["plan_revision"], "freeze_day": args.freeze_day, "runs": []}
    for attempt in range(args.repeat):
        restored = deserialize_snapshot(copy.deepcopy(payload))
        data, config, before = restored["engine_data"], restored["config"], restored["result"]
        apply_calendars(data, config)
        reapply_calendar_mutations(data, restored.get("active_mutations", []), config)
        unchanged = copy.deepcopy((data, config, before))
        started = time.perf_counter()
        with patch("backend.plans.frozen._current_planning_day", return_value=args.freeze_day):
            result = move_lot(
                before.segments, before.lots, before.score, data, config,
                lot_id=args.lot, target_day=args.day, target_start_min=args.minute,
                target_machine=args.machine, optimization_mode="quick",
            )
        elapsed = time.perf_counter() - started
        errors = validate_plan(result.segments, data, config, lots=result.lots)
        errors += coverage_violations(result.segments, result.lots)
        assert not errors, errors
        assert result.gate_report["physical_gate_passed"]
        assert result.gate_report["coverage_gate_passed"]
        assert _production_start(result.segments, args.lot) == (args.day, float(args.minute), args.machine)
        assert production_lot_obligations(result.lots) == production_lot_obligations(before.lots)
        assert (data, config, before) == unchanged
        assert elapsed <= 62, elapsed
        improvement = result.gate_report.get("improvement") or {}
        entry = {"attempt": attempt, "seconds": round(elapsed, 3),
                 "rss_mib": round(process_peak_rss_mib(), 2),
                 "fingerprint": schedule_fingerprint(result.segments, result.lots),
                 "physical_signature": physical_signature(result.segments, result.lots),
                 "improvement_status": improvement.get("status"),
                 "improvement_stop": improvement.get("stop_reason"),
                 "improvement_moves": improvement.get("moves_accepted"),
                 "apply_decision": result.gate_report["apply_decision"],
                 "physical_errors": errors, "quantities_preserved": True,
                 "source_unchanged": True}
        report["runs"].append(entry)
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps(entry), flush=True)
    times = sorted(entry["seconds"] for entry in report["runs"])
    report["summary"] = {"p50_s": statistics.median(times),
                         "p95_s": times[max(0, math.ceil(.95 * len(times)) - 1)],
                         "max_rss_mib": max(entry["rss_mib"] for entry in report["runs"]),
                         "distinct_fingerprints": len({entry["fingerprint"] for entry in report["runs"]})}
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["summary"]), flush=True)


if __name__ == "__main__":
    main()
