"""Tier 3 — Monte Carlo Risk: Spec 06 §4.

Latin Hypercube Sampling with perturbation of OEE and setup times.
Requires scipy and numpy (optional dependencies).
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable
from typing import Any

from backend.types import EngineData

# Distribution parameters for Incompol (metal stamping)
OEE_ALPHA = 10.6  # Beta(10.6, 5.5) → mean ≈ 0.66
OEE_BETA = 5.5
SETUP_CV = 0.20  # Lognormal CV 20%


def monte_carlo_risk(
    engine_data: EngineData,
    schedule_fn: Callable[[EngineData], Any],
    n_samples: int = 500,
    seed: int = 42,
) -> dict:
    """Run Monte Carlo risk simulation via Latin Hypercube Sampling.

    Each sample perturbs OEE (Beta distribution) and setup times (Lognormal).
    500 samples ≈ 2000-5000 equivalent random samples.

    Args:
        engine_data: Base schedule input.
        schedule_fn: Scheduling function (schedule_all).
        n_samples: Number of LHS samples.
        seed: Random seed for reproducibility.

    Returns:
        Dict with percentile statistics for OTD and tardiness.

    Raises:
        ImportError: If scipy/numpy are not installed.
    """
    try:
        import numpy as np
        from scipy.stats import beta as beta_dist
        from scipy.stats import lognorm
        from scipy.stats.qmc import LatinHypercube
    except ImportError as exc:
        raise ImportError("Monte Carlo requer scipy e numpy: pip install scipy numpy") from exc

    tools = sorted({op.t for op in engine_data.ops})
    n_dims = 1 + len(tools)  # OEE global + setup per tool

    sampler = LatinHypercube(d=n_dims, seed=seed)
    samples = sampler.random(n=n_samples)

    otd_results: list[float] = []
    tardy_results: list[int] = []

    sigma_log = math.sqrt(math.log(1 + SETUP_CV**2))

    for i in range(n_samples):
        mutated = copy.deepcopy(engine_data)

        # Perturb OEE (column 0)
        oee_sample = float(beta_dist.ppf(samples[i, 0], OEE_ALPHA, OEE_BETA))
        for op in mutated.ops:
            op.oee = oee_sample

        # Perturb setup times (columns 1..n_tools)
        for j, tool in enumerate(tools):
            if j + 1 < n_dims:
                factor = float(lognorm.ppf(samples[i, j + 1], s=sigma_log))
                for op in mutated.ops:
                    if op.t == tool:
                        op.sH *= factor

        try:
            result = schedule_fn(mutated)
            otd_results.append(result.score.get("otd", 100.0))
            tardy_results.append(result.score.get("tardy_count", 0))
        except Exception:
            otd_results.append(0.0)
            tardy_results.append(999)

    otd_arr = np.array(otd_results)
    tardy_arr = np.array(tardy_results)

    return {
        "otd_p50": round(float(np.percentile(otd_arr, 50)), 1),
        "otd_p80": round(float(np.percentile(otd_arr, 20)), 1),
        "otd_p95": round(float(np.percentile(otd_arr, 5)), 1),
        "tardy_mean": round(float(np.mean(tardy_arr)), 1),
        "tardy_p95": round(float(np.percentile(tardy_arr, 95)), 1),
        "otd_100_pct": round(float(np.mean(otd_arr >= 100) * 100), 1),
        "n_samples": n_samples,
    }
