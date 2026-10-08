"""Operational sequencing audit for a material-release production plan.

Physical validation answers whether a plan can run.  This module answers the
separate business question: whether the final sequence still contains an
obvious earlier slot or lets a less urgent lot interrupt an urgent campaign.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.config.types import FactoryConfig
from backend.scheduler.gap_filling import PartialGapOpportunity, find_gap_opportunities
from backend.scheduler.jit_policy import calendar_holidays, earliest_allowed_start
from backend.scheduler.priority import lot_priority_key
from backend.scheduler.priority_normalization import classify_priority_order_anomalies
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData


def build_operational_audit(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig | None = None,
    *,
    gap_opportunities: list[PartialGapOpportunity] | None = None,
) -> dict[str, Any]:
    """Return stable metrics and evidence for final-plan sequencing quality."""

    anchored_lot_ids = {
        str(anchor.lot_id) for anchor in getattr(data, "plan_anchors", None) or []
    }
    preserved_lot_ids = set(getattr(data, "preserved_lot_proofs", None) or {})
    frozen_lot_ids = preserved_lot_ids | anchored_lot_ids
    all_left_shift = _left_shift_detail(
        segments,
        lots,
        data,
        config or FactoryConfig(),
        gap_opportunities=gap_opportunities,
    )
    # A gap in front of a protected lot is explained, not actionable: history
    # and manual positions are never moved by a recalculation (plan §6.4).
    left_shift_detail = []
    protected_left_shift_detail = []
    for item in all_left_shift:
        lot_id = item.get("lot_id")
        # Anchored lots also carry a preservation proof in a protected
        # replan; the explicit manual position is the reason to report.
        reason = (
            "manual_anchor" if lot_id in anchored_lot_ids
            else "historical_lot_locked" if lot_id in preserved_lot_ids
            else None
        )
        if reason is None:
            left_shift_detail.append(item)
        else:
            protected_left_shift_detail.append({**item, "protection": reason})
    interruption_detail = _lower_priority_campaign_interruptions(segments, lots)
    priority_detail = classify_priority_order_anomalies(
        segments,
        lots,
        data,
        config or FactoryConfig(),
    )
    tool_priority_detail = released_tool_priority_inversion_detail(
        segments,
        lots,
        data,
        config or FactoryConfig(),
        frozen_lot_ids=frozen_lot_ids,
    )
    for item in priority_detail:
        if (
            item.get("urgent_lot_id") in frozen_lot_ids
            or item.get("blocking_lot_id") in frozen_lot_ids
        ):
            pair = {item.get("urgent_lot_id"), item.get("blocking_lot_id")}
            historical = bool(pair & (preserved_lot_ids - anchored_lot_ids))
            item["verification_status"] = "historical_locked" if historical else "manual_locked"
            item["blocking_reason"] = "historical_lot_locked" if historical else "manual_anchor"
            item["blocking_reasons"] = [item["blocking_reason"]]
    # Only a validated rotation that reduces the anomaly count proves the
    # current order avoidable. A neutral counterfactual remains useful audit
    # evidence, but must not block an otherwise executable plan.
    avoidable_priority = sum(
        item["verification_status"] == "permutable" for item in priority_detail
    )
    return {
        "left_shift_opportunities": len(left_shift_detail),
        "lower_priority_campaign_interruptions": len(interruption_detail),
        "priority_order_anomalies": len(priority_detail),
        "avoidable_priority_order_anomalies": avoidable_priority,
        "released_tool_priority_inversions": len(tool_priority_detail),
        "left_shift_detail": left_shift_detail,
        "protected_left_shift_detail": protected_left_shift_detail,
        "campaign_interruption_detail": interruption_detail,
        "priority_order_detail": priority_detail,
        "released_tool_priority_detail": tool_priority_detail,
    }


def released_tool_priority_inversion_detail(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    frozen_lot_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Find released urgent runs placed after later work on one physical tool."""

    frozen = frozen_lot_ids or set()
    lots_by_id = {lot.id: lot for lot in lots}
    holidays = calendar_holidays(
        data,
        min((segment.day_idx for segment in segments), default=0) - 14,
        max(data.n_days, max((segment.day_idx for segment in segments), default=0)) + 30,
    )
    by_run: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        if segment.end_min > segment.start_min:
            by_run[segment.run_id].append(segment)

    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run_id, run_segments in by_run.items():
        run_lots = [
            lots_by_id[lot_id]
            for lot_id in dict.fromkeys(segment.lot_id for segment in run_segments)
            if lot_id in lots_by_id
        ]
        if not run_lots or any(lot.id in frozen for lot in run_lots):
            continue
        urgent = min(run_lots, key=lot_priority_key)
        by_tool[run_segments[0].tool_id].append(
            {
                "run_id": run_id,
                "lot": urgent,
                "start": min(_position(segment) for segment in run_segments),
                "end": max((segment.day_idx, segment.end_min) for segment in run_segments),
                "release": min(earliest_allowed_start(lot, holidays) for lot in run_lots),
                "machines": sorted({segment.machine_id for segment in run_segments}),
            }
        )

    detail: list[dict[str, Any]] = []
    for tool_id, runs in by_tool.items():
        timeline = sorted(runs, key=lambda run: (run["start"], run["run_id"]))
        for index, blocking in enumerate(timeline):
            for urgent in timeline[index + 1 :]:
                if lot_priority_key(urgent["lot"])[:5] >= lot_priority_key(blocking["lot"])[:5]:
                    continue
                if urgent["release"] > blocking["release"]:
                    continue
                detail.append(
                    {
                        "tool_id": tool_id,
                        "urgent_run_id": urgent["run_id"],
                        "urgent_lot_id": urgent["lot"].id,
                        "urgent_due_day": lot_priority_key(urgent["lot"])[0],
                        "urgent_release_day": urgent["release"],
                        "urgent_machines": urgent["machines"],
                        "blocking_run_id": blocking["run_id"],
                        "blocking_lot_id": blocking["lot"].id,
                        "blocking_due_day": lot_priority_key(blocking["lot"])[0],
                        "blocking_release_day": blocking["release"],
                        "blocking_machines": blocking["machines"],
                    }
                )
    return sorted(
        detail,
        key=lambda item: (
            item["urgent_due_day"],
            item["tool_id"],
            item["urgent_run_id"],
            item["blocking_run_id"],
        ),
    )


def _left_shift_detail(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    gap_opportunities: list[PartialGapOpportunity] | None = None,
) -> list[dict[str, Any]]:
    opportunities = (
        find_gap_opportunities(segments, lots, data, config)
        if gap_opportunities is None
        else gap_opportunities
    )
    canonical = [
        (
            opportunity,
            "partial_opening_gap"
            if opportunity.movable_setup_min > 0
            else "partial_internal_gap",
        )
        for opportunity in actionable_gap_opportunities(
            segments,
            lots,
            data,
            config,
            gap_opportunities=opportunities,
        )
    ]
    canonical.sort(
        key=lambda item: (
            item[0].gap_day,
            item[0].gap_start_min,
            item[0].source_day,
            item[0].source_start_min,
            item[0].machine_id,
            item[0].lot_id,
        )
    )
    detail = [
        {
            **opportunity.to_dict(),
            "current_day": opportunity.source_day,
            "current_start_min": opportunity.source_start_min,
            "evidence": evidence,
        }
        for opportunity, evidence in canonical
    ]
    return detail


def actionable_gap_opportunities(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    gap_opportunities: list[PartialGapOpportunity] | None = None,
) -> list[PartialGapOpportunity]:
    """Every left-shift gap is actionable.

    Setup families describe physical compatibility; they never reserve the
    final shift. A gap left before a campaign tail is therefore reported like
    any other until the improvement contract fills it or explains why not.
    """

    if gap_opportunities is not None:
        return list(gap_opportunities)
    return find_gap_opportunities(segments, lots, data, config)


def _lower_priority_campaign_interruptions(
    segments: list[Segment],
    lots: list[Lot],
) -> list[dict[str, Any]]:
    lots_by_id = {lot.id: lot for lot in lots}
    productive = [
        segment
        for segment in segments
        if segment.prod_min > 0 and segment.end_min > segment.start_min
    ]
    by_machine_lot: dict[tuple[str, str], list[Segment]] = defaultdict(list)
    by_machine: dict[str, list[Segment]] = defaultdict(list)
    for segment in productive:
        by_machine_lot[(segment.machine_id, segment.lot_id)].append(segment)
        by_machine[segment.machine_id].append(segment)

    detail: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for (machine_id, lot_id), campaign in by_machine_lot.items():
        protected = lots_by_id.get(lot_id)
        if protected is None or len(campaign) < 2:
            continue
        ordered = sorted(campaign, key=_position)
        for previous, following in zip(ordered, ordered[1:]):
            blockers = [
                segment
                for segment in by_machine[machine_id]
                if segment.lot_id != lot_id
                and _position(previous) < _position(segment) < _position(following)
            ]
            for blocker in blockers:
                blocking_lot = lots_by_id.get(blocker.lot_id)
                if blocking_lot is None:
                    continue
                if lot_priority_key(blocking_lot)[:-1] <= lot_priority_key(protected)[:-1]:
                    continue
                key = (machine_id, lot_id, blocker.lot_id)
                if key in seen:
                    continue
                seen.add(key)
                detail.append(
                    {
                        "machine_id": machine_id,
                        "urgent_lot_id": lot_id,
                        "blocking_lot_id": blocker.lot_id,
                        "gap_start_day": previous.day_idx,
                        "gap_end_day": following.day_idx,
                        "blocking_day": blocker.day_idx,
                    }
                )
    return sorted(
        detail,
        key=lambda item: (
            item["blocking_day"],
            item["machine_id"],
            item["urgent_lot_id"],
        ),
    )


def _position(segment: Segment) -> tuple[int, int]:
    return segment.day_idx, segment.start_min
