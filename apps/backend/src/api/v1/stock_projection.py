"""Stock projection endpoint — CTP based on REAL schedule capacity.

POST /v1/schedule/stock/{sku}/ctp — CTP for specific qty + deadline
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...core.logging import get_logger
from ...domain.scheduling.analysis.ctp_real import compute_ctp_real
from .pipeline_helpers import get_last_schedule

logger = get_logger(__name__)

stock_projection_router = APIRouter(prefix="/schedule/stock", tags=["stock"])


class CTPRealRequest(BaseModel):
    qty: int
    deadline_day: int


@stock_projection_router.post("/{sku}/ctp")
async def stock_ctp(sku: str, req: CTPRealRequest):
    """CTP based on REAL schedule capacity (block-level free minutes)."""
    cached = get_last_schedule()
    if not cached:
        raise HTTPException(404, "Nenhum plano em cache. Execute o pipeline primeiro.")

    engine_data = cached["engine_data"]
    blocks = cached["blocks"]

    result = compute_ctp_real(
        sku=sku,
        qty=req.qty,
        deadline_day=req.deadline_day,
        blocks=blocks,
        engine_data=engine_data,
    )

    return {
        "feasible": result.feasible,
        "machine": result.machine,
        "earliestDay": result.earliest_day,
        "requiredMin": result.required_min,
        "freeMinOnTarget": result.free_min_on_target,
        "confidence": result.confidence,
        "reason": result.reason,
        "altMachine": result.alt_machine,
        "altEarliestDay": result.alt_earliest_day,
    }
