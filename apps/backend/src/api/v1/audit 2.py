# Audit API endpoints — DB-backed
# Conforme C-15: Observability and Audit Trail

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...domain.audit.service import AuditService

audit_router = APIRouter(prefix="/audit", tags=["audit"])


# ==================== Schemas ====================


class EntityRef(BaseModel):
    entity_type: str
    entity_id: str


class AuditEntryResponse(BaseModel):
    audit_id: str
    timestamp: datetime
    actor: str
    action: str
    correlation_id: str
    entity_type: str
    entity_id: str
    before: dict | None = None
    after: dict | None = None
    metadata: dict | None = None
    entity_refs: list[EntityRef] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AuditStats(BaseModel):
    total_entries: int
    entries_last_24h: int
    entries_last_7d: int
    top_actions: list[dict]
    top_actors: list[dict]
    top_entity_types: list[dict]


class AuditExportRequest(BaseModel):
    start_date: datetime
    end_date: datetime
    entity_type: str | None = None
    actor: str | None = None
    actions: list[str] | None = None
    format: str = "json"  # json, csv


class AuditExportResponse(BaseModel):
    export_id: str
    status: str
    download_url: str | None = None
    entries_count: int
    created_at: datetime


# ==================== Helpers ====================


def _to_response(entry) -> dict:
    """Convert AuditLog ORM model to response dict."""
    # Extract entity_refs from audit_metadata if present
    meta = entry.audit_metadata or {}
    entity_refs = meta.pop("entity_refs", []) if isinstance(meta, dict) else []

    return {
        "audit_id": str(entry.audit_id),
        "timestamp": entry.timestamp,
        "actor": entry.actor,
        "action": entry.action,
        "correlation_id": str(entry.correlation_id),
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "before": entry.before,
        "after": entry.after,
        "metadata": meta if meta else None,
        "entity_refs": entity_refs,
    }


# ==================== Endpoints ====================


@audit_router.get("/entries", response_model=list[AuditEntryResponse])
async def list_audit_entries(
    entity_type: str | None = Query(
        None, description="Filter by entity type (SNAPSHOT, PLAN, PR, etc.)"
    ),
    entity_id: str | None = Query(None, description="Filter by entity ID"),
    actor: str | None = Query(None, description="Filter by actor (user or system)"),
    action: str | None = Query(None, description="Filter by action type"),
    correlation_id: str | None = Query(None, description="Filter by correlation ID"),
    start_date: datetime | None = Query(None, description="Start date filter"),
    end_date: datetime | None = Query(None, description="End date filter"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    """
    List audit trail entries with filtering and pagination.

    Supports filtering by:
    - entity_type: SNAPSHOT, PLAN, PR, SCENARIO, SUGGESTION, USER
    - entity_id: specific entity ID
    - actor: user ID or system service
    - action: specific action type
    - correlation_id: trace a full operation
    - date range: start_date and end_date
    """
    entries = AuditService.list_entries(
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
    return [_to_response(e) for e in entries]


@audit_router.get("/entries/{audit_id}", response_model=AuditEntryResponse)
async def get_audit_entry(audit_id: str, db: Session = Depends(get_db)):
    """Get a specific audit entry by ID."""
    entry = AuditService.get_entry(db, audit_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Audit entry not found")
    return _to_response(entry)


@audit_router.get("/correlation/{correlation_id}", response_model=list[AuditEntryResponse])
async def get_audit_by_correlation(correlation_id: str, db: Session = Depends(get_db)):
    """
    Get all audit entries for a correlation ID.
    Useful for tracing a complete operation end-to-end.
    """
    entries = AuditService.get_by_correlation(db, correlation_id)
    if not entries:
        raise HTTPException(status_code=404, detail="No audit entries found for correlation ID")
    return [_to_response(e) for e in entries]


@audit_router.get("/entity/{entity_type}/{entity_id}", response_model=list[AuditEntryResponse])
async def get_audit_for_entity(
    entity_type: str,
    entity_id: str,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    Get audit history for a specific entity.
    Returns all changes made to the entity in chronological order.
    """
    entries = AuditService.get_for_entity(db, entity_type, entity_id, limit)
    return [_to_response(e) for e in entries]


@audit_router.get("/actor/{actor_id}", response_model=list[AuditEntryResponse])
async def get_audit_by_actor(
    actor_id: str,
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    Get all actions performed by a specific actor (user or system).
    Useful for user activity auditing.
    """
    entries = AuditService.get_by_actor(db, actor_id, start_date, end_date, limit)
    return [_to_response(e) for e in entries]


@audit_router.get("/stats", response_model=AuditStats)
async def get_audit_stats(db: Session = Depends(get_db)):
    """
    Get audit trail statistics.
    Provides overview of system activity.
    """
    stats = AuditService.get_stats(db)
    return AuditStats(
        total_entries=stats["total"],
        entries_last_24h=stats["entries_24h"],
        entries_last_7d=stats["entries_7d"],
        top_actions=stats["top_actions"],
        top_actors=stats["top_actors"],
        top_entity_types=stats["top_entity_types"],
    )


@audit_router.get("/actions", response_model=list[str])
async def list_action_types(db: Session = Depends(get_db)):
    """
    List all distinct action types in the audit log.
    Useful for building filter dropdowns.
    """
    return AuditService.get_action_types(db)


@audit_router.get("/entity-types", response_model=list[str])
async def list_entity_types(db: Session = Depends(get_db)):
    """
    List all entity types tracked in the audit log.
    """
    return AuditService.get_entity_types(db)


@audit_router.post("/export", response_model=AuditExportResponse)
async def export_audit_log(request: AuditExportRequest, db: Session = Depends(get_db)):
    """
    Export audit log entries to file.
    Supports JSON and CSV formats.
    """
    export_id = f"export-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    count = AuditService.count_for_export(
        db,
        entity_type=request.entity_type,
        actor=request.actor,
        actions=request.actions,
        start_date=request.start_date,
        end_date=request.end_date,
    )

    return AuditExportResponse(
        export_id=export_id,
        status="COMPLETED",
        download_url=f"/api/v1/audit/export/{export_id}/download",
        entries_count=count,
        created_at=datetime.utcnow(),
    )


@audit_router.get("/search")
async def search_audit_log(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Full-text search across audit log entries.
    Searches in action, actor, entity_id, entity_type, and metadata.
    """
    entries = AuditService.search(db, q, limit)
    return [_to_response(e) for e in entries]
