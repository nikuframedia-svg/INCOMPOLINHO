# Plan service — persistence only
# All scheduling is done client-side via INCOMPOL PLAN.
# This service manages plan lifecycle (commit, query).

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from ...core.errors import APIException, ErrorCodes
from ...core.logging import get_logger
from ...domain.models.audit import AuditLog
from ...domain.models.plan import Plan, PlanStatus

logger = get_logger(__name__)


def canonical_plan_json(plan: dict[str, Any]) -> str:
    """Gera JSON canonico do plano (para hash)"""
    canonical = plan.copy()
    canonical.pop("plan_id", None)
    canonical.pop("created_at", None)
    canonical.pop("status", None)
    return json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def calculate_plan_hash(plan: dict[str, Any]) -> str:
    """Calcula hash SHA-256 do plano canonico"""
    canonical = canonical_plan_json(plan)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def commit_plan(
    db: Session,
    plan_id: UUID,
    correlation_id: str,
) -> Plan:
    """
    Promove candidate a plan_version oficial.
    Marca status=OFFICIAL e escreve audit.
    """
    plan = db.query(Plan).filter(Plan.plan_id == plan_id).first()
    if not plan:
        raise APIException(
            status_code=404,
            code=ErrorCodes.ERR_INVALID_UUID,
            message=f"Plan not found: {plan_id}",
            correlation_id=correlation_id,
        )

    if plan.status == PlanStatus.OFFICIAL:
        logger.info(
            "Plan already official",
            plan_id=str(plan_id),
            correlation_id=correlation_id,
        )
        return plan

    # Marcar como OFFICIAL
    plan.status = PlanStatus.OFFICIAL

    # Registrar no audit log
    audit_log_entry = AuditLog(
        audit_id=str(uuid4()),
        actor="system-plan-commit",
        action="PLAN_COMMITTED",
        correlation_id=correlation_id,
        entity_type="PLAN",
        entity_id=str(plan.plan_id),
        before={"status": "CANDIDATE"},
        after={"status": "OFFICIAL"},
        audit_metadata={"plan_id": str(plan_id)},
    )
    db.add(audit_log_entry)

    db.commit()
    db.refresh(plan)

    logger.info(
        "Plan committed successfully",
        plan_id=str(plan_id),
        correlation_id=correlation_id,
    )

    return plan
