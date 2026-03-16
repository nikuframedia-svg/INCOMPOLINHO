# Stock Alerts — SQLAlchemy model
# Persists acknowledge/snooze actions from frontend

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID

from ...db.base import Base


class StockAlert(Base):
    """Registo de acoes sobre alertas de stock (acknowledge, snooze, clear)."""

    __tablename__ = "stock_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id = Column(String(100), nullable=False, index=True)
    tool_code = Column(String(50), nullable=False, index=True)
    machine = Column(String(20), nullable=False)
    priority = Column(String(10), nullable=False)
    action = Column(String(20), nullable=False)
    action_by = Column(String(100), nullable=True)
    snooze_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
