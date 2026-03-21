"""Failure Impact Analysis — per-failure impact on scheduled blocks.

Port of failures/impact-analysis.ts.
Returns 1 ImpactReport per FailureEvent with affected blocks and loss metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..types import Block


@dataclass
class ImpactedBlock:
    op_id: str
    tool_id: str
    sku: str
    machine_id: str
    day_idx: int
    shift: str
    scheduled_qty: int
    qty_at_risk: int
    minutes_at_risk: int
    has_alternative: bool
    alt_machine: str | None = None


@dataclass
class DailyImpact:
    day_idx: int
    qty_at_risk: int = 0
    minutes_at_risk: int = 0
    blocks_affected: int = 0


@dataclass
class ImpactSummary:
    total_blocks_affected: int = 0
    total_qty_at_risk: int = 0
    total_minutes_at_risk: int = 0
    blocks_with_alternative: int = 0
    blocks_without_alternative: int = 0
    ops_affected: int = 0
    skus_affected: int = 0


@dataclass
class ImpactReport:
    failure_event: dict[str, Any]
    impacted_blocks: list[ImpactedBlock] = field(default_factory=list)
    summary: ImpactSummary = field(default_factory=ImpactSummary)
    daily_impact: list[DailyImpact] = field(default_factory=list)


def analyze_all_failures(
    failures: list[dict[str, Any]],
    blocks: list[Block],
    n_days: int,
    third_shift: bool = False,
) -> list[ImpactReport]:
    """Analyze impact of each failure event on scheduled blocks.

    Args:
        failures: List of FailureEvent dicts
        blocks: Scheduled production blocks
        n_days: Planning horizon
        third_shift: Include Z shift

    Returns:
        One ImpactReport per failure event.
    """
    return [
        _analyze_single_failure(failure, blocks, n_days)
        for failure in failures
    ]


def _analyze_single_failure(
    failure: dict[str, Any],
    blocks: list[Block],
    n_days: int,
) -> ImpactReport:
    """Analyze a single failure's impact on blocks."""
    resource_type = failure.get("resourceType", failure.get("resource_type", "machine"))
    resource_id = failure.get("resourceId", failure.get("resource_id", ""))
    start_day = failure.get("startDay", failure.get("start_day", 0))
    end_day = failure.get("endDay", failure.get("end_day", start_day))
    cap_factor = failure.get("capacityFactor", failure.get("capacity_factor", 0.0))
    failure_shift = failure.get("shift")

    impacted: list[ImpactedBlock] = []
    daily: dict[int, DailyImpact] = {}
    ops_set: set[str] = set()
    skus_set: set[str] = set()

    for block in blocks:
        # Match resource
        if resource_type == "machine" and block.machine_id != resource_id:
            continue
        if resource_type == "tool" and block.tool_id != resource_id:
            continue

        # Check temporal overlap
        if block.day_idx < start_day or block.day_idx > end_day:
            continue

        # If failure specifies shift, check match
        if failure_shift and block.shift != failure_shift:
            continue

        # Calculate loss
        loss_factor = 1.0 - cap_factor
        qty_at_risk = round(block.qty * loss_factor)
        minutes_at_risk = round(block.prod_min * loss_factor)

        has_alt = block.has_alt
        alt_m = block.alt_m

        impacted.append(ImpactedBlock(
            op_id=block.op_id,
            tool_id=block.tool_id,
            sku=block.sku,
            machine_id=block.machine_id,
            day_idx=block.day_idx,
            shift=block.shift,
            scheduled_qty=block.qty,
            qty_at_risk=qty_at_risk,
            minutes_at_risk=minutes_at_risk,
            has_alternative=has_alt,
            alt_machine=alt_m,
        ))

        ops_set.add(block.op_id)
        skus_set.add(block.sku)

        # Aggregate daily
        if block.day_idx not in daily:
            daily[block.day_idx] = DailyImpact(day_idx=block.day_idx)
        di = daily[block.day_idx]
        di.qty_at_risk += qty_at_risk
        di.minutes_at_risk += minutes_at_risk
        di.blocks_affected += 1

    # Build summary
    with_alt = sum(1 for ib in impacted if ib.has_alternative)
    summary = ImpactSummary(
        total_blocks_affected=len(impacted),
        total_qty_at_risk=sum(ib.qty_at_risk for ib in impacted),
        total_minutes_at_risk=sum(ib.minutes_at_risk for ib in impacted),
        blocks_with_alternative=with_alt,
        blocks_without_alternative=len(impacted) - with_alt,
        ops_affected=len(ops_set),
        skus_affected=len(skus_set),
    )

    return ImpactReport(
        failure_event=failure,
        impacted_blocks=impacted,
        summary=summary,
        daily_impact=sorted(daily.values(), key=lambda d: d.day_idx),
    )
