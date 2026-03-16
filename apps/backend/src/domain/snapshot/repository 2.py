# Snapshot repository
# Conforme SP-BE-04

from uuid import UUID

from sqlalchemy.orm import Session

from ...core.errors import APIException, ErrorCodes
from ...core.logging import get_logger
from ...domain.models.snapshot import Snapshot

logger = get_logger(__name__)


class SnapshotRepository:
    """Repository para snapshots com regras de imutabilidade"""

    @staticmethod
    def get_by_id(db: Session, snapshot_id: UUID) -> Snapshot | None:
        """Obtém snapshot por ID"""
        return db.query(Snapshot).filter(Snapshot.snapshot_id == snapshot_id).first()

    @staticmethod
    def get_by_hash(db: Session, snapshot_hash: str) -> Snapshot | None:
        """Obtém snapshot por hash"""
        return db.query(Snapshot).filter(Snapshot.snapshot_hash == snapshot_hash).first()

    @staticmethod
    def list_all(
        db: Session, tenant_id: UUID | None = None, limit: int = 100, offset: int = 0
    ) -> list[Snapshot]:
        """Lista snapshots"""
        query = db.query(Snapshot)
        if tenant_id:
            query = query.filter(Snapshot.tenant_id == tenant_id)
        return query.order_by(Snapshot.created_at.desc()).limit(limit).offset(offset).all()

    @staticmethod
    def seal(db: Session, snapshot_id: UUID) -> Snapshot:
        """
        Sela snapshot (torna imutável).

        Conforme SP-BE-04: após sealed_at != null, snapshot não pode ser atualizado.
        """
        snapshot = SnapshotRepository.get_by_id(db, snapshot_id)
        if not snapshot:
            raise APIException(
                status_code=404,
                code=ErrorCodes.ERR_INVALID_UUID,
                message=f"Snapshot not found: {snapshot_id}",
            )

        if snapshot.sealed_at is not None:
            raise APIException(
                status_code=400,
                code=ErrorCodes.ERR_IMMUTABLE_ENTITY,
                message=f"Snapshot {snapshot_id} is already sealed",
            )

        from datetime import datetime

        snapshot.sealed_at = datetime.utcnow()
        db.commit()
        db.refresh(snapshot)

        logger.info(f"Snapshot sealed: {snapshot_id}")
        return snapshot

    @staticmethod
    def update_check_immutability(db: Session, snapshot_id: UUID) -> Snapshot:
        """
        Verifica se snapshot pode ser atualizado (não selado).

        Conforme SP-BE-04: qualquer correção cria novo snapshot.
        """
        snapshot = SnapshotRepository.get_by_id(db, snapshot_id)
        if not snapshot:
            raise APIException(
                status_code=404,
                code=ErrorCodes.ERR_INVALID_UUID,
                message=f"Snapshot not found: {snapshot_id}",
            )

        if snapshot.sealed_at is not None:
            raise APIException(
                status_code=400,
                code=ErrorCodes.ERR_IMMUTABLE_ENTITY,
                message=f"Cannot update sealed snapshot {snapshot_id}. Create a new snapshot instead.",
            )

        return snapshot
