# Audit service — business logic for audit trail
# Conforme C-15: append-only audit trail with correlation tracking

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ...core.logging import get_logger
from ..models.audit import AuditLog
from .repository import AuditRepository

logger = get_logger(__name__)

# Known action types (superset — DB may have a subset)
KNOWN_ACTIONS = [
    "SNAPSHOT_CREATED",
    "SNAPSHOT_SEALED",
    "PLAN_GENERATED",
    "PLAN_COMMITTED",
    "SCENARIO_CREATED",
    "SCENARIO_RUN",
    "PR_CREATED",
    "PR_APPROVED",
    "PR_MERGED",
    "PR_ROLLED_BACK",
    "PR_REJECTED",
    "SUGGESTION_CREATED",
    "SUGGESTION_ACCEPTED",
    "SUGGESTION_REJECTED",
    "USER_CREATED",
    "USER_ROLE_ASSIGNED",
    "USER_ROLE_REVOKED",
    "USER_DEACTIVATED",
    "EVENT_RECEIVED",
    "EVENT_PROCESSED",
    "REPLAN_TRIGGERED",
]

# Known entity types
KNOWN_ENTITY_TYPES = [
    "CALENDAR",
    "CAPACITY",
    "EVENT",
    "MATERIAL",
    "PLAN",
    "PR",
    "ROLE",
    "SCENARIO",
    "SNAPSHOT",
    "SOD_RULE",
    "SUGGESTION",
    "USER",
]


class AuditService:
    """Service for audit trail operations."""

    @staticmethod
    def log(
        db: Session,
        *,
        actor: str,
        action: str,
        correlation_id: str,
        entity_type: str,
        entity_id: str,
        before: dict | None = None,
        after: dict | None = None,
        metadata: dict | None = None,
    ) -> AuditLog:
        """Create an audit log entry. Primary entry point for all audit writes."""
        return AuditRepository.create(
            db,
            actor=actor,
            action=action,
            correlation_id=correlation_id,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
            audit_metadata=metadata,
        )

    @staticmethod
    def get_entry(db: Session, audit_id: str) -> AuditLog | None:
        return AuditRepository.get_by_id(db, audit_id)

    @staticmethod
    def list_entries(
        db: Session,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        correlation_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        sort_order: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        return AuditRepository.list_entries(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            action=action,
            correlation_id=correlation_id,
            start_date=start_date,
            end_date=end_date,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def get_by_correlation(db: Session, correlation_id: str) -> list[AuditLog]:
        return AuditRepository.get_by_correlation(db, correlation_id)

    @staticmethod
    def get_for_entity(
        db: Session, entity_type: str, entity_id: str, limit: int = 50
    ) -> list[AuditLog]:
        return AuditRepository.get_for_entity(db, entity_type, entity_id, limit)

    @staticmethod
    def get_by_actor(
        db: Session,
        actor: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditLog]:
        return AuditRepository.get_by_actor(db, actor, start_date, end_date, limit)

    @staticmethod
    def get_stats(db: Session) -> dict:
        return AuditRepository.get_stats(db)

    @staticmethod
    def get_action_types(db: Session) -> list[str]:
        """Return union of known actions + actions found in DB."""
        db_actions = set(AuditRepository.get_distinct_actions(db))
        db_actions.update(KNOWN_ACTIONS)
        return sorted(db_actions)

    @staticmethod
    def get_entity_types(db: Session) -> list[str]:
        """Return union of known entity types + types found in DB."""
        db_types = set(AuditRepository.get_distinct_entity_types(db))
        db_types.update(KNOWN_ENTITY_TYPES)
        return sorted(db_types)

    @staticmethod
    def search(db: Session, query_str: str, limit: int = 50) -> list[AuditLog]:
        return AuditRepository.search(db, query_str, limit)

    @staticmethod
    def count_for_export(
        db: Session,
        *,
        entity_type: str | None = None,
        actor: str | None = None,
        actions: list[str] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        return AuditRepository.count(
            db,
            entity_type=entity_type,
            actor=actor,
            actions=actions,
            start_date=start_date,
            end_date=end_date,
        )
