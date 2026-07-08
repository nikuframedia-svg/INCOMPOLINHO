"""Hierarchical reward function — Spec 08 §3."""

from __future__ import annotations


def compute_reward(score: dict) -> float:
    """Hierarchical reward. Range: ~-50 (infeasible) to 1.0 (perfect).

    1. Hard: OTD-D failures and tardy → strong negative penalty.
    2. Soft (only when OTD=100%): earliness 50% + setups 50%.
    """
    otd_d_failures = score.get("otd_d_failures", 0)
    tardy_count = score.get("tardy_count", 0)

    if otd_d_failures > 0 or tardy_count > 0:
        return -10.0 * otd_d_failures - 5.0 * tardy_count

    # Secondary objectives (normalised 0-1)
    earliness = score.get("earliness_avg_days", 15)
    setups = score.get("setups", 200)

    earliness_score = max(0.0, 1.0 - earliness / 15.0)  # 0d→1.0, 15d→0.0
    setup_score = max(0.0, 1.0 - setups / 200.0)  # 0→1.0, 200→0.0

    return round(0.5 * earliness_score + 0.5 * setup_score, 4)
