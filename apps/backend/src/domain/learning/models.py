# Learning Engine — SQLAlchemy models

from __future__ import annotations

import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ...db.base import Base


class LearningProposal(Base):
    """Proposta de ajuste gerada pela Learning Engine quando variance > 10%."""

    __tablename__ = "learning_proposals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # FK para a decisão que gerou esta proposta
    decision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("decision_entries.id"),
        nullable=False,
        index=True,
    )

    # Tipo de variance: data | heuristic | context | human_deviation
    variance_type = Column(String(30), nullable=False)

    # Valor da variance (0.0 - 1.0+)
    variance_value = Column(Numeric(8, 4), nullable=False)

    # Ajuste proposto (JSON com parâmetros a alterar)
    proposed_adjustment = Column(JSONB, nullable=False)

    # Status: pending | accepted | rejected
    status = Column(String(20), nullable=False, default="pending", index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
