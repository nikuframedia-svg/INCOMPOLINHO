# Learning Engine API endpoints
# Conforme Contrato C3: Learning Engine
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.errors import APIException, ErrorCodes
from ...db.base import get_db
from ...domain.learning.engine import LearningEngine
from ...domain.learning.schemas import (
    LearningProposalResponse,
    OutcomeRequest,
    OutcomeResponse,
    ProposalUpdateRequest,
)

learning_router = APIRouter(prefix="/learning", tags=["learning"])

_engine = LearningEngine()


@learning_router.post("/outcomes/{decision_id}", response_model=OutcomeResponse)
async def process_outcome(
    decision_id: UUID,
    data: OutcomeRequest,
    db: Session = Depends(get_db),
):
    """Registar outcome real de uma decisão e comparar com previsão."""
    result = _engine.process_outcome(db, decision_id, data.actual_kpis)
    return OutcomeResponse(**result)


@learning_router.get("/proposals", response_model=list[LearningProposalResponse])
async def list_proposals(
    status: str | None = Query(None, pattern="^(pending|accepted|rejected)$"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Listar propostas de ajuste pendentes."""
    proposals = LearningEngine.list_proposals(db, status=status, limit=limit)
    return proposals


@learning_router.patch("/proposals/{proposal_id}", response_model=LearningProposalResponse)
async def update_proposal(
    proposal_id: UUID,
    data: ProposalUpdateRequest,
    db: Session = Depends(get_db),
):
    """Aceitar ou rejeitar proposta de ajuste."""
    if data.status not in ("accepted", "rejected"):
        raise APIException(
            status_code=422,
            code=ErrorCodes.ERR_INVALID_INPUT,
            message="Status must be 'accepted' or 'rejected'",
        )

    proposal = LearningEngine.update_proposal_status(db, proposal_id, data.status)
    if not proposal:
        raise APIException(
            status_code=404,
            code=ErrorCodes.ERR_NOT_FOUND,
            message="Learning proposal not found",
        )
    return proposal
