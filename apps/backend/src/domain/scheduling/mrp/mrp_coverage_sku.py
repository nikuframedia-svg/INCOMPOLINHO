"""Per-SKU Coverage Matrix — port of mrp/mrp-coverage-sku.ts.

Computes coverage matrix with SKU rows (instead of tool rows).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..types import EngineData
from .mrp_engine import MRPResult


@dataclass
class CoverageSkuCell:
    sku: str
    tool_code: str
    day_index: int
    days_of_supply: float = 0
    color_band: str = "blue"


@dataclass
class CoverageMatrixSkuResult:
    skus: list[dict] = field(default_factory=list)
    days: list[str] = field(default_factory=list)
    cells: list[list[CoverageSkuCell]] = field(default_factory=list)


def compute_coverage_matrix_sku(
    mrp: MRPResult,
    engine: EngineData,
) -> CoverageMatrixSkuResult:
    """Compute coverage matrix with SKU rows."""
    num_days = len(engine.dates)

    # Flatten all SKU records
    all_sku_records: list[dict] = []
    for rec in mrp.records:
        for sr in rec.sku_records:
            total_gross = sum(b.gross_requirement for b in sr.buckets)
            all_sku_records.append({
                "sku": sr.sku,
                "name": sr.name,
                "tool_code": sr.tool_code,
                "machine": sr.machine,
                "coverage_days": sr.coverage_days,
                "total_gross_req": total_gross,
                "buckets": sr.buckets,
            })

    # Sort by urgency (lowest coverage first)
    all_sku_records.sort(key=lambda r: r["coverage_days"])

    skus = [
        {
            "sku": r["sku"],
            "name": r["name"],
            "toolCode": r["tool_code"],
            "machine": r["machine"],
            "urgencyScore": r["coverage_days"],
        }
        for r in all_sku_records
    ]

    cells: list[list[CoverageSkuCell]] = []
    for sr in all_sku_records:
        avg_daily = sr["total_gross_req"] / num_days if num_days > 0 else 0
        row: list[CoverageSkuCell] = []
        for bucket in sr["buckets"]:
            dos = bucket.projected_available / avg_daily if avg_daily > 0 else num_days
            band = "red" if dos < 1 else ("amber" if dos < 3 else ("green" if dos < 7 else "blue"))
            row.append(CoverageSkuCell(
                sku=sr["sku"],
                tool_code=sr["tool_code"],
                day_index=bucket.day_index,
                days_of_supply=round(dos * 10) / 10,
                color_band=band,
            ))
        cells.append(row)

    return CoverageMatrixSkuResult(skus=skus, days=engine.dates, cells=cells)
