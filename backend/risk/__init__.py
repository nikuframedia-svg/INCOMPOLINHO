"""Risk Assessment — Spec 06.

Three tiers:
  Tier 1: Slack analytics (<50ms) — always computed
  Tier 2: Surrogate model (<100ms) — if model trained
  Tier 3: Monte Carlo LHS (~3s) — if cache passed or run on demand
"""

from __future__ import annotations

from backend.config.types import FactoryConfig
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData

from .heatmap import compute_heatmap
from .slack_analytics import (
    compute_health_score,
    compute_lot_risks,
    compute_machine_risks,
)
from .surrogate import extract_features, predict_risk
from .types import RiskResult

__all__ = [
    "compute_risk",
    "RiskResult",
]


def compute_risk(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    mc_cache: dict | None = None,
    config: FactoryConfig | None = None,
) -> RiskResult:
    """Compute risk assessment (Tier 1 always, Tier 2/3 if available).

    Args:
        segments: Schedule segments from dispatch.
        lots: Production lots from lot sizing.
        engine_data: Full engine input data.
        mc_cache: Pre-computed Monte Carlo results (from monte_carlo_risk).
        config: Factory runtime rules for resources and calendars.

    Returns:
        RiskResult with all tiers populated as available.
    """
    # Tier 1: Slack analytics (always)
    lot_risks = compute_lot_risks(segments, lots, engine_data, config=config)
    machine_risks = compute_machine_risks(
        segments,
        lot_risks,
        engine_data,
        config=config,
    )
    health = compute_health_score(lot_risks, machine_risks)
    heatmap = compute_heatmap(segments, lot_risks, engine_data, config=config)

    critical_count = sum(1 for lr in lot_risks if lr.risk_level == "critical")
    top_risks = sorted(
        lot_risks,
        key=lambda lr: (
            lr.edd,
            -lr.risk_score,
            lr.completion_day,
            lr.sku,
        ),
    )[:5]
    bottleneck = (
        max(
            machine_risks, key=lambda mr: (mr.peak_utilization is None, mr.peak_utilization or 0)
        ).machine_id
        if machine_risks
        else ""
    )

    # Tier 2: Surrogate (if trained)
    surrogate_otd: float | None = None
    surrogate_conf: str | None = None
    features = extract_features(lot_risks, machine_risks, engine_data)
    prediction = (
        predict_risk(features)
        if all(m.peak_utilization is not None for m in machine_risks)
        else None
    )
    if prediction:
        surrogate_otd, surrogate_conf = prediction

    # Tier 3: Monte Carlo (if cached)
    mc_otd_p50: float | None = None
    mc_otd_p80: float | None = None
    mc_otd_p95: float | None = None
    mc_tardy: float | None = None
    mc_runs: int | None = None
    if mc_cache:
        mc_otd_p50 = mc_cache.get("otd_p50")
        mc_otd_p80 = mc_cache.get("otd_p80")
        mc_otd_p95 = mc_cache.get("otd_p95")
        mc_tardy = mc_cache.get("tardy_mean")
        mc_runs = mc_cache.get("n_samples")

    return RiskResult(
        health_score=health,
        lot_risks=lot_risks,
        machine_risks=machine_risks,
        heatmap=heatmap,
        critical_count=critical_count,
        top_risks=top_risks,
        bottleneck=bottleneck,
        surrogate_otd_prob=surrogate_otd,
        surrogate_confidence=surrogate_conf,
        mc_otd_p50=mc_otd_p50,
        mc_otd_p80=mc_otd_p80,
        mc_otd_p95=mc_otd_p95,
        mc_tardy_expected=mc_tardy,
        mc_runs=mc_runs,
    )
