"""Order Tracking — per-order traceability.

For each ClientDemandEntry, traces exactly which lot/segments satisfy it,
how much comes from surplus (eco lot), and generates a Portuguese explanation.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass

from backend.scheduler.material_quantities import (
    DeliveryPortion,
    delivery_portions,
    production_by_op,
)
from backend.scheduler.types import Lot, Segment
from backend.types import ClientDemandEntry, EngineData


@dataclass(slots=True)
class OrderReadiness:
    entry: ClientDemandEntry
    ready_day: int | None
    factory_ready_day: int | None
    covered_qty: int
    factory_covered_qty: int
    cumulative_produced_qty: int
    cumulative_factory_qty: int


def compute_order_readiness(segments, lots, data) -> dict[str, list[OrderReadiness]]:
    """FIFO allocation of real output, without charging net ISOP demand twice for stock.

    Pieces of a SKU are fungible: every lot of the operation serves its
    deliveries in due order (``delivery_portions``), so an order is judged
    by when its own pieces exist, whichever lot makes them.
    """
    portions = delivery_portions(lots, segments, data)
    customer = production_by_op(portions)
    factory = production_by_op(portions, customer=False)
    for supply in data.committed_supplies:
        customer[supply.op_id][supply.available_day] += supply.qty
        factory[supply.op_id][supply.available_day] += supply.qty
    ops_by_sku = defaultdict(list)
    for op in data.ops:
        ops_by_sku[op.sku].append(op)

    def cumulative(source, ops):
        daily = defaultdict(int)
        for op in ops:
            for day, qty in source.get(op.id, {}).items():
                daily[day] += qty
        days, amounts, total = [], [], 0
        for day, qty in sorted(daily.items()):
            total += qty
            days.append(day)
            amounts.append(total)
        return days, amounts

    def quantity(curve, day):
        days, amounts = curve
        index = bisect_right(days, day) - 1
        return amounts[index] if index >= 0 else 0

    def ready(curve, required):
        if required <= 0:
            return 0
        days, amounts = curve
        index = bisect_left(amounts, required)
        return days[index] if index < len(days) else None

    result = {}
    for sku, entries in data.client_demands.items():
        ops = ops_by_sku[sku]
        curves = cumulative(customer, ops), cumulative(factory, ops)
        stock = sum(max(0, op.stk) for op in ops)
        previous = stock_used = 0
        allocated = []
        for entry in sorted(entries, key=lambda e: (e.day_idx, e.client)):
            if entry.order_qty <= 0:
                continue
            # Imported entries are net NP. Historical full-order entries may
            # explicitly include the stock component in order_qty - abs(NP).
            credit = min(stock, max(0, entry.order_qty - abs(entry.np_value)))
            stock -= credit
            stock_used += credit
            previous += entry.order_qty - credit
            available = [quantity(curve, entry.day_idx) for curve in curves]
            net = entry.order_qty - credit
            covered = [credit + min(net, max(0, qty - previous + net)) for qty in available]
            allocated.append(OrderReadiness(
                entry=entry, ready_day=ready(curves[0], previous),
                factory_ready_day=ready(curves[1], previous),
                covered_qty=covered[0], factory_covered_qty=covered[1],
                cumulative_produced_qty=available[0] + stock_used,
                cumulative_factory_qty=available[1] + stock_used,
            ))
        result[sku] = allocated
    return result


def readiness_for_entry(entry, segments, lots, data):
    return next(
        (
            allocation
            for allocation in compute_order_readiness(segments, lots, data).get(entry.sku, [])
            if allocation.entry.day_idx == entry.day_idx
            and allocation.entry.client == entry.client
            and allocation.entry.order_qty == entry.order_qty
        ),
        None,
    )


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
    production_qty: int  # total qty in newly opened covering lots
    # Tracing
    lot_id: str | None
    eco_lot_total: int
    surplus_used: int
    surplus_remaining: int
    # Status
    status: str  # ready | partial | at_subcontractor | planned | not_planned
    ready_day: int | None  # compatibility alias for customer_ready_day
    factory_ready_day: int | None
    customer_ready_day: int | None
    subcontract_dispatch_day: int | None
    is_subcontracted: bool
    days_early: int | None  # delivery_day - ready_day (positive = early)
    # Explanation
    reason: str
    # Full allocation trace (the singular fields above remain compatibility aliases)
    lot_ids: list[str]
    production_run_ids: list[str]
    production_machines: list[str]
    allocated_qty: int
    shortfall_qty: int


@dataclass(slots=True)
class ClientOrders:
    client: str
    total_orders: int
    total_ready: int
    orders: list[OrderTracking]


# ── Production slices ──


@dataclass
class _LotInfo:
    lot_id: str
    machine: str
    run_id: str
    days: list[int]


@dataclass
class _LotContribution:
    lot: Lot | None
    info: _LotInfo | None
    qty: int
    from_surplus: bool
    factory_day: int
    customer_day: int
    segment_index: int | None = None
    abs_end: int = 0
    output: DeliveryPortion | None = None


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
    *,
    segment_allocations: list[list[dict]] | None = None,
    portions: list[DeliveryPortion] | None = None,
) -> list[ClientOrders]:
    """Trace each client demand to its covering lot/segments.

    ``portions`` reuses an already computed ``delivery_portions``.
    """
    readiness = (
        portions if portions is not None else delivery_portions(lots, segments, engine_data)
    )

    # Twin lots are indexed by all operations they produce for.
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
    sku_to_ops: dict[str, list[str]] = defaultdict(list)
    for op in engine_data.ops:
        sku_to_ops[op.sku].append(op.id)

    # Allocate demands to lots per SKU
    all_trackings: dict[str, list[OrderTracking]] = defaultdict(list)

    for sku, demand_entries in engine_data.client_demands.items():
        op_ids = sku_to_ops.get(sku, [])
        if not op_ids:
            # No op for this SKU → all not_planned
            for entry in demand_entries:
                t = _make_not_planned(entry)
                all_trackings[entry.client].append(t)
            continue

        sku_lots_by_id = {
            lot.id: lot
            for op_id in op_ids
            for lot in lots_by_op.get(op_id, [])
        }
        sorted_demands = sorted(demand_entries, key=lambda e: (e.day_idx, e.client))

        _allocate_demands(
            sku,
            list(sku_lots_by_id.values()),
            sorted_demands,
            all_trackings,
            segments,
            engine_data,
            readiness,
            segment_allocations,
        )

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
    all_trackings: dict[str, list[OrderTracking]],
    segments: list[Segment],
    data: EngineData,
    readiness: list[DeliveryPortion],
    segment_allocations: list[list[dict]] | None = None,
) -> None:
    """Allocate real outputs first-in-first-out, by availability then absolute time.

    Each event is the part of a segment that serves one delivery portion of
    the operation (all its lots, ``delivery_portions``). An in-house piece is
    available when produced; a subcontracted delivery portion when it
    returns, so each order carries its own portion's dispatch and return.
    """
    by_id = {lot.id: lot for lot in sku_lots}
    events = []
    produced = defaultdict(int)
    for portion in readiness:
        if portion.sku != sku:
            continue
        for item in portion.slices:
            lot = by_id.get(item.lot_id)
            if lot is None:
                continue
            segment = segments[item.segment_index]
            if portion.is_subcontracted:
                factory_day, customer_day = portion.factory_day, portion.customer_ready_day
            else:
                factory_day = customer_day = item.day_idx
            info = _LotInfo(lot.id, segment.machine_id, segment.run_id, [item.day_idx])
            events.append(_LotContribution(lot, info, item.qty, False, factory_day, customer_day,
                                           item.segment_index,
                                           item.day_idx * 1440 + item.end_min, portion))
            produced[lot.id] += item.qty
    op_ids = {op.id for op in data.ops if op.sku == sku}
    for supply in data.committed_supplies:
        if supply.op_id in op_ids and supply.qty > 0:
            events.append(_LotContribution(None, None, supply.qty, True,
                                           supply.available_day, supply.available_day,
                                           abs_end=supply.available_day * 1440))
    # Chronological in absolute time (day * 1440 + end), never minute-of-day.
    events.sort(key=lambda e: (
        e.customer_day,
        e.abs_end,
        e.segment_index if e.segment_index is not None else -1,
    ))
    event_index = 0
    used = defaultdict(int)
    stock = sum(max(0, op.stk) for op in data.ops if op.sku == sku)

    for entry in demands:
        needed = entry.order_qty
        if needed <= 0:
            continue

        contributions: list[_LotContribution] = []
        previously_used = dict(used)
        credit = min(stock, max(0, entry.order_qty - abs(entry.np_value)))
        stock -= credit
        still_needed = needed - credit
        if credit:
            contributions.append(_LotContribution(None, None, credit, True, 0, 0))

        while still_needed > 0:
            if event_index >= len(events):
                break
            event = events[event_index]
            consumed = min(event.qty, still_needed)
            if segment_allocations is not None and event.segment_index is not None:
                segment_allocations[event.segment_index].append({
                    "sku": sku,
                    "client": entry.client,
                    "delivery_day": entry.day_idx,
                    "delivery_date": entry.date,
                    "qty": consumed,
                    "customer_ready_day": event.customer_day,
                })
            lot_id = event.lot.id if event.lot else ""
            contributions.append(
                _LotContribution(
                    lot=event.lot,
                    info=event.info,
                    qty=consumed,
                    from_surplus=not event.lot or previously_used.get(lot_id, 0) > 0,
                    factory_day=event.factory_day,
                    customer_day=event.customer_day,
                    output=event.output,
                )
            )
            used[lot_id] += consumed
            event.qty -= consumed
            if event.qty == 0:
                event_index += 1
            still_needed -= consumed

        if not contributions:
            tracking = _make_not_planned(entry)
        else:
            tracking = _make_allocated(
                entry,
                contributions,
                sum(produced[lot_id] - used[lot_id] for lot_id in used if lot_id)
                if still_needed == 0 else 0,
                still_needed,
            )
        all_trackings[entry.client].append(tracking)


def compute_segment_deliveries(segments, lots, data):
    """Read-only projection of the same FIFO allocations used by Entregas.

    ``subcontract_trips``: when the pieces of each segment of a
    subcontracted reference leave for the subcontractor and when they are
    back (``sent_day``, ``return_day``), read from the shared evaluator; a
    lot that goes out whole (``whole_lot``, 13/10/2026) has one trip for all
    its segments, its surplus included. Empty for in-house production.
    """
    allocations = [[] for _ in segments]
    portions = delivery_portions(lots, segments, data)
    compute_order_tracking(
        segments, lots, data, segment_allocations=allocations, portions=portions,
    )
    trips: list[set[tuple[int, int, bool]]] = [set() for _ in segments]
    for portion in portions:
        if not portion.is_subcontracted or not portion.produced_qty:
            continue
        for item in portion.slices:
            if not 0 <= item.segment_index < len(segments):
                continue
            if item.whole_lot and item.lot_ready_day is not None:
                # Its own lot's trip: out at that lot's end, back with that
                # lot, even when the delivery also waits for another lot.
                trip = (item.available_day, item.lot_ready_day, True)
            else:
                # Per-delivery dispatch (a lot taken over from material
                # versions 1-2, a twin cycle): out when the delivery's pieces
                # are complete, back with it.
                trip = (portion.factory_day, portion.customer_ready_day, False)
            trips[item.segment_index].add(trip)
    untraced_skus = {
        op.sku for op in data.ops
        if any(qty > 0 for qty in op.d) and not data.client_demands.get(op.sku)
    }
    result = []
    for segment, deliveries, segment_trips in zip(segments, allocations, trips, strict=True):
        quantities = defaultdict(int)
        for _op_id, sku, qty in segment.twin_outputs or [("", segment.sku, segment.qty)]:
            quantities[sku] += qty
        known = not untraced_skus.intersection(quantities)
        for delivery in deliveries:
            quantities[delivery["sku"]] -= delivery["qty"]
        result.append({
            "delivery_allocations": deliveries if known else None,
            "unallocated_output": [
                {"sku": sku, "qty": qty} for sku, qty in quantities.items() if qty > 0
            ] if known else None,
            "subcontract_trips": [
                {"sent_day": sent, "return_day": back, "whole_lot": whole}
                for sent, back, whole in sorted(segment_trips)
            ],
        })
    return result


def _make_allocated(
    entry: ClientDemandEntry,
    contributions: list[_LotContribution],
    surplus_remaining: int,
    shortfall_qty: int,
) -> OrderTracking:
    production = [c for c in contributions if c.lot is not None]
    lot_ids = list(dict.fromkeys(c.lot.id for c in production))
    machines = list(
        dict.fromkeys(
            contribution.info.machine
            if contribution.info
            else contribution.lot.machine_id
            for contribution in production
        )
    )
    run_ids = list(
        dict.fromkeys(
            contribution.info.run_id
            for contribution in contributions
            if contribution.info and contribution.info.run_id
        )
    )
    days = sorted(
        {
            day
            for contribution in contributions
            if contribution.info
            for day in contribution.info.days
        }
    )
    allocated_qty = sum(contribution.qty for contribution in contributions)
    surplus_used = sum(
        contribution.qty for contribution in contributions if contribution.from_surplus
    )
    new_lots = list({c.lot.id: c for c in production if not c.from_surplus}.values())
    production_qty = sum(
        _get_lot_qty_for_sku(contribution.lot, entry.sku)
        for contribution in new_lots
    )
    source = "surplus" if not new_lots else "production"

    readiness: list[tuple[int, int, bool, int | None, _LotContribution]] = []
    for contribution in contributions:
        output = contribution.output
        subcontracted = bool(output and output.is_subcontracted)
        readiness.append((
            contribution.customer_day,
            contribution.factory_day,
            subcontracted,
            output.planned_dispatch_day if subcontracted else None,
            contribution,
        ))

    controlling = max(readiness, key=lambda item: (item[0], item[4].lot.id if item[4].lot else ""))
    is_subcontracted = any(item[2] for item in readiness)
    dispatch_days = [item[3] for item in readiness if item[3] is not None]

    if shortfall_qty > 0:
        ready_day = None
        factory_ready_day = None
        days_early = None
        status = "partial"
        reason = (
            f"Cobertura parcial planeada: {allocated_qty} de {entry.order_qty} pç "
            f"por {len(contributions)} lote(s) ({', '.join(lot_ids)}). "
            f"Faltam {shortfall_qty} pç sem produção planeada."
        )
    else:
        ready_day = max(item[0] for item in readiness)
        factory_ready_day = max(item[1] for item in readiness)
        days_early = entry.day_idx - ready_day
        status = (
            "ready"
            if ready_day <= entry.day_idx
            else "at_subcontractor"
            if factory_ready_day <= entry.day_idx
            and any(item[2] and item[0] > entry.day_idx for item in readiness)
            else "planned"
        )
        reason = (
            f"Coberta por {len(contributions)} lote(s) ({', '.join(lot_ids)}) "
            f"na(s) máquina(s) {', '.join(machines)}. "
            f"Disponibilidade total ao cliente no dia {ready_day}."
        )
        if not production:
            reason = f"Coberta por stock ou fornecimento confirmado; disponível no dia {ready_day}."
        if surplus_remaining > 0:
            reason += f" Excedente: {surplus_remaining} pç."

    return OrderTracking(
        client=entry.client,
        sku=entry.sku,
        order_qty=entry.order_qty,
        delivery_day=entry.day_idx,
        delivery_date=entry.date,
        source=source,
        production_machine=", ".join(machines) or None,
        production_days=days,
        production_run_id=controlling[4].info.run_id if controlling[4].info else None,
        production_qty=production_qty,
        lot_id=controlling[4].lot.id if controlling[4].lot else None,
        eco_lot_total=production_qty,
        surplus_used=surplus_used,
        surplus_remaining=surplus_remaining,
        status=status,
        ready_day=ready_day,
        factory_ready_day=factory_ready_day,
        customer_ready_day=ready_day,
        subcontract_dispatch_day=max(dispatch_days) if dispatch_days else None,
        is_subcontracted=is_subcontracted,
        days_early=days_early,
        reason=reason,
        lot_ids=lot_ids,
        production_run_ids=run_ids,
        production_machines=machines,
        allocated_qty=allocated_qty,
        shortfall_qty=shortfall_qty,
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
        factory_ready_day=None,
        customer_ready_day=None,
        subcontract_dispatch_day=None,
        is_subcontracted=False,
        days_early=None,
        reason="Sem produção planeada para esta encomenda.",
        lot_ids=[],
        production_run_ids=[],
        production_machines=[],
        allocated_qty=0,
        shortfall_qty=entry.order_qty,
    )
