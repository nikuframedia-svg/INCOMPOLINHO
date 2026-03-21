"""What-If Simulator — port of mrp/mrp-what-if.ts.

Scenario mutations: rush orders, machine down, demand factor.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from ..constants import DAY_CAP
from ..types import EngineData
from .mrp_engine import MRPResult, compute_mrp


@dataclass
class FailureEvent:
    resource_type: str = "machine"
    resource_id: str = ""
    start_day: int = 0
    end_day: int = 0
    capacity_factor: float = 0.0


@dataclass
class WhatIfMutation:
    type: str  # "rush_order" | "demand_factor" | "machine_down" | "failure_event"
    tool_code: str | None = None
    rush_qty: int | None = None
    rush_day: int | None = None
    factor: float | None = None
    factor_tool_code: str | None = None
    machine: str | None = None
    down_start_day: int | None = None
    down_end_day: int | None = None
    failure_event: FailureEvent | None = None


@dataclass
class WhatIfDelta:
    tool_code: str
    baseline_stockout: int | None = None
    modified_stockout: int | None = None
    baseline_coverage: float = 0
    modified_coverage: float = 0
    baseline_planned_qty: int = 0
    modified_planned_qty: int = 0


@dataclass
class RCCPDelta:
    machine: str
    day_index: int
    baseline_util: float = 0
    modified_util: float = 0


@dataclass
class SummaryDelta:
    stockouts_change: int = 0
    avg_util_change: float = 0


@dataclass
class WhatIfResult:
    baseline: MRPResult | None = None
    modified: MRPResult | None = None
    deltas: list[WhatIfDelta] = field(default_factory=list)
    rccp_deltas: list[RCCPDelta] = field(default_factory=list)
    summary_delta: SummaryDelta = field(default_factory=SummaryDelta)


def compute_what_if(
    engine: EngineData,
    mutations: list[WhatIfMutation],
    baseline: MRPResult,
) -> WhatIfResult:
    """Compute What-If scenario by applying mutations and comparing against baseline."""
    # Deep clone engine data
    clone = engine.model_copy(deep=True)
    num_days = len(engine.dates)
    capacity_overrides: dict[str, list[int]] = {}
    wid_counter = 0

    for mut in mutations:
        if mut.type == "rush_order" and mut.tool_code and mut.rush_qty and mut.rush_day is not None:
            existing_ops = [o for o in clone.ops if o.t == mut.tool_code]
            if existing_ops:
                d_arr = existing_ops[0].d
                if mut.rush_day < len(d_arr):
                    d_arr[mut.rush_day] += mut.rush_qty
            else:
                tool = clone.tool_map.get(mut.tool_code)
                if tool:
                    from ..types import EOp
                    new_d = [0] * num_days
                    new_d[mut.rush_day] = mut.rush_qty
                    wid_counter += 1
                    clone.ops.append(EOp(
                        id=f"RUSH_{wid_counter}",
                        t=mut.tool_code,
                        m=tool.m,
                        sku="RUSH",
                        nm="Rush Order",
                        atr=0,
                        d=new_d,
                    ))

        if mut.type == "demand_factor" and mut.factor is not None:
            for op in clone.ops:
                if mut.factor_tool_code == "__all__" or op.t == mut.factor_tool_code:
                    op.d = [round(v * mut.factor) for v in op.d]

        if (
            mut.type == "machine_down"
            and mut.machine
            and mut.down_start_day is not None
            and mut.down_end_day is not None
        ):
            if mut.machine not in capacity_overrides:
                capacity_overrides[mut.machine] = [DAY_CAP] * num_days
            for d in range(mut.down_start_day, min(mut.down_end_day + 1, num_days)):
                capacity_overrides[mut.machine][d] = 0

        if mut.type == "failure_event" and mut.failure_event:
            fe = mut.failure_event
            if fe.resource_type == "machine":
                if fe.resource_id not in capacity_overrides:
                    capacity_overrides[fe.resource_id] = [DAY_CAP] * num_days
                d_start = max(fe.start_day, 0)
                d_end = min(fe.end_day, num_days - 1)
                for d in range(d_start, d_end + 1):
                    capacity_overrides[fe.resource_id][d] = round(DAY_CAP * fe.capacity_factor)

    has_co = len(capacity_overrides) > 0
    modified = compute_mrp(clone, capacity_overrides if has_co else None)

    # Build deltas per tool
    deltas: list[WhatIfDelta] = []
    for br in baseline.records:
        mr = next((r for r in modified.records if r.tool_code == br.tool_code), None)
        deltas.append(WhatIfDelta(
            tool_code=br.tool_code,
            baseline_stockout=br.stockout_day,
            modified_stockout=mr.stockout_day if mr else None,
            baseline_coverage=br.coverage_days,
            modified_coverage=mr.coverage_days if mr else br.coverage_days,
            baseline_planned_qty=br.total_planned_qty,
            modified_planned_qty=mr.total_planned_qty if mr else 0,
        ))

    # Include new tools in modified that don't exist in baseline
    baseline_tools = {br.tool_code for br in baseline.records}
    for mr in modified.records:
        if mr.tool_code not in baseline_tools:
            deltas.append(WhatIfDelta(
                tool_code=mr.tool_code,
                baseline_stockout=None,
                modified_stockout=mr.stockout_day,
                baseline_coverage=0,
                modified_coverage=mr.coverage_days,
                baseline_planned_qty=0,
                modified_planned_qty=mr.total_planned_qty,
            ))

    # RCCP deltas
    rccp_deltas: list[RCCPDelta] = []
    for be in baseline.rccp:
        me = next(
            (e for e in modified.rccp if e.machine == be.machine and e.day_index == be.day_index),
            None,
        )
        rccp_deltas.append(RCCPDelta(
            machine=be.machine,
            day_index=be.day_index,
            baseline_util=be.utilization,
            modified_util=me.utilization if me else 0,
        ))

    return WhatIfResult(
        baseline=baseline,
        modified=modified,
        deltas=deltas,
        rccp_deltas=rccp_deltas,
        summary_delta=SummaryDelta(
            stockouts_change=(
                modified.summary.tools_with_stockout - baseline.summary.tools_with_stockout
            ),
            avg_util_change=(
                modified.summary.avg_utilization - baseline.summary.avg_utilization
            ),
        ),
    )
