# Audit repository — DB access for audit_log table
# Conforme C-15: append-only audit trail

import uuid
from datetime import datetime, timedelta

from sqlalchemy import String, asc, cast, desc, func, or_
from sqlalchemy.orm import Session

from ...core.logging import get_logger
from ..models.audit import AuditLog

logger = get_logger(__name__)


class AuditRepository:
    """Repository for audit_log table (append-only)."""

    @staticmethod
    def create(
        db: Session,
        *,
        actor: str,
        action: str,
        correlation_id: str,
        entity_type: str,
        entity_id: str,
        before: dict | None = None,
        after: dict | None = None,
        audit_metadata: dict | None = None,
    ) -> AuditLog:
        """Create a new audit log entry (append-only)."""
        entry = AuditLog(
            audit_id=uuid.uuid4(),
            timestamp=datetime.utcnow(),
            actor=actor,
            action=action,
            correlation_id=uuid.UUID(correlation_id)
            if isinstance(correlation_id, str)
            else correlation_id,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
            audit_metadata=audit_metadata,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        logger.info(
            f"Audit entry created: {entry.audit_id} action={action} entity={entity_type}/{entity_id}"
        )
        return entry

    @staticmethod
    def get_by_id(db: Session, audit_id: str) -> AuditLog | None:
        """Get a single audit entry by ID."""
        try:
            uid = uuid.UUID(audit_id)
        except ValueError:
            return None
        return db.query(AuditLog).filter(AuditLog.audit_id == uid).first()

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
        """List audit entries with filtering, sorting, and pagination."""
        query = db.query(AuditLog)

        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)
        if entity_id:
            query = query.filter(AuditLog.entity_id == entity_id)
        if actor:
            query = query.filter(AuditLog.actor == actor)
        if action:
            query = query.filter(AuditLog.action == action)
        if correlation_id:
            try:
                cid = uuid.UUID(correlation_id)
                query = query.filter(AuditLog.correlation_id == cid)
            except ValueError:
                pass
        if start_date:
            query = query.filter(AuditLog.timestamp >= start_date)
        if end_date:
            query = query.filter(AuditLog.timestamp <= end_date)

        order_fn = desc if sort_order == "desc" else asc
        query = query.order_by(order_fn(AuditLog.timestamp))

        return query.offset(offset).limit(limit).all()

    @staticmethod
    def get_by_correlation(db: Session, correlation_id: str) -> list[AuditLog]:
        """Get all entries for a correlation ID (end-to-end trace)."""
        try:
            cid = uuid.UUID(correlation_id)
        except ValueError:
            return []
        return (
            db.query(AuditLog)
            .filter(AuditLog.correlation_id == cid)
            .order_by(asc(AuditLog.timestamp))
            .all()
        )

    @staticmethod
    def get_for_entity(
        db: Session,
        entity_type: str,
        entity_id: str,
        limit: int = 50,
    ) -> list[AuditLog]:
        """Get audit history for a specific entity (direct match + entity_refs in metadata)."""
        direct = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == entity_type,
                AuditLog.entity_id == entity_id,
            )
            .order_by(desc(AuditLog.timestamp))
            .limit(limit)
            .all()
        )
        return direct

    @staticmethod
    def get_by_actor(
        db: Session,
        actor: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditLog]:
        """Get all actions by a specific actor."""
        query = db.query(AuditLog).filter(AuditLog.actor == actor)
        if start_date:
            query = query.filter(AuditLog.timestamp >= start_date)
        if end_date:
            query = query.filter(AuditLog.timestamp <= end_date)
        return query.order_by(desc(AuditLog.timestamp)).limit(limit).all()

    @staticmethod
    def get_stats(db: Session) -> dict:
        """Compute audit statistics from the DB."""
        now = datetime.utcnow()
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)

        total = db.query(func.count(AuditLog.audit_id)).scalar() or 0
        entries_24h = (
            db.query(func.count(AuditLog.audit_id)).filter(AuditLog.timestamp >= day_ago).scalar()
            or 0
        )
        entries_7d = (
            db.query(func.count(AuditLog.audit_id)).filter(AuditLog.timestamp >= week_ago).scalar()
            or 0
        )

        # Top actions
        top_actions = (
            db.query(AuditLog.action, func.count(AuditLog.audit_id).label("cnt"))
            .group_by(AuditLog.action)
            .order_by(desc("cnt"))
            .limit(10)
            .all()
        )

        # Top actors
        top_actors = (
            db.query(AuditLog.actor, func.count(AuditLog.audit_id).label("cnt"))
            .group_by(AuditLog.actor)
            .order_by(desc("cnt"))
            .limit(10)
            .all()
        )

        # Top entity types
        top_entity_types = (
            db.query(AuditLog.entity_type, func.count(AuditLog.audit_id).label("cnt"))
            .group_by(AuditLog.entity_type)
            .order_by(desc("cnt"))
            .limit(10)
            .all()
        )

        return {
            "total": total,
            "entries_24h": entries_24h,
            "entries_7d": entries_7d,
            "top_actions": [{"action": a, "count": c} for a, c in top_actions],
            "top_actors": [{"actor": a, "count": c} for a, c in top_actors],
            "top_entity_types": [{"entity_type": t, "count": c} for t, c in top_entity_types],
        }

    @staticmethod
    def get_distinct_actions(db: Session) -> list[str]:
        """Get all distinct action types in the audit log."""
        rows = db.query(AuditLog.action).distinct().order_by(AuditLog.action).all()
        return [r[0] for r in rows]

    @staticmethod
    def get_distinct_entity_types(db: Session) -> list[str]:
        """Get all distinct entity types in the audit log."""
        rows = db.query(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type).all()
        return [r[0] for r in rows]

    @staticmethod
    def search(db: Session, query_str: str, limit: int = 50) -> list[AuditLog]:
        """Full-text search across audit entries (action, actor, entity_id, entity_type)."""
        pattern = f"%{query_str}%"
        return (
            db.query(AuditLog)
            .filter(
                or_(
                    AuditLog.action.ilike(pattern),
                    AuditLog.actor.ilike(pattern),
                    AuditLog.entity_id.ilike(pattern),
                    AuditLog.entity_type.ilike(pattern),
                    cast(AuditLog.audit_metadata, String).ilike(pattern),
                )
            )
            .order_by(desc(AuditLog.timestamp))
            .limit(limit)
            .all()
        )

    @staticmethod
    def count(
        db: Session,
        *,
        entity_type: str | None = None,
        actor: str | None = None,
        actions: list[str] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        """Count audit entries matching filters (for export)."""
        query = db.query(func.count(AuditLog.audit_id))
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)
        if actor:
            query = query.filter(AuditLog.actor == actor)
        if actions:
            query = query.filter(AuditLog.action.in_(actions))
        if start_date:
            query = query.filter(AuditLog.timestamp >= start_date)
        if end_date:
            query = query.filter(AuditLog.timestamp <= end_date)
        return query.scalar() or 0
