"""Learning Engine types — Spec 08."""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(slots=True)
class SchedulerParams:
    """Tunable scheduler parameters. Defaults match current constants."""

    max_edd_gap: int = 10
    max_run_days: int = 4
    edd_swap_tolerance: int = 5
    edd_assign_threshold: int = 5
    campaign_window: int = 15  # EDD_SWAP_TOLERANCE + 10
    backward_buffer_pct: float = 0.05
    jit_threshold: float = 95.0
    interleave_enabled: bool = True

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> SchedulerParams:
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass(slots=True)
class ISContext:
    """ISOP feature vector for transfer learning."""

    n_ops: int
    n_machines: int
    n_days: int
    total_demand: int
    avg_oee: float
    twin_pct: float  # fraction of ops with twins
    alt_pct: float  # fraction of ops with alt machines
    avg_edd: float
    demand_density: float  # total_load_min / total_capacity_min
    planning_policy_version: str = "twin-shared-material-v2"


@dataclass(slots=True)
class StudyResult:
    """Result of a Bayesian optimization study."""

    best_params: SchedulerParams
    best_reward: float
    best_score: dict
    baseline_score: dict
    improvement: dict
    n_trials: int
    total_time_ms: float
    confidence: str  # "high" | "medium" | "low" | "cold_start"
