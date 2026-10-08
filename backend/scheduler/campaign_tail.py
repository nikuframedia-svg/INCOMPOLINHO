"""Validation-gated placement of short work after a merged setup campaign.

When references explicitly share one physical adjustment, grouping them can
turn several shorter runs into a multi-day campaign. A small, no-earlier-due
run scheduled before that campaign can then be deferred to the last shift of
the campaign's completion day. Only the immediately displaced tail is reflowed.

The neighbourhood is deliberately narrow. It only exists for configured setup
families, and every candidate must conserve output, remain physically valid,
and add neither setups nor setup time. Delivery must remain no worse, both in
the aggregate ranking and for every individual order. A configured setup family
describes physical compatibility only: it never authorises a delivery loss.
Physically valid moves that would cost delivery are returned as unapplied
trade-off proposals for a human decision.
"""

from __future__ import annotations

import copy
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from backend.config.shifts import ordered_shifts
from backend.config.types import FactoryConfig
from backend.scheduler.gap_filling import (
    apply_partial_gap_move,
    find_gap_opportunities,
)
from backend.scheduler.global_jit import materialise_fixed_run
from backend.scheduler.improvement import no_loss_verdict, plan_facts
from backend.scheduler.jit_policy import calendar_holidays, earliest_allowed_start
from backend.scheduler.priority import delivery_improves, delivery_not_worse
from backend.scheduler.priority_normalization import (
    _clock_to_coord,
    _rebuild_run,
    _restore_exact_production,
    _working_days,
)
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.scheduler.validation import coverage_metrics, validate_plan
from backend.types import EngineData

_MAX_LAST_SHIFT_SHARE = 0.40


@dataclass(slots=True)
class CampaignTailResult:
    segments: list[Segment]
    moves: list[dict[str, Any]] = field(default_factory=list)
    evaluated: int = 0
    before_score: dict[str, Any] = field(default_factory=dict)
    after_score: dict[str, Any] = field(default_factory=dict)
    # Physically valid moves rejected only because they cost delivery. They
    # are descriptive proposals, never applied by this repair.
    tradeoffs: list[dict[str, Any]] = field(default_factory=list)


def campaign_tail_warnings(result: CampaignTailResult) -> list[str]:
    """Build stable audit warnings for accepted campaign-tail moves."""

    warnings = []
    if result.tradeoffs:
        skus = sorted({str(sku) for item in result.tradeoffs for sku in item.get("skus", [])})
        warnings.append(
            "Campanhas de setup: sugestão não aplicada para "
            f"{', '.join(skus)} (piora pelo menos uma entrega; exige decisão)."
        )
    if not result.moves:
        return warnings
    moved_skus = sorted(
        {
            str(sku)
            for move in result.moves
            for sku in move.get("skus", [])
        }
    )
    warnings.insert(0,
        "Campanhas de setup: referências curtas "
        f"{', '.join(moved_skus)} colocadas no turno final "
        f"({len(result.moves)} movimento(s))."
    )
    return warnings


@dataclass(slots=True)
class _RunView:
    run_id: str
    machine_id: str
    segments: list[Segment]
    productive: list[Segment]
    start_coord: int
    end_coord: int
    start: tuple[int, int]
    end: tuple[int, int]


def repair_short_runs_after_merged_campaigns(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    max_last_shift_share: float = _MAX_LAST_SHIFT_SHARE,
) -> CampaignTailResult:
    """Move eligible short runs behind long configured-family campaigns."""

    current = _sorted_segments(copy.deepcopy(segments))
    before_score = _score(current, lots, data, config)
    result = CampaignTailResult(
        segments=current,
        before_score=dict(before_score),
        after_score=dict(before_score),
    )
    shifts = ordered_shifts(config)
    if not current or not config.setup_families or len(shifts) < 2:
        return result

    final_shift = shifts[-1]
    shift_duration = int(final_shift.duration_min)
    if shift_duration <= 0:
        return result
    max_short_duration = max(1, math.floor(shift_duration * max_last_shift_share))
    working_days = _working_days(data, config)
    if not working_days:
        return result

    lots_by_id = {lot.id: lot for lot in lots}
    holidays = calendar_holidays(data, -14, data.n_days + 14)
    used_short_runs: set[str] = set()
    handled_campaigns: set[tuple[str, str]] = set()

    while True:
        views = _run_views(current, working_days, config)
        campaigns = [
            view
            for view in views
            if (view.machine_id, view.run_id) not in handled_campaigns
            and _is_long_merged_campaign(view, config)
            and view.end[1] <= int(final_shift.start_min)
        ]
        campaigns.sort(key=lambda view: (view.end_coord, view.machine_id, view.run_id))

        accepted = False
        for campaign in campaigns:
            handled_campaigns.add((campaign.machine_id, campaign.run_id))
            campaign_lots = _view_lots(campaign, lots_by_id)
            if not campaign_lots:
                continue
            campaign_due = min(_lot_due_day(lot) for lot in campaign_lots)
            day_idx = campaign.end[0]
            shift_start = _clock_to_coord(
                day_idx,
                int(final_shift.start_min),
                working_days,
                config,
            )
            shift_end = _clock_to_coord(
                day_idx,
                int(final_shift.end_min),
                working_days,
                config,
            )
            if shift_start is None or shift_end is None:
                continue
            short_runs = _eligible_short_runs(
                views,
                campaign,
                shift_start,
                lots_by_id,
                holidays,
                max_short_duration,
                used_short_runs,
            )
            if not short_runs:
                continue

            for short_view, short_run in short_runs:
                short_lots = short_run.lots
                if min(_lot_due_day(lot) for lot in short_lots) < campaign_due:
                    continue
                if any(earliest_allowed_start(lot, holidays) > day_idx for lot in short_lots):
                    continue

                duration = _run_duration(short_run)
                anchors = _insertion_anchors(
                    views,
                    campaign,
                    shift_start,
                    shift_end,
                    duration,
                )
                for anchor in anchors:
                    candidate = _build_tail_candidate(
                        current,
                        views,
                        short_view,
                        short_run,
                        anchor,
                        working_days,
                        lots_by_id,
                        config,
                    )
                    result.evaluated += 1
                    if candidate is None:
                        continue
                    candidate, gap_compaction_moves = _compact_exposed_machine_gaps(
                        candidate,
                        lots,
                        data,
                        config,
                        machine_id=short_view.machine_id,
                        protected_lot_ids={lot.id for lot in short_run.lots},
                        vacated_segments=short_view.segments,
                        working_days=working_days,
                    )
                    moved_segments = [
                        segment
                        for segment in candidate
                        if segment.run_id == short_run.id and segment.prod_min > 0
                    ]
                    if not moved_segments or any(
                        segment.day_idx != day_idx or segment.shift != final_shift.id
                        for segment in moved_segments
                    ):
                        continue
                    acceptance = _acceptable_score(
                        current,
                        candidate,
                        lots,
                        data,
                        config,
                        result.after_score,
                    )
                    if acceptance is None:
                        continue
                    after_score, delivery_tradeoff = acceptance
                    if delivery_tradeoff:
                        _record_tradeoff(result, short_run, campaign, after_score)
                        continue

                    moved_start = min(
                        (segment.day_idx, segment.start_min)
                        for segment in candidate
                        if segment.run_id == short_run.id
                    )
                    original_start = short_view.start
                    if moved_start <= original_start:
                        continue
                    current = candidate
                    result.segments = current
                    result.after_score = after_score
                    result.moves.append(
                        {
                            "campaign_run_id": campaign.run_id,
                            "campaign_setup_family": _campaign_family(campaign),
                            "run_id": short_run.id,
                            "lot_ids": [lot.id for lot in short_run.lots],
                            "skus": sorted({lot.sku for lot in short_run.lots}),
                            "machine_id": campaign.machine_id,
                            "from_day": original_start[0],
                            "from_min": original_start[1],
                            "to_day": moved_start[0],
                            "to_min": moved_start[1],
                            "shift": final_shift.id,
                            "gap_compaction_moves": gap_compaction_moves,
                        }
                    )
                    result.tradeoffs = [
                        item for item in result.tradeoffs if item["run_id"] != short_run.id
                    ]
                    used_short_runs.add(short_run.id)
                    accepted = True
                    break
                if accepted:
                    break
            if accepted:
                break
        if not accepted:
            return result


def _run_views(
    segments: list[Segment],
    working_days: list[int],
    config: FactoryConfig,
) -> list[_RunView]:
    grouped: dict[tuple[str, str], list[Segment]] = defaultdict(list)
    machines_by_run: dict[str, set[str]] = defaultdict(set)
    for segment in segments:
        if segment.end_min <= segment.start_min:
            continue
        grouped[(segment.machine_id, segment.run_id)].append(segment)
        machines_by_run[segment.run_id].add(segment.machine_id)

    views: list[_RunView] = []
    for (machine_id, run_id), run_segments in grouped.items():
        if len(machines_by_run[run_id]) != 1:
            continue
        productive = [segment for segment in run_segments if segment.prod_min > 0]
        if not productive:
            continue
        start_segment = min(run_segments, key=_segment_start)
        end_segment = max(run_segments, key=_segment_end)
        start_coord = _clock_to_coord(
            start_segment.day_idx,
            start_segment.start_min,
            working_days,
            config,
        )
        end_coord = _clock_to_coord(
            end_segment.day_idx,
            end_segment.end_min,
            working_days,
            config,
        )
        if start_coord is None or end_coord is None or end_coord <= start_coord:
            continue
        views.append(
            _RunView(
                run_id=run_id,
                machine_id=machine_id,
                segments=run_segments,
                productive=productive,
                start_coord=start_coord,
                end_coord=end_coord,
                start=_segment_start(start_segment),
                end=_segment_end(end_segment),
            )
        )
    return views


def _is_long_merged_campaign(view: _RunView, config: FactoryConfig) -> bool:
    tool_ids = {str(segment.tool_id).strip() for segment in view.productive}
    if len(tool_ids) != 1:
        return False
    configured = {
        "|".join(sorted(str(member).strip() for member in group if str(member).strip()))
        for group in config.setup_families.get(next(iter(tool_ids)), [])
    }
    families: dict[str, set[str]] = defaultdict(set)
    for segment in view.productive:
        family = str(segment.setup_family or "").strip()
        sku = str(segment.sku or "").strip()
        if family and sku:
            families[family].add(sku)
    merged = any(
        family in configured and len(skus) > 1
        for family, skus in families.items()
    )
    work = sum(
        max(0.0, float(segment.setup_min)) + max(0.0, float(segment.prod_min))
        for segment in view.segments
    )
    return merged and work >= int(config.day_capacity_min)


def _campaign_family(view: _RunView) -> str:
    families: dict[str, set[str]] = defaultdict(set)
    for segment in view.productive:
        family = str(segment.setup_family or "").strip()
        if family:
            families[family].add(str(segment.sku or "").strip())
    eligible = [family for family, skus in families.items() if len(skus) > 1]
    return min(eligible, default="")


def _eligible_short_runs(
    views: list[_RunView],
    campaign: _RunView,
    final_shift_start: int,
    lots_by_id: dict[str, Lot],
    holidays: set[int],
    max_duration: int,
    excluded: set[str],
) -> list[tuple[_RunView, ToolRun]]:
    candidates: list[tuple[_RunView, ToolRun]] = []
    campaign_lots = _view_lots(campaign, lots_by_id)
    if not campaign_lots:
        return candidates
    campaign_due = min(_lot_due_day(lot) for lot in campaign_lots)

    for view in views:
        if (
            view.machine_id != campaign.machine_id
            or view.run_id == campaign.run_id
            or view.run_id in excluded
        ):
            continue
        before_campaign = view.end_coord <= campaign.start_coord
        between_campaign_and_final_shift = (
            view.start_coord >= campaign.end_coord
            and view.end_coord <= final_shift_start
        )
        if not (before_campaign or between_campaign_and_final_shift):
            continue
        rebuilt = _rebuild_run(
            view.run_id,
            view.segments,
            lots_by_id,
            view.machine_id,
        )
        if rebuilt is None or _run_duration(rebuilt) > max_duration:
            continue
        if len({lot.sku for lot in rebuilt.lots}) != 1:
            continue
        if min(_lot_due_day(lot) for lot in rebuilt.lots) < campaign_due:
            continue
        if any(
            earliest_allowed_start(lot, holidays) > campaign.end[0]
            for lot in rebuilt.lots
        ):
            continue
        candidates.append((view, rebuilt))

    candidates.sort(
        key=lambda item: (
            -item[0].end_coord,
            _run_duration(item[1]),
            item[0].run_id,
        )
    )
    return candidates


def _insertion_anchors(
    views: list[_RunView],
    campaign: _RunView,
    shift_start: int,
    shift_end: int,
    duration: int,
) -> list[int]:
    anchors = {shift_start}
    for view in views:
        if (
            view.machine_id == campaign.machine_id
            and view.run_id != campaign.run_id
            and view.start_coord >= shift_start
            and view.end_coord <= shift_end
        ):
            anchors.add(view.end_coord)
    return sorted(anchor for anchor in anchors if anchor + duration <= shift_end)


def _build_tail_candidate(
    segments: list[Segment],
    views: list[_RunView],
    short_view: _RunView,
    short_run: ToolRun,
    anchor: int,
    working_days: list[int],
    lots_by_id: dict[str, Lot],
    config: FactoryConfig,
) -> list[Segment] | None:
    machine_views = sorted(
        (
            view
            for view in views
            if view.machine_id == short_view.machine_id
            and view.run_id != short_view.run_id
            and view.start_coord >= anchor
        ),
        key=lambda view: (view.start_coord, view.run_id),
    )
    replacement_runs = [short_run]
    replacement_segments = materialise_fixed_run(
        short_run,
        short_view.machine_id,
        anchor,
        working_days,
        config,
    )
    cursor = anchor + _run_duration(short_run)
    removed_ids = {short_view.run_id}

    for view in machine_views:
        if view.start_coord >= cursor:
            break
        rebuilt = _rebuild_run(
            view.run_id,
            view.segments,
            lots_by_id,
            view.machine_id,
        )
        if rebuilt is None:
            return None
        duration = _run_duration(rebuilt)
        if cursor + duration > len(working_days) * int(config.day_capacity_min):
            return None
        replacement_segments.extend(
            materialise_fixed_run(
                rebuilt,
                view.machine_id,
                cursor,
                working_days,
                config,
            )
        )
        replacement_runs.append(rebuilt)
        removed_ids.add(view.run_id)
        cursor += duration

    _restore_exact_production(replacement_segments, replacement_runs)
    candidate = [
        copy.deepcopy(segment)
        for segment in segments
        if segment.run_id not in removed_ids
    ]
    candidate.extend(replacement_segments)
    return _sorted_segments(candidate)


def _compact_exposed_machine_gaps(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    machine_id: str,
    protected_lot_ids: set[str],
    vacated_segments: list[Segment],
    working_days: list[int],
) -> tuple[list[Segment], int]:
    """Close gaps exposed by relocation without pulling the tail run back.

    Removing a short run can expose its old slot and, after the immediate
    follower moves, a chain of later continuation gaps. The canonical gap
    move is reused transactionally on that machine. The deliberately deferred
    run is protected because its same-day pre-shift gap belongs to the campaign
    tail policy and is classified separately by the operational audit.
    """

    current = _sorted_segments(segments)
    moves = 0
    holes = _merge_intervals(
        [
            (start, end)
            for segment in vacated_segments
            if (
                start := _clock_to_coord(
                    segment.day_idx,
                    segment.start_min,
                    working_days,
                    config,
                )
            )
            is not None
            and (
                end := _clock_to_coord(
                    segment.day_idx,
                    segment.end_min,
                    working_days,
                    config,
                )
            )
            is not None
            and end > start
        ]
    )
    if not holes:
        return current, moves
    max_moves = min(256, max(32, len(current) * 2))
    coverage_keys = (
        "missing_lots",
        "missing_qty",
        "unexpected_lots",
        "overproduced_qty",
        "duplicate_twin_output_qty",
        "twin_output_mismatches",
    )

    for _ in range(max_moves):
        opportunities = sorted(
            (
                opportunity
                for opportunity in find_gap_opportunities(
                    current,
                    lots,
                    data,
                    config,
                )
                if opportunity.machine_id == machine_id
                and opportunity.lot_id not in protected_lot_ids
                and _opportunity_starts_in_holes(
                    opportunity,
                    holes,
                    working_days,
                    config,
                )
            ),
            key=lambda opportunity: (
                opportunity.gap_day,
                opportunity.gap_start_min,
                opportunity.source_day,
                opportunity.source_start_min,
                opportunity.lot_id,
            ),
        )
        if not opportunities:
            break

        before_score = _score(current, lots, data, config)
        accepted = False
        for opportunity in opportunities:
            source = next(
                (
                    segment
                    for segment in current
                    if segment.lot_id == opportunity.lot_id
                    and segment.machine_id == opportunity.machine_id
                    and segment.tool_id == opportunity.tool_id
                    and segment.day_idx == opportunity.source_day
                    and segment.start_min == opportunity.source_start_min
                    and segment.end_min == opportunity.source_end_min
                    and segment.qty == opportunity.source_qty
                ),
                None,
            )
            target_start = _clock_to_coord(
                opportunity.gap_day,
                opportunity.gap_start_min,
                working_days,
                config,
            )
            target_end = (
                target_start
                + int(
                    math.ceil(
                        float(opportunity.movable_setup_min)
                        + float(opportunity.movable_prod_min)
                    )
                )
                if target_start is not None
                else None
            )
            source_end = _clock_to_coord(
                opportunity.source_day,
                opportunity.source_end_min,
                working_days,
                config,
            )
            if (
                source is None
                or target_start is None
                or target_end is None
                or source_end is None
            ):
                continue
            candidate = _sorted_segments(
                apply_partial_gap_move(current, opportunity, config, data)
            )
            if _schedule_signature(candidate) == _schedule_signature(current):
                continue
            violations = validate_plan(candidate, data, config, lots=lots)
            coverage = coverage_metrics(candidate, lots)
            if violations or any(int(coverage.get(key, 0) or 0) for key in coverage_keys):
                continue
            after_score = _score(candidate, lots, data, config)
            if not _strict_left_shift_improvement(after_score, before_score):
                continue

            residual = next(
                (
                    segment
                    for segment in candidate
                    if segment.lot_id == source.lot_id
                    and segment.run_id == source.run_id
                    and segment.machine_id == source.machine_id
                    and segment.day_idx == source.day_idx
                    and segment.start_min == source.start_min
                ),
                None,
            )
            vacancy_start = _clock_to_coord(
                source.day_idx,
                residual.end_min if residual is not None else source.start_min,
                working_days,
                config,
            )
            if vacancy_start is None:
                continue
            holes = _subtract_interval(
                _merge_intervals([*holes, (vacancy_start, source_end)]),
                target_start,
                target_end,
            )
            current = candidate
            moves += 1
            accepted = True
            break
        if not accepted:
            break

    return current, moves


def _opportunity_starts_in_holes(
    opportunity: Any,
    holes: list[tuple[int, int]],
    working_days: list[int],
    config: FactoryConfig,
) -> bool:
    start = _clock_to_coord(
        opportunity.gap_day,
        opportunity.gap_start_min,
        working_days,
        config,
    )
    return start is not None and any(left <= start < right for left, right in holes)


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _subtract_interval(
    intervals: list[tuple[int, int]],
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    remaining: list[tuple[int, int]] = []
    for left, right in intervals:
        if end <= left or right <= start:
            remaining.append((left, right))
            continue
        if left < start:
            remaining.append((left, start))
        if end < right:
            remaining.append((end, right))
    return _merge_intervals(remaining)


def _strict_left_shift_improvement(
    candidate: dict[str, Any],
    reference: dict[str, Any],
) -> bool:
    if not delivery_not_worse(candidate, reference):
        return False
    for key in (
        "hard_violations",
        "early_window_violations",
        "operator_capacity_violations",
        "setup_crew_overlaps",
        "setups",
        "setup_time_min",
    ):
        if _metric(candidate, key) > _metric(reference, key):
            return False
    return _metric(candidate, "production_time_cost") < (
        _metric(reference, "production_time_cost") - 1e-6
    )


def _strict_tail_benefit(
    candidate: dict[str, Any],
    reference: dict[str, Any],
) -> bool:
    if delivery_improves(candidate, reference):
        return True
    for key in ("setups", "setup_time_min"):
        if _metric(candidate, key) < _metric(reference, key):
            return True
    return _metric(candidate, "production_time_cost") < (
        _metric(reference, "production_time_cost") - 1e-6
    )


def _acceptable_score(
    before_segments: list[Segment],
    candidate: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    before_score: dict[str, Any],
) -> tuple[dict[str, Any], bool] | None:
    violations = validate_plan(candidate, data, config, lots=lots)
    coverage = coverage_metrics(candidate, lots)
    if violations or any(
        int(coverage.get(key, 0) or 0) > 0
        for key in (
            "missing_lots",
            "missing_qty",
            "unexpected_lots",
            "overproduced_qty",
            "duplicate_twin_output_qty",
            "twin_output_mismatches",
        )
    ):
        return None
    after_score = _score(candidate, lots, data, config)
    delivery_tradeoff = not delivery_not_worse(after_score, before_score) or not (
        no_loss_verdict(
            plan_facts(candidate, lots, data, after_score),
            plan_facts(before_segments, lots, data, before_score),
        ).admissible
    )
    if after_score.get("early_window_violations", 0) > before_score.get(
        "early_window_violations", 0
    ):
        return None
    if not delivery_tradeoff and not _strict_tail_benefit(after_score, before_score):
        # A pure deferral only reserves the final shift. Without a strict
        # gain it would leave an actionable gap behind, so it is not a move.
        return None
    if after_score.get("setups", 0) > before_score.get("setups", 0):
        return None
    if after_score.get("setup_time_min", 0) > before_score.get("setup_time_min", 0):
        return None
    if not math.isclose(
        sum(segment.prod_min for segment in candidate),
        sum(segment.prod_min for segment in before_segments),
        abs_tol=1e-6,
    ):
        return None
    return after_score, delivery_tradeoff


def _record_tradeoff(
    result: CampaignTailResult,
    short_run: ToolRun,
    campaign: _RunView,
    after_score: dict[str, Any],
) -> None:
    """Keep a bounded, descriptive summary of a rejected delivery trade-off."""

    if any(item["run_id"] == short_run.id for item in result.tradeoffs):
        return
    result.tradeoffs.append(
        {
            "kind": "campaign_tail",
            "campaign_run_id": campaign.run_id,
            "run_id": short_run.id,
            "lot_ids": [lot.id for lot in short_run.lots],
            "skus": sorted({lot.sku for lot in short_run.lots}),
            "machine_id": campaign.machine_id,
            "total_tardiness_delta": _metric(after_score, "total_tardiness")
            - _metric(result.after_score, "total_tardiness"),
            "tardy_count_delta": _metric(after_score, "tardy_count")
            - _metric(result.after_score, "tardy_count"),
            "applied": False,
        }
    )


def _metric(score: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(score.get(key, default) or 0.0)
    except (TypeError, ValueError):
        return default


def _view_lots(view: _RunView, lots_by_id: dict[str, Lot]) -> list[Lot]:
    lot_ids = {segment.lot_id for segment in view.productive}
    return [lots_by_id[lot_id] for lot_id in sorted(lot_ids) if lot_id in lots_by_id]


def _lot_due_day(lot: Lot) -> int:
    return int(lot.production_due_day if lot.production_due_day is not None else lot.edd)


def _run_duration(run: ToolRun) -> int:
    return max(0, math.ceil(run.setup_min)) + sum(
        max(1, math.ceil(lot.prod_min)) for lot in run.lots
    )


def _score(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
) -> dict[str, Any]:
    return compute_score(
        segments,
        lots,
        data,
        config=config,
        include_operational_audit=False,
    )


def _segment_start(segment: Segment) -> tuple[int, int]:
    return int(segment.day_idx), int(segment.start_min)


def _segment_end(segment: Segment) -> tuple[int, int]:
    return int(segment.day_idx), int(segment.end_min)


def _schedule_signature(segments: list[Segment]) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            segment.lot_id,
            segment.run_id,
            segment.machine_id,
            segment.day_idx,
            int(segment.start_min),
            int(segment.end_min),
            round(float(segment.setup_min), 6),
            round(float(segment.prod_min), 6),
            int(segment.qty),
        )
        for segment in _sorted_segments(segments)
    )


def _sorted_segments(segments: list[Segment]) -> list[Segment]:
    return sorted(
        segments,
        key=lambda segment: (
            segment.day_idx,
            segment.start_min,
            segment.machine_id,
            segment.run_id,
            segment.lot_id,
        ),
    )
