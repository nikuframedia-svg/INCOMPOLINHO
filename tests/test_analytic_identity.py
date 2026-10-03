import asyncio

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from backend.api.plan_reads import PlanReadRoute
from backend.copilot.state import CopilotState, state


def test_read_captures_state_and_returns_identity_without_changing_json(monkeypatch):
    live = CopilotState(plan_revision=10, dataset_info={"id": "isop-a"}, score={"otd": 91})
    monkeypatch.setattr(state, "__dict__", live.__dict__)
    app = FastAPI()
    router = APIRouter(route_class=PlanReadRoute)

    @router.get("/analytic")
    async def analytic():
        # Concurrent commits publish a new dictionary. This response keeps the
        # captured one even across an await and after the live state advances.
        object.__setattr__(state, "__dict__", CopilotState(plan_revision=11, dataset_info={"id": "isop-a"}, score={"otd": 12}).__dict__)
        await asyncio.sleep(0)
        return [state.score["otd"]]

    app.include_router(router)
    client = TestClient(app)
    response = client.get("/analytic", headers={"X-Dataset-Id": "isop-a", "X-Plan-Revision": "10"})
    assert response.status_code == 200
    assert response.json() == [91]
    assert response.headers["X-Dataset-Id"] == "isop-a"
    assert response.headers["X-Plan-Revision"] == "10"
    assert state.plan_revision == 11
    conflict = client.get("/analytic", headers={"X-Dataset-Id": "isop-a", "X-Plan-Revision": "10"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "stale_revision"
    assert client.get("/analytic").status_code == 200
