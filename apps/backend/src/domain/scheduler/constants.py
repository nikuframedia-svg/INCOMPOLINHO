"""Scheduler constants — re-exports from scheduling/constants.py + additions.

All values FROZEN. Do not change without updating frozen-invariants tests.
"""

from __future__ import annotations

# ── Re-export from scheduling/constants ──
from ..scheduling.constants import (  # noqa: E402, F401
    BUCKET_WINDOW,
    DAY_CAP,
    DEFAULT_OEE,
    LEVEL_HIGH_THRESHOLD,
    LEVEL_LOOKAHEAD,
    LEVEL_LOW_THRESHOLD,
    MAX_ADVANCE_DAYS,
    MAX_AUTO_MOVES,
    MAX_EDD_GAP,
    MAX_OVERFLOW_ITER,
    MINUTES_PER_DAY,
    S0,
    S1,
    S2,
    T1,
)

# ── ATCS grid search ──
K1_VALUES: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0, 3.0)
K2_VALUES: tuple[float, ...] = (0.1, 0.25, 0.5, 0.75, 1.0)

# ── Dispatch rules for Tier 3 multi-rule search ──
DISPATCH_RULES: tuple[str, ...] = ("EDD", "ATCS", "CR", "SPT", "WSPT")

# ── Tier 3 OTD-D tardiness budget ──
TIER3_TARDINESS_FACTOR = 1.50
TIER3_TARDINESS_ADDEND = 500

# ── Setup attempt limit per tool group ──
MAX_SETUP_ATTEMPTS = 12
