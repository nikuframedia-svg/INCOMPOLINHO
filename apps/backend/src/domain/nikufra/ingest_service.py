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
from .ingest_validators import (
    _fuzzy_match,
    assign_operation_status,
    build_typed_machines,
    check_data_quality,
    compute_stock_projections,
    compute_trust_index,
    fuzzy_link_entities,
)
from .schemas import (
    AlertCategory,
    AlertSeverity,
    NikufraAlert,
    NikufraDashboardState,
    NikufraHistoryEventV2,
    NikufraToolV2,
)

# Re-export for backward compatibility (used by tests)
_fuzzy_match = _fuzzy_match  # noqa: F811

logger = logging.getLogger(__name__)


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
        check_data_quality(tools_raw, self._alerts)

        # Build base data (same as original _combine logic)
        dates, days_label, mo, machines_list, ops_list, machine_area_map = self._build_base_data(
            isop, pp_data
        )

        # C. Fuzzy entity linking
        if pp_data:
            fuzzy_link_entities(isop, pp_data, self._alerts)

        # D. Stock projections
        tools_list = list(tools_raw.values())
        stock_projections = compute_stock_projections(tools_list, ops_list, dates, self._alerts)

        # E. Operation status assignment
        typed_ops = assign_operation_status(ops_list, down_set)

        # Build machine utilization maps
        typed_machines = build_typed_machines(machines_list, typed_ops, dates, down_set)

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
        trust_index = compute_trust_index(tools_list, typed_ops, self._alerts)

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

    # Backward-compatible private method aliases (delegate to module functions)
    def _check_data_quality(self, tools: dict[str, dict[str, Any]]) -> None:
        check_data_quality(tools, self._alerts)

    def _assign_operation_status(self, ops: list[dict[str, Any]], down_machines: set) -> list:
        return assign_operation_status(ops, down_machines)

    def _build_typed_machines(
        self, machines: list, ops: list, dates: list, down_machines: set
    ) -> list:
        return build_typed_machines(machines, ops, dates, down_machines)

    def _compute_trust_index(self, tools: list, ops: list) -> float:
        return compute_trust_index(tools, ops, self._alerts)

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
