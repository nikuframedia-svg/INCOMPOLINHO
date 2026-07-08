"""Order Tracking — per-order traceability.

For each ClientDemandEntry, traces exactly which lot/segments satisfy it,
how much comes from surplus (eco lot), and generates a Portuguese explanation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from backend.scheduler.types import Lot, Segment
from backend.types import ClientDemandEntry, EngineData


@dataclass(slots=True)
class OrderTracking:
    client: str
    sku: str
    order_qty: int
    delivery_day: int
    delivery_date: str
    # Production
    source: str  # "production" | "surplus" | "not_planned"
    production_machine: str | None
    production_days: list[int]
    production_run_id: str | None
    production_qty: int  # total qty in the covering lot
    # Tracing
    lot_id: str | None
    eco_lot_total: int
    surplus_used: int
    surplus_remaining: int
    # Status
    status: str  # "ready" | "in_production" | "planned" | "not_planned"
    ready_day: int | None
    days_early: int | None  # delivery_day - ready_day (positive = early)
    # Explanation
    reason: str


@dataclass(slots=True)
class ClientOrders:
    client: str
    total_orders: int
    total_ready: int
    orders: list[OrderTracking]


# ── Lot metadata from segments ──


@dataclass
class _LotInfo:
    lot_id: str
    machine: str
    run_id: str
    days: list[int]
    ready_day: int
    qty: int  # for this specific SKU (twin-aware)


def _build_lot_info(
    lots: list[Lot],
    segments: list[Segment],
) -> dict[str, _LotInfo]:
    """Build metadata for each lot from its segments."""
    seg_by_lot: dict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        seg_by_lot[seg.lot_id].append(seg)

    info: dict[str, _LotInfo] = {}
    for lot in lots:
        segs = seg_by_lot.get(lot.id, [])
        if segs:
            days = sorted({s.day_idx for s in segs})
            info[lot.id] = _LotInfo(
                lot_id=lot.id,
                machine=segs[0].machine_id,
                run_id=segs[0].run_id,
                days=days,
                ready_day=max(s.day_idx for s in segs),
                qty=lot.qty,
            )
        else:
            info[lot.id] = _LotInfo(
                lot_id=lot.id,
                machine=lot.machine_id,
                run_id="",
                days=[],
                ready_day=lot.edd,
                qty=lot.qty,
            )
    return info


def _get_lot_qty_for_sku(lot: Lot, sku: str) -> int:
    """Get qty produced for a specific SKU (twin-aware)."""
    if lot.twin_outputs:
        for _op_id, lot_sku, qty in lot.twin_outputs:
            if lot_sku == sku:
                return qty
    return lot.qty


def compute_order_tracking(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
) -> list[ClientOrders]:
    """Trace each client demand to its covering lot/segments."""
    lot_info = _build_lot_info(lots, segments)

    # Group lots by op_id, sorted by EDD
    # Twin lots are indexed by ALL op_ids they produce for
    lots_by_op: dict[str, list[Lot]] = defaultdict(list)
    for lot in lots:
        if lot.twin_outputs:
            seen: set[str] = set()
            for op_id, _sku, _qty in lot.twin_outputs:
                if op_id not in seen:
                    lots_by_op[op_id].append(lot)
                    seen.add(op_id)
        else:
            lots_by_op[lot.op_id].append(lot)
    for op_id in lots_by_op:
        lots_by_op[op_id].sort(key=lambda lot: lot.edd)

    # SKU → op_id
    sku_to_op: dict[str, str] = {op.sku: op.id for op in engine_data.ops}

    # Allocate demands to lots per SKU
    all_trackings: dict[str, list[OrderTracking]] = defaultdict(list)

    for sku, demand_entries in engine_data.client_demands.items():
        op_id = sku_to_op.get(sku)
        if op_id is None:
            # No op for this SKU → all not_planned
            for entry in demand_entries:
                t = _make_not_planned(entry)
                all_trackings[entry.client].append(t)
            continue

        sku_lots = lots_by_op.get(op_id, [])
        sorted_demands = sorted(demand_entries, key=lambda e: e.day_idx)

        _allocate_demands(sku, sku_lots, sorted_demands, lot_info, all_trackings)

    # Build ClientOrders
    result: list[ClientOrders] = []
    for client in sorted(all_trackings.keys()):
        orders = all_trackings[client]
        orders.sort(key=lambda o: (o.sku, o.delivery_day))
        result.append(
            ClientOrders(
                client=client,
                total_orders=len(orders),
                total_ready=sum(1 for o in orders if o.status == "ready"),
                orders=orders,
            )
        )

    return result


def _allocate_demands(
    sku: str,
    sku_lots: list[Lot],
    demands: list[ClientDemandEntry],
    lot_info: dict[str, _LotInfo],
    all_trackings: dict[str, list[OrderTracking]],
) -> None:
    """Walk lots in EDD order, allocating demands. Mirrors lot_sizing carry-forward."""
    surplus = 0
    lot_idx = 0
    lot_remaining = 0
    current_lot: Lot | None = None

    if sku_lots:
        current_lot = sku_lots[0]
        lot_remaining = _get_lot_qty_for_sku(current_lot, sku)

    for entry in demands:
        needed = entry.order_qty
        if needed <= 0:
            continue

        # Try surplus from current lot
        if surplus >= needed:
            info = lot_info.get(current_lot.id) if current_lot else None
            t = _make_surplus(entry, needed, surplus - needed, current_lot, info)
            surplus -= needed
            all_trackings[entry.client].append(t)
            continue

        # Need production — advance to lot that covers this demand
        # First consume any remaining surplus
        still_needed = needed - surplus
        surplus_part = needed - still_needed

        # Advance lots until we find one with capacity
        while current_lot is not None and lot_remaining <= 0:
            lot_idx += 1
            if lot_idx < len(sku_lots):
                current_lot = sku_lots[lot_idx]
                lot_remaining = _get_lot_qty_for_sku(current_lot, sku)
            else:
                current_lot = None
                lot_remaining = 0

        if current_lot is None or lot_remaining <= 0:
            t = _make_not_planned(entry)
            all_trackings[entry.client].append(t)
            continue

        # Consume from current lot
        consumed = min(lot_remaining, still_needed)
        lot_remaining -= consumed
        surplus = lot_remaining  # remaining becomes surplus for next demand

        info = lot_info.get(current_lot.id)
        lot_qty = _get_lot_qty_for_sku(current_lot, sku)

        t = _make_production(entry, current_lot, info, lot_qty, surplus_part, surplus)
        all_trackings[entry.client].append(t)


def _make_production(
    entry: ClientDemandEntry,
    lot: Lot,
    info: _LotInfo | None,
    eco_lot_total: int,
    surplus_used: int,
    surplus_remaining: int,
) -> OrderTracking:
    machine = info.machine if info else lot.machine_id
    days = info.days if info else []
    run_id = info.run_id if info else None
    ready_day = info.ready_day if info else lot.edd
    days_early = entry.day_idx - ready_day

    days_str = ", ".join(str(d) for d in days) if days else "?"
    reason = f"Produzido na {machine} dias {days_str}. Eco lot de {eco_lot_total} pç."
    if surplus_remaining > 0:
        reason += f" Excedente: {surplus_remaining} pç."

    status = "ready" if ready_day <= entry.day_idx else "planned"

    return OrderTracking(
        client=entry.client,
        sku=entry.sku,
        order_qty=entry.order_qty,
        delivery_day=entry.day_idx,
        delivery_date=entry.date,
        source="production",
        production_machine=machine,
        production_days=days,
        production_run_id=run_id,
        production_qty=eco_lot_total,
        lot_id=lot.id,
        eco_lot_total=eco_lot_total,
        surplus_used=surplus_used,
        surplus_remaining=surplus_remaining,
        status=status,
        ready_day=ready_day,
        days_early=days_early,
        reason=reason,
    )


def _make_surplus(
    entry: ClientDemandEntry,
    surplus_used: int,
    surplus_remaining: int,
    lot: Lot | None,
    info: _LotInfo | None,
) -> OrderTracking:
    machine = info.machine if info else (lot.machine_id if lot else None)
    ready_day = info.ready_day if info else (lot.edd if lot else None)
    days_early = (entry.day_idx - ready_day) if ready_day is not None else None
    status = "ready" if ready_day is not None and ready_day <= entry.day_idx else "planned"

    reason = f"Coberta pelo excedente do eco lot anterior ({surplus_used} pç)."

    return OrderTracking(
        client=entry.client,
        sku=entry.sku,
        order_qty=entry.order_qty,
        delivery_day=entry.day_idx,
        delivery_date=entry.date,
        source="surplus",
        production_machine=machine,
        production_days=info.days if info else [],
        production_run_id=info.run_id if info else None,
        production_qty=0,
        lot_id=lot.id if lot else None,
        eco_lot_total=0,
        surplus_used=surplus_used,
        surplus_remaining=surplus_remaining,
        status=status,
        ready_day=ready_day,
        days_early=days_early,
        reason=reason,
    )


def _make_not_planned(entry: ClientDemandEntry) -> OrderTracking:
    return OrderTracking(
        client=entry.client,
        sku=entry.sku,
        order_qty=entry.order_qty,
        delivery_day=entry.day_idx,
        delivery_date=entry.date,
        source="not_planned",
        production_machine=None,
        production_days=[],
        production_run_id=None,
        production_qty=0,
        lot_id=None,
        eco_lot_total=0,
        surplus_used=0,
        surplus_remaining=0,
        status="not_planned",
        ready_day=None,
        days_early=None,
        reason="Sem produção planeada para esta encomenda.",
    )
