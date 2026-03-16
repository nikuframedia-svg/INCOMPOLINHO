# Decision Ledger — Pydantic schemas

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DecisionEntryCreate(BaseModel):
    """Request para criar um DecisionEntry."""

    tenant_id: UUID
    user_id: UUID
    decision_type: str = Field(..., max_length=50)
    optimal_state: dict
    proposed_state: dict
    deviation_cost: Decimal = Field(..., ge=0)
    incentive_category: str = Field(
        ...,
        pattern="^(technical|commercial_pressure|operational_convenience|hierarchical_pressure|risk_deferral)$",
    )
    declared_reason: str = Field(..., min_length=1)
    governance_level: str = Field(..., pattern="^L[0-5]$")
    contrafactual: dict | None = None


class DecisionEntryResponse(BaseModel):
    """Response para DecisionEntry."""

    id: UUID
    tenant_id: UUID
    user_id: UUID
    decision_type: str
    optimal_state: dict
    proposed_state: dict
    deviation_cost: Decimal
    incentive_category: str
    declared_reason: str
    governance_level: str
    contrafactual: dict | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    outcome: dict | None = None
    outcome_variance: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApproveRequest(BaseModel):
    """Request para aprovar uma decisão (L4+)."""

    approved_by: UUID


class LedgerStats(BaseModel):
    """Estatísticas do Decision Ledger."""

    total_entries: int
    total_deviation_cost: Decimal
    entries_by_category: dict[str, int]
    entries_by_type: dict[str, int]
    pending_approvals: int
