# Plan models
# Conforme SP-BE-02 e C-04

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from ...db.base import Base


class PlanStatus(str, enum.Enum):
    CANDIDATE = "CANDIDATE"
    OFFICIAL = "OFFICIAL"


class Plan(Base):
    """Plano de produção"""

    __tablename__ = "plans"

    plan_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id = Column(
        UUID(as_uuid=True), ForeignKey("snapshots.snapshot_id"), nullable=False, index=True
    )

    # Hash canónico
    snapshot_hash = Column(String(64), nullable=False, index=True)
    plan_hash = Column(String(64), nullable=False, unique=True, index=True)

    status = Column(SQLEnum(PlanStatus), nullable=False, default=PlanStatus.CANDIDATE, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Plan params (JSONB)
    plan_params = Column(JSONB, nullable=False)

    # Plan canónico (JSONB)
    plan_json = Column(JSONB, nullable=False)

    # KPI Pack (JSONB)
    kpi_pack = Column(JSONB, nullable=False)

    # Explain trace (JSONB)
    explain_trace = Column(JSONB, nullable=True)

    # Relationships
    workorders = relationship("WorkOrder", back_populates="plan", cascade="all, delete-orphan")
    operations = relationship("PlanOperation", back_populates="plan", cascade="all, delete-orphan")


class WorkOrder(Base):
    """Ordem de trabalho"""

    __tablename__ = "workorders"

    workorder_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id = Column(
        UUID(as_uuid=True), ForeignKey("plans.plan_id", ondelete="CASCADE"), nullable=False
    )

    snapshot_id = Column(UUID(as_uuid=True), nullable=True)
    customer_code = Column(String(100), nullable=True)
    item_sku = Column(String(100), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    day_bucket = Column(String(10), nullable=True)  # YYYY-MM-DD
    routing_ref = Column(String(100), nullable=True)

    # Relationships
    plan = relationship("Plan", back_populates="workorders")


class PlanOperation(Base):
    """Operação do plano"""

    __tablename__ = "plan_operations"

    operation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id = Column(
        UUID(as_uuid=True), ForeignKey("plans.plan_id", ondelete="CASCADE"), nullable=False
    )

    workorder_id = Column(
        UUID(as_uuid=True), ForeignKey("workorders.workorder_id"), nullable=False, index=True
    )

    item_sku = Column(String(100), nullable=False)
    resource_code = Column(String(100), nullable=False, index=True)
    tool_code = Column(String(100), nullable=True)

    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=False, index=True)

    quantity = Column(Integer, nullable=False, default=0)
    is_setup = Column(Boolean, nullable=False, default=False)
    operators_required = Column(Integer, nullable=True, default=1)

    # Relationships
    plan = relationship("Plan", back_populates="operations")
    workorder = relationship("WorkOrder")
