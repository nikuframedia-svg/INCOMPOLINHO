# Snapshot models
# Conforme SP-BE-02 e C-01

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from ...db.base import Base


class SourceType(str, enum.Enum):
    XLSX = "XLSX"
    PDF = "PDF"
    API = "API"
    MANUAL = "MANUAL"


class SeriesSemantics(str, enum.Enum):
    NET_POSITION_AFTER_ALL_NEEDS_BY_DATE = "NET_POSITION_AFTER_ALL_NEEDS_BY_DATE"
    PROJECTED_AVAILABLE_AFTER_ALL_NEEDS_BY_DATE = "PROJECTED_AVAILABLE_AFTER_ALL_NEEDS_BY_DATE"
    DEMAND_QTY_BY_DATE = "DEMAND_QTY_BY_DATE"
    PLANNED_PRODUCTION_QTY_BY_DATE = "PLANNED_PRODUCTION_QTY_BY_DATE"
    PROJECTED_STOCK_LEVEL = "PROJECTED_STOCK_LEVEL"
    NET_REQUIREMENT = "NET_REQUIREMENT"
    UNKNOWN = "UNKNOWN"


class Snapshot(Base):
    """Snapshot canónico e imutável"""

    __tablename__ = "snapshots"

    snapshot_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Hash canónico (SHA-256)
    snapshot_hash = Column(String(64), nullable=False, unique=True, index=True)

    # Semântica
    series_semantics = Column(SQLEnum(SeriesSemantics), nullable=False)
    setup_time_uom = Column(String(20), nullable=True)  # HOURS, MINUTES, SECONDS, UNKNOWN
    mo_uom = Column(String(20), nullable=True)  # HOURS, FTE, OPERATORS, UNKNOWN

    # Trust Index
    trust_index_overall = Column(Numeric(3, 2), nullable=False, default=Decimal("0.0"))

    # Imutabilidade
    sealed_at = Column(
        DateTime(timezone=True), nullable=True, index=True
    )  # Quando selado, snapshot é imutável

    # Snapshot canónico (JSONB para flexibilidade)
    snapshot_json = Column(JSONB, nullable=False)

    # Relationships
    sources = relationship(
        "SnapshotSource", back_populates="snapshot", cascade="all, delete-orphan"
    )
    items = relationship("Item", back_populates="snapshot", cascade="all, delete-orphan")
    resources = relationship("Resource", back_populates="snapshot", cascade="all, delete-orphan")
    tools = relationship("Tool", back_populates="snapshot", cascade="all, delete-orphan")
    routings = relationship("Routing", back_populates="snapshot", cascade="all, delete-orphan")


class SnapshotSource(Base):
    """Fonte de dados do snapshot"""

    __tablename__ = "snapshot_sources"

    source_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id = Column(
        UUID(as_uuid=True), ForeignKey("snapshots.snapshot_id", ondelete="CASCADE"), nullable=False
    )

    type = Column(SQLEnum(SourceType), nullable=False)
    filename = Column(String(255), nullable=True)
    file_hash_sha256 = Column(String(64), nullable=False, index=True)
    generated_at_local = Column(DateTime(timezone=True), nullable=True)
    source_timezone = Column(String(50), nullable=True)  # IANA timezone
    source_metadata = Column(
        JSONB, nullable=True
    )  # Renomeado de 'metadata' (reservado no SQLAlchemy)

    # Relationships
    snapshot = relationship("Snapshot", back_populates="sources")


class Item(Base):
    """Item/SKU"""

    __tablename__ = "items"

    item_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id = Column(
        UUID(as_uuid=True), ForeignKey("snapshots.snapshot_id", ondelete="CASCADE"), nullable=False
    )

    item_sku = Column(String(100), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    parent_sku = Column(String(100), nullable=True)
    lot_economic_qty = Column(Integer, nullable=True)

    # Relationships
    snapshot = relationship("Snapshot", back_populates="items")


class Resource(Base):
    """Recurso (máquina, SetupCrew, etc.)"""

    __tablename__ = "resources"

    resource_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id = Column(
        UUID(as_uuid=True), ForeignKey("snapshots.snapshot_id", ondelete="CASCADE"), nullable=False
    )

    resource_code = Column(String(100), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    resource_type = Column(String(50), nullable=True)  # MACHINE, SETUP_CREW, etc.

    # Relationships
    snapshot = relationship("Snapshot", back_populates="resources")


class Tool(Base):
    """Ferramenta"""

    __tablename__ = "tools"

    tool_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id = Column(
        UUID(as_uuid=True), ForeignKey("snapshots.snapshot_id", ondelete="CASCADE"), nullable=False
    )

    tool_code = Column(String(100), nullable=False, index=True)
    name = Column(String(255), nullable=True)

    # Relationships
    snapshot = relationship("Snapshot", back_populates="tools")


class Routing(Base):
    """Rota de produção"""

    __tablename__ = "routings"

    routing_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id = Column(
        UUID(as_uuid=True), ForeignKey("snapshots.snapshot_id", ondelete="CASCADE"), nullable=False
    )

    item_sku = Column(String(100), nullable=False, index=True)
    routing_ref = Column(String(100), nullable=True)

    # Relationships
    snapshot = relationship("Snapshot", back_populates="routings")
    operations = relationship(
        "RoutingOperation", back_populates="routing", cascade="all, delete-orphan"
    )


class RoutingOperation(Base):
    """Operação de rota"""

    __tablename__ = "routing_operations"

    operation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    routing_id = Column(
        UUID(as_uuid=True), ForeignKey("routings.routing_id", ondelete="CASCADE"), nullable=False
    )

    sequence = Column(Integer, nullable=False)
    resource_code = Column(String(100), nullable=False)
    tool_code = Column(String(100), nullable=True)
    setup_time = Column(Numeric(10, 2), nullable=True)
    rate = Column(Numeric(10, 2), nullable=True)  # unidades/hora
    operators_required = Column(Integer, nullable=True, default=1)
    alt_resources = Column(JSONB, nullable=True)  # Array de resource_code alternativos

    # Relationships
    routing = relationship("Routing", back_populates="operations")
