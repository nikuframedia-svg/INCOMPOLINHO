"""REST API for persistent background robustness analyses.

The result is information only: it never ranks, gates or approves a plan.
Jobs carry ``trigger`` ("auto" after each commit, "manual" from this API),
``plan_revision``, ``horizon_workdays``, ``model_version`` and ``anchor_day``.
``GET /latest?trigger=auto`` also re-queues the automatic analysis when the
planning day moved since it ran (the 10-working-day window starts today).
"""

from __future__ import annotations

import pickle

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.locks import commit_lock
from backend.api.plan_reads import PlanReadRoute
from backend.copilot.state import state
from backend.risk import jobs as risk_jobs
from backend.risk.jobs import TRIGGERS, detach_plan, manager
from backend.risk.plan_identity import planning_anchor_day, robustness_dataset_fingerprint
from backend.risk.robustness import PROFILE_SAMPLES
from backend.validation import IntegerInput

router = APIRouter(
    prefix="/api/data/robustness-runs", tags=["robustness"], route_class=PlanReadRoute
)


class RobustnessRunRequest(BaseModel):
    profile: str = "standard"
    samples: IntegerInput | None = None
    seed: IntegerInput = 42
    expected_revision: IntegerInput | None = None
    dataset_id: str | None = None


def _require_plan() -> None:
    if state.engine_data is None or state.config is None:
        raise HTTPException(503, "Sem plano carregado.")


def current_dataset_fingerprint() -> str:
    return robustness_dataset_fingerprint(state)


def _with_staleness(job: dict) -> dict:
    job["stale"] = job["dataset_fingerprint"] != current_dataset_fingerprint()
    return job


@router.post("")
async def start_robustness_run(request: RobustnessRunRequest):
    _require_plan()
    if request.profile not in PROFILE_SAMPLES:
        raise HTTPException(400, f"Perfil inválido: {request.profile}")
    samples = request.samples if request.samples is not None else PROFILE_SAMPLES[request.profile]
    if samples < 10 or samples > 2000:
        raise HTTPException(400, "samples deve estar entre 10 e 2000.")
    with commit_lock:
        if (
            request.expected_revision is not None
            and request.expected_revision != state.plan_revision
        ) or (
            request.dataset_id is not None
            and request.dataset_id != (state.dataset_info or {}).get("id")
        ):
            raise HTTPException(
                409,
                {
                    "code": "stale_revision",
                    "message": "O plano mudou. Atualiza os dados antes de testar.",
                },
            )
        blob = detach_plan(state.segments, state.lots, state.engine_data, state.config)
        fingerprint = current_dataset_fingerprint()
        revision = state.plan_revision
        anchor = planning_anchor_day(state.engine_data, state.config)
    segments, lots, engine_data, config = pickle.loads(blob)
    job = manager.start(
        profile=request.profile,
        samples=samples,
        seed=request.seed,
        dataset_fingerprint=fingerprint,
        segments=segments,
        lots=lots,
        engine_data=engine_data,
        config=config,
        trigger="manual",
        plan_revision=revision,
        anchor_day=anchor,
    )
    return {"status": "accepted", "job": job}


@router.get("/latest")
async def latest_robustness_run(trigger: str | None = None):
    if trigger is not None and trigger not in TRIGGERS:
        raise HTTPException(400, f"Origem inválida: {trigger}")
    job = manager.store.latest(trigger=trigger)
    refreshing = False
    if (
        trigger == "auto"
        and job is not None
        and risk_jobs.auto_robustness_enabled()
        and state.engine_data is not None
        and state.config is not None
        and job["plan_revision"] == state.plan_revision
        and job["anchor_day"] != planning_anchor_day(state.engine_data, state.config)
    ):
        # A new day moved the window: queue a fresh run, do no work here.
        refreshing = risk_jobs.request_refresh(state) or risk_jobs.refresh_pending()
    return {
        "job": _with_staleness(job) if job is not None else None,
        "refreshing": refreshing,
    }


@router.get("/{job_id}")
async def get_robustness_run(job_id: str):
    job = manager.store.get(job_id)
    if job is None:
        raise HTTPException(404, f"Análise {job_id} não existe.")
    return {"job": _with_staleness(job)}


@router.post("/{job_id}/cancel")
async def cancel_robustness_run(job_id: str):
    job = manager.cancel(job_id)
    if job is None:
        raise HTTPException(404, f"Análise {job_id} não existe.")
    return {"job": job}
