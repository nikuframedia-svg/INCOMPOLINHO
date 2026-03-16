# Audit log model
# Conforme SP-BE-02 e C-15

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ...db.base import Base


class AuditLog(Base):
    """Log de auditoria (append-only)"""

    __tablename__ = "audit_log"

    audit_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)

    actor = Column(String(255), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    correlation_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(String(255), nullable=False, index=True)

    # Estado antes/depois (JSONB)
    before = Column(JSONB, nullable=True)
    after = Column(JSONB, nullable=True)
    audit_metadata = Column(
        JSONB, nullable=True
    )  # Renomeado de 'metadata' (reservado no SQLAlchemy)

    # Constraint: append-only (sem updates/deletes)
    # Isto é garantido pela aplicação, não pela DB (mas podemos adicionar trigger se necessário)
