"""Breakdown Simulator — machine failure impact analysis.

Wraps simulate() with machine_down mutation and enriched output.
Answers: "If machine X goes down for N days starting day D, what happens?"
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.config.types import FactoryConfig
from backend.types import EngineData

from .simulator import DeltaReport, Mutation, SimulateResponse, simulate


@dataclass(slots=True)
class BreakdownReport:
    """Enriched breakdown analysis result."""

    machine_id: str
    down_start: int
    down_end: int
    delta: DeltaReport
    score: dict
    impact_level: str          # "critical" | "warning" | "ok"
    summary_pt: str            # Portuguese summary
    affected_ops: list[str]    # ops that were on this machine
    time_ms: float


def simulate_breakdown(
    engine_data: EngineData,
    baseline_score: dict,
    machine_id: str,
    start_day: int,
    end_day: int,
    config: FactoryConfig | None = None,
) -> BreakdownReport:
    """Simulate a machine breakdown and return enriched report.

    Args:
        engine_data: Current EngineData.
        baseline_score: Score from current schedule.
        machine_id: Machine that goes down (e.g. "PRM019").
        start_day: First day of breakdown (0-indexed).
        end_day: Last day of breakdown (inclusive).
        config: Factory config.

    Returns:
        BreakdownReport with impact assessment.
    """
    # Find ops assigned to this machine
    affected_ops = [
        op.id for op in engine_data.ops if op.m == machine_id
    ]

    # Run simulation with machine_down mutation
    mutations = [Mutation(
        type="machine_down",
        params={"machine_id": machine_id, "start": start_day, "end": end_day},
    )]

    sim_result: SimulateResponse = simulate(
        engine_data, baseline_score, mutations, config=config,
    )

    # Assess impact level
    delta = sim_result.delta
    if delta.tardy_after > delta.tardy_before:
        impact = "critical"
    elif delta.otd_after < delta.otd_before - 0.5:
        impact = "critical"
    elif delta.setups_after > delta.setups_before + 5:
        impact = "warning"
    elif delta.earliness_after > delta.earliness_before + 2.0:
        impact = "warning"
    else:
        impact = "ok"

    # Portuguese summary
    n_days = end_day - start_day + 1
    parts = [f"Máquina {machine_id} parada {n_days} dia(s) (dia {start_day}-{end_day})."]
    parts.append(f"{len(affected_ops)} operação(ões) afectada(s).")

    if delta.tardy_after > delta.tardy_before:
        parts.append(
            f"ALERTA: atrasos aumentam de {delta.tardy_before} para {delta.tardy_after}."
        )
    if abs(delta.otd_after - delta.otd_before) > 0.05:
        parts.append(
            f"OTD: {delta.otd_before:.1f}% → {delta.otd_after:.1f}%."
        )
    if delta.setups_after != delta.setups_before:
        diff = delta.setups_after - delta.setups_before
        parts.append(f"Setups: {'+' if diff > 0 else ''}{diff}.")

    if impact == "ok":
        parts.append("Impacto controlável — schedule absorve a paragem.")
    elif impact == "warning":
        parts.append("Impacto moderado — monitorizar KPIs.")
    else:
        parts.append("Impacto CRÍTICO — acção imediata recomendada.")

    return BreakdownReport(
        machine_id=machine_id,
        down_start=start_day,
        down_end=end_day,
        delta=delta,
        score=sim_result.score,
        impact_level=impact,
        summary_pt=" ".join(parts),
        affected_ops=affected_ops,
        time_ms=sim_result.time_ms,
    )
