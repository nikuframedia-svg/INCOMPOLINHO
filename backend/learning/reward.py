"""Hierarchical reward function — Spec 08 §3."""

from __future__ import annotations


def compute_reward(score: dict) -> float:
    """Hierarchical reward. Range: ~-50 (infeasible) to 1.0 (perfect).

    1. Hard: OTD-D failures and tardy → strong negative penalty.
    2. Soft (only when OTD=100%): earliness 50% + setups 50%.
    Robustness is informational only and never enters the reward.
    """
    otd_d_failures = score.get("otd_d_failures", 0)
    tardy_count = score.get("tardy_count", 0)
    hard_violations = score.get("hard_violations", 0)
    early_window_violations = score.get("early_window_violations", 0)
    dispatch_misses = score.get("subcontract_dispatch_misses", 0)
    dispatch_late = score.get("subcontract_dispatch_late_workdays", 0)

    if hard_violations > 0 or early_window_violations > 0:
        return -100.0 - 20.0 * hard_violations - 20.0 * early_window_violations
    if otd_d_failures > 0 or tardy_count > 0 or dispatch_misses > 0:
        return (
            -10.0 * otd_d_failures
            - 5.0 * tardy_count
            - 7.0 * dispatch_misses
            - 1.0 * dispatch_late
        )

    # Secondary objectives (normalised 0-1)
    earliness = score.get("earliness_avg_days", 15)
    setups = score.get("setups", 200)

    earliness_score = max(0.0, 1.0 - earliness / 15.0)  # 0d→1.0, 15d→0.0
    setup_score = max(0.0, 1.0 - setups / 200.0)  # 0→1.0, 200→0.0

    latest_gap_hours = float(score.get("latest_start_gap_avg_min", 0.0) or 0.0) / 60.0
    latest_start_score = max(0.0, 1.0 - latest_gap_hours / 24.0)

    return round(0.5 * latest_start_score + 0.25 * earliness_score + 0.25 * setup_score, 4)
