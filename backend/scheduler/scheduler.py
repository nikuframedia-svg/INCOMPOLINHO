"""Scheduler entry point — Spec 02 v6 §9.

Pipeline:
  Phase 1: lot_sizing      — EOps → Lots (eco lot + twins + min prod_min)
  Phase 2: tool_grouping   — Lots → ToolRuns (group + split + EDD sort)
  Phase 3: dispatch         — assign + sequence + allocate segments
  Phase 4: jit              — LST-gated re-dispatch (safety: fallback)
  Phase 5: scoring          — OTD, OTD-D, setups, earliness, utilisation
"""

from __future__ import annotations

import copy
import logging
import math
import time
from collections import Counter, defaultdict
from dataclasses import replace

from backend.calendar import available_machine_capacity, is_factory_workday
from backend.config.planning import apply_effective_planning_config
from backend.config.shifts import clock_to_productive_offset
from backend.config.types import FactoryConfig
from backend.guardian.guardian import validate_input, validate_output
from backend.journal.journal import Journal
from backend.planning_control import (
    PlanningTimeout,
    planning_checkpoint,
    planning_scope,
    remaining_time,
)
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.dispatch import (
    assign_machines,
    per_machine_dispatch,
    sequence_per_machine,
)
from backend.scheduler.gap_filling import (
    apply_partial_gap_move,
    find_internal_continuation_opportunities,
    find_opening_gap_opportunities,
    split_production_at_shift_boundaries,
)
from backend.scheduler.gates import build_gate_report
from backend.scheduler.jit import jit_dispatch
from backend.scheduler.jit_policy import calendar_holidays, earliest_allowed_start
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.operational_audit import (
    actionable_gap_opportunities,
    build_operational_audit,
)
from backend.scheduler.operators import compute_operator_alerts
from backend.scheduler.priority import (
    delivery_improves,
    delivery_not_worse,
    lot_priority_key,
    run_priority_key,
)
from backend.scheduler.priority_normalization import (
    repair_priority_inversions,
    repair_same_reference_interruptions,
)
from backend.scheduler.protection import protected_lot_ids as planning_protected_lot_ids
from backend.scheduler.scoring import compute_score
from backend.scheduler.setup_identity import retained_setup_at, segment_setup_identity
from backend.scheduler.tool_grouping import create_tool_runs
from backend.scheduler.types import Lot, ScheduleResult, Segment, ToolRun
from backend.scheduler.validation import (
    PlanValidationError,
    abs_to_day_min,
    assert_plan_valid,
    hard_gate_metrics,
    required_setup_minutes,
    segment_abs,
    validate_plan,
)
from backend.telemetry import measured
from backend.types import EngineData

logger = logging.getLogger(__name__)


def _detect_buffer_need(
    runs: list[ToolRun],
    config: FactoryConfig | None = None,
    machine_runs: dict[str, list[ToolRun]] | None = None,
    holidays: set[int] | None = None,
) -> int:
    """Return number of buffer days needed so no machine has infeasible early load.

    For each machine, simulates strict production-due dispatch with holidays.
    If any run completes after its operational due date, computes how many
    extra days are needed. Falls back to the compatibility `edd` field when
    machine runs are not provided.
    """
    import math

    day_cap = config.day_capacity_min if config else DAY_CAP
    hols = holidays or set()

    if machine_runs:
        max_buffer = 0
        for m_id, m_runs in machine_runs.items():
            planning_checkpoint()
            sorted_runs = sorted(m_runs, key=run_priority_key)
            abs_min = 0.0
            for run in sorted_runs:
                # Snap to workday
                day = int(abs_min) // day_cap
                while day in hols:
                    planning_checkpoint()
                    day += 1
                    abs_min = float(day * day_cap)

                remaining = run.total_min
                while remaining > 0.01:
                    planning_checkpoint()
                    day = int(abs_min) // day_cap
                    while day in hols:
                        planning_checkpoint()
                        day += 1
                        abs_min = float(day * day_cap)
                    day_used = abs_min - day * day_cap
                    day_left = day_cap - day_used
                    block = min(remaining, day_left)
                    abs_min += block
                    remaining -= block
                    if remaining > 0.01:
                        abs_min = float((day + 1) * day_cap)

                comp_day = day
                if comp_day > run.edd:
                    tardiness = comp_day - run.edd
                    max_buffer = max(max_buffer, tardiness)
        return max_buffer

    # Fallback: simple edd=0 check
    max_buffer = 0
    for run in runs:
        if run.edd == 0 and run.total_min > day_cap:
            days_needed = math.ceil(run.total_min / day_cap)
            max_buffer = max(max_buffer, days_needed - 1)
    return max_buffer


def _apply_buffer(runs: list[ToolRun], buffer_days: int) -> None:
    """Shift compatibility deadlines and all named milestones forward."""
    for run in runs:
        run.edd += buffer_days
        if run.production_due_day is not None:
            run.production_due_day += buffer_days
        for lot in run.lots:
            lot.edd += buffer_days
            if lot.original_edd is not None:
                lot.original_edd += buffer_days
            if lot.internal_deadline is not None:
                lot.internal_deadline += buffer_days
            if lot.delivery_day is not None:
                lot.delivery_day += buffer_days
            if lot.target_start_day is not None:
                lot.target_start_day += buffer_days
            _shift_named_planning_dates(lot, buffer_days)


def _shift_engine_data(data: EngineData, buffer_days: int) -> EngineData:
    """Return a detached EngineData copy on the temporary buffered timeline."""
    import copy

    shifted = copy.copy(data)
    shifted.n_days = data.n_days + buffer_days
    shifted.calendar_projection_end = data.calendar_projection_end + buffer_days
    shifted.calendar_day_offset = data.calendar_day_offset + buffer_days
    shifted.holidays = [day + buffer_days for day in data.holidays]
    if data.calendar_base_holidays is not None:
        shifted.calendar_base_holidays = [
            day + buffer_days for day in data.calendar_base_holidays
        ]
    shifted.calendar_explicit_holidays = [
        day + buffer_days for day in data.calendar_explicit_holidays
    ]
    shifted.machine_blocked_days = {
        machine: {day + buffer_days for day in days}
        for machine, days in data.machine_blocked_days.items()
    }
    shifted.tool_blocked_days = {
        tool: {day + buffer_days for day in days}
        for tool, days in data.tool_blocked_days.items()
    }

    def shifted_interval(interval: dict) -> dict:
        result = copy.deepcopy(interval)
        if "start_day" in result:
            result["start_day"] = int(result["start_day"]) + buffer_days
        if "end_day" in result:
            result["end_day"] = int(result["end_day"]) + buffer_days
        return result

    shifted.machine_blocked_intervals = {
        machine: [shifted_interval(interval) for interval in intervals]
        for machine, intervals in data.machine_blocked_intervals.items()
    }
    shifted.tool_blocked_intervals = {
        tool: [shifted_interval(interval) for interval in intervals]
        for tool, intervals in data.tool_blocked_intervals.items()
    }
    shifted.operator_blocked_intervals = [
        shifted_interval(interval) for interval in data.operator_blocked_intervals
    ]
    shifted.setup_crew_reservations = [
        shifted_interval(interval) for interval in data.setup_crew_reservations
    ]
    return shifted


def _unshift_segments(segments: list[Segment], buffer_days: int) -> list[Segment]:
    """Shift segment day_idx and edd back by buffer_days.

    Buffer-day production keeps negative day_idx (e.g. day -1) so the
    Gantt can display it truthfully instead of cramming into day 0.
    """
    for seg in segments:
        seg.day_idx = seg.day_idx - buffer_days
        seg.edd -= buffer_days
        if seg.original_edd is not None:
            seg.original_edd -= buffer_days
        if seg.internal_deadline is not None:
            seg.internal_deadline -= buffer_days
        if seg.delivery_day is not None:
            seg.delivery_day -= buffer_days
        if seg.target_start_day is not None:
            seg.target_start_day -= buffer_days
        _shift_named_planning_dates(seg, -buffer_days)
    return segments


def _unshift_lots(lots: list[Lot], buffer_days: int) -> list[Lot]:
    """Shift lot EDDs back by buffer_days."""
    for lot in lots:
        lot.edd -= buffer_days
        if lot.original_edd is not None:
            lot.original_edd -= buffer_days
        if lot.internal_deadline is not None:
            lot.internal_deadline -= buffer_days
        if lot.delivery_day is not None:
            lot.delivery_day -= buffer_days
        if lot.target_start_day is not None:
            lot.target_start_day -= buffer_days
        _shift_named_planning_dates(lot, -buffer_days)
    return lots


def _shift_named_planning_dates(lot_or_segment: Lot | Segment, delta: int) -> None:
    """Shift additive milestone fields used by the legacy auto-buffer path."""

    for field_name in (
        "customer_delivery_day",
        "latest_subcontract_dispatch_day",
        "subcontract_dispatch_day",
        "production_due_day",
        "internal_target_day",
        "material_reference_day",
        "material_release_day",
    ):
        value = getattr(lot_or_segment, field_name, None)
        if value is not None:
            setattr(lot_or_segment, field_name, int(value) + delta)
    outputs = getattr(lot_or_segment, "output_milestones", None)
    if outputs:
        for output in outputs:
            for field_name in (
                "customer_delivery_day",
                "latest_subcontract_dispatch_day",
                "subcontract_dispatch_day",
                "production_due_day",
                "internal_target_day",
                "material_reference_day",
                "material_release_day",
            ):
                value = output.get(field_name)
                if value is not None:
                    output[field_name] = int(value) + delta


def _next_workday(day: int, holidays: set[int]) -> int:
    """Return next day that is not a holiday."""
    d = day
    while d in holidays:
        planning_checkpoint()
        d += 1
    return d


def _fix_day_overlaps(
    segments: list[Segment], config: FactoryConfig | None = None, holidays: set[int] | None = None
) -> list[Segment]:
    """Fix overlapping segments on same machine/day after buffer unshift.

    Per machine: sort all segments by (day_idx, start_min), then sequentially
    ensure each segment starts after the previous one ends. Segments that
    overflow past shift_b_end are pushed intact to the next workday. Physical
    work is never shortened merely to keep an EDD looking feasible.
    """
    shift_a_start = config.shift_a_start if config else 420
    shift_b_end = config.shift_b_end if config else 1440
    hols = holidays or set()

    by_machine: defaultdict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        by_machine[seg.machine_id].append(seg)

    for machine_id, segs in by_machine.items():
        planning_checkpoint()
        segs.sort(key=lambda s: (s.day_idx, s.start_min))
        for i in range(1, len(segs)):
            prev = segs[i - 1]
            curr = segs[i]

            # Only fix overlaps within the same day
            if curr.day_idx != prev.day_idx:
                continue

            if curr.start_min < prev.end_min:
                duration = curr.end_min - curr.start_min
                new_start = prev.end_min
                new_end = new_start + duration

                # If overflows day, move to next workday
                if new_end > shift_b_end:
                    new_day = _next_workday(curr.day_idx + 1, hols)
                    curr.day_idx = new_day
                    curr.start_min = shift_a_start
                    curr.end_min = shift_a_start + duration
                    curr.is_continuation = True
                    curr.shift = "A"
                    # Re-sort needed since we moved a segment to a later day
                    segs.sort(key=lambda s: (s.day_idx, s.start_min))
                    break
                else:
                    curr.start_min = new_start
                    curr.end_min = new_end
        else:
            continue
        # Break happened — re-scan this machine (max iterations = n_segments)
        for _ in range(len(segs)):
            planning_checkpoint()
            segs.sort(key=lambda s: (s.day_idx, s.start_min))
            cascaded = False
            for i in range(1, len(segs)):
                prev = segs[i - 1]
                curr = segs[i]
                if curr.day_idx != prev.day_idx:
                    continue
                if curr.start_min < prev.end_min:
                    duration = curr.end_min - curr.start_min
                    new_start = prev.end_min
                    new_end = new_start + duration
                    if new_end > shift_b_end:
                        new_day = _next_workday(curr.day_idx + 1, hols)
                        curr.day_idx = new_day
                        curr.start_min = shift_a_start
                        curr.end_min = shift_a_start + duration
                        curr.is_continuation = True
                        curr.shift = "A"
                        cascaded = True
                        break
                    else:
                        curr.start_min = new_start
                        curr.end_min = new_end
            if not cascaded:
                break

    return segments


def _try_relocate_truncated(
    seg: Segment,
    all_segments: list[Segment],
    used: dict[tuple[str, int], float],
    shift_a_start: int,
    day_cap: int,
    holidays: set[int],
    lots_by_id: dict[str, Lot] | None = None,
    config: FactoryConfig | None = None,
) -> bool:
    """Try to move a truncated segment to an earlier day with free capacity.

    Searches backward from seg.edd. Checks both total capacity and that the
    segment fits within one configured shift.
    Does NOT check crew availability — caller should log a warning.
    """
    needed = seg.prod_min + seg.setup_min
    planned_duration = max(1, int(math.ceil(needed))) if needed > 0 else 0
    machine = seg.machine_id
    effective_config = config or FactoryConfig()
    # This is a repair path, but it must obey the same material-release
    # floor as the primary dispatcher.  Without it, a zero-length segment
    # created by a later repair could be silently pulled before its five-day
    # availability window.
    lot = (lots_by_id or {}).get(seg.lot_id)
    first_allowed_day = max(0, earliest_allowed_start(lot, holidays)) if lot else 0
    for candidate_day in range(seg.edd, first_allowed_day - 1, -1):
        planning_checkpoint()
        if candidate_day in holidays or candidate_day == seg.day_idx:
            continue
        day_used = used.get((machine, candidate_day), 0)
        if day_cap - day_used < needed:
            continue
        # Find end of existing segments on this day
        existing_end = shift_a_start
        for other in all_segments:
            if other.machine_id == machine and other.day_idx == candidate_day:
                existing_end = max(existing_end, other.end_min)
        candidate_abs = float(
            candidate_day * day_cap
            + clock_to_productive_offset(effective_config, existing_end)
        )
        slot = _shift_slot_at_or_after(
            candidate_abs,
            planned_duration,
            effective_config,
            holidays,
        )
        if slot is None or slot[0] != candidate_day:
            continue
        _slot_day, slot_start, shift_id = slot
        # Tool contention: the same physical tool must not be on another
        # machine during the candidate slot.
        new_start_abs = float(
            candidate_day * day_cap
            + clock_to_productive_offset(effective_config, slot_start)
        )
        new_end_abs = new_start_abs + needed
        conflict = False
        for other in all_segments:
            if other is not seg and other.tool_id == seg.tool_id and other.machine_id != machine:
                o_start, o_end = segment_abs(other, config)
                if new_start_abs < o_end and o_start < new_end_abs:
                    conflict = True
                    break
        if conflict:
            continue
        old_day = seg.day_idx
        seg.day_idx = candidate_day
        seg.start_min = slot_start
        seg.end_min = slot_start + planned_duration
        seg.shift = shift_id
        used[(machine, candidate_day)] = day_used + needed
        old_key = (machine, old_day)
        if old_key in used:
            used[old_key] = max(0, used[old_key] - needed)
        logger.info(
            "Relocated truncated segment %s to day %d (was day %d, %s, crew overlap possible)",
            seg.lot_id,
            candidate_day,
            old_day,
            machine,
        )
        return True
    return False


def _sanitize_segments(
    segments: list[Segment],
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
    lots: list[Lot] | None = None,
) -> list[Segment]:
    """Enforce factory-day bounds without deleting physical work or output.

    This is a geometry repair only. It may move a malformed block and therefore
    expose real tardiness, but it never scales setup, production, quantity or
    twin output to make an invalid candidate appear feasible.
    """
    shift_a_start = config.shift_a_start if config else 420
    shift_b_end = config.shift_b_end if config else 1440
    day_cap = config.day_capacity_min if config else 1020
    effective_config = config or FactoryConfig()
    hols = holidays or set()
    lots_by_id = {lot.id: lot for lot in lots or []}

    # Pass 1: retain the complete physical duration while normalising starts.
    result: list[Segment] = []
    for seg in segments:
        if seg.start_min > seg.end_min:
            if seg.prod_min + seg.setup_min <= 0:
                continue
            seg.end_min = seg.start_min + int(math.ceil(seg.prod_min + seg.setup_min))
        duration = max(
            int(seg.end_min - seg.start_min),
            int(math.ceil(max(0.0, seg.prod_min + seg.setup_min))),
        )
        if seg.start_min < shift_a_start:
            seg.start_min = shift_a_start
            seg.end_min = shift_a_start + duration
        result.append(seg)

    # Pass 2: rematerialise malformed geometry without changing workload.
    used: dict[tuple[str, int], float] = {}
    for seg in result:
        key = (seg.machine_id, seg.day_idx)
        used[key] = used.get(key, 0.0) + max(0, seg.end_min - seg.start_min)

    final: list[Segment] = []
    for seg in result:
        actual_duration = seg.end_min - seg.start_min
        needed = seg.prod_min + seg.setup_min

        needs_reflow = (
            actual_duration < needed - 1.0
            or seg.start_min < shift_a_start
            or seg.start_min >= shift_b_end
            or seg.end_min > shift_b_end
            or not any(
                int(shift.start_min) <= int(seg.start_min)
                and int(seg.end_min) <= int(shift.end_min)
                for shift in effective_config.shifts
            )
        )
        if needs_reflow and needed > 0:
            if _try_relocate_truncated(
                seg,
                result,
                used,
                shift_a_start,
                day_cap,
                hols,
                lots_by_id,
                config,
            ):
                final.append(seg)
                continue
            planned_duration = max(1, int(math.ceil(needed)))
            target_abs = float(
                int(seg.day_idx) * day_cap
                + clock_to_productive_offset(effective_config, int(seg.start_min))
            )
            slot = _shift_slot_at_or_after(
                target_abs,
                planned_duration,
                effective_config,
                hols,
            )
            if slot is None:
                final.append(seg)
                continue
            target_day, target_start, shift_id = slot
            seg.day_idx = target_day
            seg.start_min = target_start
            seg.end_min = target_start + planned_duration
            seg.shift = shift_id

        final.append(seg)

    removed_total = len(segments) - len(final)
    if removed_total > 0:
        logger.info(
            "Sanitize: removed %d empty inverted segment(s)",
            removed_total,
        )
    return final


def _fix_orphan_continuations(
    segments: list[Segment], *, protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Reset is_continuation for segments that are the first of their lot.

    After _fix_day_overlaps and crew serialization, some segments may be
    incorrectly marked as continuations when they are actually the first
    (or only) segment of their lot.
    """
    by_lot: dict[str, list[Segment]] = defaultdict(list)
    for s in segments:
        by_lot[s.lot_id].append(s)

    fixed = 0
    for lot_id, segs in by_lot.items():
        if lot_id in (protected_lot_ids or ()):
            continue
        segs.sort(key=lambda s: (s.day_idx, s.start_min))
        if segs[0].is_continuation:
            segs[0].is_continuation = False
            fixed += 1

    if fixed > 0:
        logger.info("Fixed %d orphan continuations", fixed)

    return segments


def _remove_redundant_retained_tool_setups(
    segments: list[Segment],
    *,
    protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Remove a setup when the same tool is still mounted on the machine.

    Material-release splitting can create separate runs for the same physical
    tool. A new run is useful for sequencing, but it is not a physical tool
    change when no different tool ran on the machine and the mould did not move
    to another machine in between. Keep the allocated production window until
    resource-aware normalization can safely fill the released time.
    """

    by_machine_run: dict[tuple[str, str], list[Segment]] = defaultdict(list)
    for segment in segments:
        if segment.end_min > segment.start_min:
            by_machine_run[(segment.machine_id, segment.run_id)].append(segment)

    openings_by_machine: dict[str, list[Segment]] = defaultdict(list)
    for (machine_id, _run_id), run_segments in by_machine_run.items():
        productive = [segment for segment in run_segments if segment.prod_min > 0]
        if productive:
            openings_by_machine[machine_id].append(
                min(productive, key=lambda item: (item.day_idx, item.start_min))
            )

    removed = 0
    discarded: set[int] = set()
    protected = protected_lot_ids or set()
    for machine_id, openings in openings_by_machine.items():
        planning_checkpoint()
        openings.sort(key=lambda item: (item.day_idx, item.start_min, item.run_id))
        for opening in openings:
            if any(
                segment.lot_id in protected
                for segment in by_machine_run[(machine_id, opening.run_id)]
            ):
                continue
            run_segments = by_machine_run[(machine_id, opening.run_id)]
            prefix = [
                item for item in run_segments
                if item.setup_min > 0
                and (item.day_idx, item.start_min) <= (opening.day_idx, opening.start_min)
            ]
            if not prefix:
                continue
            identity = segment_setup_identity(opening)
            first = min(prefix, key=lambda item: (item.day_idx, item.start_min))
            if not all(segment_setup_identity(item) == identity for item in prefix):
                continue
            if not retained_setup_at(
                segments, machine_id, identity, first.day_idx,
                first.start_min, ignore_run_id=opening.run_id,
            ):
                continue
            for item in prefix:
                # Free physical preparation without shifting already allocated
                # production; normalization still checks the shared resources.
                item.start_min = min(
                    item.end_min, item.start_min + max(0, int(round(item.setup_min))),
                )
                item.setup_min = 0.0
                if item.prod_min <= 0 and item.qty == 0 and not any(
                    quantity for _op, _sku, quantity in item.twin_outputs or []
                ):
                    discarded.add(id(item))
            remaining_setup = sum(max(0.0, item.setup_min) for item in run_segments)
            for item in run_segments:
                item.run_setup_min = remaining_setup
            removed += 1

    if removed:
        logger.info("Removed %d redundant retained-tool setup(s)", removed)
        segments[:] = [item for item in segments if id(item) not in discarded]
    return segments


def _compact_segments(
    segments: list[Segment],
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
    lots: list[Lot] | None = None,
    data: EngineData | None = None,
) -> list[Segment]:
    """Opt-in compaction: pull whole lots earlier to close idle gaps on machines.

    Bug 3 mitigation: JIT + crew serialization + tool contention leave idle
    time between production blocks. This pass works lot-by-lot, per machine:
    each lot is treated as one contiguous block of work-minutes and slid to the
    earliest feasible absolute start, then re-flowed day-by-day so its segments
    are contiguous (no day-boundary holes).

    Hard constraints (all preserved — caller still wraps this in a tardy /
    contention safety-net revert):
      - never schedules production after the lot's EDD (only earlier or equal);
      - never overlaps two segments on the same machine (re-flow packs after
        the running machine cursor);
      - never exceeds shift bounds (start >= shift_a_start, end <= shift_b_end);
      - never exceeds DAY_CAP (a day holds at most shift_b_end-shift_a_start
        minutes by construction of the re-flow);
      - never creates a same-tool cross-machine overlap (every produced
        interval is checked against other-machine bookings of the same tool,
        same logic as ``_detect_tool_machine_overlaps``).

    Work-minutes, quantities, setup and twin outputs are NEVER changed — only
    day_idx / start_min / end_min / shift / is_continuation are rewritten.

    Mutates and returns ``segments``.
    """
    shift_a_start = config.shift_a_start if config else 420
    shift_b_end = config.shift_b_end if config else 1440
    day_cap = config.day_capacity_min if config else DAY_CAP
    hols = holidays or set()
    lots_by_id = {lot.id: lot for lot in lots or []}

    # Tool bookings from segments on OTHER machines (for cross-machine guard).
    # Built once; a lot only moves within its own machine so other-machine
    # segments are a fixed reference during this pass.
    by_machine: defaultdict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        by_machine[seg.machine_id].append(seg)

    def _tool_busy_other(
        tool_id: str, machine_id: str, start_abs: float, end_abs: float, own_lot: str
    ) -> bool:
        """True if `tool_id` is used on a different machine during [start, end)."""
        for other in segments:
            if other.lot_id == own_lot:
                continue
            if other.tool_id != tool_id or other.machine_id == machine_id:
                continue
            if other.end_min <= other.start_min:
                continue
            o_start, o_end = _seg_abs(other, config)
            if start_abs < o_end and o_start < end_abs:
                return True
        return False

    def _next_workday(d: int, machine_id: str, tool_id: str) -> int:
        while d in hols or (
            data is not None and _resource_day_blocked(data, machine_id, tool_id, d, hols)
        ):
            d += 1
        return d

    moved = 0
    for machine_id, m_segs in by_machine.items():
        planning_checkpoint()
        # Group this machine's segments into lots, ordered chronologically.
        lots: dict[str, list[Segment]] = defaultdict(list)
        for s in m_segs:
            lots[s.lot_id].append(s)
        lot_order = sorted(
            lots.keys(),
            key=lambda lid: min((s.day_idx, s.start_min) for s in lots[lid]),
        )

        # Machine occupancy cursor: earliest free absolute minute. Starts at
        # day 0 shift start; advances as each lot is placed.
        cursor_day = 0
        cursor_min = shift_a_start

        for lid in lot_order:
            planning_checkpoint()
            lot_segs = sorted(lots[lid], key=lambda s: (s.day_idx, s.start_min))
            work = [s.end_min - s.start_min for s in lot_segs]
            total_work = sum(w for w in work if w > 0)
            tool_id = lot_segs[0].tool_id
            edd = lot_segs[0].edd
            lot = lots_by_id.get(lid)
            first_allowed_day = (
                max(0, earliest_allowed_start(lot, hols)) if lot is not None else 0
            )

            if total_work <= 0:
                # Degenerate / placeholder-only lot — leave untouched but make
                # sure the cursor never rewinds before it.
                last = lot_segs[-1]
                if (last.day_idx, last.end_min) > (cursor_day, cursor_min):
                    cursor_day, cursor_min = last.day_idx, last.end_min
                continue

            # Re-flow the lot's TOTAL work as one continuous stream starting at
            # a trial (day, start). The stream is split into day-blocks packed
            # tightly within shift bounds. Returns the list of
            # (day, start, end) blocks or None if it cannot fit by EDD /
            # tool contention.
            def _try_flow(d0: int, s0: int):
                blocks: list[tuple[int, int, int]] = []
                d = _next_workday(max(d0, first_allowed_day), machine_id, tool_id)
                s = s0 if d == d0 else shift_a_start
                if s >= shift_b_end:
                    d = _next_workday(d + 1, machine_id, tool_id)
                    s = shift_a_start
                remaining = total_work
                while remaining > 0:
                    planning_checkpoint()
                    if d > edd:
                        return None  # would breach the deadline
                    avail = shift_b_end - s
                    block = min(remaining, avail)
                    seg_start_abs = d * day_cap + (s - shift_a_start)
                    seg_end_abs = seg_start_abs + block
                    if _tool_busy_other(tool_id, machine_id, seg_start_abs, seg_end_abs, lid):
                        return None  # same tool on another machine
                    blocks.append((d, s, s + block))
                    s += block
                    remaining -= block
                    if remaining > 0:
                        d = _next_workday(d + 1, machine_id, tool_id)
                        s = shift_a_start
                return blocks

            total_setup = sum(s.setup_min for s in lot_segs if s.end_min > s.start_min)
            current_pos = (lot_segs[0].day_idx, lot_segs[0].start_min)
            # Search the first actually feasible minute between the machine
            # cursor and the current position.  The old implementation tested
            # only the cursor and abandoned the move when a short tool/crew
            # conflict existed there, leaving hours or days of avoidable idle
            # time even when the resource became free moments later.
            trial_day = _next_workday(
                max(cursor_day, first_allowed_day), machine_id, tool_id
            )
            trial_min = cursor_min if trial_day == cursor_day else shift_a_start
            if trial_min < shift_a_start:
                trial_min = shift_a_start
            if trial_min >= shift_b_end:
                trial_day = _next_workday(trial_day + 1, machine_id, tool_id)
                trial_min = shift_a_start

            placements = None
            attempts = 0
            while (trial_day, trial_min) < current_pos and attempts < 100_000:
                planning_checkpoint()
                candidate = _try_flow(trial_day, trial_min)
                if candidate is not None:
                    setup_ok = True
                    if total_setup > 0:
                        first_day, first_start, _first_end = candidate[0]
                        setup_ok = _setup_capacity_ok_for_trial(
                            segments,
                            config or FactoryConfig(),
                            machine_id=machine_id,
                            day_idx=first_day,
                            start_min=first_start,
                            setup_min=total_setup,
                            ignored_lot_ids={lid},
                            data=data,
                        )
                    if setup_ok:
                        placements = candidate
                        break
                trial_min += 1
                if trial_min >= shift_b_end:
                    trial_day = _next_workday(trial_day + 1, machine_id, tool_id)
                    trial_min = shift_a_start
                attempts += 1

            if placements is None or (placements[0][0], placements[0][1]) >= current_pos:
                # Cannot improve — keep the lot where it is, advance cursor.
                last = lot_segs[-1]
                if (last.day_idx, last.end_min) > (cursor_day, cursor_min):
                    cursor_day, cursor_min = last.day_idx, last.end_min
                continue

            # Map the re-flowed day-blocks onto the existing Segment objects.
            # Production and quantity are split with the productive minutes,
            # while a setup is always attached to the first block it prepares.
            orig_work_segs = [s for s in lot_segs if s.end_min > s.start_min]
            tot_prod = sum(s.prod_min for s in orig_work_segs)
            tot_setup = sum(s.setup_min for s in orig_work_segs)
            tot_qty = sum(s.qty for s in orig_work_segs)
            twin_totals: dict[tuple[str, str], int] = {}
            for s in orig_work_segs:
                for oid, sku, q in s.twin_outputs or []:
                    twin_totals[(oid, sku)] = twin_totals.get((oid, sku), 0) + q

            template = orig_work_segs[0]
            new_segs: list[Segment] = []
            n_blocks = len(placements)
            prod_acc = 0.0
            setup_remaining = tot_setup
            qty_acc = 0
            twin_acc: dict[tuple[str, str], int] = {k: 0 for k in twin_totals}
            for k, (d, st, en) in enumerate(placements):
                dur = en - st
                last_block = k == n_blocks - 1
                setup_for_block = min(setup_remaining, dur)
                productive_duration = max(0.0, dur - setup_for_block)
                if last_block:
                    p_prod = tot_prod - prod_acc
                    p_setup = setup_remaining
                    p_qty = tot_qty - qty_acc
                else:
                    p_prod = min(tot_prod - prod_acc, productive_duration)
                    p_setup = setup_for_block
                    p_qty = round(tot_qty * (p_prod / tot_prod)) if tot_prod else 0
                prod_acc += p_prod
                setup_remaining -= p_setup
                qty_acc += p_qty
                twin_out: list[tuple[str, str, int]] | None = None
                if twin_totals:
                    twin_out = []
                    for (oid, sku), tq in twin_totals.items():
                        if last_block:
                            piece = tq - twin_acc[(oid, sku)]
                        else:
                            piece = round(tq * (p_prod / tot_prod)) if tot_prod else 0
                        twin_acc[(oid, sku)] += piece
                        twin_out.append((oid, sku, piece))
                ns = Segment(
                    lot_id=template.lot_id,
                    run_id=template.run_id,
                    machine_id=template.machine_id,
                    tool_id=template.tool_id,
                    day_idx=d,
                    start_min=st,
                    end_min=en,
                    shift="A" if st < 930 else "B",
                    qty=p_qty,
                    prod_min=p_prod,
                    setup_min=p_setup,
                    is_continuation=k > 0,
                    edd=template.edd,
                    sku=template.sku,
                    setup_family=template.setup_family,
                    twin_outputs=twin_out,
                    lot_qty=template.lot_qty,
                    run_qty=template.run_qty,
                    run_setup_min=template.run_setup_min,
                    run_lot_count=template.run_lot_count,
                    original_edd=template.original_edd,
                    internal_deadline=template.internal_deadline,
                    delivery_day=template.delivery_day,
                    customer_delivery_day=template.customer_delivery_day,
                    latest_subcontract_dispatch_day=template.latest_subcontract_dispatch_day,
                    subcontract_dispatch_day=template.subcontract_dispatch_day,
                    production_due_day=template.production_due_day,
                    internal_target_day=template.internal_target_day,
                    material_reference_day=template.material_reference_day,
                    material_reference_kind=template.material_reference_kind,
                    eco_lot_isop=template.eco_lot_isop,
                    eco_lot_effective=template.eco_lot_effective,
                    start_buffer_days=template.start_buffer_days,
                    finish_buffer_days=template.finish_buffer_days,
                    target_start_day=template.target_start_day,
                    min_campaign_qty=template.min_campaign_qty,
                    min_campaign_prod_min=template.min_campaign_prod_min,
                    max_group_gap_days=template.max_group_gap_days,
                    planning_priority=template.planning_priority,
                    material_release_day=template.material_release_day,
                    output_milestones=(
                        [dict(item) for item in template.output_milestones]
                        if template.output_milestones is not None
                        else None
                    ),
                    release_delay_workdays=template.release_delay_workdays,
                    planning_source=template.planning_source,
                    economic_warning=template.economic_warning,
                    is_subcontracted=template.is_subcontracted,
                    subcontract_company_id=template.subcontract_company_id,
                    subcontract_lead_time_days=template.subcontract_lead_time_days,
                    subcontract_buffer_days=template.subcontract_buffer_days,
                )
                new_segs.append(ns)

            # Replace this lot's segments in the master list.
            lot_id_set = lid
            segments[:] = [s for s in segments if s.lot_id != lot_id_set]
            segments.extend(new_segs)
            moved += 1

            # Advance machine cursor past this lot.
            last_d, _ls, last_e = placements[-1]
            cursor_day, cursor_min = last_d, last_e

    if moved > 0:
        logger.info("Compaction: pulled %d lots earlier to close gaps", moved)
    return segments


def _left_shift_lots_into_empty_workdays(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    holidays: set[int],
) -> list[Segment]:
    """Move a lot, or its first productive part, into an empty allowed day.

    The global re-flow pass intentionally preserves a machine's inherited
    sequence.  That is usually the right conservative choice, but it cannot
    fill an entirely empty day which sits before a later short lot.  This pass
    handles precisely that case. A short lot moves as a whole. A larger lot
    moves its first day of production together with its setup and leaves the
    remaining production in its already-reserved positions; it therefore never
    evicts another production block or creates a setup after production.
    """

    shift_a_start = config.shift_a_start
    shift_b_end = config.shift_b_end
    lots_by_id = {lot.id: lot for lot in lots}
    moved = 0

    def _first_free_interval_start(
        intervals: list[dict],
        day_idx: int,
        duration: float,
    ) -> int | None:
        """Return the first production-sized gap left by exact downtime slices."""

        cursor = shift_a_start
        required = int(math.ceil(duration))
        day_blocks = sorted(
            (
                (
                    max(shift_a_start, int(block.get("start_min", 0))),
                    min(shift_b_end, int(block.get("end_min", shift_b_end))),
                )
                for block in intervals
                if int(block.get("start_day", -1)) == day_idx
            ),
            key=lambda item: item[0],
        )
        for block_start, block_end in day_blocks:
            if block_end <= cursor:
                continue
            if block_start - cursor >= required:
                return cursor
            cursor = max(cursor, block_end)
        return cursor if shift_b_end - cursor >= required else None

    # Re-evaluate after every move: a newly occupied day must not become a
    # candidate for another lot in the same pass.
    first_by_lot: dict[str, tuple[int, int]] = {}
    for segment in segments:
        if segment.prod_min <= 0 or segment.end_min <= segment.start_min:
            continue
        current = first_by_lot.get(segment.lot_id)
        position = (segment.day_idx, segment.start_min)
        if current is None or position < current:
            first_by_lot[segment.lot_id] = position

    # A day that is fully empty is a scarce early slot.  Consider the lots in
    # the same operational order used by the global constructor, rather than
    # in the accidental order of their previous positions; otherwise a later
    # reference can occupy the slot before a rupture-priority lot is checked.
    for lot_id in sorted(
        first_by_lot,
        key=lambda item: (lot_priority_key(lots_by_id[item]), first_by_lot[item]),
    ):
        planning_checkpoint()
        lot = lots_by_id.get(lot_id)
        if lot is None:
            continue
        lot_segments = sorted(
            [segment for segment in segments if segment.lot_id == lot_id],
            key=lambda segment: (segment.day_idx, segment.start_min),
        )
        active = [segment for segment in lot_segments if segment.end_min > segment.start_min]
        if not active:
            continue
        first = min(
            (segment for segment in active if segment.prod_min > 0),
            key=lambda segment: (segment.day_idx, segment.start_min),
            default=None,
        )
        if first is None:
            continue
        total_work = sum(segment.end_min - segment.start_min for segment in active)
        if total_work <= 0:
            continue
        total_setup = sum(segment.setup_min for segment in active)
        day_capacity = shift_b_end - shift_a_start
        moved_work = min(total_work, day_capacity)

        floor = max(0, earliest_allowed_start(lot, holidays))
        candidate_day: int | None = None
        candidate_start: int | None = None
        for day_idx in range(floor, first.day_idx):
            planning_checkpoint()
            if not is_factory_workday(day_idx, data, config):
                continue
            if day_idx in data.machine_blocked_days.get(first.machine_id, set()):
                continue
            if day_idx in data.tool_blocked_days.get(first.tool_id, set()):
                continue
            if (
                available_machine_capacity(first.machine_id, day_idx, data, config)
                < moved_work
            ):
                continue
            if any(
                segment.machine_id == first.machine_id
                and segment.lot_id != lot_id
                and segment.day_idx == day_idx
                and segment.end_min > segment.start_min
                for segment in segments
            ):
                continue
            if any(
                segment.tool_id == first.tool_id
                and segment.machine_id != first.machine_id
                and segment.day_idx == day_idx
                and segment.end_min > segment.start_min
                for segment in segments
            ):
                continue
            start = _first_free_interval_start(
                data.machine_blocked_intervals.get(first.machine_id, [])
                + data.tool_blocked_intervals.get(first.tool_id, []),
                day_idx,
                moved_work,
            )
            if start is None:
                continue
            # A continuation may only move before another lot in the same
            # campaign if that campaign's setup is already complete. Moving a
            # later lot ahead of a setup would look compact but is physically
            # impossible (and was the source of detached-setup regressions).
            candidate_position = (day_idx, start)
            setup_positions = [
                (segment.day_idx, segment.start_min)
                for segment in segments
                if segment.run_id == first.run_id and segment.setup_min > 0
            ]
            if total_setup <= 0 and setup_positions and min(setup_positions) > candidate_position:
                continue
            if total_setup > 0 and not _setup_capacity_ok_for_trial(
                segments,
                config,
                machine_id=first.machine_id,
                day_idx=day_idx,
                start_min=start,
                setup_min=total_setup,
                ignored_lot_ids={lot_id},
                data=data,
            ):
                continue
            if _interrupts_higher_priority_campaign(
                segments,
                lots_by_id,
                lot,
                machine_id=first.machine_id,
                day_idx=day_idx,
                start_min=start,
                end_min=start + int(math.ceil(moved_work)),
            ):
                continue
            candidate_day = day_idx
            candidate_start = start
            break

        if candidate_day is None or candidate_start is None:
            continue

        template = active[0]
        total_prod = sum(segment.prod_min for segment in active)
        total_qty = sum(segment.qty for segment in active)
        twin_totals: dict[tuple[str, str], int] = defaultdict(int)
        for segment in active:
            for op_id, sku, qty in segment.twin_outputs or []:
                twin_totals[(op_id, sku)] += qty
        moved_prod = min(total_prod, max(0.0, moved_work - total_setup))
        if moved_prod <= 0:
            continue
        moved_qty = round(total_qty * moved_prod / total_prod) if total_prod else 0
        remaining_twin = dict(twin_totals)
        moved_twins: list[tuple[str, str, int]] = []
        for identity, qty in twin_totals.items():
            portion = round(qty * moved_prod / total_prod) if total_prod else 0
            remaining_twin[identity] -= portion
            moved_twins.append((*identity, portion))
        end_min = candidate_start + total_setup + moved_prod
        replacement = replace(
            template,
            day_idx=candidate_day,
            start_min=candidate_start,
            end_min=end_min,
            shift="A" if end_min <= config.shift_a_end else "B",
            qty=moved_qty,
            prod_min=moved_prod,
            setup_min=total_setup,
            is_continuation=False,
            twin_outputs=moved_twins or None,
        )

        remaining_prod = total_prod - moved_prod
        remaining_qty = total_qty - moved_qty
        remainder: list[Segment] = []
        for original in active:
            if remaining_prod <= 0:
                break
            available = original.end_min - original.start_min
            prod_piece = min(remaining_prod, available)
            is_last_piece = remaining_prod - prod_piece <= 0.01
            if is_last_piece:
                qty_piece = remaining_qty
            else:
                qty_piece = round(remaining_qty * prod_piece / remaining_prod)
            twin_piece: list[tuple[str, str, int]] = []
            for identity, qty in tuple(remaining_twin.items()):
                if is_last_piece:
                    piece = qty
                else:
                    piece = round(qty * prod_piece / remaining_prod)
                remaining_twin[identity] -= piece
                twin_piece.append((*identity, piece))
            remainder.append(
                replace(
                    original,
                    end_min=original.start_min + int(round(prod_piece)),
                    qty=qty_piece,
                    prod_min=prod_piece,
                    setup_min=0.0,
                    is_continuation=True,
                    twin_outputs=twin_piece or None,
                )
            )
            remaining_prod -= prod_piece
            remaining_qty -= qty_piece
        if remaining_prod > 0.01:
            continue
        segments[:] = [segment for segment in segments if segment.lot_id != lot_id]
        segments.append(replacement)
        segments.extend(remainder)
        moved += 1

    if moved:
        logger.info("Left shift: moved %d short lot(s) into empty workdays", moved)
    return segments


def _seg_abs(
    seg: Segment,
    config: FactoryConfig | None = None,
) -> tuple[float, float]:
    """Return (start_abs, end_abs) of a segment in absolute scheduling minutes."""
    return segment_abs(seg, config)


def _parallelize_independent_setup_starts(
    segments: list[Segment],
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
) -> list[Segment]:
    """Pull setup-starting runs into idle gaps on their own machine.

    This is deliberately narrower than the optional full compactor: it only
    shifts a whole run earlier within the same day when the machine has idle
    time immediately before the setup. Same-group setup capacity and physical
    tool availability are checked before the move is accepted.
    """
    shift_a_start = config.shift_a_start if config else 420
    shift_b_end = config.shift_b_end if config else 1440
    hols = holidays or set()
    by_run: dict[str, list[Segment]] = defaultdict(list)
    by_machine_day: dict[tuple[str, int], list[Segment]] = defaultdict(list)
    for segment in segments:
        by_run[segment.run_id].append(segment)
        by_machine_day[(segment.machine_id, segment.day_idx)].append(segment)

    def _setup_capacity_ok(group: str, day_idx: int) -> bool:
        capacity = _setup_group_capacity(config, group)
        events: list[tuple[float, int]] = []
        for segment in segments:
            if segment.day_idx != day_idx or segment.setup_min <= 0:
                continue
            if _setup_group(segment, config) != group:
                continue
            events.extend(
                [
                    (float(segment.start_min), 1),
                    (float(segment.start_min + segment.setup_min), -1),
                ]
            )
        active = 0
        for _minute, delta in sorted(events, key=lambda item: (item[0], item[1])):
            active += delta
            if active > capacity:
                return False
        return True

    def _setup_candidate_starts(
        group: str,
        day_idx: int,
        earliest: int,
        latest: int,
    ) -> list[int]:
        candidates = {earliest}
        for segment in segments:
            if segment.day_idx != day_idx or segment.setup_min <= 0:
                continue
            if _setup_group(segment, config) != group:
                continue
            setup_end = math.ceil(segment.production_start_min)
            if earliest < setup_end < latest:
                candidates.add(setup_end)
        return sorted(candidates)

    def _would_conflict_with_tool_after_shift(
        run_segments: list[Segment],
        delta: int,
    ) -> bool:
        """Keep a shared mould from being pulled onto another machine's run."""

        shifted_ids = {id(segment) for segment in run_segments}
        for segment in run_segments:
            new_start = segment.start_min - delta
            new_end = segment.end_min - delta
            for other in segments:
                if id(other) in shifted_ids or other.day_idx != segment.day_idx:
                    continue
                if (
                    other.tool_id == segment.tool_id
                    and other.machine_id != segment.machine_id
                    and new_start < other.end_min
                    and other.start_min < new_end
                ):
                    return True
        return False

    moved = 0
    setup_runs = sorted(
        (
            min(run_segments, key=lambda item: (item.day_idx, item.start_min))
            for run_segments in by_run.values()
        ),
        key=lambda item: (item.day_idx, item.start_min, item.machine_id),
    )
    for first in setup_runs:
        planning_checkpoint()
        if first.setup_min <= 0 or first.day_idx in hols:
            continue
        run_segments = sorted(
            (
                segment
                for segment in by_run[first.run_id]
                if segment.day_idx == first.day_idx and segment.start_min >= first.start_min
            ),
            key=lambda item: (item.start_min, item.end_min),
        )
        if not run_segments:
            continue

        previous_end = shift_a_start
        for other in by_machine_day[(first.machine_id, first.day_idx)]:
            if other.run_id == first.run_id:
                continue
            if other.end_min <= first.start_min:
                previous_end = max(previous_end, other.end_min)
        earliest_start = max(shift_a_start, previous_end)
        if first.start_min - earliest_start <= 0:
            continue
        group = _setup_group(first, config)
        for target_start in _setup_candidate_starts(
            group,
            first.day_idx,
            earliest_start,
            int(first.start_min),
        ):
            delta = first.start_min - target_start
            if delta <= 0:
                continue
            if any(segment.start_min - delta < shift_a_start for segment in run_segments):
                continue
            if any(segment.end_min - delta > shift_b_end for segment in run_segments):
                continue
            if _would_conflict_with_tool_after_shift(run_segments, delta):
                continue
            for segment in run_segments:
                segment.start_min -= delta
                segment.end_min -= delta
            if _setup_capacity_ok(group, first.day_idx) and not _detect_tool_machine_overlaps(
                segments, config
            ):
                moved += 1
                break
            for segment in run_segments:
                segment.start_min += delta
                segment.end_min += delta

    if moved > 0:
        logger.info("Setup parallelization: pulled %d setup run(s) earlier", moved)
    return segments


def _accept_setup_parallelization(
    before: dict,
    after: dict,
    *,
    before_tool_conflicts: int,
    after_tool_conflicts: int,
) -> bool:
    """Accept an earlier legal setup without sacrificing a hard constraint.

    Material release is enforced separately by the JIT window gate. Once a
    run is inside that legal window, advancing it into idle capacity is the
    intended operational behaviour. ``latest_start_gap`` measures how close a
    lot is to its last permissible start, so it naturally grows when a setup
    and its production are pulled earlier; it must not veto this improvement.
    """

    return bool(
        delivery_not_worse(after, before)
        and after.get("hard_violations", 0) <= before.get("hard_violations", 0)
        and after.get("early_window_violations", 0)
        <= before.get("early_window_violations", 0)
        and after.get("operator_capacity_violations", 0)
        <= before.get("operator_capacity_violations", 0)
        and after_tool_conflicts <= before_tool_conflicts
    )


def _repair_zero_slack_lots_into_previous_gaps(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    holidays: set[int] | None = None,
) -> list[Segment]:
    """Move complete single-block lots into obvious earlier machine gaps.

    The global solver and compactor can leave a short, complete lot behind a
    removable same-machine gap after shared-resource repairs. This bounded
    post-pass moves only work that fits in full, so it never fragments a
    campaign or creates an extra setup merely to claim an earlier start.
    """

    lots_by_id = {lot.id: lot for lot in lots}
    holiday_set = holidays or calendar_holidays(data, -7, data.n_days + 7)
    current = segments
    moved = 0

    for lot_id in _complete_lot_gap_candidates(current, lots, config, holiday_set):
        planning_checkpoint()
        lot = lots_by_id.get(lot_id)
        if lot is None:
            continue
        trial = _try_pull_lot_to_previous_gap(
            current,
            lot,
            data,
            config,
            holiday_set,
            lots_by_id,
        )
        if trial is None:
            continue

        pre_score = compute_score(
            current,
            lots,
            data,
            config=config,
            include_operational_audit=False,
        )
        trial = _merge_detached_setup_segments(
            trial,
            config,
            lots,
            holiday_set,
            data=data,
        )
        trial = _fix_orphan_continuations(trial)
        try:
            assert_plan_valid(trial, data, config, lots=lots)
        except Exception:
            continue
        trial_score = compute_score(
            trial,
            lots,
            data,
            config=config,
            include_operational_audit=False,
        )
        if _accept_zero_slack_repair(pre_score, trial_score):
            current = trial
            moved += 1

    if moved:
        logger.info("Complete-lot repair: pulled %d lot(s) into earlier gaps", moved)
    return current


def _pull_internal_continuations_into_idle_gaps(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    holidays: set[int],
) -> list[Segment]:
    """Close an unexplained gap inside one uninterrupted tool campaign.

    This deliberately does not reorder other work. Productive prefixes may be
    split from a longer continuation, allowing a short legal gap to be used
    without changing the machine assignment, setup count or delivered output.
    """

    current = segments
    moved = 0
    max_moves = max(1, len(segments) * 2)
    for _sweep in range(max_moves):
        planning_checkpoint()
        opportunities = find_internal_continuation_opportunities(
            current,
            lots,
            data,
            config,
        )
        if not opportunities:
            break

        accepted = False
        before_score = compute_score(
            current,
            lots,
            data,
            config=config,
            include_operational_audit=False,
        )
        for opportunity in opportunities:
            trial = apply_partial_gap_move(current, opportunity, config, data)
            if _segment_schedule_signature(trial) == _segment_schedule_signature(current):
                continue
            try:
                assert_plan_valid(trial, data, config, lots=lots)
            except PlanValidationError:
                continue
            after_score = compute_score(
                trial,
                lots,
                data,
                config=config,
                include_operational_audit=False,
            )
            if not _accept_zero_slack_repair(before_score, after_score):
                continue
            current = trial
            moved += 1
            accepted = True
            break
        if not accepted:
            break

    if moved:
        logger.info("Continuation repair: applied %d partial/complete move(s)", moved)
    return current


def _pull_following_run_lots_into_idle_gaps(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    holidays: set[int],
) -> list[Segment]:
    """Compatibility wrapper for the canonical partial-gap normalizer."""

    return _pull_internal_continuations_into_idle_gaps(
        segments,
        lots,
        data,
        config,
        holidays,
    )


def _start_production_at_open_after_parked_setup(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Start production at opening after a setup parked at the prior close."""

    current = segments
    protected = planning_protected_lot_ids(data, protected_lot_ids)
    lots_by_id = {lot.id: lot for lot in lots}
    for setup in sorted(
        (
            segment
            for segment in current
            if segment.setup_min > 0
            and segment.prod_min <= 0
            and segment.qty <= 0
            and segment.end_min == config.shift_b_end
        ),
        key=lambda item: (item.day_idx, item.start_min),
    ):
        planning_checkpoint()
        first_prod = min(
            (
                segment
                for segment in current
                if segment.run_id == setup.run_id
                and segment.machine_id == setup.machine_id
                and segment.tool_id == setup.tool_id
                and segment.prod_min > 0
                and (segment.day_idx, segment.start_min)
                > (setup.day_idx, setup.end_min)
            ),
            key=lambda item: (item.day_idx, item.start_min),
            default=None,
        )
        if (first_prod is None or first_prod.lot_id in protected
                or first_prod.start_min <= config.shift_a_start):
            continue
        previous_workday = first_prod.day_idx - 1
        while previous_workday > setup.day_idx and not is_factory_workday(
            previous_workday, data, config
        ):
            planning_checkpoint()
            previous_workday -= 1
        if previous_workday != setup.day_idx:
            continue

        duration = int(first_prod.end_min - first_prod.start_min)
        if duration <= 0 or config.shift_a_start + duration > config.shift_b_end:
            continue
        lot = lots_by_id.get(first_prod.lot_id)
        if lot is not None and _interrupts_higher_priority_campaign(
            current,
            lots_by_id,
            lot,
            machine_id=first_prod.machine_id,
            day_idx=first_prod.day_idx,
            start_min=config.shift_a_start,
            end_min=config.shift_a_start + duration,
        ):
            continue
        trial = [replace(segment) for segment in current]
        trial_prod = next(
            segment
            for segment in trial
            if segment.lot_id == first_prod.lot_id
            and segment.run_id == first_prod.run_id
            and segment.day_idx == first_prod.day_idx
            and segment.start_min == first_prod.start_min
            and segment.end_min == first_prod.end_min
        )
        trial_prod.start_min = config.shift_a_start
        trial_prod.end_min = config.shift_a_start + duration
        trial_prod.shift = _shift_for_start(config, config.shift_a_start)

        before_score = compute_score(
            current,
            lots,
            data,
            config=config,
            include_operational_audit=False,
        )
        try:
            assert_plan_valid(trial, data, config, lots=lots)
        except PlanValidationError:
            continue
        after_score = compute_score(
            trial,
            lots,
            data,
            config=config,
            include_operational_audit=False,
        )
        if _accept_zero_slack_repair(before_score, after_score):
            current = sorted(
                trial,
                key=lambda item: (item.day_idx, item.start_min, item.machine_id),
            )
    return current


def _stabilize_earliest_legal_starts(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    holidays: set[int],
    *,
    max_passes: int = 32,
    protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Reach one deterministic fixed point for priority, setup and idle gaps."""

    protected = planning_protected_lot_ids(data, protected_lot_ids)
    current = sorted(
        [replace(segment) for segment in segments],
        key=lambda item: (item.day_idx, item.start_min, item.machine_id),
    )
    # A partial move can expose the next few minutes of a long continuation.
    # The bound therefore scales with the plan, while every accepted move has
    # a strictly decreasing temporal cost and cannot oscillate.
    max_gap_moves = max(max_passes, min(1024, len(current) * 2))
    seen = set()
    for _pass in range(max_passes):
        planning_checkpoint()
        before_signature = _segment_schedule_signature(current)
        if before_signature in seen:
            break
        seen.add(before_signature)
        current = repair_same_reference_interruptions(
            current, lots, data, config, protected_lot_ids=protected,
        )
        planning_checkpoint()
        current = _repair_interrupted_tool_campaigns(
            current,
            lots,
            data,
            config,
            protected_lot_ids=protected,
        )
        current = repair_priority_inversions(
            current,
            lots,
            data,
            config,
            protected_lot_ids=protected,
        )
        planning_checkpoint()
        current = _merge_detached_setup_segments(
            current,
            config,
            lots,
            holidays,
            data=data,
            protected_lot_ids=protected,
        )
        current = _start_production_at_open_after_parked_setup(
            current,
            lots,
            data,
            config,
            protected_lot_ids=protected,
        )
        current = _fix_orphan_continuations(current, protected_lot_ids=protected)
        current = _fill_legal_gaps_to_fixed_point(
            current,
            lots,
            data,
            config,
            max_moves=max_gap_moves,
            protected_lot_ids=protected,
        )
        current = _merge_detached_setup_segments(
            current, config, lots, holidays, data=data, protected_lot_ids=protected,
        )
        current = _fix_orphan_continuations(current, protected_lot_ids=protected)
        current = split_production_at_shift_boundaries(
            current, config, data, lots, protected_lot_ids=protected,
        )
        _remove_redundant_retained_tool_setups(
            current,
            protected_lot_ids=protected,
        )
        if _segment_schedule_signature(current) == before_signature:
            break
    return current


def _fill_legal_gaps_to_fixed_point(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    max_moves: int,
    protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Apply canonical legal partial moves in validated deterministic sweeps."""

    current = sorted(
        [replace(segment) for segment in segments],
        key=lambda item: (item.day_idx, item.start_min, item.machine_id),
    )
    priority = {lot.id: lot_priority_key(lot) for lot in lots}
    moved = 0
    while moved < max_moves:
        planning_checkpoint()
        opportunities = sorted(
            (
                item for item in actionable_gap_opportunities(current, lots, data, config)
                if item.lot_id not in (protected_lot_ids or ())
            ),
            key=lambda item: (
                priority.get(item.lot_id, ()),
                item.gap_day,
                item.gap_start_min,
                item.source_day,
                item.source_start_min,
                item.machine_id,
                item.lot_id,
            ),
        )
        planning_checkpoint()
        if not opportunities:
            break

        before_score = compute_score(
            current,
            lots,
            data,
            config=config,
            include_operational_audit=False,
        )
        current, accepted, _after_score = _apply_gap_move_batch(
            current,
            opportunities[: max_moves - moved],
            lots,
            data,
            config,
            before_score,
            protected_lot_ids=protected_lot_ids,
        )
        if accepted == 0:
            break
        moved += accepted

    if moved:
        logger.info("Canonical gap normalization: applied %d move(s)", moved)
    return current


def _apply_gap_move_batch(
    current: list[Segment],
    opportunities: list,
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    before_score: dict,
    *,
    protected_lot_ids: set[str] | None = None,
) -> tuple[list[Segment], int, dict]:
    """Validate independent left shifts in batches, splitting only on conflict."""

    if not opportunities:
        return current, 0, before_score

    trial = current
    accepted_candidates = 0
    signature = _segment_schedule_signature(current)
    for opportunity in opportunities:
        planning_checkpoint()
        candidate = apply_partial_gap_move(
            trial, opportunity, config, data, protected_lot_ids=protected_lot_ids,
        )
        candidate_signature = _segment_schedule_signature(candidate)
        if candidate_signature == signature:
            continue
        trial = candidate
        signature = candidate_signature
        accepted_candidates += 1

    if accepted_candidates == 0:
        return current, 0, before_score

    try:
        assert_plan_valid(trial, data, config, lots=lots)
    except PlanValidationError:
        valid = False
    else:
        after_score = compute_score(
            trial,
            lots,
            data,
            config=config,
            include_operational_audit=False,
        )
        valid = _accept_zero_slack_repair(before_score, after_score)
        if valid:
            return (
                sorted(
                    trial,
                    key=lambda item: (item.day_idx, item.start_min, item.machine_id),
                ),
                accepted_candidates,
                after_score,
            )

    if len(opportunities) == 1:
        return current, 0, before_score

    midpoint = len(opportunities) // 2
    left, left_count, left_score = _apply_gap_move_batch(
        current,
        opportunities[:midpoint],
        lots,
        data,
        config,
        before_score,
        protected_lot_ids=protected_lot_ids,
    )
    right, right_count, right_score = _apply_gap_move_batch(
        left,
        opportunities[midpoint:],
        lots,
        data,
        config,
        left_score,
        protected_lot_ids=protected_lot_ids,
    )
    return right, left_count + right_count, right_score


def _repair_interrupted_tool_campaigns(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Keep a returning tool campaign ahead of less urgent intervening work.

    A solver run may retain one setup identifier even after another tool has
    physically occupied the machine.  The setup can no longer cover the
    returning production.  When the returning lot is at least as urgent, this
    repair rotates its next productive piece in front of the intervening work;
    all durations and outputs stay untouched.  Cases that cannot be rotated
    remain hard validation failures instead of being silently accepted.
    """

    protected = planning_protected_lot_ids(data, protected_lot_ids)
    current = sorted(
        [replace(segment) for segment in segments],
        key=lambda item: (item.day_idx, item.start_min, item.machine_id),
    )
    lots_by_id = {lot.id: lot for lot in lots}
    max_moves = max(1, len(current) * 2)
    repaired = 0

    for _move in range(max_moves):
        planning_checkpoint()
        before_violations = validate_plan(current, data, config, lots=lots)
        before_metrics = hard_gate_metrics(before_violations)
        before_missing = before_metrics["missing_tool_change_setup_violations"]
        if before_missing <= 0:
            break
        before_score = compute_score(
            current,
            lots,
            data,
            config=config,
            include_operational_audit=False,
        )
        accepted = False

        machine_indexes: dict[str, list[int]] = defaultdict(list)
        for index, segment in enumerate(current):
            if segment.end_min > segment.start_min:
                machine_indexes[segment.machine_id].append(index)

        candidates: list[tuple[tuple, str, list[int], int, list[int]]] = []
        for machine_id, indexes in machine_indexes.items():
            planning_checkpoint()
            indexes.sort(key=lambda index: segment_abs(current[index], config)[0])
            for position in range(1, len(indexes)):
                planning_checkpoint()
                source_index = indexes[position]
                source = current[source_index]
                previous = current[indexes[position - 1]]
                source_lot = lots_by_id.get(source.lot_id)
                if (
                    source.prod_min <= 0
                    or source.setup_min > 0
                    or source_lot is None
                    or segment_setup_identity(source) == segment_setup_identity(previous)
                    or required_setup_minutes(source, lots_by_id) <= 0
                ):
                    continue

                prior_position = next(
                    (
                        prior
                        for prior in range(position - 1, -1, -1)
                        if current[indexes[prior]].tool_id == source.tool_id
                        and current[indexes[prior]].run_id == source.run_id
                    ),
                    None,
                )
                if prior_position is None:
                    continue
                prior = current[indexes[prior_position]]
                blockers: list[int] = []
                blocker_cursor = int(prior.end_min)
                for between_position in range(prior_position + 1, position):
                    between_index = indexes[between_position]
                    between = current[between_index]
                    if between.day_idx != prior.day_idx:
                        break
                    if int(between.start_min) != blocker_cursor:
                        break
                    blockers.append(between_index)
                    blocker_cursor = int(between.end_min)
                if not blockers:
                    continue

                source_indexes = [source_index]
                source_cursor = segment_abs(source, config)[1]
                for following_position in range(position + 1, len(indexes)):
                    following_index = indexes[following_position]
                    following = current[following_index]
                    following_start = segment_abs(following, config)[0]
                    if (
                        following.run_id != source.run_id
                        or following.tool_id != source.tool_id
                        or abs(following_start - source_cursor) > 0.01
                    ):
                        break
                    source_indexes.append(following_index)
                    source_cursor = segment_abs(following, config)[1]

                blocking_lots = [
                    lots_by_id.get(current[index].lot_id)
                    for index in blockers
                    if current[index].prod_min > 0
                ]
                if (
                    not blocking_lots
                    or any(lot is None for lot in blocking_lots)
                    or min(
                        lot_priority_key(lots_by_id[current[index].lot_id])
                        for index in source_indexes
                        if current[index].lot_id in lots_by_id
                    )
                    > min(
                        lot_priority_key(lot)
                        for lot in blocking_lots
                        if lot is not None
                    )
                ):
                    continue
                campaign_priority = min(
                    lot_priority_key(lots_by_id[current[index].lot_id])
                    for index in source_indexes
                    if current[index].lot_id in lots_by_id
                )
                candidates.append(
                    (
                        campaign_priority,
                        machine_id,
                        source_indexes,
                        indexes[prior_position],
                        blockers,
                    )
                )

        for _priority, _machine_id, source_indexes, prior_index, blockers in sorted(
            candidates,
            key=lambda item: (
                item[0],
                current[item[2][0]].day_idx,
                current[item[2][0]].start_min,
                item[1],
                current[item[2][0]].lot_id,
            ),
        ):
            source_index = source_indexes[0]
            source = current[source_index]
            prior = current[prior_index]
            if any(current[index].lot_id in protected for index in [*source_indexes, *blockers]):
                continue
            if any(
                current[index].end_min <= current[index].start_min
                for index in source_indexes
            ):
                continue

            trial = [replace(segment) for segment in current]
            cursor = int(prior.end_min)
            move_order = [*source_indexes, *blockers]
            interval_valid = True
            for index in move_order:
                segment = trial[index]
                duration = int(segment.end_min - segment.start_min)
                new_start = cursor
                new_end = cursor + duration
                shift = next(
                    (
                        configured.id
                        for configured in config.shifts
                        if int(configured.start_min) <= new_start
                        and new_end <= int(configured.end_min)
                    ),
                    None,
                )
                if shift is None:
                    interval_valid = False
                    break
                if index in source_indexes:
                    segment.day_idx = prior.day_idx
                segment.start_min = new_start
                segment.end_min = new_end
                segment.shift = shift
                cursor = new_end
            if not interval_valid or (
                trial[source_index].day_idx,
                trial[source_index].start_min,
            ) >= (source.day_idx, source.start_min):
                continue

            after_violations = validate_plan(trial, data, config, lots=lots)
            after_metrics = hard_gate_metrics(after_violations)
            if (
                after_metrics["missing_tool_change_setup_violations"]
                >= before_missing
            ):
                continue
            if any(
                after_metrics[key] > before_metrics[key]
                for key in before_metrics
                if key != "missing_tool_change_setup_violations"
            ):
                continue

            after_score = compute_score(
                trial,
                lots,
                data,
                config=config,
                include_operational_audit=False,
            )
            if (
                not delivery_not_worse(after_score, before_score)
                or after_score.get("early_window_violations", 0)
                > before_score.get("early_window_violations", 0)
                or after_score.get("missing_qty", 0) != before_score.get("missing_qty", 0)
                or after_score.get("overproduced_qty", 0)
                != before_score.get("overproduced_qty", 0)
                or after_score.get("duplicate_twin_output_qty", 0)
                != before_score.get("duplicate_twin_output_qty", 0)
                or after_score.get("twin_output_mismatches", 0)
                != before_score.get("twin_output_mismatches", 0)
                or after_score.get("setups", 0) != before_score.get("setups", 0)
                or after_score.get("setup_time_min", 0)
                != before_score.get("setup_time_min", 0)
            ):
                continue

            current = sorted(
                trial,
                key=lambda item: (item.day_idx, item.start_min, item.machine_id),
            )
            repaired += 1
            accepted = True
            break

        if not accepted:
            break

    if repaired:
        logger.info(
            "Interrupted-tool repair: restored %d campaign transition(s)",
            repaired,
        )
    return current


def _pull_complete_opening_segments_into_gaps(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    holidays: set[int],
) -> list[Segment]:
    """Compatibility entry point for the canonical partial opening repair."""

    del holidays
    current = segments
    moved = 0
    max_moves = max(1, len(segments) * 2)
    for _move in range(max_moves):
        planning_checkpoint()
        opportunities = find_opening_gap_opportunities(
            current,
            lots,
            data,
            config,
        )
        if not opportunities:
            break

        accepted = False
        before_score = compute_score(
            current,
            lots,
            data,
            config=config,
            include_operational_audit=False,
        )
        for opportunity in opportunities:
            trial = apply_partial_gap_move(current, opportunity, config, data)
            if _segment_schedule_signature(trial) == _segment_schedule_signature(current):
                continue
            try:
                assert_plan_valid(trial, data, config, lots=lots)
            except PlanValidationError:
                continue
            after_score = compute_score(
                trial,
                lots,
                data,
                config=config,
                include_operational_audit=False,
            )
            if not _accept_zero_slack_repair(before_score, after_score):
                continue
            current = sorted(
                trial,
                key=lambda item: (item.day_idx, item.start_min, item.machine_id),
            )
            moved += 1
            accepted = True
            break
        if not accepted:
            break

    if moved:
        logger.info("Opening-block repair: pulled %d partial/complete block(s) earlier", moved)
    return current


def _complete_lot_gap_candidates(
    segments: list[Segment],
    lots: list[Lot],
    config: FactoryConfig,
    holidays: set[int],
) -> list[str]:
    by_lot: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        if segment.prod_min > 0:
            by_lot[segment.lot_id].append(segment)

    rows: list[tuple[tuple, tuple[int, int], str]] = []
    for lot in lots:
        lot_segments = sorted(
            by_lot.get(lot.id, []),
            key=lambda item: (item.day_idx, item.start_min),
        )
        if len(lot_segments) != 1:
            continue
        segment = lot_segments[0]
        floor = max(0, earliest_allowed_start(lot, holidays))
        if (segment.day_idx, segment.start_min) <= (floor, config.shift_a_start):
            continue
        rows.append((lot_priority_key(lot), (segment.day_idx, segment.start_min), lot.id))
    return [lot_id for _priority, _position, lot_id in sorted(rows)]


def _interrupts_higher_priority_campaign(
    segments: list[Segment],
    lots_by_id: dict[str, Lot],
    moving_lot: Lot,
    *,
    machine_id: str,
    day_idx: int,
    start_min: int,
    end_min: int,
) -> bool:
    """Whether a move would insert less urgent work inside an open lot.

    Gap-closing is allowed to use genuinely idle capacity, but it must not turn
    the interval between two parts of an already-started, more urgent lot into
    capacity for a later requirement. Doing so fragments the urgent campaign
    and is the source of the visually unexplained priority inversions that the
    global solver itself did not create.
    """

    moving_priority = lot_priority_key(moving_lot)[:-1]
    target_start = day_idx * 1440 + start_min
    target_end = day_idx * 1440 + end_min
    by_lot: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        if (
            segment.machine_id == machine_id
            and segment.lot_id != moving_lot.id
            and segment.prod_min > 0
            and segment.end_min > segment.start_min
        ):
            by_lot[segment.lot_id].append(segment)

    for lot_id, productive in by_lot.items():
        protected_lot = lots_by_id.get(lot_id)
        if protected_lot is None:
            continue
        if lot_priority_key(protected_lot)[:-1] >= moving_priority:
            continue
        ordered = sorted(productive, key=lambda item: (item.day_idx, item.start_min))
        for previous, following in zip(ordered, ordered[1:]):
            previous_end = previous.day_idx * 1440 + int(previous.end_min)
            following_start = following.day_idx * 1440 + int(following.start_min)
            if previous_end <= target_start and target_end <= following_start:
                return True
    return False


def _try_pull_lot_to_previous_gap(
    segments: list[Segment],
    lot: Lot,
    data: EngineData,
    config: FactoryConfig,
    holidays: set[int],
    lots_by_id: dict[str, Lot],
) -> list[Segment] | None:
    source_segments = sorted(
        (segment for segment in segments if segment.lot_id == lot.id),
        key=lambda item: (item.day_idx, item.start_min),
    )
    if len(source_segments) != 1:
        return None
    source = source_segments[0]
    setup_min = max(
        float(source.setup_min or 0.0),
        float(source.run_setup_min or 0.0),
        float(lot.setup_min or 0.0),
    )
    duration = int(math.ceil(setup_min + float(lot.prod_min)))
    if duration <= 0:
        return None

    floor_day = max(0, earliest_allowed_start(lot, holidays))
    for target_day in range(floor_day, source.day_idx + 1):
        planning_checkpoint()
        if _resource_day_blocked(data, source.machine_id, source.tool_id, target_day, holidays):
            continue
        for gap_start, gap_end in _same_machine_tool_free_gaps(
            segments,
            source,
            machine_id=source.machine_id,
            tool_id=source.tool_id,
            day_idx=target_day,
            config=config,
        ):
            if gap_end - gap_start < duration:
                continue
            latest_start = gap_end - duration
            if target_day == source.day_idx:
                latest_start = min(latest_start, source.start_min - 1)
            for target_start in _setup_aware_candidate_starts(
                segments,
                config,
                machine_id=source.machine_id,
                day_idx=target_day,
                earliest=gap_start,
                latest=latest_start,
                setup_min=setup_min,
                ignored_lot_ids={lot.id},
                data=data,
            ):
                if (target_day, target_start) >= (source.day_idx, source.start_min):
                    continue
                if _interrupts_higher_priority_campaign(
                    segments,
                    lots_by_id,
                    lot,
                    machine_id=source.machine_id,
                    day_idx=target_day,
                    start_min=target_start,
                    end_min=target_start + duration,
                ):
                    continue
                if _exact_resource_interval_blocked(
                    data,
                    source.machine_id,
                    source.tool_id,
                    target_day,
                    target_start,
                    target_start + duration,
                    config,
                ):
                    continue
                trial = [
                    replace(segment)
                    for segment in segments
                    if segment.lot_id != lot.id
                ]
                moved = _rematerialize_single_segment_lot(
                    source,
                    lot,
                    target_day,
                    target_start,
                    setup_min,
                    config,
                )
                trial.append(moved)
                try:
                    _repair_remaining_run_setup(trial, source.run_id, setup_min, config)
                    _repair_stale_mounted_setups(trial, moved, config)
                except ValueError:
                    continue
                return sorted(
                    trial,
                    key=lambda item: (item.day_idx, item.start_min, item.machine_id),
                )
    return None


def _exact_resource_interval_blocked(
    data: EngineData,
    machine_id: str,
    tool_id: str,
    day_idx: int,
    start_min: int,
    end_min: int,
    config: FactoryConfig | None = None,
) -> bool:
    """Whether exact machine/tool downtime intersects a candidate interval."""
    from backend.transform.calendars import calendar_window

    data = calendar_window(data, config, day_idx, from_day=day_idx)

    for block in (
        data.machine_blocked_intervals.get(machine_id, [])
        + data.tool_blocked_intervals.get(tool_id, [])
    ):
        block_day = int(block.get("start_day", -1))
        if block_day != day_idx:
            continue
        block_start = int(block.get("start_min", 0))
        block_end = int(block.get("end_min", 1440))
        if start_min < block_end and block_start < end_min:
            return True
    return False


def _resource_day_blocked(
    data: EngineData,
    machine_id: str,
    tool_id: str,
    day_idx: int,
    holidays: set[int],
) -> bool:
    return (
        day_idx in holidays
        or day_idx in data.machine_blocked_days.get(machine_id, set())
        or day_idx in data.tool_blocked_days.get(tool_id, set())
    )


def _same_machine_tool_free_gaps(
    segments: list[Segment],
    ignored: Segment,
    *,
    machine_id: str,
    tool_id: str,
    day_idx: int,
    config: FactoryConfig,
) -> list[tuple[int, int]]:
    busy: list[tuple[int, int]] = []
    for segment in segments:
        if segment is ignored or segment.lot_id == ignored.lot_id:
            continue
        if segment.day_idx != day_idx:
            continue
        if segment.machine_id != machine_id and segment.tool_id != tool_id:
            continue
        start = max(config.shift_a_start, int(segment.start_min))
        end = min(config.shift_b_end, int(segment.end_min))
        if end > start:
            busy.append((start, end))

    gaps: list[tuple[int, int]] = []
    cursor = config.shift_a_start
    for start, end in sorted(busy):
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < config.shift_b_end:
        gaps.append((cursor, config.shift_b_end))
    return gaps


def _setup_capacity_ok_for_trial(
    segments: list[Segment],
    config: FactoryConfig,
    *,
    machine_id: str,
    day_idx: int,
    start_min: float,
    setup_min: float,
    ignored_lot_ids: set[str] | None = None,
    data: EngineData | None = None,
) -> bool:
    if setup_min <= 0:
        return True
    from backend.scheduler.resources import reserved_setup_segments

    ignored = ignored_lot_ids or set()
    group = config.machine_groups.get(machine_id, "Grandes")
    capacity = max(1, int(config.setup_crews_by_group.get(group, 1)))
    events: list[tuple[float, int]] = [(start_min, 1), (start_min + setup_min, -1)]
    # Crew occupancy of protected work (history) counts like plan setups.
    for segment in [*segments, *reserved_setup_segments(data)]:
        if segment.lot_id in ignored or segment.day_idx != day_idx or segment.setup_min <= 0:
            continue
        if config.machine_groups.get(segment.machine_id, "Grandes") != group:
            continue
        events.extend(
            [
                (float(segment.start_min), 1),
                (float(segment.start_min + segment.setup_min), -1),
            ]
        )
    active = 0
    for _minute, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        if active > capacity:
            return False
    return True


def _setup_aware_candidate_starts(
    segments: list[Segment],
    config: FactoryConfig,
    *,
    machine_id: str,
    day_idx: int,
    earliest: int,
    latest: int,
    setup_min: float,
    ignored_lot_ids: set[str] | None = None,
    data: EngineData | None = None,
) -> list[int]:
    """Return starts unlocked when a competing setup crew becomes free."""

    if latest < earliest:
        return []
    from backend.scheduler.resources import reserved_setup_segments

    ignored = ignored_lot_ids or set()
    candidates = {int(earliest)}
    if setup_min > 0:
        group = config.machine_groups.get(machine_id, "Grandes")
        for segment in [*segments, *reserved_setup_segments(data)]:
            if (
                segment.lot_id in ignored
                or segment.day_idx != day_idx
                or segment.setup_min <= 0
                or config.machine_groups.get(segment.machine_id, "Grandes") != group
            ):
                continue
            setup_end = math.ceil(segment.production_start_min)
            if earliest <= setup_end <= latest:
                candidates.add(setup_end)
    return [
        start
        for start in sorted(candidates)
        if _setup_capacity_ok_for_trial(
            segments,
            config,
            machine_id=machine_id,
            day_idx=day_idx,
            start_min=start,
            setup_min=setup_min,
            ignored_lot_ids=ignored,
            data=data,
        )
    ]


def _rematerialize_single_segment_lot(
    template: Segment,
    lot: Lot,
    day_idx: int,
    start_min: int,
    setup_min: float,
    config: FactoryConfig,
) -> Segment:
    duration = int(math.ceil(setup_min + float(lot.prod_min)))
    end_min = start_min + duration
    shift_b_start = config.shifts[1].start_min if len(config.shifts) > 1 else config.shift_a_end
    shift = next(
        (
            shift.id
            for shift in config.shifts
            if start_min >= shift.start_min and end_min <= shift.end_min
        ),
        "A" if start_min < shift_b_start else "B",
    )
    return replace(
        template,
        day_idx=day_idx,
        start_min=int(start_min),
        end_min=int(end_min),
        shift=shift,
        qty=lot.qty,
        prod_min=float(lot.prod_min),
        setup_min=float(setup_min),
        is_continuation=False,
        lot_qty=lot.qty,
        run_qty=lot.qty,
        run_setup_min=float(setup_min),
        run_lot_count=1,
    )


def _repair_remaining_run_setup(
    segments: list[Segment],
    run_id: str,
    setup_min: float,
    config: FactoryConfig,
) -> None:
    remaining = sorted(
        (segment for segment in segments if segment.run_id == run_id),
        key=lambda item: (item.day_idx, item.start_min),
    )
    if not remaining or any(segment.setup_min > 0 for segment in remaining):
        return
    first = remaining[0]
    new_start = int(math.floor(first.start_min - setup_min))
    if new_start < config.shift_a_start:
        raise ValueError("no room to repair source setup")
    for other in segments:
        if other is first or other.day_idx != first.day_idx:
            continue
        if other.machine_id != first.machine_id and other.tool_id != first.tool_id:
            continue
        if new_start < other.end_min and other.start_min < first.start_min:
            raise ValueError("source setup repair would overlap")
    if not _setup_capacity_ok_for_trial(
        segments,
        config,
        machine_id=first.machine_id,
        day_idx=first.day_idx,
        start_min=new_start,
        setup_min=setup_min,
        ignored_lot_ids={first.lot_id},
    ):
        raise ValueError("source setup repair lacks setup crew capacity")
    first.start_min = new_start
    first.setup_min = float(setup_min)
    first.is_continuation = False


def _repair_stale_mounted_setups(
    segments: list[Segment],
    inserted: Segment,
    config: FactoryConfig,
) -> None:
    inserted_start, inserted_end = segment_abs(inserted, config)
    by_run: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        if segment.machine_id == inserted.machine_id and segment.run_id != inserted.run_id:
            by_run[segment.run_id].append(segment)

    for run_segments in by_run.values():
        planning_checkpoint()
        setup_segments = [segment for segment in run_segments if segment.setup_min > 0]
        prod_segments = [segment for segment in run_segments if segment.prod_min > 0]
        if not setup_segments or not prod_segments:
            continue
        setup = min(setup_segments, key=lambda item: segment_abs(item, config)[0])
        first_prod = min(prod_segments, key=lambda item: segment_abs(item, config)[0])
        setup_start, setup_end = segment_abs(setup, config)
        prod_start, _prod_end = segment_abs(first_prod, config)
        if not (setup_end <= inserted_start + 0.01 and inserted_end <= prod_start + 0.01):
            continue
        if segment_setup_identity(setup) == segment_setup_identity(inserted):
            continue

        setup_min = float(setup.setup_min)
        repaired_start = int(math.floor(first_prod.start_min - setup_min))
        if repaired_start < config.shift_a_start:
            shift_delta = config.shift_a_start - repaired_start
            if not _shift_run_suffix_same_day(
                segments,
                first_prod.run_id,
                first_prod,
                shift_delta,
                config,
            ):
                raise ValueError("stale mounted setup cannot be repaired before production")
            repaired_start = int(math.floor(first_prod.start_min - setup_min))
        for other in segments:
            if other in (setup, first_prod):
                continue
            if other.day_idx != first_prod.day_idx:
                continue
            if other.machine_id != first_prod.machine_id and other.tool_id != first_prod.tool_id:
                continue
            if repaired_start < other.end_min and other.start_min < first_prod.start_min:
                raise ValueError("stale mounted setup repair would overlap")
        if not _setup_capacity_ok_for_trial(
            segments,
            config,
            machine_id=first_prod.machine_id,
            day_idx=first_prod.day_idx,
            start_min=repaired_start,
            setup_min=setup_min,
            ignored_lot_ids={setup.lot_id, first_prod.lot_id},
        ):
            raise ValueError("stale mounted setup repair lacks crew capacity")

        first_prod.start_min = repaired_start
        first_prod.setup_min = setup_min
        first_prod.is_continuation = False
        if setup.prod_min <= 0 and setup.qty <= 0:
            segments.remove(setup)
        else:
            setup.setup_min = 0.0


def _merge_detached_setup_segments(
    segments: list[Segment],
    config: FactoryConfig,
    lots: list[Lot] | None = None,
    holidays: set[int] | None = None,
    *,
    data: EngineData | None = None,
    protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Attach setup-only fragments to the first productive segment of the run.

    The global JIT materializer can represent a run as "setup today, production
    tomorrow" even when the production day has room to carry that setup. That is
    physically ambiguous on the Gantt: it looks like a zero-piece lot or a setup
    disconnected from the production it prepares. Keep the solver's machine/tool
    choice, but materialize the setup beside the first production when possible.
    """

    protected = (planning_protected_lot_ids(data, protected_lot_ids)
                 if data is not None else set(protected_lot_ids or ()))
    protected_runs = {segment.run_id for segment in segments if segment.lot_id in protected}
    before = copy.deepcopy(segments)
    before_violations = Counter(
        violation["kind"]
        for violation in validate_plan(before, data, config, lots=lots)
    )
    current = copy.deepcopy(segments)
    lots_by_id = {lot.id: lot for lot in lots or []}
    holiday_set = holidays or set()
    for setup in sorted(
        (
            segment
            for segment in current
            if segment.setup_min > 0 and segment.prod_min <= 0 and segment.qty <= 0
        ),
        key=lambda item: segment_abs(item, config)[0],
    ):
        planning_checkpoint()
        if setup not in current or setup.run_id in protected_runs:
            continue
        setup_min = float(setup.setup_min)
        if setup_min <= 0:
            continue
        candidates = sorted(
            (
                segment
                for segment in current
                if segment.run_id == setup.run_id
                and segment.machine_id == setup.machine_id
                and segment.tool_id == setup.tool_id
                and segment.prod_min > 0
            ),
            key=lambda item: segment_abs(item, config)[0],
        )
        if not candidates:
            continue
        first_prod = candidates[0]
        setup_start, _setup_end = segment_abs(setup, config)
        prod_start, _prod_end = segment_abs(first_prod, config)
        if prod_start < setup_start:
            continue
        # Shift-boundary splitting can legitimately leave the first part of a
        # setup in a setup-only segment and the remainder at the start of the
        # productive segment.  The two blocks form one contiguous physical
        # setup; deleting the first fragment silently shortens it.
        if (
            first_prod.setup_min > 0
            and setup.day_idx == first_prod.day_idx
            and abs(float(setup.end_min) - float(first_prod.start_min)) <= 0.01
        ):
            continue

        production_segments = [
            segment
            for segment in candidates
            if segment.run_id == setup.run_id
            and segment.prod_min > 0
        ]
        if _move_detached_run_to_setup_day(
            current,
            setup,
            production_segments,
            config,
            lots_by_id=lots_by_id,
            holidays=holiday_set,
        ):
            continue

        if _park_setup_at_previous_workday_end(
            current,
            setup,
            first_prod,
            config,
            lots_by_id=lots_by_id,
            holidays=holiday_set,
        ):
            continue

        target_start = int(math.floor(first_prod.start_min - setup_min))
        shifted_segments: list[tuple[Segment, int, int, str]] = []
        if target_start < config.shift_a_start:
            delta = int(config.shift_a_start - target_start)
            # A setup immediately before the opening production cannot be
            # attached by moving only that run: it would overlap the next run
            # on the same machine. Reflow the remaining machine sequence as a
            # unit instead. This is deliberately local to this repair and is
            # still rejected on a tool conflict, crew conflict or shift end.
            for segment in current:
                if (
                    segment.machine_id == first_prod.machine_id
                    and segment.day_idx == first_prod.day_idx
                    and segment.start_min >= first_prod.start_min
                ):
                    shifted_segments.append(
                        (segment, segment.start_min, segment.end_min, segment.shift)
                    )
            if not _shift_machine_suffix_same_day(
                current,
                first_prod.machine_id,
                first_prod,
                delta,
                config,
                protected_lot_ids=protected,
            ):
                continue
            target_start = int(math.floor(first_prod.start_min - setup_min))
        if target_start < config.shift_a_start:
            for segment, start_min, end_min, shift in shifted_segments:
                segment.start_min = start_min
                segment.end_min = end_min
                segment.shift = shift
            continue

        overlaps = False
        for other in current:
            if other in (setup, first_prod) or other.day_idx != first_prod.day_idx:
                continue
            if other.machine_id != first_prod.machine_id and other.tool_id != first_prod.tool_id:
                continue
            if target_start < other.end_min and other.start_min < first_prod.start_min:
                overlaps = True
                break
        if overlaps:
            for segment, start_min, end_min, shift in shifted_segments:
                segment.start_min = start_min
                segment.end_min = end_min
                segment.shift = shift
            continue

        if not _setup_capacity_ok_for_trial(
            current,
            config,
            machine_id=first_prod.machine_id,
            day_idx=first_prod.day_idx,
            start_min=target_start,
            setup_min=setup_min,
            ignored_lot_ids={setup.lot_id, first_prod.lot_id},
        ):
            for segment, start_min, end_min, shift in shifted_segments:
                segment.start_min = start_min
                segment.end_min = end_min
                segment.shift = shift
            continue

        first_prod.start_min = target_start
        first_prod.setup_min = float(first_prod.setup_min) + setup_min
        first_prod.is_continuation = False
        first_prod.run_setup_min = max(
            float(first_prod.run_setup_min or 0.0),
            float(first_prod.setup_min),
        )
        current.remove(setup)

    current = split_production_at_shift_boundaries(
        current, config, data, lots, protected_lot_ids=protected,
    )
    after_violations = Counter(
        violation["kind"]
        for violation in validate_plan(current, data, config, lots=lots)
    )
    new_violations = {
        kind: count - before_violations.get(kind, 0)
        for kind, count in after_violations.items()
        if count > before_violations.get(kind, 0)
    }
    if new_violations:
        logger.warning(
            "Detached setup merge reverted: new physical violations %s",
            new_violations,
        )
        current = before

    return sorted(current, key=lambda item: (item.day_idx, item.start_min, item.machine_id))


def _park_setup_at_previous_workday_end(
    segments: list[Segment],
    setup: Segment,
    first_prod: Segment,
    config: FactoryConfig,
    *,
    lots_by_id: dict[str, Lot],
    holidays: set[int],
) -> bool:
    """Keep setup attached across a closed factory interval.

    A setup may finish at factory close and feed production at the opening of
    the next workday. The machine remains committed in between, so no other
    reference can use it. This is the only accepted cross-day separation.
    """

    if first_prod.start_min != config.shift_a_start:
        return False

    previous_day = first_prod.day_idx - 1
    while previous_day >= 0 and previous_day in holidays:
        planning_checkpoint()
        previous_day -= 1
    if previous_day < 0:
        return False
    lot = lots_by_id.get(first_prod.lot_id)
    if lot is not None and previous_day < earliest_allowed_start(lot, holidays):
        return False

    setup_min = int(math.ceil(float(setup.setup_min)))
    target_end = int(config.shift_b_end)
    target_start = target_end - setup_min
    if target_start < config.shift_a_start:
        return False

    for other in segments:
        if other in (setup, first_prod):
            continue
        shares_machine = other.machine_id == first_prod.machine_id
        shares_tool = other.tool_id == first_prod.tool_id
        if not (shares_machine or shares_tool):
            continue
        if other.day_idx == previous_day:
            if target_start < other.end_min and other.start_min < target_end:
                return False
        elif shares_machine and previous_day < other.day_idx < first_prod.day_idx:
            return False
        elif (
            shares_machine
            and other.day_idx == first_prod.day_idx
            and other.start_min < first_prod.start_min
        ):
            return False

    if not _setup_capacity_ok_for_trial(
        segments,
        config,
        machine_id=first_prod.machine_id,
        day_idx=previous_day,
        start_min=target_start,
        setup_min=setup_min,
        ignored_lot_ids={setup.lot_id, first_prod.lot_id},
    ):
        return False

    setup.day_idx = previous_day
    setup.start_min = target_start
    setup.end_min = target_end
    setup.shift = _shift_for_start(config, target_start)
    setup.is_continuation = False
    return True


def _move_detached_run_to_setup_day(
    segments: list[Segment],
    setup: Segment,
    production_segments: list[Segment],
    config: FactoryConfig,
    *,
    lots_by_id: dict[str, Lot],
    holidays: set[int],
) -> bool:
    """Move a detached setup's production into the setup day when it fits."""

    if not production_segments:
        return False
    ordered = sorted(production_segments, key=lambda item: segment_abs(item, config)[0])
    if lots_by_id and any(
        setup.day_idx < earliest_allowed_start(lots_by_id[segment.lot_id], holidays)
        for segment in ordered
        if segment.lot_id in lots_by_id
    ):
        return False

    setup_min = float(setup.setup_min)
    embedded_setup_min = sum(float(segment.setup_min) for segment in ordered)
    total_setup_min = setup_min + embedded_setup_min
    total_duration = int(
        math.ceil(total_setup_min + sum(float(segment.prod_min) for segment in ordered))
    )
    target_start = int(setup.start_min)
    target_end = target_start + total_duration
    if target_start < config.shift_a_start or target_end > config.shift_b_end:
        return False

    for other in segments:
        if other is setup or other in ordered or other.day_idx != setup.day_idx:
            continue
        if other.machine_id != setup.machine_id and other.tool_id != setup.tool_id:
            continue
        if target_start < other.end_min and other.start_min < target_end:
            return False

    cursor = target_start
    for idx, segment in enumerate(ordered):
        duration = int(
            math.ceil(float(segment.prod_min) + (total_setup_min if idx == 0 else 0.0))
        )
        segment.day_idx = setup.day_idx
        segment.start_min = cursor
        segment.end_min = cursor + duration
        segment.shift = _shift_for_start(config, segment.start_min)
        segment.setup_min = total_setup_min if idx == 0 else 0.0
        segment.is_continuation = idx > 0
        segment.run_setup_min = max(
            float(segment.run_setup_min or 0.0),
            total_setup_min,
        )
        cursor = segment.end_min
    segments.remove(setup)
    split_segments = split_production_at_shift_boundaries(ordered, config)
    for segment in ordered:
        segments.remove(segment)
    segments.extend(split_segments)
    return True


def _shift_for_start(config: FactoryConfig, start_min: int) -> str:
    for shift in config.shifts:
        if shift.start_min <= start_min < shift.end_min:
            return shift.id
    if len(config.shifts) > 1 and start_min >= config.shifts[1].start_min:
        return config.shifts[1].id
    return config.shifts[0].id if config.shifts else "A"


def _shift_run_suffix_same_day(
    segments: list[Segment],
    run_id: str,
    first_segment: Segment,
    delta_min: int,
    config: FactoryConfig,
) -> bool:
    if delta_min <= 0:
        return True
    suffix = sorted(
        (
            segment
            for segment in segments
            if segment.run_id == run_id
            and segment.day_idx == first_segment.day_idx
            and segment.start_min >= first_segment.start_min
        ),
        key=lambda item: (item.start_min, item.end_min),
    )
    if not suffix:
        return False
    if suffix[-1].end_min + delta_min > config.shift_b_end:
        return False
    for segment in suffix:
        for other in segments:
            if other in suffix or other.day_idx != segment.day_idx:
                continue
            if other.machine_id != segment.machine_id and other.tool_id != segment.tool_id:
                continue
            if (
                segment.start_min + delta_min < other.end_min
                and other.start_min < segment.end_min + delta_min
            ):
                return False
    for segment in suffix:
        segment.start_min += delta_min
        segment.end_min += delta_min
    return True


def _shift_machine_suffix_same_day(
    segments: list[Segment],
    machine_id: str,
    first_segment: Segment,
    delta_min: int,
    config: FactoryConfig,
    *,
    protected_lot_ids: set[str] | None = None,
) -> bool:
    """Delay a machine's remaining day sequence without creating tool clashes.

    This is used only to attach a setup that otherwise sits on the preceding
    day. Shifting every later segment preserves the machine order; the explicit
    cross-machine tool check keeps a physical mould from being used twice.
    """
    if delta_min <= 0:
        return True
    suffix = sorted(
        (
            segment
            for segment in segments
            if segment.machine_id == machine_id
            and segment.day_idx == first_segment.day_idx
            and segment.start_min >= first_segment.start_min
        ),
        key=lambda item: (item.start_min, item.end_min),
    )
    if (not suffix or suffix[-1].end_min + delta_min > config.shift_b_end
            or any(segment.lot_id in (protected_lot_ids or ()) for segment in suffix)):
        return False

    suffix_ids = {id(segment) for segment in suffix}
    for segment in suffix:
        new_start = segment.start_min + delta_min
        new_end = segment.end_min + delta_min
        for other in segments:
            if id(other) in suffix_ids or other.day_idx != segment.day_idx:
                continue
            shares_machine = other.machine_id == segment.machine_id
            shares_tool = other.tool_id == segment.tool_id
            if (
                (shares_machine or shares_tool)
                and new_start < other.end_min
                and other.start_min < new_end
            ):
                return False

    for segment in suffix:
        segment.start_min += delta_min
        segment.end_min += delta_min
        segment.shift = _shift_for_start(config, segment.start_min)
    return True


def _accept_zero_slack_repair(before: dict, after: dict) -> bool:
    """Accept a legal left-shift of an urgent lot.

    ``latest_start_gap`` grows when a lot is moved earlier inside its material
    window.  That is the desired direction for this repair, so it cannot be
    used as a rejection criterion here.
    """
    if after.get("hard_violations", 0) > before.get("hard_violations", 0):
        return False
    if not delivery_not_worse(after, before):
        return False
    if after.get("early_window_violations", 0) > before.get("early_window_violations", 0):
        return False
    if after.get("operator_capacity_violations", 0) > before.get(
        "operator_capacity_violations", 0
    ):
        return False
    if after.get("setup_crew_overlaps", 0) > before.get("setup_crew_overlaps", 0):
        return False
    # An extra setup does not veto an earlier legal start (AGENTS.md §1.5);
    # its physical validity is enforced by the hard-violation gates above.
    before_temporal = before.get("production_time_cost")
    after_temporal = after.get("production_time_cost")
    if (
        isinstance(before_temporal, int | float)
        and isinstance(after_temporal, int | float)
        and float(after_temporal) >= float(before_temporal) - 1e-6
    ):
        return False
    return True


def _segment_schedule_signature(segments: list[Segment]) -> tuple[tuple, ...]:
    """Return the physical schedule identity used by fixed-point repairs."""

    return tuple(
        sorted(
            (
                segment.lot_id,
                segment.run_id,
                segment.machine_id,
                segment.tool_id,
                segment.day_idx,
                round(float(segment.start_min), 3),
                round(float(segment.end_min), 3),
                round(float(segment.setup_min), 3),
                round(float(segment.prod_min), 3),
                int(segment.qty),
            )
            for segment in segments
        )
    )


def _close_earliest_legal_start_fixed_point(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    holidays: set[int],
    *,
    max_passes: int = 32,
    protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Finish the plan through the single canonical normalization path."""

    return _stabilize_earliest_legal_starts(
        split_production_at_shift_boundaries(
            segments,
            config,
            data,
            lots,
            protected_lot_ids=protected_lot_ids,
        ),
        lots,
        data,
        config,
        holidays,
        max_passes=max_passes,
        protected_lot_ids=protected_lot_ids,
    )


@measured("normalization")
def normalize_earliest_legal_plan(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    max_passes: int = 32,
    annotate: bool = True,
    protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Return the canonical final sequence used by every solver path.

    The material-release floor is a hard lower bound. Once work is released,
    this normalizer closes every resource-safe gap that can be closed without
    worsening delivery, quantities, setup effort or physical feasibility.
    """

    planning_checkpoint()
    if not segments:
        return []
    first_day = min((segment.day_idx for segment in segments), default=0)
    last_day = max((segment.day_idx for segment in segments), default=data.n_days)
    holidays = calendar_holidays(
        data,
        min(-14, first_day - 14),
        max(data.n_days + 30, last_day + 30),
    )
    normalized = _close_earliest_legal_start_fixed_point(
        copy.deepcopy(segments),
        lots,
        data,
        config,
        holidays,
        max_passes=max_passes,
        protected_lot_ids=protected_lot_ids,
    )

    # Blocker annotations belong to the settled physical plan. Keeping this in
    # the public normalizer prevents the UI and operational gate from auditing
    # a different sequence from the one returned by an advisory solver.
    if annotate:
        from backend.scheduler.explainability import annotate_left_shift_blockers

        annotate_left_shift_blockers(
            normalized, lots, data, config,
            protected_lot_ids=protected_lot_ids,
        )
    planning_checkpoint()
    return normalized


def _detect_tool_machine_overlaps(
    segments: list[Segment],
    config: FactoryConfig | None = None,
) -> list[tuple[str, str, str, int]]:
    """Find time overlaps of the SAME tool_id on DIFFERENT machines.

    A physical tool (mould) is unique — it can move between machines over time
    but can never run in two machines at once. Returns a list of
    (tool_id, machine_a, machine_b, day_idx) for each conflicting pair.
    """
    by_tool: dict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        if seg.end_min > seg.start_min:  # skip zero-duration placeholders
            by_tool[seg.tool_id].append(seg)

    conflicts: list[tuple[str, str, str, int]] = []
    for tool_id, segs in by_tool.items():
        planning_checkpoint()
        segs = sorted(segs, key=lambda s: _seg_abs(s, config)[0])
        for i in range(len(segs)):
            planning_checkpoint()
            a_start, a_end = _seg_abs(segs[i], config)
            for j in range(i + 1, len(segs)):
                b_start, b_end = _seg_abs(segs[j], config)
                if b_start >= a_end:
                    break  # sorted — no later segment can overlap
                if segs[j].machine_id != segs[i].machine_id:
                    conflicts.append(
                        (tool_id, segs[i].machine_id, segs[j].machine_id, segs[i].day_idx)
                    )
    return conflicts


def _fix_tool_machine_overlaps(
    segments: list[Segment],
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
) -> list[Segment]:
    """Resolve same-tool-on-two-machines overlaps by deferring the later run.

    For each conflict, the segment that is LESS urgent (higher EDD, later start)
    is pushed forward until the tool is free — but only while it stays on time
    (day_idx <= edd). If it cannot be deferred without going tardy, the conflict
    is left for the verification warning rather than risking an OTD regression.
    """
    effective_config = config or FactoryConfig()
    hols = holidays or set()

    fixed = 0
    for _ in range(len(segments) + 1):
        planning_checkpoint()
        conflicts = _detect_tool_machine_overlaps(segments, config)
        if not conflicts:
            break

        by_tool: dict[str, list[Segment]] = defaultdict(list)
        for seg in segments:
            if seg.end_min > seg.start_min:
                by_tool[seg.tool_id].append(seg)

        moved_any = False
        for tool_id, _ma, _mb, _day in conflicts:
            segs = sorted(
                by_tool[tool_id],
                key=lambda s: _seg_abs(s, config)[0],
            )
            for i in range(len(segs)):
                a_start, a_end = _seg_abs(segs[i], config)
                for j in range(i + 1, len(segs)):
                    b_start, b_end = _seg_abs(segs[j], config)
                    if b_start >= a_end:
                        break
                    if segs[j].machine_id == segs[i].machine_id:
                        continue
                    # Defer the less-urgent of the two (higher EDD, then later).
                    earlier, later = segs[i], segs[j]
                    if later.edd < earlier.edd:
                        earlier, later = later, earlier
                    _e_start, e_end = _seg_abs(earlier, config)
                    duration = later.end_min - later.start_min
                    # Push `later` to start when `earlier` frees the tool.
                    slot = _shift_slot_at_or_after(
                        e_end,
                        duration,
                        effective_config,
                        hols,
                    )
                    if slot is None:
                        continue
                    new_day, new_start_in_day, shift_id = slot
                    # OTD guard: never make the segment tardy to fix contention.
                    if new_day > later.edd:
                        continue
                    later.day_idx = new_day
                    later.start_min = new_start_in_day
                    later.end_min = new_start_in_day + duration
                    later.shift = shift_id
                    later.is_continuation = False
                    fixed += 1
                    moved_any = True
                    break
                if moved_any:
                    break
            if moved_any:
                break

        if not moved_any:
            break  # remaining conflicts cannot be fixed without tardy

    if fixed > 0:
        logger.info("Tool contention: resolved %d same-tool cross-machine overlaps", fixed)
    return segments


def _day_is_blocked(
    seg: Segment,
    day: int,
    data: EngineData,
    holidays: set[int],
) -> bool:
    """True when a segment cannot run on this day."""

    machine_blocked = getattr(data, "machine_blocked_days", {}) or {}
    tool_blocked = getattr(data, "tool_blocked_days", {}) or {}
    return (
        day in holidays
        or day in machine_blocked.get(seg.machine_id, set())
        or day in tool_blocked.get(seg.tool_id, set())
    )


def _shift_slot_at_or_after(
    min_abs_start: float,
    duration: float,
    config: FactoryConfig,
    holidays: set[int],
) -> tuple[int, int, str] | None:
    """Find the first contiguous real-shift slot on the productive axis."""

    required = max(1, int(math.ceil(duration)))
    shifts = sorted(config.shifts, key=lambda shift: (shift.start_min, shift.id))
    if not shifts or required > max(shift.duration_min for shift in shifts):
        return None

    day, start_min = abs_to_day_min(max(0.0, min_abs_start), config)
    for _ in range(10_000):
        planning_checkpoint()
        if day not in holidays:
            for shift in shifts:
                candidate = max(int(math.ceil(start_min)), int(shift.start_min))
                if candidate + required <= int(shift.end_min):
                    return day, candidate, shift.id
        day += 1
        start_min = int(shifts[0].start_min)
    return None


def _move_segment_at_or_after(
    seg: Segment,
    min_abs_start: float,
    data: EngineData,
    config: FactoryConfig,
    holidays: set[int],
) -> bool:
    """Move a segment to the first day/slot allowed by machine and tool calendars."""

    duration = seg.end_min - seg.start_min
    if duration <= 0:
        return False

    day_cap = config.day_capacity_min
    cursor_abs = float(min_abs_start)
    for _ in range(max(366, data.n_days + 60)):
        planning_checkpoint()
        slot = _shift_slot_at_or_after(cursor_abs, duration, config, holidays)
        if slot is None:
            return False
        day, start_min, shift_id = slot
        from backend.transform.calendars import calendar_window

        data = calendar_window(data, config, day, from_day=day)
        if _day_is_blocked(seg, day, data, holidays):
            cursor_abs = float((day + 1) * day_cap)
            continue

        end_min = int(round(start_min + duration))
        blocking_ends = [
            int(block.get("end_min", 1440))
            for block in (
                data.machine_blocked_intervals.get(seg.machine_id, [])
                + data.tool_blocked_intervals.get(seg.tool_id, [])
            )
            if int(block.get("start_day", -1)) == day
            and start_min < int(block.get("end_min", 1440))
            and int(block.get("start_min", 0)) < end_min
        ]
        if blocking_ends:
            cursor_abs = float(
                day * day_cap
                + clock_to_productive_offset(config, max(blocking_ends))
            )
            continue

        changed = (
            seg.day_idx != day
            or seg.start_min != start_min
            or seg.end_min != end_min
        )
        if changed:
            seg.day_idx = day
            seg.start_min = start_min
            seg.end_min = end_min
            seg.shift = shift_id
            seg.is_continuation = seg.setup_min <= 0
        return changed

    return False


def _repair_hard_constraints(
    segments: list[Segment],
    data: EngineData,
    config: FactoryConfig,
    holidays: set[int],
) -> list[Segment]:
    """Best-effort final repair for non-negotiable physical constraints.

    This pass is deliberately feasibility-first: if a segment must move past
    its EDD to avoid a real physical conflict, it moves. The score can degrade,
    but the plan cannot claim a machine/tool is doing impossible work.
    """

    segments = split_production_at_shift_boundaries(segments, config, data)
    max_passes = max(100, len(segments) * 8)
    moved_total = 0
    # Feasibility repair only pushes work later; it must never reorder a
    # machine. A segment pushed past its successors would otherwise place a
    # different tool between a setup and its production, or change tools
    # with no setup at all. Successors keep their original sequence rank.
    machine_rank = {
        id(seg): rank
        for rank, seg in enumerate(
            sorted(
                (s for s in segments if s.end_min > s.start_min),
                # A setup ranks before production starting at the same
                # instant, matching the run rule below.
                key=lambda s: (
                    s.machine_id,
                    segment_abs(s, config)[0],
                    0 if s.setup_min > 0 else 1,
                    s.end_min,
                ),
            )
        )
    }

    for _ in range(max_passes):
        planning_checkpoint()
        active = [s for s in segments if s.end_min > s.start_min]
        moved = False

        for seg in sorted(active, key=lambda s: segment_abs(s, config)[0]):
            if _day_is_blocked(seg, seg.day_idx, data, holidays):
                next_day_abs = (seg.day_idx + 1) * config.day_capacity_min
                moved = _move_segment_at_or_after(seg, next_day_abs, data, config, holidays)
                if moved:
                    moved_total += 1
                    break
        if moved:
            continue

        for seg in sorted(active, key=lambda s: segment_abs(s, config)[0]):
            blocking_ends = [
                int(block.get("end_min", 1440))
                for block in (
                    data.machine_blocked_intervals.get(seg.machine_id, [])
                    + data.tool_blocked_intervals.get(seg.tool_id, [])
                )
                if int(block.get("start_day", -1)) == seg.day_idx
                and int(seg.start_min) < int(block.get("end_min", 1440))
                and int(block.get("start_min", 0)) < int(seg.end_min)
            ]
            if not blocking_ends:
                continue
            blocked_until = float(
                seg.day_idx * config.day_capacity_min
                + clock_to_productive_offset(config, max(blocking_ends))
            )
            moved = _move_segment_at_or_after(
                seg,
                blocked_until,
                data,
                config,
                holidays,
            )
            if moved:
                moved_total += 1
                break
        if moved:
            continue

        by_run: dict[str, list[Segment]] = defaultdict(list)
        for seg in active:
            by_run[seg.run_id].append(seg)
        for run_segs in by_run.values():
            setup_segs = [s for s in run_segs if s.setup_min > 0]
            if not setup_segs:
                continue
            setup = min(setup_segs, key=lambda s: segment_abs(s, config)[0])
            setup_start, _setup_end = segment_abs(setup, config)
            setup_done = setup_start + setup.setup_min
            for seg in sorted(run_segs, key=lambda s: segment_abs(s, config)[0]):
                if seg is setup:
                    continue
                seg_start, _seg_end = segment_abs(seg, config)
                if seg_start < setup_done - 0.01:
                    moved = _move_segment_at_or_after(seg, setup_done, data, config, holidays)
                    if moved:
                        moved_total += 1
                        break
            if moved:
                break
        if moved:
            continue

        by_machine: dict[str, list[Segment]] = defaultdict(list)
        for seg in active:
            by_machine[seg.machine_id].append(seg)
        for machine_segs in by_machine.values():
            ordered = sorted(
                machine_segs,
                key=lambda s: (
                    machine_rank.get(id(s), len(machine_rank)),
                    segment_abs(s, config)[0],
                ),
            )
            # Ripple the whole machine tail in one sweep: restarting the
            # outer scan after every single push is quadratic on long plans.
            for prev, curr in zip(ordered, ordered[1:]):
                if (
                    curr.run_id == prev.run_id
                    and curr.setup_min > 0
                    and prev.setup_min <= 0
                ):
                    # Never push a setup behind its own production (the two
                    # rules would leapfrog forever). The production belongs
                    # after its setup block: move it there and keep that
                    # order for the rest of the repair.
                    machine_rank[id(prev)], machine_rank[id(curr)] = (
                        machine_rank.get(id(curr), len(machine_rank)),
                        machine_rank.get(id(prev), len(machine_rank)),
                    )
                    _curr_start, curr_end = segment_abs(curr, config)
                    prev_start, _prev_end = segment_abs(prev, config)
                    if prev_start < curr_end - 0.01 and _move_segment_at_or_after(
                        prev, curr_end, data, config, holidays
                    ):
                        moved_total += 1
                    moved = True
                    break
                _prev_start, prev_end = segment_abs(prev, config)
                curr_start, _curr_end = segment_abs(curr, config)
                if curr_start < prev_end - 0.01 and _move_segment_at_or_after(
                    curr, prev_end, data, config, holidays
                ):
                    moved_total += 1
                    moved = True
        if moved:
            continue

        by_tool: dict[str, list[Segment]] = defaultdict(list)
        for seg in active:
            by_tool[seg.tool_id].append(seg)
        for tool_segs in by_tool.values():
            ordered = sorted(tool_segs, key=lambda s: segment_abs(s, config)[0])
            for i, first in enumerate(ordered):
                planning_checkpoint()
                _first_start, first_end = segment_abs(first, config)
                for second in ordered[i + 1 :]:
                    second_start, second_end = segment_abs(second, config)
                    if second_start >= first_end - 0.01:
                        break
                    if first.machine_id != second.machine_id and second_end > second_start:
                        moved = _move_segment_at_or_after(second, first_end, data, config, holidays)
                        if moved:
                            moved_total += 1
                            break
                if moved:
                    break
            if moved:
                break
        if moved:
            continue

        setup_entries_by_group: dict[str, list[tuple[float, float, Segment]]] = defaultdict(list)
        for seg in active:
            if seg.setup_min > 0:
                setup_start, _seg_end = segment_abs(seg, config)
                setup_entries_by_group[_setup_group(seg, config)].append(
                    (setup_start, setup_start + seg.setup_min, seg)
                )
        for group, setup_entries in setup_entries_by_group.items():
            capacity = _setup_group_capacity(config, group)
            active_setup_ends: list[float] = []
            for setup_start, setup_end, setup_seg in sorted(
                setup_entries,
                key=lambda item: item[0],
            ):
                active_setup_ends = [
                    end for end in active_setup_ends if end > setup_start + 0.01
                ]
                if len(active_setup_ends) >= capacity:
                    crew_free_at = min(active_setup_ends)
                    moved = _move_segment_at_or_after(
                        setup_seg,
                        crew_free_at,
                        data,
                        config,
                        holidays,
                    )
                    if moved:
                        moved_total += 1
                        break
                active_setup_ends.append(setup_end)
            if moved:
                break
        if moved:
            continue

        break

    if moved_total > 0:
        logger.info("Hard-constraint repair moved %d segment(s)", moved_total)
    return segments


def _setup_group(seg: Segment, config: FactoryConfig | None) -> str:
    return (config.machine_groups if config else {}).get(seg.machine_id, "Grandes")


def _setup_group_capacity(config: FactoryConfig | None, group: str) -> int:
    if config is None:
        return 1
    return max(1, int(config.setup_crews_by_group.get(group, 1)))


def _find_predecessor_end(segments: list[Segment], target: Segment, shift_a_start: int) -> int:
    """Find the end_min of the latest predecessor on the same machine/day before target."""
    pred_end = shift_a_start
    for other in segments:
        if (
            other.machine_id == target.machine_id
            and other.day_idx == target.day_idx
            and other.end_min <= target.start_min
            and other.end_min > pred_end
        ):
            pred_end = other.end_min
    return pred_end


def _try_pull_back(
    segments: list[Segment],
    blocker_seg_idx: int,
    blocker_abs_start: float,
    prev_crew_end: float,
    delay_needed: float,
    config: FactoryConfig | None,
) -> tuple[bool, float, float]:
    """Try pulling the blocker segment back in time to make room.

    Returns (pulled, new_blocker_abs_start, new_crew_free_at).
    """
    bseg = segments[blocker_seg_idx]
    pull_back_available = blocker_abs_start - prev_crew_end
    is_full = pull_back_available >= delay_needed
    pull_amount = int(delay_needed + 0.5) if is_full else int(pull_back_available)

    if pull_amount < 1:
        return False, blocker_abs_start, 0.0

    effective_config = config or FactoryConfig()
    current_shift = next(
        (
            shift
            for shift in effective_config.shifts
            if int(shift.start_min) <= int(bseg.start_min) < int(shift.end_min)
        ),
        None,
    )
    if current_shift is None:
        return False, blocker_abs_start, 0.0
    pred_end = _find_predecessor_end(
        segments,
        bseg,
        int(current_shift.start_min),
    )
    earliest = max(int(current_shift.start_min), pred_end)
    pull_amount = min(pull_amount, max(0, int(bseg.start_min) - earliest))
    new_bstart = bseg.start_min - pull_amount

    if pull_amount < 1:
        return False, blocker_abs_start, 0.0

    bseg.end_min -= pull_amount
    bseg.start_min = new_bstart
    new_blocker_abs = blocker_abs_start - pull_amount
    new_crew_free = new_blocker_abs + bseg.setup_min
    return is_full, new_blocker_abs, new_crew_free


def _push_forward(
    seg: Segment,
    crew_free_at: float,
    abs_start: float,
    _duration: float,
    config: FactoryConfig | None,
    holidays: set[int],
) -> bool:
    """Push a setup segment forward in time to avoid crew overlap.

    Returns True if segment was shifted.
    """
    delay = int(crew_free_at - abs_start + 0.5)
    if delay < 1:
        return False

    effective_config = config or FactoryConfig()
    seg_duration = seg.end_min - seg.start_min
    slot = _shift_slot_at_or_after(
        crew_free_at,
        seg_duration,
        effective_config,
        holidays,
    )
    if slot is None:
        return False
    new_day, new_start, shift_id = slot
    seg.day_idx = new_day
    seg.start_min = new_start
    seg.end_min = new_start + seg_duration
    seg.shift = shift_id
    return True


def _serialize_crew_setups(
    segments: list[Segment],
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
    crew_priority: list[str] | None = None,
) -> list[Segment]:
    """Serialize setups independently inside every machine group."""
    groups = sorted(
        {
            (config.machine_groups if config else {}).get(segment.machine_id, "Grandes")
            for segment in segments
            if segment.setup_min > 0
        }
    )
    for group in groups:
        segments = _serialize_crew_setups_group(
            segments,
            config,
            holidays,
            crew_priority,
            group,
        )
    return segments


def _serialize_crew_setups_group(
    segments: list[Segment],
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
    crew_priority: list[str] | None = None,
    group: str = "Grandes",
) -> list[Segment]:
    """Serialize setups for one group with configured crew capacity.

    JIT/VNS dispatch each machine independently (no shared crew) for gate independence.
    This post-processing step delays ONLY the overlapping setup segment (not all
    subsequent segments). Intra-machine cascading is handled by _fix_day_overlaps.

    Bidirectional resolution: tries pulling the blocker back before pushing current forward.
    """
    hols = holidays or set()

    # Build priority lookup (lower index = higher priority = not delayed)
    prio_map: dict[str, int] = {}
    if crew_priority:
        prio_map = {m: i for i, m in enumerate(crew_priority)}

    # Collect setups with absolute time (including buffer days)
    setup_entries: list[tuple[float, float, int]] = []
    for idx, seg in enumerate(segments):
        seg_group = (config.machine_groups if config else {}).get(
            seg.machine_id, "Grandes"
        )
        if seg.setup_min > 0 and seg_group == group:
            abs_start = segment_abs(seg, config)[0]
            setup_entries.append((abs_start, seg.setup_min, idx))

    if not setup_entries:
        return segments

    setup_entries.sort(key=lambda e: (e[0], prio_map.get(segments[e[2]].machine_id, 99)))
    capacity = _setup_group_capacity(config, group)

    if capacity > 1:
        crew_free_times = [min(e[0] for e in setup_entries)] * capacity
        shifted = 0
        for abs_start, duration, seg_idx in setup_entries:
            seg = segments[seg_idx]
            crew_index = min(range(capacity), key=crew_free_times.__getitem__)
            crew_free_at = crew_free_times[crew_index]
            if abs_start < crew_free_at - 0.01:
                if _push_forward(
                    seg,
                    crew_free_at,
                    abs_start,
                    duration,
                    config,
                    hols,
                ):
                    shifted += 1
                    new_abs_start = segment_abs(seg, config)[0]
                    crew_free_times[crew_index] = new_abs_start + duration
                else:
                    crew_free_times[crew_index] = abs_start + duration
            else:
                crew_free_times[crew_index] = abs_start + duration
        if shifted > 0:
            logger.info(
                "Crew serialization for %s: shifted %d setup segments",
                group,
                shifted,
            )
        return segments

    # Initialize before the earliest setup, including negative buffer-day absolute times.
    crew_free_at = min(e[0] for e in setup_entries)
    prev_crew_end = 0.0
    blocker_seg_idx = -1
    blocker_abs_start = 0.0
    shifted = 0

    for abs_start, duration, seg_idx in setup_entries:
        planning_checkpoint()
        seg = segments[seg_idx]

        if abs_start < crew_free_at - 0.01:
            # Overlap detected — resolve bidirectionally
            pulled = False
            if blocker_seg_idx >= 0:
                is_full, blocker_abs_start, new_crew_free = _try_pull_back(
                    segments,
                    blocker_seg_idx,
                    blocker_abs_start,
                    prev_crew_end,
                    crew_free_at - abs_start,
                    config,
                )
                if new_crew_free > 0:
                    crew_free_at = new_crew_free
                    pulled = is_full

            if pulled:
                crew_free_at = abs_start + duration
                blocker_seg_idx = seg_idx
                blocker_abs_start = abs_start
                shifted += 1
            else:
                pushed = _push_forward(
                    seg,
                    crew_free_at,
                    abs_start,
                    duration,
                    config,
                    hols,
                )
                if pushed:
                    # Update tracking only for same-day pushes (not day-overflow)
                    new_abs_start = segment_abs(seg, config)[0]
                    if new_abs_start >= abs_start:
                        crew_free_at = new_abs_start + duration
                        prev_crew_end = (
                            blocker_abs_start + segments[blocker_seg_idx].setup_min
                            if blocker_seg_idx >= 0
                            else 0.0
                        )
                        blocker_seg_idx = seg_idx
                        blocker_abs_start = new_abs_start
                    shifted += 1
                else:
                    crew_free_at = abs_start + duration
                    prev_crew_end = (
                        blocker_abs_start + segments[blocker_seg_idx].setup_min
                        if blocker_seg_idx >= 0
                        else 0.0
                    )
                    blocker_seg_idx = seg_idx
                    blocker_abs_start = abs_start
        else:
            prev_crew_end = crew_free_at
            crew_free_at = abs_start + duration
            blocker_seg_idx = seg_idx
            blocker_abs_start = abs_start

    if shifted > 0:
        logger.info("Crew serialization: shifted %d setup segments", shifted)

    return segments


def _serialize_crew_safe(
    segments: list[Segment],
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
    crew_priority: list[str] | None = None,
) -> list[Segment]:
    """EDD-safe serialization independently inside each machine group."""
    groups = sorted(
        {
            (config.machine_groups if config else {}).get(segment.machine_id, "Grandes")
            for segment in segments
            if segment.setup_min > 0
        }
    )
    for group in groups:
        segments = _serialize_crew_safe_group(
            segments,
            config,
            holidays,
            crew_priority,
            group,
        )
    return segments


def _serialize_crew_safe_group(
    segments: list[Segment],
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
    crew_priority: list[str] | None = None,
    group: str = "Grandes",
) -> list[Segment]:
    """EDD-safe per-overlap crew serialization for one group.

    Like _serialize_crew_setups but checks EDD before each fix:
    - Only delays a setup if the new day_idx <= seg.edd
    - Tries BOTH orderings (A-then-B vs B-then-A) for each overlap
    - Skips unfixable overlaps (logs warning)

    Used as fallback when standard serialization causes tardy.
    """
    effective_config = config or FactoryConfig()
    hols = holidays or set()

    prio_map: dict[str, int] = {}
    if crew_priority:
        prio_map = {m: i for i, m in enumerate(crew_priority)}

    # Collect setup intervals (including buffer days)
    setup_entries: list[tuple[float, float, int]] = []
    for idx, seg in enumerate(segments):
        seg_group = (config.machine_groups if config else {}).get(
            seg.machine_id, "Grandes"
        )
        if seg.setup_min > 0 and seg_group == group:
            abs_start = segment_abs(seg, config)[0]
            setup_entries.append((abs_start, seg.setup_min, idx))

    if not setup_entries:
        return segments

    setup_entries.sort(key=lambda e: (e[0], prio_map.get(segments[e[2]].machine_id, 99)))
    capacity = _setup_group_capacity(config, group)

    if capacity > 1:
        crew_free_times = [min(e[0] for e in setup_entries)] * capacity
        fixed = 0
        skipped = 0
        for abs_start, duration, seg_idx in setup_entries:
            seg = segments[seg_idx]
            crew_index = min(range(capacity), key=crew_free_times.__getitem__)
            crew_free_at = crew_free_times[crew_index]
            if abs_start < crew_free_at - 0.01:
                if int(crew_free_at - abs_start + 0.5) < 1:
                    crew_free_times[crew_index] = abs_start + duration
                    continue
                seg_duration = seg.end_min - seg.start_min
                slot = _shift_slot_at_or_after(
                    crew_free_at,
                    seg_duration,
                    effective_config,
                    hols,
                )
                if slot is not None and slot[0] <= seg.edd:
                    seg.day_idx, seg.start_min, seg.shift = slot
                    seg.end_min = seg.start_min + seg_duration
                    crew_free_times[crew_index] = (
                        segment_abs(seg, config)[0] + duration
                    )
                    fixed += 1
                    continue
                skipped += 1
            crew_free_times[crew_index] = max(
                crew_free_times[crew_index],
                abs_start + duration,
            )
        if fixed > 0:
            logger.info(
                "Safe crew serialization for %s: fixed %d, skipped %d overlaps",
                group,
                fixed,
                skipped,
            )
        return segments

    # Initialize before earliest setup (handles buffer days with negative abs_times)
    crew_free_at = min(e[0] for e in setup_entries)
    crew_machine = ""
    fixed = 0
    skipped = 0

    for abs_start, duration, seg_idx in setup_entries:
        planning_checkpoint()
        seg = segments[seg_idx]

        if abs_start < crew_free_at - 0.01 and seg.machine_id != crew_machine:
            delay = int(crew_free_at - abs_start + 0.5)

            if delay < 1:
                crew_free_at = abs_start + duration
                crew_machine = seg.machine_id
                continue

            seg_duration = seg.end_min - seg.start_min
            old_day = seg.day_idx
            slot = _shift_slot_at_or_after(
                crew_free_at,
                seg_duration,
                effective_config,
                hols,
            )
            if slot is not None and slot[0] <= seg.edd:
                seg.day_idx, seg.start_min, seg.shift = slot
                seg.end_min = seg.start_min + seg_duration
                fixed += 1
                if seg.day_idx == old_day:
                    crew_free_at = segment_abs(seg, config)[0] + duration
                    crew_machine = seg.machine_id
                continue

            # Can't fix without exceeding EDD — skip this overlap
            skipped += 1
            logger.warning(
                "Crew overlap unfixable (EDD %d): %s day %d delay %d min",
                seg.edd,
                seg.machine_id,
                seg.day_idx,
                delay,
            )

        # Update tracking
        if abs_start + duration > crew_free_at:
            crew_free_at = abs_start + duration
            crew_machine = seg.machine_id

    if fixed > 0:
        logger.info("Safe crew serialization: fixed %d, skipped %d overlaps", fixed, skipped)

    return segments


@measured("scheduling")
def schedule_all(
    data: EngineData,
    audit: bool = False,
    config: FactoryConfig | None = None,
    crew_priority: list[str] | None = None,
) -> ScheduleResult:
    """Run the full scheduling pipeline."""
    t0 = time.perf_counter()

    if config is None:
        config = FactoryConfig()

    apply_effective_planning_config(data, config)

    journal = Journal()

    audit_logger = None
    if audit:
        from backend.audit.logger import AuditLogger

        audit_logger = AuditLogger()

    # Guardian: validate input
    journal.phase_start("guardian")
    source_data = data
    guard = validate_input(data, config)
    planning_checkpoint()
    if guard.dropped_ops:
        journal.log(
            "guardian",
            "warn",
            f"Dropped {len(guard.dropped_ops)} ops: {', '.join(guard.dropped_ops[:5])}",
        )
    journal.phase_end(
        "guardian",
        f"{len(guard.issues)} issues, {len(guard.dropped_ops)} dropped",
        n_issues=len(guard.issues),
    )
    data = guard.cleaned

    # Phase 1: EOps → Lots
    journal.phase_start("lot_sizing")
    lots = create_lots(data, config=config)
    planning_checkpoint()
    journal.phase_end(
        "lot_sizing",
        f"{len(lots)} lots from {len(data.ops)} ops",
        n_lots=len(lots),
        n_ops=len(data.ops),
    )
    logger.info("Phase 1: %d lots from %d ops", len(lots), len(data.ops))

    if not lots:
        assert_plan_valid([], source_data, config, lots=[])
        score = compute_score([], [], source_data, config=config)
        return ScheduleResult(
            segments=[],
            lots=[],
            score=score,
            time_ms=0.0,
            warnings=journal.to_warnings(),
            operator_alerts=[],
            journal=journal.to_dicts(),
            gate_report=build_gate_report([], [], score, source_data, config),
        )

    global_holidays = calendar_holidays(data, -14, data.n_days + 30)

    # Phase 2: Lots → ToolRuns
    journal.phase_start("tool_grouping")
    runs = create_tool_runs(
        lots,
        audit_logger=audit_logger,
        config=config,
        release_holidays=global_holidays,
    )
    journal.phase_end("tool_grouping", f"{len(runs)} runs from {len(lots)} lots", n_runs=len(runs))
    logger.info("Phase 2: %d tool runs (vs %d lots)", len(runs), len(lots))

    # Auto buffer: detect per-machine capacity infeasibility with holidays
    journal.phase_start("dispatch")
    machine_runs = assign_machines(runs, data, audit_logger=audit_logger, config=config)
    planning_checkpoint()
    buffer_days = (
        _detect_buffer_need(
            runs,
            config=config,
            machine_runs=machine_runs,
            holidays=global_holidays,
        )
        if config.auto_buffer and not config.global_jit_enabled
        else 0
    )
    if buffer_days > 0:
        logger.info("Auto buffer: +%d day(s) for infeasible early runs", buffer_days)
        _apply_buffer(runs, buffer_days)
        data = _shift_engine_data(data, buffer_days)
        global_holidays = set(data.holidays) if data.holidays else set()
        # Re-assign with shifted EDDs
        machine_runs = assign_machines(runs, data, audit_logger=audit_logger, config=config)

    # Phase 3: Sequence + Allocate
    machine_runs = sequence_per_machine(
        machine_runs, audit_logger=audit_logger, config=config, holidays=global_holidays or None
    )
    baseline_segments, baseline_lots, warnings = per_machine_dispatch(
        machine_runs, data, config=config
    )
    planning_checkpoint()
    journal.phase_end(
        "dispatch", f"{len(baseline_segments)} segments", n_segments=len(baseline_segments)
    )
    logger.info("Phase 3: %d segments, %d warnings", len(baseline_segments), len(warnings))

    # Baseline score
    baseline_score = compute_score(
        baseline_segments,
        baseline_lots,
        data,
        config=config,
        include_operational_audit=False,
    )
    logger.info(
        "Baseline: OTD=%.1f%%, OTD-D=%.1f%%, setups=%d, tardy=%d/%d",
        baseline_score["otd"],
        baseline_score["otd_d"],
        baseline_score["setups"],
        baseline_score["tardy_count"],
        baseline_score["total_lots"],
    )

    # Phase 4: fixed JIT re-dispatch as late as possible. The mandatory
    # five-workday floor is anchored to customer delivery for normal output
    # and to planned subcontract dispatch for subcontracted output.
    journal.phase_start("jit")
    jit_machine_runs = None
    jit_gates = None
    jit_diagnostics = None
    _phase4_dispatch = jit_dispatch
    if config.jit_enabled:
        (
            final_segments,
            final_lots,
            jit_warnings,
            jit_machine_runs,
            jit_gates,
            jit_diagnostics,
        ) = _phase4_dispatch(
            runs,
            data,
            baseline_segments,
            baseline_lots,
            baseline_score,
            audit_logger=audit_logger,
            config=config,
        )
        warnings.extend(jit_warnings)
        planning_checkpoint()
        journal.phase_end("jit", f"JIT applied, {len(final_segments)} segments")
    else:
        final_segments = baseline_segments
        final_lots = baseline_lots
        warnings.append("JIT disabled by invalid configuration")
        journal.log("jit", "warn", "JIT disabled by invalid configuration")
        journal.phase_end("jit", "JIT skipped")

    # Phase 4b: VNS polish (post-JIT)
    if (
        config.vns_enabled
        and jit_machine_runs is not None
        and jit_gates is not None
    ):
        from backend.scheduler.vns import vns_polish

        journal.phase_start("vns")
        jit_score = compute_score(
            final_segments,
            final_lots,
            data,
            config=config,
            include_operational_audit=False,
        )
        vns_segs, vns_lots, vns_score, vns_warnings = vns_polish(
            jit_machine_runs,
            jit_gates,
            data,
            config,
            final_segments,
            final_lots,
            jit_score,
        )
        planning_checkpoint()
        vns_candidate_valid = True
        try:
            assert_plan_valid(vns_segs, data, config, lots=vns_lots)
        except PlanValidationError as exc:
            vns_candidate_valid = False
            vns_warnings.append(
                "VNS descartado: o candidato não conservava integralmente "
                f"a produção ({len(exc.violations)} conflito(s))."
            )
        vns_latest_start_gap = float(vns_score.get("latest_start_gap_avg_min", 0.0) or 0.0)
        jit_latest_start_gap = float(jit_score.get("latest_start_gap_avg_min", 0.0) or 0.0)
        if vns_candidate_valid and (
            delivery_improves(vns_score, jit_score)
            or (
                delivery_not_worse(vns_score, jit_score)
                and (
                    vns_latest_start_gap > jit_latest_start_gap
                    or (
                        vns_latest_start_gap == jit_latest_start_gap
                        and vns_score["setups"] < jit_score["setups"]
                    )
                )
            )
        ):
            final_segments = vns_segs
            final_lots = vns_lots
        warnings.extend(vns_warnings)
        journal.phase_end(
            "vns",
            f"VNS: setups={vns_score['setups']}, earliness={vns_score['earliness_avg_days']:.1f}d",
        )

    # Un-shift buffer if applied
    if buffer_days > 0:
        final_segments = _unshift_segments(final_segments, buffer_days)
        final_lots = _unshift_lots(final_lots, buffer_days)
        # Restore original n_days for scoring
        data = _shift_engine_data(data, -buffer_days)

    # Fix any overlapping segments (from buffer unshift or dispatch edge cases)
    global_holidays = set(getattr(data, "holidays", []))
    final_segments = _fix_day_overlaps(final_segments, config, holidays=global_holidays)

    # Crew mutex: serialize setups across machines (single setup operator)
    # Iterate: serialize → fix overlaps → sanitize → re-serialize (each step can create new issues)
    import copy

    pre_crew_score = compute_score(
        final_segments,
        final_lots,
        data,
        config=config,
        include_operational_audit=False,
    )
    crew_segments = copy.deepcopy(final_segments)
    prev_hash = None
    for _crew_pass in range(10):  # max 10 passes with early exit on convergence
        planning_checkpoint()
        crew_segments = _serialize_crew_setups(
            crew_segments, config, holidays=global_holidays, crew_priority=crew_priority
        )
        crew_segments = _fix_day_overlaps(crew_segments, config, holidays=global_holidays)
        crew_segments = _sanitize_segments(
            crew_segments, config, holidays=global_holidays, lots=final_lots
        )
        curr_hash = hash(
            tuple((s.lot_id, s.day_idx, s.start_min, s.end_min) for s in crew_segments)
        )
        if curr_hash == prev_hash:
            break
        prev_hash = curr_hash
    crew_score = compute_score(
        crew_segments,
        final_lots,
        data,
        config=config,
        include_operational_audit=False,
    )
    if delivery_not_worse(crew_score, pre_crew_score):
        final_segments = crew_segments
        logger.info("Crew serialization applied: no delivery-priority regression")
    else:
        # Standard serialization causes tardy — try EDD-safe per-overlap fallback
        logger.info(
            "Crew serialization caused tardy %d > %d, trying EDD-safe fallback",
            crew_score["tardy_count"],
            pre_crew_score["tardy_count"],
        )
        safe_segments = copy.deepcopy(final_segments)
        prev_hash_safe = None
        for _ in range(10):
            planning_checkpoint()
            safe_segments = _serialize_crew_safe(
                safe_segments, config, holidays=global_holidays, crew_priority=crew_priority
            )
            safe_segments = _fix_day_overlaps(safe_segments, config, holidays=global_holidays)
            safe_segments = _sanitize_segments(
                safe_segments, config, holidays=global_holidays, lots=final_lots
            )
            curr_hash_safe = hash(
                tuple((s.lot_id, s.day_idx, s.start_min, s.end_min) for s in safe_segments)
            )
            if curr_hash_safe == prev_hash_safe:
                break
            prev_hash_safe = curr_hash_safe
        safe_score = compute_score(
            safe_segments,
            final_lots,
            data,
            config=config,
            include_operational_audit=False,
        )
        if delivery_not_worse(safe_score, pre_crew_score):
            final_segments = safe_segments
            logger.info("EDD-safe crew serialization applied: no delivery-priority regression")
        else:
            logger.warning(
                "Crew serialization skipped: both strategies cause tardy (std=%d, safe=%d, pre=%d)",
                crew_score["tardy_count"],
                safe_score["tardy_count"],
                pre_crew_score["tardy_count"],
            )
            warnings.append(
                "Crew serialization limited: "
                f"{safe_score['tardy_count']} tardy vs "
                f"{pre_crew_score['tardy_count']} pre-crew"
            )

    # Tool contention: a physical tool cannot run on two machines at once.
    # JIT/VNS dispatch each machine with an isolated tool timeline, so a global
    # repair pass is needed here. OTD-guarded — never defers into tardiness.
    tc_pre_score = compute_score(
        final_segments,
        final_lots,
        data,
        config=config,
        include_operational_audit=False,
    )
    tc_segments = copy.deepcopy(final_segments)
    tc_segments = _fix_tool_machine_overlaps(tc_segments, config, holidays=global_holidays)
    tc_segments = _fix_day_overlaps(tc_segments, config, holidays=global_holidays)
    tc_score = compute_score(
        tc_segments,
        final_lots,
        data,
        config=config,
        include_operational_audit=False,
    )
    if delivery_not_worse(tc_score, tc_pre_score):
        final_segments = tc_segments
    else:
        logger.warning(
            "Tool contention fix skipped: would cause tardy %d > %d",
            tc_score["tardy_count"],
            tc_pre_score["tardy_count"],
        )

    # Setup groups are independent resources. After JIT/tool repair, some
    # setup-starting runs can be pulled into idle time on their own machine,
    # allowing Grandes and Médias to prepare in parallel without changing
    # sequence, quantities or machines.
    setup_pre_score = compute_score(
        final_segments,
        final_lots,
        data,
        config=config,
        include_operational_audit=False,
    )
    setup_pre_conflicts = len(_detect_tool_machine_overlaps(final_segments, config))
    setup_segments = copy.deepcopy(final_segments)
    setup_segments = _parallelize_independent_setup_starts(
        setup_segments,
        config,
        holidays=global_holidays,
    )
    setup_segments = _fix_day_overlaps(setup_segments, config, holidays=global_holidays)
    setup_segments = _sanitize_segments(
        setup_segments, config, holidays=global_holidays, lots=final_lots
    )
    setup_segments = _fix_orphan_continuations(setup_segments)
    setup_score = compute_score(
        setup_segments,
        final_lots,
        data,
        config=config,
        include_operational_audit=False,
    )
    setup_conflicts = len(_detect_tool_machine_overlaps(setup_segments, config))
    if _accept_setup_parallelization(
        setup_pre_score,
        setup_score,
        before_tool_conflicts=setup_pre_conflicts,
        after_tool_conflicts=setup_conflicts,
    ):
        final_segments = setup_segments
    else:
        logger.warning(
            "Setup parallelization reverted: delivery_not_worse=%s, hard %d>%d, "
            "JIT %d>%d, conflicts %d>%d",
            delivery_not_worse(setup_score, setup_pre_score),
            setup_score["hard_violations"],
            setup_pre_score["hard_violations"],
            setup_score["early_window_violations"],
            setup_pre_score["early_window_violations"],
            setup_conflicts,
            setup_pre_conflicts,
        )

    # Final sanitize: enforce shift bounds + fix ghost segments
    final_segments = _sanitize_segments(
        final_segments, config, holidays=global_holidays, lots=final_lots
    )
    # Fix orphan continuations (segments wrongly marked as continuation by _fix_day_overlaps)
    final_segments = _fix_orphan_continuations(final_segments)

    # Material-release splitting can leave consecutive runs for a tool that is
    # still mounted.  Remove those non-physical setups before compaction so the
    # newly freed machine time can be used by the following production.
    final_segments = _remove_redundant_retained_tool_setups(
        final_segments,
        protected_lot_ids=set(data.preserved_lot_proofs),
    )

    # ``compact_enabled`` remains serializable for old plans. The historical
    # compactor is deliberately no longer chained here: the canonical
    # normalizer below covers legal gap filling and priority repair with the
    # same resource evaluator used by validation and explainability.

    # Final physical repair. This is not OTD-guarded: a plan that is late is
    # acceptable to show as late; a plan that uses the same tool twice or runs
    # during a declared stop is not acceptable to show at all.
    final_segments = _repair_hard_constraints(final_segments, data, config, global_holidays)
    final_segments = _fix_orphan_continuations(final_segments)
    final_segments = normalize_earliest_legal_plan(
        final_segments,
        final_lots,
        data,
        config,
        annotate=False,
    )

    # The canonical normalizer intentionally preserves machine assignment. A
    # time-limited global solve can therefore leave a late run on a machine
    # whose new calendar pushed it out, even when its eligible alternative has
    # a validated on-time slot. Search that missing neighbourhood before the
    # final immutable audit snapshot is built.
    from backend.scheduler.alternative_repair import (
        repair_alternative_machine_delivery,
    )

    closeout_reserve_s = 8.0
    alternative_repair = None
    remaining = remaining_time()
    if remaining is None:
        alternative_repair = repair_alternative_machine_delivery(
            final_segments,
            final_lots,
            data,
            config,
            runs=runs,
        )
    elif remaining > closeout_reserve_s:
        try:
            with planning_scope(timeout_s=remaining - closeout_reserve_s):
                alternative_repair = repair_alternative_machine_delivery(
                    final_segments,
                    final_lots,
                    data,
                    config,
                    runs=runs,
                )
        except PlanningTimeout:
            planning_checkpoint()
            alternative_repair = None
            warnings.append(
                "Pesquisa opcional de máquinas alternativas interrompida para "
                "conservar o candidato físico completo."
            )
    else:
        warnings.append(
            "Pesquisa opcional de máquinas alternativas omitida para validar "
            "o candidato dentro do tempo disponível."
        )
    planning_checkpoint()
    improvement_report: dict | None = None
    if alternative_repair is not None and alternative_repair.moves:
        final_segments = alternative_repair.segments
        final_lots = alternative_repair.lots
        warnings.append(
            "Máquinas alternativas: "
            f"{len(alternative_repair.moves)} reparação(ões) de entrega validada(s)."
        )
    if alternative_repair is not None:
        from backend.scheduler.improvement import record_verified

        improvement_report = record_verified(
            None, "alternative_machine", final_segments, final_lots,
        )

    from backend.scheduler.campaign_tail import (
        campaign_tail_warnings,
        repair_short_runs_after_merged_campaigns,
    )

    campaign_tail = None
    remaining = remaining_time()
    if remaining is None:
        campaign_tail = repair_short_runs_after_merged_campaigns(
            final_segments,
            final_lots,
            data,
            config,
        )
    elif remaining > closeout_reserve_s:
        try:
            with planning_scope(timeout_s=remaining - closeout_reserve_s):
                campaign_tail = repair_short_runs_after_merged_campaigns(
                    final_segments,
                    final_lots,
                    data,
                    config,
                )
        except PlanningTimeout:
            planning_checkpoint()
            campaign_tail = None
            warnings.append(
                "Ajuste opcional de fim de campanha interrompido para conservar "
                "o candidato físico completo."
            )
    planning_checkpoint()
    if campaign_tail is not None and campaign_tail.moves:
        final_segments = campaign_tail.segments
        warnings.extend(campaign_tail_warnings(campaign_tail))

    # Alternative-machine and campaign-tail repairs run after the canonical
    # close-out and can expose fresh idle slots elsewhere in the plan. Close
    # those actionable gaps before taking the immutable audit snapshot. The
    # normalizer deliberately preserves configured campaign-tail exceptions.
    if (
        alternative_repair is not None
        and alternative_repair.moves
    ) or (
        campaign_tail is not None
        and campaign_tail.moves
    ):
        final_segments = normalize_earliest_legal_plan(
            final_segments,
            final_lots,
            data,
            config,
            annotate=False,
        )

    # The canonical normalizer cannot insert a new setup. Search the bounded
    # cross-shift exchange separately, then publish it only if the complete
    # candidate is executable and finishes a postponed lot a day earlier.
    from backend.scheduler.shift_exchange import repair_shift_capacity_exchange

    remaining = remaining_time()
    if remaining is None:
        exchanged = repair_shift_capacity_exchange(
            final_segments, final_lots, data, config,
        )
    elif remaining > closeout_reserve_s:
        try:
            with planning_scope(timeout_s=remaining - closeout_reserve_s):
                exchanged = repair_shift_capacity_exchange(
                    final_segments, final_lots, data, config,
                )
        except PlanningTimeout:
            planning_checkpoint()
            exchanged = final_segments
    else:
        exchanged = final_segments
    if exchanged is not final_segments:
        final_segments = exchanged
        warnings.append(
            "Troca entre turnos: um lote interrompido foi concluído mais cedo "
            "com setup de reinstalação validado."
        )

    # Late alternative, campaign and shift repairs may split a retained-tool
    # run after the earlier cleanup. Keep historical proof-bound lots intact.
    setup_before_cleanup = sum(segment.setup_min for segment in final_segments)
    final_segments = _remove_redundant_retained_tool_setups(
        final_segments,
        protected_lot_ids=set(data.preserved_lot_proofs),
    )
    if sum(segment.setup_min for segment in final_segments) < setup_before_cleanup:
        # This late cleanup changes the physical duration. Close the released
        # interval before auditing the final candidate, as earlier passes do.
        protected = set(data.preserved_lot_proofs)
        historical_signature = _segment_schedule_signature(
            [segment for segment in final_segments if segment.lot_id in protected]
        )
        normalized = normalize_earliest_legal_plan(
            final_segments,
            final_lots,
            data,
            config,
            annotate=False,
            protected_lot_ids=protected,
        )
        if _segment_schedule_signature(
            [segment for segment in normalized if segment.lot_id in protected]
        ) == historical_signature:
            final_segments = normalized

    # Explainability, score and the application gate share one immutable audit
    # snapshot. This avoids repeating the expensive legal-interval search and
    # prevents those public surfaces from disagreeing about the same plan.
    final_gap_opportunities = actionable_gap_opportunities(
        final_segments,
        final_lots,
        data,
        config,
    )
    planning_checkpoint()
    from backend.scheduler.explainability import annotate_left_shift_blockers

    annotate_left_shift_blockers(
        final_segments,
        final_lots,
        data,
        config,
        gap_opportunities=final_gap_opportunities,
    )

    # Verification: no physical tool may be on two machines simultaneously.
    tool_conflicts = _detect_tool_machine_overlaps(final_segments, config)
    if tool_conflicts:
        for tool_id, ma, mb, day in tool_conflicts[:5]:
            logger.warning(
                "Tool contention: tool %s on %s and %s simultaneously (day %d)",
                tool_id,
                ma,
                mb,
                day,
            )
        warnings.append(
            f"Tool contention: {len(tool_conflicts)} same-tool cross-machine overlap(s)"
        )
        journal.log(
            "scoring",
            "warn",
            f"{len(tool_conflicts)} same-tool cross-machine overlap(s) remain",
        )

    # Phase 5: Final scoring
    journal.phase_start("scoring")
    final_operational_audit = build_operational_audit(
        final_segments,
        final_lots,
        data,
        config,
        gap_opportunities=final_gap_opportunities,
    )
    score = compute_score(
        final_segments,
        final_lots,
        data,
        config=config,
        operational_audit=final_operational_audit,
    )
    score["buffer_days"] = buffer_days
    journal.phase_end(
        "scoring",
        f"OTD={score['otd']:.1f}%, tardy={score['tardy_count']}",
        **{k: v for k, v in score.items() if isinstance(v, (int, float))},
    )
    logger.info(
        "Final: OTD=%.1f%%, OTD-D=%.1f%%, setups=%d, tardy=%d/%d, earliness=%.1fd",
        score["otd"],
        score["otd_d"],
        score["setups"],
        score["tardy_count"],
        score["total_lots"],
        score["earliness_avg_days"],
    )

    # The average remains diagnostic inside the hard material-release floor.
    from backend.scheduler.window import effective_earliness_target

    earliness_target = effective_earliness_target(config)
    if score["earliness_avg_days"] > earliness_target:
        warnings.append(
            f"Aviso: antecipação média {score['earliness_avg_days']:.1f}d "
            f"> objetivo {earliness_target:.1f}d"
        )
        journal.log(
            "scoring",
            "warn",
            f"Earliness {score['earliness_avg_days']:.1f}d exceeds target {earliness_target:.1f}d",
        )

    try:
        assert_plan_valid(final_segments, data, config, lots=final_lots)
    except PlanValidationError as exc:
        logger.error("Final plan validation failed: %s", exc.violations)
        raise
    planning_checkpoint()

    # Guardian: validate output
    out_issues = validate_output(final_segments, data)
    for issue in out_issues:
        journal.log("guardian_output", "warn", issue.message, op_id=issue.op_id, field=issue.field)

    # Operator alerts
    alerts = compute_operator_alerts(final_segments, data, config=config)
    if alerts:
        logger.info("Operator alerts: %d", len(alerts))

    elapsed = (time.perf_counter() - t0) * 1000

    trail = audit_logger.get_trail() if audit_logger else None

    # Merge journal warnings into warnings list
    warnings.extend(journal.to_warnings())
    gate_report = build_gate_report(
        final_segments,
        final_lots,
        score,
        data,
        config,
        operational_audit=final_operational_audit,
    )
    if gate_report["metrics"].get("early_window_violations", 0):
        warnings.append(
            "Exceção necessária: há produções iniciadas antes da libertação "
            "de material (entrega ao cliente ou envio para subcontratação)."
        )
    if gate_report["metrics"].get("long_productions", 0):
        warnings.append(
            "Exceção necessária: há produções com mais de quatro dias úteis."
        )
    if jit_diagnostics:
        gate_report["solver_status"] = jit_diagnostics.get("solver_status")
        gate_report["feasibility"] = jit_diagnostics.get("feasibility")

    return ScheduleResult(
        segments=final_segments,
        lots=final_lots,
        score=score,
        time_ms=round(elapsed, 1),
        warnings=warnings,
        operator_alerts=alerts,
        audit_trail=trail,
        journal=journal.to_dicts(),
        gate_report=gate_report,
        solver_status=(jit_diagnostics or {}).get("solver_status"),
        feasibility=(jit_diagnostics or {}).get("feasibility"),
        improvement_report=improvement_report,
    )
