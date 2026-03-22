"""Nikufra ingest validators — data quality checks, fuzzy linking, stock projections, status assignment.

Extracted from ingest_service.py to keep the IngestService class lean.
"""

from __future__ import annotations

import logging
from typing import Any

from .schemas import (
    AlertCategory,
    AlertSeverity,
    MachineUtilization,
    NikufraAlert,
    NikufraMachineV2,
    NikufraOperationV2,
    NikufraStockProjection,
    OperationStatus,
    StockProjectionPoint,
)

logger = logging.getLogger(__name__)

# Daily production minutes (two shifts: X 06:00-14:00, Y 14:00-22:00)
DAILY_MINS = 960

# Minimum fuzzy match ratio for auto-linking
FUZZY_THRESHOLD = 90


def _fuzzy_match(a: str, b: str) -> int:
    """Fuzzy match ratio between two strings. Returns 0-100."""
    try:
        from thefuzz import fuzz

        return fuzz.ratio(a.upper().strip(), b.upper().strip())
    except ImportError:
        # Fallback: exact match
        return 100 if a.strip().upper() == b.strip().upper() else 0


def check_data_quality(
    tools: dict[str, dict[str, Any]],
    alerts: list[NikufraAlert],
) -> None:
    """Check tool data quality and append alerts."""
    for tool_id, tool_data in tools.items():
        rate = tool_data.get("pH", 0)
        if rate == 0 or rate is None:
            alerts.append(
                NikufraAlert(
                    severity=AlertSeverity.HIGH,
                    category=AlertCategory.DATA_QUALITY,
                    title=f"Tool {tool_id} has rate=0",
                    detail="Production rate is zero — this tool will produce no output.",
                    entity_id=tool_id,
                )
            )

        setup = tool_data.get("s", 0)
        if setup == 0 and tool_data.get("m"):
            alerts.append(
                NikufraAlert(
                    severity=AlertSeverity.LOW,
                    category=AlertCategory.DATA_QUALITY,
                    title=f"Tool {tool_id} has no setup time",
                    detail="Setup time is 0h — verify if this is correct.",
                    entity_id=tool_id,
                )
            )


def fuzzy_link_entities(
    isop: dict[str, Any],
    pp_data: Any,
    alerts: list[NikufraAlert],
) -> None:
    """Fuzzy-match PP entities against ISOP entities. Generate alerts for unlinked."""
    isop_machine_ids = set(isop.get("machines", {}).keys())
    pp_machine_ids = set()
    for mb in pp_data.machines:
        pp_machine_ids.add(mb.machine_id)

    for pp_id in pp_machine_ids:
        if pp_id in isop_machine_ids:
            continue

        # Try fuzzy match
        best_score = 0
        best_match = ""
        for isop_id in isop_machine_ids:
            score = _fuzzy_match(pp_id, isop_id)
            if score > best_score:
                best_score = score
                best_match = isop_id

        if best_score >= FUZZY_THRESHOLD:
            logger.info(
                f"Fuzzy-linked PP machine '{pp_id}' → ISOP '{best_match}' (score={best_score})"
            )
        else:
            alerts.append(
                NikufraAlert(
                    severity=AlertSeverity.MEDIUM,
                    category=AlertCategory.UNLINKED_ENTITY,
                    title=f"Unlinked machine: {pp_id}",
                    detail=f"PP machine '{pp_id}' has no match in ISOP data"
                    f" (best: '{best_match}' score={best_score}).",
                    entity_id=pp_id,
                )
            )


def compute_stock_projections(
    tools: list[dict[str, Any]],
    ops: list[dict[str, Any]],
    dates: list[str],
    alerts: list[NikufraAlert],
) -> list[NikufraStockProjection]:
    """Compute projected stock for each tool over the planning horizon."""
    projections = []

    for tool in tools:
        tool_id = tool.get("id", "")
        stk = tool.get("stk", 0)
        rate = tool.get("pH", 0)

        if stk <= 0 or rate <= 0:
            continue

        # Sum daily consumption for this tool
        daily_consumption = [0.0] * len(dates)
        for op in ops:
            if op.get("t") == tool_id:
                for i, qty in enumerate(op.get("d", [])):
                    if i < len(daily_consumption):
                        daily_consumption[i] += qty

        # Project stock
        points = []
        running_stock = float(stk)
        days_until_zero: int | None = None

        for i, date_label in enumerate(dates):
            running_stock -= daily_consumption[i]
            points.append(
                StockProjectionPoint(
                    day_offset=i,
                    date_label=date_label,
                    projected_stock=max(running_stock, 0.0),
                )
            )
            if running_stock <= 0 and days_until_zero is None:
                days_until_zero = i

        # Only include tools with meaningful production
        total_consumption = sum(daily_consumption)
        if total_consumption <= 0:
            continue

        proj = NikufraStockProjection(
            tool_code=tool_id,
            sku=tool.get("skus", [""])[0] if tool.get("skus") else "",
            current_stock=float(stk),
            projected=points,
            days_until_zero=days_until_zero,
        )
        projections.append(proj)

        # Alert if stock runs out within 2 days
        if days_until_zero is not None and days_until_zero <= 2:
            alerts.append(
                NikufraAlert(
                    severity=AlertSeverity.CRITICAL,
                    category=AlertCategory.STOCK_OUT,
                    title=f"Stock-out risk: {tool_id}",
                    detail=(
                        f"Tool {tool_id} projected to run out in "
                        f"{days_until_zero} day(s). Current: {stk}, "
                        f"daily consumption: ~{total_consumption / len(dates):.0f}."
                    ),
                    entity_id=tool_id,
                )
            )

    return projections


def assign_operation_status(
    ops: list[dict[str, Any]],
    down_machines: set,
) -> list[NikufraOperationV2]:
    """Assign status to each operation based on backlog and machine state."""
    typed = []
    for op in ops:
        status = OperationStatus.PLANNED
        if op.get("m") in down_machines:
            status = OperationStatus.BLOCKED
        elif op.get("atr", 0) > 0:
            status = OperationStatus.LATE

        typed.append(
            NikufraOperationV2(
                id=op["id"],
                m=op["m"],
                t=op["t"],
                sku=op["sku"],
                nm=op["nm"],
                pH=op["pH"],
                atr=op.get("atr", 0),
                d=op["d"],
                s=op["s"],
                op=op["op"],
                status=status,
            )
        )
    return typed


def build_typed_machines(
    machines: list[dict[str, Any]],
    ops: list[NikufraOperationV2],
    dates: list[str],
    down_machines: set,
) -> list[NikufraMachineV2]:
    """Build typed machines with utilization maps."""
    typed = []
    for m in machines:
        mid = m["id"]
        man = m.get("man", [0] * len(dates))
        util_map = []

        for i, date_label in enumerate(dates):
            man_val = man[i] if i < len(man) else 0
            util = min(man_val / DAILY_MINS, 1.0) if DAILY_MINS > 0 else 0.0
            ops_on_day = sum(1 for op in ops if op.m == mid and i < len(op.d) and op.d[i] > 0)
            util_map.append(
                MachineUtilization(
                    day_index=i,
                    date_label=date_label,
                    utilization=round(util, 3),
                    man_minutes=man_val,
                    ops_count=ops_on_day,
                )
            )

        typed.append(
            NikufraMachineV2(
                id=mid,
                area=m.get("area", ""),
                man=man,
                utilization_map=util_map,
            )
        )

    return typed


def compute_trust_index(
    tools: list[dict[str, Any]],
    ops: list[NikufraOperationV2],
    alerts: list[NikufraAlert],
) -> float:
    """Compute a simple trust index (0.0-1.0) based on data quality."""
    if not tools and not ops:
        return 0.0

    penalties = 0.0
    total_checks = 0

    for tool in tools:
        total_checks += 1
        if tool.get("pH", 0) == 0:
            penalties += 1.0
        if tool.get("s", 0) == 0 and tool.get("m"):
            penalties += 0.3
        if not tool.get("skus"):
            penalties += 0.5

    critical_alerts = sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL)
    penalties += critical_alerts * 2.0

    if total_checks == 0:
        return 1.0

    score = max(0.0, 1.0 - (penalties / (total_checks * 2)))
    return round(min(score, 1.0), 2)
