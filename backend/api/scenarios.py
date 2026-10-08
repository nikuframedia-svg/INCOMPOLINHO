"""Persistent, protected what-if scenarios."""

from __future__ import annotations

import copy
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.api.locks import plan_mutation_lock
from backend.copilot.state import state
from backend.plans.context import stage_state
from backend.plans.restore import restore_plan_into_state
from backend.plans.serialize import serialize_simulation_snapshot, serialize_snapshot
from backend.plans.transactions import clone_state, input_identity, plan_writer

router = APIRouter(prefix="/api/data/scenarios", tags=["scenarios"])


class ScenarioMutation(BaseModel):
    type: str
    params: dict = Field(default_factory=dict)


class SaveScenarioRequest(BaseModel):
    name: str
    note: str = ""
    mutations: list[ScenarioMutation]
    candidate_id: str | None = None


def _require_plan() -> None:
    if state.engine_data is None or state.config is None:
        raise HTTPException(503, "Sem plano carregado.")


@router.get("")
async def list_scenarios():
    plans = state.get_plans_store().list(500, source="scenario")
    return {"scenarios": plans}


@router.post("")
async def save_scenario(request: SaveScenarioRequest):
    """Calculate and save a named scenario without touching the true plan."""

    name = request.name.strip()
    if not name:
        raise HTTPException(400, "O nome do cenário é obrigatório.")
    if len(name) > 120:
        raise HTTPException(400, "O nome do cenário não pode exceder 120 caracteres.")
    if not request.mutations:
        raise HTTPException(400, "Adiciona pelo menos uma alteração.")

    from backend.api.data import (
        _compose_active_mutations,
        _pending_mutations,
        _plan_validation_error,
        _validate_mutations,
    )

    async with plan_mutation_lock:
        baseline = clone_state(state)

    def calculate_and_save():
        with stage_state(state, baseline):
            _require_plan()
            validated = _validate_mutations(request.mutations, require_non_empty=True)
            mutations = _compose_active_mutations(validated)
            pending = _pending_mutations(validated)
            origin = input_identity(baseline)
            baseline_payload = serialize_snapshot(baseline)
            baseline_score = copy.deepcopy(baseline.score)
            from backend.plans.candidates import previews

            candidate = previews.get(
                request.candidate_id, "simulation", baseline, {"mutations": pending}
            )
            with candidate.lock:
                result = copy.deepcopy(candidate.result)
            payload = serialize_simulation_snapshot(
                baseline,
                result,
                mutations,
                baseline_payload=baseline_payload,
            )
            payload["scenario_origin"] = origin
        saved = baseline.get_plans_store().save(
            name=name,
            source="scenario",
            origin=str((baseline.dataset_info or {}).get("filename", "")),
            note=request.note.strip(),
            payload=payload,
            score=result.score,
            gate_report=result.gate_report,
            is_auto=False,
        )
        return saved, baseline_score, result

    try:
        saved, baseline_score, result = await run_in_threadpool(calculate_and_save)
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc
    return {
        "status": "saved",
        "scenario": saved,
        "score_baseline": baseline_score,
        "score_scenario": result.score,
        "delta": asdict(result.delta),
        "gate_report": result.gate_report,
    }


@router.post("/{scenario_id}/apply")
@plan_writer
async def apply_scenario(scenario_id: str, body: dict):
    """Separate, explicit action that promotes a saved scenario to reality."""

    _require_plan()
    if "expected_revision" not in body:
        raise HTTPException(400, "expected_revision é obrigatório.")
    async with plan_mutation_lock:
        from backend.api.data import _require_expected_revision

        _require_expected_revision(body)
        plan = state.get_plans_store().get(scenario_id)
        if plan is None or plan.get("source") != "scenario":
            raise HTTPException(404, f"Cenário {scenario_id} não existe.")
        payload = plan.get("payload") or {}
        payload_dataset = payload.get("dataset_info") or {}
        scenario_dataset_id = str(payload_dataset.get("id", ""))
        current_dataset_id = str((state.dataset_info or {}).get("id", ""))
        if not scenario_dataset_id or scenario_dataset_id != current_dataset_id:
            raise HTTPException(
                409,
                "O cenário pertence a outro ISOP ou não identifica a sua origem; "
                "calcula-o novamente sobre o plano atual.",
            )
        if int(payload.get("plan_revision", -1)) != int(state.plan_revision):
            raise HTTPException(
                409,
                "O plano mudou depois de o cenário ser calculado; calcula-o novamente.",
            )
        scenario_origin = payload.get("scenario_origin")
        if (
            not isinstance(scenario_origin, dict)
            or not scenario_origin.get("dataset_id")
            or scenario_origin != input_identity(state)
        ):
            raise HTTPException(
                409,
                "O plano mudou e a origem completa do cenário já não corresponde; "
                "calcula-o novamente antes de aplicar.",
            )
        try:
            state.persist_current_plan(
                name="Antes de aplicar cenário",
                source="auto",
                note=f"Antes de aplicar {plan['name']}",
                is_auto=True,
            )
            restored = restore_plan_into_state(
                plan,
                state,
                autosave=True,
                preserve_exact=True,
                expected_revision=body.get("expected_revision"),
                approve_exceptions=bool(
                    body.get(
                        "approve_exceptions",
                        body.get("confirm_delivery_risk", False),
                    )
                ),
                approval_reason=str(body.get("approval_reason", body.get("reason", ""))),
                approval_author=str(body.get("approval_author", body.get("author", ""))),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                409,
                f"O cenário tem conflitos físicos e não pode ser aplicado: {exc}",
            ) from exc
    return {"status": "applied", **restored}


@router.delete("/{scenario_id}")
async def delete_scenario(scenario_id: str):
    plan = state.get_plans_store().get(scenario_id)
    if plan is None or plan.get("source") != "scenario":
        raise HTTPException(404, f"Cenário {scenario_id} não existe.")
    state.get_plans_store().delete(scenario_id)
    return {"status": "ok", "deleted": scenario_id}
