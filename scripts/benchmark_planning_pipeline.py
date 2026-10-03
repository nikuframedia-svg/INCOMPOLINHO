"""Measure full calculation paths against an explicit read-only snapshot.

CODE_ROOT optionally selects another checkout for before/after comparisons.
Only detached states are updated; this launcher has no production writer.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sqlite3
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.environ.get("CODE_ROOT", str(Path(__file__).resolve().parents[1])))

from backend.config.planning import apply_effective_planning_config
from backend.plans.frozen import optimize_preserving_started_lots
from backend.plans.serialize import deserialize_snapshot, schedule_fingerprint
from backend.planning_control import current_planning_control
from backend.scheduler.canonical import result_validation_data
from backend.scheduler.improvement import contract_verdict
from backend.scheduler.validation import coverage_violations, plan_anchor_violations, validate_plan
from backend.simulator.mutations import reapply_calendar_mutations
from backend.telemetry import observe_phases
from backend.transform.calendars import apply_calendars
from scripts.benchmark_improvement import process_peak_rss_mib


def active_payload(database):
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT p.payload_json FROM plans p JOIN plan_runtime r ON r.snapshot_id=p.id "
            "WHERE r.singleton=1"
        ).fetchone()
    if row is None:
        raise ValueError("No explicit active snapshot")
    return row[0]


def run(payload, case, freeze_day):
    restored = deserialize_snapshot(copy.deepcopy(payload))
    data, config, baseline = restored["engine_data"], restored["config"], restored["result"]
    unchanged = copy.deepcopy((data, config, baseline))
    if case == "bfp079":
        config.tool_unavailability = [*config.tool_unavailability, {
            "id": "pipeline-bfp079", "resource": "BFP079",
            "start_at": "2026-10-12T00:00:00+01:00", "end_at": "2026-10-18T23:59:00+01:00",
        }]
    elif case == "prm039":
        config.machines["PRM039"].oee = .44
    elif case == "setup":
        config.tools["BFP079"]["setup_hours"] = 1.0
    apply_effective_planning_config(data, config)
    apply_calendars(data, config)
    reapply_calendar_mutations(data, restored.get("active_mutations", []), config)
    prepared = copy.deepcopy((data, config, baseline))
    counts, timings = Counter(), Counter()
    bounded_robustness = []

    def observe(name, event, elapsed):
        if name == "robustness" and event == "start":
            control = current_planning_control()
            bounded_robustness.append(control is not None and control.deadline is not None)
        if event == "end":
            counts[name] += 1
            timings[name] += elapsed

    started = time.perf_counter()
    entry = {}
    try:
        with patch("backend.plans.frozen._current_planning_day", return_value=freeze_day), observe_phases(observe):
            if case == "compact":
                from backend.api import data as data_api
                from backend.copilot.state import CopilotState

                target = CopilotState(
                    engine_data=copy.deepcopy(data), config=copy.deepcopy(config),
                    segments=copy.deepcopy(baseline.segments), lots=copy.deepcopy(baseline.lots),
                    score=copy.deepcopy(baseline.score), gate_report=copy.deepcopy(baseline.gate_report),
                    active_mutations=copy.deepcopy(restored.get("active_mutations", [])),
                )
                with patch.object(data_api, "state", target):
                    result = data_api._compact_active_schedule(target.config)
            else:
                result = optimize_preserving_started_lots(data, config, baseline)
        # Do not include this independent postcondition audit in the deadline.
        elapsed = time.perf_counter() - started
        view = result_validation_data(data, result)
        errors = validate_plan(result.segments, view, config, lots=result.lots)
        errors += coverage_violations(result.segments, result.lots)
        errors += plan_anchor_violations(result.segments, view, config)
        assert not errors, errors
        assert result.gate_report["physical_gate_passed"]
        assert result.gate_report["coverage_gate_passed"]
        assert result.score["missing_qty"] == result.score["overproduced_qty"] == 0
        if case == "compact":
            verdict = contract_verdict(result.segments, baseline.segments, view,
                candidate_lots=result.lots, reference_lots=baseline.lots)
            assert verdict.admissible, verdict.reasons
        if case == "bfp079":
            blocked = {day for day, value in enumerate(data.workdays)
                       if "2026-10-12" <= value[:10] <= "2026-10-18"}
            assert not any(s.tool_id == "BFP079" and s.day_idx in blocked
                           and s.end_min > s.start_min for s in result.segments)
        assert elapsed <= 62, elapsed
        entry.update(status="candidate", fingerprint=schedule_fingerprint(result.segments, result.lots),
            segments=len(result.segments), lots=len(result.lots), physics="passed", quantity="passed",
            no_loss="passed" if case == "compact" else "new_scenario",
            improvement=result.improvement_report,
            robustness_samples=result.score.get("robustness_evaluated_samples", 0),
            apply_decision=result.gate_report["apply_decision"])
    except Exception as exc:
        elapsed = time.perf_counter() - started
        entry.update(status=type(exc).__name__, error=str(exc),
                     violations=getattr(exc, "violations", []))
    # frozen optimization temporarily installs reservations; it must undo them.
    assert (data, config, baseline) == prepared
    entry.update(seconds=round(elapsed, 3), rss_mib=round(process_peak_rss_mib(), 2),
        calls=dict(counts), timings_ms=dict(timings), bounded_robustness=bounded_robustness,
        source_snapshot_fingerprint=schedule_fingerprint(unchanged[2].segments, unchanged[2].lots))
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--case", choices=["compact", "bfp079", "prm039", "setup"], required=True)
    parser.add_argument("--freeze-day", type=int, required=True)
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 10:
        parser.error("--repeat must be between 1 and 10")
    database = args.database.resolve()
    original = active_payload(database)
    payload = json.loads(original)
    report = {"case": args.case, "freeze_day": args.freeze_day, "revision": payload["plan_revision"],
              "source_sha256": hashlib.sha256(original.encode()).hexdigest(), "runs": []}
    for attempt in range(args.repeat):
        entry = {"attempt": attempt, **run(payload, args.case, args.freeze_day)}
        report["runs"].append(entry)
        assert active_payload(database) == original
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps({key: entry.get(key) for key in (
            "attempt", "seconds", "rss_mib", "status", "error", "fingerprint", "apply_decision")}), flush=True)
    times = sorted(entry["seconds"] for entry in report["runs"])
    report["summary"] = {"p50_s": statistics.median(times),
        "p95_s": times[max(0, math.ceil(.95 * len(times)) - 1)],
        "max_rss_mib": max(entry["rss_mib"] for entry in report["runs"]),
        "distinct_fingerprints": len({entry.get("fingerprint") for entry in report["runs"]}),
        "candidate_runs": sum(entry["status"] == "candidate" for entry in report["runs"]),
        "source": "unchanged"}
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["summary"]), flush=True)
    if report["summary"]["candidate_runs"] != args.repeat:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
