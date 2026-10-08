"""Stock Projection — Spec 03 §1.

Day-by-day stock projection per EOp:
  stock[day] = cum_produced - cum_demand

NP negativo já desconta stock inicial, por isso initial_stock NÃO entra na fórmula.
Production comes from real Segments. Demand from EngineData op.d.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass

from backend.config.planning import planning_milestones_for_op
from backend.scheduler.jit_policy import (
    add_workdays,
    calendar_holidays,
    lot_output_milestones,
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
    internal_deadline_min: int | None = None
    first_production_due_day: int | None = None
    first_subcontract_dispatch_day: int | None = None


def build_production_by_op(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData | None = None,
) -> dict[str, dict[int, int]]:
    """Production by (op_id, day_idx).

    Twin segments credit each op_id via twin_outputs.
    Solo segments resolve op_id via lot_to_op mapping.
    """
    lot_to_op: dict[str, str] = {lot.id: lot.op_id for lot in lots}
    output_by_lot_op = {
        (lot.id, str(output.get("op_id", lot.op_id))): output
        for lot in lots
        for output in lot_output_milestones(lot)
    }

    prod: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    external_qty: dict[tuple[str, str], int] = defaultdict(int)
    external_completion: dict[tuple[str, str], int] = {}

    for seg in segments:
        if seg.twin_outputs:
            for op_id, _sku, qty in seg.twin_outputs:
                output = output_by_lot_op.get((seg.lot_id, op_id), {})
                if engine_data is not None and bool(output.get("is_subcontracted")):
                    key = (seg.lot_id, op_id)
                    external_qty[key] += qty
                    external_completion[key] = max(
                        external_completion.get(key, seg.day_idx),
                        seg.day_idx,
                    )
                else:
                    prod[op_id][seg.day_idx] += qty
        else:
            op_id = lot_to_op.get(seg.lot_id, "")
            if op_id:
                output = output_by_lot_op.get((seg.lot_id, op_id), {})
                if engine_data is not None and bool(output.get("is_subcontracted")):
                    key = (seg.lot_id, op_id)
                    external_qty[key] += seg.qty
                    external_completion[key] = max(
                        external_completion.get(key, seg.day_idx),
                        seg.day_idx,
                    )
                else:
                    prod[op_id][seg.day_idx] += seg.qty

    if engine_data is not None:
        max_lead = max(
            (
                int(output.get("subcontract_lead_time_days", 0) or 0)
                for output in output_by_lot_op.values()
            ),
            default=0,
        )
        holidays = calendar_holidays(
            engine_data,
            min((segment.day_idx for segment in segments), default=0) - 14,
            engine_data.n_days + max_lead * 2 + 14,
        )
        for key, qty in external_qty.items():
            _lot_id, op_id = key
            output = output_by_lot_op.get(key, {})
            ready_day = add_workdays(
                external_completion[key],
                int(output.get("subcontract_lead_time_days", 0) or 0),
                holidays,
            )
            prod[op_id][ready_day] += qty
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
    prod = build_production_by_op(segments, lots, engine_data)

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
