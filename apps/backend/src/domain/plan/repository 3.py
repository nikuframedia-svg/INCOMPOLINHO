# Plan repository
# Conforme SP-BE-06

from uuid import UUID

from sqlalchemy.orm import Session

from ...core.logging import get_logger
from ...domain.models.plan import Plan

logger = get_logger(__name__)


class PlanRepository:
    """Repository para planos"""

    @staticmethod
    def get_by_id(db: Session, plan_id: UUID) -> Plan | None:
        """Obtém plano por ID"""
        return db.query(Plan).filter(Plan.plan_id == plan_id).first()

    @staticmethod
    def get_by_hash(db: Session, plan_hash: str) -> Plan | None:
        """Obtém plano por hash"""
        return db.query(Plan).filter(Plan.plan_hash == plan_hash).first()

    @staticmethod
    def list_by_snapshot(
        db: Session, snapshot_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Plan]:
        """Lista planos por snapshot"""
        return (
            db.query(Plan)
            .filter(Plan.snapshot_id == snapshot_id)
            .order_by(Plan.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    @staticmethod
    def list_all(db: Session, limit: int = 100, offset: int = 0) -> list[Plan]:
        """Lista todos os planos"""
        return db.query(Plan).order_by(Plan.created_at.desc()).limit(limit).offset(offset).all()
