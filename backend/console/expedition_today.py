"""Expedition today — Spec 11 §4.2.

Grouped by client. Status clear.
"""

from __future__ import annotations

from collections import defaultdict

from backend.analytics.expedition import compute_expedition
from backend.analytics.order_tracking import readiness_for_entry
from backend.calendar import _day_date
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData


def _estimate_eta(
    entry,  # ExpeditionEntry
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
) -> str | None:
    """Use the quantity allocated to this order, not a later order of its SKU."""
    day = getattr(entry, "ready_day", None)
    if day is None:
        allocation = readiness_for_entry(entry, segments, lots, engine_data)
        day = allocation.ready_day if allocation is not None else None
    date = _day_date(day, engine_data) if day is not None else None
    return date.isoformat() if date else None


def compute_expedition_today(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    day_idx: int = 0,
) -> dict:
    """Return expedition summary for a given day.

    Keys: has_expeditions, clients, total_ready, total_orders, all_ready, total_pcs.
    """
    exp = compute_expedition(segments, lots, engine_data)
    today = next((d for d in exp.days if d.day_idx == day_idx), None)

    if not today or not today.entries:
        return {
            "has_expeditions": False,
            "total_orders": 0,
            "total_ready": 0,
            "all_ready": True,
            "total_pcs": 0,
            "clients": [],
        }

    by_client: dict[str, list[dict]] = defaultdict(list)
    for e in today.entries:
        by_client[e.client].append(
            {
                "sku": e.sku,
                "qty": e.order_qty,
                "status": e.status,
                "coverage_pct": e.coverage_pct,
                "shortfall": e.shortfall,
                "eta": _estimate_eta(e, segments, lots, engine_data)
                if e.status != "ready"
                else None,
            }
        )

    clients = []
    for client, orders in sorted(by_client.items()):
        ready = sum(1 for o in orders if o["status"] == "ready")
        clients.append(
            {
                "client": client,
                "orders": orders,
                "ready": ready,
                "total": len(orders),
            }
        )

    total_r = sum(c["ready"] for c in clients)
    total_o = sum(c["total"] for c in clients)

    return {
        "has_expeditions": True,
        "clients": clients,
        "total_ready": total_r,
        "total_orders": total_o,
        "all_ready": total_r == total_o,
        "total_pcs": sum(o["qty"] for c in clients for o in c["orders"]),
    }
