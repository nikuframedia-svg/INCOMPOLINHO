"""Workforce Forecast — Spec 12 §5.

Window-based operator demand forecast with trend and peak detection.
Extends compute_operator_alerts() to multi-day view.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.config.types import FactoryConfig
from backend.scheduler.operators import operator_peaks
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
    *,
    start_day: int = 0,
) -> WorkforceForecast:
    """Forecast operator demand for the next N days."""
    start_day = max(0, start_day)
    actual_days = min(max(0, window), max(0, engine_data.n_days - start_day))
    days = range(start_day, start_day + actual_days)
    groups = sorted(
        set(config.machine_groups.values())
        | {group for group, _shift in config.operators}
        | {
            str(block.get("group", ""))
            for block in engine_data.operator_blocked_intervals
            if block.get("group")
        }
    ) or ["Grandes"]
    shifts = [shift.id for shift in config.shifts]
    include_keys = {
        (day_idx, group, shift)
        for day_idx in days
        for group in groups
        for shift in shifts
    }
    peaks = operator_peaks(
        [segment for segment in segments if segment.day_idx in days],
        engine_data,
        config,
        include_keys=include_keys,
    )

    daily: list[DayForecast] = []
    day_totals = {day_idx: 0 for day_idx in days}

    for day_idx in days:
        date = engine_data.workdays[day_idx] if day_idx < len(engine_data.workdays) else ""
        for group in groups:
            for shift in shifts:
                peak = peaks[(day_idx, group, shift)]
                daily.append(
                    DayForecast(
                        day_idx=day_idx,
                        date=date,
                        shift=shift,
                        machine_group=group,
                        required=peak.required,
                        available=peak.available,
                        surplus_or_deficit=peak.available - peak.required,
                    )
                )
                day_totals[day_idx] += peak.required

    # Peak detection
    if day_totals:
        peak_day = max(day_totals, key=day_totals.get)
        peak_required = day_totals[peak_day]
        avg_required = sum(day_totals.values()) / len(day_totals)
    else:
        peak_day = start_day
        peak_required = 0
        avg_required = 0.0

    deficit_unique_days = len({f.day_idx for f in daily if f.surplus_or_deficit < 0})

    # Trend detection: avg first half vs second half
    half = max(actual_days // 2, 1)
    first_half = [
        day_totals.get(d, 0) for d in range(start_day, start_day + min(half, actual_days))
    ]
    second_half = [day_totals.get(d, 0) for d in range(start_day + half, start_day + actual_days)]

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
