"""Validated exchange of a light campaign tail and a heavier interrupted run.

The ordinary left-shift normalizer does not introduce another setup. This
bounded neighbourhood considers that trade only when it completes an entire
following lot a day earlier without postponing the displaced lot to another
day. No resource assumption is made from headcount totals: the complete plan
is validated against exact operator, crew, machine, tool and material windows.

The exchange reinstalls the predecessor tool, so it normally adds a physical
setup. Under the no-loss improvement contract such a candidate is a trade-off:
it is described through ``tradeoffs`` and never applied automatically.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import replace

from backend.calendar import is_factory_workday
from backend.config.shifts import ordered_shifts
from backend.config.types import FactoryConfig
from backend.planning_control import planning_checkpoint, remaining_time
from backend.scheduler.global_jit import materialise_fixed_run
from backend.scheduler.improvement import (
    ContractVerdict,
    anticipation_better,
    anticipation_key,
    contract_verdict,
    tradeoff_proposal,
)
from backend.scheduler.priority import delivery_not_worse
from backend.scheduler.priority_normalization import _rebuild_run, _restore_exact_production
from backend.scheduler.protection import protected_lot_ids
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import coverage_metrics, required_setup_minutes, validate_plan
from backend.types import EngineData


def _position(segment: Segment) -> tuple[int, int, str]:
    return segment.day_idx, segment.start_min, segment.machine_id


def _completion_days(segments: list[Segment]) -> dict[str, int]:
    result: dict[str, int] = {}
    for segment in segments:
        if segment.prod_min > 0:
            result[segment.lot_id] = max(result.get(segment.lot_id, -1), segment.day_idx)
    return result


def _complete_and_legal(
    candidate: list[Segment], lots: list[Lot], data: EngineData, config: FactoryConfig,
) -> bool:
    if validate_plan(candidate, data, config, lots=lots):
        return False
    coverage = coverage_metrics(candidate, lots)
    return not any(coverage[key] for key in (
        "missing_lots", "unexpected_lots", "missing_qty", "overproduced_qty",
        "duplicate_twin_output_qty", "twin_output_mismatches",
    ))


def repair_shift_capacity_exchange(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    max_evaluations: int | None = None,
    tradeoffs: list[dict] | None = None,
) -> list[Segment]:
    """Advance a complete interrupted run into A, resuming its predecessor in B.

    Candidate construction is generic over machines, tools and shifts. The
    predecessor must be a setup-free campaign tail already continued from an
    earlier day; the following single-lot run must currently spill past today.
    A newly installed predecessor pays its full setup in the later shift.
    Only candidates admissible under the no-loss contract are returned; the
    others are appended to ``tradeoffs`` when a list is supplied.
    """
    shifts = ordered_shifts(config)
    if len(shifts) < 2 or not segments or not lots:
        return segments
    limit = max_evaluations if max_evaluations is not None else (4 if len(segments) > 200 else 12)
    if limit <= 0:
        return segments

    frozen_ids = protected_lot_ids(data)
    lots_by_id = {lot.id: lot for lot in lots}
    by_machine: dict[str, list[Segment]] = defaultdict(list)
    by_run: dict[tuple[str, str], list[Segment]] = defaultdict(list)
    for segment in segments:
        by_machine[segment.machine_id].append(segment)
        by_run[(segment.machine_id, segment.run_id)].append(segment)
    for machine_segments in by_machine.values():
        machine_segments.sort(key=_position)

    original_completion = _completion_days(segments)
    before_score: dict | None = None
    working_days = [
        day for day in range(max(0, data.n_days))
        if is_factory_workday(day, data, config)
    ]
    day_slots = {day: slot for slot, day in enumerate(working_days)}
    existing_run_ids = {segment.run_id for segment in segments}
    evaluated = 0

    for machine_id, timeline in sorted(by_machine.items()):
        for tail, next_first in zip(timeline, timeline[1:]):
            planning_checkpoint()
            if remaining_time() is not None and remaining_time() < 2.0:
                return segments
            if evaluated >= limit:
                return segments
            if (
                tail.prod_min <= 0 or tail.setup_min > 0
                or next_first.prod_min <= 0 or next_first.setup_min <= 0
                or tail.tool_id == next_first.tool_id
                or tail.day_idx != next_first.day_idx
                or tail.end_min != next_first.start_min
                or tail.lot_id in frozen_ids or next_first.lot_id in frozen_ids
                or tail.day_idx not in day_slots
            ):
                continue
            early = next((shift for shift in shifts if shift.id == tail.shift), None)
            if early is None or tail.end_min > early.end_min:
                continue
            later_shifts = [shift for shift in shifts if shift.start_min >= early.end_min]
            if not later_shifts:
                continue

            tail_run = by_run[(machine_id, tail.run_id)]
            if not any(
                segment.prod_min > 0 and _position(segment) < _position(tail)
                for segment in tail_run
            ) or any(
                segment.end_min > segment.start_min and _position(segment) > _position(tail)
                for segment in tail_run
            ):
                continue
            following = by_run[(machine_id, next_first.run_id)]
            if (
                len({segment.lot_id for segment in following}) != 1
                or min(following, key=_position) is not next_first
                or any(segment.lot_id in frozen_ids for segment in following)
                or original_completion.get(next_first.lot_id, -1) <= tail.day_idx
            ):
                continue
            if any(
                segment.run_id == next_first.run_id and segment.machine_id != machine_id
                for segment in segments
            ):
                continue
            run = _rebuild_run(
                next_first.run_id, following, lots_by_id, machine_id,
            )
            if run is None or len(run.lots) != 1:
                continue
            required_run_minutes = math.ceil(run.setup_min) + math.ceil(run.lots[0].prod_min)
            if required_run_minutes > early.end_min - tail.start_min:
                continue

            start_coord = day_slots[tail.day_idx] * config.day_capacity_min
            start_coord += sum(
                shift.duration_min for shift in shifts if shift.end_min <= early.start_min
            ) + tail.start_min - early.start_min
            shifted_next = materialise_fixed_run(
                run, machine_id, start_coord, working_days, config,
            )
            _restore_exact_production(shifted_next, [run])
            if any(segment.day_idx != tail.day_idx or segment.shift != early.id
                   for segment in shifted_next):
                continue

            for later in later_shifts:
                setup = math.ceil(required_setup_minutes(tail, lots_by_id))
                end = later.start_min + setup + math.ceil(tail.prod_min)
                if end > later.end_min:
                    continue
                new_run_id = f"{tail.run_id}:return:{tail.day_idx}:{later.id}"
                if new_run_id in existing_run_ids:
                    continue
                resumed_tail = replace(
                    tail, run_id=new_run_id, shift=later.id,
                    start_min=later.start_min, end_min=end,
                    setup_min=float(setup), is_continuation=False,
                    run_setup_min=float(setup), run_qty=tail.qty,
                    run_lot_count=1, left_shift_blockers=[],
                )
                removed = {id(tail), *(id(segment) for segment in following)}
                candidate = sorted(
                    [segment for segment in segments if id(segment) not in removed]
                    + shifted_next + [resumed_tail],
                    key=_position,
                )
                evaluated += 1
                planning_checkpoint()
                if not _complete_and_legal(candidate, lots, data, config):
                    continue
                after_completion = _completion_days(candidate)
                if (
                    after_completion.get(next_first.lot_id, -1)
                    >= original_completion[next_first.lot_id]
                    or any(
                        after_completion.get(lot_id, -1) > completion
                        for lot_id, completion in original_completion.items()
                    )
                ):
                    continue
                extra_setup = (
                    sum(segment.setup_min for segment in candidate)
                    - sum(segment.setup_min for segment in segments)
                )
                if extra_setup > setup + 0.01:
                    continue
                if before_score is None:
                    before_score = compute_score(
                        segments, lots, data, config=config, include_operational_audit=False,
                    )
                after_score = compute_score(
                    candidate, lots, data, config=config, include_operational_audit=False,
                )
                if not delivery_not_worse(after_score, before_score):
                    continue
                if any(
                    after_score.get(key, 0) > before_score.get(key, 0)
                    for key in (
                        "production_due_misses", "production_due_late_workdays",
                        "early_window_violations", "early_window_violation_workdays",
                    )
                ):
                    continue
                verdict = contract_verdict(
                    candidate, segments, data,
                    candidate_lots=lots,
                    candidate_score=after_score, reference_score=before_score,
                )
                # Same order as the improvement evaluator: callers apply
                # this repair directly, so it must be a canonical gain.
                if verdict.admissible:
                    if anticipation_better(
                        anticipation_key(candidate, lots), anticipation_key(segments, lots),
                    ):
                        return candidate
                    verdict = ContractVerdict(False, [
                        "antecipacao atrasa um lote de maior prioridade comercial",
                    ])
                if tradeoffs is not None:
                    tradeoffs.append(tradeoff_proposal(
                        "shift_exchange", verdict,
                        machine_id=machine_id, day_idx=tail.day_idx,
                        advanced_lot_id=next_first.lot_id, resumed_lot_id=tail.lot_id,
                        shift=later.id,
                    ))
    return segments
