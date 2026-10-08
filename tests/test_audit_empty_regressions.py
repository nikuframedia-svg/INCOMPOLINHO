"""Empty plans remain loaded, durable and usable for subsequent demand."""

from datetime import datetime
from unittest.mock import Mock

from backend.api import plans
from backend.copilot.state import CopilotState, state
from backend.plans.restore import restore_plan_into_state
from tests.test_scenario_identity import services  # noqa: F401

refresh_analytics = CopilotState._refresh_analytics


def test_cancel_all_save_restart_and_add_new_demand(services, monkeypatch):  # noqa: F811
    clock = Mock(wraps=datetime)
    fixed = datetime.fromisoformat(state.engine_data.workdays[0] + "T12:00:00+01:00")
    clock.now.side_effect = lambda tz: fixed.astimezone(tz)
    monkeypatch.setattr("backend.plans.frozen.datetime", clock)
    monkeypatch.setattr(CopilotState, "_refresh_analytics", refresh_analytics)
    services.client.app.include_router(plans.router)
    mutations = [{"type": "cancel_order", "params": {"sku": "S1", "from_day": 0, "to_day": 13}}]
    preview = services.client.post("/api/data/simulate", json={"mutations": mutations})
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["score_scenario"]["otd"] == data["score_scenario"]["otd_d"] == 100
    applied = services.client.post("/api/data/simulate-apply", json={
        "mutations": mutations, "expected_revision": state.plan_revision,
        **{key: data[key] for key in ("candidate_id", "dataset_id", "base_revision", "input_fingerprint", "candidate_fingerprint")},
        "approve_exceptions": True, "approval_reason": "Isolated empty plan", "approval_author": "test",
    })
    assert applied.status_code == 200, applied.text
    assert state.engine_data is not None and not state.segments and not state.lots
    saved = services.client.post("/api/data/plans", json={"name": "Valid empty plan"})
    assert saved.status_code == 200, saved.text
    active = services.store.active()
    assert active["payload"]["segments"] == []
    restored = CopilotState(config=state.config, plans_store=services.store)
    restore_plan_into_state(active, restored, preserve_exact=True, recover_existing=True, prefer_current_config=True)
    assert restored.engine_data is not None and not restored.segments
    assert restored.score["otd"] == restored.score["otd_d"] == 100
    for path in ("plan-view", "expedition", "risk", "stock", "orders"):
        response = services.client.get(f"/api/data/{path}")
        assert response.status_code == 200, response.text
    rush = services.client.post("/api/data/simulate", json={"mutations": [
        {"type": "rush_order", "params": {"sku": "S1", "qty": 100, "deadline_day": 9}},
    ]})
    assert rush.status_code == 200, rush.text
    assert rush.json()["score_scenario"]["expected_qty"] == 100
