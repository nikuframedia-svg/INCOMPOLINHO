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
    """Return a copy of EngineData with n_days increased and holidays shifted."""
    import copy
    shifted = copy.copy(data)
    shifted.n_days = data.n_days + buffer_days
    if hasattr(data, "holidays") and data.holidays:
        shifted.holidays = [h + buffer_days for h in data.holidays]
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
                    # EDD guard: never cause tardy
                    if new_day > curr.edd:
                        # Cap segment within remaining day time instead
                        if prev.end_min < shift_b_end:
                            curr.start_min = prev.end_min
                            curr.end_min = shift_b_end
                        else:
                            # No space left — collapse (zero visual footprint)
                            curr.start_min = shift_b_end
                            curr.end_min = shift_b_end
                        continue
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


def schedule_all(data: EngineData, params=None, audit: bool = False, config: FactoryConfig | None = None) -> ScheduleResult:
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
    runs = create_tool_runs(lots, audit_logger=audit_logger, params=params, config=config)
    journal.phase_end("tool_grouping", f"{len(runs)} runs from {len(lots)} lots", n_runs=len(runs))
    logger.info("Phase 2: %d tool runs (vs %d lots)", len(runs), len(lots))

    # Auto buffer: detect per-machine capacity infeasibility with holidays
    journal.phase_start("dispatch")
    machine_runs = assign_machines(runs, data, audit_logger=audit_logger, params=params, config=config)
    global_holidays = set(data.holidays) if data.holidays else set()
    buffer_days = _detect_buffer_need(runs, config=config, machine_runs=machine_runs, holidays=global_holidays)
    if buffer_days > 0:
        logger.info("Auto buffer: +%d day(s) for infeasible early runs", buffer_days)
        _apply_buffer(runs, buffer_days)
        data = _shift_engine_data(data, buffer_days)
        global_holidays = set(data.holidays) if data.holidays else set()
        # Re-assign with shifted EDDs
        machine_runs = assign_machines(runs, data, audit_logger=audit_logger, params=params, config=config)

    # Phase 3: Sequence + Allocate
    machine_runs = sequence_per_machine(machine_runs, audit_logger=audit_logger, params=params, config=config, holidays=global_holidays or None)
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
    jit_thresh = getattr(params, 'jit_threshold', config.jit_threshold)
    jit_machine_runs = None
    jit_gates = None
    if config.jit_enabled and baseline_score["otd"] >= jit_thresh:
        final_segments, final_lots, jit_warnings, jit_machine_runs, jit_gates = jit_dispatch(
            runs, data,
            baseline_segments, baseline_lots, baseline_score,
            audit_logger=audit_logger, params=params, config=config,
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
        if vns_score["setups"] < jit_score["setups"] or vns_score["earliness_avg_days"] < jit_score["earliness_avg_days"]:
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

    # Phase 5: Final scoring
    journal.phase_start("scoring")
    score = compute_score(final_segments, final_lots, data, config=config)
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
