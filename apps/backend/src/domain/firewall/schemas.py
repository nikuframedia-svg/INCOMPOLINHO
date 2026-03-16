# Decision Integrity Firewall — Pydantic schemas

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class DeviationRequest(BaseModel):
    """Request para avaliar um desvio."""

    optimal_state: dict
    proposed_state: dict
    incentive_category: str = Field(
        ...,
        pattern="^(technical|commercial_pressure|operational_convenience|hierarchical_pressure|risk_deferral)$",
    )
    governance_level: str = Field(..., pattern="^L[0-5]$")


class DeviationAssessment(BaseModel):
    """Resultado da avaliação do Firewall."""

    allowed: bool
    requires_approval: bool
    requires_contrafactual: bool
    deviation_cost: Decimal
    cascade_ops_count: int
    warnings: list[str]
    contrafactual: dict | None = None
