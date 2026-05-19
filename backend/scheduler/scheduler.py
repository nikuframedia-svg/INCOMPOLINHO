"""Scheduler entry point — Spec 02 v6 §9.

Pipeline:
  Phase 1: lot_sizing      — EOps → Lots (eco lot + twins + min prod_min)
  Phase 2: tool_grouping   — Lots → ToolRuns (group + split + EDD sort)
  Phase 3: dispatch         — assign + sequence + allocate segments
  Phase 4: jit              — LST-gated re-dispatch (safety: fallback)
  Phase 5: scoring          — OTD, OTD-D, setups, earliness, utilisation
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from backend.scheduler.constants import DAY_CAP
from backend.config.types import FactoryConfig
from backend.guardian.guardian import validate_input, validate_output
from backend.journal.journal import Journal
from backend.scheduler.dispatch import (
    assign_machines,
    per_machine_dispatch,
    sequence_per_machine,
)
from backend.scheduler.jit import jit_dispatch
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.operators import compute_operator_alerts
from backend.scheduler.scoring import compute_score
from backend.scheduler.tool_grouping import create_tool_runs
from backend.scheduler.types import Lot, ScheduleResult, Segment, ToolRun
from backend.types import EngineData

logger = logging.getLogger(__name__)


def _detect_buffer_need(
    runs: list[ToolRun],
    config: FactoryConfig | None = None,
    machine_runs: dict[str, list[ToolRun]] | None = None,
    holidays: set[int] | None = None,
) -> int:
    """Return number of buffer days needed so no machine has infeasible early load.

    For each machine, simulates strict-EDD dispatch accounting for holidays.
    If any run completes after its EDD, computes how many extra days are needed.
    Falls back to simple edd=0 check when machine_runs not provided.
    """
    import math
    day_cap = config.day_capacity_min if config else DAY_CAP
    hols = holidays or set()

    if machine_runs:
        max_buffer = 0
        for m_id, m_runs in machine_runs.items():
            sorted_runs = sorted(m_runs, key=lambda r: r.edd)
            abs_min = 0.0
            for run in sorted_runs:
                # Snap to workday
                day = int(abs_min) // day_cap
                while day in hols:
                    day += 1
                    abs_min = float(day * day_cap)

                remaining = run.total_min
                while remaining > 0.01:
                    day = int(abs_min) // day_cap
                    while day in hols:
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
    """Shift all run and lot EDDs forward by buffer_days."""
    for run in runs:
        run.edd += buffer_days
        for lot in run.lots:
            lot.edd += buffer_days


def _shift_engine_data(data: EngineData, buffer_days: int) -> EngineData:
    """Return a copy of EngineData with n_days increased and holidays/blocked days shifted."""
    import copy
    shifted = copy.copy(data)
    shifted.n_days = data.n_days + buffer_days
    if hasattr(data, "holidays") and data.holidays:
        shifted.holidays = [h + buffer_days for h in data.holidays]
    if getattr(data, "machine_blocked_days", None):
        shifted.machine_blocked_days = {
            m: {d + buffer_days for d in days}
            for m, days in data.machine_blocked_days.items()
        }
    if getattr(data, "tool_blocked_days", None):
        shifted.tool_blocked_days = {
            t: {d + buffer_days for d in days}
            for t, days in data.tool_blocked_days.items()
        }
    return shifted


def _unshift_segments(segments: list[Segment], buffer_days: int) -> list[Segment]:
    """Shift segment day_idx and edd back by buffer_days.

    Buffer-day production keeps negative day_idx (e.g. day -1) so the
    Gantt can display it truthfully instead of cramming into day 0.
    """
    for seg in segments:
        seg.day_idx = seg.day_idx - buffer_days
        seg.edd -= buffer_days
    return segments


def _unshift_lots(lots: list[Lot], buffer_days: int) -> list[Lot]:
    """Shift lot EDDs back by buffer_days."""
    for lot in lots:
        lot.edd -= buffer_days
    return lots


def _next_workday(day: int, holidays: set[int]) -> int:
    """Return next day that is not a holiday."""
    d = day
    while d in holidays:
        d += 1
    return d


def _fix_day_overlaps(segments: list[Segment], config: FactoryConfig | None = None, holidays: set[int] | None = None) -> list[Segment]:
    """Fix overlapping segments on same machine/day after buffer unshift.

    Per machine: sort all segments by (day_idx, start_min), then sequentially
    ensure each segment starts after the previous one ends. Segments that
    overflow past shift_b_end are pushed to the next workday (skipping holidays).
    """
    shift_a_start = config.shift_a_start if config else 420
    shift_b_end = config.shift_b_end if config else 1440
    hols = holidays or set()

    by_machine: defaultdict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        by_machine[seg.machine_id].append(seg)

    for machine_id, segs in by_machine.items():
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
                    # EDD guard: never cause tardy by moving to next day
                    if new_day > curr.edd:
                        if prev.end_min < shift_b_end:
                            curr.start_min = prev.end_min
                            curr.end_min = shift_b_end
                        else:
                            # No space left — keep zero-duration placeholder to preserve EDD
                            curr.start_min = shift_b_end
                            curr.end_min = shift_b_end
                        continue
                    # Safe to move to next workday
                    curr.day_idx = new_day
                    curr.start_min = shift_a_start
                    curr.end_min = min(shift_a_start + duration, shift_b_end)
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
                        if new_day > curr.edd:
                            if prev.end_min < shift_b_end:
                                curr.start_min = prev.end_min
                                curr.end_min = shift_b_end
                            else:
                                curr.start_min = shift_b_end
                                curr.end_min = shift_b_end
                            continue
                        curr.day_idx = new_day
                        curr.start_min = shift_a_start
                        curr.end_min = min(shift_a_start + duration, shift_b_end)
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
    shift_b_end: int,
    day_cap: int,
    holidays: set[int],
) -> bool:
    """Try to move a truncated segment to an earlier day with free capacity.

    Searches backward from seg.edd. Checks both total capacity AND that
    the segment fits within shift bounds (existing_end + needed <= shift_b_end).
    Does NOT check crew availability — caller should log a warning.
    """
    needed = seg.prod_min + seg.setup_min
    machine = seg.machine_id
    for candidate_day in range(seg.edd, -2, -1):
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
        # Guard: segment must fit within shift bounds
        if existing_end + int(round(needed)) > shift_b_end:
            continue
        # Tool contention: the same physical tool must not be on another
        # machine during the candidate slot.
        new_start_abs = candidate_day * day_cap + (existing_end - shift_a_start)
        new_end_abs = new_start_abs + needed
        conflict = False
        for other in all_segments:
            if (other is not seg
                    and other.tool_id == seg.tool_id
                    and other.machine_id != machine):
                o_start = other.day_idx * day_cap + (other.start_min - shift_a_start)
                o_end = other.day_idx * day_cap + (other.end_min - shift_a_start)
                if new_start_abs < o_end and o_start < new_end_abs:
                    conflict = True
                    break
        if conflict:
            continue
        old_day = seg.day_idx
        seg.day_idx = candidate_day
        seg.start_min = existing_end
        seg.end_min = existing_end + int(round(needed))
        seg.shift = "A" if seg.start_min < 930 else "B"
        used[(machine, candidate_day)] = day_used + needed
        old_key = (machine, old_day)
        if old_key in used:
            used[old_key] = max(0, used[old_key] - needed)
        logger.info(
            "Relocated truncated segment %s to day %d (was day %d, %s, crew overlap possible)",
            seg.lot_id, candidate_day, old_day, machine,
        )
        return True
    return False


def _sanitize_segments(
    segments: list[Segment],
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
) -> list[Segment]:
    """Final safety net: enforce shift bounds and fix ghost segments.

    Pass 1: existing logic — remove inverted, clamp start, cap end.
    Pass 2: detect ghost segments (duration < prod_min + setup_min) and
             try to relocate to an earlier day with capacity, or truncate
             proportionally, or remove if degenerate.
    """
    shift_a_start = config.shift_a_start if config else 420
    shift_b_end = config.shift_b_end if config else 1440
    day_cap = config.day_capacity_min if config else 1020
    hols = holidays or set()

    # Pass 1: clamp bounds
    result: list[Segment] = []
    for seg in segments:
        if seg.start_min > seg.end_min:
            continue
        if seg.start_min < shift_a_start:
            seg.start_min = shift_a_start
        if seg.end_min > shift_b_end:
            seg.end_min = shift_b_end
        result.append(seg)

    removed_pass1 = len(segments) - len(result)

    # Pass 2: fix ghost segments (duration < prod_min + setup_min)
    used: dict[tuple[str, int], float] = {}
    for seg in result:
        key = (seg.machine_id, seg.day_idx)
        dur = max(0, seg.end_min - seg.start_min)
        used[key] = used.get(key, 0) + dur

    final: list[Segment] = []
    for seg in result:
        actual_duration = seg.end_min - seg.start_min
        needed = seg.prod_min + seg.setup_min

        if actual_duration < needed - 1.0 and needed > 1.0:
            # Ghost segment: try to relocate to earlier day
            if _try_relocate_truncated(seg, result, used, shift_a_start, shift_b_end, day_cap, hols):
                final.append(seg)
                continue

            # Can't relocate — remove if degenerate, else truncate proportionally
            if actual_duration < 1.0:
                logger.warning(
                    "Removed ghost segment %s day %d (duration=0, needed=%.0f min)",
                    seg.lot_id, seg.day_idx, needed,
                )
                continue

            ratio = actual_duration / needed
            seg.prod_min = seg.prod_min * ratio
            seg.qty = max(0, round(seg.qty * ratio))
            seg.setup_min = seg.setup_min * ratio
            if seg.twin_outputs:
                seg.twin_outputs = [
                    (oid, sku, max(0, round(qty * ratio)))
                    for oid, sku, qty in seg.twin_outputs
                ]

        final.append(seg)

    removed_total = len(segments) - len(final)
    if removed_total > 0:
        logger.info(
            "Sanitize: removed %d segments (%d inverted, %d ghost)",
            removed_total, removed_pass1, removed_total - removed_pass1,
        )
    return final


def _fix_orphan_continuations(segments: list[Segment]) -> list[Segment]:
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
        segs.sort(key=lambda s: (s.day_idx, s.start_min))
        if segs[0].is_continuation:
            segs[0].is_continuation = False
            fixed += 1

    if fixed > 0:
        logger.info("Fixed %d orphan continuations", fixed)

    return segments


def _compact_segments(
    segments: list[Segment],
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
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
    shift_span = shift_b_end - shift_a_start
    hols = holidays or set()

    # Tool bookings from segments on OTHER machines (for cross-machine guard).
    # Built once; a lot only moves within its own machine so other-machine
    # segments are a fixed reference during this pass.
    by_machine: defaultdict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        by_machine[seg.machine_id].append(seg)

    def _tool_busy_other(tool_id: str, machine_id: str, start_abs: float, end_abs: float,
                         own_lot: str) -> bool:
        """True if `tool_id` is used on a different machine during [start, end)."""
        for other in segments:
            if other.lot_id == own_lot:
                continue
            if other.tool_id != tool_id or other.machine_id == machine_id:
                continue
            if other.end_min <= other.start_min:
                continue
            o_start, o_end = _seg_abs(other, shift_a_start, day_cap)
            if start_abs < o_end and o_start < end_abs:
                return True
        return False

    def _next_workday(d: int) -> int:
        while d in hols:
            d += 1
        return d

    moved = 0
    for machine_id, m_segs in by_machine.items():
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
        cursor_day = _next_workday(0)
        cursor_min = shift_a_start

        for lid in lot_order:
            lot_segs = sorted(lots[lid], key=lambda s: (s.day_idx, s.start_min))
            work = [s.end_min - s.start_min for s in lot_segs]
            total_work = sum(w for w in work if w > 0)
            tool_id = lot_segs[0].tool_id
            edd = lot_segs[0].edd

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
                d, s = _next_workday(d0), s0
                if s >= shift_b_end:
                    d = _next_workday(d + 1)
                    s = shift_a_start
                remaining = total_work
                while remaining > 0:
                    if d > edd:
                        return None  # would breach the deadline
                    avail = shift_b_end - s
                    block = min(remaining, avail)
                    seg_start_abs = d * day_cap + (s - shift_a_start)
                    seg_end_abs = seg_start_abs + block
                    if _tool_busy_other(tool_id, machine_id, seg_start_abs,
                                        seg_end_abs, lid):
                        return None  # same tool on another machine
                    blocks.append((d, s, s + block))
                    s += block
                    remaining -= block
                    if remaining > 0:
                        d = _next_workday(d + 1)
                        s = shift_a_start
                return blocks

            # Trial start = machine cursor (earliest free slot on this machine).
            placements = _try_flow(cursor_day, cursor_min)

            current_pos = (lot_segs[0].day_idx, lot_segs[0].start_min)
            if placements is None or (placements[0][0], placements[0][1]) >= current_pos:
                # Cannot improve — keep the lot where it is, advance cursor.
                last = lot_segs[-1]
                if (last.day_idx, last.end_min) > (cursor_day, cursor_min):
                    cursor_day, cursor_min = last.day_idx, last.end_min
                continue

            # Map the re-flowed day-blocks onto the existing Segment objects.
            # prod_min / qty / setup / twin_outputs are redistributed strictly
            # proportionally to block duration so totals are conserved exactly.
            orig_work_segs = [s for s in lot_segs if s.end_min > s.start_min]
            tot_prod = sum(s.prod_min for s in orig_work_segs)
            tot_setup = sum(s.setup_min for s in orig_work_segs)
            tot_qty = sum(s.qty for s in orig_work_segs)
            twin_totals: dict[tuple[str, str], int] = {}
            for s in orig_work_segs:
                for oid, sku, q in (s.twin_outputs or []):
                    twin_totals[(oid, sku)] = twin_totals.get((oid, sku), 0) + q

            template = orig_work_segs[0]
            new_segs: list[Segment] = []
            n_blocks = len(placements)
            prod_acc = 0.0
            setup_acc = 0.0
            qty_acc = 0
            twin_acc: dict[tuple[str, str], int] = {k: 0 for k in twin_totals}
            for k, (d, st, en) in enumerate(placements):
                dur = en - st
                last_block = k == n_blocks - 1
                frac = dur / total_work if total_work else 0.0
                if last_block:
                    p_prod = tot_prod - prod_acc
                    p_setup = tot_setup - setup_acc
                    p_qty = tot_qty - qty_acc
                else:
                    p_prod = tot_prod * frac
                    p_setup = tot_setup * frac
                    p_qty = round(tot_qty * frac)
                prod_acc += p_prod
                setup_acc += p_setup
                qty_acc += p_qty
                twin_out: list[tuple[str, str, int]] | None = None
                if twin_totals:
                    twin_out = []
                    for (oid, sku), tq in twin_totals.items():
                        if last_block:
                            piece = tq - twin_acc[(oid, sku)]
                        else:
                            piece = round(tq * frac)
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
                    twin_outputs=twin_out,
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


def _seg_abs(seg: Segment, shift_a_start: int, day_cap: int) -> tuple[float, float]:
    """Return (start_abs, end_abs) of a segment in absolute scheduling minutes."""
    start_abs = seg.day_idx * day_cap + (seg.start_min - shift_a_start)
    end_abs = seg.day_idx * day_cap + (seg.end_min - shift_a_start)
    return start_abs, end_abs


def _detect_tool_machine_overlaps(
    segments: list[Segment],
    config: FactoryConfig | None = None,
) -> list[tuple[str, str, str, int]]:
    """Find time overlaps of the SAME tool_id on DIFFERENT machines.

    A physical tool (mould) is unique — it can move between machines over time
    but can never run in two machines at once. Returns a list of
    (tool_id, machine_a, machine_b, day_idx) for each conflicting pair.
    """
    shift_a_start = config.shift_a_start if config else 420
    day_cap = config.day_capacity_min if config else DAY_CAP

    by_tool: dict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        if seg.end_min > seg.start_min:  # skip zero-duration placeholders
            by_tool[seg.tool_id].append(seg)

    conflicts: list[tuple[str, str, str, int]] = []
    for tool_id, segs in by_tool.items():
        segs = sorted(segs, key=lambda s: _seg_abs(s, shift_a_start, day_cap)[0])
        for i in range(len(segs)):
            a_start, a_end = _seg_abs(segs[i], shift_a_start, day_cap)
            for j in range(i + 1, len(segs)):
                b_start, b_end = _seg_abs(segs[j], shift_a_start, day_cap)
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
    shift_a_start = config.shift_a_start if config else 420
    shift_b_end = config.shift_b_end if config else 1440
    day_cap = config.day_capacity_min if config else DAY_CAP
    hols = holidays or set()

    fixed = 0
    for _ in range(len(segments) + 1):
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
                key=lambda s: _seg_abs(s, shift_a_start, day_cap)[0],
            )
            for i in range(len(segs)):
                a_start, a_end = _seg_abs(segs[i], shift_a_start, day_cap)
                for j in range(i + 1, len(segs)):
                    b_start, b_end = _seg_abs(segs[j], shift_a_start, day_cap)
                    if b_start >= a_end:
                        break
                    if segs[j].machine_id == segs[i].machine_id:
                        continue
                    # Defer the less-urgent of the two (higher EDD, then later).
                    earlier, later = segs[i], segs[j]
                    if later.edd < earlier.edd:
                        earlier, later = later, earlier
                    e_start, e_end = _seg_abs(earlier, shift_a_start, day_cap)
                    duration = later.end_min - later.start_min
                    # Push `later` to start when `earlier` frees the tool.
                    new_abs = e_end
                    new_day = int(new_abs) // day_cap
                    while new_day in hols:
                        new_day += 1
                    new_start_in_day = shift_a_start + int(
                        round(new_abs - new_day * day_cap)
                    )
                    if new_start_in_day + duration > shift_b_end:
                        new_day += 1
                        while new_day in hols:
                            new_day += 1
                        new_start_in_day = shift_a_start
                    # OTD guard: never make the segment tardy to fix contention.
                    if new_day > later.edd:
                        continue
                    later.day_idx = new_day
                    later.start_min = new_start_in_day
                    later.end_min = new_start_in_day + duration
                    later.shift = "A" if new_start_in_day < 930 else "B"
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


def _find_predecessor_end(segments: list[Segment], target: Segment, shift_a_start: int) -> int:
    """Find the end_min of the latest predecessor on the same machine/day before target."""
    pred_end = shift_a_start
    for other in segments:
        if (other.machine_id == target.machine_id
                and other.day_idx == target.day_idx
                and other.end_min <= target.start_min
                and other.end_min > pred_end):
            pred_end = other.end_min
    return pred_end


def _try_pull_back(
    segments: list[Segment],
    blocker_seg_idx: int,
    blocker_abs_start: float,
    prev_crew_end: float,
    delay_needed: float,
    shift_a_start: int,
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

    new_bstart = bseg.start_min - pull_amount
    pred_end = _find_predecessor_end(segments, bseg, shift_a_start)

    # Limit pull to available intra-machine space
    if new_bstart < pred_end:
        pull_amount = max(0, bseg.start_min - pred_end)
        new_bstart = bseg.start_min - pull_amount

    if pull_amount < 1 or new_bstart < shift_a_start:
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
    duration: float,
    shift_a_start: int,
    shift_b_end: int,
    holidays: set[int],
) -> bool:
    """Push a setup segment forward in time to avoid crew overlap.

    Returns True if segment was shifted.
    """
    new_abs_start = crew_free_at
    delay = int(new_abs_start - abs_start + 0.5)
    if delay < 1:
        return False

    new_start = seg.start_min + delay
    new_end = seg.end_min + delay

    if new_end > shift_b_end:
        # Overflow: move entire segment to next workday
        seg_duration = seg.end_min - seg.start_min
        new_day = seg.day_idx + 1
        while new_day in holidays:
            new_day += 1
        seg.day_idx = new_day
        seg.start_min = shift_a_start
        seg.end_min = shift_a_start + seg_duration
    else:
        seg.start_min = new_start
        seg.end_min = new_end
    return True


def _serialize_crew_setups(
    segments: list[Segment],
    config: FactoryConfig | None = None,
    holidays: set[int] | None = None,
    crew_priority: list[str] | None = None,
) -> list[Segment]:
    """Serialize setups across machines: single crew can only do one setup at a time.

    JIT/VNS dispatch each machine independently (no shared crew) for gate independence.
    This post-processing step delays ONLY the overlapping setup segment (not all
    subsequent segments). Intra-machine cascading is handled by _fix_day_overlaps.

    Bidirectional resolution: tries pulling the blocker back before pushing current forward.
    """
    day_cap = config.day_capacity_min if config else DAY_CAP
    shift_a_start = config.shift_a_start if config else 420
    shift_b_end = config.shift_b_end if config else 1440
    hols = holidays or set()

    # Build priority lookup (lower index = higher priority = not delayed)
    prio_map: dict[str, int] = {}
    if crew_priority:
        prio_map = {m: i for i, m in enumerate(crew_priority)}

    # Collect setups with absolute time (including buffer days)
    setup_entries: list[tuple[float, float, int]] = []
    for idx, seg in enumerate(segments):
        if seg.setup_min > 0:
            abs_start = seg.day_idx * day_cap + (seg.start_min - shift_a_start)
            setup_entries.append((abs_start, seg.setup_min, idx))

    if not setup_entries:
        return segments

    setup_entries.sort(key=lambda e: (e[0], prio_map.get(segments[e[2]].machine_id, 99)))

    # Initialize crew_free_at before the earliest setup (handles negative abs_times from buffer days)
    crew_free_at = min(e[0] for e in setup_entries)
    prev_crew_end = 0.0
    blocker_seg_idx = -1
    blocker_abs_start = 0.0
    shifted = 0

    for abs_start, duration, seg_idx in setup_entries:
        seg = segments[seg_idx]

        if abs_start < crew_free_at - 0.01:
            # Overlap detected — resolve bidirectionally
            pulled = False
            if blocker_seg_idx >= 0:
                is_full, blocker_abs_start, new_crew_free = _try_pull_back(
                    segments, blocker_seg_idx, blocker_abs_start, prev_crew_end,
                    crew_free_at - abs_start, shift_a_start,
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
                pushed = _push_forward(seg, crew_free_at, abs_start, duration,
                                       shift_a_start, shift_b_end, hols)
                if pushed:
                    new_abs = crew_free_at
                    new_end = seg.start_min + duration if seg.end_min - seg.start_min >= duration else seg.end_min
                    # Update tracking only for same-day pushes (not day-overflow)
                    if seg.day_idx * day_cap + (seg.start_min - shift_a_start) >= abs_start:
                        crew_free_at = seg.day_idx * day_cap + (seg.start_min - shift_a_start) + duration
                        prev_crew_end = blocker_abs_start + segments[blocker_seg_idx].setup_min if blocker_seg_idx >= 0 else 0.0
                        blocker_seg_idx = seg_idx
                        blocker_abs_start = seg.day_idx * day_cap + (seg.start_min - shift_a_start)
                    shifted += 1
                else:
                    crew_free_at = abs_start + duration
                    prev_crew_end = blocker_abs_start + segments[blocker_seg_idx].setup_min if blocker_seg_idx >= 0 else 0.0
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
    """EDD-safe per-overlap crew serialization.

    Like _serialize_crew_setups but checks EDD before each fix:
    - Only delays a setup if the new day_idx <= seg.edd
    - Tries BOTH orderings (A-then-B vs B-then-A) for each overlap
    - Skips unfixable overlaps (logs warning)

    Used as fallback when standard serialization causes tardy.
    """
    day_cap = config.day_capacity_min if config else DAY_CAP
    shift_a_start = config.shift_a_start if config else 420
    shift_b_end = config.shift_b_end if config else 1440
    hols = holidays or set()

    prio_map: dict[str, int] = {}
    if crew_priority:
        prio_map = {m: i for i, m in enumerate(crew_priority)}

    # Collect setup intervals (including buffer days)
    setup_entries: list[tuple[float, float, int]] = []
    for idx, seg in enumerate(segments):
        if seg.setup_min > 0:
            abs_start = seg.day_idx * day_cap + (seg.start_min - shift_a_start)
            setup_entries.append((abs_start, seg.setup_min, idx))

    if not setup_entries:
        return segments

    setup_entries.sort(key=lambda e: (e[0], prio_map.get(segments[e[2]].machine_id, 99)))

    # Initialize before earliest setup (handles buffer days with negative abs_times)
    crew_free_at = min(e[0] for e in setup_entries)
    crew_machine = ""
    fixed = 0
    skipped = 0

    for abs_start, duration, seg_idx in setup_entries:
        seg = segments[seg_idx]

        if abs_start < crew_free_at - 0.01 and seg.machine_id != crew_machine:
            delay = int(crew_free_at - abs_start + 0.5)

            if delay < 1:
                crew_free_at = abs_start + duration
                crew_machine = seg.machine_id
                continue

            # Try push-forward with EDD check
            new_start = seg.start_min + delay
            new_end = seg.end_min + delay

            if new_end <= shift_b_end:
                # Same day — safe if day_idx <= edd
                if seg.day_idx <= seg.edd:
                    seg.start_min = new_start
                    seg.end_min = new_end
                    crew_free_at = (seg.day_idx * day_cap + (new_start - shift_a_start)) + duration
                    crew_machine = seg.machine_id
                    fixed += 1
                    continue

            # Try next workday with EDD check
            seg_duration = seg.end_min - seg.start_min
            new_day = seg.day_idx + 1
            while new_day in hols:
                new_day += 1

            if new_day <= seg.edd:
                seg.day_idx = new_day
                seg.start_min = shift_a_start
                seg.end_min = shift_a_start + seg_duration
                fixed += 1
                # Don't update crew_free_at — crew is free today for others
                continue

            # Can't fix without exceeding EDD — skip this overlap
            skipped += 1
            logger.warning(
                "Crew overlap unfixable (EDD %d): %s day %d delay %d min",
                seg.edd, seg.machine_id, seg.day_idx, delay,
            )

        # Update tracking
        if abs_start + duration > crew_free_at:
            crew_free_at = abs_start + duration
            crew_machine = seg.machine_id

    if fixed > 0:
        logger.info("Safe crew serialization: fixed %d, skipped %d overlaps", fixed, skipped)

    return segments


def schedule_all(data: EngineData, audit: bool = False, config: FactoryConfig | None = None, crew_priority: list[str] | None = None) -> ScheduleResult:
    """Run the full scheduling pipeline."""
    t0 = time.perf_counter()

    if config is None:
        config = FactoryConfig()

    journal = Journal()

    audit_logger = None
    if audit:
        from backend.audit.logger import AuditLogger
        audit_logger = AuditLogger()

    # Guardian: validate input
    journal.phase_start("guardian")
    guard = validate_input(data, config)
    if guard.dropped_ops:
        journal.log("guardian", "warn", f"Dropped {len(guard.dropped_ops)} ops: {', '.join(guard.dropped_ops[:5])}")
    journal.phase_end("guardian", f"{len(guard.issues)} issues, {len(guard.dropped_ops)} dropped", n_issues=len(guard.issues))
    data = guard.cleaned

    # Phase 1: EOps → Lots
    journal.phase_start("lot_sizing")
    lots = create_lots(data, config=config)
    journal.phase_end("lot_sizing", f"{len(lots)} lots from {len(data.ops)} ops", n_lots=len(lots), n_ops=len(data.ops))
    logger.info("Phase 1: %d lots from %d ops", len(lots), len(data.ops))

    if not lots:
        return ScheduleResult(
            segments=[], lots=[], score={},
            time_ms=0.0, warnings=journal.to_warnings(), operator_alerts=[],
            journal=journal.to_dicts(),
        )

    # Phase 2: Lots → ToolRuns
    journal.phase_start("tool_grouping")
    runs = create_tool_runs(lots, audit_logger=audit_logger, config=config)
    journal.phase_end("tool_grouping", f"{len(runs)} runs from {len(lots)} lots", n_runs=len(runs))
    logger.info("Phase 2: %d tool runs (vs %d lots)", len(runs), len(lots))

    # Auto buffer: detect per-machine capacity infeasibility with holidays
    journal.phase_start("dispatch")
    machine_runs = assign_machines(runs, data, audit_logger=audit_logger, config=config)
    global_holidays = set(data.holidays) if data.holidays else set()
    buffer_days = _detect_buffer_need(runs, config=config, machine_runs=machine_runs, holidays=global_holidays)
    if buffer_days > 0:
        logger.info("Auto buffer: +%d day(s) for infeasible early runs", buffer_days)
        _apply_buffer(runs, buffer_days)
        data = _shift_engine_data(data, buffer_days)
        global_holidays = set(data.holidays) if data.holidays else set()
        # Re-assign with shifted EDDs
        machine_runs = assign_machines(runs, data, audit_logger=audit_logger, config=config)

    # Phase 3: Sequence + Allocate
    machine_runs = sequence_per_machine(machine_runs, audit_logger=audit_logger, config=config, holidays=global_holidays or None)
    baseline_segments, baseline_lots, warnings = per_machine_dispatch(machine_runs, data, config=config)
    journal.phase_end("dispatch", f"{len(baseline_segments)} segments", n_segments=len(baseline_segments))
    logger.info("Phase 3: %d segments, %d warnings", len(baseline_segments), len(warnings))

    # Baseline score
    baseline_score = compute_score(baseline_segments, baseline_lots, data, config=config)
    logger.info(
        "Baseline: OTD=%.1f%%, OTD-D=%.1f%%, setups=%d, tardy=%d/%d",
        baseline_score["otd"], baseline_score["otd_d"], baseline_score["setups"],
        baseline_score["tardy_count"], baseline_score["total_lots"],
    )

    # Phase 4: JIT (LST-gated re-dispatch)
    journal.phase_start("jit")
    jit_thresh = config.jit_threshold
    jit_machine_runs = None
    jit_gates = None
    if config.jit_enabled and baseline_score["otd"] >= jit_thresh:
        final_segments, final_lots, jit_warnings, jit_machine_runs, jit_gates = jit_dispatch(
            runs, data,
            baseline_segments, baseline_lots, baseline_score,
            audit_logger=audit_logger, config=config,
        )
        warnings.extend(jit_warnings)
        journal.phase_end("jit", f"JIT applied, {len(final_segments)} segments")
    else:
        final_segments = baseline_segments
        final_lots = baseline_lots
        warnings.append("JIT disabled: baseline OTD < 95%")
        journal.log("jit", "warn", "JIT disabled: baseline OTD < 95%")
        journal.phase_end("jit", "JIT skipped")

    # Phase 4b: VNS polish (post-JIT)
    if config.vns_enabled and jit_machine_runs is not None and jit_gates is not None:
        from backend.scheduler.vns import vns_polish
        journal.phase_start("vns")
        jit_score = compute_score(final_segments, final_lots, data, config=config)
        vns_segs, vns_lots, vns_score, vns_warnings = vns_polish(
            jit_machine_runs, jit_gates, data, config,
            final_segments, final_lots, jit_score,
        )
        if (vns_score["tardy_count"] <= jit_score["tardy_count"]
                and (vns_score["setups"] < jit_score["setups"] or vns_score["earliness_avg_days"] < jit_score["earliness_avg_days"])):
            final_segments = vns_segs
            final_lots = vns_lots
        warnings.extend(vns_warnings)
        journal.phase_end("vns", f"VNS: setups={vns_score['setups']}, earliness={vns_score['earliness_avg_days']:.1f}d")

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
    pre_crew_score = compute_score(final_segments, final_lots, data, config=config)
    crew_segments = copy.deepcopy(final_segments)
    prev_hash = None
    for _crew_pass in range(10):  # max 10 passes with early exit on convergence
        crew_segments = _serialize_crew_setups(crew_segments, config, holidays=global_holidays, crew_priority=crew_priority)
        crew_segments = _fix_day_overlaps(crew_segments, config, holidays=global_holidays)
        crew_segments = _sanitize_segments(crew_segments, config, holidays=global_holidays)
        curr_hash = hash(tuple(
            (s.lot_id, s.day_idx, s.start_min, s.end_min) for s in crew_segments
        ))
        if curr_hash == prev_hash:
            break
        prev_hash = curr_hash
    crew_score = compute_score(crew_segments, final_lots, data, config=config)
    if crew_score["tardy_count"] <= pre_crew_score["tardy_count"]:
        final_segments = crew_segments
        logger.info("Crew serialization applied: no tardy regression")
    else:
        # Standard serialization causes tardy — try EDD-safe per-overlap fallback
        logger.info(
            "Crew serialization caused tardy %d > %d, trying EDD-safe fallback",
            crew_score["tardy_count"], pre_crew_score["tardy_count"],
        )
        safe_segments = copy.deepcopy(final_segments)
        prev_hash_safe = None
        for _ in range(10):
            safe_segments = _serialize_crew_safe(safe_segments, config, holidays=global_holidays, crew_priority=crew_priority)
            safe_segments = _fix_day_overlaps(safe_segments, config, holidays=global_holidays)
            safe_segments = _sanitize_segments(safe_segments, config, holidays=global_holidays)
            curr_hash_safe = hash(tuple(
                (s.lot_id, s.day_idx, s.start_min, s.end_min) for s in safe_segments
            ))
            if curr_hash_safe == prev_hash_safe:
                break
            prev_hash_safe = curr_hash_safe
        safe_score = compute_score(safe_segments, final_lots, data, config=config)
        if safe_score["tardy_count"] <= pre_crew_score["tardy_count"]:
            final_segments = safe_segments
            logger.info("EDD-safe crew serialization applied: no tardy regression")
        else:
            logger.warning(
                "Crew serialization skipped: both strategies cause tardy (std=%d, safe=%d, pre=%d)",
                crew_score["tardy_count"], safe_score["tardy_count"], pre_crew_score["tardy_count"],
            )
            warnings.append(
                f"Crew serialization limited: {safe_score['tardy_count']} tardy vs {pre_crew_score['tardy_count']} pre-crew"
            )

    # Tool contention: a physical tool cannot run on two machines at once.
    # JIT/VNS dispatch each machine with an isolated tool timeline, so a global
    # repair pass is needed here. OTD-guarded — never defers into tardiness.
    tc_pre_score = compute_score(final_segments, final_lots, data, config=config)
    tc_segments = copy.deepcopy(final_segments)
    tc_segments = _fix_tool_machine_overlaps(tc_segments, config, holidays=global_holidays)
    tc_segments = _fix_day_overlaps(tc_segments, config, holidays=global_holidays)
    tc_score = compute_score(tc_segments, final_lots, data, config=config)
    if tc_score["tardy_count"] <= tc_pre_score["tardy_count"]:
        final_segments = tc_segments
    else:
        logger.warning(
            "Tool contention fix skipped: would cause tardy %d > %d",
            tc_score["tardy_count"], tc_pre_score["tardy_count"],
        )

    # Final sanitize: enforce shift bounds + fix ghost segments
    final_segments = _sanitize_segments(final_segments, config, holidays=global_holidays)
    # Fix orphan continuations (segments wrongly marked as continuation by _fix_day_overlaps)
    final_segments = _fix_orphan_continuations(final_segments)

    # Optional compaction (opt-in via config.compact_enabled — default OFF).
    # Closes idle gaps left by JIT + crew serialization + tool contention by
    # pulling segments earlier. OTD-guarded: reverts if tardy regresses or new
    # tool-contention violations appear (same safety-net pattern as JIT/crew).
    if config.compact_enabled:
        compact_pre_score = compute_score(final_segments, final_lots, data, config=config)
        compact_pre_conflicts = len(_detect_tool_machine_overlaps(final_segments, config))
        compact_segments = copy.deepcopy(final_segments)
        compact_segments = _compact_segments(compact_segments, config, holidays=global_holidays)
        compact_segments = _fix_day_overlaps(compact_segments, config, holidays=global_holidays)
        compact_segments = _sanitize_segments(compact_segments, config, holidays=global_holidays)
        compact_segments = _fix_orphan_continuations(compact_segments)
        compact_score = compute_score(compact_segments, final_lots, data, config=config)
        compact_conflicts = len(_detect_tool_machine_overlaps(compact_segments, config))
        if (compact_score["tardy_count"] <= compact_pre_score["tardy_count"]
                and compact_conflicts <= compact_pre_conflicts):
            final_segments = compact_segments
            logger.info("Compaction applied: no tardy/contention regression")
        else:
            logger.warning(
                "Compaction reverted: tardy %d>%d or conflicts %d>%d",
                compact_score["tardy_count"], compact_pre_score["tardy_count"],
                compact_conflicts, compact_pre_conflicts,
            )

    # Verification: no physical tool may be on two machines simultaneously.
    tool_conflicts = _detect_tool_machine_overlaps(final_segments, config)
    if tool_conflicts:
        for tool_id, ma, mb, day in tool_conflicts[:5]:
            logger.warning(
                "Tool contention: tool %s on %s and %s simultaneously (day %d)",
                tool_id, ma, mb, day,
            )
        warnings.append(
            f"Tool contention: {len(tool_conflicts)} same-tool cross-machine overlap(s)"
        )
        journal.log(
            "scoring", "warn",
            f"{len(tool_conflicts)} same-tool cross-machine overlap(s) remain",
        )

    # Phase 5: Final scoring
    journal.phase_start("scoring")
    score = compute_score(final_segments, final_lots, data, config=config)
    score["buffer_days"] = buffer_days
    journal.phase_end("scoring", f"OTD={score['otd']:.1f}%, tardy={score['tardy_count']}", **{k: v for k, v in score.items() if isinstance(v, (int, float))})
    logger.info(
        "Final: OTD=%.1f%%, OTD-D=%.1f%%, setups=%d, tardy=%d/%d, earliness=%.1fd",
        score["otd"], score["otd_d"], score["setups"],
        score["tardy_count"], score["total_lots"], score["earliness_avg_days"],
    )

    # Earliness hard constraint check
    earliness_target = config.jit_earliness_target if config else 6.0
    if score["earliness_avg_days"] > earliness_target:
        warnings.append(
            f"HARD: earliness {score['earliness_avg_days']:.1f}d > target {earliness_target:.1f}d"
        )
        journal.log("scoring", "warn", f"Earliness {score['earliness_avg_days']:.1f}d exceeds target {earliness_target:.1f}d")

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

    return ScheduleResult(
        segments=final_segments,
        lots=final_lots,
        score=score,
        time_ms=round(elapsed, 1),
        warnings=warnings,
        operator_alerts=alerts,
        audit_trail=trail,
        journal=journal.to_dicts(),
    )
