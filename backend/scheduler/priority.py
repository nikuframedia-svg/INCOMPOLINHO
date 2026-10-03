"""Deterministic production and best-effort delivery priorities."""

from __future__ import annotations

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


def delivery_is_complete(score: Mapping[str, object] | None) -> bool:
    """Whether every delivery and demand checkpoint is fully on time."""

    values = score or {}
    return (
        _metric(values, "otd", 100.0) >= 100.0
        and _metric(values, "otd_d", 100.0) >= 100.0
        and all(_metric(values, key) <= 0.0 for key in DELIVERY_PRIORITY_KEYS)
    )


def delivery_priority_key(
    score: Mapping[str, object] | None,
    *,
    use_daily_shortfall: bool = True,
) -> tuple[object, ...]:
    """Lexicographic delivery rank used whenever a plan is infeasible.

    Fully delivered plans always rank ahead of best-effort plans. Among two
    infeasible plans, explicit customer priorities and customer delivery
    performance remain decisive. Subcontract dispatch then resolves plans with
    equivalent customer outcomes, so a buffer recovery can never buy a worse
    customer commitment.
    """

    values = score or {}
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


def delivery_improves(
    candidate: Mapping[str, object] | None,
    reference: Mapping[str, object] | None,
) -> bool:
    if _regresses_delivery_guards(candidate, reference):
        return False
    use_daily = _has_daily_shortfall(candidate) and _has_daily_shortfall(reference)
    return delivery_priority_key(candidate, use_daily_shortfall=use_daily) < delivery_priority_key(
        reference, use_daily_shortfall=use_daily
    )


def delivery_not_worse(
    candidate: Mapping[str, object] | None,
    reference: Mapping[str, object] | None,
) -> bool:
    if _regresses_delivery_guards(candidate, reference):
        return False
    use_daily = _has_daily_shortfall(candidate) and _has_daily_shortfall(reference)
    return delivery_priority_key(candidate, use_daily_shortfall=use_daily) <= delivery_priority_key(
        reference, use_daily_shortfall=use_daily
    )


def _has_daily_shortfall(score: Mapping[str, object] | None) -> bool:
    return isinstance((score or {}).get("otd_d_daily_shortfall_qty"), (list, tuple))


def _regresses_delivery_guards(
    candidate: Mapping[str, object] | None,
    reference: Mapping[str, object] | None,
) -> bool:
    candidate_values = candidate or {}
    reference_values = reference or {}
    return any(
        _metric(candidate_values, key) > _metric(reference_values, key)
        for key in ("hard_violations", "tardy_count", "otd_d_failures")
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
