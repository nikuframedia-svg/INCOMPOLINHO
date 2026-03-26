"""CLI runner for CPO v3.0 — Load ISOP, run optimizer, print comparison.

Usage:
  python scripts/run_cpo.py --mode normal
  python scripts/run_cpo.py --isop "ISOP_ Nikufra_27_2.xlsx" --mode deep
"""

from __future__ import annotations

import argparse
import logging
import sys
import os
import time

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config.types import FactoryConfig
from backend.cpo import optimize


def main():
    parser = argparse.ArgumentParser(description="CPO v3.0 — Super Scheduler")
    parser.add_argument("--isop", type=str, help="Path to ISOP Excel file")
    parser.add_argument(
        "--mode", type=str, default="normal",
        choices=["quick", "normal", "deep", "max"],
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    try:
        from backend.config.loader import load_config
        config = load_config()
    except Exception:
        config = FactoryConfig()

    # Load data
    if args.isop:
        engine_data = _load_isop(args.isop, config)
    else:
        engine_data = _build_demo_data()

    print(f"\n{'='*60}")
    print(f"CPO v3.0 — {len(engine_data.ops)} ops, {len(engine_data.machines)} machines, {engine_data.n_days} days")
    print(f"{'='*60}\n")

    # Baseline
    print("Running baseline (greedy)...")
    t0 = time.perf_counter()
    baseline = optimize(engine_data, mode="quick", config=config)
    baseline_time = (time.perf_counter() - t0) * 1000

    # CPO
    print(f"Running CPO mode={args.mode}...")
    cpo_result = optimize(engine_data, mode=args.mode, config=config, seed=args.seed)

    # Print comparison
    print(f"\n{'─'*60}")
    print(f"{'':20s} {'Setups':>8s} {'Earliness':>10s} {'Tardy':>7s} {'OTD':>6s} {'OTD-D':>7s} {'Time':>8s}")
    print(f"{'─'*60}")

    _print_row("Baseline", baseline.score, baseline_time)
    _print_row(f"CPO {args.mode}", cpo_result.score, cpo_result.time_ms)

    print(f"{'─'*60}")

    # Improvement summary
    b_setups = baseline.score.get("setups", 0)
    c_setups = cpo_result.score.get("setups", 0)
    b_earl = baseline.score.get("earliness_avg_days", 0)
    c_earl = cpo_result.score.get("earliness_avg_days", 0)

    if b_setups > 0:
        setup_pct = (b_setups - c_setups) / b_setups * 100
        print(f"\nSetups:    {b_setups} -> {c_setups} ({setup_pct:+.1f}%)")
    if b_earl > 0:
        earl_pct = (b_earl - c_earl) / b_earl * 100
        print(f"Earliness: {b_earl:.1f}d -> {c_earl:.1f}d ({earl_pct:+.1f}%)")

    # Constraint validation
    print(f"\n{'='*60}")
    print("CONSTRAINT VALIDATION")
    print(f"{'='*60}")
    score = cpo_result.score
    _check("OTD = 100%", score.get("otd", 0) == 100.0)
    _check("OTD-D = 100%", score.get("otd_d", 0) == 100.0)
    _check("Tardy = 0", score.get("tardy_count", 1) == 0)
    _check("Earliness <= 6.5d", score.get("earliness_avg_days", 999) <= 6.5)

    # Structural checks
    shift_ok = all(420 <= s.start_min and s.end_min <= 1440 for s in cpo_result.segments)
    _check("Shift bounds [420, 1440]", shift_ok)

    holidays = set(engine_data.holidays)
    holiday_ok = all(s.day_idx not in holidays for s in cpo_result.segments)
    _check("No holidays", holiday_ok)

    prm020_ok = all(s.machine_id != "PRM020" for s in cpo_result.segments)
    _check("PRM020 inactive", prm020_ok)

    start_end_ok = all(s.start_min <= s.end_min for s in cpo_result.segments)
    _check("Segment start <= end", start_end_ok)

    qty_ok = all(s.qty >= 0 for s in cpo_result.segments)
    _check("Segment qty >= 0", qty_ok)


def _print_row(label: str, score: dict, time_ms: float):
    print(
        f"{label:20s} {score.get('setups', 0):>8d} "
        f"{score.get('earliness_avg_days', 0):>9.1f}d "
        f"{score.get('tardy_count', 0):>7d} "
        f"{score.get('otd', 0):>5.1f}% "
        f"{score.get('otd_d', 0):>6.1f}% "
        f"{time_ms/1000:>7.1f}s"
    )


def _check(label: str, passed: bool):
    status = "PASS" if passed else "FAIL"
    mark = "✓" if passed else "✗"
    print(f"  {mark} {label}: {status}")


def _build_demo_data():
    """Build demo data when no ISOP file provided."""
    from backend.types import EOp, MachineInfo
    from backend.scheduler.constants import DAY_CAP

    ops = []
    tools_machines = [
        ("SKU_1", "PRM031", "BFP079", 500.0, "PRM039"),
        ("SKU_2", "PRM031", "BFP083", 600.0, "PRM039"),
        ("SKU_3", "PRM039", "BFP091", 400.0, "PRM043"),
        ("SKU_4", "PRM039", "BFP100", 350.0, None),
        ("SKU_5", "PRM019", "BFP179", 550.0, "PRM043"),
        ("SKU_6", "PRM043", "BFP125", 420.0, "PRM039"),
        ("SKU_7", "PRM042", "VUL115", 200.0, None),
    ]

    for sku, machine, tool, pH, alt in tools_machines:
        d = [0] * 80
        for day in range(5, 80, 12):
            d[day] = 2000
        ops.append(EOp(
            id=f"{tool}_{machine}_{sku}",
            sku=sku, client="DEMO", designation="Demo part",
            m=machine, t=tool, pH=pH, sH=0.5, operators=1,
            eco_lot=1000, alt=alt, stk=0, backlog=0, d=d, oee=0.66, wip=0,
        ))

    machines = [
        MachineInfo(id="PRM019", group="Grandes", day_capacity=DAY_CAP),
        MachineInfo(id="PRM031", group="Grandes", day_capacity=DAY_CAP),
        MachineInfo(id="PRM039", group="Grandes", day_capacity=DAY_CAP),
        MachineInfo(id="PRM042", group="Medias", day_capacity=DAY_CAP),
        MachineInfo(id="PRM043", group="Grandes", day_capacity=DAY_CAP),
    ]

    from backend.types import EngineData
    return EngineData(
        ops=ops, machines=machines, twin_groups=[], client_demands={},
        workdays=[f"2026-03-{d:02d}" for d in range(5, 31)] +
                 [f"2026-04-{d:02d}" for d in range(1, 30)] +
                 [f"2026-05-{d:02d}" for d in range(1, 31)],
        n_days=80, holidays=[10, 25, 40, 55, 70],
    )


def _load_isop(path: str, config: FactoryConfig):
    """Load ISOP Excel and transform to EngineData."""
    try:
        from backend.parser.isop_reader import read_isop
        from backend.transform.transform import transform
        from pathlib import Path
        import yaml

        raw_rows, workdays, has_twin_col = read_isop(path)

        # Load master data from factory.yaml
        master_data = None
        yaml_path = Path("config/factory.yaml")
        if yaml_path.exists():
            with open(yaml_path) as f:
                master_data = yaml.safe_load(f)

        return transform(raw_rows, workdays, has_twin_col, master_data)
    except ImportError as e:
        print(f"Warning: parser/transform not available ({e}). Using demo data.")
        return _build_demo_data()


if __name__ == "__main__":
    main()
