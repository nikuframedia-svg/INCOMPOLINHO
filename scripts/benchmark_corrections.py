"""Read-only real-snapshot regression harness. Run from the isolated checkout."""

from __future__ import annotations

import argparse
import copy
import json
import resource
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from backend.config.planning import apply_effective_planning_config
from backend.plans.frozen import optimize_preserving_started_lots
from backend.plans.serialize import deserialize_snapshot, schedule_fingerprint
from backend.scheduler.validation import validate_plan
from backend.telemetry import observe_phases
from backend.transform.calendars import apply_calendars


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/plans.db"))
    parser.add_argument("--case", choices=["prm039", "bfp079", "setup", "operators", "released", "validate"], default="prm039")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--freeze-day", type=int, default=6)
    parser.add_argument("--cancel-after", type=float)
    args = parser.parse_args()
    with sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "plan_runtime" in tables:
            row = db.execute("SELECT p.payload_json FROM plans p JOIN plan_runtime r ON r.snapshot_id=p.id").fetchone()
        else:
            row = db.execute("SELECT payload_json FROM plans WHERE source!='scenario' ORDER BY created_at DESC LIMIT 1").fetchone()
    payload = json.loads(row[0])
    for attempt in range(args.repeat):
        restored = deserialize_snapshot(copy.deepcopy(payload))
        data, config, baseline = restored["engine_data"], restored["config"], restored["result"]
        before = schedule_fingerprint(baseline.segments, baseline.lots)
        if args.case == "validate":
            print(json.dumps({"case": args.case, "revision": restored["plan_revision"], "violations": validate_plan(baseline.segments, data, config, lots=baseline.lots)}, default=str), flush=True)
            continue
        if args.case == "prm039":
            config.machines["PRM039"].oee = 0.44
        elif args.case == "bfp079":
            config.tool_unavailability = [entry for entry in config.tool_unavailability if entry.get("resource") != "BFP079"] + [
                {"id": "bench-bfp079", "resource": "BFP079", "start_at": "2026-10-12T00:00:00+01:00", "end_at": "2026-10-18T23:59:00+01:00"},
            ]
        elif args.case == "setup":
            config.tools["BFP079"]["setup_hours"] = 1.0
        elif args.case in {"operators", "released"}:
            config.operators[("Grandes", "A")] = 6
            config.operators[("Grandes", "B")] = 5
            config.operator_unavailability = [entry for entry in config.operator_unavailability if entry.get("group") != "Grandes"]
            if args.case == "operators":
                config.operator_unavailability.extend(
                    {"id": f"bench-{shift}", "group": "Grandes", "shift": shift, "count": 3,
                     "start_at": "2026-09-21T00:00:00+01:00", "end_at": "2026-09-27T23:59:00+01:00"}
                    for shift in ("A", "B")
                )
        apply_effective_planning_config(data, config)
        apply_calendars(data, config)
        counts, timings = Counter(), Counter()

        def observe(name, event, elapsed):
            if event == "end":
                counts[name] += 1
                timings[name] += elapsed

        started = time.perf_counter()
        report = {"case": args.case, "attempt": attempt, "revision": restored["plan_revision"]}
        cancelled = threading.Event()
        timer = threading.Timer(args.cancel_after, cancelled.set) if args.cancel_after is not None else None
        if timer is not None:
            timer.start()
        try:
            with patch("backend.plans.frozen._current_planning_day", return_value=args.freeze_day), observe_phases(observe):
                result = optimize_preserving_started_lots(data, config, baseline, cancel_event=cancelled)
            from backend.scheduler.canonical import result_validation_data
            from backend.scheduler.operators import operator_peaks
            from dataclasses import asdict

            report.update(status="candidate", score=result.score, gate=result.gate_report,
                          violations=validate_plan(result.segments, result_validation_data(data, result), config, lots=result.lots),
                          fingerprint=schedule_fingerprint(result.segments, result.lots), segments=len(result.segments))
            report["operator_week"] = [asdict(peak) for (day, group, shift), peak in
                                       operator_peaks(result.segments, data, config).items()
                                       if 4 <= day <= 10 and group == "Grandes"]
            report["bfp079"] = [
                {"lot": lot.id, "delivery": lot.edd, "qty": lot.qty,
                 "segments": [{"machine": s.machine_id, "day": s.day_idx, "start": s.start_min,
                               "end": s.end_min, "qty": s.qty} for s in result.segments if s.lot_id == lot.id]}
                for lot in result.lots if lot.tool_id == "BFP079"
            ]
        except Exception as exc:
            report.update(status=type(exc).__name__, error=str(exc), violations=getattr(exc, "violations", []))
        finally:
            if timer is not None:
                timer.cancel()
        report.update(seconds=round(time.perf_counter() - started, 3), calls=dict(counts), timings_ms=dict(timings),
                      rss_mib=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
                      baseline_unchanged=before == schedule_fingerprint(baseline.segments, baseline.lots))
        print(json.dumps(report, default=str), flush=True)


if __name__ == "__main__":
    main()
