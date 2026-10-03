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

from backend.config.shifts import (
    clock_to_productive_offset,
    ordered_shifts,
    productive_offset_to_clock,
)
from backend.config.types import FactoryConfig
from backend.scheduler.constants import (
    DAY_CAP,
    EDD_SWAP_TOLERANCE,
    SHIFT_A_END,
    SHIFT_A_START,
    SHIFT_B_END,
)
from backend.scheduler.priority import (
    enforce_same_deadline_run_priority,
    run_priority_key,
)
from backend.scheduler.resources import clone_run_for_machine, rebind_runs_to_machines
from backend.scheduler.setup_identity import run_setup_identity
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


def _productive_position(
    offset_in_day: float,
    config: FactoryConfig | None,
) -> tuple[int, str, int]:
    """Return wall-clock minute, shift id and shift end for a productive offset."""

    if config is None:
        minute = SHIFT_A_START + int(round(offset_in_day))
        shift_id = "A" if minute < SHIFT_A_END else "B"
        shift_end = SHIFT_A_END if minute < SHIFT_A_END else SHIFT_B_END
        return minute, shift_id, shift_end

    minute = productive_offset_to_clock(
        config,
        int(round(offset_in_day)),
        boundary="start",
    )
    for shift in ordered_shifts(config):
        if int(shift.start_min) <= minute < int(shift.end_min):
            return minute, shift.id, int(shift.end_min)
    last = ordered_shifts(config)[-1]
    return int(last.end_min), last.id, int(last.end_min)


def _next_productive_boundary_abs(
    day: int,
    shift_end: int,
    day_cap: int,
    config: FactoryConfig | None,
) -> float:
    if config is None:
        return float((day + 1) * day_cap)
    return float(
        day * day_cap + clock_to_productive_offset(config, int(shift_end))
    )


def _early_load(
    machine_runs: dict[str, list[ToolRun]],
    machine_id: str,
    edd_threshold: int,
) -> float:
    """Sum of total_min for runs with edd <= threshold on this machine."""
    return sum(r.total_min for r in machine_runs.get(machine_id, []) if r.edd <= edd_threshold)


# ─── 5.1 Assign machines ───────────────────────────────────────────────


def _estimate_run_window(
    run: ToolRun,
    machine_runs: dict[str, list[ToolRun]],
    machine_id: str,
    day_cap: float,
) -> tuple[float, float]:
    """Rough absolute-time window [start, end) a run would occupy on a machine.

    Used by assign_machines for tool-contention avoidance. EDD-driven estimate:
    the run is assumed to finish at its EDD and start total_min earlier. This
    is approximate but sufficient to keep two overlapping runs of the SAME tool
    off two different machines.
    """
    end = (run.edd + 1) * day_cap
    start = end - max(run.total_min, 1.0)
    return start, end


def assign_machines(
    runs: list[ToolRun],
    engine_data: EngineData,
    audit_logger: object | None = None,
    config: FactoryConfig | None = None,
) -> dict[str, list[ToolRun]]:
    """Assign runs to machines. Load-balance runs with alt machines.

    Tool contention: a physical tool can move between machines over time but
    must never be on two machines at once. When choosing between primary and
    alt, an option that would place the same tool on a *different* machine
    during an overlapping time window is avoided.
    """
    day_cap = config.day_capacity_min if config else DAY_CAP
    machine_runs: dict[str, list[ToolRun]] = defaultdict(list)
    machine_load: dict[str, float] = defaultdict(float)
    # tool_id -> list of (start_abs, end_abs, machine_id) already assigned
    tool_windows: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
    candidate_cache: dict[tuple[int, str], ToolRun] = {}

    def _run_for_machine(run: ToolRun, machine_id: str) -> ToolRun:
        if config is None:
            return run
        key = (id(run), machine_id)
        candidate = candidate_cache.get(key)
        if candidate is None:
            candidate = clone_run_for_machine(run, machine_id, engine_data, config)
            candidate_cache[key] = candidate
        return candidate

    def _record(run: ToolRun, chosen: str, *, resolved: bool = False) -> None:
        assigned = run if resolved else _run_for_machine(run, chosen)
        machine_runs[chosen].append(assigned)
        machine_load[chosen] += assigned.total_min
        w_start, w_end = _estimate_run_window(assigned, machine_runs, chosen, day_cap)
        tool_windows[assigned.tool_id].append((w_start, w_end, chosen))

    def _conflicts(run: ToolRun, candidate: str) -> bool:
        """True if placing run on candidate overlaps the same tool on another machine."""
        w_start, w_end = _estimate_run_window(run, machine_runs, candidate, day_cap)
        for o_start, o_end, o_machine in tool_windows.get(run.tool_id, []):
            if o_machine != candidate and w_start < o_end and o_start < w_end:
                return True
        return False

    # First pass: runs without alt go to their primary
    has_alt: list[ToolRun] = []
    for run in sorted(runs, key=run_priority_key):
        if run.alt_machine_id is None:
            _record(run, run.machine_id)
            if audit_logger:
                audit_logger.log_assign(
                    run.id,
                    run.tool_id,
                    run.machine_id,
                    [(run.machine_id, machine_load[run.machine_id])],
                    "assign_no_alt",
                )
        else:
            has_alt.append(run)

    # Second pass: runs with alt go to least-loaded machine
    # For early-EDD runs (edd <= 5), use EDD-aware load to avoid overloading
    # machines in the first few days.
    def _sort_total(run: ToolRun) -> float:
        if run.alt_machine_id is None:
            return _run_for_machine(run, run.machine_id).total_min
        return max(
            _run_for_machine(run, run.machine_id).total_min,
            _run_for_machine(run, run.alt_machine_id).total_min,
        )

    has_alt.sort(key=lambda r: (-_sort_total(r), *run_priority_key(r)))
    for run in has_alt:
        primary_run = _run_for_machine(run, run.machine_id)
        alt_run = _run_for_machine(run, run.alt_machine_id)
        candidate_runs = {
            run.machine_id: primary_run,
            run.alt_machine_id: alt_run,
        }
        edd_thresh = config.edd_assign_threshold if config else 5
        if run.edd <= edd_thresh:
            primary_early = (
                _early_load(machine_runs, run.machine_id, run.edd) + primary_run.total_min
            )
            alt_early = _early_load(machine_runs, run.alt_machine_id, run.edd) + alt_run.total_min
            if primary_early <= alt_early:
                chosen = run.machine_id
            else:
                chosen = run.alt_machine_id
            reason = "assign_edd_aware"
            options = [(run.machine_id, primary_early), (run.alt_machine_id, alt_early)]
        else:
            primary_load_val = machine_load.get(run.machine_id, 0) + primary_run.total_min
            alt_load_val = machine_load.get(run.alt_machine_id, 0) + alt_run.total_min
            if primary_load_val <= alt_load_val:
                chosen = run.machine_id
            else:
                chosen = run.alt_machine_id
            reason = "assign_load_balance"
            options = [(run.machine_id, primary_load_val), (run.alt_machine_id, alt_load_val)]

        # Tool contention: if the load-preferred machine would place the same
        # tool on another machine during an overlapping window, switch to the
        # other option when that one is conflict-free.
        if _conflicts(candidate_runs[chosen], chosen):
            other = run.alt_machine_id if chosen == run.machine_id else run.machine_id
            if not _conflicts(candidate_runs[other], other):
                chosen = other
                reason = "assign_tool_contention"

        if audit_logger:
            audit_logger.log_assign(run.id, run.tool_id, chosen, options, reason)
            if reason == "assign_edd_aware":
                audit_logger.decisions[-1].state_snapshot["edd"] = run.edd

        _record(candidate_runs[chosen], chosen, resolved=True)

    # Re-resolve machine-dependent setup/OEE against the chosen machines
    # (no-op unless setup_overrides or per-machine OEE are configured).
    rebind_runs_to_machines(machine_runs, engine_data, config)

    return dict(machine_runs)


# ─── 5.2 Sequence per machine ──────────────────────────────────────────


def sequence_per_machine(
    machine_runs: dict[str, list[ToolRun]],
    audit_logger: object | None = None,
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
) -> dict[str, list[ToolRun]]:
    """Sequence runs per machine: risk priority → campaign → interleave → 2-opt."""
    for machine_id, runs in machine_runs.items():
        runs.sort(key=_run_priority)  # 1. rupture / delivery baseline

        # Campaign grouping: cluster same-tool runs to reduce setups
        before = [r.id for r in runs]
        runs = _campaign_sequence(runs, config=config)
        after_campaign = [r.id for r in runs]
        if audit_logger and before != after_campaign:
            moves = sum(1 for a, b in zip(before, after_campaign) if a != b)
            audit_logger.log_sequence(machine_id, "sequence_campaign", moves)

        interleave = config.interleave_enabled if config else True
        if interleave:
            before = [r.id for r in runs]
            runs = _interleave_urgent(runs)
            after_interleave = [r.id for r in runs]
            if audit_logger and before != after_interleave:
                moves = sum(1 for a, b in zip(before, after_interleave) if a != b)
                audit_logger.log_sequence(machine_id, "sequence_interleave", moves)

        before = [r.id for r in runs]
        runs = _two_opt(runs, config=config)
        runs = enforce_same_deadline_run_priority(runs)
        after_2opt = [r.id for r in runs]
        if audit_logger and before != after_2opt:
            moves = sum(1 for a, b in zip(before, after_2opt) if a != b)
            audit_logger.log_sequence(machine_id, "sequence_2opt", moves)

        machine_runs[machine_id] = runs
    return machine_runs


def _run_priority(run: ToolRun) -> tuple[int, int, int, int, int, int, int, str]:
    return run_priority_key(run)


def _campaign_sequence(runs: list[ToolRun], config: FactoryConfig | None = None) -> list[ToolRun]:
    """Nearest-neighbor: prefer the same setup identity within EDD tolerance.

    Reduces setups by grouping runs of the same tool.
    """
    if len(runs) <= 2:
        return runs

    edd_tol = config.edd_swap_tolerance if config else EDD_SWAP_TOLERANCE
    window = config.campaign_window if config else edd_tol + 10
    result = [runs[0]]
    remaining = list(runs[1:])

    while remaining:
        last = result[-1]
    # Candidates: within campaign window
        candidates = [r for r in remaining if r.edd <= last.edd + window]
        if not candidates:
            candidates = remaining

        # Campaign convenience can only break ties between requirements with
        # the same stock-risk/deadline class.  It must never put a later
        # rupture ahead of the best available requirement.
        most_urgent = min(candidates, key=_run_priority)
        urgency_class = _run_priority(most_urgent)[:3]
        same_setup = [
            run
            for run in candidates
            if run_setup_identity(run) == run_setup_identity(last)
        ]
        same_priority_setup = [
            run for run in same_setup if _run_priority(run)[:3] == urgency_class
        ]
        if same_priority_setup:
            best = min(same_priority_setup, key=_run_priority)
        else:
            best = most_urgent

        result.append(best)
        remaining.remove(best)

    return result


def _interleave_urgent(runs: list[ToolRun]) -> list[ToolRun]:
    """Break campaigns when an urgent run is blocked behind equal setup runs.

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

            # Only act when two consecutive runs share the mounted adjustment.
            if run_setup_identity(current) == run_setup_identity(next_run):
                # Look for runs further ahead with higher operational urgency.
                best_insert = None
                best_idx = None

                for j in range(i + 2, len(result)):
                    candidate = result[j]
                    if (
                        run_setup_identity(candidate) != run_setup_identity(current)
                        and _run_priority(candidate) < _run_priority(next_run)
                    ):
                        if best_insert is None or _run_priority(candidate) < _run_priority(
                            best_insert
                        ):
                            best_insert = candidate
                            best_idx = j

                if best_insert is not None:
                    result.pop(best_idx)
                    result.insert(i + 1, best_insert)
                    changed = True
                    break  # restart scan

            i += 1

    return result


def _two_opt(runs: list[ToolRun], config: FactoryConfig | None = None) -> list[ToolRun]:
    """Local 2-opt: swap adjacent runs to reduce setups within EDD tolerance."""
    tolerance = config.edd_swap_tolerance if config else EDD_SWAP_TOLERANCE
    improved = True
    while improved:
        improved = False
        for i in range(len(runs) - 1):
            if run_setup_identity(runs[i]) == run_setup_identity(runs[i + 1]):
                continue
            for j in range(i + 2, min(i + 10, len(runs))):
                if run_setup_identity(runs[j]) == run_setup_identity(runs[i]):
                    if (
                        abs(runs[i + 1].edd - runs[j].edd) <= tolerance
                        and _run_priority(runs[j]) >= _run_priority(runs[i + 1])
                    ):
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
    tool_tl: ToolTimeline | None = None,
    lot_floors: dict[str, float] | None = None,
) -> tuple[list[Segment], list[Lot], list[str]]:
    """Dispatch runs across machines with one setup resource per group.

    Each machine advances independently through its sequenced run queue.
    Machines wait only for the crew of their own group.  Grandes and Médias
    can therefore be prepared simultaneously.

    The ``tool_tl`` (tool timeline) is SHARED across every machine in this
    call: a physical tool can never be in two machines simultaneously. Callers
    that dispatch machines one-at-a-time (e.g. JIT) should pass a single
    shared ToolTimeline so contention is enforced globally.

    Returns (segments, all_lots, warnings).
    """
    crews = {
        group: CrewState()
        for group in {
            machine.group for machine in engine_data.machines
        }
    }
    if tool_tl is None:
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

    # Priority queue: availability, then deterministic run urgency.
    # Machines with earliest available time get served first.
    # Tie-break by most urgent EDD so crew serves the most time-critical machine.
    heap: list[tuple[float, int, int, int, str, str]] = []
    for m_id in queues:
        if queues[m_id]:
            heapq.heappush(heap, (0.0, *run_priority_key(queues[m_id][0]), m_id))

    while heap:
        *_priority, machine_id = heapq.heappop(heap)

        if not queues[machine_id]:
            continue

        tl = timelines[machine_id]
        holiday_set = machine_holiday_sets.get(machine_id, global_holidays)

        # Process runs while the exact tool adjustment can be retained.
        while queues[machine_id]:
            run = queues[machine_id][0]

            # LST gate (Fix 2): don't start before Latest Start Time
            # lst_gate values are in absolute minutes.
            if lst_gate and run.id in lst_gate:
                if tl.available_at < lst_gate[run.id]:
                    tl.available_at = lst_gate[run.id]

            setup_identity = run_setup_identity(run)
            needs_setup = tl.last_setup_identity != setup_identity

            queues[machine_id].pop(0)
            # Merge tool-blocked days into holiday set for this run
            run_holidays = holiday_set | tool_blocked.get(run.tool_id, set())
            segments = _allocate_run(
                run,
                machine_id,
                needs_setup,
                timelines,
                crews.setdefault(tl.group, CrewState()),
                tool_tl,
                engine_data,
                run_holidays,
                config=config,
                lot_floors=lot_floors,
            )
            all_segments.extend(segments)

            # A retained adjustment can continue without re-entering the crew heap.
            if (
                queues[machine_id]
                and run_setup_identity(queues[machine_id][0]) == setup_identity
            ):
                continue
            break  # back to heap for crew-aware scheduling

        # Re-enqueue if more runs remain
        if queues[machine_id]:
            heapq.heappush(
                heap,
                (tl.available_at, *run_priority_key(queues[machine_id][0]), machine_id),
            )

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
    lot_floors: dict[str, float] | None = None,
) -> list[Segment]:
    """Allocate a ToolRun on a machine. Returns segments."""
    max_attempts = max(10, len(tool_tl.bookings.get(run.tool_id, [])) + 5)
    candidate_start = timelines[machine_id].available_at
    last_segments: list[Segment] = []

    for _ in range(max_attempts):
        previous_machine = tool_tl.previous_machine(run.tool_id, candidate_start)
        candidate_needs_setup = needs_setup or (
            previous_machine is not None and previous_machine != machine_id
        )
        segments, final_abs, crew_available, used_per_day = _allocate_run_candidate(
            run,
            machine_id,
            candidate_needs_setup,
            timelines,
            crew,
            engine_data,
            holidays,
            candidate_start,
            config=config,
            lot_floors=lot_floors,
        )
        last_segments = segments
        if not segments:
            return segments

        first_abs = _segment_start_abs(segments[0], config)
        previous_machine = tool_tl.previous_machine(run.tool_id, first_abs)
        if (
            not candidate_needs_setup
            and previous_machine is not None
            and previous_machine != machine_id
        ):
            needs_setup = True
            continue
        conflict = _first_tool_conflict(tool_tl, run.tool_id, first_abs, final_abs, machine_id)
        if conflict is None:
            tl = timelines[machine_id]
            tl.available_at = final_abs
            tl.last_tool = run.tool_id
            tl.last_setup_identity = run_setup_identity(run)
            for day, used in used_per_day.items():
                tl.used_per_day[day] = tl.used_per_day.get(day, 0) + used
            crew.available_at = crew_available
            tool_tl.book(run.tool_id, first_abs, final_abs, machine_id)
            return segments

        candidate_start = _snap_to_shift(
            conflict[1],
            holidays,
            day_cap=config.day_capacity_min if config else DAY_CAP,
        )

    return last_segments


def _allocate_run_candidate(
    run: ToolRun,
    machine_id: str,
    needs_setup: bool,
    timelines: dict[str, MachineState],
    crew: CrewState,
    engine_data: EngineData,
    holidays: set[int],
    candidate_start: float,
    config: FactoryConfig | None = None,
    lot_floors: dict[str, float] | None = None,
) -> tuple[list[Segment], float, float, dict[int, float]]:
    """Build a run allocation without mutating shared machine/crew/tool state."""
    day_cap = config.day_capacity_min if config else DAY_CAP
    tl = timelines[machine_id]
    segments: list[Segment] = []
    used_per_day: dict[int, float] = {}

    start_abs = max(tl.available_at, candidate_start)
    start_abs = _snap_to_shift(start_abs, holidays, day_cap=day_cap)
    crew_available = crew.available_at

    # Setup
    setup_remaining = run.setup_min if needs_setup and run.setup_min > 0 else 0.0
    if needs_setup and run.setup_min > 0:
        setup_start = max(start_abs, crew_available)
        setup_start = _snap_to_shift(setup_start, holidays, day_cap=day_cap)
        while True:
            day = int(setup_start) // day_cap
            if day >= engine_data.n_days:
                return [], setup_start, crew_available, used_per_day
            offset_in_day = setup_start - day * day_cap
            min_in_day, _shift_id, shift_end = _productive_position(
                offset_in_day,
                config,
            )
            if shift_end - min_in_day >= run.setup_min:
                break
            setup_start = _snap_to_shift(
                _next_productive_boundary_abs(
                    day,
                    shift_end,
                    day_cap,
                    config,
                ),
                holidays,
                day_cap=day_cap,
            )
        crew_available = setup_start + run.setup_min
        start_abs = setup_start

    # Production: each lot sequentially (already in EDD order — Fix 1)
    last_end_on_day: dict[int, float] = {}

    for lot_idx, lot in enumerate(run.lots):
        remaining_min = lot.prod_min
        remaining_qty = lot.qty
        is_first_seg = True

        # Fixed JIT floor applies to the first productive minute.  A required
        # setup may therefore be prepared immediately before that floor.
        if lot_floors:
            floor_abs = lot_floors.get(lot.id)
            productive_abs = start_abs + setup_remaining
            if floor_abs is not None and productive_abs < floor_abs:
                start_abs = floor_abs - setup_remaining
                crew_available = max(crew_available, start_abs + setup_remaining)

        # Fix 5: ensure at least 1 segment even for micro-lots
        while remaining_min > 0.01 or (remaining_qty > 0 and is_first_seg):
            start_abs = _snap_to_shift(start_abs, holidays, day_cap=day_cap)
            day = int(start_abs) // day_cap

            if day >= engine_data.n_days:
                break

            offset_in_day = round(start_abs - day * day_cap, 2)

            # Prevent float/int truncation overlaps: ensure we start after last segment
            if day in last_end_on_day and offset_in_day < last_end_on_day[day]:
                offset_in_day = last_end_on_day[day]
                start_abs = day * day_cap + offset_in_day

            min_in_day, shift, shift_end = _productive_position(
                offset_in_day,
                config,
            )

            # Setup only on first segment of first lot of run
            seg_setup = setup_remaining if (lot_idx == 0 and is_first_seg) else 0.0

            day_remaining = shift_end - min_in_day

            if day_remaining < 1:
                start_abs = _snap_to_shift(
                    _next_productive_boundary_abs(
                        day,
                        shift_end,
                        day_cap,
                        config,
                    ),
                    holidays,
                    day_cap=day_cap,
                )
                continue

            # If setup doesn't fit in remaining day, push to next day
            if seg_setup >= day_remaining:
                start_abs = _snap_to_shift(
                    _next_productive_boundary_abs(
                        day,
                        shift_end,
                        day_cap,
                        config,
                    ),
                    holidays,
                    day_cap=day_cap,
                )
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

            # Twin outputs proportional (floor-based to avoid over-allocation)
            twin_out = None
            if lot.twin_outputs and lot.qty > 0:
                if remaining_qty <= 0:
                    # Last segment — assign all remaining twin quantities
                    twin_out = list(lot.twin_outputs)
                else:
                    twin_out = [
                        (op_id, sku, int(qty * block_qty / lot.qty) if lot.qty > 0 else 0)
                        for op_id, sku, qty in lot.twin_outputs
                    ]

            # Lot.sku is the controlling output for a twin cycle.
            sku = lot.sku
            if not sku and lot.twin_outputs:
                sku = lot.twin_outputs[0][1]
            elif not sku and "_" in lot.op_id:
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
                setup_family=lot.setup_family,
                twin_outputs=twin_out,
                lot_qty=lot.qty,
                run_qty=sum(r_lot.qty for r_lot in run.lots),
                run_setup_min=run.setup_min,
                run_lot_count=len(run.lots),
                original_edd=lot.original_edd,
                internal_deadline=lot.internal_deadline,
                delivery_day=lot.delivery_day,
                customer_delivery_day=lot.customer_delivery_day,
                latest_subcontract_dispatch_day=lot.latest_subcontract_dispatch_day,
                subcontract_dispatch_day=lot.subcontract_dispatch_day,
                production_due_day=lot.production_due_day,
                internal_target_day=lot.internal_target_day,
                material_reference_day=lot.material_reference_day,
                material_reference_kind=lot.material_reference_kind,
                eco_lot_isop=lot.eco_lot_isop,
                eco_lot_effective=lot.eco_lot_effective,
                start_buffer_days=lot.start_buffer_days,
                finish_buffer_days=lot.finish_buffer_days,
                target_start_day=lot.target_start_day,
                min_campaign_qty=lot.min_campaign_qty,
                min_campaign_prod_min=lot.min_campaign_prod_min,
                max_group_gap_days=lot.max_group_gap_days,
                planning_priority=lot.planning_priority,
                material_release_day=lot.material_release_day,
                output_milestones=(
                    [dict(item) for item in lot.output_milestones]
                    if lot.output_milestones is not None
                    else None
                ),
                planning_source=lot.planning_source,
                economic_warning=lot.economic_warning,
                is_subcontracted=lot.is_subcontracted,
                subcontract_company_id=lot.subcontract_company_id,
                subcontract_lead_time_days=lot.subcontract_lead_time_days,
                subcontract_buffer_days=lot.subcontract_buffer_days,
            )
            segments.append(seg)

            used_per_day[day] = used_per_day.get(day, 0) + block_min + seg_setup
            last_end_on_day[day] = offset_in_day + block_min + seg_setup
            start_abs += block_min + seg_setup
            remaining_min -= block_min
            remaining_qty -= block_qty
            setup_remaining = 0.0
            is_first_seg = False

            if remaining_qty <= 0:
                break

    return segments, start_abs, crew_available, used_per_day


def _segment_start_abs(seg: Segment, config: FactoryConfig | None = None) -> float:
    day_cap = config.day_capacity_min if config else DAY_CAP
    offset = (
        clock_to_productive_offset(config, seg.start_min)
        if config is not None
        else seg.start_min - SHIFT_A_START
    )
    return seg.day_idx * day_cap + offset


def _first_tool_conflict(
    tool_tl: ToolTimeline,
    tool_id: str,
    start: float,
    end: float,
    machine_id: str,
) -> tuple[float, float, str] | None:
    """Return the first booking on another machine that overlaps [start, end)."""
    conflicts = [
        booking
        for booking in tool_tl.bookings.get(tool_id, [])
        if booking[2] != machine_id and start < booking[1] and booking[0] < end
    ]
    if not conflicts:
        return None
    return min(conflicts, key=lambda booking: booking[0])


def _snap_to_shift(abs_min: float, holidays: set[int], day_cap: int = DAY_CAP) -> float:
    """Snap to valid shift time, skipping holidays."""
    day = int(abs_min) // day_cap
    while day in holidays:
        day += 1
        abs_min = float(day * day_cap)
    return abs_min
