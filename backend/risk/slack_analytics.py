"""Tier 1 — Slack Analytics: Spec 06 §2.

Instant risk from schedule structure. No simulation. <50ms.
"""

from __future__ import annotations

import copy
from collections import defaultdict

from backend.calendar import available_machine_capacity
from backend.config.types import FactoryConfig
from backend.cpo import optimize
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.jit_policy import (
    calendar_holidays,
    production_due_day,
    window_violation_details,
)
from backend.scheduler.operators import compute_operator_alerts
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import validate_plan
from backend.types import EngineData

from .types import LotRisk, MachineRisk, risk_status

# Risk thresholds (days of slack)
SLACK_CRITICAL = 0
SLACK_HIGH = 1
SLACK_MEDIUM = 3

# Statistical parameters for risk estimation
CV_PROCESSING = 0.10  # coefficient of variation for processing time
CV_SETUP = 0.20  # coefficient of variation for setup time
Z_95 = 1.645  # z-score for 95% confidence

# Top risks shown to planners: 7 calendar days from today, worst status first.
TOP_RISK_WINDOW_DAYS = 7
TOP_RISK_LIMIT = 5
_STATUS_ORDER = {"late": 0, "at_limit": 1, "short_slack": 2}

# Only constraints the analysis below can prove. There is deliberately no
# fallback from the slack itself: a small slack does not tell which resource
# is short, so an unproven lot stays "none" and shows no cause.
_BINDING_PRIORITY = {
    "none": 0,
    "long_run": 35,
    "jit_exception": 40,
    "setup": 45,
    "operator": 50,
    "calendar": 60,
}


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

    bindings = _binding_constraints_by_lot(segments, lots, engine_data, config)
    risks: list[LotRisk] = []
    for lot in lots:
        comp = lot_end.get(lot.id, engine_data.n_days)
        machine = lot_machine.get(lot.id, lot.machine_id)
        due_day = production_due_day(lot)
        slack_days = due_day - comp
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

        binding = bindings.get(lot.id, "none")

        sku = lot.sku
        if not sku and lot.twin_outputs:
            sku = lot.sku or lot.twin_outputs[0][1]
        elif not sku and "_" in lot.op_id:
            parts = lot.op_id.split("_")
            sku = parts[-1] if len(parts) >= 3 else lot.op_id

        risks.append(
            LotRisk(
                lot_id=lot.id,
                sku=sku,
                machine_id=machine,
                edd=due_day,
                completion_day=comp,
                slack_days=slack_days,
                slack_min=slack_min,
                risk_score=round(risk_score, 3),
                risk_level=level,
                binding_constraint=binding,
                status=risk_status(slack_days),
                cause=None if binding == "none" else binding,
            )
        )

    return risks


def select_top_risks(
    lot_risks: list[LotRisk],
    today_idx: int,
    *,
    window_days: int = TOP_RISK_WINDOW_DAYS,
    limit: int | None = TOP_RISK_LIMIT,
) -> list[LotRisk]:
    """Lots that need attention in the next ``window_days`` calendar days.

    A lot is in the window when its due day falls inside it, or when it is
    late and still unfinished at the window start (due before, completion
    on/after today). A lot whose production finished before today is history
    and never returned, whatever its status (a late order it caused shows in
    the late-orders list instead). Lots with status ``ok`` are never
    returned. Order: late, at the limit, short slack; then due day; then
    highest risk score.
    """
    start = int(today_idx)
    end = start + max(1, int(window_days)) - 1
    selected = [
        risk
        for risk in lot_risks
        if (risk.status or risk_status(risk.slack_days)) in _STATUS_ORDER
        and risk.completion_day >= start
        and risk.edd <= end
    ]
    selected.sort(
        key=lambda risk: (
            _STATUS_ORDER[risk.status or risk_status(risk.slack_days)],
            risk.edd,
            -risk.risk_score,
            risk.completion_day,
            risk.sku,
            risk.lot_id,
        )
    )
    return selected if limit is None else selected[: max(0, int(limit))]


def _binding_constraints_by_lot(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    config: FactoryConfig | None,
) -> dict[str, str]:
    effective_config = config or FactoryConfig()
    bindings: dict[str, str] = {}

    def set_binding(lot_id: object, value: str) -> None:
        key = str(lot_id or "")
        if not key:
            return
        current = bindings.get(key, "none")
        if _BINDING_PRIORITY[value] > _BINDING_PRIORITY[current]:
            bindings[key] = value

    for violation in validate_plan(segments, engine_data, effective_config):
        kind = str(violation.get("kind", ""))
        if kind in {"machine_down", "tool_down"}:
            set_binding(violation.get("lot_id"), "calendar")
        elif kind == "setup_crew_overlap":
            set_binding(violation.get("lot_id"), "setup")
            set_binding((violation.get("other") or {}).get("lot_id"), "setup")

    alert_keys = {
        (alert.day_idx, alert.machine_group, alert.shift)
        for alert in compute_operator_alerts(segments, engine_data, effective_config)
    }
    if alert_keys:
        machine_groups = effective_config.machine_groups
        for segment in segments:
            if segment.prod_min <= 0:
                continue
            key = (
                segment.day_idx,
                machine_groups.get(segment.machine_id, "Grandes"),
                segment.shift,
            )
            if key in alert_keys:
                set_binding(segment.lot_id, "operator")

    if lots:
        min_start = min((segment.day_idx for segment in segments), default=0)
        holidays = calendar_holidays(
            engine_data,
            min_start - 7,
            engine_data.n_days + 7,
        )
        for item in window_violation_details(segments, lots, holidays):
            set_binding(item.get("lot_id"), "jit_exception")

    limit = max(1, int(getattr(effective_config, "max_run_days", 4) or 4))
    days_by_lot: dict[str, set[int]] = defaultdict(set)
    for segment in segments:
        if segment.prod_min > 0:
            days_by_lot[segment.lot_id].add(segment.day_idx)
    for lot in lots:
        if _longest_consecutive_streak(days_by_lot.get(lot.id, set())) > limit:
            set_binding(lot.id, "long_run")

    return bindings


def _longest_consecutive_streak(days: set[int]) -> int:
    longest = current = 0
    previous: int | None = None
    for day in sorted(days):
        if previous is None or day == previous + 1:
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        previous = day
    return longest


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
        daily_util = []
        inconsistent = False
        for day_idx in range(engine_data.n_days):
            day_cap_val = available_machine_capacity(m.id, day_idx, engine_data, config)
            inconsistent |= day_cap_val <= 0 and used.get((m.id, day_idx), 0) > 0
            daily_util.append(
                used.get((m.id, day_idx), 0) / day_cap_val if day_cap_val > 0 else 0.0
            )
        peak = max(daily_util) if daily_util else 0
        avg = sum(daily_util) / len(daily_util) if daily_util else 0
        critical = sum(
            1 for lr in lot_risks if lr.machine_id == m.id and lr.risk_level in ("critical", "high")
        )

        results.append(
            MachineRisk(
                machine_id=m.id,
                peak_utilization=None if inconsistent else round(peak, 3),
                avg_utilization=None if inconsistent else round(avg, 3),
                critical_lot_count=critical,
                bottleneck_score=0.0,
            )
        )

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
    if any(m.peak_utilization is None for m in machine_risks):
        return 0
    if not lot_risks and not any(m.peak_utilization for m in machine_risks):
        return 100
    n = len(lot_risks) or 1

    safe_pct = sum(1 for lr in lot_risks if lr.risk_level == "low") / n
    critical_pct = sum(1 for lr in lot_risks if lr.risk_level == "critical") / n
    max_peak = max((mr.peak_utilization for mr in machine_risks), default=0)
    avg_slack = sum(lr.slack_days for lr in lot_risks) / n
    slack_norm = min(1.0, avg_slack / 10.0)

    score = safe_pct * 40 + (1 - max_peak) * 20 + (1 - critical_pct) * 20 + slack_norm * 20
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
