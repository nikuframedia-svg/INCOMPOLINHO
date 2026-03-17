"""Settings model — key/value store with JSONB values."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB

from ...db.base import Base


class Setting(Base):
    """Engine settings stored as key-value pairs."""

    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(JSONB, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=func.now()
    )
    updated_by = Column(String(100), nullable=True)
