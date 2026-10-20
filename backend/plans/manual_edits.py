"""Manual edits and their plan anchors: one source of truth (decisão de 15/10/2026).

A manual move writes two things: the anchor that pins the lot
(``engine_data.plan_anchors``, read by every later calculation) and the edit
record the planner sees (``state.manual_edits``: who, when, why, from where).
Until 15/10/2026 several writes cleared the records but kept the anchors, so
lots stayed pinned with nothing on screen (Incompol, revisions 157-158: five
hidden pins after «Recalcular»). Now the visible list is always derived from
the anchors: one record per pinned lot, and a pin is only released together
with its record.

A move to a time of today already gone records what really ran (decisão do
Luís, 20/10/2026): its anchor has ``kind == EXECUTED``. «Recalcular plano»
keeps it (``release_manual_anchors(keep_executed=True)``); «Soltar» and a new
ISOP drop it like any pin.
"""

from __future__ import annotations

from collections.abc import Iterable

EXECUTED = "executed"


def executed_lot_ids(data) -> set[str]:
    """Lots whose anchor records what ran (``EXECUTED``)."""

    return {
        anchor.lot_id for anchor in getattr(data, "plan_anchors", None) or []
        if getattr(anchor, "kind", "") == EXECUTED
    }


def _anchor_record(anchor, data) -> dict:
    """A record for an anchor whose edit was lost (plans saved before 15/10)."""

    start_at = str(getattr(anchor, "start_at", "") or "")
    day, minute = None, None
    workdays = [str(item)[:10] for item in getattr(data, "workdays", None) or []]
    if len(start_at) >= 16 and start_at[:10] in workdays:
        day = workdays.index(start_at[:10])
        minute = int(start_at[11:13]) * 60 + int(start_at[14:16])
    return {
        "id": f"anchor_{anchor.lot_id}",
        "created_at": None,
        "lot_id": anchor.lot_id,
        "source_days": [],
        "target_day": day,
        "target_start_min": minute,
        "target_machine": anchor.machine_id,
        "reason": getattr(anchor, "reason", "") or "",
        "author": getattr(anchor, "author", "") or "utilizador",
        "previous_version_id": None,
        "delivery_risk_confirmed": False,
        **({"kind": EXECUTED} if getattr(anchor, "kind", "") == EXECUTED else {}),
    }


def synced_manual_edits(edits: Iterable[dict] | None, data) -> list[dict]:
    """The visible records of ``data.plan_anchors``: the latest per pinned lot."""

    anchors = list(getattr(data, "plan_anchors", None) or [])
    latest: dict[str, dict] = {}
    for edit in edits or []:
        if isinstance(edit, dict) and edit.get("lot_id"):
            latest[str(edit["lot_id"])] = edit
    return [latest.get(anchor.lot_id) or _anchor_record(anchor, data) for anchor in anchors]


def sync_manual_edits(state) -> list[dict]:
    """Make ``state.manual_edits`` match the anchors of ``state.engine_data``."""

    state.manual_edits = synced_manual_edits(state.manual_edits, state.engine_data)
    return state.manual_edits


def release_manual_anchors(
    state, lot_ids: Iterable[str] | None, *, keep_executed: bool = False,
) -> list[str]:
    """Release pins (``None``: all) together with their records; the released ids.

    ``keep_executed``: the records of what ran stay («Recalcular plano»).
    """

    data = state.engine_data
    anchors = list(getattr(data, "plan_anchors", None) or []) if data is not None else []
    wanted = None if lot_ids is None else {str(item) for item in lot_ids}
    released = [
        a.lot_id for a in anchors
        if (wanted is None or a.lot_id in wanted)
        and not (keep_executed and getattr(a, "kind", "") == EXECUTED)
    ]
    if data is not None:
        data.plan_anchors = [a for a in anchors if a.lot_id not in set(released)]
    state.manual_edits = [
        edit for edit in state.manual_edits or []
        if (wanted is not None or keep_executed) and str(edit.get("lot_id")) not in set(released)
    ]
    if data is not None:
        sync_manual_edits(state)
    return released
