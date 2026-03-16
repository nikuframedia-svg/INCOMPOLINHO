# Stock Alerts — Pydantic schemas

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AcknowledgeRequest(BaseModel):
    alert_id: str
    tool_code: str
    machine: str
    priority: str
    acknowledged_by: str | None = None


class SnoozeRequest(BaseModel):
    alert_id: str
    tool_code: str
    machine: str
    priority: str
    snooze_minutes: int
    snoozed_by: str | None = None


class StockAlertResponse(BaseModel):
    id: UUID
    alert_id: str
    tool_code: str
    machine: str
    priority: str
    action: str
    action_by: str | None
    snooze_until: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
