"""Rule model — L2 configurable rules (SE/ENTÃO)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from ...db.base import Base


class Rule(Base):
    """A configurable rule for the decision engine."""

    __tablename__ = "rules"

    id = Column(String(100), primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    rule = Column(JSONB, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    priority = Column(Integer, nullable=False, default=0)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=func.now()
    )
