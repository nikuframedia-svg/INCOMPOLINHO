"""Audit earlier placements in a detached snapshot; never writes the plan DB.

Run from the repository with its Python environment. The search scope is one
complete movable run on each eligible machine while all other runs stay fixed.
This reuses the current allocator/validators; it is not an independent oracle.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.planning_control import PlanningTimeout, planning_scope  # noqa: E402
from backend.plans.frozen import _protected_lots  # noqa: E402
from backend.plans.serialize import assert_snapshot_integrity, deserialize_snapshot  # noqa: E402
from backend.scheduler.alternative_repair import (  # noqa: E402
    _eligible_machines,
    _resolve_runs,
    _schedule_run_earliest,
)
from backend.scheduler.canonical import (  # noqa: E402
    result_validation_data,
    source_contract_violations,
)
from backend.scheduler.improvement import no_loss_verdict, plan_facts  # noqa: E402
from backend.scheduler.jit_policy import (  # noqa: E402
    calendar_holidays,
    window_violation_details,
)
from backend.scheduler.scoring import compute_score  # noqa: E402
from backend.scheduler.validation import (  # noqa: E402
    coverage_violations,
    plan_anchor_violations,
    validate_plan,
)


def production_starts(segments):
    result = {}
    for segment in segments:
        if segment.prod_min > 0:
            point = (segment.day_idx, segment.start_min + segment.setup_min, segment.machine_id)
            result[segment.lot_id] = min(result.get(segment.lot_id, point), point)
    return result


def errors(segments, lots, data, config):
    return (
        validate_plan(segments, data, config, lots=lots)
        + coverage_violations(segments, lots)
        + plan_anchor_violations(segments, data, config)
        + source_contract_violations(segments, lots, data, config)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--snapshot-id", help="Read this historical snapshot instead of the active one")
    parser.add_argument("--as-of", default="2026-10-02")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget-seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.budget_seconds <= 0:
        parser.error("budget-seconds must be positive")
    if args.output.resolve() == args.database.resolve():
        parser.error("output must not be the database")
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if args.snapshot_id:
            row = db.execute(
                "SELECT id, payload_json FROM plans WHERE id=?", (args.snapshot_id,),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT p.id, p.payload_json FROM plans p "
                "JOIN plan_runtime r ON r.snapshot_id=p.id WHERE r.singleton=1"
            ).fetchone()
    if row is None:
        raise ValueError("No active snapshot")
    payload = json.loads(row[1])
    assert_snapshot_integrity(payload)
    restored = deserialize_snapshot(payload)
    data, config, baseline = restored["engine_data"], restored["config"], restored["result"]
    if args.as_of not in data.workdays:
        raise ValueError("as-of must be a date present in this snapshot")
    freeze_day = data.workdays.index(args.as_of)
    _, protected_lots, anchored = _protected_lots(baseline, freeze_day, data, config)
    protected = {lot.id for lot in protected_lots}
    view = result_validation_data(data, baseline)
    baseline_errors = errors(baseline.segments, baseline.lots, view, config)
    if baseline_errors:
        raise ValueError(f"Baseline invalid: {baseline_errors}")
    baseline.score = compute_score(
        baseline.segments, baseline.lots, view, config, include_operational_audit=False,
    )
    original = copy.deepcopy((data, config, baseline))
    before = plan_facts(baseline.segments, baseline.lots, view, baseline.score)
    old_starts = production_starts(baseline.segments)
    runs = _resolve_runs(baseline.segments, baseline.lots, None)
    movable = [run for run in runs.values() if not {lot.id for lot in run.lots} & protected]
    report = {
        "snapshot_id": row[0], "revision": payload["plan_revision"],
        "payload_sha256": hashlib.sha256(row[1].encode()).hexdigest(),
        "freeze_day": freeze_day, "freeze_date": args.as_of,
        "lots": len(baseline.lots), "segments": len(baseline.segments),
        "protected_lots": len(protected), "additional_manual_anchors": len(anchored),
        "movable_lots": len(baseline.lots) - len(protected), "movable_runs": len(movable),
        "scope": "One complete run per eligible machine; all other runs fixed",
        "acceptance": "Existing no-loss contract, including the legacy setup cap",
        "window_violations": window_violation_details(
            baseline.segments, baseline.lots, calendar_holidays(view, -14, view.n_days + 30),
        ),
        "trials": [], "safe_anticipations": [], "local_scope_completed": False,
    }
    started = time.perf_counter()
    try:
        with planning_scope(timeout_s=args.budget_seconds):
            for run in sorted(movable, key=lambda item: min(old_starts[lot.id] for lot in item.lots)):
                fixed = [s for s in baseline.segments if s.run_id != run.id]
                for machine in _eligible_machines(run, view, config, baseline.segments):
                    placed = _schedule_run_earliest(
                        run, machine, fixed, view, config, not_before_abs=freeze_day * 1440,
                    )
                    trial = {"run_id": run.id, "tool": run.tool_id, "machine": machine}
                    report["trials"].append(trial)
                    if placed is None:
                        trial["status"] = "no_candidate_in_local_scope"
                        continue
                    rebound, created = placed
                    starts = production_starts(created)
                    advanced = [
                        {"lot_id": lot.id, "before": old_starts[lot.id], "after": starts[lot.id]}
                        for lot in rebound.lots if starts[lot.id][:2] < old_starts[lot.id][:2]
                    ]
                    trial["advanced"] = advanced
                    if not advanced:
                        trial["status"] = "not_earlier"
                        continue
                    segments = [*fixed, *created]
                    replacements = {lot.id: lot for lot in rebound.lots}
                    lots = [replacements.get(lot.id, lot) for lot in baseline.lots]
                    violations = errors(segments, lots, view, config)
                    score = compute_score(segments, lots, view, config, include_operational_audit=False)
                    verdict = no_loss_verdict(plan_facts(segments, lots, view, score), before)
                    trial.update(
                        status="safe" if not violations and verdict.admissible else "rejected",
                        physics=violations, contract_reasons=verdict.reasons,
                    )
                    if trial["status"] == "safe":
                        report["safe_anticipations"].append(trial)
            report["local_scope_completed"] = True
    except PlanningTimeout:
        report["stop_reason"] = "time_limit"
    report["local_seconds"] = round(time.perf_counter() - started, 3)
    report["baseline_errors"] = baseline_errors
    report["counts"] = dict(Counter(item.get("status", "interrupted") for item in report["trials"]))
    proc_status = Path("/proc/self/status")
    if proc_status.exists():
        report["rss_mib"] = next(
            int(line.split()[1]) / 1024
            for line in proc_status.read_text().splitlines() if line.startswith("VmHWM:")
        )
    if hasattr(os, "sched_getaffinity"):
        report["cpu_affinity"] = sorted(os.sched_getaffinity(0))
    assert (data, config, baseline) == original, "Audit mutated its input objects"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "trials"}, default=str))


if __name__ == "__main__":
    main()
