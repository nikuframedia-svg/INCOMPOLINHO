"""Revision-consistent placement reasons for the plan view."""

from __future__ import annotations

import copy
from dataclasses import asdict

from backend.plans.frozen import _current_planning_day
from backend.scheduler.explainability import annotate_left_shift_blockers


def plan_view_explanations(segments, lots, data, config):
    """Recalculate live blockers without changing the persisted schedule."""

    display_segments = copy.deepcopy(segments)
    freeze_day = _current_planning_day(data, config)
    historical = {
        segment.lot_id for segment in segments
        if segment.day_idx < freeze_day and segment.end_min > segment.start_min
    }
    anchors = {anchor.lot_id: anchor for anchor in data.plan_anchors}
    preserved = set(data.preserved_lot_proofs or {})
    protected = historical | set(anchors) | preserved
    if display_segments and lots:
        annotate_left_shift_blockers(
            display_segments, lots, data, config, protected_lot_ids=protected,
        )

    placement = {}
    for lot_id in protected:
        if lot_id in anchors:
            anchor = anchors[lot_id]
            placement[lot_id] = {
                "kind": "manual",
                "machine_id": anchor.machine_id,
                "start_at": anchor.start_at,
                "reason": anchor.reason,
                "historical": lot_id in historical,
            }
        elif lot_id in historical:
            placement[lot_id] = {"kind": "historical"}
        else:
            placement[lot_id] = {"kind": "protected"}
    for segment in display_segments:
        if segment.lot_id in protected:
            segment.left_shift_blockers = []
    return [asdict(segment) for segment in display_segments], placement
