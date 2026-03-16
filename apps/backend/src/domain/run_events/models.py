# Run Events models
# Conforme SP-BE-12 e C-RUN

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ...db.base import Base


class RunEventType(str, enum.Enum):
    """Tipos de eventos de execução"""

    MACHINE_DOWN = "MachineDown"
    MACHINE_UP = "MachineUp"
    OPERATOR_ABSENT = "OperatorAbsent"
    OPERATOR_BACK = "OperatorBack"
    QUALITY_HOLD = "QualityHold"
    SCRAP_EVENT = "ScrapEvent"


class RunEvent(Base):
    """Evento de execução (append-only)"""

    __tablename__ = "run_events"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(SQLEnum(RunEventType), nullable=False, index=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)

    # Campos opcionais por tipo
    resource_code = Column(String(100), nullable=True, index=True)
    pool_code = Column(String(10), nullable=True)  # "X" ou "Y"
    workorder_id = Column(UUID(as_uuid=True), nullable=True)

    # Tempos (para MachineDown, QualityHold)
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)

    # Data/turno (para OperatorAbsent, OperatorBack)
    date = Column(String(10), nullable=True)  # YYYY-MM-DD
    shift_code = Column(String(10), nullable=True)  # "X" ou "Y"

    # Quantidades
    operators_count = Column(Integer, nullable=True)
    scrap_qty = Column(Numeric(10, 2), nullable=True)

    # Metadados
    reason = Column(String(500), nullable=True)
    event_metadata = Column(JSONB, nullable=True)

    # Relacionamento com scenario gerado
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.scenario_id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships (usar string para evitar import circular)
    # scenario = relationship("Scenario", foreign_keys=[scenario_id])

    def __repr__(self):
        return f"<RunEvent(event_id={self.event_id}, event_type={self.event_type.value}, occurred_at={self.occurred_at})>"
