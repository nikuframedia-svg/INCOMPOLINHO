"""Tier 1 — Slack Analytics: Spec 06 §2.

Instant risk from schedule structure. No simulation. <50ms.
"""

from __future__ import annotations

import copy
from collections import defaultdict

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.scoring import compute_score
from backend.cpo import optimize
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData

from .types import LotRisk, MachineRisk

# Risk thresholds (days of slack)
SLACK_CRITICAL = 0
SLACK_HIGH = 1
SLACK_MEDIUM = 3

# Statistical parameters for risk estimation
CV_PROCESSING = 0.10    # coefficient of variation for processing time
CV_SETUP = 0.20         # coefficient of variation for setup time
Z_95 = 1.645            # z-score for 95% confidence


def compute_lot_risks(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    config: FactoryConfig | None = None,
) -> list[LotRisk]:
    """Compute risk per lot from schedule slack.

    Risk score = max(0, 1 - slack_min / (σ × Z_95))
    where σ = CV_PROCESSING × prod_min + CV_SETUP × setup_min.
    """
    # Completion day and machine per lot
    lot_end: dict[str, int] = {}
    lot_machine: dict[str, str] = {}
    for seg in segments:
        if seg.lot_id not in lot_end or seg.day_idx > lot_end[seg.lot_id]:
            lot_end[seg.lot_id] = seg.day_idx
            lot_machine[seg.lot_id] = seg.machine_id

    risks: list[LotRisk] = []
    for lot in lots:
        comp = lot_end.get(lot.id, engine_data.n_days)
        machine = lot_machine.get(lot.id, lot.machine_id)
        slack_days = lot.edd - comp
        day_cap = config.day_capacity_min if config else DAY_CAP
        slack_min = slack_days * day_cap

        # Estimated standard deviation of production time
        sigma = lot.prod_min * CV_PROCESSING + lot.setup_min * CV_SETUP
        threshold = sigma * Z_95

        if threshold > 0:
            risk_score = max(0.0, min(1.0, 1.0 - slack_min / threshold))
        else:
            risk_score = 0.0 if slack_days > 0 else 1.0

        if slack_days <= SLACK_CRITICAL:
            level = "critical"
        elif slack_days <= SLACK_HIGH:
            level = "high"
        elif slack_days <= SLACK_MEDIUM:
            level = "medium"
        else:
            level = "low"

        if slack_days <= 0:
            binding = "capacity"
        elif slack_days <= 1:
            binding = "crew"
        else:
            binding = "none"

        sku = ""
        if lot.twin_outputs:
            sku = lot.twin_outputs[0][1]
        elif "_" in lot.op_id:
            parts = lot.op_id.split("_")
            sku = parts[-1] if len(parts) >= 3 else lot.op_id

        risks.append(LotRisk(
            lot_id=lot.id,
            sku=sku,
            machine_id=machine,
            edd=lot.edd,
            completion_day=comp,
            slack_days=slack_days,
            slack_min=slack_min,
            risk_score=round(risk_score, 3),
            risk_level=level,
            binding_constraint=binding,
        ))

    return risks


def compute_machine_risks(
    segments: list[Segment],
    lot_risks: list[LotRisk],
    engine_data: EngineData,
    config: FactoryConfig | None = None,
) -> list[MachineRisk]:
    """Compute risk per machine from utilisation and lot slack."""
    used: dict[tuple[str, int], float] = defaultdict(float)
    for seg in segments:
        used[(seg.machine_id, seg.day_idx)] += seg.prod_min + seg.setup_min

    results: list[MachineRisk] = []
    for m in engine_data.machines:
        day_cap_val = config.day_capacity_min if config else DAY_CAP
        daily_util = [
            used.get((m.id, d), 0) / day_cap_val
            for d in range(engine_data.n_days)
        ]
        peak = max(daily_util) if daily_util else 0
        avg = sum(daily_util) / len(daily_util) if daily_util else 0
        critical = sum(
            1 for lr in lot_risks
            if lr.machine_id == m.id and lr.risk_level in ("critical", "high")
        )

        results.append(MachineRisk(
            machine_id=m.id,
            peak_utilization=round(peak, 3),
            avg_utilization=round(avg, 3),
            critical_lot_count=critical,
            bottleneck_score=0.0,
        ))

    return results


def compute_health_score(
    lot_risks: list[LotRisk],
    machine_risks: list[MachineRisk],
) -> int:
    """Health score 0-100. 100 = safe.

    Weighted combination of 4 signals:
    1. % lots without risk (40%)
    2. 1 - max peak utilisation (20%)
    3. 1 - % critical lots (20%)
    4. Avg slack normalised (20%)
    """
    n = len(lot_risks) or 1

    safe_pct = sum(1 for lr in lot_risks if lr.risk_level == "low") / n
    critical_pct = sum(1 for lr in lot_risks if lr.risk_level == "critical") / n
    max_peak = max((mr.peak_utilization for mr in machine_risks), default=0)
    avg_slack = sum(lr.slack_days for lr in lot_risks) / n
    slack_norm = min(1.0, avg_slack / 10.0)

    score = (
        safe_pct * 40
        + (1 - max_peak) * 20
        + (1 - critical_pct) * 20
        + slack_norm * 20
    )
    return max(0, min(100, round(score)))


def compute_bottleneck(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
) -> str:
    """Find bottleneck machine via sensitivity analysis.

    For each machine, simulate +10% capacity and measure OTD improvement.
    Machine with largest improvement = bottleneck.

    NOTE: Not in the <50ms path. Call separately when needed (~30ms).
    """
    baseline_score = compute_score(segments, lots, engine_data)
    baseline_otd = baseline_score.get("otd", 100.0)

    best_delta = -1.0
    bottleneck = engine_data.machines[0].id if engine_data.machines else ""

    for m in engine_data.machines:
        mutated = copy.deepcopy(engine_data)
        for mm in mutated.machines:
            if mm.id == m.id:
                mm.day_capacity = round(mm.day_capacity * 1.10)
                break

        result = optimize(mutated, mode="quick")
        delta = result.score.get("otd", 100.0) - baseline_otd
        if delta > best_delta:
            best_delta = delta
            bottleneck = m.id

    return bottleneck
