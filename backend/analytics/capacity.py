"""Daily and ISO-week production capacity by machine."""

from __future__ import annotations

from collections import defaultdict
from datetime import date as dt_date

from backend.calendar import (
    available_machine_capacity,
    available_operator_capacity,
    is_factory_workday,
)
from backend.config.types import FactoryConfig
from backend.scheduler.operators import operator_peaks, segment_operator_demand
from backend.scheduler.types import Segment
from backend.types import EngineData


def _machine_ids(
    data: EngineData, config: FactoryConfig, loaded: set[str]
) -> list[str]:
    # Use the effective machine set, including configured additions.
    return sorted(
        machine.id
        for machine in data.machines
        if config.machines.get(machine.id) is None
        or config.machines[machine.id].active
        or machine.id in loaded
    )


def _utilization(load: float, capacity: float) -> float | None:
    if capacity > 0:
        return round(load / capacity * 100, 1)
    return None if load > 0 else 0.0


def _day_capacity(machine_id: str, day_idx: int, data: EngineData, config: FactoryConfig) -> int:
    return available_machine_capacity(machine_id, day_idx, data, config)


def _operator_capacity_rows(
    segments: list[Segment],
    data: EngineData,
    config: FactoryConfig,
    granularity: str,
) -> list[dict]:
    groups = sorted(set(config.machine_groups.values()))
    machine_groups = config.machine_groups
    peak_keys = {
        (day_idx, group, shift.id)
        for day_idx in range(data.n_days)
        for group in groups
        for shift in config.shifts
    }
    peaks = operator_peaks(
        segments,
        data,
        config,
        include_keys=peak_keys,
    )
    daily: list[dict] = []
    for day_idx in range(data.n_days):
        date = str(data.workdays[day_idx]) if day_idx < len(data.workdays) else ""
        for group in groups:
            for shift in config.shifts:
                capacity = available_operator_capacity(group, shift, day_idx, data, config)
                load = sum(
                    max(0.0, float(segment.prod_min))
                    * segment_operator_demand(segment, data)
                    for segment in segments
                    if segment.day_idx == day_idx
                    and machine_groups.get(segment.machine_id, "Grandes") == group
                    and segment.shift == shift.id
                )
                peak = peaks[(day_idx, group, shift.id)]
                daily.append(
                    {
                        "bucket": str(day_idx),
                        "date_from": date,
                        "date_to": date,
                        "group": group,
                        "shift": shift.id,
                        "capacity_operator_min": round(capacity, 1),
                        "load_operator_min": round(load, 1),
                        "util_pct": _utilization(load, capacity),
                        "peak_required": peak.required,
                        "min_available": peak.available,
                        "peak_deficit": peak.deficit,
                        "overload": peak.deficit > 0,
                        "workday_count": 1 if is_factory_workday(day_idx, data, config) else 0,
                    }
                )
    if granularity == "day":
        return daily
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in daily:
        try:
            parsed = dt_date.fromisoformat(row["date_from"])
            year, week, _weekday = parsed.isocalendar()
            bucket = f"{year}-W{week:02d}"
        except ValueError:
            bucket = row["bucket"]
        grouped[(row["group"], row["shift"], bucket)].append(row)
    result = []
    for (group, shift, bucket), rows in sorted(grouped.items()):
        capacity = sum(row["capacity_operator_min"] for row in rows)
        load = sum(row["load_operator_min"] for row in rows)
        worst = max(
            rows,
            key=lambda row: (
                row["peak_deficit"],
                row["peak_required"],
                -row["min_available"],
            ),
        )
        result.append(
            {
                "bucket": bucket,
                "date_from": rows[0]["date_from"],
                "date_to": rows[-1]["date_to"],
                "group": group,
                "shift": shift,
                "capacity_operator_min": round(capacity, 1),
                "load_operator_min": round(load, 1),
                "util_pct": _utilization(load, capacity),
                "peak_required": worst["peak_required"],
                "min_available": worst["min_available"],
                "peak_deficit": worst["peak_deficit"],
                "overload": any(row["overload"] for row in rows),
                "workday_count": sum(row["workday_count"] for row in rows),
            }
        )
    return result


def _item(
    *,
    machine_id: str,
    bucket: str,
    label: str,
    date_from: str,
    date_to: str,
    day_indices: list[int],
    cap_min: float,
    setup_min: float,
    prod_min: float,
    n_setups: int,
    workday_count: int,
) -> dict:
    load_min = setup_min + prod_min
    util_pct = _utilization(load_min, cap_min)
    return {
        "machine_id": machine_id,
        "bucket": bucket,
        "label": label,
        "date_from": date_from,
        "date_to": date_to,
        "day_indices": day_indices,
        "cap_min": round(cap_min, 1),
        "setup_min": round(setup_min, 1),
        "prod_min": round(prod_min, 1),
        "load_min": round(load_min, 1),
        "util_pct": util_pct,
        "overload": load_min > cap_min + 0.01,
        "n_setups": n_setups,
        "workday_count": workday_count,
    }


def compute_capacity(
    segments: list[Segment],
    data: EngineData,
    config: FactoryConfig,
    granularity: str = "day",
) -> dict:
    """Return capacity rows for every machine and day/week bucket."""
    if granularity not in {"day", "week"}:
        raise ValueError("granularity deve ser 'day' ou 'week'.")

    usage: dict[tuple[str, int], dict[str, float | int]] = defaultdict(
        lambda: {"setup_min": 0.0, "prod_min": 0.0, "n_setups": 0}
    )
    setup_runs: dict[tuple[str, int], set[str]] = defaultdict(set)
    for segment in segments:
        if not 0 <= segment.day_idx < data.n_days:
            continue
        entry = usage[(segment.machine_id, segment.day_idx)]
        entry["setup_min"] += segment.setup_min
        entry["prod_min"] += segment.prod_min
        if segment.setup_min > 0:
            setup_runs[(segment.machine_id, segment.day_idx)].add(segment.run_id)
            entry["n_setups"] = len(
                setup_runs[(segment.machine_id, segment.day_idx)]
            )

    loaded = {
        machine_id
        for (machine_id, _day_idx), used in usage.items()
        if used["setup_min"] + used["prod_min"] > 0
    }
    day_rows = []
    for machine_id in _machine_ids(data, config, loaded):
        for day_idx in range(data.n_days):
            date = str(data.workdays[day_idx]) if day_idx < len(data.workdays) else ""
            used = usage[(machine_id, day_idx)]
            day_rows.append(
                _item(
                    machine_id=machine_id,
                    bucket=str(day_idx),
                    label=date or f"Dia {day_idx}",
                    date_from=date,
                    date_to=date,
                    day_indices=[day_idx],
                    cap_min=_day_capacity(machine_id, day_idx, data, config),
                    setup_min=float(used["setup_min"]),
                    prod_min=float(used["prod_min"]),
                    n_setups=int(used["n_setups"]),
                    workday_count=1 if is_factory_workday(day_idx, data, config) else 0,
                )
            )

    if granularity == "day":
        return {
            "granularity": "day",
            "items": day_rows,
            "operators": _operator_capacity_rows(segments, data, config, "day"),
        }

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in day_rows:
        try:
            parsed = dt_date.fromisoformat(row["date_from"])
            iso_year, iso_week, _iso_day = parsed.isocalendar()
            week = f"{iso_year}-W{iso_week:02d}"
        except ValueError:
            week = f"dias-{row['bucket']}"
        grouped[(row["machine_id"], week)].append(row)

    week_rows = []
    for (machine_id, week), rows in sorted(grouped.items()):
        week_rows.append(
            _item(
                machine_id=machine_id,
                bucket=week,
                label=week,
                date_from=rows[0]["date_from"],
                date_to=rows[-1]["date_to"],
                day_indices=[day for row in rows for day in row["day_indices"]],
                cap_min=sum(row["cap_min"] for row in rows),
                setup_min=sum(row["setup_min"] for row in rows),
                prod_min=sum(row["prod_min"] for row in rows),
                n_setups=sum(row["n_setups"] for row in rows),
                workday_count=sum(row["workday_count"] for row in rows),
            )
        )
    return {
        "granularity": "week",
        "items": week_rows,
        "operators": _operator_capacity_rows(segments, data, config, "week"),
    }
