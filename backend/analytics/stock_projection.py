"""Stock Projection — Spec 03 §1.

Day-by-day stock projection per EOp:
  stock[day] = cum_produced - cum_demand

NP negativo já desconta stock inicial, por isso initial_stock NÃO entra na fórmula.
Production comes from real Segments. Demand from EngineData op.d.

Every reference, subcontracted or not, counts its pieces on the day they are
produced in the factory (14/10/2026: the screen does not show trips to and
from the subcontractor). The rupture (``stockout_day``) follows that same
stock: the first day it goes negative (Incompol, 14/10/2026). A subcontracted
delivery is late exactly when this stock is short on its day (Luís,
14/10/2026); finishing five working days before it is the planner's aim,
never reported as a delay.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass

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
    # Subcontracted: production must be finished this many working days
    # before each delivery (subcontract lead time plus its buffer).
    subcontract_due_workdays: int | None = None
    internal_deadline_min: int | None = None
    first_production_due_day: int | None = None
    first_subcontract_dispatch_day: int | None = None


def build_production_by_op(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData | None = None,
) -> dict[str, dict[int, int]]:
    """Production by (op_id, day_idx), from the shared readiness evaluator.

    Every piece counts on the day it is produced, subcontracted ones too
    (14/10/2026). With ``engine_data``, committed supplies count on their
    available day.
    """
    if engine_data is None:
        prod: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        for record in factory_readiness(lots, segments, missing_day=0):
            for item in record.slices:
                prod[record.op_id][item.day_idx] += item.qty
        return prod
    return _production(delivery_portions(lots, segments, engine_data), engine_data)


def _production(
    portions: list[DeliveryPortion],
    engine_data: EngineData,
) -> dict[str, dict[int, int]]:
    prod = production_by_op(portions)
    for supply in engine_data.committed_supplies:
        prod[supply.op_id][supply.available_day] += supply.qty
    return prod


def compute_stock_projections(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    buffer_days: int = 0,
) -> list[StockProjection]:
    """Compute stock projection for every EOp."""
    portions = delivery_portions(lots, segments, engine_data)
    # Every piece on the day it is produced (subcontracted ones too); the
    # rupture is read from this same stock.
    prod = _production(portions, engine_data)

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

        stockout_day, coverage = _stockout(
            op, op_prod, buffer_days, engine_data.n_days,
        )

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
                subcontract_due_workdays=_subcontract_due_workdays(op),
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


def _stockout(
    op,
    op_prod: dict[int, int],
    buffer_days: int,
    n_days: int,
) -> tuple[int | None, float]:
    """First day the shown stock goes negative (``stockout_day``) and the days
    covered until then (buffer days excluded, the whole horizon if none).

    Cumulative production minus cumulative demand, exactly like the grid, for
    every reference: a subcontracted one is judged on the stock shown (its
    pieces on the day they are produced), never on the day they are back.
    """
    available = sum(op_prod.get(day, 0) for day in range(-buffer_days, 0))
    demanded = 0
    for day_idx in range(n_days):
        demanded += max(op.d[day_idx], 0) if day_idx < len(op.d) else 0
        available += op_prod.get(day_idx, 0)
        if available < demanded:
            return day_idx, float(day_idx)
    return None, float(n_days)


def _subcontract_due_workdays(op) -> int | None:
    lead = max(0, int(getattr(op, "subcontract_lead_time_days", 0) or 0))
    buffer = max(0, int(getattr(op, "subcontract_buffer_days", 0) or 0))
    if not (getattr(op, "is_subcontracted", False) or op.subcontract_company_id or lead):
        return None
    return lead + buffer


def _first_internal_deadline(op, engine_data: EngineData) -> int | None:
    """Earliest calendar-aware internal target for this SKU."""

    return _first_milestone(op, engine_data, "internal_target_day")


def _first_milestone(op, engine_data: EngineData, field: str) -> int | None:
    holidays = calendar_holidays(engine_data, -90, engine_data.n_days + 14)
    for day_idx, demand in enumerate(op.d):
        if demand > 0:
            return getattr(planning_milestones_for_op(op, day_idx, holidays), field)
    return None
