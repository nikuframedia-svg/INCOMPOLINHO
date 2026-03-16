# Pydantic V2 schemas for Nikufra dashboard data
# Rich typed models replacing loose Dict[str, Any]

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class OperationStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    LATE = "LATE"
    BLOCKED = "BLOCKED"


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertCategory(str, Enum):
    DATA_QUALITY = "data_quality"
    STOCK_OUT = "stock_out"
    UNLINKED_ENTITY = "unlinked_entity"
    PARSER_ERROR = "parser_error"
    CAPACITY = "capacity"
    TEMPLATE_CHANGE = "template_change"


class NikufraAlert(BaseModel):
    severity: AlertSeverity
    category: AlertCategory
    title: str
    detail: str
    entity_id: str | None = None


class StockProjectionPoint(BaseModel):
    day_offset: int
    date_label: str
    projected_stock: float


class NikufraStockProjection(BaseModel):
    tool_code: str
    sku: str
    current_stock: float
    projected: list[StockProjectionPoint]
    days_until_zero: int | None = None


class MachineUtilization(BaseModel):
    day_index: int
    date_label: str
    utilization: float = Field(ge=0.0, le=2.0)
    man_minutes: int = 0
    ops_count: int = 0


class NikufraMachineV2(BaseModel):
    id: str
    area: str
    man: list[int]
    utilization_map: list[MachineUtilization] = []


class NikufraToolV2(BaseModel):
    id: str
    m: str
    alt: str
    s: float
    pH: int
    op: int
    skus: list[str]
    nm: list[str]
    lt: int
    stk: int


class NikufraOperationV2(BaseModel):
    id: str
    m: str
    t: str
    sku: str
    nm: str
    pH: int
    atr: int
    d: list[int]
    s: float
    op: int
    status: OperationStatus = OperationStatus.PLANNED


class NikufraHistoryEventV2(BaseModel):
    dt: str
    type: str
    mach: str
    tool: str
    action: str
    result: str
    roi: str


class NikufraMOLoadV2(BaseModel):
    model_config = {"extra": "allow"}

    PG1: list[float] = []
    PG2: list[float] = []


class NikufraDashboardState(BaseModel):
    """Full V2 response model for /v1/nikufra/live endpoint."""

    dates: list[str]
    days_label: list[str]
    mo: dict[str, list[float]]
    machines: list[NikufraMachineV2]
    tools: list[NikufraToolV2]
    operations: list[NikufraOperationV2]
    history: list[NikufraHistoryEventV2]
    alerts: list[NikufraAlert] = []
    stock_projections: list[NikufraStockProjection] = []
    data_hash: str = ""
    parsed_at: str | None = None
    trust_index: float = Field(default=1.0, ge=0.0, le=1.0)
