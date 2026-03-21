"""Per-SKU CTP (Capable-to-Promise) — port of mrp/mrp-ctp-sku.ts.

Resolves SKU → tool, delegates to compute_ctp().
"""

from __future__ import annotations

from dataclasses import dataclass

from ..types import EngineData
from .ctp import CTPInput, CTPResult, compute_ctp
from .mrp_engine import MRPResult


@dataclass
class CTPSkuInput:
    sku: str
    quantity: int
    target_day: int


@dataclass
class CTPSkuResult(CTPResult):
    sku: str = ""
    sku_name: str = ""


def compute_ctp_sku(
    inp: CTPSkuInput,
    mrp: MRPResult,
    engine: EngineData,
) -> CTPSkuResult:
    """Compute Capable-to-Promise for a given SKU."""
    # Resolve SKU → tool
    op = next((o for o in engine.ops if o.sku == inp.sku), None)

    if not op:
        return CTPSkuResult(
            feasible=False,
            tool_code="?",
            machine="?",
            reason=f"SKU {inp.sku} not found.",
            sku=inp.sku,
            sku_name="",
        )

    tool_code = op.t
    ctp_result = compute_ctp(
        CTPInput(tool_code=tool_code, quantity=inp.quantity, target_day=inp.target_day),
        mrp,
        engine,
    )

    # Annotate with per-SKU projected stock
    rec = next((r for r in mrp.records if r.tool_code == tool_code), None)
    sku_rec = None
    if rec:
        sku_rec = next((sr for sr in rec.sku_records if sr.op_id == op.id), None)

    sku_projected = (
        sku_rec.buckets[inp.target_day].projected_available
        if sku_rec and inp.target_day < len(sku_rec.buckets)
        else ctp_result.projected_stock_on_day
        if hasattr(ctp_result, "projected_stock_on_day")
        else 0
    )

    return CTPSkuResult(
        feasible=ctp_result.feasible,
        tool_code=ctp_result.tool_code,
        machine=ctp_result.machine,
        required_min=ctp_result.required_min,
        available_min_on_day=ctp_result.available_min_on_day,
        capacity_slack=ctp_result.capacity_slack,
        earliest_feasible_day=ctp_result.earliest_feasible_day,
        confidence=ctp_result.confidence,
        reason=ctp_result.reason,
        capacity_timeline=ctp_result.capacity_timeline,
        sku=inp.sku,
        sku_name=op.nm,
    )
