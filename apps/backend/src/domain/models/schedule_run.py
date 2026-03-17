"""ScheduleRun model — persisted pipeline execution results."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ...db.base import Base


class ScheduleRun(Base):
    """A single pipeline execution: ISOP → schedule → results."""

    __tablename__ = "schedule_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    solver_used = Column(String(50), nullable=False, default="atcs_python")
    dispatch_rule = Column(String(20), nullable=False, default="EDD")
    solve_time_s = Column(Float, nullable=True)

    # Results
    blocks = Column(JSONB, nullable=False, default=list)
    kpis = Column(JSONB, nullable=False, default=dict)
    decisions = Column(JSONB, nullable=False, default=list)
    feasibility_report = Column(JSONB, nullable=True)
    settings_snapshot = Column(JSONB, nullable=True)

    # Counts
    n_blocks = Column(Integer, nullable=False, default=0)
    n_ops = Column(Integer, nullable=False, default=0)
    otd_pct = Column(Float, nullable=True)

    # Traceability
    isop_hash = Column(String(64), nullable=True, index=True)
