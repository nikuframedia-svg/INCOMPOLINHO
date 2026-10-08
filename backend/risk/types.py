"""Risk assessment types — Spec 06 §1."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LotRisk:
    lot_id: str
    sku: str
    machine_id: str
    edd: int
    completion_day: int
    slack_days: int
    slack_min: float
    risk_score: float  # 0.0 (safe) to 1.0 (critical)
    risk_level: str  # "low" | "medium" | "high" | "critical"
    # Only constraints proven by the plan analysis: jit_exception|long_run|
    # operator|setup|calendar, else "none". Never a guess from the slack.
    binding_constraint: str
    # Plain planner level, independent from risk_level (which feeds the health
    # score and the surrogate and keeps its meaning): late (slack < 0),
    # at_limit (slack == 0), short_slack (slack 1-2) or ok.
    status: str = ""
    # Proven cause (same code as binding_constraint) or None when unproven.
    cause: str | None = None

    def __post_init__(self) -> None:
        if not self.status:
            self.status = risk_status(self.slack_days)
        if self.cause is None and self.binding_constraint not in ("", "none"):
            self.cause = self.binding_constraint


SHORT_SLACK_MAX_DAYS = 2


def risk_status(slack_days: int) -> str:
    """Plain level shown to planners; slack in the same days as ``slack_days``."""
    if slack_days < 0:
        return "late"
    if slack_days == 0:
        return "at_limit"
    if slack_days <= SHORT_SLACK_MAX_DAYS:
        return "short_slack"
    return "ok"


@dataclass(slots=True)
class MachineRisk:
    machine_id: str
    peak_utilization: float | None  # None: positive load without capacity
    avg_utilization: float | None
    critical_lot_count: int  # lots with slack < 2 days on this machine
    bottleneck_score: float  # 0-1, sensitivity of OTD to this machine


@dataclass(slots=True)
class HeatmapCell:
    machine_id: str
    day_idx: int
    utilization: float | None  # None: positive load without capacity
    load_min: float
    capacity_min: float
    min_slack_min: float  # min slack of active lots (-1 if none)
    risk_level: str  # "low" | "medium" | "high" | "critical"


@dataclass(slots=True)
class RiskResult:
    # Tier 1 (always present)
    health_score: int  # 0-100 (100 = safe)
    lot_risks: list[LotRisk]
    machine_risks: list[MachineRisk]
    heatmap: list[HeatmapCell]
    critical_count: int
    top_risks: list[LotRisk]  # top 5 riskiest
    bottleneck: str  # machine_id

    # Tier 2 (if surrogate trained)
    surrogate_otd_prob: float | None
    surrogate_confidence: str | None

    # Tier 3 (if Monte Carlo cached)
    mc_otd_p50: float | None
    mc_otd_p80: float | None
    mc_otd_p95: float | None
    mc_tardy_expected: float | None
    mc_runs: int | None
