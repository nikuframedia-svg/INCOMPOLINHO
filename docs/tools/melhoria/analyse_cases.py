"""Re-plan the active snapshot as if today were FREEZE_DAY and show the
BFP112 (PRM039) and BFP079 (PRM031/PRM039) placements from the photos.

  CODE_ROOT=<tree> FREEZE_DAY=3 python docs/tools/melhoria/analyse_cases.py
"""
import os
import runpy
import sys
from unittest.mock import patch

root = os.environ.get("CODE_ROOT", ".")
sys.path.insert(0, root)
import backend.plans.frozen as frozen  # noqa: E402

freeze = int(os.environ.get("FREEZE_DAY", "3"))
captured = {}
original = frozen.optimize_preserving_started_lots


def spy(*args, **kwargs):
    result = original(*args, **kwargs)
    captured["result"] = result
    return result


sys.argv = [sys.argv[0], "data/plans.db", "/dev/null"]
with patch.object(frozen, "_current_planning_day", lambda *a, **k: freeze), \
        patch.object(frozen, "optimize_preserving_started_lots", spy):
    try:
        runpy.run_path("docs/tools/melhoria/compare_replan.py", run_name="__main__")
    except Exception as exc:  # noqa: BLE001
        print("ERROR", type(exc).__name__, str(exc)[:200])
result = captured.get("result")
if result is None:
    sys.exit(1)


def hhmm(minute):
    return f"{int(minute) // 60:02d}:{int(minute) % 60:02d}"


print("\n== PRM039 / PRM031, dias 3-12")
for machine in ("PRM039", "PRM031"):
    print(machine)
    rows = sorted(
        (s for s in result.segments
         if s.machine_id == machine and 3 <= s.day_idx <= 12 and s.end_min > s.start_min),
        key=lambda s: (s.day_idx, s.start_min),
    )
    for s in rows:
        print(f"  D{s.day_idx} {hhmm(s.start_min)}-{hhmm(s.end_min)} {s.tool_id:8s} "
              f"setup={s.setup_min:.0f} qty={s.qty} lot={s.lot_id}")
report = result.improvement_report or {}
print("\nimprovement", {k: report.get(k) for k in (
    "status", "stop_reason", "candidates_evaluated", "moves_accepted",
    "accepted_by_scope", "rejections")})

from collections import defaultdict  # noqa: E402

from backend.scheduler.improvement import physical_setups, tool_transfers  # noqa: E402

print("\n== BFP112")
for s in sorted((s for s in result.segments if s.tool_id == "BFP112" and s.end_min > s.start_min),
                key=lambda s: (s.day_idx, s.start_min)):
    print(f"  {s.machine_id} D{s.day_idx} {hhmm(s.start_min)}-{hhmm(s.end_min)} "
          f"setup={s.setup_min:.0f} qty={s.qty} lot={s.lot_id} due={s.production_due_day}")
print("\n== transferências de ferramenta (máquina muda na sequência de uso)")
uses = defaultdict(list)
for s in result.segments:
    if s.end_min > s.start_min:
        uses[s.tool_id].append(s)
for tool, items in sorted(uses.items()):
    items.sort(key=lambda s: (s.day_idx, s.start_min))
    hops = [(a.machine_id, b.machine_id, b.day_idx) for a, b in zip(items, items[1:])
            if a.machine_id != b.machine_id]
    if hops:
        print(f"  {tool}: {hops}")
score = result.score
print("\nscore", {k: score.get(k) for k in ("otd", "otd_d", "tardy_count", "total_tardiness",
                                            "setups", "setup_time_min", "left_shift_opportunities")},
      "physical_setups", physical_setups(result.segments), "transfers", tool_transfers(result.segments))

print("\n== registo do juiz (hipóteses de transferência)")
for key, entry in sorted((report.get("proposal_log") or {}).items()):
    print(f"  {key}: {entry.get('outcome')} {entry.get('reason')} {entry.get('details', [])[:2]}")
print("closing_pass", report.get("closing_pass"), "duration_ms", report.get("duration_ms"),
      "evaluations", report.get("evaluations_by_scope"),
      "skipped", report.get("skipped_by_scope"))
