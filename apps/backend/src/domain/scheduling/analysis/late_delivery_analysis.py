"""Late delivery analysis — port of analysis/late-delivery-analysis.ts.

Pure read-only analysis of already-scheduled blocks.
Identifies demand checkpoints where cumProd < cumDemand
and enriches each entry with delay estimate + suggested actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..types import Block, EOp

SuggestedAction = Literal[
    "THIRD_SHIFT", "OVERTIME", "NEGOTIATE_DATE", "SPLIT", "FORMAL_ACCEPT"
]


@dataclass
class LateDeliveryEntry:
    op_id: str
    sku: str
    nm: str
    machine_id: str
    tool_id: str
    cl: str | None = None
    cl_nm: str | None = None
    client_tier: int = 3
    deadline: int = 0
    deadline_date: str | None = None
    shortfall: int = 0
    delay_days: int = 0
    earliest_possible_day: int = 0
    is_resolved: bool = False
    resolved_by: str | None = None
    suggested_actions: list[str] = field(default_factory=list)


@dataclass
class LateDeliveryAnalysis:
    entries: list[LateDeliveryEntry] = field(default_factory=list)
    unresolved_count: int = 0
    resolved_with_cost_count: int = 0
    total_shortfall_pcs: int = 0
    affected_clients: list[str] = field(default_factory=list)
    worst_tier_affected: int = 5
    otd_delivery: float = 100.0


def _get_block_qty_for_op(block: Block, op_id: str) -> int:
    """Get production qty for a specific op from a block (twin-aware)."""
    if block.is_twin_production and block.outputs:
        for out in block.outputs:
            if out.op_id == op_id:
                return out.qty
        return 0
    return block.qty if block.op_id == op_id else 0


def analyze_late_deliveries(
    blocks: list[Block],
    ops: list[EOp],
    dates: list[str],
    client_tiers: dict[str, int] | None = None,
) -> LateDeliveryAnalysis:
    """Analyze late deliveries from an already-scheduled set of blocks.

    Pure function, O(ops × days). Does NOT re-run the scheduler.
    """
    if client_tiers is None:
        client_tiers = {}

    ok_blocks = [b for b in blocks if b.type != "blocked"]
    entries: list[LateDeliveryEntry] = []

    otd_d_on_time = 0
    otd_d_total = 0

    for op in ops:
        # Twin-aware: include blocks where this op appears in outputs[]
        op_ok_blocks = [
            b for b in ok_blocks
            if (b.is_twin_production and b.outputs and any(o.op_id == op.id for o in b.outputs))
            or (b.op_id == op.id)
        ]

        cum_demand = 0
        cum_prod = 0
        worst_shortfall = 0
        worst_day = -1
        cum_prod_by_day: list[int] = []

        for d in range(len(op.d)):
            day_demand = max(op.d[d] if d < len(op.d) and op.d[d] else 0, 0)
            cum_demand += day_demand
            cum_prod += sum(
                _get_block_qty_for_op(b, op.id)
                for b in op_ok_blocks
                if b.day_idx == d
            )
            cum_prod_by_day.append(cum_prod)

            # OTD-D counting
            if day_demand > 0:
                otd_d_total += 1
                if cum_prod >= cum_demand:
                    otd_d_on_time += 1

            # Checkpoint failure detection
            if day_demand > 0 and cum_prod < cum_demand:
                shortfall = cum_demand - cum_prod
                if shortfall > worst_shortfall:
                    worst_shortfall = shortfall
                    worst_day = d

        if worst_day < 0:
            continue

        # Find earliest possible day
        total_cum_demand_at_worst = sum(
            max(op.d[i] if i < len(op.d) and op.d[i] else 0, 0)
            for i in range(worst_day + 1)
        )
        earliest_possible_day = len(op.d)
        resolved = False
        for d in range(worst_day + 1, len(op.d)):
            if (cum_prod_by_day[d] if d < len(cum_prod_by_day) else 0) >= total_cum_demand_at_worst:
                earliest_possible_day = d
                resolved = True
                break
        if not resolved and cum_prod >= total_cum_demand_at_worst:
            earliest_possible_day = len(op.d) - 1
            resolved = True

        delay_days = max(0, earliest_possible_day - worst_day)
        client_tier = client_tiers.get(op.cl, 3) if op.cl else 3

        # Determine resolved_by
        resolved_by = None
        if resolved:
            primary_machine = op.m
            has_alt = any(b.machine_id != primary_machine for b in op_ok_blocks)
            if has_alt:
                resolved_by = "ALT_MACHINE"
            elif any(b.day_idx < worst_day for b in op_ok_blocks):
                resolved_by = "ADVANCE"
            else:
                resolved_by = "OVERTIME"

        # Suggest actions
        suggested: list[str] = []
        if delay_days <= 2:
            suggested.append("OVERTIME")
        if 1 <= delay_days <= 3:
            suggested.append("THIRD_SHIFT")
        if delay_days > 3:
            suggested.append("SPLIT")
        if delay_days > 5:
            suggested.append("NEGOTIATE_DATE")
        suggested.append("FORMAL_ACCEPT")

        entries.append(LateDeliveryEntry(
            op_id=op.id,
            sku=op.sku,
            nm=op.nm,
            machine_id=op.m,
            tool_id=op.t,
            cl=op.cl,
            cl_nm=op.cl_nm,
            client_tier=client_tier,
            deadline=worst_day,
            deadline_date=dates[worst_day] if worst_day < len(dates) else None,
            shortfall=worst_shortfall,
            delay_days=delay_days,
            earliest_possible_day=earliest_possible_day,
            is_resolved=resolved,
            resolved_by=resolved_by,
            suggested_actions=suggested,
        ))

    # Sort: unresolved first, then tier asc, then delay desc
    entries.sort(key=lambda e: (e.is_resolved, e.client_tier, -e.delay_days))

    unresolved_count = sum(1 for e in entries if not e.is_resolved)
    resolved_with_cost_count = sum(1 for e in entries if e.is_resolved)
    total_shortfall_pcs = sum(e.shortfall for e in entries)

    client_set: set[str] = set()
    for e in entries:
        if e.cl:
            client_set.add(e.cl)

    worst_tier = min((e.client_tier for e in entries), default=5)
    otd_delivery = (otd_d_on_time / otd_d_total * 100) if otd_d_total > 0 else 100.0

    return LateDeliveryAnalysis(
        entries=entries,
        unresolved_count=unresolved_count,
        resolved_with_cost_count=resolved_with_cost_count,
        total_shortfall_pcs=total_shortfall_pcs,
        affected_clients=sorted(client_set),
        worst_tier_affected=worst_tier,
        otd_delivery=otd_delivery,
    )
