"""REST API for persistent background robustness analyses."""

from __future__ import annotations

import copy
import hashlib
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.locks import commit_lock
from backend.api.plan_reads import PlanReadRoute
from backend.copilot.state import state
from backend.risk.jobs import manager
from backend.risk.robustness import PROFILE_SAMPLES, ROBUSTNESS_MODEL_VERSION
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
    from backend.plans.serialize import planning_input_fingerprints, schedule_fingerprint

    payload = {
        "robustness_model_version": ROBUSTNESS_MODEL_VERSION,
        "plan_revision": state.plan_revision,
        "dataset": state.dataset_info or {},
        "inputs": planning_input_fingerprints(state.engine_data, state.config)
        if state.engine_data is not None
        else None,
        "schedule": schedule_fingerprint(state.segments, state.lots),
        "mutations": state.active_mutations,
        "manual_edits": state.manual_edits,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


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
        job = manager.start(
            profile=request.profile,
            samples=samples,
            seed=request.seed,
            dataset_fingerprint=current_dataset_fingerprint(),
            segments=copy.deepcopy(state.segments),
            lots=copy.deepcopy(state.lots),
            engine_data=copy.deepcopy(state.engine_data),
            config=copy.deepcopy(state.config),
        )
    return {"status": "accepted", "job": job}


@router.get("/latest")
async def latest_robustness_run():
    job = manager.store.latest()
    if job is not None:
        job["stale"] = job["dataset_fingerprint"] != current_dataset_fingerprint()
    return {"job": job}


@router.get("/{job_id}")
async def get_robustness_run(job_id: str):
    job = manager.store.get(job_id)
    if job is None:
        raise HTTPException(404, f"Análise {job_id} não existe.")
    job["stale"] = job["dataset_fingerprint"] != current_dataset_fingerprint()
    return {"job": job}


@router.post("/{job_id}/cancel")
async def cancel_robustness_run(job_id: str):
    job = manager.cancel(job_id)
    if job is None:
        raise HTTPException(404, f"Análise {job_id} não existe.")
    return {"job": job}
