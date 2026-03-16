# Event Applier — persistence only
# Events are stored in the DB for audit/history.
# All scheduling is done client-side via INCOMPOL PLAN.

from sqlalchemy.orm import Session

from ...core.logging import get_logger
from .models import RunEvent

logger = get_logger(__name__)


class EventApplier:
    """Records events for audit. Scheduling reacts client-side."""

    def __init__(self, db: Session):
        self.db = db

    def apply_event(self, event: RunEvent) -> None:
        """Log event for audit trail. No server-side scheduling effect."""
        logger.info(
            f"Event recorded: {event.event_type.value}",
            event_id=str(event.event_id),
            event_type=event.event_type.value,
            resource_code=event.resource_code,
        )
