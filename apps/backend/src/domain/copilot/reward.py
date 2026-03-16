"""GRPO reward function for copilot training.

Connects to the real CP-SAT solver via POST /v1/solver/schedule
to compute reward scores for model-generated scheduling responses.

Reward components:
  - OTD (40%): On-time delivery percentage
  - Tardiness (30%): Inverse of normalized tardiness
  - Feasibility (20%): Proportion of feasible operations
  - Efficiency (10%): Machine utilization balance

Usage in GRPO training:
  reward = compute_reward(model_output, problem_context)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Reward weights (sum = 1.0)
W_OTD = 0.40
W_TARDINESS = 0.30
W_FEASIBILITY = 0.20
W_EFFICIENCY = 0.10

# Thresholds
OTD_FLOOR = 0.99  # Below this → severe penalty
MAX_TARDINESS_DAYS = 30  # Normalize tardiness against this


@dataclass
class RewardBreakdown:
    """Detailed reward breakdown for analysis."""

    total: float
    otd_score: float
    tardiness_score: float
    feasibility_score: float
    efficiency_score: float
    viable: bool
    otd_pct: float
    details: str


def compute_reward(solver_result: dict[str, Any]) -> RewardBreakdown:
    """Compute reward from a solver result.

    Args:
        solver_result: Response from POST /v1/solver/schedule

    Returns:
        RewardBreakdown with total reward in [0.0, 1.0]
    """
    status = solver_result.get("solver_status", "error")
    kpis = solver_result.get("kpis", {})

    # Not viable → 0
    if status == "error":
        return RewardBreakdown(
            total=0.0,
            otd_score=0.0,
            tardiness_score=0.0,
            feasibility_score=0.0,
            efficiency_score=0.0,
            viable=False,
            otd_pct=0.0,
            details="Solver error",
        )

    # OTD component
    otd_pct = kpis.get("otd_pct", 0) / 100.0
    if otd_pct >= OTD_FLOOR:
        otd_score = 1.0
    elif otd_pct >= 0.90:
        otd_score = 0.5 + 0.5 * (otd_pct - 0.90) / (OTD_FLOOR - 0.90)
    else:
        otd_score = 0.3 * otd_pct / 0.90

    # Tardiness component (lower is better)
    tardiness_days = kpis.get("total_tardiness_days", 0)
    tardiness_norm = min(tardiness_days / MAX_TARDINESS_DAYS, 1.0)
    tardiness_score = 1.0 - tardiness_norm

    # Feasibility component
    total_ops = kpis.get("total_jobs", 1)
    infeasible = kpis.get("infeasible_count", 0)
    feasibility_score = max(0.0, 1.0 - infeasible / max(total_ops, 1))

    # Efficiency component (machine utilization balance)
    jobs = solver_result.get("jobs", [])
    if jobs:
        machine_loads: dict[str, float] = {}
        for j in jobs:
            m = j.get("machine", "?")
            machine_loads[m] = machine_loads.get(m, 0) + j.get("production_minutes", 0)
        loads = list(machine_loads.values())
        if loads:
            avg = sum(loads) / len(loads)
            if avg > 0:
                variance = sum((l - avg) ** 2 for l in loads) / len(loads)
                cv = (variance**0.5) / avg  # coefficient of variation
                efficiency_score = max(0.0, 1.0 - cv)  # lower CV = better balance
            else:
                efficiency_score = 0.5
        else:
            efficiency_score = 0.5
    else:
        efficiency_score = 0.0

    # Weighted total
    total = (
        W_OTD * otd_score
        + W_TARDINESS * tardiness_score
        + W_FEASIBILITY * feasibility_score
        + W_EFFICIENCY * efficiency_score
    )

    viable = status in ("optimal", "feasible") and otd_pct >= OTD_FLOOR

    details = (
        f"OTD={otd_pct:.1%}({otd_score:.2f}) "
        f"Tard={tardiness_days}d({tardiness_score:.2f}) "
        f"Feas={feasibility_score:.2f} "
        f"Eff={efficiency_score:.2f}"
    )

    return RewardBreakdown(
        total=round(total, 4),
        otd_score=round(otd_score, 4),
        tardiness_score=round(tardiness_score, 4),
        feasibility_score=round(feasibility_score, 4),
        efficiency_score=round(efficiency_score, 4),
        viable=viable,
        otd_pct=otd_pct * 100,
        details=details,
    )


def reward_for_grpo(solver_results: list[dict[str, Any]]) -> list[float]:
    """Compute rewards for a batch of GRPO candidates.

    In GRPO, the model generates N candidates per problem.
    This returns the reward for each candidate.

    Args:
        solver_results: List of solver results (one per candidate)

    Returns:
        List of reward floats in [0.0, 1.0]
    """
    return [compute_reward(r).total for r in solver_results]
