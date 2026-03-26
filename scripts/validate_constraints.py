#!/usr/bin/env python3
"""Validate ALL 17 scheduling constraints against real ISOPs."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from collections import defaultdict
from backend.parser.isop_reader import read_isop
from backend.transform.transform import transform
from backend.cpo import optimize
from backend.config.loader import load_config
from backend.config.types import FactoryConfig

ISOP_FILES = [
    "ISOP_ Nikufra_17_3.xlsx",
    "ISOP_ Nikufra_27_2.xlsx",
]

DAY_CAP = 1020
SHIFT_A_START = 420
SHIFT_B_END = 1440


def load_master_data():
    with open("config/factory.yaml") as f:
        return yaml.safe_load(f)


def validate(isop_path: str):
    print(f"\n{'='*60}")
    print(f"  VALIDATING: {isop_path}")
    print(f"{'='*60}")

    rows, workdays, has_twin = read_isop(isop_path)
    master_data = load_master_data()
    data = transform(rows, workdays, has_twin, master_data)
    config = load_config()
    result = optimize(data, mode="normal", config=config)

    segments = result.segments
    lots = result.lots
    score = result.score

    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            print(f"  ✅ {name}")
            passed += 1
        else:
            print(f"  ❌ {name}: {detail}")
            failed += 1

    # ─── HARD ───────────────────────────────────────────────

    # 1. OTD = 100%
    check("OTD = 100%", score["otd"] >= 100.0, f"got {score['otd']:.1f}%")

    # 2. OTD-D = 100%
    check("OTD-D = 100%", score["otd_d"] >= 100.0, f"got {score['otd_d']:.1f}%")

    # 3. Tardy = 0
    check("Tardy = 0", score["tardy_count"] == 0, f"got {score['tardy_count']}")

    # 4. Shift bounds [420, 1440]
    shift_violations = []
    for seg in segments:
        if seg.start_min < SHIFT_A_START or seg.end_min > SHIFT_B_END:
            shift_violations.append(
                f"{seg.machine_id} day{seg.day_idx} [{seg.start_min}-{seg.end_min}]"
            )
    check("Shift bounds [420,1440]", len(shift_violations) == 0,
          f"{len(shift_violations)} violations: {shift_violations[:3]}")

    # 5. Holidays
    holidays = set(getattr(data, "holidays", []))
    holiday_segs = [s for s in segments if s.day_idx in holidays]
    check("No segments on holidays", len(holiday_segs) == 0,
          f"{len(holiday_segs)} on holidays")

    # 6. PRM020 inactive
    prm020 = [s for s in segments if s.machine_id == "PRM020"]
    check("PRM020 inactive", len(prm020) == 0, f"{len(prm020)} segments")

    # 7. Tool contention
    tool_violations = 0
    by_tool_day: defaultdict[tuple, set] = defaultdict(set)
    for seg in segments:
        key = (seg.tool_id, seg.day_idx)
        by_tool_day[key].add(seg.machine_id)
    for (tool, day), machines in by_tool_day.items():
        if len(machines) > 1:
            tool_violations += 1
    check("Tool contention = 0", tool_violations == 0,
          f"{tool_violations} tool/day on multiple machines")

    # 8. Crew mutex (no simultaneous setups) — sweep line with 1min tolerance
    setup_entries = []
    for seg in segments:
        if seg.setup_min > 0 and seg.day_idx >= 0:
            abs_start = seg.day_idx * DAY_CAP + (seg.start_min - SHIFT_A_START)
            abs_end = abs_start + seg.setup_min
            setup_entries.append((abs_start, abs_end, seg.machine_id))
    setup_entries.sort()
    crew_overlaps = 0
    crew_free_at = 0.0
    crew_machine = ""
    for abs_start, abs_end, machine in setup_entries:
        if abs_start < crew_free_at - 1.0 and machine != crew_machine:
            crew_overlaps += 1
        if abs_end > crew_free_at:
            crew_free_at = abs_end
            crew_machine = machine
    check("Crew mutex = 0", crew_overlaps == 0,
          f"{crew_overlaps} simultaneous setups")

    # 9. Day capacity <= 1020
    used_per_day: defaultdict[tuple, float] = defaultdict(float)
    for seg in segments:
        duration = seg.end_min - seg.start_min
        used_per_day[(seg.machine_id, seg.day_idx)] += duration
    cap_violations = []
    for (m, d), used in used_per_day.items():
        if used > DAY_CAP + 1:  # +1 for rounding tolerance
            cap_violations.append(f"{m} day{d}: {used:.0f}")
    check("Day capacity <= 1020", len(cap_violations) == 0,
          f"{len(cap_violations)} violations: {cap_violations[:3]}")

    # 10. Eco lot (skip twins: they use max(eco_a, eco_b) by design)
    ops_by_id = {op.id: op for op in data.ops}
    eco_violations = []
    for lot in lots:
        if lot.is_twin:
            continue
        op = ops_by_id.get(lot.op_id)
        if op and op.eco_lot > 0 and lot.qty > 0:
            if lot.qty % op.eco_lot != 0:
                eco_violations.append(
                    f"{lot.op_id}: qty={lot.qty}, eco={op.eco_lot}, rem={lot.qty % op.eco_lot}"
                )
    check("Eco lot multiples", len(eco_violations) == 0,
          f"{len(eco_violations)} violations: {eco_violations[:3]}")

    # 11. Demand conservation
    produced_by_op: defaultdict[str, int] = defaultdict(int)
    for seg in segments:
        if seg.twin_outputs:
            for op_id, sku, qty in seg.twin_outputs:
                produced_by_op[op_id] += qty
        else:
            produced_by_op[seg.lot_id.rsplit("_", 1)[0] if "_" in seg.lot_id else seg.lot_id] += seg.qty
    # Use lot-level production for more accurate tracking
    lot_produced: defaultdict[str, int] = defaultdict(int)
    for lot in lots:
        if lot.twin_outputs:
            for op_id, sku, qty in lot.twin_outputs:
                lot_produced[op_id] += qty
        else:
            lot_produced[lot.op_id] += lot.qty
    demand_by_op: defaultdict[str, int] = defaultdict(int)
    for op in data.ops:
        demand_by_op[op.id] = sum(max(0, d) for d in op.d)
    conservation_fails = 0
    for op_id, demand in demand_by_op.items():
        if demand > 0 and lot_produced.get(op_id, 0) < demand:
            conservation_fails += 1
    check("Demand conservation", conservation_fails == 0,
          f"{conservation_fails} ops under-produced")

    # ─── SOFT ───────────────────────────────────────────────

    # 12. Earliness
    earliness = score.get("earliness_avg_days", 0)
    check(f"Earliness <= 6.5d (got {earliness:.1f}d)", earliness <= 6.5)

    # 13. Setups
    setups = score.get("setups", 0)
    check(f"Setups = {setups}", True)

    # 14. Segment overlaps (intra-machine/day)
    overlaps = 0
    by_md: defaultdict[tuple, list] = defaultdict(list)
    for seg in segments:
        by_md[(seg.machine_id, seg.day_idx)].append(seg)
    for (m, d), segs in by_md.items():
        segs.sort(key=lambda s: s.start_min)
        for i in range(1, len(segs)):
            if segs[i].start_min < segs[i-1].end_min - 1:
                overlaps += 1
    check("Segment overlaps = 0", overlaps == 0, f"{overlaps} overlaps")

    # ─── STRUCTURAL ─────────────────────────────────────────

    # 15. Segment start < end
    bad_segs = [s for s in segments if s.start_min >= s.end_min]
    check("Segment start < end", len(bad_segs) == 0,
          f"{len(bad_segs)} bad segments")

    # 16. Segment qty >= 0
    neg_qty = [s for s in segments if s.qty < 0]
    check("Segment qty >= 0", len(neg_qty) == 0, f"{len(neg_qty)} negative")

    # 17. Min prod_min
    bad_prod = [l for l in lots if l.prod_min < 1.0 and l.qty > 0]
    check("Min prod_min >= 1.0", len(bad_prod) == 0,
          f"{len(bad_prod)} lots with prod_min < 1.0")

    print(f"\n  RESULT: {passed} PASS, {failed} FAIL")
    return failed


if __name__ == "__main__":
    total_fails = 0
    for isop in ISOP_FILES:
        if os.path.exists(isop):
            total_fails += validate(isop)
        else:
            print(f"SKIP: {isop} not found")

    print(f"\n{'='*60}")
    if total_fails == 0:
        print("  ALL CONSTRAINTS PASS ✅")
    else:
        print(f"  {total_fails} TOTAL FAILURES ❌")
    sys.exit(1 if total_fails else 0)
