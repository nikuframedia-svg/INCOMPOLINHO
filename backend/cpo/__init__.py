"""CPO v3.0 — Cascading Pipeline Optimizer.

Primary scheduling interface. Wraps the greedy pipeline in a Genetic Algorithm.
"""

from backend.cpo.optimizer import optimize

__all__ = ["optimize"]
