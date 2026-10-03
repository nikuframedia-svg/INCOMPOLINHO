"""Measure optimize() as used by ISOP loading, on the active snapshot inputs.

  PYTHONPATH=. .venv/bin/python docs/tools/melhoria/measure_load_path.py
"""
import copy
import json
import sqlite3
import time

from backend.config.loader import load_config
from backend.config.planning import synchronize_active_twin_groups
from backend.cpo import optimize
from backend.plans.serialize import deserialize_snapshot
from backend.scheduler.validation import validate_plan
from backend.transform.calendars import apply_calendars

con = sqlite3.connect("file:data/plans.db?mode=ro", uri=True)
sid, = con.execute("SELECT snapshot_id FROM plan_runtime WHERE singleton=1").fetchone()
payload = json.loads(con.execute("SELECT payload_json FROM plans WHERE id=?", (sid,)).fetchone()[0])
data = deserialize_snapshot(payload)["engine_data"]
config = load_config("config/factory.yaml")
data = copy.deepcopy(data)
data.plan_anchors = []  # a freshly loaded ISOP carries no manual anchors
synchronize_active_twin_groups(data, config.twins)
apply_calendars(data, config)
started = time.perf_counter()
result = optimize(data, mode="normal", audit=True, config=config)
seconds = time.perf_counter() - started
report = result.improvement_report or {}
print(json.dumps({
    "seconds": round(seconds, 2),
    "violations": len(validate_plan(result.segments, data, config, lots=result.lots)),
    "score": {k: result.score.get(k) for k in ("otd", "otd_d", "tardy_count", "setups",
                                               "setup_time_min", "left_shift_opportunities")},
    "apply_decision": (result.gate_report or {}).get("apply_decision"),
    "improvement": {k: report.get(k) for k in ("status", "stop_reason", "candidates_evaluated",
                                               "moves_accepted", "accepted_by_scope",
                                               "rejections", "duration_ms", "reference", "final")},
}, indent=1, default=str))
