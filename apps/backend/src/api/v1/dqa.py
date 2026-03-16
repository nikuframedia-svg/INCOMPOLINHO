# Data Quality Assessment (TrustIndex) API endpoints
# Conforme Contrato C3: DQA

from __future__ import annotations

from fastapi import APIRouter

from ...domain.dqa.engine import DQAEngine
from ...domain.dqa.schemas import GateInfo, TrustIndexResult

dqa_router = APIRouter(prefix="/dqa", tags=["dqa"])

_engine = DQAEngine()


@dqa_router.post("/assess", response_model=TrustIndexResult)
async def assess_isop(file_data: dict):
    """
    Avaliar qualidade de dados ISOP e calcular TrustIndex.

    file_data deve conter:
    - rows: list[dict] com campos sku, machine, tool, pcs_per_hour, twin
    - file_date: str ISO date
    """
    return _engine.assess_isop(file_data)


@dqa_router.get("/gates", response_model=list[GateInfo])
async def list_gates():
    """Listar gates e thresholds do TrustIndex."""
    return [
        GateInfo(threshold=threshold, name=name, description=desc)
        for threshold, name, desc in DQAEngine.GATES
    ]
