"""Risk Grid — unified 3-dimensional risk map.

Port of risk/risk-grid.ts.
Computes capacity, stock, and constraint risk per machine/tool per day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..constants import (
    DAY_CAP,
    RISK_CRITICAL_THRESHOLD,
    RISK_HIGH_THRESHOLD,
    RISK_MEDIUM_THRESHOLD,
)


@dataclass
class RiskCell:
    row_id: str
    day_idx: int
    level: str  # "critical" | "high" | "medium" | "low"
    tooltip: str
    entity_type: str  # "machine" | "tool" | "constraint"


@dataclass
class RiskRow:
    id: str
    label: str
    entity_type: str
    cells: list[RiskCell] = field(default_factory=list)


@dataclass
class RiskSummary:
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0


@dataclass
class RiskGridData:
    rows: list[RiskRow] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    dnames: list[str] = field(default_factory=list)
    summary: RiskSummary = field(default_factory=RiskSummary)


def compute_risk_grid(
    engine_data: Any,
    cap: dict[str, list[dict]] | None = None,
    validation: dict | None = None,
    mrp: Any | None = None,
) -> RiskGridData:
    """Compute a unified risk grid across capacity, stock, and constraints.

    Args:
        engine_data: EngineData with machines, dates, dnames
        cap: Capacity analysis {machine_id: [{util, load_min, cap_min}, ...]}
        validation: Validation report with violations
        mrp: MRPResult with tool-level stock projections
    """
    dates = engine_data.dates or []
    dnames = engine_data.dnames or []
    n_days = len(dates)
    rows: list[RiskRow] = []
    summary = RiskSummary()

    # 1. Capacity rows (1 per machine)
    if cap:
        for machine in engine_data.machines:
            mid = machine.id
            day_loads = cap.get(mid, [])
            row = RiskRow(id=f"cap_{mid}", label=mid, entity_type="machine")

            for d_idx in range(n_days):
                if d_idx < len(day_loads):
                    dl = day_loads[d_idx]
                    util = dl.get("util", 0) if isinstance(dl, dict) else 0
                else:
                    util = 0

                level = _util_to_level(util)
                if level != "low":
                    cell = RiskCell(
                        row_id=row.id,
                        day_idx=d_idx,
                        level=level,
                        tooltip=f"{mid} D{d_idx}: {util:.0%} utilization",
                        entity_type="machine",
                    )
                    row.cells.append(cell)
                    _inc_summary(summary, level)

            if row.cells:
                rows.append(row)

    # 2. Stock rows (tools with MRP stockout risk)
    if mrp is not None:
        tools_data = getattr(mrp, "tools", {})
        if isinstance(tools_data, dict):
            for tool_code, tool_mrp in tools_data.items():
                projections = getattr(tool_mrp, "projected_available", None)
                if projections is None and isinstance(tool_mrp, dict):
                    projections = tool_mrp.get("projected_available", [])
                if not projections:
                    continue

                row = RiskRow(id=f"stk_{tool_code}", label=tool_code, entity_type="tool")

                for d_idx, pa in enumerate(projections):
                    if d_idx >= n_days:
                        break
                    pa_val = pa if isinstance(pa, (int, float)) else 0

                    if pa_val < 0:
                        level = "critical"
                    elif pa_val == 0:
                        level = "high"
                    else:
                        level = "low"

                    if level != "low":
                        cell = RiskCell(
                            row_id=row.id,
                            day_idx=d_idx,
                            level=level,
                            tooltip=f"{tool_code} D{d_idx}: PA={pa_val}",
                            entity_type="tool",
                        )
                        row.cells.append(cell)
                        _inc_summary(summary, level)

                if row.cells:
                    rows.append(row)

    # 3. Constraint violation rows
    if validation:
        violations = validation.get("violations", [])
        # Group by machine
        machine_violations: dict[str, list[dict]] = {}
        for v in violations:
            mid = v.get("machine_id", v.get("machineId", "unknown"))
            machine_violations.setdefault(mid, []).append(v)

        for mid, vlist in machine_violations.items():
            row = RiskRow(id=f"cst_{mid}", label=f"{mid} constraints", entity_type="constraint")

            for v in vlist:
                d_idx = v.get("day_idx", v.get("dayIdx", 0))
                severity = v.get("severity", "medium")
                level = "critical" if severity == "critical" else (
                    "high" if severity == "high" else "medium"
                )
                cell = RiskCell(
                    row_id=row.id,
                    day_idx=d_idx,
                    level=level,
                    tooltip=v.get("detail", v.get("message", "Constraint violation")),
                    entity_type="constraint",
                )
                row.cells.append(cell)
                _inc_summary(summary, level)

            if row.cells:
                rows.append(row)

    return RiskGridData(rows=rows, dates=dates, dnames=dnames, summary=summary)


def _util_to_level(util: float) -> str:
    if util > RISK_CRITICAL_THRESHOLD:
        return "critical"
    if util > RISK_HIGH_THRESHOLD:
        return "high"
    if util > RISK_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def _inc_summary(summary: RiskSummary, level: str) -> None:
    if level == "critical":
        summary.critical_count += 1
    elif level == "high":
        summary.high_count += 1
    elif level == "medium":
        summary.medium_count += 1
