"""Shared detection and materialisation of legal partial production moves."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Collection
from dataclasses import asdict, dataclass, replace

from backend.calendar import is_factory_workday
from backend.config.types import FactoryConfig
from backend.scheduler.jit_policy import calendar_holidays, earliest_allowed_start
from backend.scheduler.operators import (
    effective_operator_capacity,
    segment_operator_demand,
)
from backend.scheduler.priority import lot_priority_key
from backend.scheduler.protection import protected_lot_ids as planning_protected_lot_ids
from backend.scheduler.setup_identity import retained_setup_at, segment_setup_identity
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData


@dataclass(frozen=True, slots=True)
class PartialGapOpportunity:
    """A productive prefix that can move into an earlier resource-safe gap."""

    lot_id: str
    machine_id: str
    tool_id: str
    gap_day: int
    gap_start_min: int
    gap_end_min: int
    movable_prod_min: float
    source_day: int
    source_start_min: int
    source_end_min: int
    source_qty: int
    movable_setup_min: float = 0.0

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["blocking_reason"] = None
        return result


@dataclass(frozen=True, slots=True)
class LegalIntervalEvaluation:
    """Result of evaluating one exact factory interval."""

    allowed: bool
    shift_id: str | None
    blocking_reasons: tuple[str, ...] = ()

    @property
    def blocking_reason(self) -> str | None:
        return self.blocking_reasons[0] if self.blocking_reasons else None


@dataclass(slots=True)
class LegalIntervalContext:
    """Indexes shared by repeated legal-interval evaluations of one plan."""

    segments_by_day: dict[int, tuple[Segment, ...]]
    setups_by_group_day: dict[tuple[str, int], tuple[Segment, ...]]
    production_by_group_day: dict[tuple[str, int], tuple[Segment, ...]]
    productive_by_machine_lot: dict[str, dict[str, tuple[Segment, ...]]]
    operator_demand_by_segment: dict[int, int]
    lot_priorities: dict[str, tuple]


def build_legal_interval_context(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
) -> LegalIntervalContext:
    """Index an immutable plan snapshot for interval searches and explanations."""

    by_day: dict[int, list[Segment]] = defaultdict(list)
    setups: dict[tuple[str, int], list[Segment]] = defaultdict(list)
    production: dict[tuple[str, int], list[Segment]] = defaultdict(list)
    campaigns: dict[str, dict[str, list[Segment]]] = defaultdict(
        lambda: defaultdict(list)
    )
    demands: dict[int, int] = {}
    for segment in segments:
        by_day[segment.day_idx].append(segment)
        group = config.machine_groups.get(segment.machine_id, "Grandes")
        if segment.setup_min > 0:
            setups[(group, segment.day_idx)].append(segment)
        if segment.prod_min > 0:
            production[(group, segment.day_idx)].append(segment)
            campaigns[segment.machine_id][segment.lot_id].append(segment)
            demands[id(segment)] = segment_operator_demand(segment, data)

    def position(item: Segment) -> tuple[int, int, str]:
        return item.day_idx, item.start_min, item.machine_id
    return LegalIntervalContext(
        segments_by_day={
            day: tuple(sorted(items, key=position)) for day, items in by_day.items()
        },
        setups_by_group_day={
            key: tuple(sorted(items, key=position)) for key, items in setups.items()
        },
        production_by_group_day={
            key: tuple(sorted(items, key=position)) for key, items in production.items()
        },
        productive_by_machine_lot={
            machine_id: {
                lot_id: tuple(sorted(items, key=position))
                for lot_id, items in by_lot.items()
            }
            for machine_id, by_lot in campaigns.items()
        },
        operator_demand_by_segment=demands,
        lot_priorities={lot.id: lot_priority_key(lot) for lot in lots},
    )


def _overlaps(start: float, end: float, other_start: float, other_end: float) -> bool:
    return start < other_end and other_start < end


def _source_matches(segment: Segment, opportunity: PartialGapOpportunity) -> bool:
    return bool(
        segment.lot_id == opportunity.lot_id
        and segment.machine_id == opportunity.machine_id
        and segment.tool_id == opportunity.tool_id
        and segment.day_idx == opportunity.source_day
        and segment.start_min == opportunity.source_start_min
        and segment.end_min == opportunity.source_end_min
        and segment.qty == opportunity.source_qty
    )


def _shift_for_interval(config: FactoryConfig, start: float, end: float) -> str | None:
    return next(
        (
            shift.id
            for shift in config.shifts
            if int(shift.start_min) <= start and end <= int(shift.end_min)
        ),
        None,
    )


def _reason(code: str, **fields: object) -> str:
    parts = [code]
    parts.extend(f"{key}={str(value).replace('|', '/')}" for key, value in fields.items())
    return "|".join(parts)


def _fmt_minute(minute: float) -> str:
    minute = max(0, min(1440, int(minute)))
    return "00:00" if minute == 1440 else f"{minute // 60:02d}:{minute % 60:02d}"


def _date_label(day_idx: int, data: EngineData) -> str:
    if 0 <= day_idx < len(data.workdays):
        return str(data.workdays[day_idx])[:10]
    return "fora_do_horizonte"


def tool_is_mounted_at(
    segments: list[Segment],
    source: Segment,
    day_idx: int,
    start_min: int,
) -> bool:
    """Whether the source tool is physically mounted at an idle-slot start.

    A run identifier is an optimisation construct, not physical evidence.  The
    last completed machine activity is what determines the mounted tool after
    repairs or solver reordering.
    """

    return retained_setup_at(
        [other for other in segments if other is not source],
        source.machine_id, segment_setup_identity(source), day_idx, start_min,
    )


def _contiguous_setup_chain(
    segments: list[Segment],
    source: Segment,
    config: FactoryConfig,
    data: EngineData | None,
) -> list[Segment]:
    """Return every setup fragment immediately preceding source production."""

    chain: list[Segment] = [source] if source.setup_min > 0 else []
    cursor_day = int(source.day_idx)
    cursor_min = int(source.start_min)
    candidates = sorted(
        (
            segment
            for segment in segments
            if segment is not source
            and segment.run_id == source.run_id
            and segment.machine_id == source.machine_id
            and segment.tool_id == source.tool_id
            and segment.setup_min > 0
            and segment.prod_min <= 0
        ),
        key=lambda item: (item.day_idx, item.start_min),
        reverse=True,
    )
    used: set[int] = set()
    while True:
        previous = next(
            (
                segment
                for segment in candidates
                if id(segment) not in used
                and (
                    (
                        segment.day_idx == cursor_day
                        and abs(
                            float(segment.start_min)
                            + float(segment.setup_min)
                            - cursor_min
                        )
                        <= 0.01
                    )
                    or (
                        segment.day_idx < cursor_day
                        and cursor_min == int(config.shift_a_start)
                        and abs(
                            float(segment.start_min)
                            + float(segment.setup_min)
                            - float(config.shift_b_end)
                        )
                        <= 0.01
                        and (
                            data is None
                            and cursor_day == segment.day_idx + 1
                            or data is not None
                            and all(
                                not is_factory_workday(day_idx, data, config)
                                for day_idx in range(segment.day_idx + 1, cursor_day)
                            )
                        )
                    )
                )
            ),
            None,
        )
        if previous is None:
            break
        used.add(id(previous))
        chain.insert(0, previous)
        cursor_day = int(previous.day_idx)
        cursor_min = int(previous.start_min)
    return chain


def _transition_setup_is_sufficient(
    segments: list[Segment],
    previous: Segment | None,
    following: Segment | None,
    lots_by_id: dict[str, Lot],
    config: FactoryConfig,
    data: EngineData,
) -> bool:
    if previous is None or following is None:
        return True
    if segment_setup_identity(previous) == segment_setup_identity(following):
        return True
    lot = lots_by_id.get(following.lot_id)
    required = max(
        0.0,
        float(following.run_setup_min or 0.0),
        float(lot.setup_min if lot is not None else 0.0),
    )
    actual = sum(
        float(segment.setup_min)
        for segment in _contiguous_setup_chain(segments, following, config, data)
    )
    return actual + 0.01 >= required


def _full_move_preserves_machine_setups(
    segments: list[Segment],
    source: Segment,
    setup_chain: list[Segment],
    lots_by_id: dict[str, Lot],
    config: FactoryConfig,
    data: EngineData,
    target_day: int,
    target_end: int,
) -> bool:
    """Check the two machine transitions changed by relocating a whole block."""

    target_abs = target_day * 1440 + int(target_end)
    target_following = min(
        (
            other
            for other in segments
            if other is not source
            and other.machine_id == source.machine_id
            and other.prod_min > 0
            and other.day_idx * 1440 + int(other.start_min) >= target_abs
        ),
        key=lambda item: (item.day_idx, item.start_min),
        default=None,
    )
    if not _transition_setup_is_sufficient(
        segments,
        source,
        target_following,
        lots_by_id,
        config,
        data,
    ):
        return False

    source_end = source.day_idx * 1440 + int(source.end_min)
    removed_ids = {id(segment) for segment in setup_chain}
    removed_ids.add(id(source))
    source_following = min(
        (
            other
            for other in segments
            if id(other) not in removed_ids
            and other.machine_id == source.machine_id
            and other.prod_min > 0
            and other.day_idx * 1440 + int(other.start_min) >= source_end
        ),
        key=lambda item: (item.day_idx, item.start_min),
        default=None,
    )
    if source_following is None:
        return True

    following_start = source_following.day_idx * 1440 + int(
        source_following.start_min
    )
    source_previous = max(
        (
            other
            for other in segments
            if id(other) not in removed_ids
            and other.machine_id == source.machine_id
            and other.prod_min > 0
            and other.day_idx * 1440 + int(other.end_min) <= following_start
        ),
        key=lambda item: (item.day_idx, item.end_min),
        default=None,
    )
    if target_abs <= following_start and (
        source_previous is None
        or source_previous.day_idx * 1440 + int(source_previous.end_min)
        <= target_abs
    ):
        source_previous = source
    return _transition_setup_is_sufficient(
        segments,
        source_previous,
        source_following,
        lots_by_id,
        config,
        data,
    )


def _campaign_bridge_blocker(
    segments: list[Segment],
    source: Segment,
    start_abs: int,
    end_abs: int,
) -> Segment | None:
    """Return work that would unmount a tool between two campaign pieces."""

    if end_abs <= start_abs:
        return None
    source_identity = segment_setup_identity(source)
    return next(
        (
            other
            for other in sorted(
                segments,
                key=lambda item: (item.day_idx, item.start_min, item.machine_id),
            )
            if other is not source
            and other.end_min > other.start_min
            and start_abs < other.day_idx * 1440 + int(other.end_min)
            and other.day_idx * 1440 + int(other.start_min) < end_abs
            and (
                (
                    other.machine_id == source.machine_id
                    and segment_setup_identity(other)
                    != source_identity
                )
                or (
                    other.tool_id == source.tool_id
                    and other.machine_id != source.machine_id
                )
            )
        ),
        None,
    )


def _scheduled_resource_reason(
    code: str,
    other: Segment,
    day_idx: int,
    data: EngineData,
    lots_by_id: dict[str, Lot],
    moving_lot: Lot | None,
    **fields: object,
) -> str:
    competing = lots_by_id.get(other.lot_id)
    return _reason(
        code,
        day=day_idx,
        date=_date_label(day_idx, data),
        interval=f"{_fmt_minute(other.start_min)}-{_fmt_minute(other.end_min)}",
        lot=other.lot_id,
        sku=other.sku,
        target_rupture=(
            lot_priority_key(moving_lot)[0] if moving_lot is not None else ""
        ),
        competing_rupture=(
            lot_priority_key(competing)[0] if competing is not None else ""
        ),
        target_priority=(
            int(moving_lot.planning_priority or 0) if moving_lot is not None else ""
        ),
        competing_priority=(
            int(competing.planning_priority or 0) if competing is not None else ""
        ),
        **fields,
    )


def _higher_priority_campaign_reason(
    segments: list[Segment],
    source: Segment,
    lots_by_id: dict[str, Lot],
    moving_lot: Lot | None,
    day_idx: int,
    start: int,
    end: int,
    context: LegalIntervalContext | None = None,
) -> str | None:
    if moving_lot is None:
        return None
    priorities = context.lot_priorities if context is not None else {}
    moving_priority = (
        priorities.get(moving_lot.id) or lot_priority_key(moving_lot)
    )[:-1]
    target_start = day_idx * 1440 + start
    target_end = day_idx * 1440 + end
    if context is not None:
        by_lot = context.productive_by_machine_lot.get(source.machine_id, {})
    else:
        mutable_by_lot: dict[str, list[Segment]] = {}
        for segment in segments:
            if (
                segment is not source
                and segment.machine_id == source.machine_id
                and segment.lot_id != source.lot_id
                and segment.prod_min > 0
            ):
                mutable_by_lot.setdefault(segment.lot_id, []).append(segment)
        by_lot = mutable_by_lot
    for lot_id, productive in by_lot.items():
        if lot_id == source.lot_id:
            continue
        protected = lots_by_id.get(lot_id)
        protected_priority = (
            priorities.get(lot_id) or lot_priority_key(protected)
            if protected is not None
            else ()
        )
        if protected is None or protected_priority[:-1] >= moving_priority:
            continue
        ordered = (
            productive
            if context is not None
            else sorted(productive, key=lambda item: (item.day_idx, item.start_min))
        )
        for previous, following in zip(ordered, ordered[1:]):
            previous_end = previous.day_idx * 1440 + int(previous.end_min)
            following_start = following.day_idx * 1440 + int(following.start_min)
            if previous_end <= target_start and target_end <= following_start:
                return _reason(
                    "blocked_by_priority_higher_risk_lot",
                    lot=lot_id,
                    day=day_idx,
                    interval=f"{start}-{end}",
                )
    return None


def evaluate_legal_interval(
    segments: list[Segment],
    source: Segment,
    data: EngineData,
    config: FactoryConfig,
    day_idx: int,
    start: int,
    end: int,
    *,
    setup_min: float = 0.0,
    lots_by_id: dict[str, Lot] | None = None,
    moving_lot: Lot | None = None,
    ignored_lot_ids: Collection[str] = (),
    context: LegalIntervalContext | None = None,
    explain: bool = True,
) -> LegalIntervalEvaluation:
    """Evaluate an exact slot against every shared physical resource.

    Planner repairs, the operational auditor and user-facing explanations use
    this function so an interval cannot be called free by one subsystem and
    blocked by another. Searches may skip explanations and stop at the first
    blocker; accepted intervals still pass every check.
    """

    from backend.transform.calendars import calendar_window

    projected = calendar_window(data, config, day_idx, from_day=day_idx)
    if projected is not data:
        data = projected
        context = None
    ignored = set(ignored_lot_ids)
    shift_id = _shift_for_interval(config, start, end)
    reasons: list[str] = []
    if end <= start:
        reasons.append(_reason("blocked_by_invalid_interval", day=day_idx))
    if shift_id is None:
        reasons.append(
            _reason(
                "blocked_by_shift_boundary",
                day=day_idx,
                interval=f"{start}-{end}",
            )
        )
    if not is_factory_workday(day_idx, data, config):
        reasons.append(
            _reason(
                "blocked_by_holiday",
                day=day_idx,
                date=_date_label(day_idx, data),
                interval=(
                    f"{_fmt_minute(config.shift_a_start)}-"
                    f"{_fmt_minute(config.shift_b_end)}"
                ),
            )
        )

    machine_cfg = config.machines.get(source.machine_id)
    if machine_cfg is not None and not machine_cfg.active:
        reasons.append(
            _reason(
                "blocked_by_inactive_machine",
                day=day_idx,
                date=_date_label(day_idx, data),
                interval=(
                    f"{_fmt_minute(config.shift_a_start)}-"
                    f"{_fmt_minute(config.shift_b_end)}"
                ),
                machine=source.machine_id,
            )
        )
    if day_idx in data.machine_blocked_days.get(source.machine_id, set()):
        reasons.append(
            _reason("blocked_by_machine_busy", day=day_idx, machine=source.machine_id)
        )
    if day_idx in data.tool_blocked_days.get(source.tool_id, set()):
        reasons.append(_reason("blocked_by_tool_busy", day=day_idx, tool=source.tool_id))
    if reasons and not explain:
        return LegalIntervalEvaluation(False, shift_id, tuple(reasons))

    day_segments = (
        context.segments_by_day.get(day_idx, ())
        if context is not None
        else segments
    )
    for other in day_segments:
        if (
            other is source
            or other.lot_id in ignored
            or other.day_idx != day_idx
            or other.end_min <= other.start_min
            or not _overlaps(start, end, int(other.start_min), int(other.end_min))
        ):
            continue
        if not explain and (
            other.machine_id == source.machine_id or other.tool_id == source.tool_id
        ):
            return LegalIntervalEvaluation(False, shift_id)
        if other.machine_id == source.machine_id:
            reasons.append(
                _scheduled_resource_reason(
                    "blocked_by_machine_busy",
                    other,
                    day_idx=day_idx,
                    data=data,
                    lots_by_id=lots_by_id or {},
                    moving_lot=moving_lot,
                    machine=source.machine_id,
                )
            )
            if (
                moving_lot is not None
                and (other_lot := (lots_by_id or {}).get(other.lot_id)) is not None
                and lot_priority_key(other_lot) < lot_priority_key(moving_lot)
            ):
                reasons.append(
                    _scheduled_resource_reason(
                        "blocked_by_priority_higher_risk_lot",
                        other,
                        day_idx=day_idx,
                        data=data,
                        lots_by_id=lots_by_id or {},
                        moving_lot=moving_lot,
                        machine=source.machine_id,
                    )
                )
        elif other.tool_id == source.tool_id:
            reasons.append(
                _scheduled_resource_reason(
                    "blocked_by_tool_busy",
                    other,
                    day_idx=day_idx,
                    data=data,
                    lots_by_id=lots_by_id or {},
                    moving_lot=moving_lot,
                    tool=source.tool_id,
                    machine=other.machine_id,
                )
            )

    for code, resource, blocks in (
        (
            "blocked_by_machine_busy",
            ("machine", source.machine_id),
            data.machine_blocked_intervals.get(source.machine_id, []),
        ),
        (
            "blocked_by_tool_busy",
            ("tool", source.tool_id),
            data.tool_blocked_intervals.get(source.tool_id, []),
        ),
    ):
        resource_key, resource_value = resource
        for block in blocks:
            if int(block.get("start_day", -1)) != day_idx:
                continue
            if not _overlaps(
                start,
                end,
                int(block.get("start_min", 0)),
                int(block.get("end_min", 1440)),
            ):
                continue
            if not explain:
                return LegalIntervalEvaluation(False, shift_id)
            reasons.append(
                _reason(
                    code,
                    day=day_idx,
                    date=_date_label(day_idx, data),
                    interval=(
                        f"{_fmt_minute(int(block.get('start_min', 0)))}-"
                        f"{_fmt_minute(int(block.get('end_min', 1440)))}"
                    ),
                    source="unavailability",
                    category=block.get("category", ""),
                    reason=block.get("reason", ""),
                    **{resource_key: resource_value},
                )
            )

    if shift_id is None:
        return LegalIntervalEvaluation(False, None, tuple(dict.fromkeys(reasons)))

    group = config.machine_groups.get(source.machine_id, "Grandes")
    setup_end = min(end, start + max(0.0, setup_min))
    if setup_end > start:
        from backend.scheduler.resources import reserved_setup_segments

        setup_candidates = (
            context.setups_by_group_day.get((group, day_idx), ())
            if context is not None
            else segments
        )
        setup_intervals = [
            other
            for other in [*setup_candidates, *reserved_setup_segments(data)]
            if other is not source
            and other.lot_id not in ignored
            and other.day_idx == day_idx
            and other.setup_min > 0
            and config.machine_groups.get(other.machine_id, "Grandes") == group
            and _overlaps(
                start,
                setup_end,
                int(other.start_min),
                other.production_start_min,
            )
        ]
        boundaries = {start, setup_end}
        for other in setup_intervals:
            boundaries.update(
                (
                    max(start, int(other.start_min)),
                    min(setup_end, other.production_start_min),
                )
            )
        capacity = max(1, int(config.setup_crews_by_group.get(group, 1)))
        points = sorted(boundaries)
        for left, right in zip(points, points[1:]):
            active = [
                other
                for other in setup_intervals
                if _overlaps(
                    left,
                    right,
                    int(other.start_min),
                    other.production_start_min,
                )
            ]
            if right <= left or len(active) < capacity:
                continue
            if not explain:
                return LegalIntervalEvaluation(False, shift_id)
            reasons.append(
                _reason(
                    "blocked_by_setup_crew",
                    day=day_idx,
                    date=_date_label(day_idx, data),
                    interval=f"{_fmt_minute(left)}-{_fmt_minute(right)}",
                    group=group,
                    capacity=capacity,
                    occupied=len(active),
                    competing_lots=",".join(
                        sorted({other.lot_id for other in active})
                    ),
                    competing_machines=",".join(
                        sorted({other.machine_id for other in active})
                    ),
                )
            )
            break

    production_start = setup_end
    if production_start < end:
        required = (
            context.operator_demand_by_segment.get(id(source))
            if context is not None
            else None
        ) or segment_operator_demand(source, data)
        capacity = effective_operator_capacity(data, config, day_idx, group, shift_id)
        production_candidates = (
            context.production_by_group_day.get((group, day_idx), ())
            if context is not None
            else segments
        )
        operator_segments = [
            other
            for other in production_candidates
            if other is not source
            and other.lot_id not in ignored
            and other.day_idx == day_idx
            and other.prod_min > 0
            and config.machine_groups.get(other.machine_id, "Grandes") == group
            and _overlaps(
                production_start,
                end,
                other.production_start_min,
                int(other.end_min),
            )
        ]
        operator_blocks = [
            block
            for block in data.operator_blocked_intervals
            if int(block.get("start_day", -1)) == day_idx
            and str(block.get("group", "")) == group
            and str(block.get("shift", "")) == shift_id
            and _overlaps(
                production_start,
                end,
                float(block.get("start_min", 0)),
                float(block.get("end_min", 1440)),
            )
        ]
        boundaries = {production_start, end}
        for other in operator_segments:
            boundaries.update(
                (
                    max(production_start, other.production_start_min),
                    min(end, int(other.end_min)),
                )
            )
        for block in operator_blocks:
            boundaries.update(
                (
                    max(production_start, float(block.get("start_min", 0))),
                    min(end, float(block.get("end_min", 1440))),
                )
            )
        points = sorted(boundaries)
        for left, right in zip(points, points[1:]):
            if right <= left:
                continue
            used = sum(
                (
                    context.operator_demand_by_segment.get(id(other))
                    if context is not None
                    else None
                )
                or segment_operator_demand(other, data)
                for other in operator_segments
                if _overlaps(
                    left,
                    right,
                    other.production_start_min,
                    int(other.end_min),
                )
            )
            unavailable = sum(
                max(0, int(block.get("count", 1)))
                for block in operator_blocks
                if _overlaps(
                    left,
                    right,
                    float(block.get("start_min", 0)),
                    float(block.get("end_min", 1440)),
                )
            )
            if used + required > max(0, capacity - unavailable):
                if not explain:
                    return LegalIntervalEvaluation(False, shift_id)
                competing_lots = sorted(
                    {
                        other.lot_id
                        for other in operator_segments
                        if _overlaps(
                            left,
                            right,
                            other.production_start_min,
                            int(other.end_min),
                        )
                    }
                )
                reasons.append(
                    _reason(
                        "blocked_by_operator_capacity",
                        day=day_idx,
                        date=_date_label(day_idx, data),
                        interval=f"{_fmt_minute(left)}-{_fmt_minute(right)}",
                        group=group,
                        shift=shift_id,
                        capacity=capacity,
                        unavailable=unavailable,
                        occupied=used,
                        required=required,
                        competing_lots=",".join(competing_lots),
                    )
                )
                break

    priority_reason = _higher_priority_campaign_reason(
        segments,
        source,
        lots_by_id or {},
        moving_lot,
        day_idx,
        start,
        end,
        context,
    )
    if priority_reason is not None:
        reasons.append(priority_reason)

    unique = tuple(dict.fromkeys(reasons))
    return LegalIntervalEvaluation(not unique, shift_id, unique)


def candidate_interval_boundaries(
    segments: list[Segment],
    source: Segment,
    data: EngineData,
    config: FactoryConfig,
    day_idx: int,
    gap_start: int,
    gap_end: int,
    context: LegalIntervalContext | None = None,
) -> list[float]:
    boundaries = {float(gap_start), float(gap_end)}
    for shift in config.shifts:
        if gap_start < int(shift.start_min) < gap_end:
            boundaries.add(int(shift.start_min))
        if gap_start < int(shift.end_min) < gap_end:
            boundaries.add(int(shift.end_min))
    day_segments = (
        context.segments_by_day.get(day_idx, ())
        if context is not None
        else segments
    )
    for other in day_segments:
        if other is source or other.day_idx != day_idx:
            continue
        if (
            other.machine_id == source.machine_id
            or other.tool_id == source.tool_id
            or config.machine_groups.get(other.machine_id, "Grandes")
            == config.machine_groups.get(source.machine_id, "Grandes")
        ):
            boundaries.add(max(gap_start, min(gap_end, int(other.start_min))))
            boundaries.add(max(gap_start, min(gap_end, int(other.end_min))))
            if other.setup_min > 0:
                boundaries.add(
                    max(
                        gap_start,
                        min(gap_end, other.production_start_min),
                    )
                )
    for block in (
        data.machine_blocked_intervals.get(source.machine_id, [])
        + data.tool_blocked_intervals.get(source.tool_id, [])
        + data.operator_blocked_intervals
    ):
        if int(block.get("start_day", -1)) != day_idx:
            continue
        boundaries.add(max(gap_start, min(gap_end, float(block.get("start_min", 0)))))
        boundaries.add(max(gap_start, min(gap_end, float(block.get("end_min", 1440)))))
    # The setup crew may be busy with protected work (history) on another
    # machine of the group. The moment it becomes free must be a candidate
    # start, otherwise the lot waits for the next shift or day (BFP112, §2.1).
    from backend.scheduler.resources import reserved_setup_segments

    group = config.machine_groups.get(source.machine_id, "Grandes")
    for reserved in reserved_setup_segments(data):
        if (
            reserved.day_idx != day_idx
            or config.machine_groups.get(reserved.machine_id, "Grandes") != group
        ):
            continue
        boundaries.add(max(gap_start, min(gap_end, int(reserved.start_min))))
        boundaries.add(
            max(gap_start, min(gap_end, reserved.production_start_min))
        )
    return sorted(boundaries)


def candidate_setup_starts(
    boundaries: Collection[float],
    setup_min: float,
    earliest: int,
    latest: int,
) -> list[int]:
    """Include preparation starts that finish at a resource availability event."""
    # Operators are required only after preparation. Each event may therefore
    # unlock either setup or production; the interval validator decides which.
    setup = max(0.0, float(setup_min))
    return sorted(
        {
            start
            for boundary in boundaries
            for start in (math.ceil(boundary), math.ceil(boundary - setup))
            if earliest <= start <= latest
        }
    )


def _available_intervals(
    segments: list[Segment],
    source: Segment,
    data: EngineData,
    config: FactoryConfig,
    day_idx: int,
    gap_start: int,
    gap_end: int,
    *,
    lots_by_id: dict[str, Lot],
    moving_lot: Lot,
    context: LegalIntervalContext,
) -> list[tuple[int, int]]:
    points = candidate_interval_boundaries(
        segments,
        source,
        data,
        config,
        day_idx,
        gap_start,
        gap_end,
        context,
    )
    available: list[tuple[float, float]] = []
    for start, end in zip(points, points[1:]):
        evaluation = evaluate_legal_interval(
            segments,
            source,
            data,
            config,
            day_idx,
            start,
            end,
            lots_by_id=lots_by_id,
            moving_lot=moving_lot,
            context=context,
            explain=False,
        )
        if end <= start or not evaluation.allowed:
            continue
        if (
            available
            and available[-1][1] == start
            and _shift_for_interval(config, available[-1][0], end) is not None
        ):
            previous_start, _previous_end = available[-1]
            available[-1] = (previous_start, end)
        else:
            available.append((start, end))
    return [(math.ceil(start), math.floor(end)) for start, end in available
            if math.ceil(start) < math.floor(end)]


def find_internal_continuation_opportunities(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    context: LegalIntervalContext | None = None,
) -> list[PartialGapOpportunity]:
    """Find partial moves inside a still-mounted tool campaign.

    A campaign can cross lot/run identifiers when the physical tool remains on
    the same machine. This catches both an interrupted lot and a later lot of
    the same tool that can continue in an earlier partial slot without a new
    setup.
    """

    lots_by_id = {lot.id: lot for lot in lots}
    context = context or build_legal_interval_context(segments, lots, data, config)
    holidays = calendar_holidays(data, -7, data.n_days + 7)
    result: list[PartialGapOpportunity] = []

    productive = sorted(
        (
            segment
            for segment in segments
            if segment.prod_min > 0
            and segment.setup_min <= 0
            and segment.end_min > segment.start_min
            and segment.lot_id in lots_by_id
        ),
        key=lambda item: (
            lot_priority_key(lots_by_id[item.lot_id]),
            item.day_idx,
            item.start_min,
            item.machine_id,
            item.lot_id,
        ),
    )
    seen_lots: set[str] = set()
    for source in productive:
        if source.lot_id in seen_lots:
            continue
        lot = lots_by_id[source.lot_id]
        source_start = (source.day_idx, int(source.start_min))
        previous = max(
            (
                other
                for other in segments
                if other is not source
                and other.machine_id == source.machine_id
                and segment_setup_identity(other) == segment_setup_identity(source)
                and other.prod_min > 0
                and (other.day_idx, int(other.end_min)) <= source_start
            ),
            key=lambda item: (item.day_idx, item.end_min),
            default=None,
        )
        if previous is None:
            continue
        previous_end = (previous.day_idx, int(previous.end_min))
        if previous_end >= source_start:
            continue
        if _campaign_bridge_blocker(
            segments,
            source,
            previous.day_idx * 1440 + int(previous.end_min),
            source.day_idx * 1440 + int(source.start_min),
        ) is not None:
            continue

        floor = max(0, earliest_allowed_start(lot, holidays))
        opportunity: PartialGapOpportunity | None = None
        for day_idx in range(max(floor, previous.day_idx), source.day_idx + 1):
            gap_start = (
                int(previous.end_min)
                if day_idx == previous.day_idx
                else int(config.shift_a_start)
            )
            gap_end = (
                int(source.start_min)
                if day_idx == source.day_idx
                else int(config.shift_b_end)
            )
            if gap_end - gap_start < max(1, int(math.ceil(config.min_prod_min))):
                continue
            for start, end in _available_intervals(
                segments,
                source,
                data,
                config,
                day_idx,
                gap_start,
                gap_end,
                lots_by_id=lots_by_id,
                moving_lot=lot,
                context=context,
            ):
                movable = min(float(source.prod_min), float(end - start))
                if movable + 1e-9 < float(config.min_prod_min):
                    continue
                opportunity = PartialGapOpportunity(
                    lot_id=source.lot_id,
                    machine_id=source.machine_id,
                    tool_id=source.tool_id,
                    gap_day=day_idx,
                    gap_start_min=start,
                    gap_end_min=end,
                    movable_prod_min=movable,
                    source_day=source.day_idx,
                    source_start_min=int(source.start_min),
                    source_end_min=int(source.end_min),
                    source_qty=int(source.qty),
                )
                break
            if opportunity is not None:
                break
        if opportunity is not None:
            result.append(opportunity)
            seen_lots.add(source.lot_id)

    priority = {lot.id: lot_priority_key(lot) for lot in lots}
    return sorted(
        result,
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


def find_opening_gap_opportunities(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    context: LegalIntervalContext | None = None,
    allow_setup_free: bool = False,
) -> list[PartialGapOpportunity]:
    """Find the earliest partial slot for a campaign's setup and production.

    Unlike the historical whole-block repair, this detector can use the useful
    remainder of a shift.  Moving even a small productive prefix is safe when
    the setup travels with it and the tool stays mounted until the source
    continuation.
    """

    from backend.scheduler.resources import build_setup_override_map, resolve_setup_hours

    lots_by_id = {lot.id: lot for lot in lots}
    ops_by_id = {op.id: op for op in data.ops}
    setup_overrides = build_setup_override_map(config)
    context = context or build_legal_interval_context(segments, lots, data, config)
    holidays = calendar_holidays(data, -7, data.n_days + 7)
    opportunities: list[PartialGapOpportunity] = []

    for lot in sorted(lots, key=lot_priority_key):
        productive = sorted(
            (
                segment
                for segment in segments
                if segment.lot_id == lot.id
                and segment.prod_min > 0
                and segment.end_min > segment.start_min
            ),
            key=lambda item: (item.day_idx, item.start_min),
        )
        if not productive:
            continue
        source = productive[0]
        setup_chain = _contiguous_setup_chain(segments, source, config, data)
        setup_min = sum(float(segment.setup_min) for segment in setup_chain)
        if setup_min <= 0 and not allow_setup_free:
            # A zero prefix can be a continuation with preparation elsewhere.
            # Only a canonically setup-free operation may open without it.
            outputs = lot.twin_outputs or [(lot.op_id, lot.sku, lot.qty)]
            if not all(
                (op := ops_by_id.get(op_id)) is not None
                and resolve_setup_hours(sku, source.machine_id, op.sH, config, setup_overrides) <= 0
                for op_id, sku, _qty in outputs
            ):
                continue

        floor = max(0, earliest_allowed_start(lot, holidays))
        source_abs = source.day_idx * 1440 + int(source.start_min)
        opportunity: PartialGapOpportunity | None = None
        for day_idx in range(floor, source.day_idx + 1):
            boundaries = candidate_interval_boundaries(
                segments,
                source,
                data,
                config,
                day_idx,
                int(config.shift_a_start),
                int(config.shift_b_end),
                context,
            )
            for shift in config.shifts:
                shift_start = int(shift.start_min)
                shift_end = int(shift.end_min)
                latest_end = shift_end
                if day_idx == source.day_idx:
                    # A complete source block may be relocated into a slot
                    # that overlaps its old position because that old block
                    # disappears. Partial moves must still end before the
                    # residual starts below.
                    latest_end = min(latest_end, int(source.end_min))
                if latest_end - shift_start <= setup_min:
                    continue

                starts = candidate_setup_starts(
                    boundaries,
                    setup_min,
                    shift_start,
                    latest_end - 1,
                )
                for start in starts:
                    if (day_idx, start) >= (source.day_idx, int(source.start_min)):
                        continue
                    productive_room = float(latest_end - start) - setup_min
                    if productive_room + 1e-9 < float(config.min_prod_min):
                        continue

                    max_moved_prod = min(float(source.prod_min), productive_room)
                    minimum_end = start + int(
                        math.ceil(setup_min + float(config.min_prod_min))
                    )
                    maximum_end = start + int(
                        math.ceil(setup_min + max_moved_prod)
                    )
                    candidate_ends = sorted(
                        {
                            minimum_end,
                            maximum_end,
                            *(
                                [int(source.start_min)]
                                if day_idx == source.day_idx
                                and minimum_end
                                <= int(source.start_min)
                                <= maximum_end
                                else []
                            ),
                            *(
                                math.floor(boundary)
                                for boundary in boundaries
                                if minimum_end < math.floor(boundary) < maximum_end
                            ),
                        }
                    )
                    legal_candidates: list[tuple[int, float]] = []
                    for candidate_end in candidate_ends:
                        moved_prod = min(
                            float(source.prod_min),
                            float(candidate_end - start) - setup_min,
                        )
                        if moved_prod + 1e-9 < float(config.min_prod_min):
                            continue
                        if (
                            day_idx == source.day_idx
                            and moved_prod < float(source.prod_min) - 1e-9
                            and candidate_end > int(source.start_min)
                        ):
                            continue
                        evaluation = evaluate_legal_interval(
                            segments,
                            source,
                            data,
                            config,
                            day_idx,
                            start,
                            candidate_end,
                            setup_min=setup_min,
                            lots_by_id=lots_by_id,
                            moving_lot=lot,
                            ignored_lot_ids={lot.id},
                            context=context,
                            explain=False,
                        )
                        if not evaluation.allowed:
                            # Resource conflicts are monotonic for one fixed
                            # start: a longer contiguous interval still
                            # contains the first blocked sub-interval.
                            break
                        legal_candidates.append((candidate_end, moved_prod))

                    for candidate_end, moved_prod in reversed(legal_candidates):
                        remaining_prod = float(source.prod_min) - moved_prod
                        following = next(
                            (
                                segment
                                for segment in productive
                                if (segment.day_idx, segment.start_min)
                                > (source.day_idx, source.start_min)
                            ),
                            None,
                        )
                        bridge_end = None
                        if remaining_prod > 1e-9:
                            bridge_end = source_abs
                        elif following is not None:
                            bridge_end = (
                                following.day_idx * 1440 + int(following.start_min)
                            )
                        if bridge_end is not None and _campaign_bridge_blocker(
                            segments,
                            source,
                            day_idx * 1440 + candidate_end,
                            bridge_end,
                        ) is not None:
                            continue
                        if remaining_prod <= 1e-9 and not _full_move_preserves_machine_setups(
                            segments,
                            source,
                            setup_chain,
                            lots_by_id,
                            config,
                            data,
                            day_idx,
                            candidate_end,
                        ):
                            continue

                        opportunity = PartialGapOpportunity(
                            lot_id=source.lot_id,
                            machine_id=source.machine_id,
                            tool_id=source.tool_id,
                            gap_day=day_idx,
                            gap_start_min=start,
                            gap_end_min=candidate_end,
                            movable_prod_min=moved_prod,
                            source_day=source.day_idx,
                            source_start_min=int(source.start_min),
                            source_end_min=int(source.end_min),
                            source_qty=int(source.qty),
                            movable_setup_min=setup_min,
                        )
                        break
                    if opportunity is not None:
                        break
                if opportunity is not None:
                    break
            if opportunity is not None:
                break
        if opportunity is not None:
            opportunities.append(opportunity)

    return opportunities


def find_gap_opportunities(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    context: LegalIntervalContext | None = None,
    allow_setup_free_opening: bool = False,
) -> list[PartialGapOpportunity]:
    """Return every canonical earlier-slot opportunity for one plan snapshot.

    Keeping this aggregation here means normalization, explainability and the
    operational gate all inspect the same two classes of legal move.
    """

    context = context or build_legal_interval_context(segments, lots, data, config)
    return [
        *find_internal_continuation_opportunities(
            segments, lots, data, config, context=context
        ),
        *find_opening_gap_opportunities(
            segments,
            lots,
            data,
            config,
            context=context,
            allow_setup_free=allow_setup_free_opening,
        ),
    ]


def _proportional_prefix(total: int, moved: float, original: float) -> int:
    if total <= 0 or original <= 0 or moved <= 0:
        return 0
    if moved >= original - 1e-9:
        return total
    return max(0, min(total, int(math.floor(total * moved / original + 0.5))))


def _merge_twin_outputs(
    first: list[tuple[str, str, int]] | None,
    second: list[tuple[str, str, int]] | None,
) -> list[tuple[str, str, int]] | None:
    if first is None and second is None:
        return None
    totals: dict[tuple[str, str], int] = {}
    order: list[tuple[str, str]] = []
    for outputs in (first or [], second or []):
        for op_id, sku, qty in outputs:
            key = (op_id, sku)
            if key not in totals:
                order.append(key)
                totals[key] = 0
            totals[key] += int(qty)
    return [(op_id, sku, totals[(op_id, sku)]) for op_id, sku in order]


def _merge_contiguous_segments(
    segments: list[Segment], *, protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Merge adjacent pieces of the same run without crossing a shift."""

    ordered = sorted(
        segments,
        key=lambda item: (item.day_idx, item.start_min, item.machine_id),
    )
    result: list[Segment] = []
    for segment in ordered:
        previous = result[-1] if result else None
        if not (
            previous is not None
            and segment.lot_id not in (protected_lot_ids or ())
            and previous.lot_id == segment.lot_id
            and previous.run_id == segment.run_id
            and previous.machine_id == segment.machine_id
            and previous.tool_id == segment.tool_id
            and previous.day_idx == segment.day_idx
            and previous.shift == segment.shift
            and previous.end_min == segment.start_min
            and segment.setup_min <= 0
            and abs(
                (float(previous.end_min) - float(previous.start_min))
                - (float(previous.setup_min) + float(previous.prod_min))
            )
            <= 1.0
        ):
            result.append(segment)
            continue
        result[-1] = replace(
            previous,
            end_min=segment.end_min,
            qty=int(previous.qty) + int(segment.qty),
            prod_min=float(previous.prod_min) + float(segment.prod_min),
            twin_outputs=_merge_twin_outputs(
                previous.twin_outputs,
                segment.twin_outputs,
            ),
            left_shift_blockers=list(
                dict.fromkeys(
                    [*previous.left_shift_blockers, *segment.left_shift_blockers]
                )
            ),
        )
    return result


def split_production_at_shift_boundaries(
    segments: list[Segment],
    config: FactoryConfig,
    data: EngineData | None = None,
    _lots: list[Lot] | None = None,
    *,
    protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Materialise malformed cross-shift blocks on the productive calendar.

    A setup remains one continuous operation, but may be represented by two
    contiguous fragments when a shift changes during the setup. Counting and
    validation group those fragments by run, so this remains one physical
    preparation.
    """

    result: list[Segment] = []
    shifts = sorted(config.shifts, key=lambda shift: (shift.start_min, shift.id))
    if not shifts:
        return list(segments)
    protected = (
        planning_protected_lot_ids(data, protected_lot_ids)
        if data is not None else set(protected_lot_ids or ())
    )

    for source in segments:
        if source.lot_id in protected:
            result.append(source)
            continue
        if _shift_for_interval(config, int(source.start_min), int(source.end_min)):
            result.append(source)
            continue

        remaining_setup = float(source.setup_min)
        remaining_prod = float(source.prod_min)
        remaining_qty = int(source.qty)
        remaining_twins = list(source.twin_outputs or [])
        remaining_work = remaining_setup + remaining_prod
        if remaining_work <= 1e-9:
            result.append(source)
            continue

        day_idx = int(source.day_idx)
        cursor = int(source.start_min)
        piece_index = 0
        while remaining_work > 1e-9:
            if data is not None:
                while day_idx < data.n_days and not is_factory_workday(
                    day_idx,
                    data,
                    config,
                ):
                    day_idx += 1
                    cursor = int(shifts[0].start_min)

            selected = next(
                (
                    shift
                    for shift in shifts
                    if max(cursor, int(shift.start_min)) < int(shift.end_min)
                ),
                None,
            )
            if selected is None:
                day_idx += 1
                cursor = int(shifts[0].start_min)
                continue

            start = max(cursor, int(selected.start_min))
            available = max(0.0, float(int(selected.end_min) - start))
            if available <= 0:
                cursor = int(selected.end_min)
                continue

            piece_setup = min(remaining_setup, available)
            piece_prod = min(remaining_prod, max(0.0, available - piece_setup))
            piece_work = piece_setup + piece_prod
            last = remaining_work - piece_work <= 1e-9
            piece_qty = (
                remaining_qty
                if last
                else _proportional_prefix(
                    remaining_qty,
                    piece_prod,
                    remaining_prod,
                )
            )

            piece_twins: list[tuple[str, str, int]] | None = None
            if source.twin_outputs is not None:
                piece_twins = []
                next_remaining_twins: list[tuple[str, str, int]] = []
                for op_id, sku, qty in remaining_twins:
                    piece = int(qty) if last else _proportional_prefix(
                        int(qty),
                        piece_prod,
                        remaining_prod,
                    )
                    piece_twins.append((op_id, sku, piece))
                    next_remaining_twins.append((op_id, sku, int(qty) - piece))
                remaining_twins = next_remaining_twins

            if piece_setup > 0 or piece_prod > 1e-9:
                end = start + int(math.ceil(piece_work))
                result.append(
                    replace(
                        source,
                        day_idx=day_idx,
                        start_min=start,
                        end_min=end,
                        shift=selected.id,
                        qty=piece_qty,
                        prod_min=piece_prod,
                        setup_min=piece_setup,
                        is_continuation=source.is_continuation or piece_index > 0,
                        twin_outputs=piece_twins,
                    )
                )

            remaining_prod = max(0.0, remaining_prod - piece_prod)
            remaining_setup = max(0.0, remaining_setup - piece_setup)
            remaining_work = remaining_setup + remaining_prod
            remaining_qty -= piece_qty
            piece_index += 1
            cursor = end

    # Keep the segmentation of historical lots intact. Their stored proof
    # covers every physical fragment, even when adjacent pieces could merge.
    return _merge_contiguous_segments(
        result,
        protected_lot_ids=protected,
    )


def apply_partial_gap_move(
    segments: list[Segment],
    opportunity: PartialGapOpportunity,
    config: FactoryConfig,
    data: EngineData | None = None,
    *,
    protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Move a source prefix and leave every quantity residual on the source."""

    source = next(
        (segment for segment in segments if _source_matches(segment, opportunity)),
        None,
    )
    protected = (
        planning_protected_lot_ids(data, protected_lot_ids)
        if data is not None else set(protected_lot_ids or ())
    )
    if source is None or source.prod_min <= 0 or source.lot_id in protected:
        return list(segments)

    setup_chain = _contiguous_setup_chain(segments, source, config, data)
    if any(segment.lot_id in protected for segment in setup_chain):
        return list(segments)
    original_setup = sum(float(segment.setup_min) for segment in setup_chain)
    moved_setup = float(opportunity.movable_setup_min)
    if original_setup > 0 and abs(moved_setup - original_setup) > 1e-6:
        return list(segments)
    if original_setup <= 0:
        moved_setup = 0.0

    moved_prod = min(float(source.prod_min), float(opportunity.movable_prod_min))
    moved_duration = int(math.ceil(moved_setup + moved_prod))
    if moved_duration <= 0 or moved_duration > (
        opportunity.gap_end_min - opportunity.gap_start_min
    ):
        return list(segments)

    moved_qty = _proportional_prefix(int(source.qty), moved_prod, float(source.prod_min))
    moved_twins: list[tuple[str, str, int]] | None = None
    remaining_twins: list[tuple[str, str, int]] | None = None
    if source.twin_outputs is not None:
        moved_twins = []
        remaining_twins = []
        for op_id, sku, qty in source.twin_outputs:
            prefix = _proportional_prefix(int(qty), moved_prod, float(source.prod_min))
            moved_twins.append((op_id, sku, prefix))
            remaining_twins.append((op_id, sku, int(qty) - prefix))

    target_start = int(opportunity.gap_start_min)
    moved = replace(
        source,
        day_idx=int(opportunity.gap_day),
        start_min=target_start,
        end_min=target_start + moved_duration,
        shift=_shift_for_interval(
            config,
            target_start,
            target_start + moved_duration,
        )
        or source.shift,
        qty=moved_qty,
        prod_min=moved_prod,
        setup_min=moved_setup,
        is_continuation=moved_setup <= 0,
        twin_outputs=moved_twins,
    )

    moved_setup_ids = {id(segment) for segment in setup_chain}
    result = [
        segment
        for segment in segments
        if segment is not source and id(segment) not in moved_setup_ids
    ]
    remaining_prod = float(source.prod_min) - moved_prod
    if remaining_prod > 1e-9:
        remaining_duration = int(math.ceil(remaining_prod))
        remaining = replace(
            source,
            end_min=int(source.start_min) + remaining_duration,
            qty=int(source.qty) - moved_qty,
            prod_min=remaining_prod,
            setup_min=0.0,
            is_continuation=True,
            twin_outputs=remaining_twins,
        )
        result.append(remaining)
    result.append(moved)
    return split_production_at_shift_boundaries(
        result, config, data, protected_lot_ids=protected,
    )
