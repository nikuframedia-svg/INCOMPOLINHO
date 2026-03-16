# Decision Ledger — SQLAlchemy models
# Conforme CLAUDE.md: Decision Integrity Firewall

from __future__ import annotations

import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ...db.base import Base


class DecisionEntry(Base):
    """Registo imutável de cada desvio do plano óptimo."""

    __tablename__ = "decision_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Tipo: schedule_override | priority_change | night_shift | ...
    decision_type = Column(String(50), nullable=False, index=True)

    # Estado óptimo (do scheduler) vs proposto (pelo utilizador)
    optimal_state = Column(JSONB, nullable=False)
    proposed_state = Column(JSONB, nullable=False)

    # Custo calculado deterministicamente (euros)
    deviation_cost = Column(Numeric(12, 2), nullable=False)

    # Categoria de incentivo (conforme Firewall)
    incentive_category = Column(String(30), nullable=False)

    # Motivo declarado pelo utilizador
    declared_reason = Column(Text, nullable=False)

    # Nível de governance aplicado (L0-L5)
    governance_level = Column(String(2), nullable=False)

    # Contrafactual (obrigatório L3+)
    contrafactual = Column(JSONB, nullable=True)

    # Aprovação (obrigatório L4+)
    approved_by = Column(UUID(as_uuid=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # Outcome (preenchido depois pela Learning Engine)
    outcome = Column(JSONB, nullable=True)
    outcome_variance = Column(String(20), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
