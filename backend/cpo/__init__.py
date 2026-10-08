"""CPO v4 — APS trust-loop optimizer.

Primary scheduling interface. Operational mode is the greedy/VNS baseline,
local CP-SAT polish and the no-loss improvement cycle, with hard-gate
validation. The GA lives offline in ``backend.cpo.offline_ga``.
"""

from backend.cpo.optimizer import optimize

__all__ = ["optimize"]
