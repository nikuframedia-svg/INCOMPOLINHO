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
- A subcontracted order leaves when the pieces it consumes leave and is back
  ``lead`` working days later. An economic lot of material version 3 (its
  outputs say so, and no ``material_upgraded_from``) of a subcontracted
  operation leaves whole on the day its last piece is made, once all its
  pieces are made (Luís, 13/10/2026); every other piece leaves on the day it
  is made, so the order leaves when its own cumulative quantity is complete.
- Explicit stock in an order (``order_qty - |NP|``) is served from the
  opening stock first; net NP never deducts stock twice.
- Twin cycles: each side is its own SKU, served from that side's pieces
  (``twin_outputs``) like any other production.

Material window (``oracle_window_violations``, AGENTS §2 "Janela por
entrega", Fase B2): the release ``R`` of every delivery is recomputed here
from its customer day and the operation's subcontract lead and buffer
(``R = M - 5`` working days, ``M`` the customer day or the planned dispatch).
Of a lot, only the quantity of deliveries with ``R <= d`` may be set up for or
produced by day ``d``; the economic surplus takes the ``R`` of the last
delivery its side covers (never a shared cycle ``R``). Which deliveries a lot
covers is rebuilt here from the ISOP demand, first in first out over the
lots of each operation in lot-sizing order (``oracle_lot_order``, never the
plan's list order), with the quantity each side really makes
(``twin_outputs``); the lot's own delivery days, surplus flags and pair
claims are never read. Twin cycle: on day ``d`` the cycle may make as many
pieces as the larger of its two sides' released quantities. The cycle pair is
the first delivery each side covers, when both exist with customer days at
most ``ORACLE_TWIN_PAIR_GAP_DAYS`` apart; only that pair shares ``min(R)``.
Co-produced stock (a side with no delivery of its own in the cycle) never
drives the release: the cycle follows the other side.
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
        # Holidays before the first ISOP column (05/10 for rev121) count too.
        if day in self.holidays:
            return False
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


def _goes_out_whole(lot, data) -> bool:
    """A subcontracted economic lot of material version 3 (not taken over)."""

    outputs = lot.output_milestones or []
    version = max((int(o.get("quantity_material_version") or 0) for o in outputs), default=0)
    if version < 3 or any(o.get("material_upgraded_from") for o in outputs):
        return False
    op_ids = {str(op_id) for op_id, _sku, _qty in lot.twin_outputs or []} or {lot.op_id}
    return any(_subcontract(op)[0] for op in data.ops if op.id in op_ids)


def _lot_dispatch_days(segments, lots, data) -> dict[str, int | None]:
    """Day each whole-going lot leaves: its last piece, once all are made."""

    result = {}
    for lot in lots:
        if not _goes_out_whole(lot, data):
            continue
        own = [segment for segment in segments if segment.lot_id == lot.id and segment.qty > 0]
        made = sum(int(segment.qty) for segment in own)
        result[lot.id] = max(s.day_idx for s in own) if own and made >= lot.qty else None
    return result


def _events(segments, lots, data, op_ids: set[str]) -> list[_Event]:
    op_of_lot = {lot.id: lot.op_id for lot in lots}
    whole = _lot_dispatch_days(segments, lots, data)
    subcontracted_ops = {op.id for op in data.ops if _subcontract(op)[0]}
    events = []
    for index, segment in enumerate(segments):
        outputs = segment.twin_outputs or [(op_of_lot.get(segment.lot_id), segment.sku, segment.qty)]
        qty = sum(int(q) for op, _sku, q in outputs if op in op_ids)
        if qty <= 0:
            continue
        day = segment.day_idx
        if segment.lot_id in whole and op_ids & subcontracted_ops:
            if whole[segment.lot_id] is None:
                continue  # the lot is never complete: its pieces never leave
            day = whole[segment.lot_id]
        events.append(_Event(segment.day_idx * DAY + segment.end_min, index, day, qty, index))
    for supply in data.committed_supplies:
        if supply.op_id in op_ids and supply.qty > 0:
            events.append(_Event(supply.available_day * DAY, -1, supply.available_day,
                                 int(supply.qty), None))
    # Available day first (a whole lot leaves on its last day), then time.
    events.sort(key=lambda event: (event.day, event.abs_time, event.order))
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
    """First day each operation's shown stock goes negative (Entregas grid).

    Pieces count on the day they are produced, subcontracted ones too
    (Incompol, 14/10/2026): cumulative production (committed supplies on
    their available day, buffer days before day 0) against cumulative
    positive ISOP demand. Not the customer readiness of ``oracle_checkpoints``.
    """

    op_of_lot = {lot.id: lot.op_id for lot in lots}
    made: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for segment in segments:
        outputs = segment.twin_outputs or [(op_of_lot.get(segment.lot_id), segment.sku, segment.qty)]
        for op_id, _sku, qty in outputs:
            made[op_id][segment.day_idx] += int(qty)
    for supply in data.committed_supplies:
        made[supply.op_id][supply.available_day] += int(supply.qty)
    result = {}
    for op in data.ops:
        produced = sum(qty for day, qty in made[op.id].items() if day < 0)
        demanded, result[op.id] = 0, None
        for day in range(data.n_days):
            produced += made[op.id].get(day, 0)
            demanded += max(0, int(op.d[day])) if day < len(op.d) else 0
            if produced < demanded:
                result[op.id] = day
                break
    return result


# ── Material window per delivery (independent of lot sizing's dates) ─────


def _on_or_previous_workday(calendar: WorkCalendar, day: int) -> int:
    while not calendar.is_workday(day):
        day -= 1
    return day


def oracle_release_day(op, customer_day: int, calendar: WorkCalendar) -> int:
    """``R`` of one delivery of ``op`` due on ``customer_day`` (AGENTS §2)."""

    subcontracted, lead, buffer = _subcontract(op)
    reference = int(customer_day)
    if subcontracted:
        latest = _on_or_previous_workday(calendar, calendar.subtract(reference, lead))
        reference = calendar.subtract(latest, buffer)
    return calendar.subtract(reference, 5)


@dataclass
class WindowViolation:
    lot_id: str
    day: int
    produced: int  # cumulative (cycles for a twin lot) up to and including ``day``
    allowed: int  # released by ``day``
    setup_only: bool


ORACLE_TWIN_PAIR_GAP_DAYS = 5  # AGENTS §2: deliveries of one cycle pair


def _released(lot, releases: list[tuple[str, int, int]], day: int) -> int:
    """Released quantity on ``day``: per side for a twin cycle, the larger."""

    by_side: dict[str, int] = defaultdict(int)
    for side, qty, release in releases:
        if release <= day:
            by_side[side] += qty
    if not lot.is_twin:
        return sum(by_side.values())
    return max(by_side.values(), default=0)


def _net_deliveries(op, data) -> list[list[int]]:
    """``[customer day, qty]`` of every ISOP delivery of ``op``, in day order.

    ``op.d`` is the net NP (the opening stock is already deducted from the
    first order, so it is never deducted twice); a committed supply serves
    the deliveries due on or after its available day, first in first out.
    """

    supplies = sorted(
        (int(s.available_day), int(s.qty)) for s in data.committed_supplies
        if s.op_id == op.id and s.qty > 0
    )
    available, next_supply = 0, 0
    deliveries = []
    for day, qty in enumerate(op.d):
        while next_supply < len(supplies) and supplies[next_supply][0] <= day:
            available += supplies[next_supply][1]
            next_supply += 1
        if qty <= 0:
            continue
        credit = min(int(qty), available)
        available -= credit
        if qty - credit > 0:
            deliveries.append([day, int(qty) - credit])
    return deliveries


def _side_quantities(lot) -> list[tuple[str, int]]:
    """Pieces of each side the lot makes (``twin_outputs``; else the lot)."""

    if lot.is_twin and lot.twin_outputs:
        return [(str(op_id), int(qty)) for op_id, _sku, qty in lot.twin_outputs]
    return [(str(lot.op_id), int(lot.qty))]


def _protected_lot_ids(data) -> set[str]:
    """Lots kept from the stored plan: preserved history and manual anchors."""

    return {str(lot_id) for lot_id in (getattr(data, "preserved_lot_proofs", None) or {})} | {
        str(anchor.lot_id) for anchor in (getattr(data, "plan_anchors", None) or [])
    }


def _lot_index(lot_id: str) -> tuple[int, ...]:
    """Numeric parts of a lot id: the demand day, then a duplicate counter.

    Lots of one operation share every other part of the id
    (``LOT_<tool>_<machine>_<sku>_<day>``, ``LOT_TWIN_<tool>_<day>[_<n>]``),
    so this orders them numerically, never as text (``_10`` after ``_9``).
    """

    return tuple(int(part) for part in str(lot_id).split("_") if part.isdigit())


def oracle_lot_order(lots, data) -> list:
    """The order in which lots consume each operation's deliveries.

    Never the plan's list order: a frozen recalculation lists the protected
    lots last, although they were sized first and cover the earliest
    deliveries. Protected lots (preserved history, anchors) come first.
    Within each group, the order lot sizing creates them in:

    * a solo operation makes one lot per rupture day, at increasing days;
    * a twin group makes its cycles at increasing priority of the delivery
      that controls each cycle (production due day, then customer day), and
      each side consumes its own deliveries first in first out in that same
      creation order. So one order serves both sides: a cycle's ``edd`` (the
      earliest due day it serves) never decreases along the creation order,
      on either side.

    Hence: due day (``edd``), customer rupture (``original_edd``), then the
    numeric parts of the id (demand day, duplicate counter), then the id.
    Equal to the creation order of ``create_lots`` on every side of the
    real fixtures (revisions 82, 85, 87, 90, 121; material versions 0-2),
    see ``tests/test_twin_per_delivery.py``. Ordering by each side's first
    recorded delivery is not: it reads the lot's labels, which twin cycles
    of version 0/1 record only for the paired deliveries. The order only
    decides which lot comes first; which deliveries a lot covers is still
    rebuilt from the ISOP.
    """

    protected = _protected_lot_ids(data)

    def rank(lot):
        rupture = lot.original_edd if lot.original_edd is not None else lot.edd
        return (lot.id not in protected, int(lot.edd), int(rupture), _lot_index(lot.id), str(lot.id))

    return sorted(lots, key=rank)


def oracle_coverage(lots, data) -> dict[str, dict[str, list[tuple[int | None, int]]]]:
    """``{lot id: {side: [(customer day, qty), ...]}}`` rebuilt from the ISOP.

    The surplus of a side is listed last, with day ``None``.

    Each operation's deliveries are served first in first out by its lots in
    lot-sizing order (``oracle_lot_order``: protected lots first, then the
    creation order of lot sizing), each with the quantity it really makes of that
    side. The lot's own delivery, surplus and co-produced labels are never
    read; what a side makes beyond its covered deliveries is its surplus.
    """

    ops = {op.id: op for op in data.ops}
    pending: dict[str, list[list[int]]] = {}
    coverage: dict[str, dict[str, list[tuple[int | None, int]]]] = {}
    for lot in oracle_lot_order(lots, data):
        sides = coverage.setdefault(lot.id, {})
        for side, qty in _side_quantities(lot):
            op = ops.get(side)
            if op is None:
                continue
            queue = pending.setdefault(side, _net_deliveries(op, data))
            covered = sides.setdefault(side, [])
            while qty > 0 and queue:
                take = min(qty, queue[0][1])
                covered.append((queue[0][0], take))
                qty -= take
                queue[0][1] -= take
                if queue[0][1] == 0:
                    queue.pop(0)
            if qty > 0:
                covered.append((None, qty))  # surplus beyond the visible demand
    return coverage


def oracle_lot_releases(lot, data, calendar=None, lots=None) -> list[tuple[str, int, int]]:
    """``(side, qty, R)`` of every quantity of ``lot`` that drives its release.

    The coverage of each side is rebuilt from the ISOP (``oracle_coverage``
    over ``lots``, default ``[lot]``; pass the plan's lots so earlier lots of
    the operation consume their deliveries first). ``R`` is recomputed from
    each covered delivery's customer day. The surplus of a side takes the own
    ``R`` of the last delivery that side covers; a side covering no delivery
    is co-produced stock and never drives the release. Twin cycle pair: the
    first delivery each side covers, when both exist with customer days at
    most ``ORACLE_TWIN_PAIR_GAP_DAYS`` apart, share ``min(R)``. No recorded
    date, surplus flag or pair claim of the lot is read.
    """

    calendar = calendar or WorkCalendar(data)
    ops = {op.id: op for op in data.ops}
    plan_lots = list(lots) if lots is not None else [lot]
    if all(other.id != lot.id for other in plan_lots):
        plan_lots.append(lot)
    sides = oracle_coverage(plan_lots, data).get(lot.id, {})
    own: dict[str, list[tuple[int, int, bool]]] = {}
    for side, covered in sides.items():
        rows, last = [], None
        for day, qty in covered:
            if day is not None:
                last = oracle_release_day(ops[side], day, calendar)
                rows.append((qty, last, False))
            elif last is not None:
                rows.append((qty, last, True))
        own[side] = rows
    firsts = {
        side: next(day for day, _qty in covered if day is not None)
        for side, covered in sides.items()
        if any(day is not None for day, _qty in covered)
    }
    if (
        lot.is_twin and len(firsts) == 2
        and max(firsts.values()) - min(firsts.values()) <= ORACLE_TWIN_PAIR_GAP_DAYS
    ):
        pair_release = min(own[side][0][1] for side in firsts)
        for side in firsts:
            qty, _release, surplus = own[side][0]
            own[side][0] = (qty, pair_release, surplus)
    return [(side, qty, release) for side, rows in own.items() for qty, release, _s in rows]


def oracle_window_violations(segments, lots, data) -> list[WindowViolation]:
    """Segments that prepare or make pieces before their material is released.

    Lots without per-delivery outputs (``quantity_material_version``) are not
    judged here. Versions 1-2: each delivery at its own ``R``. Version 3
    (13/10/2026, AGENTS §2): the whole economic lot at the earliest ``R``
    the oracle finds for it (its first delivery's, or the twin pair's).
    Production counts on the segment's day; a setup on a day when nothing
    more is released is a violation too.
    """

    calendar = WorkCalendar(data)
    by_lot = defaultdict(list)
    for segment in segments:
        if segment.end_min > segment.start_min:
            by_lot[segment.lot_id].append(segment)
    result: list[WindowViolation] = []
    for lot in lots:
        outputs = list(lot.output_milestones or [])
        if not outputs or not any(o.get("quantity_material_version") for o in outputs):
            continue
        releases = oracle_lot_releases(lot, data, calendar, lots)
        if max(int(o.get("quantity_material_version") or 0) for o in outputs) >= 3:
            lot_release = min(release for _side, _qty, release in releases)
            releases = [(side, qty, lot_release) for side, qty, _release in releases]
        produced = 0
        for segment in sorted(by_lot.get(lot.id, []), key=lambda s: (s.day_idx, s.start_min)):
            if lot.is_twin and segment.twin_outputs:
                made = max(int(q) for _op, _sku, q in segment.twin_outputs)
            else:
                made = int(segment.qty)
            allowed = _released(lot, releases, segment.day_idx)
            setup_only = segment.setup_min > 0 and produced >= allowed and produced < lot.qty
            produced += made
            if produced > allowed or setup_only:
                result.append(WindowViolation(lot.id, segment.day_idx, produced, allowed,
                                              setup_only))
    return result
