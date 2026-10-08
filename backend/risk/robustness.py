"""Reproducible fixed-plan robustness simulation.

The evaluator replays the visible plan under execution uncertainty; it never
re-optimizes or mutates the active plan.  This separates plan robustness from
the scheduler's ability to find a different plan after the disruption.

Model v5 is information only (AGENTS.md §1): it never ranks, gates or approves
a plan.  Disruptions, tardiness and the baseline tardy lots are limited to the
first ``ROBUSTNESS_HORIZON_WORKDAYS`` working days from the planning anchor
(today's day index when the ISOP covers today, otherwise day 0), because a
fixed-plan replay says little about deliveries weeks away that will be
replanned long before they happen.  Production before the anchor is history:
it is replayed exactly as planned, so every random disruption happens inside
the window.  A window without deliveries has no success probability (None),
never a perfect 100%.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import date, timedelta
from statistics import mean

from backend.config.shifts import clock_to_productive_offset, ordered_shifts
from backend.config.types import FactoryConfig
from backend.planning_control import (
    PlanningCancelled,
    current_planning_control,
    planning_checkpoint,
    planning_scope,
    wait_while_planning,
)
from backend.scheduler.jit_policy import (
    add_workdays,
    calendar_holidays,
    lot_demand_output_milestones,
    lot_output_milestones,
)
from backend.scheduler.operators import segment_operator_demand
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData

PROFILE_SAMPLES = {"quick": 100, "standard": 500, "intensive": 2000}
ROBUSTNESS_MODEL_VERSION = 5
ROBUSTNESS_HORIZON_WORKDAYS = 10


@dataclass(frozen=True, slots=True)
class RobustnessHorizon:
    """Working-day window whose deliveries and disruptions the model measures."""

    workdays: int
    start_day: int
    end_day: int
    days: tuple[int, ...]
    lot_ids: frozenset[str]

    def covers(self, day: int) -> bool:
        return self.start_day <= day <= self.end_day


@dataclass(slots=True)
class ScenarioOutcome:
    index: int
    seed: int
    otd: float
    tardy_count: int
    total_tardiness: int
    max_tardiness: int
    affected_lots: list[str]
    manifest: dict
    tardy_lot_ids: frozenset[str] | None = None


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] * (1 - fraction) + ordered[upper] * fraction)


def _snap_to_open_day(value: float, blocked: set[int], day_cap: int) -> float:
    current = max(value, -365.0 * day_cap)
    while True:
        planning_checkpoint()
        day = math.floor(current / day_cap)
        if day not in blocked:
            return current
        current = float((day + 1) * day_cap)


def _advance_work(value: float, duration: float, blocked: set[int], day_cap: int) -> float:
    return _advance_work_with_intervals(value, duration, blocked, day_cap, [])


def _advance_work_with_intervals(
    value: float,
    duration: float,
    blocked: set[int],
    day_cap: int,
    blocked_intervals: list[tuple[float, float]],
) -> float:
    cursor = _snap_to_open_day(value, blocked, day_cap)
    remaining = max(0.0, duration)
    intervals = _merge_intervals(blocked_intervals)
    while remaining > 0.001:
        planning_checkpoint()
        day = math.floor(cursor / day_cap)
        if day in blocked:
            cursor = float((day + 1) * day_cap)
            continue
        day_end = float((day + 1) * day_cap)
        active_block = next(
            (
                (start, end)
                for start, end in intervals
                if end > cursor + 0.001 and start < day_end - 0.001
            ),
            None,
        )
        if active_block is not None and active_block[0] <= cursor + 0.001:
            cursor = max(cursor, active_block[1])
            cursor = _snap_to_open_day(cursor, blocked, day_cap)
            continue
        available_end = (
            min(day_end, active_block[0])
            if active_block is not None
            else day_end
        )
        available = max(0.0, available_end - cursor)
        if available <= 0.001:
            cursor = available_end
            continue
        used = min(available, remaining)
        cursor += used
        remaining -= used
        if remaining > 0.001 and cursor >= day_end - 0.001:
            cursor = day_end
            cursor = _snap_to_open_day(cursor, blocked, day_cap)
    return cursor


def _absolute_intervals(
    entries: list[dict],
    config: FactoryConfig,
    *,
    open_horizon: float | None = None,
) -> list[tuple[float, float]]:
    day_cap = config.day_capacity_min
    result: list[tuple[float, float]] = []
    for entry in entries:
        start_day = int(entry.get("start_day", -1))
        end_day = int(entry.get("end_day", start_day))
        start_offset = clock_to_productive_offset(
            config,
            int(entry.get("start_min", config.shift_a_start)),
        )
        end_offset = clock_to_productive_offset(
            config,
            int(entry.get("end_min", config.shift_b_end)),
        )
        start = float(start_day * day_cap + start_offset)
        end = (
            float(open_horizon)
            if entry.get("open_end") and open_horizon is not None
            else float(end_day * day_cap + end_offset)
        )
        if end > start:
            result.append((start, end))
    return _merge_intervals(result)


def _merge_intervals(
    intervals: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1] + 0.001:
            merged.append([float(start), float(end)])
        else:
            merged[-1][1] = max(merged[-1][1], float(end))
    return [(start, end) for start, end in merged]


def _operator_demand(segment: Segment, data: EngineData) -> int:
    return segment_operator_demand(segment, data)


def _operator_absences(
    data: EngineData,
    config: FactoryConfig,
) -> list[tuple[str, str, float, float, int]]:
    result: list[tuple[str, str, float, float, int]] = []
    for block in data.operator_blocked_intervals:
        intervals = _absolute_intervals([block], config)
        if not intervals:
            continue
        start, end = intervals[0]
        result.append(
            (
                str(block.get("group", "")),
                str(block.get("shift", "")),
                start,
                end,
                max(0, int(block.get("count", 1))),
            )
        )
    return result


def _shift_at_coordinate(value: float, config: FactoryConfig) -> tuple[str, float]:
    """Return shift id and its absolute productive end for a coordinate."""

    day_cap = config.day_capacity_min
    day = math.floor(value / day_cap)
    offset = value - day * day_cap
    elapsed = 0
    shifts = ordered_shifts(config)
    for shift in shifts:
        duration = max(0, int(shift.end_min) - int(shift.start_min))
        end = elapsed + duration
        if offset < end - 0.001:
            return shift.id, float(day * day_cap + end)
        elapsed = end
    first = shifts[0]
    return first.id, float((day + 1) * day_cap + first.duration_min)


def _active_resource_block(
    cursor: float,
    intervals: list[tuple[float, float]],
) -> tuple[float, float] | None:
    return next(
        ((start, end) for start, end in intervals if start <= cursor + 0.001 < end),
        None,
    )


def _reserve_operator_work(
    value: float,
    duration: float,
    *,
    demand: int,
    group: str,
    blocked_days: set[int],
    blocked_intervals: list[tuple[float, float]],
    absences: list[tuple[str, str, float, float, int]],
    reservations: list[tuple[float, float, int]],
    config: FactoryConfig,
    horizon: float | None = None,
) -> float:
    """Advance production and reserve exact concurrent operator capacity."""

    day_cap = config.day_capacity_min
    fallback_horizon = float(
        (max(0, math.floor(value / day_cap)) + 366) * day_cap
    )
    stop_at = max(float(value), float(horizon or fallback_horizon))
    maximum_team = max(
        (
            max(0, int(config.operators.get((group, shift.id), 0)))
            for shift in ordered_shifts(config)
        ),
        default=0,
    )
    if demand > maximum_team:
        return stop_at

    cursor = _snap_to_open_day(value, blocked_days, day_cap)
    remaining = max(0.0, duration)
    resource_blocks = _merge_intervals(blocked_intervals)
    iterations = 0
    while remaining > 0.001:
        planning_checkpoint()
        if cursor >= stop_at - 0.001:
            return stop_at
        iterations += 1
        if iterations > 100_000:  # pragma: no cover - defensive malformed-calendar guard
            raise RuntimeError("Robustness replay could not advance operator timeline")

        cursor = _snap_to_open_day(cursor, blocked_days, day_cap)
        active_block = _active_resource_block(cursor, resource_blocks)
        if active_block is not None:
            cursor = active_block[1]
            continue

        shift_id, shift_end = _shift_at_coordinate(cursor, config)
        base = max(0, int(config.operators.get((group, shift_id), 0)))
        unavailable = sum(
            count
            for absence_group, absence_shift, start, end, count in absences
            if absence_group == group
            and absence_shift == shift_id
            and start <= cursor + 0.001 < end
        )
        occupied = sum(
            count
            for start, end, count in reservations
            if start <= cursor + 0.001 < end
        )

        day = math.floor(cursor / day_cap)
        boundaries = [float((day + 1) * day_cap), shift_end]
        boundaries.extend(
            point
            for start, end in resource_blocks
            for point in (start, end)
            if point > cursor + 0.001
        )
        boundaries.extend(
            point
            for absence_group, _absence_shift, start, end, _count in absences
            if absence_group == group
            for point in (start, end)
            if point > cursor + 0.001
        )
        boundaries.extend(
            point
            for start, end, _count in reservations
            for point in (start, end)
            if point > cursor + 0.001
        )
        boundary = min(min(boundaries), stop_at)
        if demand <= max(0, base - unavailable - occupied):
            used = min(remaining, boundary - cursor)
            if used > 0.001:
                reservations.append((cursor, cursor + used, demand))
                cursor += used
                remaining -= used
                continue
        cursor = boundary
    return cursor


def _scenario_manifest(
    rng: random.Random,
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    horizon: RobustnessHorizon | None = None,
) -> dict:
    machines = sorted({segment.machine_id for segment in segments})
    tools = sorted({segment.tool_id for segment in segments})
    if horizon is not None:
        # Events on lots outside the window cannot change the measured result.
        lots = [lot for lot in lots if lot.id in horizon.lot_ids]
        skus = sorted({lot.sku for lot in lots if lot.sku})
        measured = [
            segment
            for segment in segments
            if segment.lot_id in horizon.lot_ids and horizon.covers(segment.day_idx)
        ]
        # Breakdowns only on resources that produce measured lots in the window.
        down_machines = sorted({segment.machine_id for segment in measured})
        down_tools = sorted({segment.tool_id for segment in measured})
    else:
        skus = sorted({segment.sku for segment in segments if segment.sku})
        down_machines, down_tools = machines, tools
    lot_ids = [lot.id for lot in lots]

    def down_days(durations: list[int], weights: list[int]) -> list[int]:
        # Draw order (start, then duration) is part of the reproducible seed.
        if horizon is not None:
            first = rng.randrange(len(horizon.days)) if horizon.days else 0
            duration = rng.choices(durations, weights=weights, k=1)[0]
            # Consecutive working days, clipped to the end of the window.
            return list(horizon.days[first : first + duration])
        start = rng.randrange(max(1, data.n_days))
        duration = rng.choices(durations, weights=weights, k=1)[0]
        return list(range(start, start + duration))

    oee_mean = max(
        0.01,
        config.risk_oee_alpha
        / max(0.01, config.risk_oee_alpha + config.risk_oee_beta),
    )
    machine_efficiency = {
        machine: round(
            max(
                0.35,
                min(
                    1.4,
                    rng.betavariate(config.risk_oee_alpha, config.risk_oee_beta)
                    / oee_mean,
                ),
            ),
            4,
        )
        for machine in machines
    }
    processing_sigma = math.sqrt(
        math.log(1 + max(config.risk_processing_cv, 0.001) ** 2)
    )
    processing_factor = {
        machine: round(
            rng.lognormvariate(-0.5 * processing_sigma**2, processing_sigma),
            4,
        )
        for machine in machines
    }
    setup_sigma = math.sqrt(math.log(1 + max(config.risk_setup_cv, 0.01) ** 2))
    setup_factor = round(rng.lognormvariate(-0.5 * setup_sigma**2, setup_sigma), 4)

    machine_down: dict[str, list[int]] = {}
    if down_machines and rng.random() < 0.14:
        machine = rng.choice(down_machines)
        days = down_days([1, 2, 3], [70, 23, 7])
        if days:
            machine_down[machine] = days

    tool_down: dict[str, list[int]] = {}
    if down_tools and rng.random() < 0.08:
        tool = rng.choice(down_tools)
        days = down_days([1, 2], [85, 15])
        if days:
            tool_down[tool] = days

    material_delays: dict[str, int] = {}
    if lot_ids and rng.random() < 0.12:
        material_delays[rng.choice(lot_ids)] = rng.choices([1, 2, 3], [70, 25, 5], k=1)[0]

    demand_factors: dict[str, float] = {}
    if skus and rng.random() < 0.16:
        demand_factors[rng.choice(skus)] = rng.choice([0.9, 1.1, 1.2])

    stock_factors: dict[str, float] = {}
    if skus and rng.random() < 0.12:
        stock_factors[rng.choice(skus)] = rng.choice([1.05, 1.10, 1.20])

    subcontract_delays: dict[str, int] = {}
    subcontract_lots = [
        lot.id
        for lot in lots
        if any(
            bool(output.get("is_subcontracted"))
            for output in lot_demand_output_milestones(lot)
        )
    ]
    if subcontract_lots and rng.random() < 0.10:
        subcontract_delays[rng.choice(subcontract_lots)] = rng.choice([1, 2, 3])

    return {
        "machine_efficiency": machine_efficiency,
        "processing_factor": processing_factor,
        "setup_factor": setup_factor,
        "operator_factor": round(rng.choice([1.0, 1.0, 1.0, 1.08, 1.15]), 3),
        "machine_down": machine_down,
        "tool_down": tool_down,
        "material_delays": material_delays,
        "demand_factors": demand_factors,
        "stock_factors": stock_factors,
        "subcontract_delays": subcontract_delays,
    }


def replay_scenario(
    index: int,
    seed: int,
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    horizon: RobustnessHorizon | None = None,
) -> ScenarioOutcome:
    planning_checkpoint()
    rng = random.Random(seed)
    if horizon is None:
        manifest = _scenario_manifest(rng, segments, lots, data, config)
    else:
        manifest = _scenario_manifest(rng, segments, lots, data, config, horizon)
    day_cap = config.day_capacity_min
    max_lead = _max_subcontract_lead(lots)
    holidays = calendar_holidays(
        data,
        -30,
        data.n_days + max_lead * 2 + 30,
    )

    machine_available: dict[str, float] = {}
    tool_available: dict[str, float] = {}
    crew_available: dict[str, list[float]] = {}
    operator_reservations: dict[str, list[tuple[float, float, int]]] = {}
    lot_completion: dict[str, int] = {}
    operator_absences = _operator_absences(data, config)
    open_horizon = float((data.n_days + max_lead * 2 + 365) * day_cap)

    ordered = sorted(
        (segment for segment in segments if segment.prod_min > 0 or segment.setup_min > 0),
        key=lambda segment: (segment.day_idx, segment.start_min, segment.machine_id),
    )
    if horizon is not None:
        # The replay is a forward pass: a later segment never moves an earlier
        # one, so stopping after the last measured lot gives the same result.
        last = max(
            (index for index, segment in enumerate(ordered) if segment.lot_id in horizon.lot_ids),
            default=-1,
        )
        ordered = ordered[: last + 1]
    measured_lots = (
        lots if horizon is None else [lot for lot in lots if lot.id in horizon.lot_ids]
    )
    for segment in ordered:
        planning_checkpoint()
        planned = segment.day_idx * day_cap + clock_to_productive_offset(
            config,
            segment.start_min,
        )
        if horizon is not None and segment.day_idx < horizon.start_day:
            # Before the anchor is history: replay it exactly as planned, so no
            # random factor there can spill into the measured window.
            end = max(
                planned,
                float(
                    segment.day_idx * day_cap
                    + clock_to_productive_offset(config, segment.end_min)
                ),
            )
            _record_completion(
                segment, end, day_cap, machine_available, tool_available, lot_completion,
            )
            continue
        material_delay = int(manifest["material_delays"].get(segment.lot_id, 0))
        if material_delay:
            delayed_day = add_workdays(segment.day_idx, material_delay, holidays)
            planned = max(planned, float(delayed_day * day_cap))

        blocked = set(holidays)
        blocked.update(data.machine_blocked_days.get(segment.machine_id, set()))
        blocked.update(data.tool_blocked_days.get(segment.tool_id, set()))
        blocked.update(manifest["machine_down"].get(segment.machine_id, []))
        blocked.update(manifest["tool_down"].get(segment.tool_id, []))
        resource_intervals = _absolute_intervals(
            data.machine_blocked_intervals.get(segment.machine_id, [])
            + data.tool_blocked_intervals.get(segment.tool_id, []),
            config,
            open_horizon=open_horizon,
        )

        start = max(
            planned,
            machine_available.get(segment.machine_id, float("-inf")),
            tool_available.get(segment.tool_id, float("-inf")),
        )
        setup_duration = float(segment.setup_min) * float(manifest["setup_factor"])
        if setup_duration > 0:
            group = config.machine_groups.get(segment.machine_id, "Grandes")
            capacity = max(1, int(config.setup_crews_by_group.get(group, 1)))
            crews = crew_available.setdefault(group, [float("-inf")] * capacity)
            crew_index = min(range(len(crews)), key=crews.__getitem__)
            start = max(start, crews[crew_index])
            setup_end = _advance_work_with_intervals(
                start,
                setup_duration,
                blocked,
                day_cap,
                resource_intervals,
            )
            crews[crew_index] = setup_end
        else:
            setup_end = start

        efficiency = max(0.35, float(manifest["machine_efficiency"][segment.machine_id]))
        operator_factor = float(manifest["operator_factor"])
        production_duration = (
            float(segment.prod_min)
            * operator_factor
            * float(manifest["processing_factor"][segment.machine_id])
            / efficiency
        )
        group = config.machine_groups.get(segment.machine_id, "Grandes")
        end = _reserve_operator_work(
            setup_end,
            production_duration,
            demand=_operator_demand(segment, data),
            group=group,
            blocked_days=blocked,
            blocked_intervals=resource_intervals,
            absences=operator_absences,
            reservations=operator_reservations.setdefault(group, []),
            config=config,
            horizon=open_horizon,
        )
        _record_completion(
            segment, end, day_cap, machine_available, tool_available, lot_completion,
        )

    tardy: list[tuple[str, int]] = []
    for lot in measured_lots:
        planning_checkpoint()
        completion = lot_completion.get(lot.id, data.n_days)
        supplier_delay = int(manifest["subcontract_delays"].get(lot.id, 0))
        output_delays: list[int] = []
        for output in _measured_outputs(lot, horizon):
            ready_day = completion
            if bool(output.get("is_subcontracted")):
                ready_day = add_workdays(
                    ready_day,
                    int(output.get("subcontract_lead_time_days", 0) or 0)
                    + supplier_delay,
                    holidays,
                )
            output_delays.append(
                max(
                    0,
                    ready_day
                    - int(output.get("customer_delivery_day", lot.edd)),
                )
            )
        delay = max(output_delays, default=0)
        demand_factor = float(manifest["demand_factors"].get(lot.sku, 1.0))
        stock_factor = float(manifest["stock_factors"].get(lot.sku, 1.0))
        if math.ceil(lot.qty * demand_factor / max(0.01, stock_factor)) > lot.qty:
            # Demand/stock shocks alter service need, never the duration of
            # production blocks already fixed in the replayed plan.
            delay = max(delay, 1)
        if delay:
            tardy.append((lot.id, delay))

    count = len(tardy)
    return ScenarioOutcome(
        index=index,
        seed=seed,
        otd=round((1 - count / max(len(measured_lots), 1)) * 100.0, 1),
        tardy_count=count,
        total_tardiness=sum(delay for _, delay in tardy),
        max_tardiness=max((delay for _, delay in tardy), default=0),
        affected_lots=[lot_id for lot_id, _ in sorted(tardy, key=lambda item: -item[1])[:10]],
        manifest=manifest,
        tardy_lot_ids=frozenset(lot_id for lot_id, _ in tardy),
    )


def _record_completion(
    segment: Segment,
    end: float,
    day_cap: int,
    machine_available: dict[str, float],
    tool_available: dict[str, float],
    lot_completion: dict[str, int],
) -> None:
    machine_available[segment.machine_id] = end
    tool_available[segment.tool_id] = end
    completion_day = math.floor((end - 0.001) / day_cap)
    previous_completion = lot_completion.get(segment.lot_id)
    lot_completion[segment.lot_id] = (
        completion_day
        if previous_completion is None
        else max(previous_completion, completion_day)
    )


def _measured_outputs(lot: Lot, horizon: RobustnessHorizon | None) -> list[dict]:
    outputs = lot_demand_output_milestones(lot)
    if horizon is None:
        return outputs
    return [
        output
        for output in outputs
        if horizon.covers(int(output.get("customer_delivery_day", lot.edd)))
    ]


def _max_subcontract_lead(lots: list[Lot]) -> int:
    return max(
        (
            int(output.get("subcontract_lead_time_days", 0) or 0)
            for lot in lots
            for output in lot_output_milestones(lot)
        ),
        default=0,
    )


def robustness_horizon(
    lots: list[Lot],
    data: EngineData,
    *,
    anchor_day: int | None = None,
    horizon_workdays: int = ROBUSTNESS_HORIZON_WORKDAYS,
) -> RobustnessHorizon:
    """Return the measured window: ``horizon_workdays`` working days from the anchor.

    The anchor day itself counts as the first working day when it is open.
    Lots enter the window when one of their real-demand deliveries falls in it.
    """

    anchor = max(0, int(anchor_day or 0))
    if data.n_days > 0:
        anchor = min(anchor, data.n_days - 1)
    workdays = max(1, int(horizon_workdays))
    holidays = calendar_holidays(
        data,
        -30,
        max(data.n_days, anchor) + _max_subcontract_lead(lots) * 2 + workdays * 2 + 30,
    )
    end_day = add_workdays(anchor - 1, workdays, holidays)
    window = RobustnessHorizon(
        workdays=workdays,
        start_day=anchor,
        end_day=end_day,
        days=tuple(day for day in range(anchor, end_day + 1) if day not in holidays),
        lot_ids=frozenset(),
    )
    return replace(
        window,
        lot_ids=frozenset(lot.id for lot in lots if _measured_outputs(lot, window)),
    )


def _baseline_tardy_lot_ids(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    horizon: RobustnessHorizon | None = None,
) -> frozenset[str]:
    """Return lots already late in the unperturbed candidate plan."""

    lot_completion: dict[str, int] = {}
    for segment in segments:
        if segment.prod_min <= 0 and segment.setup_min <= 0:
            continue
        lot_completion[segment.lot_id] = max(
            lot_completion.get(segment.lot_id, segment.day_idx),
            segment.day_idx,
        )
    max_lead = _max_subcontract_lead(lots)
    holidays = calendar_holidays(data, -30, data.n_days + max_lead * 2 + 30)
    tardy: set[str] = set()
    for lot in lots:
        if horizon is not None and lot.id not in horizon.lot_ids:
            continue
        completion = lot_completion.get(lot.id, data.n_days)
        for output in _measured_outputs(lot, horizon):
            ready_day = completion
            if bool(output.get("is_subcontracted")):
                ready_day = add_workdays(
                    ready_day,
                    int(output.get("subcontract_lead_time_days", 0) or 0),
                    holidays,
                )
            if ready_day > int(output.get("customer_delivery_day", lot.edd)):
                tardy.add(lot.id)
                break
    return frozenset(tardy)


def run_robustness_battery(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    n_samples: int,
    seed: int = 42,
    profile: str = "custom",
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    anchor_day: int | None = None,
    horizon_workdays: int = ROBUSTNESS_HORIZON_WORKDAYS,
    yield_to_planning: bool = False,
) -> dict:
    """Replay a fixed plan with common, reproducible scenario seeds.

    An outer planning control raises on interruption. The legacy ``cancelled``
    callback still returns partial diagnostics, never an optimizer gate score.
    Only the first ``horizon_workdays`` working days from ``anchor_day`` are
    measured (model v5). With ``yield_to_planning`` a background caller pauses
    between scenarios while any plan is being calculated, so the analysis never
    takes CPU from (and never changes) a time-limited plan search.
    """

    horizon = robustness_horizon(
        lots, data, anchor_day=anchor_day, horizon_workdays=horizon_workdays,
    )
    # Waiting inside our own planning scope would wait for ourselves.
    yield_to_planning = yield_to_planning and current_planning_control() is None
    empty_window = not horizon.lot_ids
    outcomes: list[ScenarioOutcome] = []
    planning_checkpoint()
    for index in range(n_samples):
        planning_checkpoint()
        if yield_to_planning and not wait_while_planning(cancelled):
            break
        if cancelled and cancelled():
            break
        try:
            with (
                planning_scope(cancelled=cancelled, background=True)
                if cancelled is not None
                else nullcontext()
            ):
                outcome = replay_scenario(
                    index,
                    seed + index * 104729,
                    segments,
                    lots,
                    data,
                    config,
                    horizon,
                )
        except PlanningCancelled:
            # Preserve the diagnostic jobs API, but never swallow a parent stop.
            planning_checkpoint()
            if cancelled is not None and cancelled():
                break
            raise
        planning_checkpoint()
        outcomes.append(outcome)
        if progress and (index == 0 or (index + 1) % max(1, n_samples // 100) == 0):
            progress(index + 1, n_samples)

    planning_checkpoint()
    baseline_tardy_lot_ids = _baseline_tardy_lot_ids(segments, lots, data, horizon)
    baseline_tardy_count = len(baseline_tardy_lot_ids)

    def additional_tardy_count(outcome: ScenarioOutcome) -> int:
        if outcome.tardy_lot_ids is not None:
            return len(outcome.tardy_lot_ids - baseline_tardy_lot_ids)
        # Compatibility with callers constructing legacy outcomes in tests.
        return max(0, outcome.tardy_count - baseline_tardy_count)

    additional_tardy = [float(additional_tardy_count(item)) for item in outcomes]
    tardy_counts = [float(item.tardy_count) for item in outcomes]
    total_tardiness = [float(item.total_tardiness) for item in outcomes]
    otd_values = [item.otd for item in outcomes]
    tail_threshold = _percentile(total_tardiness, 95)
    tail = [value for value in total_tardiness if value >= tail_threshold]
    worst = sorted(
        outcomes,
        key=lambda item: (item.total_tardiness, item.max_tardiness, -item.otd),
        reverse=True,
    )[:20]

    return {
        "model_version": ROBUSTNESS_MODEL_VERSION,
        "informational_only": True,
        "horizon_workdays": horizon.workdays,
        "horizon_start_day": horizon.start_day,
        "horizon_end_day": horizon.end_day,
        "horizon_start_date": _workday_label(data, horizon.start_day),
        "horizon_end_date": _workday_label(data, horizon.end_day),
        "horizon_lot_count": len(horizon.lot_ids),
        # Nothing to measure is not the same as perfectly robust.
        "no_deliveries_in_window": empty_window,
        "profile": profile,
        "seed": seed,
        "sample_seeds": [item.seed for item in outcomes],
        "requested_samples": n_samples,
        "completed_samples": len(outcomes),
        "success_definition": "no_additional_tardy_lots",
        "baseline_tardy_count": baseline_tardy_count,
        "success_probability_pct": None if empty_window else round(
            100.0
            * sum(additional_tardy_count(item) == 0 for item in outcomes)
            / max(len(outcomes), 1),
            1,
        ),
        "additional_tardy_mean": round(
            mean(additional_tardy) if additional_tardy else 0.0,
            2,
        ),
        "additional_tardy_p95": round(_percentile(additional_tardy, 95), 1),
        "otd_p50": round(_percentile(otd_values, 50), 1),
        "otd_p90": round(_percentile(otd_values, 10), 1),
        "otd_p95": round(_percentile(otd_values, 5), 1),
        "tardy_mean": round(mean(tardy_counts) if tardy_counts else 0.0, 2),
        "tardy_p90": round(_percentile(tardy_counts, 90), 1),
        "tardy_p95": round(_percentile(tardy_counts, 95), 1),
        "total_tardiness_cvar95": round(mean(tail) if tail else 0.0, 2),
        "worst_scenarios": [
            {
                "index": item.index,
                "seed": item.seed,
                "otd": item.otd,
                "tardy_count": item.tardy_count,
                "total_tardiness": item.total_tardiness,
                "max_tardiness": item.max_tardiness,
                "affected_lots": item.affected_lots,
                "manifest": item.manifest,
            }
            for item in worst
        ],
    }


def _workday_label(data: EngineData, day: int) -> str | None:
    """ISO date of a day index; past the ISOP, day indices are calendar days."""
    workdays = list(getattr(data, "workdays", []) or [])
    if 0 <= day < len(workdays):
        return str(workdays[day])[:10]
    if day < 0 or not workdays:
        return None
    try:
        last = date.fromisoformat(str(workdays[-1])[:10])
    except ValueError:
        return None
    return (last + timedelta(days=day - len(workdays) + 1)).isoformat()
