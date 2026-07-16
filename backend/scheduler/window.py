"""Phase 4 (earliness_policy="window") — materials-window dispatch.

Policy: each lot is produced AS EARLY AS POSSIBLE but never before
[lot.edd − material_release_days workdays]. The release offset is the
raw-material availability proxy (Incompol: material arrives ~5 workdays
before the need date).

Mechanics mirror jit_dispatch (same signature, same safety net), with one
inversion: gates are FLOORS (earliest allowed start), not latest-start
targets. Baseline dispatch packs ASAP by construction, so "floor + ASAP"
yields "as early as possible without violating the window".

OTD always wins: floors are statically clamped per lot so they never force
tardiness by themselves (a lot larger than its window keeps its feasible
latest start), and the binary-search safety net relaxes the floors of any
run that still turns tardy — relaxations are reported in the warnings.
"""

from __future__ import annotations

import logging
import math

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.dispatch import assign_machines, per_machine_dispatch
from backend.scheduler.jit import _compute_run_timing, _subtract_workdays
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.types import EngineData

logger = logging.getLogger(__name__)


def compute_lot_floor(lot: Lot, holiday_set: set[int], release_days: int) -> int:
    """Earliest allowed production day for a lot: edd − N workdays."""
    return _subtract_workdays(lot.edd, release_days, holiday_set)


def _lot_latest_start(
    lot: Lot, extra_min: float, holiday_set: set[int], day_cap: int
) -> int:
    """Latest start day that still finishes this lot by its edd (like _max_gate)."""
    days_needed = math.ceil((lot.prod_min + extra_min) / day_cap)
    return _subtract_workdays(lot.edd, days_needed, holiday_set)


def compute_window_gates(
    machine_runs: dict[str, list[ToolRun]],
    holiday_set: set[int],
    config: FactoryConfig,
) -> tuple[dict[str, float], dict[str, float]]:
    """Per-run floor gates + per-lot floors, in absolute minutes.

    Run gate = floor of its first (EDD-earliest) lot. Each lot floor is
    statically OTD-guarded: never later than the lot's own feasible latest
    start, so the window yields when the lot needs more time than the window
    holds.
    """
    day_cap = config.day_capacity_min
    release_days = config.material_release_days

    run_gates: dict[str, float] = {}
    lot_floors: dict[str, float] = {}
    for m_runs in machine_runs.values():
        for run in m_runs:
            first_floor: int | None = None
            for i, lot in enumerate(run.lots):
                floor = compute_lot_floor(lot, holiday_set, release_days)
                extra = run.setup_min if i == 0 else 0.0
                latest = _lot_latest_start(lot, extra, holiday_set, day_cap)
                floor = max(0, min(floor, latest))
                lot_floors[lot.id] = float(floor * day_cap)
                if first_floor is None:
                    first_floor = floor
            run_gates[run.id] = float((first_floor or 0) * day_cap)

    return run_gates, lot_floors


def window_dispatch(
    runs: list[ToolRun],
    engine_data: EngineData,
    baseline_segments: list[Segment],
    baseline_lots: list[Lot],
    baseline_score: dict,
    audit_logger: object | None = None,
    config: FactoryConfig | None = None,
) -> tuple[
    list[Segment], list[Lot], list[str], dict[str, list[ToolRun]] | None, dict[str, float] | None
]:
    """Window policy dispatch — same contract as jit_dispatch.

    Returns (segments, lots, warnings, machine_runs, gates);
    machine_runs and gates are None when reverting to baseline.
    """
    if config is None:
        config = FactoryConfig()
    day_cap = config.day_capacity_min
    target_tardy = baseline_score["tardy_count"]
    holiday_set = set(getattr(engine_data, "holidays", []))

    # Phase 1: assign machines (same load balancing as baseline)
    machine_runs = assign_machines(runs, engine_data, audit_logger=audit_logger, config=config)

    # Phase 2: EDD sort per machine
    for m_id in machine_runs:
        machine_runs[m_id].sort(key=lambda r: r.edd)

    # Phase 3: floor gates (earliest allowed starts)
    current_gate, lot_floors = compute_window_gates(machine_runs, holiday_set, config)
    gated_count = sum(1 for g in current_gate.values() if g > 0)
    logger.info("Window: %d/%d runs floor-gated (release=%dd)",
                gated_count, len(runs), config.material_release_days)

    if audit_logger:
        run_by_id = {r.id: r for r in runs}
        for run_id, gate_abs in current_gate.items():
            if gate_abs > 0 and run_id in run_by_id:
                r = run_by_id[run_id]
                audit_logger.log_gate(run_id, gate_abs, gate_abs, r.edd, "gate_window")

    def _dispatch_all() -> tuple[list[Segment], list[Lot], list[str]]:
        segs: list[Segment] = []
        lots_out: list[Lot] = []
        warns: list[str] = []
        for m_id, m_runs in machine_runs.items():
            m_segs, m_lots, m_warns = per_machine_dispatch(
                {m_id: m_runs},
                engine_data,
                lst_gate=current_gate,
                config=config,
                lot_floors=lot_floors,
            )
            segs.extend(m_segs)
            lots_out.extend(m_lots)
            warns.extend(m_warns)
        return segs, lots_out, warns

    # Phase 4: per-machine dispatch with floors
    win_segs, win_lots, win_warns = _dispatch_all()
    win_score = compute_score(win_segs, win_lots, engine_data, config=config)

    # Phase 5: binary-search safety net — relax floors of tardy runs toward 0.
    # OTD always wins over the material window.
    relaxed_runs: set[str] = set()
    max_retries = config.jit_max_retries
    for _attempt in range(max_retries):
        if win_score["tardy_count"] <= target_tardy:
            break

        _, run_end = _compute_run_timing(win_segs)
        run_by_id = {r.id: r for r in runs}
        adjusted = False
        for rid, end_day in run_end.items():
            run = run_by_id.get(rid)
            if run is None or end_day <= run.edd:
                continue
            hi = current_gate.get(rid, 0.0)
            if hi <= 0.0:
                continue
            mid = hi / 2.0
            current_gate[rid] = mid if mid > day_cap * 0.5 else 0.0
            for lot in run.lots:
                lot_floors.pop(lot.id, None)
            relaxed_runs.add(rid)
            adjusted = True

        if not adjusted:
            break

        win_segs, win_lots, win_warns = _dispatch_all()
        win_score = compute_score(win_segs, win_lots, engine_data, config=config)

    # Final check: revert to baseline if the window still hurts delivery
    if win_score["tardy_count"] > target_tardy:
        logger.warning(
            "Window safety net: tardy %d > %d after %d retries, reverting to baseline",
            win_score["tardy_count"],
            target_tardy,
            max_retries,
        )
        return (
            baseline_segments,
            baseline_lots,
            [
                "Janela de materiais: revertido para baseline "
                f"(tardy {win_score['tardy_count']} > {target_tardy})"
            ],
            None,
            None,
        )

    warnings = [
        f"Janela de materiais: {gated_count} runs com chão de {config.material_release_days} "
        f"dias úteis, earliness {baseline_score.get('earliness_avg_days', 0):.1f}"
        f" → {win_score.get('earliness_avg_days', 0):.1f}d",
    ]
    if relaxed_runs:
        warnings.append(
            f"Janela cedeu ao OTD em {len(relaxed_runs)} run(s): "
            + ", ".join(sorted(relaxed_runs))
        )
    warnings.extend(win_warns)

    return win_segs, win_lots, warnings, machine_runs, current_gate


def window_policy_active(config: FactoryConfig | None) -> bool:
    """True when the materials-window policy replaces JIT."""
    return bool(config and getattr(config, "earliness_policy", "jit") == "window")


def effective_earliness_target(config: FactoryConfig | None) -> float:
    """Average-earliness ceiling, recalibrated under the window policy.

    The window is measured in WORKDAYS while earliness_avg_days is measured in
    day indices (weekends/holidays included), so 5 workdays can span 7+ day
    indices — a strict jit target would false-alarm under the window policy.
    """
    if config is None:
        return 6.0
    target = config.jit_earliness_target
    if window_policy_active(config):
        return max(target, config.material_release_days * 1.5)
    return target


DAY_CAP_DEFAULT = DAY_CAP  # re-export for tests
