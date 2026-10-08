"""Repeatable benchmark of the improvement cycle on frozen snapshots (plan §7).

Each repetition runs in a fresh process (cold start: imports, snapshot load,
cycle) pinned to ``--cores`` CPUs, and reports wall time, peak RSS (VmHWM),
accepted moves per scope, stop reason and the physical signature of the
result. p50/p95 come from the repetitions; a single machine's numbers are an
observation, not a production SLA. Never writes the plan database.

    .venv/bin/python scripts/benchmark_solver.py --fixture rev90 --budget 10 \\
        --repeat 20 --cores 1 --output /tmp/bench-rev90-1core.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_CHILD = r"""
import copy, json, os, sys, time
from pathlib import Path
sys.path.insert(0, {root!r})
cores = {cores}
allowed = sorted(os.sched_getaffinity(0))
os.sched_setaffinity(0, set(allowed[:cores]))
started = time.perf_counter()
from tests.snapshot_fixture import load_snapshot
from backend.plans.frozen import improve_preserving_protected_lots
from backend.scheduler.improvement import physical_setups, physical_signature, production_windows
snapshot = load_snapshot({fixture!r}, clock={clock!r})
loaded = time.perf_counter()
data, config, result = copy.deepcopy((snapshot.data, snapshot.config, snapshot.result))
improved, report = improve_preserving_protected_lots(
    result, data, copy.deepcopy(data), config,
    copy.deepcopy(snapshot.protected_segments), copy.deepcopy(snapshot.protected_lots),
    snapshot.freeze_day, time_budget_s={budget},
)
finished = time.perf_counter()
before, after = production_windows(snapshot.result.segments), production_windows(improved.segments)
rss = next(int(line.split()[1]) / 1024 for line in Path("/proc/self/status").read_text().splitlines()
           if line.startswith("VmHWM:"))
print(json.dumps({{
    "total_s": round(finished - started, 3), "load_s": round(loaded - started, 3),
    "cycle_s": round(finished - loaded, 3), "rss_mib": round(rss, 1),
    "stop_reason": report.get("stop_reason"), "moves": report.get("moves_accepted"),
    "accepted_by_scope": report.get("accepted_by_scope"),
    "evaluations_by_scope": report.get("evaluations_by_scope"),
    "setups": physical_setups(improved.segments).count,
    "lots_changed": sum(1 for lot in before if before[lot] != after.get(lot)),
    "start_gain_min": round(sum(max(0.0, before[lot][0] - after[lot][0])
                                for lot in before if lot in after), 1),
    "signature": physical_signature(improved.segments, improved.lots),
}}))
"""


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="rev90")
    parser.add_argument("--clock", default=None, help="Replay date (YYYY-MM-DD)")
    parser.add_argument("--budget", type=float, default=10.0)
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    child = _CHILD.format(root=str(ROOT), cores=args.cores, fixture=args.fixture,
                          clock=args.clock, budget=args.budget)
    runs = []
    for index in range(args.repeat):
        completed = subprocess.run(
            [sys.executable, "-c", child], capture_output=True, text=True, check=False,
            cwd=ROOT, env={**os.environ, "PYTHONHASHSEED": "0"},
        )
        if completed.returncode != 0:
            raise SystemExit(f"run {index} failed:\n{completed.stderr[-2000:]}")
        runs.append(json.loads(completed.stdout.strip().splitlines()[-1]))
        print(f"run {index + 1}/{args.repeat}: {runs[-1]['total_s']} s, "
              f"{runs[-1]['moves']} moves, {runs[-1]['stop_reason']}", file=sys.stderr)

    def summary(key: str) -> dict[str, float]:
        values = [float(run[key]) for run in runs]
        return {"p50": _percentile(values, 0.5), "p95": _percentile(values, 0.95),
                "min": min(values), "max": max(values), "mean": round(statistics.mean(values), 3)}

    report = {
        "fixture": args.fixture, "clock": args.clock, "budget_s": args.budget,
        "cores": args.cores, "repeat": args.repeat, "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "total_s": summary("total_s"), "cycle_s": summary("cycle_s"), "load_s": summary("load_s"),
        "rss_mib": summary("rss_mib"), "moves": summary("moves"),
        "lots_changed": summary("lots_changed"), "start_gain_min": summary("start_gain_min"),
        "stop_reasons": {reason: sum(run["stop_reason"] == reason for run in runs)
                         for reason in {run["stop_reason"] for run in runs}},
        "distinct_results": len({run["signature"] for run in runs}),
        "runs": runs,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "runs"}, indent=2))


if __name__ == "__main__":
    main()
