"""Compatibility facade for the retired configurable earliness window.

The five-working-day JIT rule is now an immutable industrial constraint.
Legacy imports remain available, but every dispatch path delegates to the
same backward scheduler and none can relax or remove a lot floor.
"""

from __future__ import annotations

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.jit import _backward_stack_gates, jit_dispatch
from backend.scheduler.jit_policy import (
    clamp_run_gates_to_window,
    earliest_allowed_start,
    lot_floor_minutes,
)
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.types import EngineData


def compute_lot_floor(lot: Lot, holiday_set: set[int], release_days: int = 5) -> int:
    """Earliest productive day; ``release_days`` is kept for API compatibility."""

    return earliest_allowed_start(lot, holiday_set)


def compute_window_gates(
    machine_runs: dict[str, list[ToolRun]],
    holiday_set: set[int],
    config: FactoryConfig,
    n_days: int | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """Return minute-precise backward gates clamped to the fixed JIT floor."""

    day_cap = config.day_capacity_min
    floors = lot_floor_minutes(machine_runs, holiday_set, day_cap)
    horizon = n_days if n_days is not None else max(
        (run.edd for runs in machine_runs.values() for run in runs),
        default=0,
    ) + 1
    gates = _backward_stack_gates(
        machine_runs,
        holiday_set,
        horizon,
        config=config,
    )
    return clamp_run_gates_to_window(machine_runs, gates, floors), floors


def window_dispatch(
    runs: list[ToolRun],
    engine_data: EngineData,
    baseline_segments: list[Segment],
    baseline_lots: list[Lot],
    baseline_score: dict,
    audit_logger: object | None = None,
    config: FactoryConfig | None = None,
) -> tuple[
    list[Segment],
    list[Lot],
    list[str],
    dict[str, list[ToolRun]] | None,
    dict[str, float] | None,
    dict | None,
]:
    """Legacy name for the fixed backward JIT dispatcher."""

    return jit_dispatch(
        runs,
        engine_data,
        baseline_segments,
        baseline_lots,
        baseline_score,
        audit_logger=audit_logger,
        config=config or FactoryConfig(),
    )


def window_policy_active(config: FactoryConfig | None) -> bool:
    """The former selectable materials-window policy is permanently retired."""

    return False


def effective_earliness_target(config: FactoryConfig | None) -> float:
    """Return the JIT target without legacy window recalibration."""

    return config.jit_earliness_target if config is not None else 6.0


DAY_CAP_DEFAULT = DAY_CAP
