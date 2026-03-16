# Stock Alerts API endpoints
# Conforme Contrato F3: Alertas Automaticos de Stock
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...domain.stock_alerts.models import StockAlert
from ...domain.stock_alerts.schemas import (
    AcknowledgeRequest,
    SnoozeRequest,
    StockAlertResponse,
)

stock_alerts_router = APIRouter(prefix="/stock-alerts", tags=["stock-alerts"])


@stock_alerts_router.post("/acknowledge", response_model=StockAlertResponse, status_code=201)
async def acknowledge_alert(
    data: AcknowledgeRequest,
    db: Session = Depends(get_db),
):
    """Registar acknowledge de um alerta de stock."""
    entry = StockAlert(
        id=uuid.uuid4(),
        alert_id=data.alert_id,
        tool_code=data.tool_code,
        machine=data.machine,
        priority=data.priority,
        action="acknowledge",
        action_by=data.acknowledged_by,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@stock_alerts_router.post("/snooze", response_model=StockAlertResponse, status_code=201)
async def snooze_alert(
    data: SnoozeRequest,
    db: Session = Depends(get_db),
):
    """Registar snooze de um alerta de stock."""
    snooze_until = datetime.now(UTC) + timedelta(minutes=data.snooze_minutes)
    entry = StockAlert(
        id=uuid.uuid4(),
        alert_id=data.alert_id,
        tool_code=data.tool_code,
        machine=data.machine,
        priority=data.priority,
        action="snooze",
        action_by=data.snoozed_by,
        snooze_until=snooze_until,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@stock_alerts_router.get("/history", response_model=list[StockAlertResponse])
async def get_alert_history(
    tool_code: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Historico de acoes sobre alertas de stock."""
    query = db.query(StockAlert).order_by(StockAlert.created_at.desc())
    if tool_code:
        query = query.filter(StockAlert.tool_code == tool_code)
    return query.limit(limit).all()
