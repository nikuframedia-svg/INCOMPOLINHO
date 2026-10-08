"""Run the improvement cycle on a pickled recalculation (compare_replan.py OUT).

  PYTHONPATH=. .venv/bin/python docs/tools/melhoria/run_improvement_cycle.py OUT.pkl [budget_s]
"""
import json
import pickle
import sys
import time

from backend.config.loader import load_config
from backend.scheduler.improvement import improve_plan

payload = pickle.load(open(sys.argv[1], "rb"))
budget = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
config = load_config("config/factory.yaml")
started = time.perf_counter()
segments, lots, report = improve_plan(
    payload["segments"], payload["lots"], payload["data"], config, time_budget_s=budget,
)
print(json.dumps(report, default=str, indent=1, ensure_ascii=False))
print("wall_s", round(time.perf_counter() - started, 2))
