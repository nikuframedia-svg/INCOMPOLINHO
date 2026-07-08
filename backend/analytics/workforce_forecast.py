"""Workforce Forecast — Spec 12 §5.

Window-based operator demand forecast with trend and peak detection.
Extends compute_operator_alerts() to multi-day view.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from backend.config.types import FactoryConfig
from backend.scheduler.types import Segment
from backend.types import EngineData


@dataclass(slots=True)
class DayForecast:
    day_idx: int
    date: str
    shift: str
    machine_group: str
    required: int
    available: int
    surplus_or_deficit: int  # positive = surplus, negative = deficit


@dataclass(slots=True)
class WorkforceForecast:
    window_days: int
    daily: list[DayForecast]
    peak_day: int
    peak_required: int
    avg_required: float
    deficit_days: int
    trend: str  # "increasing" | "stable" | "decreasing"
    summary: str  # Portuguese


def forecast_workforce(
    segments: list[Segment],
    engine_data: EngineData,
    config: FactoryConfig,
    window: int = 10,
) -> WorkforceForecast:
    """Forecast operator demand for the next N days."""
    machine_group = config.machine_groups
    operator_cap = dict(config.operators)

    # Count segments per (day, group, shift)
    counts: dict[tuple[int, str, str], int] = defaultdict(int)
    for seg in segments:
        if seg.day_idx >= window:
            continue
        if seg.setup_min > 0 and seg.qty == 0:
            continue
        group = machine_group.get(seg.machine_id, "Grandes")
        counts[(seg.day_idx, group, seg.shift)] += 1

    # Build daily forecasts
    daily: list[DayForecast] = []
    day_totals: dict[int, int] = defaultdict(int)

    groups = sorted({g for _, g, _ in counts})
    shifts = sorted({s for _, _, s in counts})

    for day_idx in range(min(window, engine_data.n_days)):
        date = engine_data.workdays[day_idx] if day_idx < len(engine_data.workdays) else ""
        for group in groups or ["Grandes"]:
            for shift in shifts or ["A", "B"]:
                required = counts.get((day_idx, group, shift), 0)
                available = operator_cap.get((group, shift), 6)
                daily.append(
                    DayForecast(
                        day_idx=day_idx,
                        date=date,
                        shift=shift,
                        machine_group=group,
                        required=required,
                        available=available,
                        surplus_or_deficit=available - required,
                    )
                )
                day_totals[day_idx] += required

    # Peak detection
    if day_totals:
        peak_day = max(day_totals, key=day_totals.get)
        peak_required = day_totals[peak_day]
        avg_required = sum(day_totals.values()) / len(day_totals)
    else:
        peak_day = 0
        peak_required = 0
        avg_required = 0.0

    deficit_unique_days = len({f.day_idx for f in daily if f.surplus_or_deficit < 0})

    # Trend detection: avg first half vs second half
    actual_days = min(window, engine_data.n_days)
    half = max(actual_days // 2, 1)
    first_half = [day_totals.get(d, 0) for d in range(half)]
    second_half = [day_totals.get(d, 0) for d in range(half, actual_days)]

    avg_first = sum(first_half) / max(len(first_half), 1)
    avg_second = sum(second_half) / max(len(second_half), 1)

    if avg_first == 0:
        trend = "stable" if avg_second == 0 else "increasing"
    else:
        ratio = avg_second / avg_first
        if ratio > 1.1:
            trend = "increasing"
        elif ratio < 0.9:
            trend = "decreasing"
        else:
            trend = "stable"

    # Summary
    if deficit_unique_days == 0:
        summary = f"Próximos {actual_days} dias: sem défice de operadores."
    else:
        deficit_label = "dias" if deficit_unique_days > 1 else "dia"
        summary = (
            f"Próximos {actual_days} dias: {deficit_unique_days} {deficit_label} "
            f"com défice. Pico dia {peak_day} ({peak_required} operadores). "
            f"Tendência {trend}."
        )

    return WorkforceForecast(
        window_days=actual_days,
        daily=daily,
        peak_day=peak_day,
        peak_required=peak_required,
        avg_required=round(avg_required, 1),
        deficit_days=deficit_unique_days,
        trend=trend,
        summary=summary,
    )
