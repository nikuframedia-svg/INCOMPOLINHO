"""Count accepted moves that add physical setups, per improvement routine.

Runs the real recalculation (compare_replan.py) with the routines wrapped.
  PYTHONPATH=. .venv/bin/python docs/tools/melhoria/measure_setup_tradeoffs.py
"""
import functools
import runpy
import sys
from collections import defaultdict

sys.argv = [sys.argv[0], "data/plans.db", "/dev/null"]
import backend.cpo.optimizer as optimizer  # noqa: E402
import backend.plans.frozen as frozen  # noqa: E402
import backend.scheduler.alternative_repair as alternative_repair  # noqa: E402
import backend.scheduler.priority_normalization as priority_normalization  # noqa: E402
import backend.scheduler.scheduler as scheduler  # noqa: E402
import backend.scheduler.shift_exchange as shift_exchange  # noqa: E402
from backend.scheduler.improvement import physical_setups  # noqa: E402

stats = defaultdict(lambda: {"calls": 0, "changed": 0, "setup_up": 0, "setup_down": 0,
                             "count_delta": 0, "minutes_delta": 0.0})


def segs(value):
    return value if isinstance(value, list) else getattr(value, "segments", None)


def wrap(name, fn):
    @functools.wraps(fn)
    def inner(segments, *args, **kwargs):
        before = physical_setups(segments)
        out = fn(segments, *args, **kwargs)
        after_segments = segs(out)
        entry = stats[name]
        entry["calls"] += 1
        if after_segments is not None:
            after = physical_setups(after_segments)
            changed = after_segments is not segments and (after != before or len(after_segments) != len(segments)
                                                        or getattr(out, "moves", None))
            if changed:
                entry["changed"] += 1
            if (after.count, after.minutes) > (before.count, before.minutes) and (
                    after.count > before.count or after.minutes > before.minutes):
                entry["setup_up"] += 1
            elif after.count < before.count or after.minutes < before.minutes:
                entry["setup_down"] += 1
            entry["count_delta"] += after.count - before.count
            entry["minutes_delta"] += after.minutes - before.minutes
        return out
    return inner


targets = {
    "repair_alternative_machine_delivery": [alternative_repair, scheduler, optimizer, frozen],
    "repair_priority_inversions": [priority_normalization, scheduler, frozen],
    "repair_shift_capacity_exchange": [shift_exchange, scheduler, optimizer, frozen],
}
for name, modules in targets.items():
    original = getattr(modules[0], name)
    wrapped = wrap(name, original)
    for module in modules:
        if hasattr(module, name):
            setattr(module, name, wrapped)
# Late imports inside functions resolve through the defining module.
try:
    runpy.run_path("docs/tools/melhoria/compare_replan.py", run_name="__main__")
except Exception as exc:  # noqa: BLE001
    print("ERROR", type(exc).__name__, exc)
for name, entry in stats.items():
    print(name, dict(entry))
