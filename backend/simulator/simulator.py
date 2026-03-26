"""Simulator — Spec 04: What-If.

simulate() deepcopies EngineData, applies mutations, re-runs schedule_all(),
and compares BEFORE vs AFTER KPIs.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass

from backend.cpo import optimize
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData

from .mutations import apply_mutation, mutation_summary


@dataclass(slots=True)
class Mutation:
    type: str
    params: dict


@dataclass(slots=True)
class DeltaReport:
    otd_before: float
    otd_after: float
    otd_d_before: float
    otd_d_after: float
    setups_before: int
    setups_after: int
    earliness_before: float
    earliness_after: float
    tardy_before: int
    tardy_after: int


@dataclass(slots=True)
class SimulateResponse:
    segments: list[Segment]
    lots: list[Lot]
    score: dict
    delta: DeltaReport
    time_ms: float
    summary: list[str]


def simulate(
    engine_data: EngineData,
    baseline_score: dict,
    mutations: list[Mutation],
    config=None,
) -> SimulateResponse:
    """Run what-if simulation.

    1. deepcopy(engine_data)
    2. Apply each mutation
    3. schedule_all(mutated)
    4. Build DeltaReport comparing baseline_score vs new score
    5. Generate Portuguese summary
    """
    t0 = time.perf_counter()

    # 1. Deep copy data AND config (mutations may modify config.shifts)
    mutated = copy.deepcopy(engine_data)
    sim_config = copy.deepcopy(config) if config else None

    # 2. Apply mutations (pass config so third_shift/overtime can modify shifts)
    summaries: list[str] = []
    for mut in mutations:
        msg = apply_mutation(mutated, mut.type, mut.params, config=sim_config)
        summaries.append(msg)

    # 3. Re-schedule with (possibly modified) config
    try:
        result = optimize(mutated, mode="quick", config=sim_config)
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        summaries.append(f"ERRO no scheduler: {exc}")
        empty_delta = DeltaReport(
            otd_before=baseline_score.get("otd", 0.0), otd_after=0.0,
            otd_d_before=baseline_score.get("otd_d", 0.0), otd_d_after=0.0,
            setups_before=baseline_score.get("setups", 0), setups_after=0,
            earliness_before=baseline_score.get("earliness_avg_days", 0.0), earliness_after=0.0,
            tardy_before=baseline_score.get("tardy_count", 0), tardy_after=0,
        )
        return SimulateResponse(
            segments=[], lots=[], score={},
            delta=empty_delta, time_ms=round(elapsed, 1), summary=summaries,
        )

    # 4. Delta report
    delta = DeltaReport(
        otd_before=baseline_score.get("otd", 0.0),
        otd_after=result.score.get("otd", 0.0),
        otd_d_before=baseline_score.get("otd_d", 0.0),
        otd_d_after=result.score.get("otd_d", 0.0),
        setups_before=baseline_score.get("setups", 0),
        setups_after=result.score.get("setups", 0),
        earliness_before=baseline_score.get("earliness_avg_days", 0.0),
        earliness_after=result.score.get("earliness_avg_days", 0.0),
        tardy_before=baseline_score.get("tardy_count", 0),
        tardy_after=result.score.get("tardy_count", 0),
    )

    # 5. Summary
    summaries.append(_delta_summary(delta))

    elapsed = (time.perf_counter() - t0) * 1000

    return SimulateResponse(
        segments=result.segments,
        lots=result.lots,
        score=result.score,
        delta=delta,
        time_ms=round(elapsed, 1),
        summary=summaries,
    )


def _delta_summary(delta: DeltaReport) -> str:
    """Generate Portuguese summary of KPI changes."""
    parts: list[str] = []

    otd_diff = delta.otd_after - delta.otd_before
    if abs(otd_diff) > 0.05:
        direction = "subiu" if otd_diff > 0 else "desceu"
        parts.append(f"OTD {direction} {abs(otd_diff):.1f}% ({delta.otd_before:.1f}% → {delta.otd_after:.1f}%)")

    otd_d_diff = delta.otd_d_after - delta.otd_d_before
    if abs(otd_d_diff) > 0.05:
        direction = "subiu" if otd_d_diff > 0 else "desceu"
        parts.append(f"OTD-D {direction} {abs(otd_d_diff):.1f}%")

    setup_diff = delta.setups_after - delta.setups_before
    if setup_diff != 0:
        direction = "+" if setup_diff > 0 else ""
        parts.append(f"Setups: {direction}{setup_diff} ({delta.setups_before} → {delta.setups_after})")

    tardy_diff = delta.tardy_after - delta.tardy_before
    if tardy_diff != 0:
        direction = "+" if tardy_diff > 0 else ""
        parts.append(f"Atrasos: {direction}{tardy_diff} ({delta.tardy_before} → {delta.tardy_after})")

    if not parts:
        return "Sem alterações significativas nos KPIs."

    return "Resumo: " + "; ".join(parts) + "."
