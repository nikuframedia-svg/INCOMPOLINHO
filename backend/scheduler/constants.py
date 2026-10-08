"""Scheduler constants — Spec 02 §1 / Spec 09.

Thin wrapper over FactoryConfig defaults for backward compatibility.
All values match the Incompol factory configuration.
New code should use config directly via FactoryConfig.
"""

from __future__ import annotations

from backend.config.types import FactoryConfig

_DEFAULT = FactoryConfig()

# Day capacity in minutes (07:00–00:00 = 17h = 1020 min)
DAY_CAP = _DEFAULT.day_capacity_min

# Shift boundaries (real clock minutes from midnight)
SHIFT_A_START = _DEFAULT.shift_a_start  # 07:00 = 420
SHIFT_A_END = _DEFAULT.shift_a_end  # 15:30 = 930
SHIFT_B_END = _DEFAULT.shift_b_end  # 00:00 = 1440

# Default OEE
DEFAULT_OEE = _DEFAULT.oee_default

# Default setup hours when not in master data
DEFAULT_SETUP_H = _DEFAULT.default_setup_hours

# Tool grouping split thresholds
MAX_RUN_DAYS = _DEFAULT.max_run_days
MAX_EDD_GAP = _DEFAULT.max_edd_gap

# JIT / Latest Start Time
LST_SAFETY_BUFFER = _DEFAULT.lst_safety_buffer

# Dispatch sequencing
EDD_SWAP_TOLERANCE = _DEFAULT.edd_swap_tolerance

# Minimum production time per lot
MIN_PROD_MIN = _DEFAULT.min_prod_min

# Operator capacities per (group, shift)
OPERATOR_CAP = dict(_DEFAULT.operators)

# Machine → group mapping
MACHINE_GROUP = _DEFAULT.machine_groups
