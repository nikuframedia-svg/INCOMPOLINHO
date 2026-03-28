"""Population management for CPO v3.0.

Components:
  - FRRMAB: Fitness-Rate-Rank Multi-Armed Bandit (adaptive operator selection)
  - MAPElitesArchive: Quality-diversity archive (setups × earliness)
  - OneFifthRule: Adaptive mutation rate
  - Tournament selection
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

from backend.cpo.chromosome import Chromosome


# ─── FRRMAB ────────────────────────────────────────────────────────────


class FRRMAB:
    """Fitness-Rate-Rank Multi-Armed Bandit with UCB1.

    Selects operators adaptively based on observed fitness improvements.
    """

    def __init__(self, operators: list[str], window: int = 50, c: float = 0.5):
        self.operators = operators
        self.window = window
        self.c = c
        self.rewards: dict[str, deque] = {
            op: deque(maxlen=window) for op in operators
        }
        self.counts: dict[str, int] = {op: 0 for op in operators}
        self.total: int = 0

    def select(self, rng: random.Random) -> str:
        # Explore untested operators first
        untested = [op for op in self.operators if self.counts[op] == 0]
        if untested:
            return rng.choice(untested)

        scores = []
        for op in self.operators:
            avg_reward = (
                sum(self.rewards[op]) / len(self.rewards[op])
                if self.rewards[op]
                else 0.0
            )
            explore = self.c * math.sqrt(
                math.log(self.total + 1) / max(self.counts[op], 1)
            )
            scores.append(avg_reward + explore)

        best_score = max(scores)
        best_ops = [
            self.operators[i]
            for i, s in enumerate(scores)
            if abs(s - best_score) < 1e-9
        ]
        return rng.choice(best_ops)

    def update(self, operator: str, reward: float) -> None:
        self.rewards[operator].append(reward)
        self.counts[operator] += 1
        self.total += 1


# ─── MAP-Elites Archive ───────────────────────────────────────────────


@dataclass
class ArchiveEntry:
    chrom: Chromosome
    score: dict
    cost: float


class MAPElitesArchive:
    """2D quality-diversity archive indexed by (setups, earliness).

    Each cell stores the best feasible solution with that behavioral profile.
    Grid boundaries adapt automatically as new solutions are inserted.
    """

    def __init__(
        self,
        setups_range: tuple[int, int] = (60, 180),
        earliness_range: tuple[float, float] = (1.0, 10.0),
        bins: int = 10,
    ):
        self.setups_lo, self.setups_hi = setups_range
        self.earl_lo, self.earl_hi = earliness_range
        self.bins = bins
        self.grid: dict[tuple[int, int], ArchiveEntry] = {}

    def _adapt_range(self, setups: int, earliness: float) -> None:
        """Expand grid boundaries if a solution falls outside current range."""
        changed = False
        if setups < self.setups_lo:
            self.setups_lo = max(0, setups - 10)
            changed = True
        if setups > self.setups_hi:
            self.setups_hi = setups + 10
            changed = True
        if earliness < self.earl_lo:
            self.earl_lo = max(0.0, earliness - 1.0)
            changed = True
        if earliness > self.earl_hi:
            self.earl_hi = earliness + 1.0
            changed = True
        if changed:
            # Re-index existing entries under new grid
            old_entries = list(self.grid.values())
            self.grid.clear()
            for entry in old_entries:
                cell = self._to_cell(
                    entry.score.get("setups", 100),
                    entry.score.get("earliness_avg_days", 5.0),
                )
                existing = self.grid.get(cell)
                if existing is None or entry.cost < existing.cost:
                    self.grid[cell] = entry

    def _to_cell(self, setups: int, earliness: float) -> tuple[int, int]:
        si = int(
            (setups - self.setups_lo) / max(self.setups_hi - self.setups_lo, 1) * self.bins
        )
        si = max(0, min(self.bins - 1, si))
        ei = int(
            (earliness - self.earl_lo)
            / max(self.earl_hi - self.earl_lo, 0.1)
            * self.bins
        )
        ei = max(0, min(self.bins - 1, ei))
        return (si, ei)

    def try_insert(
        self, chrom: Chromosome, score: dict, cost: float
    ) -> bool:
        # Only feasible solutions
        if score.get("tardy_count", 1) > 0:
            return False

        setups = score.get("setups", 100)
        earliness = score.get("earliness_avg_days", 5.0)
        self._adapt_range(setups, earliness)

        cell = self._to_cell(
            score.get("setups", 100),
            score.get("earliness_avg_days", 5.0),
        )
        existing = self.grid.get(cell)
        if existing is None or cost < existing.cost:
            self.grid[cell] = ArchiveEntry(chrom=chrom, score=score, cost=cost)
            return True
        return False

    def sample(self, rng: random.Random) -> Chromosome | None:
        if not self.grid:
            return None
        entry = rng.choice(list(self.grid.values()))
        return entry.chrom.clone()

    def best(self) -> ArchiveEntry | None:
        if not self.grid:
            return None
        return min(self.grid.values(), key=lambda e: e.cost)

    def size(self) -> int:
        return len(self.grid)


# ─── 1/5 Rule ─────────────────────────────────────────────────────────


class OneFifthRule:
    """Adaptive mutation rate based on Rechenberg's 1/5 success rule."""

    def __init__(self, initial_rate: float = 0.3, window: int = 20):
        self.rate = initial_rate
        self.history: deque = deque(maxlen=window)

    def record(self, improved: bool) -> None:
        self.history.append(1 if improved else 0)
        if len(self.history) >= self.history.maxlen:
            ratio = sum(self.history) / len(self.history)
            if ratio > 0.2:
                self.rate = min(0.8, self.rate * 1.1)
            elif ratio < 0.2:
                self.rate = max(0.05, self.rate * 0.9)


# ─── Selection ─────────────────────────────────────────────────────────


def tournament_select(
    population: list[tuple[Chromosome, float]],
    k: int = 3,
    rng: random.Random | None = None,
) -> Chromosome:
    """Tournament selection. Returns clone of winner (lowest cost)."""
    rng = rng or random.Random()
    candidates = rng.sample(population, min(k, len(population)))
    winner = min(candidates, key=lambda x: x[1])
    return winner[0].clone()
