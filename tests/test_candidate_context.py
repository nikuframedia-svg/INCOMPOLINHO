"""Every application path must retain the same complete planning origin."""

import json
import time
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from backend.api.copilot import app
from backend.copilot.state import state
from backend.plans import candidates, serialize
from tests.test_candidate_api import (  # noqa: F401
    PARAMETERS, ROUTES, _apply_body, _preview, _snapshot, client, services,
)
from tests.test_manual_move import manual_api_state  # noqa: F401
from tests.test_replan_jobs import _apply, ready_replan  # noqa: F401
from tests.test_scenario_identity import (
    _apply as apply_scenario,
    _save as save_scenario,
    services as scenario_services,  # noqa: F401
)


@pytest.mark.parametrize("kind", ROUTES)
def test_model_change_invalidates_immediate_preview(client, services, monkeypatch, kind):  # noqa: F811
    preview = _preview(client, kind)
    monkeypatch.setattr(serialize, "MODEL_VERSION", "aps-next")
    before = _snapshot()
    response = client.post(ROUTES[kind] + "-apply", json=_apply_body(kind, preview))
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "stale_preview"
    assert _snapshot() == before
    assert services.simulate.call_count == 1


def test_model_change_invalidates_saved_scenario(scenario_services, monkeypatch):  # noqa: F811
    saved = save_scenario(scenario_services)
    monkeypatch.setattr(serialize, "MODEL_VERSION", "aps-next")
    before = serialize.serialize_snapshot(state)
    response = apply_scenario(scenario_services, saved["scenario"]["id"])
    assert response.status_code == 409, response.text
    assert serialize.serialize_snapshot(state) == before


@pytest.mark.parametrize("changed", ["rules", "manual_edits", "model", "legacy"])
def test_replan_rejects_incomplete_or_changed_context(ready_replan, monkeypatch, changed):  # noqa: F811
    live, manager, job, _, config_path = ready_replan
    if changed == "rules":
        live.rules.append({"id": "new-rule", "value": 1})
    elif changed == "manual_edits":
        live.manual_edits.append({"id": "protected-decision", "lot_id": "L1"})
    elif changed == "model":
        monkeypatch.setattr(serialize, "MODEL_VERSION", "aps-next")
    else:
        manager.store.conn.execute(
            "UPDATE replan_jobs SET base_input_fingerprints_json=? WHERE id=?",
            (json.dumps({"legacy": {"config": "not-the-origin"}}), job["id"]),
        )
        manager.store.conn.commit()
    before = serialize.serialize_snapshot(live), config_path.read_bytes(), live.plans_store.list()
    with pytest.raises(ValueError, match="recalcula"):
        _apply(manager, job["id"])
    assert (serialize.serialize_snapshot(live), config_path.read_bytes(), live.plans_store.list()) == before
    assert manager.store.get(job["id"])["status"] == "ready"


def _ready_manual_job(http_client):
    body = {"lot_id": "LOT1", "target_day": 1, "target_machine": "M2"}
    response = http_client.post("/api/data/plan/move-preview-jobs", json=body)
    assert response.status_code == 200, response.text
    job = response.json()["job"]
    for _ in range(300):
        if job["status"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
        job = http_client.get(f"/api/data/plan/move-preview-jobs/{job['id']}").json()["job"]
    assert job["status"] == "ready", job
    body.update(
        target_start_min=job["result"]["target_start_min"],
        expected_revision=state.plan_revision,
        preview_job_id=job["id"],
        approve_exceptions=True,
        approval_reason="Verified",
        approval_author="pytest",
    )
    return job, body


@pytest.mark.parametrize("changed", ["schedule", "rules", "manual_edits", "mutations", "model"])
def test_manual_job_rejects_changed_context(manual_api_state, monkeypatch, changed):  # noqa: F811
    http_client = TestClient(app)
    try:
        job, body = _ready_manual_job(http_client)
        if changed == "schedule":
            state.segments[0].end_min += 1
        elif changed == "rules":
            monkeypatch.setattr(state, "rules", [*state.rules, {"id": "new-rule", "value": 1}])
        elif changed == "manual_edits":
            state.manual_edits.append({"id": "protected-decision", "lot_id": "LOT1"})
        elif changed == "mutations":
            state.active_mutations.append({"type": "add_holiday", "params": {"day_idx": 3}})
        else:
            monkeypatch.setattr(serialize, "MODEL_VERSION", "aps-next")
        before = serialize.serialize_snapshot(state), state.plans_store.list()
        response = http_client.post("/api/data/plan/move-apply", json=body)
        assert response.status_code == 409, response.text
        assert (serialize.serialize_snapshot(state), state.plans_store.list()) == before
        polled = http_client.get(f"/api/data/plan/move-preview-jobs/{job['id']}").json()["job"]
        assert polled["status"] == "failed" and polled["result"] is None
    finally:
        http_client.close()


@pytest.mark.parametrize("version", ["policy", "improvement", "manual", "protected", "transfer"])
def test_each_calculation_contract_invalidates_preview(client, services, monkeypatch, version):  # noqa: F811
    preview = _preview(client, "simulation")
    if version == "policy":
        monkeypatch.setattr(serialize, "PLANNING_POLICY_VERSION", "next-policy")
    elif version == "improvement":
        from backend.scheduler import improvement

        monkeypatch.setattr(improvement, "CONTRACT_VERSION", improvement.CONTRACT_VERSION + 1)
    elif version == "manual":
        from backend.plans import manual_move

        monkeypatch.setattr(manual_move, "ALLOCATION_MODEL_VERSION", 2)
    elif version == "transfer":
        from backend.scheduler import transfer_consolidation

        monkeypatch.setattr(
            transfer_consolidation, "TRANSFER_SEARCH_VERSION",
            transfer_consolidation.TRANSFER_SEARCH_VERSION + 1,
        )
    else:
        from backend.scheduler import improvement

        monkeypatch.setattr(
            improvement, "PROTECTED_CONTEXT_VERSION", improvement.PROTECTED_CONTEXT_VERSION + 1,
        )
    before = _snapshot()
    response = client.post(ROUTES["simulation"] + "-apply", json=_apply_body("simulation", preview))
    assert response.status_code == 409, response.text
    assert _snapshot() == before


def test_robustness_model_is_not_part_of_the_planning_identity(monkeypatch):
    # Robustness is informational only: a model bump must not invalidate a
    # pending candidate or preview.
    from backend.risk import robustness

    before = serialize.planning_model_identity()
    monkeypatch.setattr(robustness, "ROBUSTNESS_MODEL_VERSION", robustness.ROBUSTNESS_MODEL_VERSION + 1)
    assert serialize.planning_model_identity() == before
    assert not any("robustness" in key for key in before)


def test_origin_covers_unreferenced_resources_and_is_hash_protected(services):  # noqa: F811
    from backend.plans.transactions import input_identity
    from backend.types import MachineInfo

    before = input_identity(state)
    state.engine_data.machines.append(MachineInfo("UNREFERENCED", "Grandes", 480))
    assert input_identity(state) != before
    payload = serialize.serialize_snapshot(state)
    assert payload["planning_origin"] == input_identity(state)
    payload["planning_origin"]["rules"] = "changed"
    with pytest.raises(ValueError, match="fingerprint"):
        serialize.assert_snapshot_integrity(payload)


@pytest.mark.parametrize("kind", ROUTES)
def test_changed_candidate_content_is_not_applied(client, services, kind):  # noqa: F811
    preview = _preview(client, kind)
    cached = candidates.previews._items[preview["candidate_id"]]
    result = cached.simulation if kind == "ctp" else cached.result
    result.mutated_data.ops[0].d[1] += 999
    before = _snapshot()
    response = client.post(ROUTES[kind] + "-apply", json=_apply_body(kind, preview))
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "stale_preview"
    assert _snapshot() == before


def test_preview_storage_detaches_result(services):  # noqa: F811
    # Use the same result shape as the simulation producer, without a new solver run.
    from tests.test_api_validation import _simulation_result

    result = _simulation_result()
    preview = candidates.previews.put("simulation", state, PARAMETERS["simulation"], result)
    result.score["changed"] = True
    assert "changed" not in preview.result.score


def test_manual_application_persists_candidate_and_plan_view_is_read_only(
    manual_api_state, monkeypatch,  # noqa: F811
):
    from backend.plans.manual_move_jobs import manager
    from backend.plans.transactions import input_identity

    monkeypatch.setattr(state, "dataset_info", {"id": "manual-exact"})
    monkeypatch.setattr("backend.plans.explanations._current_planning_day", lambda *_: 0)
    with TestClient(app) as http_client:
        job, body = _ready_manual_job(http_client)
        candidate, _ = manager.result(
            job["id"], dataset_id="manual-exact", plan_revision=state.plan_revision,
            origin=input_identity(state),
        )
        response = http_client.post("/api/data/plan/move-apply", json=body)
        assert response.status_code == 200, response.text
        persisted = state.plans_store.active()["payload"]
        assert persisted["segments"] == [asdict(item) for item in candidate.segments]
        assert persisted["lots"] == [asdict(item) for item in candidate.lots]
        before = serialize.serialize_snapshot(state), state.plans_store.active()
        assert http_client.get("/api/data/plan-view").status_code == 200
        assert (serialize.serialize_snapshot(state), state.plans_store.active()) == before
        assert http_client.get("/api/data/segments").json() == persisted["segments"]
