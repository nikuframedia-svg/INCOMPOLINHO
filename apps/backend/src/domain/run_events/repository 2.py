# Run Events repository
# Conforme SP-BE-12

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from .models import RunEvent, RunEventType


class RunEventRepository:
    """Repository para RunEvent"""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, event_id: UUID) -> RunEvent | None:
        """Obtém evento por ID"""
        return self.db.query(RunEvent).filter(RunEvent.event_id == event_id).first()

    def get_by_event_id_string(self, event_id: str) -> RunEvent | None:
        """Obtém evento por event_id (string) - para idempotência"""
        try:
            event_uuid = UUID(event_id)
            return self.get_by_id(event_uuid)
        except ValueError:
            return None

    def list_events(
        self,
        event_type: RunEventType | None = None,
        resource_code: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RunEvent]:
        """Lista eventos com filtros opcionais"""
        query = self.db.query(RunEvent)

        if event_type:
            query = query.filter(RunEvent.event_type == event_type)
        if resource_code:
            query = query.filter(RunEvent.resource_code == resource_code)
        if date_from:
            query = query.filter(RunEvent.occurred_at >= date_from)
        if date_to:
            query = query.filter(RunEvent.occurred_at <= date_to)

        query = query.order_by(RunEvent.occurred_at.desc())
        return query.limit(limit).offset(offset).all()

    def create_event(self, event: RunEvent) -> RunEvent:
        """Cria novo evento (append-only)"""
        self.db.add(event)
        self.db.flush()
        return event
