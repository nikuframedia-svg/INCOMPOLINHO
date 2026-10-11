"""A plan refused at commit is a clear 409, never an Internal Server Error.

Rehearsal of 11/10/2026: a Gantt move on a plan saved before per-delivery
material raised LegacyMaterialPlanError at commit and the UI showed
"Internal Server Error".
"""

from fastapi.testclient import TestClient

from backend.api.copilot import app
from backend.plans.store import LegacyMaterialPlanError
from backend.scheduler.validation import PlanValidationError


def _client_raising(exc):
    route = "/__test_plan_validation__"

    async def boom():
        raise exc

    app.add_api_route(route, boom, methods=["POST"])
    try:
        return TestClient(app, raise_server_exceptions=False).post(route)
    finally:
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != route]


def test_legacy_plan_refusal_asks_for_recalculation_in_portuguese():
    response = _client_raising(LegacyMaterialPlanError([{"kind": "material_quantity"}]))
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "legacy_material_plan"
    assert detail["requires_recalculation"] is True
    assert "Recalcular plano" in detail["message"]
    assert "Internal Server Error" not in response.text


def test_invalid_plan_is_409_with_plain_message():
    response = _client_raising(PlanValidationError([{"kind": "machine_overlap"}]))
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_plan"
    assert detail["message"].startswith("Plano inválido: 1 conflito.")
    assert "O plano ativo não foi alterado." in detail["message"]
