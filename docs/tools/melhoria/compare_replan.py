"""Read-only reproduction of POST /api/data/recalculate on the active plan.

Usage (cwd = code tree to measure; it must contain config/factory.yaml):
  PYTHONDONTWRITEBYTECODE=1 python compare_replan.py DB OUT.pkl
"""

from __future__ import annotations

import copy
import json
import pickle
import sqlite3
import sys
import time
from pathlib import Path

import os  # noqa: E402
sys.path.insert(0, os.environ.get("CODE_ROOT", str(Path.cwd())))

from backend.config.loader import load_config, validate_config  # noqa: E402
from backend.config.planning import (  # noqa: E402
    apply_effective_planning_config,
    enforce_machine_scope,
    synchronize_active_twin_groups,
)
from backend.cpo import optimize  # noqa: E402
from backend.plans.frozen import optimize_preserving_started_lots  # noqa: E402
from backend.plans.serialize import (  # noqa: E402
    assert_snapshot_integrity,
    deserialize_snapshot,
    schedule_fingerprint,
    serialize_config,
    value_fingerprint,
)
from backend.scheduler.validation import validate_plan  # noqa: E402
from backend.simulator.mutations import reapply_calendar_mutations  # noqa: E402
from backend.transform.calendars import apply_calendars  # noqa: E402


def main() -> None:
    db_path, out = Path(sys.argv[1]), Path(sys.argv[2])
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as con:
        sid, _rev = con.execute(
            "SELECT snapshot_id, plan_revision FROM plan_runtime WHERE singleton=1"
        ).fetchone()
        origin, payload_json = con.execute(
            "SELECT origin, payload_json FROM plans WHERE id=?", (sid,)
        ).fetchone()
    payload = json.loads(payload_json)
    assert_snapshot_integrity(payload, origin=origin)

    restored = deserialize_snapshot(payload)
    data = restored["engine_data"]
    cfg = load_config("config/factory.yaml")
    enforce_machine_scope(cfg, data, restored["result"].segments)
    problems = validate_config(cfg, data)
    assert not problems, problems
    if restored.get("fingerprints", {}).get("config") != value_fingerprint(serialize_config(cfg)):
        print("config drift: startup re-applies config", file=sys.stderr)
        synchronize_active_twin_groups(data, cfg.twins)
        apply_effective_planning_config(data, cfg)
        apply_calendars(data, cfg)
        reapply_calendar_mutations(data, list(restored.get("active_mutations", [])), cfg)
    baseline = restored["result"]
    mutations = restored.get("active_mutations", [])

    data, cfg = copy.deepcopy(data), copy.deepcopy(cfg)
    case = os.environ.get("CASE", "")
    # Same what-if mutations as scripts/benchmark_corrections.py.
    if case == "prm039":
        cfg.machines["PRM039"].oee = 0.44
    elif case == "bfp079":
        cfg.tool_unavailability = [
            entry for entry in cfg.tool_unavailability if entry.get("resource") != "BFP079"
        ] + [{"id": "bench-bfp079", "resource": "BFP079",
              "start_at": "2026-10-12T00:00:00+01:00", "end_at": "2026-10-18T23:59:00+01:00"}]
    elif case == "setup":
        cfg.tools["BFP079"]["setup_hours"] = 1.0
    if case:
        print("case", case, file=sys.stderr)
    synchronize_active_twin_groups(data, cfg.twins)
    apply_calendars(data, cfg)
    if mutations:
        reapply_calendar_mutations(data, mutations, cfg)
    started = time.perf_counter()
    result = optimize_preserving_started_lots(
        data, cfg, baseline, mode="normal", audit=True, optimizer=optimize
    )
    seconds = time.perf_counter() - started

    from backend.scheduler.canonical import result_validation_data

    view = result_validation_data(data, result)
    violations = validate_plan(result.segments, view, cfg, lots=result.lots)
    keys = (
        "otd", "otd_d", "tardy_count", "total_tardiness", "otd_d_failures", "setups",
        "setup_time_min", "left_shift_opportunities", "production_time_cost",
        "earliness_avg_days", "hard_violations", "early_window_violations",
    )
    gate = result.gate_report or {}
    report = {
        "revision": restored["plan_revision"],
        "seconds": round(seconds, 2),
        "score": {key: result.score.get(key) for key in keys},
        "gate_status": gate.get("status"),
        "apply_decision": gate.get("apply_decision"),
        "violations": len(violations),
        "fingerprint": schedule_fingerprint(result.segments, result.lots),
        "campaign_warnings": [w for w in result.warnings if w.startswith("Campanhas de setup")],
        "improvement": {
            key: (result.improvement_report or {}).get(key)
            for key in ("status", "stop_reason", "candidates_evaluated", "moves_accepted",
                        "accepted_by_scope", "rejections", "duration_ms")
        },
    }
    print(json.dumps(report, default=str, indent=1))
    with out.open("wb") as handle:
        pickle.dump({"segments": result.segments, "lots": result.lots, "score": result.score,
                     "data": view}, handle)


if __name__ == "__main__":
    main()
