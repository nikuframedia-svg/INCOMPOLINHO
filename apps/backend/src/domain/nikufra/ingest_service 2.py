# Nikufra Ingest Service — "Data Fusion Engine"
# Upgrades the basic _combine() with fuzzy entity linking, stock projections,
# data quality alerts, and operation status assignment.

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import generate_fallback_dates
from .schemas import (
    AlertCategory,
    AlertSeverity,
    MachineUtilization,
    NikufraAlert,
    NikufraDashboardState,
    NikufraHistoryEventV2,
    NikufraMachineV2,
    NikufraOperationV2,
    NikufraStockProjection,
    NikufraToolV2,
    OperationStatus,
    StockProjectionPoint,
)

logger = logging.getLogger(__name__)

# Daily production minutes (two shifts: X 06:00-14:00, Y 14:00-22:00)
DAILY_MINS = 960

# Minimum fuzzy match ratio for auto-linking
FUZZY_THRESHOLD = 90


def _compute_header_hash(xlsx_path: Path) -> str:
    """Compute SHA-256 of the ISOP header row for template change detection."""
    try:
        import openpyxl

        wb = openpyxl.load_workbook(str(xlsx_path), data_only=True, read_only=True)
        ws = wb["Planilha1"]
        header_row = []
        for cell in ws[7]:
            header_row.append(str(cell.value) if cell.value else "")
        wb.close()
        header_str = "|".join(header_row)
        return hashlib.sha256(header_str.encode()).hexdigest()
    except Exception as e:
        logger.warning(f"Could not compute header hash: {e}")
        return ""


def _fuzzy_match(a: str, b: str) -> int:
    """Fuzzy match ratio between two strings. Returns 0-100."""
    try:
        from thefuzz import fuzz

        return fuzz.ratio(a.upper().strip(), b.upper().strip())
    except ImportError:
        # Fallback: exact match
        return 100 if a.strip().upper() == b.strip().upper() else 0


class IngestService:
    """Fusion engine that builds a rich NikufraDashboardState from raw parsed data.

    Features:
    - Header hash change detection
    - Fuzzy entity linking (ISOP ↔ PP entities)
    - Stock projection with days-until-zero
    - Data quality alerts
    - Operation status assignment
    """

    def __init__(self, known_header_hash: str | None = None):
        self._known_header_hash = known_header_hash
        self._alerts: list[NikufraAlert] = []

    def build_dashboard_state(
        self,
        isop: dict[str, Any],
        pp_data: Any | None,
        xlsx_path: Path | None = None,
        history: list[dict[str, Any]] | None = None,
        down_machines: list[str] | None = None,
    ) -> NikufraDashboardState:
        """Build the full V2 dashboard state from parsed ISOP + PP data."""
        self._alerts = []
        down_set = set(down_machines or [])

        # A. Header hash change detection
        if xlsx_path and self._known_header_hash:
            current_hash = _compute_header_hash(xlsx_path)
            if current_hash and current_hash != self._known_header_hash:
                self._alerts.append(
                    NikufraAlert(
                        severity=AlertSeverity.HIGH,
                        category=AlertCategory.TEMPLATE_CHANGE,
                        title="ISOP template changed",
                        detail="Header row hash mismatch — data mapping may be incorrect.",
                    )
                )

        # B. Entity extraction with quality flags
        tools_raw = isop.get("tools", {})
        self._check_data_quality(tools_raw)

        # Build base data (same as original _combine logic)
        dates, days_label, mo, machines_list, ops_list, machine_area_map = self._build_base_data(
            isop, pp_data
        )

        # C. Fuzzy entity linking
        if pp_data:
            self._fuzzy_link_entities(isop, pp_data)

        # D. Stock projections
        tools_list = list(tools_raw.values())
        stock_projections = self._compute_stock_projections(tools_list, ops_list, dates)

        # E. Operation status assignment
        typed_ops = self._assign_operation_status(ops_list, down_set)

        # Build machine utilization maps
        typed_machines = self._build_typed_machines(machines_list, typed_ops, dates, down_set)

        # Build typed tools
        typed_tools = [NikufraToolV2(**t) for t in tools_list]

        # Build history
        typed_history = [NikufraHistoryEventV2(**h) for h in (history or self._default_history())]

        # Compute data hash
        content_for_hash = json.dumps(
            {"dates": dates, "ops": len(typed_ops), "tools": len(typed_tools)},
            sort_keys=True,
        )
        data_hash = hashlib.sha256(content_for_hash.encode()).hexdigest()[:16]

        # Compute trust index
        trust_index = self._compute_trust_index(tools_list, typed_ops)

        return NikufraDashboardState(
            dates=dates,
            days_label=days_label,
            mo=mo,
            machines=typed_machines,
            tools=typed_tools,
            operations=typed_ops,
            history=typed_history,
            alerts=self._alerts,
            stock_projections=stock_projections,
            data_hash=data_hash,
            parsed_at=datetime.utcnow().isoformat() + "Z",
            trust_index=trust_index,
        )

    def _check_data_quality(self, tools: dict[str, dict[str, Any]]) -> None:
        """Check tool data quality and generate alerts."""
        for tool_id, tool_data in tools.items():
            rate = tool_data.get("pH", 0)
            if rate == 0 or rate is None:
                self._alerts.append(
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
                self._alerts.append(
                    NikufraAlert(
                        severity=AlertSeverity.LOW,
                        category=AlertCategory.DATA_QUALITY,
                        title=f"Tool {tool_id} has no setup time",
                        detail="Setup time is 0h — verify if this is correct.",
                        entity_id=tool_id,
                    )
                )

    def _build_base_data(
        self,
        isop: dict[str, Any],
        pp_data: Any | None,
    ) -> tuple[
        list[str],
        list[str],
        dict[str, list[float]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, str],
    ]:
        """Build base data arrays (mirrors original _combine logic)."""
        dates, days_label = generate_fallback_dates()
        mo: dict[str, list[float]] = {"PG1": [0.0] * 8, "PG2": [0.0] * 8}

        machines_list: list[dict[str, Any]] = []
        ops_list: list[dict[str, Any]] = []
        machine_area_map: dict[str, str] = {}

        if pp_data:
            dates = pp_data.dates or dates
            days_label = pp_data.days_label or days_label
            mo = pp_data.mo_load if pp_data.mo_load else mo

            for mb in pp_data.machines:
                machines_list.append(
                    {
                        "id": mb.machine_id,
                        "area": mb.area,
                        "man": mb.man_minutes,
                    }
                )
                machine_area_map[mb.machine_id] = mb.area

                for op in mb.operations:
                    isop_tool = isop["tools"].get(op.tool_code, {})
                    setup_h = isop_tool.get("s", 0) if isop_tool else 0
                    if op.setup_hours > 0:
                        setup_h = op.setup_hours

                    ops_list.append(
                        {
                            "id": f"OP{len(ops_list) + 1:02d}",
                            "m": op.machine,
                            "t": op.tool_code,
                            "sku": op.sku,
                            "nm": op.name,
                            "pH": op.pcs_per_hour or isop_tool.get("pH", 0),
                            "atr": op.atraso,
                            "d": op.daily_qty,
                            "s": setup_h,
                            "op": op.operators or isop_tool.get("op", 1),
                        }
                    )

            # Update tool stock from PP data
            for op in pp_data.all_operations:
                if op.tool_code in isop["tools"] and op.stock > 0:
                    isop["tools"][op.tool_code]["stk"] = op.stock

        if not machines_list:
            for mid, mdata in isop.get("machines", {}).items():
                machines_list.append(mdata)

        for m in machines_list:
            if m["id"] in machine_area_map:
                m["area"] = machine_area_map[m["id"]]

        return dates, days_label, mo, machines_list, ops_list, machine_area_map

    def _fuzzy_link_entities(self, isop: dict[str, Any], pp_data: Any) -> None:
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
                self._alerts.append(
                    NikufraAlert(
                        severity=AlertSeverity.MEDIUM,
                        category=AlertCategory.UNLINKED_ENTITY,
                        title=f"Unlinked machine: {pp_id}",
                        detail=f"PP machine '{pp_id}' has no match in ISOP data"
                        f" (best: '{best_match}' score={best_score}).",
                        entity_id=pp_id,
                    )
                )

    def _compute_stock_projections(
        self,
        tools: list[dict[str, Any]],
        ops: list[dict[str, Any]],
        dates: list[str],
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
                self._alerts.append(
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

    def _assign_operation_status(
        self,
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

    def _build_typed_machines(
        self,
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

    def _compute_trust_index(
        self,
        tools: list[dict[str, Any]],
        ops: list[NikufraOperationV2],
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

        critical_alerts = sum(1 for a in self._alerts if a.severity == AlertSeverity.CRITICAL)
        penalties += critical_alerts * 2.0

        if total_checks == 0:
            return 1.0

        score = max(0.0, 1.0 - (penalties / (total_checks * 2)))
        return round(min(score, 1.0), 2)

    @staticmethod
    def _default_history() -> list[dict[str, Any]]:
        """Static sample history (same as original service.py)."""
        return [
            {
                "dt": "01/02",
                "type": "machine_down",
                "mach": "PRM039",
                "tool": "BFP092",
                "action": "BFP092 \u2192 PRM043",
                "result": "Retomada 45min",
                "roi": "\u2014",
            },
            {
                "dt": "30/01",
                "type": "maintenance",
                "mach": "PRM031",
                "tool": "BFP079",
                "action": "Manuten\u00e7\u00e3o preventiva",
                "result": "Sem impacto",
                "roi": "\u2014",
            },
            {
                "dt": "28/01",
                "type": "urgent_order",
                "mach": "PRM019",
                "tool": "BFP080",
                "action": "Resequenciamento",
                "result": "OTD 100%",
                "roi": "\u2014",
            },
            {
                "dt": "27/01",
                "type": "operator",
                "mach": "PRM043",
                "tool": "BFP172",
                "action": "Pool Y reassignado",
                "result": "Delay 30min T1",
                "roi": "\u2014",
            },
            {
                "dt": "25/01",
                "type": "machine_down",
                "mach": "PRM031",
                "tool": "BFP114",
                "action": "BFP114 \u2192 PRM039",
                "result": "Setup +1.25h ok",
                "roi": "\u2014",
            },
            {
                "dt": "23/01",
                "type": "machine_down",
                "mach": "PRM039",
                "tool": "BFP178",
                "action": "BFP178 \u2192 PRM043",
                "result": "Sem impacto",
                "roi": "\u2014",
            },
            {
                "dt": "20/01",
                "type": "maintenance",
                "mach": "PRM043",
                "tool": "BFP202",
                "action": "Corretiva 2h",
                "result": "Sem alt. dispo.",
                "roi": "\u2014",
            },
        ]
