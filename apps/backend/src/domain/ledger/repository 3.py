# Decision Ledger — Repository (CRUD estático)
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import DecisionEntry


class LedgerRepository:
    @staticmethod
    def create(db: Session, entry: DecisionEntry) -> DecisionEntry:
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry

    @staticmethod
    def get_by_id(db: Session, entry_id: UUID) -> DecisionEntry | None:
        return db.query(DecisionEntry).filter(DecisionEntry.id == entry_id).first()

    @staticmethod
    def list_entries(
        db: Session,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        decision_type: str | None = None,
        incentive_category: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DecisionEntry]:
        query = db.query(DecisionEntry)

        if tenant_id:
            query = query.filter(DecisionEntry.tenant_id == tenant_id)
        if user_id:
            query = query.filter(DecisionEntry.user_id == user_id)
        if decision_type:
            query = query.filter(DecisionEntry.decision_type == decision_type)
        if incentive_category:
            query = query.filter(DecisionEntry.incentive_category == incentive_category)
        if start_date:
            query = query.filter(DecisionEntry.created_at >= start_date)
        if end_date:
            query = query.filter(DecisionEntry.created_at <= end_date)

        return query.order_by(DecisionEntry.created_at.desc()).limit(limit).offset(offset).all()

    @staticmethod
    def approve(db: Session, entry_id: UUID, approved_by: UUID) -> DecisionEntry | None:
        entry = db.query(DecisionEntry).filter(DecisionEntry.id == entry_id).first()
        if not entry:
            return None
        entry.approved_by = approved_by
        entry.approved_at = datetime.utcnow()
        db.commit()
        db.refresh(entry)
        return entry

    @staticmethod
    def update_outcome(
        db: Session,
        entry_id: UUID,
        outcome: dict,
        outcome_variance: str,
    ) -> DecisionEntry | None:
        entry = db.query(DecisionEntry).filter(DecisionEntry.id == entry_id).first()
        if not entry:
            return None
        entry.outcome = outcome
        entry.outcome_variance = outcome_variance
        db.commit()
        db.refresh(entry)
        return entry

    @staticmethod
    def get_stats(db: Session, tenant_id: UUID | None = None) -> dict:
        query = db.query(DecisionEntry)
        if tenant_id:
            query = query.filter(DecisionEntry.tenant_id == tenant_id)

        total = query.count()

        total_cost = (
            db.query(func.coalesce(func.sum(DecisionEntry.deviation_cost), 0))
            .filter(DecisionEntry.tenant_id == tenant_id if tenant_id else True)
            .scalar()
        )

        by_category = dict(
            db.query(DecisionEntry.incentive_category, func.count())
            .filter(DecisionEntry.tenant_id == tenant_id if tenant_id else True)
            .group_by(DecisionEntry.incentive_category)
            .all()
        )

        by_type = dict(
            db.query(DecisionEntry.decision_type, func.count())
            .filter(DecisionEntry.tenant_id == tenant_id if tenant_id else True)
            .group_by(DecisionEntry.decision_type)
            .all()
        )

        pending = query.filter(
            DecisionEntry.governance_level.in_(["L4", "L5"]),
            DecisionEntry.approved_by.is_(None),
        ).count()

        return {
            "total_entries": total,
            "total_deviation_cost": total_cost,
            "entries_by_category": by_category,
            "entries_by_type": by_type,
            "pending_approvals": pending,
        }
