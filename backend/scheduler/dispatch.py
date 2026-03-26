"""Phase 3 — Assign + Sequence + Allocate: Spec 02 v6 §5.

Pipeline:
  1. assign_machines()       — bin pack runs to machines (load balance with alt)
  2. sequence_per_machine()  — EDD → campaign → interleave urgent → 2-opt
  3. per_machine_dispatch()  — allocate segments (crew + tool timeline)

Fix 3: Campaign sequencing (nearest-neighbor by tool family)
Fix 4: Interleave urgent (break campaigns when urgent run is blocked)
Fix 5: Micro-lot threshold lowered to 0.01 in allocator
"""

from __future__ import annotations

import heapq
import logging
from collections import defaultdict

from backend.config.types import FactoryConfig
from backend.scheduler.constants import (
    DAY_CAP,
    EDD_SWAP_TOLERANCE,
    SHIFT_A_END,
    SHIFT_A_START,
    SHIFT_B_END,
)
from backend.scheduler.types import (
    CrewState,
    Lot,
    MachineState,
    Segment,
    ToolRun,
    ToolTimeline,
)
from backend.types import EngineData

logger = logging.getLogger(__name__)


def _early_load(
    machine_runs: dict[str, list[ToolRun]],
    machine_id: str,
    edd_threshold: int,
) -> float:
    """Sum of total_min for runs with edd <= threshold on this machine."""
    return sum(
        r.total_min for r in machine_runs.get(machine_id, [])
        if r.edd <= edd_threshold
    )


# ─── 5.1 Assign machines ───────────────────────────────────────────────


def assign_machines(
    runs: list[ToolRun],
    engine_data: EngineData,
    audit_logger: object | None = None,
    params: object | None = None,
    config: FactoryConfig | None = None,
) -> dict[str, list[ToolRun]]:
    """Assign runs to machines. Load-balance runs with alt machines."""
    machine_runs: dict[str, list[ToolRun]] = defaultdict(list)
    machine_load: dict[str, float] = defaultdict(float)

    # First pass: runs without alt go to their primary
    has_alt: list[ToolRun] = []
    for run in runs:
        if run.alt_machine_id is None:
            machine_runs[run.machine_id].append(run)
            machine_load[run.machine_id] += run.total_min
            if audit_logger:
                audit_logger.log_assign(
                    run.id, run.tool_id, run.machine_id,
                    [(run.machine_id, machine_load[run.machine_id])],
                    "assign_no_alt",
                )
        else:
            has_alt.append(run)

    # Second pass: runs with alt go to least-loaded machine
    # For early-EDD runs (edd <= 5), use EDD-aware load to avoid overloading
    # machines in the first few days.
    has_alt.sort(key=lambda r: -r.total_min)
    for run in has_alt:
        edd_thresh = getattr(params, 'edd_assign_threshold', 5)
        if run.edd <= edd_thresh:
            # EDD-aware: compare load from runs with edd <= run.edd
            primary_early = _early_load(machine_runs, run.machine_id, run.edd)
            alt_early = _early_load(machine_runs, run.alt_machine_id, run.edd)
            if primary_early <= alt_early:
                chosen = run.machine_id
            else:
                chosen = run.alt_machine_id
            if audit_logger:
                audit_logger.log_assign(
                    run.id, run.tool_id, chosen,
                    [(run.machine_id, primary_early), (run.alt_machine_id, alt_early)],
                    "assign_edd_aware",
                )
                audit_logger.decisions[-1].state_snapshot["edd"] = run.edd
        else:
            primary_load_val = machine_load.get(run.machine_id, 0)
            alt_load_val = machine_load.get(run.alt_machine_id, 0)
            if primary_load_val <= alt_load_val:
                chosen = run.machine_id
            else:
                chosen = run.alt_machine_id
            if audit_logger:
                audit_logger.log_assign(
                    run.id, run.tool_id, chosen,
                    [(run.machine_id, primary_load_val), (run.alt_machine_id, alt_load_val)],
                    "assign_load_balance",
                )

        machine_runs[chosen].append(run)
        machine_load[chosen] += run.total_min

    return dict(machine_runs)


# ─── 5.2 Sequence per machine ──────────────────────────────────────────


def sequence_per_machine(
    machine_runs: dict[str, list[ToolRun]],
    audit_logger: object | None = None,
    params: object | None = None,
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
) -> dict[str, list[ToolRun]]:
    """Sequence runs per machine: EDD → campaign → interleave → 2-opt → tardy repair."""
    day_cap = config.day_capacity_min if config else DAY_CAP
    has_holidays = bool(holidays)

    for machine_id, runs in machine_runs.items():
        runs.sort(key=lambda r: r.edd)             # 1. EDD baseline

        if not has_holidays:
            # Campaign grouping only when no weekends/holidays reduce capacity
            before = [r.id for r in runs]
            runs = _campaign_sequence(runs, params=params, config=config)
            after_campaign = [r.id for r in runs]
            if audit_logger and before != after_campaign:
                moves = sum(1 for a, b in zip(before, after_campaign) if a != b)
                audit_logger.log_sequence(machine_id, "sequence_campaign", moves)

            interleave = getattr(params, 'interleave_enabled', config.interleave_enabled if config else True)
            if interleave:
                before = [r.id for r in runs]
                runs = _interleave_urgent(runs)
                after_interleave = [r.id for r in runs]
                if audit_logger and before != after_interleave:
                    moves = sum(1 for a, b in zip(before, after_interleave) if a != b)
                    audit_logger.log_sequence(machine_id, "sequence_interleave", moves)

            before = [r.id for r in runs]
            runs = _two_opt(runs, params=params, config=config)
            after_2opt = [r.id for r in runs]
            if audit_logger and before != after_2opt:
                moves = sum(1 for a, b in zip(before, after_2opt) if a != b)
                audit_logger.log_sequence(machine_id, "sequence_2opt", moves)

        machine_runs[machine_id] = runs
    return machine_runs


def _campaign_sequence(runs: list[ToolRun], params=None, config: FactoryConfig | None = None) -> list[ToolRun]:
    """Nearest-neighbor: prefer same tool within EDD tolerance.

    Reduces setups by grouping runs of the same tool.
    """
    if len(runs) <= 2:
        return runs

    edd_tol = config.edd_swap_tolerance if config else EDD_SWAP_TOLERANCE
    window = getattr(params, 'campaign_window', (config.campaign_window if config else edd_tol + 10))
    result = [runs[0]]
    remaining = list(runs[1:])

    while remaining:
        last = result[-1]
        # Candidates: within campaign window
        candidates = [
            r for r in remaining
            if r.edd <= last.edd + window
        ]
        if not candidates:
            candidates = remaining

        # Prefer same tool
        same_tool = [r for r in candidates if r.tool_id == last.tool_id]
        if same_tool:
            best = min(same_tool, key=lambda r: r.edd)
        else:
            best = min(candidates, key=lambda r: r.edd)

        result.append(best)
        remaining.remove(best)

    return result


def _interleave_urgent(runs: list[ToolRun]) -> list[ToolRun]:
    """Break campaigns when an urgent run is blocked behind same-tool runs.

    When two consecutive runs share a tool (campaign), check if any later run
    has an earlier EDD. If so, move it between them to break the campaign.

    Example:
      BEFORE:  [BFP079 edd=4, BFP079 edd=11, BFP114 edd=6]
      AFTER:   [BFP079 edd=4, BFP114 edd=6, BFP079 edd=11]

    Cost: +2 setups. Benefit: BFP114 on time.
    """
    if len(runs) <= 2:
        return runs

    result = list(runs)
    changed = True

    while changed:
        changed = False
        i = 0
        while i < len(result) - 1:
            current = result[i]
            next_run = result[i + 1]

            # Only act when two consecutive runs share the same tool
            if current.tool_id == next_run.tool_id:
                # Look for runs further ahead with earlier EDD
                best_insert = None
                best_idx = None

                for j in range(i + 2, len(result)):
                    candidate = result[j]
                    if (candidate.tool_id != current.tool_id
                            and candidate.edd < next_run.edd):
                        if best_insert is None or candidate.edd < best_insert.edd:
                            best_insert = candidate
                            best_idx = j

                if best_insert is not None:
                    result.pop(best_idx)
                    result.insert(i + 1, best_insert)
                    changed = True
                    break  # restart scan

            i += 1

    return result


def _two_opt(runs: list[ToolRun], params=None, config: FactoryConfig | None = None) -> list[ToolRun]:
    """Local 2-opt: swap adjacent runs to reduce setups within EDD tolerance."""
    tolerance = getattr(params, 'edd_swap_tolerance', config.edd_swap_tolerance if config else EDD_SWAP_TOLERANCE)
    improved = True
    while improved:
        improved = False
        for i in range(len(runs) - 1):
            if runs[i].tool_id == runs[i + 1].tool_id:
                continue
            for j in range(i + 2, min(i + 6, len(runs))):
                if runs[j].tool_id == runs[i].tool_id:
                    if abs(runs[i + 1].edd - runs[j].edd) <= tolerance:
                        runs[i + 1], runs[j] = runs[j], runs[i + 1]
                        improved = True
                        break
            if improved:
                break
    return runs



# ─── 5.3 Per-machine dispatch (allocate segments) ──────────────────────


def per_machine_dispatch(
    machine_runs: dict[str, list[ToolRun]],
    engine_data: EngineData,
    lst_gate: dict[str, float] | None = None,
    audit_logger: object | None = None,
    config: FactoryConfig | None = None,
) -> tuple[list[Segment], list[Lot], list[str]]:
    """Dispatch runs across machines. Parallel per-machine with crew mutex.

    Each machine advances independently through its sequenced run queue.
    The crew (single setup resource) is shared — machines wait for crew
    only when they need a tool change. Campaign continuations (same tool)
    skip the crew entirely.

    Returns (segments, all_lots, warnings).
    """
    crew = CrewState()
    tool_tl = ToolTimeline()
    timelines: dict[str, MachineState] = {}
    for m in engine_data.machines:
        timelines[m.id] = MachineState(machine_id=m.id, group=m.group)

    global_holidays = set(getattr(engine_data, "holidays", []))
    machine_blocked = getattr(engine_data, "machine_blocked_days", {})
    tool_blocked = getattr(engine_data, "tool_blocked_days", {})

    # Per-machine holiday sets (global holidays + machine-specific blocked days)
    machine_holiday_sets: dict[str, set[int]] = {}
    for m in engine_data.machines:
        machine_holiday_sets[m.id] = global_holidays | machine_blocked.get(m.id, set())

    queues = {m: list(runs) for m, runs in machine_runs.items()}

    all_segments: list[Segment] = []

    # Priority queue: (available_at, next_edd, machine_id)
    # Machines with earliest available time get served first.
    # Tie-break by most urgent EDD so crew serves the most time-critical machine.
    heap: list[tuple[float, int, str]] = []
    for m_id in queues:
        if queues[m_id]:
            heapq.heappush(heap, (0.0, queues[m_id][0].edd, m_id))

    while heap:
        _, _, machine_id = heapq.heappop(heap)

        if not queues[machine_id]:
            continue

        tl = timelines[machine_id]
        holiday_set = machine_holiday_sets.get(machine_id, global_holidays)

        # Process runs — campaign continuation: keep going while same tool
        while queues[machine_id]:
            run = queues[machine_id][0]

            # LST gate (Fix 2): don't start before Latest Start Time
            # lst_gate values are in absolute minutes.
            if lst_gate and run.id in lst_gate:
                if tl.available_at < lst_gate[run.id]:
                    tl.available_at = lst_gate[run.id]

            needs_setup = tl.last_tool != run.tool_id

            queues[machine_id].pop(0)
            # Merge tool-blocked days into holiday set for this run
            run_holidays = holiday_set | tool_blocked.get(run.tool_id, set())
            segments = _allocate_run(
                run, machine_id, needs_setup,
                timelines, crew, tool_tl, engine_data, run_holidays,
                config=config,
            )
            all_segments.extend(segments)

            # Campaign continuation: next run same tool → skip heap, no crew needed
            if (queues[machine_id]
                    and queues[machine_id][0].tool_id == run.tool_id):
                continue
            break  # back to heap for crew-aware scheduling

        # Re-enqueue if more runs remain
        if queues[machine_id]:
            next_edd = queues[machine_id][0].edd
            heapq.heappush(heap, (tl.available_at, next_edd, machine_id))

    # Extract all lots
    all_lots: list[Lot] = []
    for runs in machine_runs.values():
        for run in runs:
            all_lots.extend(run.lots)

    return all_segments, all_lots, []


def _allocate_run(
    run: ToolRun,
    machine_id: str,
    needs_setup: bool,
    timelines: dict[str, MachineState],
    crew: CrewState,
    tool_tl: ToolTimeline,
    engine_data: EngineData,
    holidays: set[int],
    config: FactoryConfig | None = None,
) -> list[Segment]:
    """Allocate a ToolRun on a machine. Returns segments."""
    day_cap = config.day_capacity_min if config else DAY_CAP
    shift_a_start = config.shift_a_start if config else SHIFT_A_START
    shift_a_end = config.shift_a_end if config else SHIFT_A_END
    shift_b_end = config.shift_b_end if config else SHIFT_B_END

    tl = timelines[machine_id]
    segments: list[Segment] = []

    start_abs = tl.available_at

    # Tool contention: wait if tool is booked on another machine
    while not tool_tl.is_available(run.tool_id, start_abs, machine_id):
        start_abs += day_cap  # skip to next day
        start_abs = _snap_to_shift(start_abs, holidays, day_cap=day_cap)

    # Setup
    if needs_setup and run.setup_min > 0:
        setup_start = max(start_abs, crew.available_at)
        setup_start = _snap_to_shift(setup_start, holidays, day_cap=day_cap)
        crew.available_at = setup_start + run.setup_min
        start_abs = setup_start + run.setup_min

    # Production: each lot sequentially (already in EDD order — Fix 1)
    last_end_on_day: dict[int, int] = {}  # track end_min per day to prevent overlaps

    for lot_idx, lot in enumerate(run.lots):
        remaining_min = lot.prod_min
        remaining_qty = lot.qty
        is_first_seg = True

        # Fix 5: ensure at least 1 segment even for micro-lots
        while remaining_min > 0.01 or (remaining_qty > 0 and is_first_seg):
            start_abs = _snap_to_shift(start_abs, holidays, day_cap=day_cap)
            day = int(start_abs) // day_cap

            if day >= engine_data.n_days:
                break

            offset_in_day = start_abs - day * day_cap
            min_in_day = shift_a_start + int(offset_in_day)

            # Prevent float/int truncation overlaps: ensure we start after last segment
            if day in last_end_on_day and min_in_day < last_end_on_day[day]:
                min_in_day = last_end_on_day[day]

            # Setup only on first segment of first lot of run
            seg_setup = (
                run.setup_min
                if (lot_idx == 0 and is_first_seg and needs_setup)
                else 0.0
            )

            day_remaining = shift_b_end - min_in_day

            if day_remaining < 1:
                start_abs = (day + 1) * day_cap
                continue

            # If setup doesn't fit in remaining day, push to next day
            if seg_setup >= day_remaining:
                start_abs = (day + 1) * day_cap
                continue

            # Production time available AFTER setup
            prod_available = day_remaining - seg_setup
            block_min = min(remaining_min, float(prod_available))
            block_min = max(block_min, 0.01)  # never zero

            # Proportional qty
            if lot.prod_min > 0.01 and remaining_min - block_min > 0.01:
                block_qty = round(lot.qty * (block_min / lot.prod_min))
            else:
                block_qty = remaining_qty
            block_qty = min(block_qty, remaining_qty)

            shift = "A" if min_in_day < shift_a_end else "B"

            # Twin outputs proportional
            twin_out = None
            if lot.twin_outputs and lot.qty > 0:
                twin_out = [
                    (op_id, sku, round(qty * block_qty / lot.qty) if lot.qty > 0 else 0)
                    for op_id, sku, qty in lot.twin_outputs
                ]

            # SKU from twin outputs or op_id
            sku = ""
            if lot.twin_outputs:
                sku = lot.twin_outputs[0][1]
            elif "_" in lot.op_id:
                parts = lot.op_id.split("_")
                sku = parts[-1] if len(parts) >= 3 else lot.op_id

            seg = Segment(
                lot_id=lot.id,
                run_id=run.id,
                machine_id=machine_id,
                tool_id=run.tool_id,
                day_idx=day,
                start_min=min_in_day,
                end_min=min_in_day + int(block_min + seg_setup),
                shift=shift,
                qty=block_qty,
                prod_min=block_min,
                setup_min=seg_setup,
                is_continuation=not is_first_seg,
                edd=lot.edd,
                sku=sku,
                twin_outputs=twin_out,
            )
            segments.append(seg)

            tl.used_per_day[day] = tl.used_per_day.get(day, 0) + block_min + seg_setup
            last_end_on_day[day] = seg.end_min
            start_abs += block_min
            remaining_min -= block_min
            remaining_qty -= block_qty
            is_first_seg = False

            if remaining_qty <= 0:
                break

    # Update machine state
    if segments:
        tl.available_at = start_abs
        tl.last_tool = run.tool_id

        first_abs = segments[0].day_idx * day_cap + (segments[0].start_min - shift_a_start)
        tool_tl.book(run.tool_id, first_abs, start_abs, machine_id)

    return segments


def _snap_to_shift(abs_min: float, holidays: set[int], day_cap: int = DAY_CAP) -> float:
    """Snap to valid shift time, skipping holidays."""
    day = int(abs_min) // day_cap
    while day in holidays:
        day += 1
        abs_min = float(day * day_cap)
    return abs_min
