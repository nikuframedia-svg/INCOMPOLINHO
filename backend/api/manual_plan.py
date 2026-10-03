"""Preview and apply direct production-lot moves."""

from __future__ import annotations

import copy
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from backend.api.locks import plan_mutation_lock
from backend.copilot.state import state
from backend.plans.manual_move import (
    ManualMoveError,
    ManualMoveInconclusive,
    ManualMoveResult,
    move_lot,
)
from backend.plans.manual_move_jobs import manager as move_job_manager
from backend.plans.serialize import planning_input_fingerprints
from backend.plans.transactions import clone_state, input_identity, plan_writer
from backend.scheduler.gates import authorize_application
from backend.scheduler.operators import compute_operator_alerts
from backend.scheduler.types import ScheduleResult
from backend.types import PlanAnchor
from backend.validation import strict_bool, strict_int

UTC = timezone.utc  # noqa: UP017 - Python 3.10 compatibility
router = APIRouter(prefix="/api/data/plan", tags=["manual-plan"])
logger = logging.getLogger(__name__)
MANUAL_MOVE_CONTRACT_VERSION = 2


def _require_plan() -> None:
    if state.engine_data is None or state.config is None or not state.segments:
        raise HTTPException(503, "Sem plano carregado.")


def _request_values(body: dict) -> tuple[str, int, str | None, int | None, bool, str, str]:
    lot_id = str(body.get("lot_id", "")).strip()
    if not lot_id:
        raise HTTPException(400, "lot_id é obrigatório.")
    try:
        target_day = strict_int(body.get("target_day"), "target_day")
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "target_day deve ser um inteiro.") from exc
    target_machine = str(body.get("target_machine", "")).strip() or None
    target_start_min = body.get("target_start_min")
    if target_start_min not in (None, ""):
        try:
            target_start_min = strict_int(target_start_min, "target_start_min")
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "target_start_min deve ser um inteiro.") from exc
    else:
        target_start_min = None
    try:
        confirm_delivery_risk = strict_bool(
            body.get("approve_exceptions", body.get("confirm_delivery_risk", False))
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    reason = str(body.get("reason", "")).strip()
    author = str(body.get("author", "utilizador")).strip() or "utilizador"
    return (
        lot_id,
        target_day,
        target_machine,
        target_start_min,
        confirm_delivery_risk,
        reason,
        author,
    )


def _candidate(body: dict) -> tuple[ManualMoveResult, bool]:
    lot_id, target_day, target_machine, target_start_min, confirmed, reason, author = (
        _request_values(body)
    )
    try:
        candidate = move_lot(
            state.segments,
            state.lots,
            state.score,
            state.engine_data,
            state.config,
            lot_id=lot_id,
            target_day=target_day,
            target_machine=target_machine,
            target_start_min=target_start_min,
            reason=reason,
            author=author,
            optimization_mode="quick",
        )
    except ManualMoveError as exc:
        detail: dict[str, object] = {"message": str(exc)}
        if isinstance(exc, ManualMoveInconclusive):
            detail["code"] = "verification_inconclusive"
        if exc.gate_report is not None:
            detail["gate_report"] = exc.gate_report
        raise HTTPException(409, detail) from exc
    return candidate, confirmed


def _response(candidate: ManualMoveResult, score_previous: dict | None = None) -> dict:
    return {
        "contract_version": MANUAL_MOVE_CONTRACT_VERSION,
        "status": "preview",
        "lot_id": candidate.lot_id,
        "source_days": candidate.source_days,
        "target_day": candidate.target_day,
        "target_start_min": candidate.target_start_min,
        "target_machine": candidate.target_machine,
        "score": candidate.score,
        "score_previous": score_previous if score_previous is not None else state.score,
        "delta": asdict(candidate.delta),
        "gate_report": candidate.gate_report,
        "improvement_report": candidate.improvement_report,
        "requires_confirmation": candidate.requires_confirmation,
        "delivery_warnings": candidate.delivery_warnings,
        "time_ms": candidate.time_ms,
    }


@router.post("/move-preview")
async def preview_move(body: dict):
    _require_plan()
    from backend.plans.candidates import previews
    from backend.plans.context import stage_state
    from backend.plans.transactions import clone_state

    async with plan_mutation_lock:
        baseline = clone_state(state)
    with stage_state(state, baseline):
        candidate, _confirmed = await run_in_threadpool(_candidate, body)
    preview = previews.put("manual", baseline, _preview_parameters(body), candidate)
    return {**_response(candidate, baseline.score), **preview.identity()}


def _preview_parameters(body):
    lot_id, day, machine, start, *_ = _request_values(body)
    return {
        "lot_id": lot_id,
        "target_day": day,
        "target_machine": machine,
        "target_start_min": start,
    }


def _job_response(job_id: str) -> dict:
    job = move_job_manager.get(job_id)
    if job is None:
        raise HTTPException(404, "Esta verificação não existe.")
    result = None
    if job["status"] in {"ready", "applied"}:
        try:
            baseline = clone_state(state)
            candidate, score_previous = move_job_manager.result(
                job_id,
                dataset_id=str((baseline.dataset_info or {}).get("id", "")),
                plan_revision=baseline.plan_revision,
                input_fingerprints=planning_input_fingerprints(
                    baseline.engine_data, baseline.config
                ),
                origin=input_identity(baseline),
            )
            result = _response(candidate, score_previous)
        except ValueError:
            if job["status"] == "ready":
                job = {
                    **job,
                    "status": "failed",
                    "message": "O plano mudou durante a verificação",
                    "error": "O plano mudou durante a verificação; verifica novamente.",
                }
    return {**job, "result": result}


@router.post("/move-preview-jobs")
async def start_move_preview_job(body: dict):
    _require_plan()
    (
        lot_id,
        target_day,
        target_machine,
        target_start_min,
        _confirmed,
        reason,
        author,
    ) = _request_values(body)
    async with plan_mutation_lock:
        baseline = clone_state(state)
        job = move_job_manager.start(
            segments=baseline.segments,
            lots=baseline.lots,
            score=baseline.score,
            engine_data=baseline.engine_data,
            config=baseline.config,
            dataset_id=str((baseline.dataset_info or {}).get("id", "")),
            base_revision=baseline.plan_revision,
            lot_id=lot_id,
            target_day=target_day,
            target_machine=target_machine,
            target_start_min=target_start_min,
            reason=reason,
            author=author,
            origin=input_identity(baseline),
        )
    return {"status": job["status"], "job": _job_response(job["id"])}


@router.get("/move-preview-jobs/{job_id}")
async def get_move_preview_job(job_id: str):
    return {"job": _job_response(job_id)}


@router.post("/move-preview-jobs/{job_id}/cancel")
async def cancel_move_preview_job(job_id: str):
    job = move_job_manager.cancel(job_id)
    if job is None:
        raise HTTPException(404, "Esta verificação não existe.")
    return {"job": {**job, "result": None}}


def _require_matching_preview_request(
    candidate: ManualMoveResult,
    body: dict,
) -> None:
    try:
        requested = (
            str(body["lot_id"]).strip(),
            strict_int(body["target_day"], "target_day"),
            str(body["target_machine"]).strip(),
            strict_int(body["target_start_min"], "target_start_min"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            409,
            "O pedido já não corresponde à verificação; verifica novamente.",
        ) from exc
    verified = (
        candidate.lot_id,
        candidate.target_day,
        candidate.target_machine,
        candidate.target_start_min,
    )
    if requested != verified:
        raise HTTPException(
            409,
            "O lote, máquina, dia ou hora mudaram desde a verificação; verifica novamente.",
        )


@router.post("/move-apply")
@plan_writer
async def apply_move(body: dict):
    _require_plan()
    async with plan_mutation_lock:
        from backend.api.data import _require_expected_revision

        _require_expected_revision(body)
        preview_job_id = str(body.get("preview_job_id", "")).strip()
        if preview_job_id:
            try:
                candidate, _score_previous = move_job_manager.result(
                    preview_job_id,
                    dataset_id=str((state.dataset_info or {}).get("id", "")),
                    plan_revision=state.plan_revision,
                    input_fingerprints=planning_input_fingerprints(state.engine_data, state.config),
                    origin=input_identity(state),
                )
            except ValueError as exc:
                raise HTTPException(
                    409, {"code": "stale_preview", "message": str(exc)}
                ) from exc
            _require_matching_preview_request(candidate, body)
            confirmed = bool(
                body.get(
                    "approve_exceptions",
                    body.get("confirm_delivery_risk", False),
                )
            )
        else:
            from backend.plans.candidates import previews

            preview = previews.get(
                body.get("candidate_id"), "manual", state, _preview_parameters(body)
            )
            candidate = copy.deepcopy(preview.result)
            confirmed = bool(
                body.get("approve_exceptions", body.get("confirm_delivery_risk", False))
            )
        try:
            approval = authorize_application(
                candidate.gate_report,
                approve_exceptions=confirmed,
                approval_reason=str(body.get("approval_reason", body.get("reason", ""))),
                approval_author=str(body.get("approval_author", body.get("author", ""))),
            )
        except ValueError as exc:
            raise HTTPException(
                409,
                {
                    "message": str(exc),
                    "requires_confirmation": True,
                    "delivery_warnings": candidate.delivery_warnings,
                    "candidate": _response(candidate),
                },
            ) from exc

        response_payload = _response(candidate)

        # Persist both sides of the manual change. Failure is non-blocking,
        # matching the scheduler's snapshot policy.
        previous_version = None
        if state.dataset_info is not None:
            try:
                previous_version = state.persist_current_plan(
                    name="Antes da edição manual",
                    source="auto",
                    note=f"Antes de mover {candidate.lot_id}",
                    is_auto=True,
                )
            except Exception:
                logger.exception("Failed to persist pre-edit plan snapshot")

        state.save_current()
        target_date = str(state.engine_data.workdays[candidate.target_day])[:10]
        target_at = (
            f"{target_date}T{candidate.target_start_min // 60:02d}:"
            f"{candidate.target_start_min % 60:02d}"
        )
        state.engine_data.plan_anchors = [
            anchor for anchor in state.engine_data.plan_anchors if anchor.lot_id != candidate.lot_id
        ]
        state.engine_data.plan_anchors.append(
            PlanAnchor(
                lot_id=candidate.lot_id,
                machine_id=candidate.target_machine,
                start_at=target_at,
                reason=str(body.get("reason", "")),
                author=str(body.get("author", "utilizador")),
            )
        )
        edit = {
            "id": f"edit_{uuid4().hex[:12]}",
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "lot_id": candidate.lot_id,
            "source_days": candidate.source_days,
            "target_day": candidate.target_day,
            "target_start_min": candidate.target_start_min,
            "target_machine": candidate.target_machine,
            "reason": str(body.get("reason", "")),
            "author": str(body.get("author", "utilizador")),
            "previous_version_id": (previous_version.get("id") if previous_version else None),
            "delivery_risk_confirmed": bool(candidate.requires_confirmation and confirmed),
        }
        state.manual_edits = [*state.manual_edits, edit]
        if approval is not None:
            state.approvals.append({**approval, "action": "manual_move"})
        journal = copy.deepcopy(state.journal_entries or [])
        journal.append(
            {
                "step": "manual_move",
                "severity": "warn" if candidate.requires_confirmation else "info",
                "message": (
                    f"{candidate.lot_id} movido para {candidate.target_machine}, "
                    f"dia {candidate.target_day}."
                ),
                "metadata": edit,
                "elapsed_ms": candidate.time_ms,
            }
        )
        result = ScheduleResult(
            segments=candidate.segments,
            lots=candidate.lots,
            score=candidate.score,
            time_ms=candidate.time_ms,
            warnings=[*state.warnings, *candidate.delivery_warnings],
            operator_alerts=compute_operator_alerts(
                candidate.segments,
                state.engine_data,
                state.config,
            ),
            audit_trail=None,
            journal=journal,
            gate_report=candidate.gate_report,
            improvement_report=copy.deepcopy(candidate.improvement_report),
        )
        state.update_schedule(
            result,
            plan_source="manual_edit",
            plan_note=f"{candidate.lot_id} → dia {candidate.target_day}",
        )
        if preview_job_id:
            from backend.plans.context import after_commit

            after_commit(lambda: move_job_manager.mark_applied(preview_job_id))

    return {
        **response_payload,
        "status": "applied",
        "edit": edit,
        "can_revert": True,
        "plan_revision": state.plan_revision,
    }


@router.get("/edits")
async def get_manual_edits():
    return {
        "active": bool(state.manual_edits),
        "edits": state.manual_edits,
        "can_revert": state.saved_schedule is not None,
    }
