"""Bayesian Optimization — Spec 08 §4.

Inner loop: Optuna TPESampler to tune scheduler params for a given ISOP.
"""

from __future__ import annotations

import copy
import logging
import time

import optuna

from .reward import compute_reward
from .types import SchedulerParams, StudyResult

optuna.logging.set_verbosity(optuna.logging.WARNING)
logger = logging.getLogger(__name__)


class OptunaTuner:
    """Bayesian optimization of scheduler parameters via Optuna."""

    def __init__(
        self,
        engine_data,
        n_trials: int = 30,
        timeout_s: float = 15.0,
        config=None,
    ) -> None:
        self._data = engine_data
        self._n_trials = n_trials
        self._timeout_s = timeout_s
        self._config = config

    def optimize(
        self, warm_start: SchedulerParams | None = None,
    ) -> StudyResult:
        """Run Bayesian optimization. Returns StudyResult."""
        from backend.cpo import optimize

        t0 = time.perf_counter()

        # Baseline (default params)
        baseline_result = optimize(copy.deepcopy(self._data), mode="quick", config=self._config)
        baseline_reward = compute_reward(baseline_result.score)

        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
        )

        if warm_start:
            study.enqueue_trial(warm_start.to_dict())

        def objective(trial: optuna.Trial) -> float:
            params = SchedulerParams(
                max_edd_gap=trial.suggest_int("max_edd_gap", 5, 20),
                max_run_days=trial.suggest_int("max_run_days", 2, 10),
                edd_swap_tolerance=trial.suggest_int("edd_swap_tolerance", 2, 15),
                edd_assign_threshold=trial.suggest_int("edd_assign_threshold", 2, 10),
                campaign_window=trial.suggest_int("campaign_window", 10, 25),
                backward_buffer_pct=trial.suggest_float("backward_buffer_pct", 0.01, 0.15),
                jit_threshold=trial.suggest_float("jit_threshold", 85.0, 100.0),
                interleave_enabled=trial.suggest_categorical(
                    "interleave_enabled", [True, False],
                ),
            )
            result = optimize(copy.deepcopy(self._data), mode="quick", config=self._config)
            return compute_reward(result.score)

        study.optimize(
            objective,
            n_trials=self._n_trials,
            timeout=self._timeout_s,
        )

        # Best result
        best_trial = study.best_trial
        best_params = SchedulerParams.from_dict(best_trial.params)
        best_result = optimize(copy.deepcopy(self._data), mode="normal", config=self._config)
        best_reward = compute_reward(best_result.score)

        elapsed_ms = (time.perf_counter() - t0) * 1000

        # Confidence
        n = len(study.trials)
        delta = best_reward - baseline_reward
        if n < 10:
            confidence = "cold_start"
        elif delta < 0.01:
            confidence = "low"
        elif delta < 0.05:
            confidence = "medium"
        else:
            confidence = "high"

        improvement = {
            "reward": round(delta, 4),
            "earliness_delta": round(
                best_result.score.get("earliness_avg_days", 0)
                - baseline_result.score.get("earliness_avg_days", 0),
                1,
            ),
            "setups_delta": (
                best_result.score.get("setups", 0)
                - baseline_result.score.get("setups", 0)
            ),
        }

        logger.info(
            "BO: %d trials in %.1fs, reward %.4f → %.4f (%s)",
            n, elapsed_ms / 1000, baseline_reward, best_reward, confidence,
        )

        return StudyResult(
            best_params=best_params,
            best_reward=best_reward,
            best_score=best_result.score,
            baseline_score=baseline_result.score,
            improvement=improvement,
            n_trials=n,
            total_time_ms=round(elapsed_ms, 1),
            confidence=confidence,
        )
