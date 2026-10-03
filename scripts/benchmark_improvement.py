"""Read-only benchmark of capacity-release compaction on the explicit active plan."""

from __future__ import annotations

import argparse
import copy
import json
import math
import resource
import sqlite3
import statistics
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from backend.planning_control import planning_scope
from backend.plans.frozen import compact_preserving_started_lots
from backend.plans.serialize import (
    assert_snapshot_integrity, deserialize_snapshot, schedule_fingerprint, serialize_result_snapshot,
)
from backend.scheduler.canonical import production_lot_obligations, result_validation_data
from backend.scheduler.improvement import no_loss_verdict, plan_facts, production_windows
from backend.scheduler.scoring import compute_score
from backend.scheduler.validation import plan_anchor_violations, validate_plan
from backend.simulator.mutations import reapply_calendar_mutations
from backend.telemetry import observe_phases
from backend.transform.calendars import apply_calendars


def process_peak_rss_mib():
    # Linux rusage can retain the launcher's pre-exec high-water mark.
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--freeze-day", type=int, required=True)
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path)
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
        data, config, baseline = restored["engine_data"], restored["config"], restored["result"]
        apply_calendars(data, config)
        reapply_calendar_mutations(data, restored.get("active_mutations", []), config)
        baseline.score = compute_score(baseline.segments, baseline.lots, data, config)
        assert not validate_plan(baseline.segments, data, config, lots=baseline.lots)
        before = schedule_fingerprint(baseline.segments, baseline.lots)
        reference = plan_facts(baseline.segments, baseline.lots, data, baseline.score)
        initial_windows = production_windows(baseline.segments)
        counts, timings = Counter(), Counter()

        def observe(name, event, elapsed):
            if event == "end":
                counts[name] += 1
                timings[name] += elapsed

        started = time.perf_counter()
        with patch("backend.plans.frozen._current_planning_day", return_value=args.freeze_day), \
                observe_phases(observe), planning_scope(timeout_s=60):
            result = compact_preserving_started_lots(data, config, baseline)
        elapsed = time.perf_counter() - started
        view = result_validation_data(data, result)
        errors = validate_plan(result.segments, view, config, lots=result.lots)
        errors += plan_anchor_violations(result.segments, view, config)
        verdict = no_loss_verdict(plan_facts(result.segments, result.lots, view, result.score), reference)
        assert not errors, errors
        assert verdict.admissible, verdict.reasons
        assert production_lot_obligations(result.lots) == production_lot_obligations(baseline.lots)
        assert before == schedule_fingerprint(baseline.segments, baseline.lots)
        assert elapsed <= 62, elapsed
        entry = {"attempt": attempt, "seconds": round(elapsed, 3),
                 "rss_mib": round(process_peak_rss_mib(), 2),
                 "fingerprint": schedule_fingerprint(result.segments, result.lots),
                 "calls": dict(counts), "timings_ms": dict(timings),
                 "improvement": result.improvement_report,
                 "physical_errors": errors, "no_loss": verdict.admissible}
        entry["anticipations"] = [
            {"lot_id": lot_id, "before": initial_windows[lot_id], "after": window}
            for lot_id, window in production_windows(result.segments).items()
            if lot_id in initial_windows and window[0] < initial_windows[lot_id][0]
        ]
        report["runs"].append(entry)
        print(json.dumps({**{key: entry[key] for key in (
            "attempt", "seconds", "rss_mib", "no_loss", "fingerprint")},
            "anticipations": len(entry["anticipations"])}), flush=True)
    times = sorted(entry["seconds"] for entry in report["runs"])
    report["summary"] = {"p50_s": statistics.median(times),
                         "p95_s": times[max(0, math.ceil(.95 * len(times)) - 1)],
                         "max_rss_mib": max(entry["rss_mib"] for entry in report["runs"]),
                         "distinct_fingerprints": len({entry["fingerprint"] for entry in report["runs"]})}
    args.output.write_text(json.dumps(report, indent=2))
    if args.candidate_output is not None:
        args.candidate_output.write_text(json.dumps(serialize_result_snapshot(
            data, config, result, plan_revision=payload["plan_revision"],
            dataset_info=payload.get("dataset_info"),
        )))
    print(json.dumps(report["summary"]), flush=True)


if __name__ == "__main__":
    main()
