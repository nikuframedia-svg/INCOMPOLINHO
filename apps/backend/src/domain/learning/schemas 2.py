# Learning Engine — Pydantic schemas
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OutcomeRequest(BaseModel):
    """Request para registar outcome real de uma decisão."""

    actual_kpis: dict  # {tardiness_min, otd_pct, makespan_min, utilization_pct}


class OutcomeResponse(BaseModel):
    """Response após processar outcome."""

    decision_id: UUID
    variance: Decimal
    variance_type: str
    proposal_created: bool


class LearningProposalResponse(BaseModel):
    """Response para LearningProposal."""

    id: UUID
    decision_id: UUID
    variance_type: str
    variance_value: Decimal
    proposed_adjustment: dict
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProposalUpdateRequest(BaseModel):
    """Request para aceitar/rejeitar proposta."""

    status: str  # accepted | rejected
