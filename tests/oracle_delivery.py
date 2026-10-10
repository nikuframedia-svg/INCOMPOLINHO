"""Independent delivery oracle: when is each order really ready?

Written from AGENTS.md §2-§3 and the owner decisions of 09-10/10/2026,
without the project's readiness, allocation or calendar helpers. It reads
only plain fields of the plan (segments, lots for the lot -> operation map,
the ISOP demand and the factory calendar):

- Working days: the factory holidays inside the ISOP; outside it, weekends
  (unless declared an extra workday).
- Production of a SKU is served first-in-first-out in absolute time
  (``day * 1440 + end``, then segment order); committed supplies enter on
  their available day.
- An in-house order is ready on the day of the last piece it consumes.
- A subcontracted order leaves when its own cumulative quantity is complete
  and is back ``lead`` working days later (never at the end of the lot).
- Explicit stock in an order (``order_qty - |NP|``) is served from the
  opening stock first; net NP never deducts stock twice.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

DAY = 1440


class WorkCalendar:
    def __init__(self, data) -> None:
        self.n_days = int(data.n_days)
        self.holidays = set(data.holidays or [])
        self.extra = set(getattr(data, "calendar_extra_workdays", []) or [])
        self.first = date.fromisoformat(str(data.workdays[0])[:10]) if data.workdays else None

    def is_workday(self, day: int) -> bool:
        if 0 <= day < self.n_days or self.first is None:
            return day not in self.holidays
        if day in self.extra:
            return True
        return (self.first + timedelta(days=day)).weekday() < 5

    def add(self, day: int, workdays: int) -> int:
        while workdays > 0:
            day += 1
            if self.is_workday(day):
                workdays -= 1
        return day

    def subtract(self, day: int, workdays: int) -> int:
        while workdays > 0:
            day -= 1
            if self.is_workday(day):
                workdays -= 1
        return day

    def between(self, start: int, end: int) -> int:
        return sum(1 for day in range(start + 1, end + 1) if self.is_workday(day))


@dataclass
class OracleOrder:
    sku: str
    client: str
    due_day: int
    qty: int
    subcontracted: bool
    factory_day: int | None = None
    ready_day: int | None = None
    latest_dispatch_day: int | None = None
    allocations: list[tuple[int, int]] = field(default_factory=list)  # (segment index, qty)

    @property
    def late(self) -> bool:
        return self.ready_day is None or self.ready_day > self.due_day

    @property
    def delay(self) -> int | None:
        return None if self.ready_day is None else self.ready_day - self.due_day


@dataclass
class _Event:
    abs_time: int
    order: int
    day: int
    qty: int
    segment_index: int | None  # None: committed supply


def _subcontract(op) -> tuple[bool, int, int]:
    flagged = bool(op.is_subcontracted or op.subcontract_company_id
                   or op.subcontract_lead_time_days or op.subcontract_buffer_days)
    return flagged, int(op.subcontract_lead_time_days or 0), int(op.subcontract_buffer_days or 0)


def _events(segments, lots, data, op_ids: set[str]) -> list[_Event]:
    op_of_lot = {lot.id: lot.op_id for lot in lots}
    events = []
    for index, segment in enumerate(segments):
        outputs = segment.twin_outputs or [(op_of_lot.get(segment.lot_id), segment.sku, segment.qty)]
        qty = sum(int(q) for op, _sku, q in outputs if op in op_ids)
        if qty > 0:
            events.append(_Event(segment.day_idx * DAY + segment.end_min, index,
                                 segment.day_idx, qty, index))
    for supply in data.committed_supplies:
        if supply.op_id in op_ids and supply.qty > 0:
            events.append(_Event(supply.available_day * DAY, -1, supply.available_day,
                                 int(supply.qty), None))
    events.sort(key=lambda event: (event.abs_time, event.order))
    return events


def _serve(orders: list[OracleOrder], events: list[_Event], calendar: WorkCalendar,
           lead: int, stock: int, explicit_stock: list[int]) -> None:
    cursor, left = 0, events[0].qty if events else 0
    for order, explicit in zip(orders, explicit_stock):
        credit = min(stock, explicit)
        stock -= credit
        need = order.qty - credit
        last_production = last_supply = None
        while need > 0 and cursor < len(events):
            event = events[cursor]
            take = min(left, need)
            need -= take
            left -= take
            if event.segment_index is None:
                last_supply = event.day
            else:
                last_production = event.day
                order.allocations.append((event.segment_index, take))
            if left == 0:
                cursor += 1
                left = events[cursor].qty if cursor < len(events) else 0
        if need > 0:
            continue
        candidates = [day for day in (last_supply,) if day is not None]
        if last_production is not None:
            order.factory_day = last_production
            candidates.append(
                calendar.add(last_production, lead) if order.subcontracted else last_production
            )
        else:
            order.factory_day = last_supply if last_supply is not None else 0
        order.ready_day = max(candidates, default=0)


def oracle_orders(segments, lots, data) -> list[OracleOrder]:
    """Every client order with its oracle readiness, in (sku, day, client) order."""

    calendar = WorkCalendar(data)
    ops_by_sku = defaultdict(list)
    for op in data.ops:
        ops_by_sku[op.sku].append(op)
    result: list[OracleOrder] = []
    for sku in sorted(ops_by_sku):
        ops = ops_by_sku[sku]
        subcontracted, lead, _buffer = _subcontract(ops[0])
        entries = data.client_demands.get(sku)
        if entries:
            raw = [(e.day_idx, e.client, int(e.order_qty), abs(int(e.np_value))) for e in entries]
        else:
            raw = [(day, str(op.client or ""), int(q), int(q))
                   for op in ops for day, q in enumerate(op.d) if q > 0]
        raw = [item for item in sorted(raw, key=lambda item: (item[0], item[1])) if item[2] > 0]
        orders = [
            OracleOrder(sku, client, day, qty, subcontracted,
                        latest_dispatch_day=calendar.subtract(day, lead) if subcontracted else None)
            for day, client, qty, _np in raw
        ]
        _serve(orders, _events(segments, lots, data, {op.id for op in ops}), calendar, lead,
               sum(max(0, op.stk) for op in ops), [max(0, qty - np) for _d, _c, qty, np in raw])
        result.extend(orders)
    return result


def oracle_checkpoints(segments, lots, data) -> dict[str, list[OracleOrder]]:
    """OTD-D checkpoints: each positive net ISOP demand of each operation."""

    calendar = WorkCalendar(data)
    result = {}
    for op in data.ops:
        subcontracted, lead, _buffer = _subcontract(op)
        orders = [OracleOrder(op.sku, "", day, int(q), subcontracted)
                  for day, q in enumerate(op.d) if q > 0]
        _serve(orders, _events(segments, lots, data, {op.id}), calendar, lead, 0, [0] * len(orders))
        result[op.id] = orders
    return result


def oracle_otd_d_failures(segments, lots, data) -> int:
    """Checkpoints whose cumulative demand is not available by its day."""

    # FIFO makes "this checkpoint's last piece is available by its day"
    # equivalent to "cumulative supply covers cumulative demand on that day".
    return sum(
        checkpoint.late
        for checkpoints in oracle_checkpoints(segments, lots, data).values()
        for checkpoint in checkpoints
    )


def oracle_first_rupture(segments, lots, data) -> dict[str, int | None]:
    """First day each operation's projected stock goes negative."""

    return {
        op_id: next((c.due_day for c in checkpoints if c.late), None)
        for op_id, checkpoints in oracle_checkpoints(segments, lots, data).items()
    }
