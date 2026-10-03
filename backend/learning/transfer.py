"""Thompson Sampling transfer — Spec 08 §5.

Cross-ISOP knowledge transfer via simplified Thompson Sampling.
"""

from __future__ import annotations

import random

from .store import LearnStore
from .types import ISContext, SchedulerParams, StudyResult


class ThompsonTransfer:
    """Cross-ISOP transfer via Thompson Sampling."""

    def __init__(self, store: LearnStore) -> None:
        self._store = store

    def suggest_warm_start(self, context: ISContext) -> SchedulerParams | None:
        """Pick warm-start params using Thompson Sampling on similar ISOPs."""
        history = self._store.load_history()
        if not history:
            return None

        compatible = [
            item
            for item in history
            if item["context"].get("planning_policy_version")
            == context.planning_policy_version
        ]
        if not compatible:
            return None

        # Filter by similarity
        similar = [h for h in compatible if _is_similar(h["context"], context)]
        if not similar:
            # Fallback: best result under the same planning semantics.
            return SchedulerParams.from_dict(compatible[0]["best_params"])

        # Thompson: sample Normal(reward, std) per entry, pick highest sample
        best_sample = -float("inf")
        best_params = None

        for h in similar:
            mean = h["reward"]
            baseline = h.get("baseline_reward", mean)
            std = max(0.1, abs(mean - baseline))
            sample = random.gauss(mean, std)

            if sample > best_sample:
                best_sample = sample
                best_params = SchedulerParams.from_dict(h["best_params"])

        return best_params

    def record(self, context: ISContext, result: StudyResult, label: str = "") -> None:
        """Record a study result for future transfer."""
        self._store.save_study(context, result, label)


def _is_similar(ctx_dict: dict, ctx: ISContext) -> bool:
    """Check if two ISOP contexts are similar enough for transfer."""
    dd = ctx_dict.get("demand_density", 0)
    n = ctx_dict.get("n_ops", 0)

    dd_threshold = 0.3 * max(dd, ctx.demand_density, 0.01)
    n_threshold = 0.5 * max(n, ctx.n_ops, 1)

    return abs(dd - ctx.demand_density) < dd_threshold and abs(n - ctx.n_ops) < n_threshold
