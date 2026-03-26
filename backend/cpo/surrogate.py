"""Surrogate pre-screening for CPO v3.0.

Uses RandomForest to predict fitness of chromosomes before full evaluation.
Only used in deep/max modes. Graceful fallback if sklearn unavailable.
"""

from __future__ import annotations

import logging

from backend.cpo.chromosome import Chromosome

logger = logging.getLogger(__name__)


class SurrogateModel:
    """RandomForest surrogate for pre-screening candidates."""

    def __init__(self, n_estimators: int = 50, min_samples: int = 30):
        self.n_estimators = n_estimators
        self.min_samples = min_samples
        self.model = None
        self.X: list[list[float]] = []
        self.y: list[float] = []
        self.is_trained = False
        self._sklearn_available: bool | None = None

    def _check_sklearn(self) -> bool:
        if self._sklearn_available is not None:
            return self._sklearn_available
        try:
            from sklearn.ensemble import RandomForestRegressor  # noqa: F401
            self._sklearn_available = True
        except ImportError:
            logger.warning("scikit-learn not available; surrogate disabled")
            self._sklearn_available = False
        return self._sklearn_available

    def _encode(self, chrom: Chromosome) -> list[float]:
        """Encode chromosome as feature vector."""
        # Machine choice summary
        n_alt = sum(chrom.machine_choice.values()) if chrom.machine_choice else 0
        n_total = max(len(chrom.machine_choice), 1)

        # Sequence disorder (sum of key deltas from sorted order)
        disorder = 0.0
        for keys in chrom.sequence_keys.values():
            if len(keys) >= 2:
                sorted_keys = sorted(keys)
                for k, s in zip(keys, sorted_keys):
                    disorder += abs(k - s)

        return [
            float(chrom.edd_gap),
            float(chrom.max_edd_span),
            float(n_alt) / float(n_total),
            disorder,
            chrom.buffer_pct,
            float(chrom.campaign_window),
        ]

    def add_sample(self, chrom: Chromosome, cost: float) -> None:
        self.X.append(self._encode(chrom))
        self.y.append(cost)

    def train(self) -> bool:
        if not self._check_sklearn():
            return False
        if len(self.X) < self.min_samples:
            return False

        from sklearn.ensemble import RandomForestRegressor

        self.model = RandomForestRegressor(
            n_estimators=self.n_estimators,
            max_depth=8,
            random_state=42,
        )
        self.model.fit(self.X, self.y)
        self.is_trained = True
        return True

    def predict(self, chrom: Chromosome) -> float:
        if not self.is_trained or self.model is None:
            return float("inf")
        features = self._encode(chrom)
        return float(self.model.predict([features])[0])

    def should_evaluate(self, chrom: Chromosome, best_cost: float, threshold: float = 1.3) -> bool:
        """Return True if chromosome is worth full evaluation."""
        if not self.is_trained:
            return True
        predicted = self.predict(chrom)
        return predicted < best_cost * threshold
