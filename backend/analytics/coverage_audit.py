"""Coverage Audit — Spec 12 §9.

Per-client coverage summary. Aggregates expedition + stock projection.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from backend.analytics.expedition import compute_expedition
from backend.analytics.stock_projection import compute_stock_projections
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData


@dataclass(slots=True)
class ClientCoverage:
    client: str
    total_orders: int
    covered_orders: int
    coverage_pct: float
    at_risk_orders: int
    avg_days_early: float
    worst_sku: str | None


@dataclass(slots=True)
class CoverageAudit:
    overall_coverage_pct: float
    overall_fill_rate: float
    clients: list[ClientCoverage]
    stockout_count: int
    health_score: int  # 0-100
    summary: str


def compute_coverage_audit(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
) -> CoverageAudit:
    """Aggregate expedition + stock projection into per-client coverage."""
    exp = compute_expedition(segments, lots, engine_data)
    projs = compute_stock_projections(segments, lots, engine_data)

    # Per-client expedition aggregation
    client_data: dict[str, dict] = defaultdict(
        lambda: {
            "total": 0,
            "ready": 0,
            "at_risk": 0,
            "worst_sku": None,
            "worst_cov": 100.0,
        }
    )

    for day in exp.days:
        for entry in day.entries:
            cd = client_data[entry.client]
            cd["total"] += 1
            if entry.status == "ready":
                cd["ready"] += 1
            if entry.coverage_pct < 100 and day.day_idx <= 5:
                cd["at_risk"] += 1
            if entry.coverage_pct < cd["worst_cov"]:
                cd["worst_cov"] = entry.coverage_pct
                cd["worst_sku"] = entry.sku

    # Build client coverages
    clients: list[ClientCoverage] = []
    total_all = 0
    ready_all = 0

    for client, cd in sorted(client_data.items()):
        total_all += cd["total"]
        ready_all += cd["ready"]
        cov_pct = (cd["ready"] / cd["total"] * 100) if cd["total"] > 0 else 100.0
        clients.append(
            ClientCoverage(
                client=client,
                total_orders=cd["total"],
                covered_orders=cd["ready"],
                coverage_pct=round(cov_pct, 1),
                at_risk_orders=cd["at_risk"],
                avg_days_early=0.0,  # could be computed from order_tracking
                worst_sku=cd["worst_sku"],
            )
        )

    overall_cov = (ready_all / total_all * 100) if total_all > 0 else 100.0

    # Stockout count from projections
    stockout_count = sum(1 for p in projs if p.stockout_day is not None)

    # Health score: weighted coverage + stockout penalty
    stockout_penalty = min(stockout_count * 5, 30)
    health = max(0, round(overall_cov - stockout_penalty))

    # Summary
    if health >= 90:
        summary = (
            f"Cobertura excelente: {overall_cov:.0f}%. {total_all} encomendas, {ready_all} prontas."
        )
    elif health >= 70:
        at_risk = sum(c.at_risk_orders for c in clients)
        summary = f"Cobertura boa ({overall_cov:.0f}%) mas {at_risk} encomendas em risco."
    else:
        worst = min(clients, key=lambda c: c.coverage_pct) if clients else None
        worst_summary = f"Cliente {worst.client} com {round(worst.coverage_pct)}%." if worst else ""
        summary = f"Cobertura insuficiente: {overall_cov:.0f}%. {worst_summary}"

    return CoverageAudit(
        overall_coverage_pct=round(overall_cov, 1),
        overall_fill_rate=exp.fill_rate,
        clients=clients,
        stockout_count=stockout_count,
        health_score=health,
        summary=summary,
    )
