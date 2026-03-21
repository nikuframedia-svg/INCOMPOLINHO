"""Safety Stock & ROP — port of mrp/mrp-rop.ts + mrp-rop-sku.ts.

Computes ROP (Reorder Point) at both tool and SKU level.
Includes ABC/XYZ classification and coverage matrix.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from ..types import EngineData
from .mrp_engine import MRPResult

ServiceLevel = Literal[90, 95, 99]

Z_MAP: dict[int, float] = {90: 1.28, 95: 1.645, 99: 2.33}


@dataclass
class ROPConfig:
    abc_a: float = 0.80
    abc_b: float = 0.95
    xyz_x: float = 0.50
    xyz_y: float = 1.00


@dataclass
class StockProjectionPoint:
    day_index: int
    projected: int = 0
    rop_line: int = 0
    ss_line: int = 0


@dataclass
class ROPResult:
    tool_code: str
    demand_avg: float = 0
    demand_std_dev: float = 0
    coefficient_of_variation: float = 0
    lead_time_days: int = 0
    safety_stock: int = 0
    rop: int = 0
    service_level: int = 95
    z_score: float = 1.645
    current_stock: int = 0
    abc_class: str = "C"
    xyz_class: str = "Z"
    stock_projection: list[StockProjectionPoint] = field(default_factory=list)


@dataclass
class ROPSummary:
    records: list[ROPResult] = field(default_factory=list)
    abc_distribution: dict[str, int] = field(default_factory=lambda: {"A": 0, "B": 0, "C": 0})
    xyz_distribution: dict[str, int] = field(default_factory=lambda: {"X": 0, "Y": 0, "Z": 0})
    tools_below_rop: int = 0
    tools_below_ss: int = 0


@dataclass
class ROPSkuResult:
    sku: str
    name: str = ""
    op_id: str = ""
    tool_code: str = ""
    machine: str = ""
    demand_avg: float = 0
    demand_std_dev: float = 0
    coefficient_of_variation: float = 0
    lead_time_days: int = 0
    safety_stock: int = 0
    rop: int = 0
    service_level: int = 95
    z_score: float = 1.645
    current_stock: int = 0
    abc_class: str = "C"
    xyz_class: str = "Z"
    stock_projection: list[StockProjectionPoint] = field(default_factory=list)


@dataclass
class ROPSkuSummary:
    records: list[ROPSkuResult] = field(default_factory=list)
    abc_distribution: dict[str, int] = field(default_factory=lambda: {"A": 0, "B": 0, "C": 0})
    xyz_distribution: dict[str, int] = field(default_factory=lambda: {"X": 0, "Y": 0, "Z": 0})
    skus_below_rop: int = 0
    skus_below_ss: int = 0


@dataclass
class CoverageCell:
    tool_code: str
    day_index: int
    days_of_supply: float = 0
    color_band: str = "blue"


@dataclass
class CoverageMatrixResult:
    tools: list[dict] = field(default_factory=list)
    days: list[str] = field(default_factory=list)
    cells: list[list[CoverageCell]] = field(default_factory=list)


def _mean(arr: list[float]) -> float:
    if not arr:
        return 0
    return sum(arr) / len(arr)


def _stddev(arr: list[float]) -> float:
    if len(arr) < 2:
        return 0
    m = _mean(arr)
    variance = sum((v - m) ** 2 for v in arr) / (len(arr) - 1)
    return math.sqrt(variance)


def compute_rop(
    mrp: MRPResult,
    engine: EngineData,
    service_level: int = 95,
    config: ROPConfig | None = None,
) -> ROPSummary:
    """Compute ROP (Reorder Point) per tool."""
    cfg = config or ROPConfig()
    z = Z_MAP.get(service_level, 1.645)
    num_days = len(engine.dates)

    # Aggregate daily demand per tool
    demand_by_tool: dict[str, list[float]] = {}
    for op in engine.ops:
        if op.t not in demand_by_tool:
            demand_by_tool[op.t] = [0.0] * num_days
        for d in range(min(num_days, len(op.d))):
            demand_by_tool[op.t][d] += op.d[d]

    records: list[ROPResult] = []
    for rec in mrp.records:
        demands = demand_by_tool.get(rec.tool_code, [0.0] * num_days)
        d_avg = _mean(demands)
        sigma = _stddev(demands)
        cv = sigma / d_avg if d_avg > 0 else 0
        lt = rec.lead_days
        ss = z * sigma * math.sqrt(lt) if lt > 0 else 0
        rop_val = d_avg * lt + ss

        projection = [
            StockProjectionPoint(
                day_index=b.day_index,
                projected=b.projected_available,
                rop_line=round(rop_val),
                ss_line=round(ss),
            )
            for b in rec.buckets
        ]

        records.append(ROPResult(
            tool_code=rec.tool_code,
            demand_avg=round(d_avg * 10) / 10,
            demand_std_dev=round(sigma * 10) / 10,
            coefficient_of_variation=round(cv * 100) / 100,
            lead_time_days=lt,
            safety_stock=round(ss),
            rop=round(rop_val),
            service_level=service_level,
            z_score=z,
            current_stock=rec.stock,
            abc_class="C",
            xyz_class="X" if cv < cfg.xyz_x else ("Y" if cv < cfg.xyz_y else "Z"),
            stock_projection=projection,
        ))

    # ABC classification by total volume
    sorted_recs = sorted(records, key=lambda r: r.demand_avg, reverse=True)
    total_volume = sum(r.demand_avg for r in sorted_recs)
    cumulative = 0.0
    for r in sorted_recs:
        cumulative += r.demand_avg
        pct = cumulative / total_volume if total_volume > 0 else 1
        r.abc_class = "A" if pct <= cfg.abc_a else ("B" if pct <= cfg.abc_b else "C")

    abc_dist = {"A": 0, "B": 0, "C": 0}
    xyz_dist = {"X": 0, "Y": 0, "Z": 0}
    for r in records:
        abc_dist[r.abc_class] += 1
        xyz_dist[r.xyz_class] += 1

    return ROPSummary(
        records=records,
        abc_distribution=abc_dist,
        xyz_distribution=xyz_dist,
        tools_below_rop=sum(1 for r in records if r.current_stock < r.rop),
        tools_below_ss=sum(1 for r in records if r.current_stock < r.safety_stock),
    )


def compute_rop_sku(
    mrp: MRPResult,
    engine: EngineData,
    service_level: int = 95,
    config: ROPConfig | None = None,
) -> ROPSkuSummary:
    """Compute ROP per SKU (not tool)."""
    cfg = config or ROPConfig()
    z = Z_MAP.get(service_level, 1.645)

    records: list[ROPSkuResult] = []
    for rec in mrp.records:
        for sr in rec.sku_records:
            demands = [float(b.gross_requirement) for b in sr.buckets]
            d_avg = _mean(demands)
            sigma = _stddev(demands)
            cv = sigma / d_avg if d_avg > 0 else 0
            lt = rec.lead_days
            ss = z * sigma * math.sqrt(lt) if lt > 0 else 0
            rop_val = d_avg * lt + ss

            projection = [
                StockProjectionPoint(
                    day_index=b.day_index,
                    projected=b.projected_available,
                    rop_line=round(rop_val),
                    ss_line=round(ss),
                )
                for b in sr.buckets
            ]

            records.append(ROPSkuResult(
                sku=sr.sku,
                name=sr.name,
                op_id=sr.op_id,
                tool_code=rec.tool_code,
                machine=rec.machine,
                demand_avg=round(d_avg * 10) / 10,
                demand_std_dev=round(sigma * 10) / 10,
                coefficient_of_variation=round(cv * 100) / 100,
                lead_time_days=lt,
                safety_stock=round(ss),
                rop=round(rop_val),
                service_level=service_level,
                z_score=z,
                current_stock=sr.stock,
                abc_class="C",
                xyz_class="X" if cv < cfg.xyz_x else ("Y" if cv < cfg.xyz_y else "Z"),
                stock_projection=projection,
            ))

    # ABC classification
    sorted_recs = sorted(records, key=lambda r: r.demand_avg, reverse=True)
    total_volume = sum(r.demand_avg for r in sorted_recs)
    cumulative = 0.0
    for r in sorted_recs:
        cumulative += r.demand_avg
        pct = cumulative / total_volume if total_volume > 0 else 1
        r.abc_class = "A" if pct <= cfg.abc_a else ("B" if pct <= cfg.abc_b else "C")

    abc_dist = {"A": 0, "B": 0, "C": 0}
    xyz_dist = {"X": 0, "Y": 0, "Z": 0}
    for r in records:
        abc_dist[r.abc_class] += 1
        xyz_dist[r.xyz_class] += 1

    return ROPSkuSummary(
        records=records,
        abc_distribution=abc_dist,
        xyz_distribution=xyz_dist,
        skus_below_rop=sum(1 for r in records if r.current_stock < r.rop),
        skus_below_ss=sum(1 for r in records if r.current_stock < r.safety_stock),
    )


def compute_coverage_matrix(mrp: MRPResult, engine: EngineData) -> CoverageMatrixResult:
    """Compute coverage matrix (tool-level rows)."""
    num_days = len(engine.dates)
    sorted_records = sorted(mrp.records, key=lambda r: r.coverage_days)

    tools = [
        {"toolCode": r.tool_code, "machine": r.machine, "urgencyScore": r.coverage_days}
        for r in sorted_records
    ]

    cells: list[list[CoverageCell]] = []
    for rec in sorted_records:
        total_gross = sum(b.gross_requirement for b in rec.buckets)
        avg_daily = total_gross / num_days if num_days > 0 else 0
        row: list[CoverageCell] = []
        for bucket in rec.buckets:
            dos = bucket.projected_available / avg_daily if avg_daily > 0 else num_days
            band = "red" if dos < 1 else ("amber" if dos < 3 else ("green" if dos < 7 else "blue"))
            row.append(CoverageCell(
                tool_code=rec.tool_code,
                day_index=bucket.day_index,
                days_of_supply=round(dos * 10) / 10,
                color_band=band,
            ))
        cells.append(row)

    return CoverageMatrixResult(tools=tools, days=engine.dates, cells=cells)
