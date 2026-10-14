"""Stock Projection — Spec 03 §1.

Day-by-day stock projection per EOp:
  stock[day] = cum_produced - cum_demand

NP negativo já desconta stock inicial, por isso initial_stock NÃO entra na fórmula.
Production comes from real Segments. Demand from EngineData op.d.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass, field

from backend.config.planning import planning_milestones_for_op
from backend.scheduler.jit_policy import calendar_holidays
from backend.scheduler.material_quantities import (
    DeliveryPortion,
    delivery_portions,
    factory_readiness,
    production_by_op,
)
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData


@dataclass(slots=True)
class StockDay:
    day_idx: int
    date: str
    demand: int
    produced: int
    cum_demand: int
    cum_produced: int
    stock: int  # cum_produced - cum_demand (NP já desconta stock inicial)
    machine: str | None  # where it was produced (None if nothing produced)
    is_buffer: bool = False
    # Subcontracted SKUs: pieces stamped on this day that go to the
    # subcontractor (counted in ``produced`` only on their return day) and the
    # returns that make up ``produced`` here, each with its stamping days and
    # machines.
    subcontract_sent: int = 0
    subcontract_returns: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class StockProjection:
    op_id: str
    sku: str
    client: str
    days: list[StockDay]
    initial_stock: int
    stockout_day: int | None  # first day with stock < 0
    coverage_days: float
    total_demand: int
    total_produced: int
    subcontract_company_id: str | None = None
    internal_deadline_min: int | None = None
    first_production_due_day: int | None = None
    first_subcontract_dispatch_day: int | None = None


def build_production_by_op(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData | None = None,
) -> dict[str, dict[int, int]]:
    """Production by (op_id, day_idx), from the shared readiness evaluator.

    Without ``engine_data`` every piece counts on the day it is produced
    (factory view). With it, the customer view: a subcontracted delivery
    (served first-in-first-out by all lots of its operation) counts when it
    returns, its own completion plus the lead time in working days, and
    committed supplies count on their available day.
    """
    if engine_data is None:
        prod: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        for record in factory_readiness(lots, segments, missing_day=0):
            for item in record.slices:
                prod[record.op_id][item.day_idx] += item.qty
        return prod
    return _customer_production(delivery_portions(lots, segments, engine_data), engine_data)


def _customer_production(
    portions: list[DeliveryPortion],
    engine_data: EngineData,
) -> dict[str, dict[int, int]]:
    prod = production_by_op(portions)
    for supply in engine_data.committed_supplies:
        prod[supply.op_id][supply.available_day] += supply.qty
    return prod


def _subcontract_movements(
    portions: list[DeliveryPortion],
    segments: list[Segment],
) -> tuple[dict[str, dict[int, int]], dict[str, dict[int, list[dict]]]]:
    """Pieces sent to and returned from the subcontractor, per (op_id, day).

    Read from the shared evaluator (``delivery_portions``). A lot that goes
    out whole (material version 3, ``whole_lot_subcontract``, 13/10/2026)
    is shown leaving whole on its completion day and back together on its
    return day, stamped over the whole lot's days and machines. Older lots
    keep the per-delivery rule: a portion's pieces leave on the days they are
    stamped (its slices) and come back together on its customer-ready day.
    Portions stamped on the same days and machines that come back on the
    same day are one return.
    """
    sent: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    returns: dict[str, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    by_origin: dict[tuple, dict] = {}

    def machines_of(items) -> set[str]:
        return {
            segments[item.segment_index].machine_id
            for item in items
            if 0 <= item.segment_index < len(segments)
        }

    # Stamping days and machines of each whole lot, over all its portions.
    whole_lots: dict[str, list] = defaultdict(list)
    for portion in portions:
        if portion.is_subcontracted and portion.whole_lot_dispatch:
            for item in portion.slices:
                if item.whole_lot:
                    whole_lots[item.lot_id].append(item)

    for portion in portions:
        if not portion.is_subcontracted or not portion.produced_qty:
            continue
        for item in portion.slices:
            leaves = item.available_day if item.lot_id in whole_lots else item.day_idx
            sent[portion.op_id][leaves] += item.qty
        lots_out_whole = {item.lot_id for item in portion.slices if item.lot_id in whole_lots}
        stamped_items = [
            *portion.slices, *(item for lot_id in lots_out_whole for item in whole_lots[lot_id]),
        ]
        stamped = [item.day_idx for item in stamped_items]
        machines = sorted(machines_of(stamped_items))
        first = min(stamped, default=portion.factory_day)
        last = max(stamped, default=portion.factory_day)
        for day, qty in portion.credits():
            key = (portion.op_id, day, first, last, tuple(machines))
            if key in by_origin:
                by_origin[key]["qty"] += qty
                continue
            by_origin[key] = {
                "qty": qty,
                "stamped_from_day": first,
                "stamped_to_day": last,
                "machines": machines,
            }
            returns[portion.op_id][day].append(by_origin[key])
    return sent, returns


def compute_stock_projections(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    buffer_days: int = 0,
) -> list[StockProjection]:
    """Compute stock projection for every EOp."""
    portions = delivery_portions(lots, segments, engine_data)
    prod = _customer_production(portions, engine_data)
    sub_sent, sub_returns = _subcontract_movements(portions, segments)

    # Build machine-by-(op_id, day) for the machine field
    op_machine: dict[str, dict[int, str]] = defaultdict(dict)
    lot_to_op: dict[str, str] = {lot.id: lot.op_id for lot in lots}
    for seg in segments:
        if seg.twin_outputs:
            for op_id, _sku, _qty in seg.twin_outputs:
                op_machine[op_id][seg.day_idx] = seg.machine_id
        else:
            oid = lot_to_op.get(seg.lot_id, "")
            if oid:
                op_machine[oid][seg.day_idx] = seg.machine_id

    # Generate buffer day dates (workdays before first ISOP date)
    buffer_dates: list[str] = []
    if buffer_days > 0 and engine_data.workdays:
        first = _dt.date.fromisoformat(engine_data.workdays[0])
        d = first
        while len(buffer_dates) < buffer_days:
            d -= _dt.timedelta(days=1)
            if d.weekday() < 5:  # skip weekends
                buffer_dates.append(d.isoformat())
        buffer_dates.reverse()  # oldest first: [-N, ..., -1]

    projections: list[StockProjection] = []

    for op in engine_data.ops:
        initial_stock = op.stk
        cum_demand = 0
        cum_produced = 0
        stockout_day: int | None = None
        days: list[StockDay] = []

        op_prod = prod.get(op.id, {})

        # Buffer days (negative day_idx): demand=0, only production
        for i, neg_day in enumerate(range(-buffer_days, 0)):
            produced = op_prod.get(neg_day, 0)
            cum_produced += produced
            stock = cum_produced - cum_demand
            machine = op_machine.get(op.id, {}).get(neg_day)

            days.append(
                StockDay(
                    day_idx=neg_day,
                    date=buffer_dates[i] if i < len(buffer_dates) else "",
                    demand=0,
                    produced=produced,
                    cum_demand=cum_demand,
                    cum_produced=cum_produced,
                    stock=stock,
                    machine=machine,
                    is_buffer=True,
                )
            )

        # Regular days (day_idx >= 0)
        for day_idx in range(engine_data.n_days):
            demand = op.d[day_idx] if day_idx < len(op.d) else 0
            demand = max(demand, 0)
            produced = op_prod.get(day_idx, 0)

            cum_demand += demand
            cum_produced += produced
            stock = cum_produced - cum_demand

            if stock < 0 and stockout_day is None:
                stockout_day = day_idx

            machine = op_machine.get(op.id, {}).get(day_idx)

            days.append(
                StockDay(
                    day_idx=day_idx,
                    date=engine_data.workdays[day_idx]
                    if day_idx < len(engine_data.workdays)
                    else "",
                    demand=demand,
                    produced=produced,
                    cum_demand=cum_demand,
                    cum_produced=cum_produced,
                    stock=stock,
                    machine=machine,
                )
            )

        _attach_subcontract_movements(days, sub_sent.get(op.id, {}), sub_returns.get(op.id, {}))
        coverage = _calc_coverage(days)

        projections.append(
            StockProjection(
                op_id=op.id,
                sku=op.sku,
                client=op.client,
                days=days,
                initial_stock=initial_stock,
                stockout_day=stockout_day,
                coverage_days=coverage,
                total_demand=cum_demand,
                total_produced=cum_produced,
                subcontract_company_id=op.subcontract_company_id,
                internal_deadline_min=_first_internal_deadline(op, engine_data),
                first_production_due_day=_first_milestone(
                    op,
                    engine_data,
                    "production_due_day",
                ),
                first_subcontract_dispatch_day=_first_milestone(
                    op,
                    engine_data,
                    "subcontract_dispatch_day",
                ),
            )
        )

    return projections


def _attach_subcontract_movements(
    days: list[StockDay],
    sent: dict[int, int],
    returns: dict[int, list[dict]],
) -> None:
    if not sent and not returns:
        return
    date_of = {day.day_idx: day.date for day in days}
    for day in days:
        day.subcontract_sent = sent.get(day.day_idx, 0)
        day.subcontract_returns = [
            {
                **item,
                "stamped_from_date": date_of.get(item["stamped_from_day"], ""),
                "stamped_to_date": date_of.get(item["stamped_to_day"], ""),
            }
            for item in returns.get(day.day_idx, [])
        ]


def _calc_coverage(days: list[StockDay]) -> float:
    """Days until first stockout (buffer days excluded)."""
    n_regular = 0
    for d in days:
        if d.is_buffer:
            continue
        n_regular += 1
        if d.stock < 0:
            return float(d.day_idx)
    return float(n_regular)


def _first_internal_deadline(op, engine_data: EngineData) -> int | None:
    """Earliest calendar-aware internal target for this SKU."""

    return _first_milestone(op, engine_data, "internal_target_day")


def _first_milestone(op, engine_data: EngineData, field: str) -> int | None:
    holidays = calendar_holidays(engine_data, -90, engine_data.n_days + 14)
    for day_idx, demand in enumerate(op.d):
        if demand > 0:
            return getattr(planning_milestones_for_op(op, day_idx, holidays), field)
    return None
