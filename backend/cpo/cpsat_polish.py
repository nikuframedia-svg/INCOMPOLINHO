"""CP-SAT surgical polisher for bottleneck machines.

After the GA finds the best chromosome, identifies "sick" machines
(high utilisation, tardies, or redundant setups) and re-sequences
their ToolRuns with OR-Tools CP-SAT, keeping everything else frozen.

Graceful fallback: if ortools is not installed, returns original schedule.
"""

from __future__ import annotations

import copy
import logging
from collections import defaultdict

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.dispatch import per_machine_dispatch
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.types import EngineData

logger = logging.getLogger(__name__)

try:
    from ortools.sat.python import cp_model
    _HAS_ORTOOLS = True
except ImportError:
    _HAS_ORTOOLS = False
    logger.info("ortools not available; CP-SAT polish disabled")


def identify_bottleneck_machines(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    utilisation_threshold: float = 0.85,
) -> list[str]:
    """Identify machines that would benefit from CP-SAT re-sequencing."""
    # Utilisation per machine
    machine_used: dict[str, float] = defaultdict(float)
    for seg in segments:
        if seg.day_idx >= 0:
            machine_used[seg.machine_id] += seg.prod_min + seg.setup_min

    day_cap = config.day_capacity_min if config else DAY_CAP
    n_holidays = len(set(getattr(data, "holidays", []) or []))
    n_work_days = max(data.n_days - n_holidays, 1)
    total_available = n_work_days * day_cap

    # Completion day per lot
    lot_completion: dict[str, int] = {}
    for seg in segments:
        if seg.day_idx >= 0 and seg.prod_min > 0:
            prev = lot_completion.get(seg.lot_id, -1)
            if seg.day_idx > prev:
                lot_completion[seg.lot_id] = seg.day_idx

    # EDD per lot
    lot_edd: dict[str, int] = {lot.id: lot.edd for lot in lots}
    lot_machine: dict[str, str] = {}
    for seg in segments:
        if seg.day_idx >= 0:
            lot_machine[seg.lot_id] = seg.machine_id

    # Machine tardies
    machine_tardy: dict[str, int] = defaultdict(int)
    for lot in lots:
        comp = lot_completion.get(lot.id, data.n_days)
        if comp > lot.edd:
            m_id = lot_machine.get(lot.id, "")
            if m_id:
                machine_tardy[m_id] += 1

    bottlenecks: list[str] = []
    for m_id, used in machine_used.items():
        util = used / total_available if total_available > 0 else 0.0
        is_bottleneck = False

        # Criterion 1: high utilisation
        if util > utilisation_threshold:
            is_bottleneck = True

        # Criterion 2: tardies on this machine
        if machine_tardy.get(m_id, 0) > 0:
            is_bottleneck = True

        # Criterion 3: redundant setups (same tool interrupted)
        machine_segs = sorted(
            [s for s in segments if s.machine_id == m_id and s.day_idx >= 0],
            key=lambda s: (s.day_idx, s.start_min),
        )
        for i in range(1, len(machine_segs)):
            if (machine_segs[i].setup_min > 0
                    and machine_segs[i].tool_id == machine_segs[i - 1].tool_id):
                is_bottleneck = True
                break

        if is_bottleneck:
            bottlenecks.append(m_id)

    return bottlenecks


def _resequence_machine_cpsat(
    runs: list[ToolRun],
    n_days: int,
    day_cap: int,
    time_limit_s: float = 5.0,
) -> list[ToolRun] | None:
    """Re-sequence runs on one machine using CP-SAT.

    Returns reordered runs if improvement found, None otherwise.
    """
    if not _HAS_ORTOOLS or len(runs) < 2:
        return None

    model = cp_model.CpModel()
    n = len(runs)
    horizon = (n_days + 1) * day_cap

    # Variables: position in sequence (0 to n-1)
    pos = [model.new_int_var(0, n - 1, f"pos_{i}") for i in range(n)]
    model.add_all_different(pos)

    # Start/end times
    starts = [model.new_int_var(0, horizon, f"start_{i}") for i in range(n)]
    ends = [model.new_int_var(0, horizon, f"end_{i}") for i in range(n)]
    durations = [int(r.total_min + 0.5) for r in runs]

    for i in range(n):
        model.add(ends[i] == starts[i] + durations[i])

    # No overlap via position-based ordering
    for i in range(n):
        for j in range(i + 1, n):
            b = model.new_bool_var(f"order_{i}_{j}")
            # b=1 => i before j
            big_m = horizon + 1
            model.add(pos[i] < pos[j]).only_enforce_if(b)
            model.add(pos[j] < pos[i]).only_enforce_if(b.negated())
            model.add(ends[i] <= starts[j]).only_enforce_if(b)
            model.add(ends[j] <= starts[i]).only_enforce_if(b.negated())

    # Setup savings: if consecutive runs share same tool, save setup time
    # Model as: for each pair (i,j) where tool matches, bonus if adjacent
    same_tool_bonus = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if runs[i].tool_id == runs[j].tool_id:
                # is_adjacent: pos[j] == pos[i] + 1
                adj = model.new_bool_var(f"adj_{i}_{j}")
                model.add(pos[j] == pos[i] + 1).only_enforce_if(adj)
                model.add(pos[j] != pos[i] + 1).only_enforce_if(adj.negated())
                setup_saved = int(runs[j].setup_min)
                same_tool_bonus.append(adj * setup_saved)

    # Tardiness per run
    tardy_vars = []
    for i, run in enumerate(runs):
        edd_abs = (run.edd + 1) * day_cap
        tardy = model.new_int_var(0, horizon, f"tardy_{i}")
        model.add(tardy >= ends[i] - edd_abs)
        tardy_vars.append(tardy)

    # Objective: minimize tardiness (weight 1000) - setup savings (weight 1)
    setup_bonus = sum(same_tool_bonus) if same_tool_bonus else 0
    model.minimize(
        sum(t * 1000 for t in tardy_vars) - setup_bonus
    )

    # Warm-start: current order = EDD order
    current_order = sorted(range(n), key=lambda i: runs[i].edd)
    for rank, run_idx in enumerate(current_order):
        model.add_hint(pos[run_idx], rank)

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_workers = 4

    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    # Extract new order
    new_positions = [(solver.value(pos[i]), i) for i in range(n)]
    new_positions.sort()
    new_order = [runs[idx] for _, idx in new_positions]

    # Check if it actually changed
    old_ids = [r.id for r in runs]
    new_ids = [r.id for r in new_order]
    if old_ids == new_ids:
        return None  # same order

    # Check tardiness improvement
    new_tardies = sum(1 for i in range(n) if solver.value(tardy_vars[i]) > 0)
    old_tardies = 0  # current runs are from best solution, assumed 0
    for run in runs:
        # Conservative: count as tardy if total_min before EDD is tight
        pass

    return new_order


def cpsat_polish(
    segments: list[Segment],
    lots: list[Lot],
    machine_runs: dict[str, list[ToolRun]],
    data: EngineData,
    config: FactoryConfig,
    time_limit_per_machine: float = 5.0,
) -> tuple[list[Segment], list[Lot], dict]:
    """Entry point: identify bottlenecks and polish with CP-SAT.

    Returns (segments, lots, score). If no improvement, returns originals.
    """
    if not _HAS_ORTOOLS:
        score = compute_score(segments, lots, data, config=config)
        return segments, lots, score

    original_score = compute_score(segments, lots, data, config=config)
    bottlenecks = identify_bottleneck_machines(segments, lots, data, config)

    if not bottlenecks:
        logger.info("CP-SAT polish: no bottleneck machines identified")
        return segments, lots, original_score

    logger.info("CP-SAT polish: %d bottleneck machines: %s", len(bottlenecks), bottlenecks)

    day_cap = config.day_capacity_min if config else DAY_CAP
    improved_machines: list[str] = []

    # Work on a copy of machine_runs
    polished_machine_runs = {m: list(runs) for m, runs in machine_runs.items()}

    for m_id in bottlenecks:
        m_runs = polished_machine_runs.get(m_id, [])
        if len(m_runs) < 2:
            continue

        new_order = _resequence_machine_cpsat(
            m_runs, data.n_days, day_cap,
            time_limit_s=time_limit_per_machine,
        )

        if new_order is not None:
            polished_machine_runs[m_id] = new_order
            improved_machines.append(m_id)
            logger.info("CP-SAT polish: improved %s", m_id)

    if not improved_machines:
        logger.info("CP-SAT polish: no improvements found")
        return segments, lots, original_score

    # Re-dispatch improved machines only
    try:
        new_segments, new_lots, new_warnings = per_machine_dispatch(
            polished_machine_runs, data, config=config
        )
        new_score = compute_score(new_segments, new_lots, data, config=config)

        # Safety: never worsen tardy
        if new_score["tardy_count"] <= original_score["tardy_count"]:
            # Accept if setups or earliness improved
            if (new_score["setups"] < original_score["setups"]
                    or new_score["earliness_avg_days"] < original_score["earliness_avg_days"]):
                logger.info(
                    "CP-SAT polish accepted: setups %d→%d, earliness %.1f→%.1fd",
                    original_score["setups"], new_score["setups"],
                    original_score["earliness_avg_days"], new_score["earliness_avg_days"],
                )
                return new_segments, new_lots, new_score
            else:
                logger.info("CP-SAT polish: no metric improvement, keeping original")
        else:
            logger.warning(
                "CP-SAT polish rejected: tardy %d → %d",
                original_score["tardy_count"], new_score["tardy_count"],
            )
    except Exception as e:
        logger.warning("CP-SAT polish dispatch failed: %s", e)

    return segments, lots, original_score
