# Monte Carlo Robustness Simulation (S-05)
# Runs N scenarios with perturbed durations/setups/breakdowns.
# Uses CP-SAT solver per scenario with short time limit (1s each).

from __future__ import annotations

import random
import time

from .cpsat_solver import CpsatSolver
from .perturbation import perturb_request
from .schemas import SolverRequest


def monte_carlo_otd(
    request: SolverRequest,
    n_scenarios: int = 200,
    seed: int = 42,
    duration_cv: float = 0.10,
    setup_cv: float = 0.20,
    breakdown_rate: float = 0.005,
) -> dict:
    """Run Monte Carlo simulation to estimate schedule robustness.

    Uses heuristic solver per scenario (not CP-SAT) for speed.

    Returns:
        {
            "p_otd_100": float,          # P(OTD=100%) across scenarios
            "p_otd_95": float,           # P(OTD>=95%)
            "mean_tardiness": float,     # Mean weighted tardiness
            "vulnerable_jobs": list,     # Jobs that are late in >20% of scenarios
            "suggested_buffers": list,   # Buffer suggestions for vulnerable ops
            "n_scenarios": int,
            "seed": int,
            "elapsed_s": float,
        }
    """
    start_time = time.monotonic()
    rng = random.Random(seed)
    solver = CpsatSolver()

    # Build job metadata
    job_due = {j.id: j.due_date_min for j in request.jobs}

    # Track per-scenario results
    otd_100_count = 0
    otd_95_count = 0
    total_tardiness_sum = 0.0
    job_late_count: dict[str, int] = {j.id: 0 for j in request.jobs}
    job_tardiness_sum: dict[str, int] = {j.id: 0 for j in request.jobs}

    for _ in range(n_scenarios):
        perturbed = perturb_request(
            request,
            rng,
            duration_cv=duration_cv,
            setup_cv=setup_cv,
            breakdown_rate=breakdown_rate,
        )

        # Use short time limit for Monte Carlo scenarios
        perturbed.config.time_limit_s = 1
        result = solver.solve(perturbed)

        # Calculate OTD for this scenario
        n_jobs = len(request.jobs)
        n_late = 0
        for sop in result.schedule:
            if sop.is_tardy and sop.tardiness_min > 0:
                n_late += 1
                job_late_count[sop.job_id] = job_late_count.get(sop.job_id, 0) + 1
                job_tardiness_sum[sop.job_id] = (
                    job_tardiness_sum.get(sop.job_id, 0) + sop.tardiness_min
                )

        otd_pct = (n_jobs - n_late) / n_jobs * 100 if n_jobs > 0 else 100
        if otd_pct >= 100:
            otd_100_count += 1
        if otd_pct >= 95:
            otd_95_count += 1
        total_tardiness_sum += result.weighted_tardiness

    # Identify vulnerable jobs (late in >20% of scenarios)
    threshold = n_scenarios * 0.20
    vulnerable_jobs = []
    for job_id, count in job_late_count.items():
        if count > threshold:
            avg_tardiness = job_tardiness_sum[job_id] / count if count > 0 else 0
            vulnerable_jobs.append(
                {
                    "job_id": job_id,
                    "late_pct": round(count / n_scenarios * 100, 1),
                    "avg_tardiness_min": round(avg_tardiness, 1),
                }
            )
    vulnerable_jobs.sort(key=lambda x: -x["late_pct"])

    # Suggest buffers for vulnerable ops
    suggested_buffers = []
    for vj in vulnerable_jobs:
        job_id = vj["job_id"]
        avg_tard = vj["avg_tardiness_min"]
        # Suggest buffer = average tardiness + 20% margin
        buffer_min = int(avg_tard * 1.2)
        if buffer_min > 0:
            suggested_buffers.append(
                {
                    "job_id": job_id,
                    "buffer_min": buffer_min,
                    "reason": f"Late in {vj['late_pct']}% of scenarios, avg delay {avg_tard}min",
                }
            )

    elapsed = time.monotonic() - start_time

    return {
        "p_otd_100": round(otd_100_count / n_scenarios * 100, 1),
        "p_otd_95": round(otd_95_count / n_scenarios * 100, 1),
        "mean_tardiness": round(total_tardiness_sum / n_scenarios, 2),
        "vulnerable_jobs": vulnerable_jobs,
        "suggested_buffers": suggested_buffers,
        "n_scenarios": n_scenarios,
        "seed": seed,
        "elapsed_s": round(elapsed, 3),
    }
