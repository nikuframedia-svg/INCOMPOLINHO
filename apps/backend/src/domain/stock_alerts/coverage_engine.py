"""Coverage-based alerts engine.

Computes stock alerts from ISOP data:
  ATRASO: refs with negative atraso — delivery failure ALREADY HAPPENED
  RED:    refs missing to cover orders for TOMORROW
  YELLOW: refs missing to cover orders within 2-3 DAYS
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel


class CoverageAlert(BaseModel):
    sku: str
    client: str
    designation: str
    severity: Literal["atraso", "red", "yellow"]
    shortage_qty: int
    shortage_date: date
    machine: str
    message: str
    coverage_days: int


_SEVERITY_ORDER = {"atraso": 0, "red": 1, "yellow": 2}


def _classify_severity(
    atraso: int,
    stockout_date: date,
    today: date,
) -> Literal["atraso", "red", "yellow"] | None:
    if atraso < 0:
        return "atraso"
    if stockout_date <= today + timedelta(days=1):
        return "red"
    if stockout_date <= today + timedelta(days=3):
        return "yellow"
    return None


def _build_message(
    severity: Literal["atraso", "red", "yellow"],
    sku_code: str,
    designation: str,
    shortage_qty: int,
    shortage_date: date,
) -> str:
    if severity == "atraso":
        return f"ATRASO: {designation} \u2014 falha de entrega. Faltam {shortage_qty} pe\u00e7as."
    if severity == "red":
        return f"Faltam {shortage_qty} pe\u00e7as da ref {sku_code} para cobrir pedidos de amanh\u00e3."
    formatted = shortage_date.strftime("%d/%m")
    return f"Faltam {shortage_qty} pe\u00e7as da ref {sku_code} para cobrir pedidos de {formatted}."


def _compute_sku_alert(sku: dict[str, Any], today: date) -> CoverageAlert | None:
    """Compute alert for a single SKU dict."""
    orders = sorted(sku.get("orders", []), key=lambda o: o.get("deadline", today))
    atraso = sku.get("atraso", 0)
    clients = sku.get("clients", [])
    client_str = ", ".join(clients) if clients else ""
    designation = sku.get("designation", "")
    machine = sku.get("machine", "")
    sku_code = sku.get("sku", "")

    if not orders:
        if atraso < 0:
            return CoverageAlert(
                sku=sku_code,
                client=client_str,
                designation=designation,
                severity="atraso",
                shortage_qty=abs(atraso),
                shortage_date=today,
                machine=machine,
                message=_build_message("atraso", sku_code, designation, abs(atraso), today),
                coverage_days=0,
            )
        return None

    stock_available = sku.get("stock", 0)
    stockout_date = None
    shortage_qty = 0

    for order in orders:
        qty = order.get("qty", 0)
        deadline = order.get("deadline", today)
        if isinstance(deadline, str):
            deadline = date.fromisoformat(deadline)
        stock_available -= qty
        if stock_available < 0:
            stockout_date = deadline
            shortage_qty = abs(stock_available)
            break

    if stockout_date is None:
        if atraso < 0:
            return CoverageAlert(
                sku=sku_code,
                client=client_str,
                designation=designation,
                severity="atraso",
                shortage_qty=abs(atraso),
                shortage_date=today,
                machine=machine,
                message=_build_message("atraso", sku_code, designation, abs(atraso), today),
                coverage_days=0,
            )
        return None

    coverage_days = max((stockout_date - today).days, 0)
    severity = _classify_severity(atraso, stockout_date, today)
    if severity is None:
        return None

    message = _build_message(severity, sku_code, designation, shortage_qty, stockout_date)
    return CoverageAlert(
        sku=sku_code,
        client=client_str,
        designation=designation,
        severity=severity,
        shortage_qty=shortage_qty,
        shortage_date=stockout_date,
        machine=machine,
        message=message,
        coverage_days=coverage_days,
    )


def compute_coverage_alerts(
    skus: dict[str, dict[str, Any]],
    today: date | None = None,
) -> list[CoverageAlert]:
    """Compute all coverage alerts from SKU data.

    Args:
        skus: dict of SKU code -> SKU data (with orders, stock, atraso, etc.)
        today: reference date (defaults to today)

    Returns alerts sorted: atraso first, then red, then yellow.
    """
    if today is None:
        today = date.today()

    alerts: list[CoverageAlert] = []
    for sku_data in skus.values():
        alert = _compute_sku_alert(sku_data, today)
        if alert is not None:
            alerts.append(alert)

    alerts.sort(key=lambda a: (_SEVERITY_ORDER[a.severity], -a.shortage_qty))
    return alerts
