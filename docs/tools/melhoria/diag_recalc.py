"""Diagnose why the active-plan recalculation yields no valid candidate."""
import os, sys, runpy
from unittest.mock import patch
sys.argv = [sys.argv[0], "data/plans.db", os.environ["OUT"]]
import backend.plans.frozen as frozen
from backend.scheduler import validation
freeze = os.environ.get("FREEZE")
orig_assert = validation.assert_plan_valid
seen = []
def spy(segments, data, config, lots=None, **kw):
    try:
        return orig_assert(segments, data, config, lots=lots, **kw)
    except validation.PlanValidationError as exc:
        seen.append(exc.violations)
        raise
patches = [patch.object(validation, "assert_plan_valid", spy)]
if freeze is not None:
    patches.append(patch.object(frozen, "_current_planning_day", lambda *a, **k: int(freeze)))
for p in patches: p.start()
try:
    runpy.run_path(os.environ["SCRIPT"], run_name="__main__")
except Exception as exc:
    print("ERROR", type(exc).__name__, exc)
from collections import Counter
for i, v in enumerate(seen[:5]):
    print("attempt", i, Counter(x.get("kind") if isinstance(x, dict) else getattr(x, "kind", str(x)[:40]) for x in v))
    for x in v[:4]:
        print("   ", str(x)[:300])
