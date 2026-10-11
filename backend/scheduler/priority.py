"""Deterministic production and best-effort delivery priorities."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping

from backend.scheduler.jit_policy import (
    expedition_day,
    planning_deadline_day,
    production_due_day,
)
from backend.scheduler.types import Lot, ToolRun

DELIVERY_PRIORITY_KEYS = (
    "priority_tardy_count",
    "priority_tardy_weight",
    "priority_tardiness_weighted",
    "tardy_count",
    "otd_d_failures",
    "otd_d_cumulative_shortfall_qty",
    "otd_d_final_shortfall_qty",
    "total_tardiness",
    "max_tardiness",
    "subcontract_dispatch_misses",
    "subcontract_dispatch_late_workdays",
)


def lot_delivery_qty(lot: Lot) -> int:
    """Return the delivered quantity represented by a lot.

    A twin cycle delivers every output simultaneously, so its priority uses
    the sum of those outputs instead of the primary lot quantity.
    """

    if lot.twin_outputs:
        return sum(max(0, int(qty)) for _op_id, _sku, qty in lot.twin_outputs)
    return max(0, int(lot.qty))


def lot_rupture_day(lot: Lot) -> int:
    """Return the demand checkpoint at which this lot first prevents a deficit.

    A lot is created at the first unmet demand after stock and committed supply
    have been applied.  ``original_edd`` therefore captures the operational
    rupture date, while ``internal_deadline`` may be deliberately moved by a
    customer buffer.  The former has to win when the two references compete
    for the same capacity.
    """

    if lot.original_edd is not None:
        return int(lot.original_edd)
    return expedition_day(lot)


def lot_priority_key(lot: Lot) -> tuple[int, int, int, int, int, int, int, str]:
    """Order lots by controllable due date before campaign convenience.

    Subcontracted production must leave the factory before the customer date,
    so its dispatch milestone is decisive. For normal output this first key is
    the customer date and preserves the historical order.
    """

    return (
        production_due_day(lot),
        lot_rupture_day(lot),
        -max(0, int(lot.planning_priority or 0)),
        int(lot.target_start_day if lot.target_start_day is not None else lot.edd),
        planning_deadline_day(lot),
        expedition_day(lot),
        -lot_delivery_qty(lot),
        str(lot.id),
    )


type OutputPriorityKey = tuple[int, int, int, int, int, int, int, str, int]


def output_priority_key(
    lot: Lot,
    index: int | None = None,
    *,
    delivery_qty: int | None = None,
) -> OutputPriorityKey:
    """Commercial priority of one delivery (output) of a lot (policy v3).

    ``index`` is the position of the output in ``lot.output_milestones``;
    ``None`` ranks the lot as a whole, exactly as ``lot_priority_key`` (the
    trailing ``-1`` only makes both shapes comparable). An output ranks by
    its own milestones, read as the builder reads a portion
    (``quantity_dispatch._portion_lot``): production due day, customer day as
    the rupture, the lot's planning priority, its own target start, internal
    target and customer day, then the larger quantity to deliver
    (``delivery_qty``: the customer delivery over every lot of the
    operation; default the output's own quantity), lot id and position.
    """

    if index is None:
        return (*lot_priority_key(lot), -1)
    output = (lot.output_milestones or [])[index]

    def day(name: str, default: int) -> int:
        value = output.get(name)
        return int(value) if value is not None else int(default)

    due = day("production_due_day", production_due_day(lot))
    customer = day("customer_delivery_day", expedition_day(lot))
    target_start = (
        max(0, customer - int(lot.start_buffer_days or 0))
        if lot.target_start_day is not None else due
    )
    qty = int(output.get("qty") or 0) if delivery_qty is None else int(delivery_qty)
    return (
        due,
        customer,
        -max(0, int(lot.planning_priority or 0)),
        target_start,
        day("internal_target_day", planning_deadline_day(lot)),
        customer,
        -max(0, qty),
        str(lot.id),
        int(index),
    )


def run_urgent_delivery_qty(run: ToolRun) -> int:
    """Quantity due at the run's earliest stock-risk checkpoint."""

    if not run.lots:
        return 0
    earliest_rupture = min(lot_rupture_day(lot) for lot in run.lots)

    return sum(
        lot_delivery_qty(lot)
        for lot in run.lots
        if lot_rupture_day(lot) == earliest_rupture
    )


def run_priority_key(run: ToolRun) -> tuple[int, int, int, int, int, int, int, int, str]:
    """Order runs by their most urgent lot, then delivered quantity."""

    if run.lots:
        urgent = min(run.lots, key=lot_priority_key)
        urgency = lot_priority_key(urgent)
    else:
        urgency = (
            int(run.edd),
            int(run.edd),
            0,
            int(run.edd),
            int(run.edd),
            int(run.edd),
            0,
            "",
        )
    return (
        urgency[0],
        urgency[1],
        int(run.edd),
        urgency[2],
        urgency[3],
        urgency[4],
        urgency[5],
        -run_urgent_delivery_qty(run),
        str(run.id),
    )


def enforce_same_deadline_run_priority(runs: list[ToolRun]) -> list[ToolRun]:
    """Restore deterministic quantity order inside equal urgency classes."""

    result = list(runs)
    positions: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, run in enumerate(result):
        priority = run_priority_key(run)
        positions[(priority[0], priority[1])].append(index)
    for indexes in positions.values():
        ordered = sorted((result[index] for index in indexes), key=run_priority_key)
        for index, run in zip(indexes, ordered):
            result[index] = run
    return result


# Per-order delivery (AGENTS §1.2, decided 11/10/2026): the comparator
# judges customer orders, read from ``material_quantities.delivery_readiness``
# through ``improvement.order_service`` (pieces of a SKU are fungible, FIFO
# over every lot of the operation). Lot tardiness (``tardy_count``,
# ``total_tardiness``, ``otd``) is an indicator only on this basis.
ORDER_DELIVERY_KEYS = ("orders_late", "orders_unready", "order_late_days")
ORDER_PRIORITY_KEYS = (
    "priority_orders_late",
    "priority_order_late_weight",
    # Never-ready priority orders rank before weighted days: their days are
    # not summed, so a 30-day-late order must never "improve" into one that
    # is never ready (review of 11/10/2026).
    "priority_orders_unready",
    "priority_order_late_days_weighted",
)
_ORDER_COMPLETE_KEYS = (
    *ORDER_PRIORITY_KEYS,
    *ORDER_DELIVERY_KEYS,
    "otd_d_failures",
    "otd_d_cumulative_shortfall_qty",
    "otd_d_final_shortfall_qty",
    "subcontract_dispatch_misses",
    "subcontract_dispatch_late_workdays",
)


def sku_planning_priorities(data) -> dict[str, int]:
    """Configured planning priority of each SKU (the largest of its ops)."""

    priorities: dict[str, int] = {}
    for op in getattr(data, "ops", None) or ():
        value = max(0, int(getattr(op, "planning_priority", 0) or 0))
        priorities[op.sku] = max(priorities.get(op.sku, 0), value)
    return priorities


def order_delivery_metrics(
    orders: Mapping[tuple, object],
    priorities: Mapping[str, int] | None = None,
) -> dict[str, float]:
    """Order lateness of one plan, from ``improvement.order_service``.

    ``orders`` maps an order key whose first element is the SKU to its
    service (``tardiness`` in days; ``inf`` when the order is never fully
    ready). An order is late when ``tardiness > 0``; one never ready is late
    and also counted in ``orders_unready`` (its days are not summed, so a
    finite total stays comparable). ``priorities`` (SKU -> configured
    planning priority) weighs the explicit customer priorities.
    """

    late = unready = 0
    days = 0.0
    priority_late = priority_weight = priority_unready = 0
    priority_days = 0.0
    for key, service in orders.items():
        tardiness = float(getattr(service, "tardiness", 0.0) or 0.0)
        if tardiness <= 0:
            continue
        late += 1
        finite = not math.isinf(tardiness)
        if finite:
            days += tardiness
        else:
            unready += 1
        priority = int((priorities or {}).get(str(key[0]), 0) or 0)
        if priority > 0:
            priority_late += 1
            priority_weight += priority
            if finite:
                priority_days += priority * tardiness
            else:
                priority_unready += 1
    return {
        "orders_late": late,
        "orders_unready": unready,
        "order_late_days": round(days, 6),
        "priority_orders_late": priority_late,
        "priority_order_late_weight": priority_weight,
        "priority_orders_unready": priority_unready,
        "priority_order_late_days_weighted": round(priority_days, 6),
    }


def with_order_delivery(
    score: Mapping[str, object] | None,
    segments,
    lots,
    data,
) -> dict[str, object]:
    """Copy of ``score`` with the per-order delivery metrics of the plan."""

    from backend.scheduler.improvement import order_service

    return {
        **dict(score or {}),
        **order_delivery_metrics(
            order_service(segments, lots, data), sku_planning_priorities(data),
        ),
    }


def has_order_delivery(score: Mapping[str, object] | None) -> bool:
    """Whether ``score`` carries the per-order delivery metrics."""

    values = score or {}
    return all(key in values for key in ORDER_DELIVERY_KEYS)


def _per_order(*scores: Mapping[str, object] | None) -> bool:
    return all(has_order_delivery(score) for score in scores)


def delivery_is_complete(score: Mapping[str, object] | None) -> bool:
    """Whether every delivery and demand checkpoint is fully on time.

    Per order when the score carries the order metrics; otherwise the
    historical lot reading (scores from ``compute_score`` alone).
    """

    values = score or {}
    if has_order_delivery(values):
        return _metric(values, "otd_d", 100.0) >= 100.0 and all(
            _metric(values, key) <= 0.0 for key in _ORDER_COMPLETE_KEYS
        )
    return (
        _metric(values, "otd", 100.0) >= 100.0
        and _metric(values, "otd_d", 100.0) >= 100.0
        and all(_metric(values, key) <= 0.0 for key in DELIVERY_PRIORITY_KEYS)
    )


def delivery_priority_key(
    score: Mapping[str, object] | None,
    *,
    use_daily_shortfall: bool = True,
    per_order: bool | None = None,
) -> tuple[object, ...]:
    """Lexicographic delivery rank used whenever a plan is infeasible.

    Fully delivered plans always rank ahead of best-effort plans. Per order
    (the score carries ``ORDER_DELIVERY_KEYS``, see ``with_order_delivery``;
    ``per_order`` forces the basis): explicit customer priorities of late
    orders, then late orders, never-ready orders, total order days late,
    then OTD-D failures and shortfalls, released-tool inversions and
    subcontract dispatch. Lot tardiness does not rank on this basis.
    Without the order metrics the historical lot key applies; compare two
    keys only on the same basis (``delivery_improves`` and
    ``delivery_not_worse`` choose it for both scores).
    """

    values = score or {}
    if per_order is None:
        per_order = has_order_delivery(values)
    daily_shortfall = values.get("otd_d_daily_shortfall_qty")
    shortfall_key = (
        tuple(
            (-day, int(qty))
            for day, qty in enumerate(daily_shortfall)
            if int(qty) > 0
        )
        if use_daily_shortfall and isinstance(daily_shortfall, (list, tuple))
        else ()
    )
    if per_order:
        return (
            0.0 if delivery_is_complete(values) else 1.0,
            *(_metric(values, key) for key in ORDER_PRIORITY_KEYS),
            *(_metric(values, key) for key in ORDER_DELIVERY_KEYS),
            _metric(values, "otd_d_failures"),
            shortfall_key,
            _metric(values, "released_tool_priority_inversions"),
            _metric(values, "otd_d_cumulative_shortfall_qty"),
            _metric(values, "otd_d_final_shortfall_qty"),
            -_metric(values, "otd_d", 100.0),
            _metric(values, "subcontract_dispatch_misses"),
            _metric(values, "subcontract_dispatch_late_workdays"),
        )
    return (
        0.0 if delivery_is_complete(values) else 1.0,
        _metric(values, "priority_tardy_count"),
        _metric(values, "priority_tardy_weight"),
        _metric(values, "priority_tardiness_weighted"),
        shortfall_key,
        _metric(values, "released_tool_priority_inversions"),
        _metric(values, "tardy_count"),
        _metric(values, "otd_d_failures"),
        _metric(values, "otd_d_cumulative_shortfall_qty"),
        _metric(values, "otd_d_final_shortfall_qty"),
        _metric(values, "total_tardiness"),
        _metric(values, "max_tardiness"),
        -_metric(values, "otd", 100.0),
        -_metric(values, "otd_d", 100.0),
        _metric(values, "subcontract_dispatch_misses"),
        _metric(values, "subcontract_dispatch_late_workdays"),
    )


def _pair_keys(candidate, reference) -> tuple[tuple, tuple]:
    use_daily = _has_daily_shortfall(candidate) and _has_daily_shortfall(reference)
    per_order = _per_order(candidate, reference)
    return (
        delivery_priority_key(candidate, use_daily_shortfall=use_daily, per_order=per_order),
        delivery_priority_key(reference, use_daily_shortfall=use_daily, per_order=per_order),
    )


def delivery_improves(
    candidate: Mapping[str, object] | None,
    reference: Mapping[str, object] | None,
) -> bool:
    if _regresses_delivery_guards(candidate, reference):
        return False
    candidate_key, reference_key = _pair_keys(candidate, reference)
    return candidate_key < reference_key


def delivery_not_worse(
    candidate: Mapping[str, object] | None,
    reference: Mapping[str, object] | None,
) -> bool:
    if _regresses_delivery_guards(candidate, reference):
        return False
    candidate_key, reference_key = _pair_keys(candidate, reference)
    return candidate_key <= reference_key


def _has_daily_shortfall(score: Mapping[str, object] | None) -> bool:
    return isinstance((score or {}).get("otd_d_daily_shortfall_qty"), (list, tuple))


def _regresses_delivery_guards(
    candidate: Mapping[str, object] | None,
    reference: Mapping[str, object] | None,
) -> bool:
    candidate_values = candidate or {}
    reference_values = reference or {}
    late = "orders_late" if _per_order(candidate, reference) else "tardy_count"
    return any(
        _metric(candidate_values, key) > _metric(reference_values, key)
        for key in ("hard_violations", late, "otd_d_failures")
    )


def _metric(
    score: Mapping[str, object],
    key: str,
    default: float = 0.0,
) -> float:
    try:
        return float(score.get(key, default) or 0.0)
    except (TypeError, ValueError):
        return default
