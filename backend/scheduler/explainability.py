"""Explain why a scheduled lot cannot start earlier.

This module performs a read-only audit of the final plan. Generic reason
codes remain stable for API compatibility; physical reasons also receive a
deterministic detail entry using the form code|field=value|....
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from backend.calendar import is_factory_workday
from backend.config.types import FactoryConfig
from backend.scheduler.gap_filling import (
    PartialGapOpportunity,
    build_legal_interval_context,
    candidate_interval_boundaries,
    candidate_setup_starts,
    evaluate_legal_interval,
    find_gap_opportunities,
    tool_is_mounted_at,
)
from backend.scheduler.jit_policy import (
    calendar_holidays,
    earliest_allowed_start,
    workdays_between,
)
from backend.scheduler.operators import effective_operator_capacity
from backend.scheduler.priority import lot_rupture_day
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import segment_abs
from backend.types import EngineData, EOp


@dataclass(frozen=True)
class _BusyInterval:
    start: int
    end: int
    segment: Segment | None = None
    metadata: dict[str, Any] | None = None


def _fmt_minute(minute: int) -> str:
    minute = max(0, min(1440, int(minute)))
    if minute == 1440:
        return "00:00"
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _date_label(day_idx: int, data: EngineData) -> str:
    if 0 <= day_idx < len(data.workdays):
        return str(data.workdays[day_idx])
    return "fora_do_horizonte"


def _detail(code: str, **fields: object) -> str:
    values = [code]
    for key, value in fields.items():
        clean = str(value).replace("|", "/").replace("\n", " ")
        values.append(f"{key}={clean}")
    return "|".join(values)


def _overlaps(start: int, end: int, busy: _BusyInterval) -> bool:
    return start < busy.end and busy.start < end


def _clip_interval(block: dict[str, Any], day_idx: int) -> _BusyInterval | None:
    if int(block.get("start_day", -1)) != day_idx:
        return None
    start = max(0, int(block.get("start_min", 0)))
    end = min(1440, int(block.get("end_min", 1440)))
    if end <= start:
        return None
    return _BusyInterval(start, end, metadata=block)


def _segment_operator_demand(segment: Segment, data: EngineData) -> int:
    ops_by_id = {op.id: op for op in data.ops}
    if segment.twin_outputs:
        return max(
            (
                max(1, int(getattr(ops_by_id.get(op_id), "operators", 1) or 1))
                for op_id, _sku, _qty in segment.twin_outputs
            ),
            default=1,
        )
    op = next(
        (
            item
            for item in data.ops
            if item.sku == segment.sku
            and item.m == segment.machine_id
            and item.t == segment.tool_id
        ),
        None,
    )
    if op is None:
        op = next(
            (item for item in data.ops if item.sku == segment.sku and item.t == segment.tool_id),
            None,
        )
    return max(1, int(getattr(op, "operators", 1) or 1))


def _target_operator_demand(lot: Lot, segment: Segment, data: EngineData) -> int:
    op: EOp | None = next((item for item in data.ops if item.id == lot.op_id), None)
    return (
        max(1, int(op.operators or 1))
        if op is not None
        else _segment_operator_demand(segment, data)
    )


def _generic_codes(details: list[str]) -> list[str]:
    order = (
        "blocked_by_holiday",
        "blocked_by_inactive_machine",
        "blocked_by_priority_higher_risk_lot",
        "blocked_by_machine_busy",
        "blocked_by_tool_busy",
        "blocked_by_setup_crew",
        "blocked_by_operator_capacity",
        "blocked_by_intervening_tool_change",
        "blocked_by_run_setup_sequence",
    )
    prefixes = {item.split("|", 1)[0] for item in details}
    return [code for code in order if code in prefixes]


def _resource_indexes(
    segments: list[Segment],
    data: EngineData,
    config: FactoryConfig,
) -> tuple[
    dict[tuple[str, int], list[_BusyInterval]],
    dict[tuple[str, int], list[_BusyInterval]],
    dict[tuple[str, int], list[_BusyInterval]],
    dict[tuple[str, str, int], list[_BusyInterval]],
]:
    machine: dict[tuple[str, int], list[_BusyInterval]] = defaultdict(list)
    tool: dict[tuple[str, int], list[_BusyInterval]] = defaultdict(list)
    setup: dict[tuple[str, int], list[_BusyInterval]] = defaultdict(list)
    operators: dict[tuple[str, str, int], list[_BusyInterval]] = defaultdict(list)

    for item in segments:
        if item.end_min <= item.start_min:
            continue
        interval = _BusyInterval(int(item.start_min), int(item.end_min), segment=item)
        machine[(item.machine_id, item.day_idx)].append(interval)
        tool[(item.tool_id, item.day_idx)].append(interval)
        group = config.machine_groups.get(item.machine_id, "Grandes")
        if item.setup_min > 0:
            setup[(group, item.day_idx)].append(
                _BusyInterval(
                    int(item.start_min),
                    min(int(item.end_min), int(item.start_min + item.setup_min)),
                    segment=item,
                )
            )
        if item.prod_min > 0:
            production_start = min(
                int(item.end_min),
                int(round(item.start_min + max(0.0, item.setup_min))),
            )
            if production_start < int(item.end_min):
                operators[(group, item.shift, item.day_idx)].append(
                    _BusyInterval(
                        production_start,
                        int(item.end_min),
                        segment=item,
                    )
                )

    for machine_id, blocks in data.machine_blocked_intervals.items():
        for block in blocks:
            day_idx = int(block.get("start_day", -1))
            interval = _clip_interval(block, day_idx)
            if interval is not None:
                machine[(machine_id, day_idx)].append(interval)
    for tool_id, blocks in data.tool_blocked_intervals.items():
        for block in blocks:
            day_idx = int(block.get("start_day", -1))
            interval = _clip_interval(block, day_idx)
            if interval is not None:
                tool[(tool_id, day_idx)].append(interval)
    for block in data.operator_blocked_intervals:
        day_idx = int(block.get("start_day", -1))
        interval = _clip_interval(block, day_idx)
        if interval is not None:
            operators[
                (str(block.get("group", "")), str(block.get("shift", "")), day_idx)
            ].append(interval)

    for index in (machine, tool, setup, operators):
        for values in index.values():
            values.sort(key=lambda item: (item.start, item.end))
    return machine, tool, setup, operators


def _segment_detail(
    code: str,
    day_idx: int,
    busy: _BusyInterval,
    data: EngineData,
    lots_by_id: dict[str, Lot],
    target: Lot,
    **fields: object,
) -> str:
    segment = busy.segment
    competing = lots_by_id.get(segment.lot_id) if segment is not None else None
    return _detail(
        code,
        day=day_idx,
        date=_date_label(day_idx, data),
        interval=f"{_fmt_minute(busy.start)}-{_fmt_minute(busy.end)}",
        lot=segment.lot_id if segment is not None else "",
        sku=segment.sku if segment is not None else "",
        target_rupture=lot_rupture_day(target),
        competing_rupture=lot_rupture_day(competing) if competing is not None else "",
        target_priority=int(target.planning_priority or 0),
        competing_priority=int(competing.planning_priority or 0) if competing else "",
        **fields,
    )


def _metadata_detail(
    code: str,
    day_idx: int,
    busy: _BusyInterval,
    data: EngineData,
    **fields: object,
) -> str:
    metadata = busy.metadata or {}
    return _detail(
        code,
        day=day_idx,
        date=_date_label(day_idx, data),
        interval=f"{_fmt_minute(busy.start)}-{_fmt_minute(busy.end)}",
        source="unavailability",
        category=metadata.get("category", ""),
        reason=metadata.get("reason", ""),
        **fields,
    )


def _operator_conflicts(
    start: int,
    end: int,
    day_idx: int,
    group: str,
    target_required: int,
    target_lot_id: str,
    operator_index: dict[tuple[str, str, int], list[_BusyInterval]],
    data: EngineData,
    config: FactoryConfig,
) -> list[str]:
    details: list[str] = []
    for shift in config.shifts:
        overlap_start = max(start, shift.start_min)
        overlap_end = min(end, shift.end_min)
        if overlap_end <= overlap_start:
            continue
        intervals = operator_index.get((group, shift.id, day_idx), [])
        boundaries = {overlap_start, overlap_end}
        for busy in intervals:
            if _overlaps(overlap_start, overlap_end, busy):
                boundaries.update((max(overlap_start, busy.start), min(overlap_end, busy.end)))
        points = sorted(boundaries)
        capacity = effective_operator_capacity(data, config, day_idx, group, shift.id)
        for left, right in zip(points, points[1:]):
            if right <= left:
                continue
            used = unavailable = 0
            competing_lots: list[str] = []
            for busy in intervals:
                if not _overlaps(left, right, busy):
                    continue
                if busy.segment is not None:
                    if busy.segment.lot_id == target_lot_id:
                        continue
                    used += _segment_operator_demand(busy.segment, data)
                    competing_lots.append(busy.segment.lot_id)
                else:
                    unavailable += max(0, int((busy.metadata or {}).get("count", 1)))
            available = max(0, capacity - unavailable)
            if used + target_required > available:
                details.append(
                    _detail(
                        "blocked_by_operator_capacity",
                        day=day_idx,
                        date=_date_label(day_idx, data),
                        interval=f"{_fmt_minute(left)}-{_fmt_minute(right)}",
                        group=group,
                        shift=shift.id,
                        capacity=capacity,
                        unavailable=unavailable,
                        occupied=used,
                        required=target_required,
                        competing_lots=",".join(sorted(set(competing_lots))),
                    )
                )
    return details


def _setup_crew_conflicts(
    start: int,
    end: int,
    day_idx: int,
    group: str,
    target_lot_id: str,
    setup_index: dict[tuple[str, int], list[_BusyInterval]],
    data: EngineData,
    config: FactoryConfig,
) -> list[str]:
    if end <= start:
        return []
    intervals = [
        busy
        for busy in setup_index.get((group, day_idx), [])
        if (busy.segment is None or busy.segment.lot_id != target_lot_id)
        and _overlaps(start, end, busy)
    ]
    capacity = max(1, int(config.setup_crews_by_group.get(group, 1)))
    boundaries = {start, end}
    for busy in intervals:
        boundaries.update((max(start, busy.start), min(end, busy.end)))

    details: list[str] = []
    points = sorted(boundaries)
    for left, right in zip(points, points[1:]):
        active = [busy for busy in intervals if _overlaps(left, right, busy)]
        if len(active) < capacity:
            continue
        details.append(
            _detail(
                "blocked_by_setup_crew",
                day=day_idx,
                date=_date_label(day_idx, data),
                interval=f"{_fmt_minute(left)}-{_fmt_minute(right)}",
                group=group,
                capacity=capacity,
                occupied=len(active),
                competing_lots=",".join(
                    sorted(
                        {
                            busy.segment.lot_id
                            for busy in active
                            if busy.segment is not None
                        }
                    )
                ),
                competing_machines=",".join(
                    sorted(
                        {
                            busy.segment.machine_id
                            for busy in active
                            if busy.segment is not None
                        }
                    )
                ),
            )
        )
    return details


def annotate_left_shift_blockers(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    gap_opportunities: list[PartialGapOpportunity] | None = None,
    protected_lot_ids: set[str] | None = None,
) -> None:
    """Attach exact, verifiable earlier-start reasons to each lot."""

    lots_by_id = {lot.id: lot for lot in lots}
    first_productive: dict[str, Segment] = {}
    run_setups: dict[str, list[Segment]] = defaultdict(list)
    protected = set(data.preserved_lot_proofs) | (protected_lot_ids or set())
    for item in segments:
        if item.setup_min > 0:
            run_setups[item.run_id].append(item)
        if item.lot_id in protected:
            continue
        item.left_shift_blockers = []
        item.material_release_day = None
        item.release_delay_workdays = 0
        if item.prod_min > 0 and (
            item.lot_id not in first_productive
            or (item.day_idx, item.start_min)
            < (first_productive[item.lot_id].day_idx, first_productive[item.lot_id].start_min)
        ):
            first_productive[item.lot_id] = item

    interval_context = build_legal_interval_context(segments, lots, data, config)
    holidays = calendar_holidays(data, -7, data.n_days + 7)
    canonical_opportunities = {
        opportunity.lot_id: opportunity
        for opportunity in (
            find_gap_opportunities(
                segments,
                lots,
                data,
                config,
                context=interval_context,
            )
            if gap_opportunities is None
            else gap_opportunities
        )
    }

    for lot_id, segment in first_productive.items():
        lot = lots_by_id.get(lot_id)
        if lot is None:
            continue
        raw_floor = earliest_allowed_start(lot, holidays)
        floor = max(0, raw_floor)
        segment.material_release_day = raw_floor
        segment.release_delay_workdays = workdays_between(raw_floor, segment.day_idx, holidays)

        if opportunity := canonical_opportunities.get(lot_id):
            segment.left_shift_blockers = [
                "left_shift_available",
                _detail(
                    "left_shift_available",
                    day=opportunity.gap_day,
                    date=_date_label(opportunity.gap_day, data),
                    interval=(
                        f"{_fmt_minute(opportunity.gap_start_min)}-"
                        f"{_fmt_minute(opportunity.gap_end_min)}"
                    ),
                    machine=opportunity.machine_id,
                    tool=opportunity.tool_id,
                    includes_setup=opportunity.movable_setup_min > 0,
                ),
            ]
            continue

        all_setup_segments = sorted(
            run_setups.get(segment.run_id, []), key=lambda item: (item.day_idx, item.start_min)
        )
        production_start_abs = segment_abs(segment, config)[0] + float(segment.setup_min)
        setup_segments: list[Segment] = []
        setup_cursor = production_start_abs
        for item in reversed(all_setup_segments):
            setup_start_abs = segment_abs(item, config)[0]
            setup_end_abs = setup_start_abs + float(item.setup_min)
            if abs(setup_end_abs - setup_cursor) > 0.01:
                continue
            setup_segments.append(item)
            setup_cursor = setup_start_abs
        setup_segments.reverse()
        run_setup = setup_segments[0] if setup_segments else None
        setup_duration = (
            sum(float(item.setup_min) for item in setup_segments)
            if setup_segments else segment.setup_min
        )
        # Only call a slot genuinely available when the complete opening block
        # fits. A token setup-sized tranche can be physically possible yet
        # operationally useless if it forces the campaign to stop and setup
        # again later.
        opening_prod = max(1, int(round(segment.prod_min)))
        next_productive = min(
            (
                item
                for item in segments
                if item.lot_id == lot_id
                and item.prod_min > 0
                and (item.day_idx, item.start_min) > (segment.day_idx, segment.start_min)
            ),
            key=lambda item: (item.day_idx, item.start_min),
            default=None,
        )
        actual_production = segment.production_start_min
        actual_abs = segment.day_idx * 1440 + actual_production

        details_seen: list[str] = []
        earliest_available: tuple[int, int, int, bool] | None = None
        had_candidate = False

        for day_idx in range(floor, min(segment.day_idx, data.n_days - 1) + 1):
            if not is_factory_workday(day_idx, data, config):
                details_seen.append(
                    _detail(
                        "blocked_by_holiday",
                        day=day_idx,
                        date=_date_label(day_idx, data),
                        interval=f"{_fmt_minute(config.shift_a_start)}-{_fmt_minute(config.shift_b_end)}",
                    )
                )
                continue

            machine_cfg = config.machines.get(segment.machine_id)
            if machine_cfg is not None and not machine_cfg.active:
                details_seen.append(
                    _detail(
                        "blocked_by_inactive_machine",
                        day=day_idx,
                        date=_date_label(day_idx, data),
                        interval=f"{_fmt_minute(config.shift_a_start)}-{_fmt_minute(config.shift_b_end)}",
                        machine=segment.machine_id,
                    )
                )
                continue
            if day_idx in data.machine_blocked_days.get(segment.machine_id, set()):
                details_seen.append(
                    _detail(
                        "blocked_by_machine_busy",
                        day=day_idx,
                        date=_date_label(day_idx, data),
                        interval=f"{_fmt_minute(config.shift_a_start)}-{_fmt_minute(config.shift_b_end)}",
                        machine=segment.machine_id,
                        source="blocked_day",
                    )
                )
                continue
            if day_idx in data.tool_blocked_days.get(segment.tool_id, set()):
                details_seen.append(
                    _detail(
                        "blocked_by_tool_busy",
                        day=day_idx,
                        date=_date_label(day_idx, data),
                        interval=f"{_fmt_minute(config.shift_a_start)}-{_fmt_minute(config.shift_b_end)}",
                        tool=segment.tool_id,
                        source="blocked_day",
                    )
                )
                continue

            boundaries = candidate_interval_boundaries(
                segments,
                segment,
                data,
                config,
                day_idx,
                int(config.shift_a_start),
                int(config.shift_b_end),
                interval_context,
            )
            for block_start in candidate_setup_starts(
                boundaries,
                setup_duration,
                int(config.shift_a_start),
                int(config.shift_b_end),
            ):
                candidate_setup = setup_duration
                if run_setup is not None:
                    final_setup = setup_segments[-1]
                    setup_end_abs = (
                        final_setup.day_idx * 1440
                        + final_setup.start_min
                        + final_setup.setup_min
                    )
                    if day_idx * 1440 + block_start >= setup_end_abs:
                        candidate_setup = 0
                production_start = block_start + candidate_setup
                production_end = production_start + opening_prod
                if production_end > config.shift_b_end:
                    continue
                if day_idx * 1440 + production_start >= actual_abs:
                    continue
                had_candidate = True
                evaluation = evaluate_legal_interval(
                    segments,
                    segment,
                    data,
                    config,
                    day_idx,
                    block_start,
                    production_end,
                    setup_min=candidate_setup,
                    lots_by_id=lots_by_id,
                    moving_lot=lot,
                    ignored_lot_ids={lot_id},
                    context=interval_context,
                )
                candidate_details = list(evaluation.blocking_reasons)
                candidate_abs = day_idx * 1440 + block_start
                known_setup = all_setup_segments[0] if all_setup_segments else None
                known_setup_end_abs = (
                    known_setup.day_idx * 1440
                    + known_setup.start_min
                    + known_setup.setup_min
                    if known_setup is not None
                    else None
                )
                if (
                    candidate_setup <= 0
                    and known_setup_end_abs is not None
                    and candidate_abs < known_setup_end_abs
                ):
                    candidate_details.append(
                        _detail(
                            "blocked_by_run_setup_sequence",
                            day=known_setup.day_idx,
                            date=_date_label(known_setup.day_idx, data),
                            interval=(
                                f"{_fmt_minute(known_setup.start_min)}-"
                                f"{_fmt_minute(known_setup.start_min + known_setup.setup_min)}"
                            ),
                            run=segment.run_id,
                            setup_lot=known_setup.lot_id,
                        )
                    )
                elif (
                    candidate_setup <= 0
                    and known_setup is not None
                    and not tool_is_mounted_at(
                        segments,
                        segment,
                        day_idx,
                        block_start,
                    )
                ):
                    candidate_details.append(
                        _detail(
                            "blocked_by_intervening_tool_change",
                            day=day_idx,
                            date=_date_label(day_idx, data),
                            interval=(
                                f"{_fmt_minute(block_start)}-"
                                f"{_fmt_minute(production_end)}"
                            ),
                            machine=segment.machine_id,
                            tool=segment.tool_id,
                        )
                    )
                if next_productive is not None:
                    candidate_end_abs = day_idx * 1440 + production_end
                    next_start_abs = (
                        next_productive.day_idx * 1440 + next_productive.start_min
                    )
                    intervening = next(
                        (
                            other
                            for other in segments
                            if other.machine_id == segment.machine_id
                            and other.lot_id != lot_id
                            and other.tool_id != segment.tool_id
                            and candidate_end_abs
                            < other.day_idx * 1440 + other.end_min
                            and other.day_idx * 1440 + other.start_min < next_start_abs
                        ),
                        None,
                    )
                    if intervening is not None:
                        candidate_details.append(
                            _detail(
                                "blocked_by_intervening_tool_change",
                                day=intervening.day_idx,
                                date=_date_label(intervening.day_idx, data),
                                interval=(
                                    f"{_fmt_minute(intervening.start_min)}-"
                                    f"{_fmt_minute(intervening.end_min)}"
                                ),
                                machine=intervening.machine_id,
                                tool=intervening.tool_id,
                            )
                        )
                if not candidate_details:
                    earliest_available = (
                        day_idx,
                        block_start,
                        production_end,
                        candidate_setup > 0,
                    )
                    break
                details_seen.extend(candidate_details)
            if earliest_available is not None:
                break

        if earliest_available is not None:
            day_idx, start, end, _includes_setup = earliest_available
            # The explanatory scan is deliberately broad. If the canonical
            # move engine rejected the slot, it cannot become actionable only
            # because this read-only scan found empty clock time.
            details_seen.append(
                _detail(
                    "blocked_by_campaign_sequence",
                    day=day_idx,
                    date=_date_label(day_idx, data),
                    interval=f"{_fmt_minute(start)}-{_fmt_minute(end)}",
                    machine=segment.machine_id,
                    tool=segment.tool_id,
                )
            )

        details = list(dict.fromkeys(details_seen))
        if run_setup is not None and (
            run_setup.day_idx,
            int(run_setup.start_min + run_setup.setup_min),
        ) > (floor, config.shift_a_start):
            details.append(
                _detail(
                    "blocked_by_run_setup_sequence",
                    day=run_setup.day_idx,
                    date=_date_label(run_setup.day_idx, data),
                    interval=(
                        f"{_fmt_minute(run_setup.start_min)}-"
                        f"{_fmt_minute(run_setup.start_min + run_setup.setup_min)}"
                    ),
                    run=segment.run_id,
                    setup_lot=run_setup.lot_id,
                )
            )

        if details:
            segment.left_shift_blockers = _generic_codes(details) + details
        elif not had_candidate:
            segment.left_shift_blockers = [
                "blocked_by_material_release",
                _detail(
                    "blocked_by_material_release",
                    day=floor,
                    date=_date_label(floor, data),
                    interval=f"{_fmt_minute(config.shift_a_start)}-{_fmt_minute(actual_production)}",
                ),
            ]
        else:
            segment.left_shift_blockers = [
                "blocked_by_campaign_sequence",
                _detail(
                    "blocked_by_campaign_sequence",
                    day=segment.day_idx,
                    date=_date_label(segment.day_idx, data),
                    interval=(
                        f"{_fmt_minute(config.shift_a_start)}-"
                        f"{_fmt_minute(segment.start_min)}"
                    ),
                    machine=segment.machine_id,
                    tool=segment.tool_id,
                ),
            ]
