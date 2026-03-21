"""Action Messages & Summary — port of mrp/mrp-actions.ts.

Generates prioritized action messages from MRP results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..types import EngineData
from .mrp_engine import MRPResult

ActionSeverity = Literal["critical", "high", "medium", "low"]


@dataclass
class ActionImpact:
    qty_affected: int = 0
    days_affected: int = 0
    capacity_minutes: int | None = None


@dataclass
class ActionMessage:
    id: str
    type: str
    severity: str
    severity_score: int = 0
    tool_code: str = ""
    machine: str = ""
    day_index: int | None = None
    sku: str | None = None
    sku_name: str | None = None
    title: str = ""
    description: str = ""
    suggested_action: str = ""
    impact: ActionImpact = field(default_factory=ActionImpact)


@dataclass
class ActionMessagesSummary:
    messages: list[ActionMessage] = field(default_factory=list)
    by_severity: dict[str, int] = field(
        default_factory=lambda: {"critical": 0, "high": 0, "medium": 0, "low": 0}
    )
    by_type: dict[str, int] = field(default_factory=dict)
    critical_count: int = 0


def _fmt_q(n: int) -> str:
    if n == 0:
        return "0"
    if n >= 10000:
        return f"{round(n / 1000)}K"
    if n >= 1000:
        return f"{n / 1000:.1f}K"
    return str(n)


def _severity_score(
    msg_type: str,
    coverage_days: float,
    qty: int,
    has_alt: bool,
) -> int:
    type_weight = {
        "stockout": 1.0,
        "overload": 0.8,
        "low_coverage": 0.5,
        "no_alt": 0.3,
    }.get(msg_type, 0.3)
    coverage_factor = min(1, max(0, (3 - coverage_days) / 3))
    qty_factor = min(1, qty / 40000)
    alt_factor = 0 if has_alt else 1
    return round(type_weight * 30 + coverage_factor * 25 + qty_factor * 25 + alt_factor * 20)


def _score_to_severity(score: int) -> str:
    if score >= 70:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def compute_action_messages(
    mrp: MRPResult,
    engine: EngineData,
    coverage_days_threshold: int = 3,
) -> ActionMessagesSummary:
    """Generate prioritized action messages from MRP results."""
    num_days = len(engine.dates)
    messages: list[ActionMessage] = []
    id_counter = 0

    for rec in mrp.records:
        has_alt = rec.alt_machine is not None and rec.alt_machine != "" and rec.alt_machine != "-"

        # Type 1: Stockout → launch POR (per-SKU)
        for sr in rec.sku_records:
            if sr.stockout_day is not None:
                sku_planned_qty = sum(b.planned_order_receipt for b in sr.buckets)
                por_day = max(0, sr.stockout_day - rec.lead_days)
                score = _severity_score("stockout", sr.coverage_days, sku_planned_qty, has_alt)
                id_counter += 1
                messages.append(ActionMessage(
                    id=f"ACT-{id_counter}",
                    type="launch_por",
                    severity=_score_to_severity(score),
                    severity_score=score,
                    tool_code=rec.tool_code,
                    machine=rec.machine,
                    day_index=sr.stockout_day,
                    sku=sr.sku,
                    sku_name=sr.name,
                    title=f"Lancar POR de {_fmt_q(sku_planned_qty)} pcs ({sr.sku})",
                    description=(
                        f"{sr.sku} {sr.name} ({rec.tool_code}/{rec.machine}): "
                        f"stockout dia {sr.stockout_day}. Stock {_fmt_q(sr.stock)}, "
                        f"backlog {_fmt_q(sr.backlog)}."
                    ),
                    suggested_action=(
                        f"Lancar POR de {_fmt_q(sku_planned_qty)} pcs para {sr.sku} -- "
                        f"release dia {por_day}"
                    ),
                    impact=ActionImpact(
                        qty_affected=sku_planned_qty,
                        days_affected=num_days - sr.stockout_day,
                        capacity_minutes=round(
                            (sku_planned_qty / max(1, getattr(rec, "rate_per_hour", 100))) * 60
                        ),
                    ),
                ))

        # Type 2: Low coverage (per-SKU)
        for sr in rec.sku_records:
            gross = sum(b.gross_requirement for b in sr.buckets)
            if sr.coverage_days < coverage_days_threshold and gross > 0 and sr.stockout_day is None:
                score = _severity_score("low_coverage", sr.coverage_days, gross, has_alt)
                id_counter += 1
                messages.append(ActionMessage(
                    id=f"ACT-{id_counter}",
                    type="advance_prod",
                    severity=_score_to_severity(score),
                    severity_score=score,
                    tool_code=rec.tool_code,
                    machine=rec.machine,
                    sku=sr.sku,
                    sku_name=sr.name,
                    title=f"Cobertura apenas {sr.coverage_days:.1f} dias ({sr.sku})",
                    description=(
                        f"{sr.sku} {sr.name} ({rec.tool_code}/{rec.machine}): "
                        f"stock {_fmt_q(sr.stock)} cobre apenas {sr.coverage_days:.1f} dias."
                    ),
                    suggested_action=(
                        f"Antecipar producao de {sr.sku} -- stock actual cobre "
                        f"{sr.coverage_days:.1f} dias vs necessidade de {num_days} dias"
                    ),
                    impact=ActionImpact(
                        qty_affected=gross,
                        days_affected=max(1, round(sr.coverage_days)),
                    ),
                ))

        # Type 3: No alternative machine risk
        total_gross = sum(b.gross_requirement for b in rec.buckets)
        if not has_alt and total_gross > 0:
            score = _severity_score("no_alt", rec.coverage_days, total_gross, False)
            id_counter += 1
            messages.append(ActionMessage(
                id=f"ACT-{id_counter}",
                type="no_alt_risk",
                severity=_score_to_severity(score),
                severity_score=score,
                tool_code=rec.tool_code,
                machine=rec.machine,
                title="Sem maquina alternativa",
                description=(
                    f"{rec.tool_code} ({rec.machine}): sem alternativa. "
                    f"Se {rec.machine} avariar, producao de {_fmt_q(total_gross)} pcs para."
                ),
                suggested_action=(
                    f"Avaliar routing alternativo para {rec.tool_code} ou criar buffer de stock"
                ),
                impact=ActionImpact(qty_affected=total_gross, days_affected=num_days),
            ))

    # Type 4: Overload → transfer tool
    for entry in mrp.rccp:
        if not entry.overloaded:
            continue
        for tool_code in entry.planned_tools:
            rec = next((r for r in mrp.records if r.tool_code == tool_code), None)
            if not rec:
                continue
            total_planned = sum(b.planned_order_receipt for b in rec.buckets)
            has_alt = rec.alt_machine is not None and rec.alt_machine != "" and rec.alt_machine != "-"
            if has_alt:
                tool_prod_min = round((total_planned / max(1, getattr(rec, "rate_per_hour", 100))) * 60)
                score = _severity_score("overload", rec.coverage_days, total_planned, True)
                id_counter += 1
                messages.append(ActionMessage(
                    id=f"ACT-{id_counter}",
                    type="transfer_tool",
                    severity=_score_to_severity(score),
                    severity_score=score,
                    tool_code=tool_code,
                    machine=entry.machine,
                    day_index=entry.day_index,
                    title=f"Transferir {tool_code} para {rec.alt_machine}",
                    description=(
                        f"{entry.machine} dia {entry.day_index}: "
                        f"sobrecarga {entry.utilization * 100:.0f}%. "
                        f"Transferir {tool_code} para {rec.alt_machine} liberta ~{tool_prod_min}min."
                    ),
                    suggested_action=(
                        f"Mover {tool_code} de {entry.machine} para {rec.alt_machine} "
                        f"no dia {entry.day_index}"
                    ),
                    impact=ActionImpact(
                        qty_affected=total_planned,
                        days_affected=1,
                        capacity_minutes=tool_prod_min,
                    ),
                ))
            else:
                score = _severity_score("no_alt", rec.coverage_days, total_planned, False)
                id_counter += 1
                messages.append(ActionMessage(
                    id=f"ACT-{id_counter}",
                    type="no_alt_risk",
                    severity=_score_to_severity(score),
                    severity_score=score,
                    tool_code=tool_code,
                    machine=entry.machine,
                    day_index=entry.day_index,
                    title=f"{tool_code} sobrecarregado sem alternativa",
                    description=(
                        f"{entry.machine} dia {entry.day_index}: "
                        f"sobrecarga {entry.utilization * 100:.0f}%. "
                        f"Ferramenta {tool_code} sem maquina alternativa."
                    ),
                    suggested_action=(
                        f"Avaliar overtime ou redistribuicao de carga para "
                        f"{entry.machine} no dia {entry.day_index}"
                    ),
                    impact=ActionImpact(qty_affected=total_planned, days_affected=1),
                ))

    messages.sort(key=lambda m: m.severity_score, reverse=True)

    by_severity: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    by_type: dict[str, int] = {}
    for m in messages:
        by_severity[m.severity] = by_severity.get(m.severity, 0) + 1
        by_type[m.type] = by_type.get(m.type, 0) + 1

    return ActionMessagesSummary(
        messages=messages,
        by_severity=by_severity,
        by_type=by_type,
        critical_count=by_severity.get("critical", 0),
    )
