# Snapshots endpoints
# Conforme SP-BE-04

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ...core.errors import APIException, ErrorCodes
from ...core.logging import get_logger
from ...core.middleware import correlation_filter
from ...db.base import get_db
from ...domain.models.snapshot import Snapshot
from ...domain.snapshot.repository import SnapshotRepository

logger = get_logger(__name__)

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


class SnapshotResponse(BaseModel):
    snapshot_id: str
    tenant_id: str
    created_at: str
    snapshot_hash: str
    series_semantics: str
    setup_time_uom: str | None
    mo_uom: str | None
    trust_index_overall: float
    sealed_at: str | None
    snapshot_json: dict
    gate_status: str  # QUARANTINE, SEMI_AUTO, AUTO_ELIGIBLE

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot) -> "SnapshotResponse":
        """Cria response a partir de snapshot, incluindo gate_status"""
        data = cls.model_validate(snapshot)
        ti = float(snapshot.trust_index_overall)
        data.gate_status = (
            "AUTO_ELIGIBLE" if ti >= 0.7 else ("SEMI_AUTO" if ti >= 0.5 else "QUARANTINE")
        )
        return data


@router.get("", response_model=list[SnapshotResponse])
async def list_snapshots(
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Lista snapshots.

    - **tenant_id**: Filtrar por tenant (opcional)
    - **limit**: Número máximo de resultados (1-1000)
    - **offset**: Offset para paginação
    """
    tenant_uuid = UUID(tenant_id) if tenant_id else None
    snapshots = SnapshotRepository.list_all(db, tenant_uuid, limit=limit, offset=offset)

    return [SnapshotResponse.from_snapshot(snapshot) for snapshot in snapshots]


@router.get("/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot(
    snapshot_id: str,
    db: Session = Depends(get_db),
):
    """
    Obtém snapshot por ID.

    - **snapshot_id**: UUID do snapshot
    """
    try:
        snapshot_uuid = UUID(snapshot_id)
    except ValueError:
        raise APIException(
            status_code=400,
            code=ErrorCodes.ERR_INVALID_UUID,
            message=f"Invalid snapshot ID format: {snapshot_id}",
            correlation_id=correlation_filter.correlation_id,
        )

    snapshot = SnapshotRepository.get_by_id(db, snapshot_uuid)
    if not snapshot:
        raise APIException(
            status_code=404,
            code=ErrorCodes.ERR_NOT_FOUND,
            message=f"Snapshot not found: {snapshot_id}",
            correlation_id=correlation_filter.correlation_id,
        )

    return SnapshotResponse.from_snapshot(snapshot)


@router.post("/{snapshot_id}/seal", response_model=SnapshotResponse)
async def seal_snapshot(
    snapshot_id: str,
    db: Session = Depends(get_db),
):
    """
    Sela snapshot (torna imutável).

    Conforme SP-BE-04: após sealed_at != null, snapshot não pode ser atualizado.
    Qualquer correção deve criar novo snapshot.

    - **snapshot_id**: UUID do snapshot
    """
    try:
        snapshot_uuid = UUID(snapshot_id)
    except ValueError:
        raise APIException(
            status_code=400,
            code=ErrorCodes.ERR_INVALID_UUID,
            message=f"Invalid snapshot ID format: {snapshot_id}",
            correlation_id=correlation_filter.correlation_id,
        )

    snapshot = SnapshotRepository.seal(db, snapshot_uuid)
    return SnapshotResponse.from_snapshot(snapshot)
