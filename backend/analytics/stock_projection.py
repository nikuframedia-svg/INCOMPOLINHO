"""Stock Projection — Spec 03 §1.

Day-by-day stock projection per EOp:
  stock[day] = cum_produced - cum_demand

Production comes from real Segments. Demand from EngineData op.d.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

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
    stock: int  # cum_produced - cum_demand
    machine: str | None  # where it was produced (None if nothing produced)


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


def build_production_by_op(
    segments: list[Segment],
    lots: list[Lot],
) -> dict[str, dict[int, int]]:
    """Production by (op_id, day_idx).

    Twin segments credit each op_id via twin_outputs.
    Solo segments resolve op_id via lot_to_op mapping.
    """
    lot_to_op: dict[str, str] = {lot.id: lot.op_id for lot in lots}

    prod: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for seg in segments:
        if seg.twin_outputs:
            for op_id, _sku, qty in seg.twin_outputs:
                prod[op_id][seg.day_idx] += qty
        else:
            op_id = lot_to_op.get(seg.lot_id, "")
            if op_id:
                prod[op_id][seg.day_idx] += seg.qty

    return prod


def compute_stock_projections(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
) -> list[StockProjection]:
    """Compute stock projection for every EOp."""
    prod = build_production_by_op(segments, lots)

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

    projections: list[StockProjection] = []

    for op in engine_data.ops:
        initial_stock = op.stk
        cum_demand = 0
        cum_produced = 0
        stockout_day: int | None = None
        days: list[StockDay] = []

        # Pre-accumulate production from negative days (buffer unshift)
        op_prod = prod.get(op.id, {})
        for neg_day, qty in op_prod.items():
            if neg_day < 0:
                cum_produced += qty

        for day_idx in range(engine_data.n_days):
            demand = op.d[day_idx] if day_idx < len(op.d) else 0
            demand = max(demand, 0)
            produced = op_prod.get(day_idx, 0)

            cum_demand += demand
            cum_produced += produced
            stock = initial_stock + cum_produced - cum_demand

            if stock < 0 and stockout_day is None:
                stockout_day = day_idx

            machine = op_machine.get(op.id, {}).get(day_idx)

            days.append(
                StockDay(
                    day_idx=day_idx,
                    date=engine_data.workdays[day_idx] if day_idx < len(engine_data.workdays) else "",
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
            )
        )

    return projections


def _calc_coverage(days: list[StockDay]) -> float:
    """Days until first stockout."""
    for d in days:
        if d.stock < 0:
            return float(d.day_idx)
    return float(len(days))
