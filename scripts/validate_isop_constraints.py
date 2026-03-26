"""Full constraint validation on real ISOP data.

Tests ALL HARD, SOFT, and STRUCTURAL constraints on both ISOPs.
"""

from __future__ import annotations

import sys
import os
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from backend.config.loader import load_config
from backend.config.types import FactoryConfig
from backend.parser.isop_reader import read_isop
from backend.scheduler.constants import DAY_CAP
from backend.cpo import optimize
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import ScheduleResult
from backend.transform.transform import transform
from backend.types import EngineData


# ─── Data loading ──────────────────────────────────────────────────────

def load_isop(path: str) -> EngineData:
    config = load_config()
    raw_rows, workdays, has_twin_col = read_isop(path)
    master_data = None
    yaml_path = Path("config/factory.yaml")
    if yaml_path.exists():
        with open(yaml_path) as f:
            master_data = yaml.safe_load(f)
    return transform(raw_rows, workdays, has_twin_col, master_data)


# ─── Constraint checks ────────────────────────────────────────────────

def validate_all(result: ScheduleResult, data: EngineData, label: str) -> dict:
    """Run ALL constraints. Returns dict of {name: (passed, detail)}."""
    segs = result.segments
    lots = result.lots
    score = result.score
    holidays = set(data.holidays) if data.holidays else set()

    results = {}

    # ═══ HARD CONSTRAINTS ═══

    # 1. OTD = 100%
    results["OTD = 100%"] = (
        score["otd"] == 100.0,
        f"OTD={score['otd']}%"
    )

    # 2. OTD-D = 100%
    results["OTD-D = 100%"] = (
        score["otd_d"] == 100.0 and score["otd_d_failures"] == 0,
        f"OTD-D={score['otd_d']}%, failures={score['otd_d_failures']}"
    )

    # 3. Tardy = 0
    results["Tardy = 0"] = (
        score["tardy_count"] == 0,
        f"tardy={score['tardy_count']}, max_tardiness={score['max_tardiness']}"
    )

    # 4. Shift bounds [420, 1440]
    shift_violations = []
    for seg in segs:
        if seg.start_min < 420:
            shift_violations.append(f"{seg.lot_id} day={seg.day_idx} start={seg.start_min}<420")
        if seg.end_min > 1440:
            shift_violations.append(f"{seg.lot_id} day={seg.day_idx} end={seg.end_min}>1440")
    results["Shift bounds [420,1440]"] = (
        len(shift_violations) == 0,
        f"{len(shift_violations)} violations" + (f": {shift_violations[:3]}" if shift_violations else "")
    )

    # 5. Feriados — nenhum segmento em dias feriados
    holiday_violations = [
        f"{seg.lot_id} on day {seg.day_idx}"
        for seg in segs if seg.day_idx in holidays
    ]
    results["Feriados respeitados"] = (
        len(holiday_violations) == 0,
        f"{len(holiday_violations)} violations" + (f": {holiday_violations[:3]}" if holiday_violations else "")
    )

    # 6. PRM020 inactivo
    prm020_segs = [seg for seg in segs if seg.machine_id == "PRM020"]
    results["PRM020 inactivo"] = (
        len(prm020_segs) == 0,
        f"{len(prm020_segs)} segments on PRM020"
    )

    # 7. Tool contention — mesma ferramenta nunca em 2 máquinas ao mesmo tempo
    tool_contention_violations = _check_tool_contention(segs)
    results["Tool contention"] = (
        len(tool_contention_violations) == 0,
        f"{len(tool_contention_violations)} violations" + (f": {tool_contention_violations[:3]}" if tool_contention_violations else "")
    )

    # 8. Crew mutex — nenhum setup simultâneo entre máquinas
    crew_violations = _check_crew_mutex(segs)
    results["Crew mutex"] = (
        len(crew_violations) == 0,
        f"{len(crew_violations)} violations" + (f": {crew_violations[:3]}" if crew_violations else "")
    )

    # 9. Day capacity — used_per_day ≤ 1020 min por máquina
    cap_violations = _check_day_capacity(segs)
    results["Day capacity <= 1020"] = (
        len(cap_violations) == 0,
        f"{len(cap_violations)} violations" + (f": {cap_violations[:3]}" if cap_violations else "")
    )

    # 10. Eco lot — quantidades arredondadas para cima ao lote económico
    eco_violations = _check_eco_lot(lots, data)
    results["Eco lot"] = (
        len(eco_violations) == 0,
        f"{len(eco_violations)} violations" + (f": {eco_violations[:3]}" if eco_violations else "")
    )

    # 11. Demand conservation — sum(produced) ≥ sum(demanded) por operação
    demand_violations = _check_demand_conservation(segs, lots, data)
    results["Demand conservation"] = (
        len(demand_violations) == 0,
        f"{len(demand_violations)} violations" + (f": {demand_violations[:3]}" if demand_violations else "")
    )

    # ═══ SOFT CONSTRAINTS ═══

    # 12. Earliness ≤ 6.5d
    earliness = score["earliness_avg_days"]
    results["Earliness <= 6.5d"] = (
        earliness <= 6.5,
        f"earliness={earliness:.1f}d"
    )

    # 13. Setups — não regride (referência: 134 para 17/03, 125 para 27/02)
    setups = score["setups"]
    results["Setups razoáveis"] = (
        setups <= 140,  # reasonable upper bound
        f"setups={setups}"
    )

    # 14. Segment overlaps — 0 overlaps intra-máquina/dia
    overlap_count = _check_segment_overlaps(segs)
    results["0 overlaps intra-máquina"] = (
        overlap_count == 0,
        f"{overlap_count} overlaps"
    )

    # ═══ STRUCTURAL ═══

    # 15. Segment start < end (= OK para markers)
    inverted = [
        f"{seg.lot_id} day={seg.day_idx} start={seg.start_min} >= end={seg.end_min}"
        for seg in segs if seg.start_min > seg.end_min
    ]
    results["Segment start <= end"] = (
        len(inverted) == 0,
        f"{len(inverted)} inverted" + (f": {inverted[:3]}" if inverted else "")
    )

    # 16. Segment qty >= 0
    neg_qty = [
        f"{seg.lot_id} qty={seg.qty}"
        for seg in segs if seg.qty < 0
    ]
    results["Segment qty >= 0"] = (
        len(neg_qty) == 0,
        f"{len(neg_qty)} negative" + (f": {neg_qty[:3]}" if neg_qty else "")
    )

    # 17. Min prod_min — todos os lotes com prod_min >= 1.0 ou qty > 0
    min_prod_violations = [
        f"{lot.id} prod_min={lot.prod_min:.2f} qty={lot.qty}"
        for lot in lots if lot.qty > 0 and lot.prod_min < 1.0
    ]
    results["Min prod_min >= 1.0"] = (
        len(min_prod_violations) == 0,
        f"{len(min_prod_violations)} violations" + (f": {min_prod_violations[:3]}" if min_prod_violations else "")
    )

    return results


# ─── Individual check functions ───────────────────────────────────────

def _check_tool_contention(segs: list) -> list[str]:
    """Check same tool never on 2 machines at same time."""
    violations = []
    by_tool_day: dict[tuple[str, int], dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for seg in segs:
        by_tool_day[(seg.tool_id, seg.day_idx)][seg.machine_id].append(seg)

    for (tool, day), machines in by_tool_day.items():
        if len(machines) <= 1:
            continue
        machine_list = list(machines.keys())
        for i in range(len(machine_list)):
            for j in range(i + 1, len(machine_list)):
                for s1 in machines[machine_list[i]]:
                    for s2 in machines[machine_list[j]]:
                        if s1.start_min < s2.end_min and s2.start_min < s1.end_min:
                            violations.append(
                                f"{tool} day={day}: {machine_list[i]}[{s1.start_min}-{s1.end_min}] "
                                f"vs {machine_list[j]}[{s2.start_min}-{s2.end_min}]"
                            )
    return violations


def _check_crew_mutex(segs: list) -> list[str]:
    """Check no simultaneous setups between machines.

    Uses sweep line: track crew_free_at and the machine that set it.
    Any cross-machine overlap is a violation.
    """
    violations = []
    setups = []
    for seg in segs:
        if seg.setup_min > 0 and seg.day_idx >= 0:
            abs_start = seg.day_idx * DAY_CAP + (seg.start_min - 420)
            abs_end = abs_start + seg.setup_min
            setups.append((abs_start, abs_end, seg.machine_id, seg.lot_id))

    setups.sort()

    # Sweep: track the furthest-ending setup and its machine
    crew_free_at = 0.0
    crew_machine = ""
    crew_lot = ""

    for abs_start, abs_end, machine, lot in setups:
        if abs_start < crew_free_at - 1.0 and machine != crew_machine:
            violations.append(
                f"{crew_machine}({crew_lot}) ends@{crew_free_at:.0f} vs {machine}({lot}) starts@{abs_start:.0f}"
            )
        # Update crew_free_at to the max end seen so far
        if abs_end > crew_free_at:
            crew_free_at = abs_end
            crew_machine = machine
            crew_lot = lot

    return violations


def _check_day_capacity(segs: list) -> list[str]:
    """Check used_per_day <= 1020 min per machine."""
    violations = []
    used: dict[tuple[str, int], float] = defaultdict(float)
    for seg in segs:
        if seg.day_idx >= 0:
            used[(seg.machine_id, seg.day_idx)] += seg.prod_min + seg.setup_min

    for (machine, day), total in used.items():
        if total > DAY_CAP + 1.0:  # 1 min tolerance
            violations.append(f"{machine} day={day}: {total:.1f}min > {DAY_CAP}")
    return violations


def _check_eco_lot(lots: list, data: EngineData) -> list[str]:
    """Check eco lot rounding."""
    violations = []
    eco_lots = {op.id: op.eco_lot for op in data.ops if op.eco_lot > 0}

    for lot in lots:
        if lot.op_id in eco_lots and lot.qty > 0 and not lot.is_twin:
            eco = eco_lots[lot.op_id]
            if lot.qty % eco != 0:
                violations.append(f"{lot.id}: qty={lot.qty} not multiple of eco={eco}")
    return violations


def _check_demand_conservation(segs: list, lots: list, data: EngineData) -> list[str]:
    """Check sum(produced) >= sum(demanded) per op."""
    violations = []

    demand: dict[str, int] = {}
    for op in data.ops:
        demand[op.id] = sum(max(0, d) for d in op.d)

    lot_to_op = {lot.id: lot.op_id for lot in lots}

    produced: dict[str, int] = defaultdict(int)
    for seg in segs:
        if seg.twin_outputs:
            for op_id, sku, qty in seg.twin_outputs:
                produced[op_id] += qty
        else:
            op_id = lot_to_op.get(seg.lot_id, "")
            if op_id:
                produced[op_id] += seg.qty

    for op_id, dem in demand.items():
        if dem > 0:
            prod = produced.get(op_id, 0)
            if prod < dem:
                violations.append(f"{op_id}: produced={prod} < demand={dem}")
    return violations


def _check_segment_overlaps(segs: list) -> int:
    """Count segment overlaps within same machine/day."""
    count = 0
    by_md: dict[tuple[str, int], list] = defaultdict(list)
    for seg in segs:
        by_md[(seg.machine_id, seg.day_idx)].append(seg)

    for (machine, day), day_segs in by_md.items():
        day_segs.sort(key=lambda s: s.start_min)
        for i in range(len(day_segs) - 1):
            if day_segs[i].end_min > day_segs[i + 1].start_min + 1:  # 1 min tolerance
                count += 1
    return count


# ─── Main ─────────────────────────────────────────────────────────────

def main():
    isop_files = [
        "ISOP_ Nikufra_27_2.xlsx",
        "ISOP_ Nikufra_17_3.xlsx",
    ]

    config = load_config()
    all_passed = True

    for isop_file in isop_files:
        if not Path(isop_file).exists():
            print(f"  SKIP: {isop_file} not found")
            continue

        print(f"\n{'='*70}")
        print(f"  ISOP: {isop_file}")
        print(f"{'='*70}")

        data = load_isop(isop_file)
        print(f"  {len(data.ops)} ops, {len(data.machines)} machines, {data.n_days} days")
        print(f"  {len(data.twin_groups)} twin groups, {len(data.holidays)} holidays")

        # Run CPO optimizer
        print(f"\n  Running CPO normal mode...")
        t0 = time.perf_counter()
        result = optimize(data, mode="normal", config=config, seed=42)
        elapsed = time.perf_counter() - t0

        score = result.score
        print(f"  Done in {elapsed:.1f}s")
        print(f"  OTD={score['otd']}%, OTD-D={score['otd_d']}%, "
              f"tardy={score['tardy_count']}, setups={score['setups']}, "
              f"earliness={score['earliness_avg_days']:.1f}d")

        # Run ALL constraint checks
        print(f"\n  {'─'*66}")
        print(f"  {'CONSTRAINT':40s} {'STATUS':8s} DETAIL")
        print(f"  {'─'*66}")

        checks = validate_all(result, data, isop_file)

        n_pass = 0
        n_fail = 0
        hard_fail = False

        sections = [
            ("HARD", [
                "OTD = 100%", "OTD-D = 100%", "Tardy = 0",
                "Shift bounds [420,1440]", "Feriados respeitados", "PRM020 inactivo",
                "Tool contention", "Crew mutex", "Day capacity <= 1020",
                "Eco lot", "Demand conservation",
            ]),
            ("SOFT", [
                "Earliness <= 6.5d", "Setups razoáveis", "0 overlaps intra-máquina",
            ]),
            ("STRUCTURAL", [
                "Segment start <= end", "Segment qty >= 0", "Min prod_min >= 1.0",
            ]),
        ]

        for section_name, constraint_names in sections:
            print(f"\n  [{section_name}]")
            for name in constraint_names:
                passed, detail = checks[name]
                status = "PASS" if passed else "FAIL"
                mark = "+" if passed else "X"
                print(f"  [{mark}] {name:40s} {status:8s} {detail}")
                if passed:
                    n_pass += 1
                else:
                    n_fail += 1
                    if section_name == "HARD":
                        hard_fail = True

        print(f"\n  {'─'*66}")
        print(f"  TOTAL: {n_pass} PASS, {n_fail} FAIL")
        if hard_fail:
            print(f"  *** HARD CONSTRAINT FAILURE ***")
            all_passed = False
        elif n_fail > 0:
            print(f"  (all HARD pass, {n_fail} soft/structural fail)")
        else:
            print(f"  ALL CONSTRAINTS PASS")

    print(f"\n{'='*70}")
    if all_passed:
        print("  OVERALL: ALL HARD CONSTRAINTS PASS ON ALL ISOPs")
    else:
        print("  OVERALL: HARD CONSTRAINT FAILURES DETECTED")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
