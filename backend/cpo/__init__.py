"""CPO v4 — APS trust-loop optimizer.

Primary scheduling interface. Operational mode is greedy/JIT/VNS plus local
CP-SAT polish with hard-gate validation. GA helpers are offline-only.
"""

from backend.cpo.optimizer import optimize

__all__ = ["optimize"]
