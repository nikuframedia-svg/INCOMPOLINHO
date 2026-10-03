"""REST API for persistent production-plan snapshots."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.locks import plan_mutation_lock
from backend.copilot.state import state
from backend.plans.restore import restore_plan_into_state
from backend.plans.transactions import plan_writer
from backend.validation import strict_bool

router = APIRouter(prefix="/api/data/plans", tags=["plans"])


def _require_active_plan() -> None:
    if state.engine_data is None:
        raise HTTPException(503, "Sem plano carregado para guardar.")


@router.get("")
async def list_plans(limit: int = 100):
    plans = state.get_plans_store().list(limit, exclude_scenarios=True)
    return {"plans": plans}


@router.post("")
async def save_plan(body: dict):
    _require_active_plan()
    name = str(body.get("name", "")).strip()
    note = str(body.get("note", "")).strip()
    if not name:
        raise HTTPException(400, "O nome do plano é obrigatório.")
    if len(name) > 120:
        raise HTTPException(400, "O nome do plano não pode exceder 120 caracteres.")
    if len(note) > 1000:
        raise HTTPException(400, "A nota não pode exceder 1000 caracteres.")
    async with plan_mutation_lock:
        saved = state.persist_current_plan(
            name=name,
            source="user",
            note=note,
            is_auto=False,
        )
    return {"status": "ok", "plan": saved}


@router.post("/{plan_id}/restore")
@plan_writer
async def restore_plan(plan_id: str, body: dict):
    from backend.api.data import _approval_args, _require_expected_revision

    try:
        recalculate = strict_bool(body.get("recalculate", False), "recalculate")
        approval = _approval_args(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    async with plan_mutation_lock:
        expected_revision = _require_expected_revision(body)
        plan = state.get_plans_store().get(plan_id)
        if plan is None:
            raise HTTPException(404, f"Plano {plan_id} não existe.")
        if plan.get("source") == "scenario":
            raise HTTPException(
                409,
                {
                    "code": "scenario_route_required",
                    "message": "Aplica este cenario pela rota de cenarios.",
                },
            )
        try:
            restored = restore_plan_into_state(
                plan,
                state,
                autosave=True,
                expected_revision=expected_revision,
                recalculate=recalculate,
                **approval,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(409, f"Não foi possível repor o plano: {exc}") from exc
    return {"status": "ok", **restored}


@router.delete("/{plan_id}")
async def delete_plan(plan_id: str):
    try:
        deleted = state.get_plans_store().delete(plan_id)
    except ValueError as exc:
        raise HTTPException(
            409, {"code": "active_plan_protected", "message": "O plano ativo nao pode ser apagado."}
        ) from exc
    if not deleted:
        raise HTTPException(404, f"Plano {plan_id} não existe.")
    return {"status": "ok", "deleted": plan_id}
