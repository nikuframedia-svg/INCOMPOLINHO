"""Locate the scheduler phase that first drops a tool-change setup.

Wraps scheduler post-processing functions and, after each call, counts
machine transitions to a different setup identity with no setup minutes.
Run from the worktree root:
  PYTHONPATH=. FREEZE=0 OUT=/tmp/x.pkl .venv/bin/python docs/tools/melhoria/trace_missing_setup.py
"""
import functools
import os
import runpy
import sys
from collections import defaultdict
from unittest.mock import patch

sys.argv = [sys.argv[0], "data/plans.db", os.environ.get("OUT", "/dev/null")]
import backend.plans.frozen as frozen  # noqa: E402
import backend.scheduler.scheduler as sched  # noqa: E402
from backend.scheduler.setup_identity import segment_setup_identity  # noqa: E402
from backend.scheduler.types import Segment  # noqa: E402

NAMES = [
    "per_machine_dispatch", "vns_polish", "_fix_day_overlaps", "_serialize_crew_setups",
    "_serialize_crew_safe", "_sanitize_segments", "_fix_tool_machine_overlaps",
    "_parallelize_independent_setup_starts", "_fix_orphan_continuations",
    "_remove_redundant_retained_tool_setups", "_repair_hard_constraints",
    "normalize_earliest_legal_plan", "repair_alternative_machine_delivery",
    "repair_short_runs_after_merged_campaigns", "repair_shift_capacity_exchange",
]
NAMES += [n for n in dir(sched) if n.startswith(("_jit", "jit_", "_apply_jit", "apply_jit"))]


def segments_of(value):
    if isinstance(value, list) and value and isinstance(value[0], Segment):
        return value
    if isinstance(value, tuple) and value and isinstance(value[0], list):
        return segments_of(value[0])
    segs = getattr(value, "segments", None)
    return segs if isinstance(segs, list) else None


def missing(segments):
    by_machine = defaultdict(list)
    for s in segments:
        if s.end_min > s.start_min or s.setup_min > 0 or s.prod_min > 0:
            by_machine[s.machine_id].append(s)
    found = []
    for m, segs in by_machine.items():
        segs.sort(key=lambda s: (s.day_idx, s.start_min, s.end_min))
        for prev, curr in zip(segs, segs[1:]):
            if curr.setup_min <= 0 and curr.run_setup_min > 0 and \
                    segment_setup_identity(prev) != segment_setup_identity(curr):
                found.append((m, curr.day_idx, curr.start_min, curr.tool_id, prev.tool_id))
    return found


seen_counts = {}
step = [0]


def wrap(name, fn):
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        before = None
        for a in list(args) + list(kwargs.values()):
            before = segments_of(a)
            if before is not None:
                break
        n_before = len(missing(before)) if before is not None else None
        out = fn(*args, **kwargs)
        after = segments_of(out)
        if after is not None:
            n_after = len(missing(after))
            step[0] += 1
            if n_before is None or n_after != n_before or step[0] >= 60:
                print(f"[{step[0]:04d}] {name}: {n_before} -> {n_after}", flush=True)
                if n_after and (n_before or 0) < n_after:
                    new = set(missing(after)) - set(missing(before or []))
                    for item in sorted(new)[:6]:
                        print("        +", item, flush=True)
        return out
    return inner


patches = []
for name in NAMES:
    if hasattr(sched, name):
        patches.append(patch.object(sched, name, wrap(name, getattr(sched, name))))
freeze = os.environ.get("FREEZE")
if freeze is not None:
    patches.append(patch.object(frozen, "_current_planning_day", lambda *a, **k: int(freeze)))
for p in patches:
    p.start()
try:
    runpy.run_path("docs/tools/melhoria/compare_replan.py", run_name="__main__")
except Exception as exc:  # noqa: BLE001
    print("ERROR", type(exc).__name__, str(exc)[:200])
