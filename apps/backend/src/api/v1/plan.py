# Plan API endpoints — persistence only
# All scheduling is done client-side via INCOMPOL PLAN.

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ...core.errors import APIException, ErrorCodes
from ...core.logging import get_logger
from ...core.middleware import correlation_filter
from ...db.base import get_db
from ...domain.plan.repository import PlanRepository
from ...domain.plan.service import commit_plan

logger = get_logger(__name__)

router = APIRouter(prefix="/plans", tags=["plans"])


class PlanResponse(BaseModel):
    """Response para GET /v1/plans/{plan_id}"""

    plan_id: str
    snapshot_id: str
    snapshot_hash: str
    plan_hash: str
    status: str
    created_at: str
    plan_params: dict
    plan_json: dict
    kpi_pack: dict
    explain_trace: dict | None = None

    model_config = ConfigDict(from_attributes=True)


@router.post("/{plan_id}/commit", response_model=PlanResponse)
async def commit_plan_endpoint(
    plan_id: str,
    db: Session = Depends(get_db),
):
    """
    Promove candidate a plan_version oficial.
    Marca status=OFFICIAL e escreve audit.
    """
    try:
        plan_uuid = UUID(plan_id)
    except ValueError:
        raise APIException(
            status_code=400,
            code=ErrorCodes.ERR_INVALID_UUID,
            message=f"Invalid plan ID format: {plan_id}",
            correlation_id=correlation_filter.correlation_id,
        )

    plan = commit_plan(
        db=db,
        plan_id=plan_uuid,
        correlation_id=correlation_filter.correlation_id,
    )

    return PlanResponse.model_validate(plan)


@router.get("/{plan_id}", response_model=PlanResponse)
async def get_plan(
    plan_id: str,
    db: Session = Depends(get_db),
):
    """Obtem plano por ID."""
    try:
        plan_uuid = UUID(plan_id)
    except ValueError:
        raise APIException(
            status_code=400,
            code=ErrorCodes.ERR_INVALID_UUID,
            message=f"Invalid plan ID format: {plan_id}",
            correlation_id=correlation_filter.correlation_id,
        )

    plan = PlanRepository.get_by_id(db, plan_uuid)
    if not plan:
        raise APIException(
            status_code=404,
            code=ErrorCodes.ERR_NOT_FOUND,
            message=f"Plan not found: {plan_id}",
            correlation_id=correlation_filter.correlation_id,
        )

    return PlanResponse.model_validate(plan)


@router.get("", response_model=list[PlanResponse])
async def list_plans(
    snapshot_id: str | None = Query(None, description="Filter by snapshot ID"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Lista planos com filtro opcional por snapshot."""
    if snapshot_id:
        try:
            snapshot_uuid = UUID(snapshot_id)
            plans = PlanRepository.list_by_snapshot(db, snapshot_uuid, limit=limit, offset=offset)
        except ValueError:
            raise APIException(
                status_code=400,
                code=ErrorCodes.ERR_INVALID_UUID,
                message=f"Invalid snapshot ID format: {snapshot_id}",
                correlation_id=correlation_filter.correlation_id,
            )
    else:
        plans = PlanRepository.list_all(db, limit=limit, offset=offset)

    return [PlanResponse.model_validate(plan) for plan in plans]
