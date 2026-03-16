# Decision Ledger API endpoints
# Conforme Contrato C3: Decision Ledger
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...domain.ledger.repository import LedgerRepository
from ...domain.ledger.schemas import (
    ApproveRequest,
    DecisionEntryCreate,
    DecisionEntryResponse,
    LedgerStats,
)
from ...domain.ledger.service import LedgerService

ledger_router = APIRouter(prefix="/ledger", tags=["ledger"])


@ledger_router.post("/entries", response_model=DecisionEntryResponse, status_code=201)
async def create_decision_entry(
    data: DecisionEntryCreate,
    db: Session = Depends(get_db),
):
    """
    Criar um registo no Decision Ledger.
    Passa pelo Firewall antes de registar.
    """
    entry = LedgerService.create_entry(db, data)
    return entry


@ledger_router.get("/entries", response_model=list[DecisionEntryResponse])
async def list_decision_entries(
    tenant_id: UUID | None = Query(None),
    user_id: UUID | None = Query(None),
    decision_type: str | None = Query(None),
    incentive_category: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Listar entradas do Decision Ledger com filtros."""
    entries = LedgerRepository.list_entries(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        decision_type=decision_type,
        incentive_category=incentive_category,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return entries


@ledger_router.get("/entries/{entry_id}", response_model=DecisionEntryResponse)
async def get_decision_entry(
    entry_id: UUID,
    db: Session = Depends(get_db),
):
    """Obter detalhe de uma entrada do Decision Ledger."""
    from ...core.errors import APIException, ErrorCodes

    entry = LedgerRepository.get_by_id(db, entry_id)
    if not entry:
        raise APIException(
            status_code=404,
            code=ErrorCodes.ERR_NOT_FOUND,
            message="Decision entry not found",
        )
    return entry


@ledger_router.patch("/entries/{entry_id}/approve", response_model=DecisionEntryResponse)
async def approve_decision_entry(
    entry_id: UUID,
    data: ApproveRequest,
    db: Session = Depends(get_db),
):
    """Aprovar uma decisão (L4+)."""
    entry = LedgerService.approve_entry(db, entry_id, data.approved_by)
    return entry


@ledger_router.get("/stats", response_model=LedgerStats)
async def get_ledger_stats(
    tenant_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
):
    """Estatísticas do Decision Ledger."""
    stats = LedgerRepository.get_stats(db, tenant_id)
    return LedgerStats(**stats)
