# Events API endpoints
# Conforme SP-BE-12 e C-RUN

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ...core.errors import APIException, ErrorCodes
from ...core.middleware import correlation_filter as correlation_filter_middleware
from ...db.base import get_db
from ...domain.run_events.event_applier import EventApplier
from ...domain.run_events.models import RunEventType
from ...domain.run_events.service import RunEventService

router = APIRouter(prefix="/events", tags=["events"])


class CreateEventRequest(BaseModel):
    """Request para criar evento"""

    event_id: str | None = Field(None, description="Event ID (para idempotência)")
    event_type: str = Field(..., description="Event type")
    occurred_at: str = Field(..., description="ISO 8601 datetime")
    resource_code: str | None = None
    pool_code: str | None = None
    workorder_id: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    date: str | None = None
    shift_code: str | None = None
    operators_count: int | None = None
    scrap_qty: float | None = None
    reason: str | None = None
    event_metadata: dict | None = None


class EventResponse(BaseModel):
    """Response para evento"""

    event_id: str
    event_type: str
    occurred_at: str
    resource_code: str | None
    pool_code: str | None
    workorder_id: str | None
    start_time: str | None
    end_time: str | None
    date: str | None
    shift_code: str | None
    operators_count: int | None
    scrap_qty: float | None
    reason: str | None
    scenario_id: str | None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


@router.post("", response_model=EventResponse, status_code=201)
def create_event(
    request: CreateEventRequest,
    db: Session = Depends(get_db),
):
    """
    Cria novo evento de execução (idempotente).

    Conforme SP-BE-12 e C-RUN:
    - Se event_id fornecido, verifica se já existe (idempotência)
    - Aplica evento ao sistema (downtime, absentismo, etc.)
    - Trigger de replan (cria scenario, corre solver)
    """
    correlation_id = correlation_filter_middleware.correlation_id

    # Validar event_type
    try:
        event_type = RunEventType(request.event_type)
    except ValueError:
        raise APIException(
            status_code=400,
            code=ErrorCodes.ERR_INVALID_INPUT,
            message=f"Invalid event_type: {request.event_type}",
            correlation_id=correlation_id,
        )

    # Parse datetimes
    try:
        occurred_at = datetime.fromisoformat(request.occurred_at.replace("Z", "+00:00"))
    except ValueError:
        raise APIException(
            status_code=400,
            code=ErrorCodes.ERR_INVALID_INPUT,
            message=f"Invalid occurred_at format: {request.occurred_at}",
            correlation_id=correlation_id,
        )

    start_time = None
    if request.start_time:
        try:
            start_time = datetime.fromisoformat(request.start_time.replace("Z", "+00:00"))
        except ValueError:
            raise APIException(
                status_code=400,
                code=ErrorCodes.ERR_INVALID_INPUT,
                message=f"Invalid start_time format: {request.start_time}",
                correlation_id=correlation_id,
            )

    end_time = None
    if request.end_time:
        try:
            end_time = datetime.fromisoformat(request.end_time.replace("Z", "+00:00"))
        except ValueError:
            raise APIException(
                status_code=400,
                code=ErrorCodes.ERR_INVALID_INPUT,
                message=f"Invalid end_time format: {request.end_time}",
                correlation_id=correlation_id,
            )

    workorder_uuid = None
    if request.workorder_id:
        try:
            workorder_uuid = request.workorder_id
        except ValueError:
            raise APIException(
                status_code=400,
                code=ErrorCodes.ERR_INVALID_INPUT,
                message=f"Invalid workorder_id format: {request.workorder_id}",
                correlation_id=correlation_id,
            )

    # Criar evento
    service = RunEventService(db)
    event = service.create_event(
        event_type=event_type,
        occurred_at=occurred_at,
        event_id=request.event_id,
        resource_code=request.resource_code,
        pool_code=request.pool_code,
        workorder_id=workorder_uuid,
        start_time=start_time,
        end_time=end_time,
        date=request.date,
        shift_code=request.shift_code,
        operators_count=request.operators_count,
        scrap_qty=request.scrap_qty,
        reason=request.reason,
        event_metadata=request.event_metadata,
    )

    # Aplicar evento ao sistema
    applier = EventApplier(db)
    applier.apply_event(event)

    # TODO: Trigger de replan (criar scenario, correr solver, guardar diff)
    # Por agora, apenas commit
    db.commit()

    return event


@router.get("", response_model=list[EventResponse])
def list_events(
    event_type: str | None = Query(None, description="Filter by event type"),
    resource_code: str | None = Query(None, description="Filter by resource code"),
    date_from: str | None = Query(None, description="Filter from date (ISO 8601)"),
    date_to: str | None = Query(None, description="Filter to date (ISO 8601)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Lista eventos com filtros opcionais"""
    correlation_id = correlation_filter_middleware.correlation_id

    # Parse event_type
    event_type_enum = None
    if event_type:
        try:
            event_type_enum = RunEventType(event_type)
        except ValueError:
            raise APIException(
                status_code=400,
                code=ErrorCodes.ERR_INVALID_INPUT,
                message=f"Invalid event_type: {event_type}",
                correlation_id=correlation_id,
            )

    # Parse dates
    date_from_obj = None
    if date_from:
        try:
            date_from_obj = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
        except ValueError:
            raise APIException(
                status_code=400,
                code=ErrorCodes.ERR_INVALID_INPUT,
                message=f"Invalid date_from format: {date_from}",
                correlation_id=correlation_id,
            )

    date_to_obj = None
    if date_to:
        try:
            date_to_obj = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
        except ValueError:
            raise APIException(
                status_code=400,
                code=ErrorCodes.ERR_INVALID_INPUT,
                message=f"Invalid date_to format: {date_to}",
                correlation_id=correlation_id,
            )

    service = RunEventService(db)
    events = service.list_events(
        event_type=event_type_enum,
        resource_code=resource_code,
        date_from=date_from_obj,
        date_to=date_to_obj,
        limit=limit,
        offset=offset,
    )

    return events


@router.get("/{event_id}", response_model=EventResponse)
def get_event(
    event_id: str,
    db: Session = Depends(get_db),
):
    """Obtém evento por ID"""
    correlation_id = correlation_filter_middleware.correlation_id

    service = RunEventService(db)
    event = service.get_event_by_id(event_id)

    if not event:
        raise APIException(
            status_code=404,
            code=ErrorCodes.ERR_NOT_FOUND,
            message=f"Event not found: {event_id}",
            correlation_id=correlation_id,
        )

    return event
