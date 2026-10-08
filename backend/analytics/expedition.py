"""Expedition — Spec 03 §3.

Per day, per client: which orders are ready/partial/in_production/not_planned.
Crosses client_demands with cumulative production from segments.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from backend.scheduler.types import Lot, Segment
from backend.types import EngineData

from .order_tracking import compute_order_readiness


@dataclass(slots=True)
class ExpeditionEntry:
    day_idx: int
    date: str
    client: str
    sku: str
    order_qty: int
    produced_qty: int  # cumulative production for this SKU up to this day
    status: str  # ready | partial | at_subcontractor | in_production | not_planned
    coverage_pct: float  # 0-100%
    shortfall: int
    factory_produced_qty: int = 0  # cumulative factory output before external lead
    ready_day: int | None = None
    factory_ready_day: int | None = None


@dataclass(slots=True)
class ExpeditionDay:
    day_idx: int
    date: str
    entries: list[ExpeditionEntry]
    total_orders: int
    total_ready: int
    total_partial: int
    total_at_subcontractor: int
    total_in_production: int
    total_not_planned: int


@dataclass(slots=True)
class ExpeditionKPIs:
    days: list[ExpeditionDay]
    fill_rate: float  # % entries "ready"
    at_risk_count: int  # unfulfilled backlog plus the next five days


def at_risk_in_window(days: list[ExpeditionDay], start_day: int, window: int = 5) -> int:
    return sum(
        1 for day in days if day.day_idx < start_day + window
        for entry in day.entries if entry.status != "ready"
        and (entry.ready_day is None or entry.ready_day > start_day)
    )


def compute_expedition(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    *,
    start_day: int = 0,
) -> ExpeditionKPIs:
    """Build expedition view from segments + client_demands."""
    # Legacy snapshots may contain more than one route for a SKU. Aggregate all
    # operation output so analytics remain conservative and order-independent.
    sku_to_ops: dict[str, list[str]] = defaultdict(list)
    for op in engine_data.ops:
        sku_to_ops[op.sku].append(op.id)
    subcontracted_ops = {
        op.id
        for op in engine_data.ops
        if op.is_subcontracted
        or op.subcontract_company_id
        or op.subcontract_lead_time_days
        or op.subcontract_buffer_days
    }

    # Check if any segment produces for an op before a given day
    lot_to_op: dict[str, str] = {lot.id: lot.op_id for lot in lots}

    days_map: dict[int, list[ExpeditionEntry]] = defaultdict(list)
    readiness = compute_order_readiness(segments, lots, engine_data)

    for sku, demand_entries in engine_data.client_demands.items():
        op_ids = sku_to_ops.get(sku, [])
        if not op_ids:
            continue

        # Sort by (day, client) for deterministic FIFO allocation
        sorted_entries = readiness.get(sku, [])

        for allocation in sorted_entries:
            entry = allocation.entry
            if entry.order_qty <= 0:
                continue

            produced = allocation.cumulative_produced_qty
            factory_produced = allocation.cumulative_factory_qty

            entry_covered = allocation.covered_qty
            entry_shortfall = entry.order_qty - entry_covered
            entry_factory_covered = allocation.factory_covered_qty

            if entry_shortfall == 0:
                status = "ready"
            elif entry_covered > 0:
                status = "partial"
            elif any(op_id in subcontracted_ops for op_id in op_ids) and entry_factory_covered > 0:
                status = "at_subcontractor"
            elif _has_segments_before(
                segments, lots, lot_to_op, set(op_ids), entry.day_idx
            ):
                status = "in_production"
            else:
                status = "not_planned"

            coverage = (
                min(100.0, entry_covered / entry.order_qty * 100) if entry.order_qty > 0 else 100.0
            )

            days_map[entry.day_idx].append(
                ExpeditionEntry(
                    day_idx=entry.day_idx,
                    date=entry.date,
                    client=entry.client,
                    sku=sku,
                    order_qty=entry.order_qty,
                    produced_qty=produced,
                    factory_produced_qty=factory_produced,
                    status=status,
                    coverage_pct=round(coverage, 1),
                    shortfall=entry_shortfall,
                    ready_day=allocation.ready_day,
                    factory_ready_day=allocation.factory_ready_day,
                )
            )

    # Build ExpeditionDays
    expedition_days: list[ExpeditionDay] = []
    for day_idx in sorted(days_map.keys()):
        entries = days_map[day_idx]
        expedition_days.append(
            ExpeditionDay(
                day_idx=day_idx,
                date=entries[0].date if entries else "",
                entries=entries,
                total_orders=len(entries),
                total_ready=sum(1 for e in entries if e.status == "ready"),
                total_partial=sum(1 for e in entries if e.status == "partial"),
                total_at_subcontractor=sum(
                    1 for e in entries if e.status == "at_subcontractor"
                ),
                total_in_production=sum(
                    1 for e in entries if e.status == "in_production"
                ),
                total_not_planned=sum(1 for e in entries if e.status == "not_planned"),
            )
        )

    total = sum(d.total_orders for d in expedition_days)
    ready = sum(d.total_ready for d in expedition_days)
    at_risk = at_risk_in_window(expedition_days, start_day)

    return ExpeditionKPIs(
        days=expedition_days,
        fill_rate=round(ready / total * 100, 1) if total else 100.0,
        at_risk_count=at_risk,
    )


def _has_segments_before(
    segments: list[Segment],
    lots: list[Lot],
    lot_to_op: dict[str, str],
    op_ids: set[str],
    day_idx: int,
) -> bool:
    """True if there's production for this op on or before day_idx."""
    for seg in segments:
        if seg.day_idx <= day_idx:
            if seg.twin_outputs:
                if any(oid in op_ids for oid, _, _ in seg.twin_outputs):
                    return True
            elif lot_to_op.get(seg.lot_id) in op_ids:
                return True
    return False
