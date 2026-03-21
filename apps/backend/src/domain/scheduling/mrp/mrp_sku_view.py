"""MRP SKU View — port of mrp/mrp-sku-view.ts.

Flattens tool-centric MRPResult into SKU-primary view.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .mrp_engine import MRPResult


@dataclass
class MRPSkuViewRecord:
    sku: str
    name: str = ""
    op_id: str = ""
    tool_code: str = ""
    machine: str = ""
    alt_machine: str = ""
    customer: str = ""
    customer_name: str = ""
    twin: str = ""
    is_twin: bool = False
    current_stock: int = 0
    wip: int = 0
    backlog: int = 0
    gross_requirement: int = 0
    projected_end: int = 0
    stockout_day: int | None = None
    coverage_days: float = 0
    buckets: list[dict] = field(default_factory=list)
    rate_per_hour: int = 0
    setup_hours: float = 0
    lot_economic_qty: int = 0


@dataclass
class MRPSkuSummary:
    total_skus: int = 0
    skus_with_backlog: int = 0
    skus_with_stockout: int = 0
    total_gross_req: int = 0
    total_planned_qty: int = 0


@dataclass
class MRPSkuViewResult:
    sku_records: list[MRPSkuViewRecord] = field(default_factory=list)
    summary: MRPSkuSummary = field(default_factory=MRPSkuSummary)


def compute_mrp_sku_view(mrp: MRPResult) -> MRPSkuViewResult:
    """Transform tool-centric MRPResult into a flat SKU-primary view."""
    sku_records: list[MRPSkuViewRecord] = []

    for rec in mrp.records:
        for sr in rec.sku_records:
            buckets_dicts = [
                {
                    "dayIndex": b.day_index,
                    "dateLabel": b.date_label,
                    "grossRequirement": b.gross_requirement,
                    "scheduledReceipts": b.scheduled_receipts,
                    "projectedAvailable": b.projected_available,
                    "netRequirement": b.net_requirement,
                    "plannedOrderReceipt": b.planned_order_receipt,
                    "plannedOrderRelease": b.planned_order_release,
                }
                for b in sr.buckets
            ]
            sku_records.append(MRPSkuViewRecord(
                sku=sr.sku,
                name=sr.name,
                op_id=sr.op_id,
                tool_code=sr.tool_code,
                machine=sr.machine,
                alt_machine=sr.alt_machine,
                customer=sr.customer,
                twin=sr.twin,
                is_twin=bool(sr.twin),
                current_stock=sr.stock,
                wip=sr.wip,
                backlog=sr.backlog,
                gross_requirement=sum(b.gross_requirement for b in sr.buckets),
                projected_end=sr.buckets[-1].projected_available if sr.buckets else 0,
                stockout_day=sr.stockout_day,
                coverage_days=sr.coverage_days,
                buckets=buckets_dicts,
                rate_per_hour=rec.sku_records[0].buckets[0].gross_requirement if False else 0,
                setup_hours=0,
                lot_economic_qty=0,
            ))

    # Fix rate/setup/lot from parent record
    rec_idx = 0
    for rec in mrp.records:
        for _sr in rec.sku_records:
            if rec_idx < len(sku_records):
                # These come from the tool-level MRPRecord
                sku_records[rec_idx].rate_per_hour = getattr(rec, "rate_per_hour", 0)
                sku_records[rec_idx].setup_hours = getattr(rec, "setup_hours", 0)
                sku_records[rec_idx].lot_economic_qty = getattr(rec, "lot_economic_qty", 0)
            rec_idx += 1

    summary = MRPSkuSummary(
        total_skus=len(sku_records),
        skus_with_backlog=sum(1 for r in sku_records if r.backlog > 0),
        skus_with_stockout=sum(1 for r in sku_records if r.stockout_day is not None),
        total_gross_req=sum(r.gross_requirement for r in sku_records),
        total_planned_qty=sum(
            sum(b.get("plannedOrderReceipt", 0) for b in r.buckets)
            for r in sku_records
        ),
    )

    return MRPSkuViewResult(sku_records=sku_records, summary=summary)
