# Run Events service
# Conforme SP-BE-12

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from ...core.logging import get_logger
from .models import RunEvent, RunEventType
from .repository import RunEventRepository

logger = get_logger(__name__)


class RunEventService:
    """Service para gestão de Run Events"""

    def __init__(self, db: Session):
        self.db = db
        self.repo = RunEventRepository(db)

    def create_event(
        self,
        event_type: RunEventType,
        occurred_at: datetime,
        event_id: str | None = None,
        resource_code: str | None = None,
        pool_code: str | None = None,
        workorder_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        date: str | None = None,
        shift_code: str | None = None,
        operators_count: int | None = None,
        scrap_qty: float | None = None,
        reason: str | None = None,
        event_metadata: dict[str, Any] | None = None,
    ) -> RunEvent:
        """
        Cria novo evento (idempotente).

        Conforme SP-BE-12:
        - Se event_id fornecido, verifica se já existe (idempotência)
        - Eventos são append-only
        """
        # Verificar idempotência
        if event_id:
            existing = self.repo.get_by_event_id_string(event_id)
            if existing:
                logger.info(
                    "Event with event_id already exists (idempotent)",
                    extra={"event_id": event_id, "existing_event_id": str(existing.event_id)},
                )
                return existing

        # Criar novo evento
        event = RunEvent(
            event_id=UUID(event_id) if event_id else uuid4(),
            event_type=event_type,
            occurred_at=occurred_at,
            resource_code=resource_code,
            pool_code=pool_code,
            workorder_id=UUID(workorder_id) if workorder_id else None,
            start_time=start_time,
            end_time=end_time,
            date=date,
            shift_code=shift_code,
            operators_count=operators_count,
            scrap_qty=scrap_qty,
            reason=reason,
            event_metadata=event_metadata,
        )

        event = self.repo.create_event(event)

        logger.info(
            "Run event created",
            extra={
                "event_id": str(event.event_id),
                "event_type": event_type.value,
                "occurred_at": occurred_at.isoformat(),
            },
        )

        return event

    def get_event_by_id(self, event_id: str) -> RunEvent | None:
        """Obtém evento por ID"""
        return self.repo.get_by_event_id_string(event_id)

    def list_events(
        self,
        event_type: RunEventType | None = None,
        resource_code: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        """Lista eventos com filtros"""
        return self.repo.list_events(
            event_type=event_type,
            resource_code=resource_code,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
