"""Restore controls must be explicit before decoding, calculation or commit."""

from __future__ import annotations

import copy
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.api import plans as plans_api
from backend.api.copilot import app
from backend.plans import restore as restore_module
from backend.plans.restore import restore_plan_into_state
from backend.plans.serialize import serialize_snapshot
from backend.scheduler.types import ScheduleResult
from tests.test_plan_transactions import planning as planning


INVALID_FLAGS = ["false", "true", 0, 1, None, [], {}]
RESTORE_FLAGS = [
    "autosave", "approve_exceptions", "recover_jit_blocked", "prefer_current_config",
    "preserve_exact", "recover_existing", "recalculate",
]


def _plan(planning):
    payload = serialize_snapshot(planning.state)
    return planning.store.save(
        name="Restore contract", source="user", origin="isop.xlsx", note="",
        payload=payload, score=payload["score"], gate_report=payload["gate_report"],
        is_auto=False, activate=True,
    )


def _unchanged(planning):
    return {
        "memory": serialize_snapshot(planning.state),
        "runtime": planning.store.runtime_identity(),
        "plans": planning.store.list(),
        "config": planning.config_path.read_bytes(),
        "mutations": planning.store._conn.execute(
            "SELECT id,status,fingerprint FROM plan_mutations ORDER BY id"
        ).fetchall(),
    }


@pytest.mark.parametrize("value", INVALID_FLAGS)
def test_api_rejects_non_boolean_recalculation_before_restore(planning, monkeypatch, value):
    saved = _plan(planning)
    before = _unchanged(planning)
    restore = Mock(return_value={"plan_revision": planning.state.plan_revision})
    monkeypatch.setattr(plans_api, "restore_plan_into_state", restore)

    response = TestClient(app).post(f"/api/data/plans/{saved['id']}/restore", json={
        "expected_revision": 7, "recalculate": value, "request_id": "bad-restore-control",
    })

    assert response.status_code == 400, response.text
    assert "recalculate" in response.text
    restore.assert_not_called()
    assert _unchanged(planning) == before


@pytest.mark.parametrize("value", [None, True, False, 7.9, "7.0", "", [], {}])
def test_api_rejects_invalid_revision_before_restore(planning, monkeypatch, value):
    saved = _plan(planning)
    before = _unchanged(planning)
    restore = Mock(return_value={"plan_revision": planning.state.plan_revision})
    monkeypatch.setattr(plans_api, "restore_plan_into_state", restore)

    response = TestClient(app).post(f"/api/data/plans/{saved['id']}/restore", json={
        "expected_revision": value, "request_id": "bad-restore-revision",
    })

    assert response.status_code == 400, response.text
    restore.assert_not_called()
    assert _unchanged(planning) == before


@pytest.mark.parametrize("field", RESTORE_FLAGS)
@pytest.mark.parametrize("value", INVALID_FLAGS)
def test_direct_restore_rejects_invalid_controls_before_decode(planning, monkeypatch, field, value):
    saved = _plan(planning)
    plan = planning.store.get(saved["id"])
    before = _unchanged(planning)
    decode = Mock(wraps=restore_module.deserialize_snapshot)
    optimizer = Mock(side_effect=AssertionError("Invalid control reached optimizer"))
    monkeypatch.setattr(restore_module, "deserialize_snapshot", decode)
    monkeypatch.setattr("backend.cpo.optimizer.optimize", optimizer)

    parameters = {"approve_exceptions": True, "approval_reason": "Private test", "approval_author": "pytest"}
    parameters[field] = value
    with pytest.raises(ValueError, match=field):
        restore_plan_into_state(plan, planning.state, expected_revision=7, **parameters)

    decode.assert_not_called()
    optimizer.assert_not_called()
    assert _unchanged(planning) == before


@pytest.mark.parametrize("value", [True, False, 7.9, "7.0", "", [], {}, float("nan"), float("inf")])
def test_direct_restore_rejects_lossy_revision_before_decode(planning, monkeypatch, value):
    saved = _plan(planning)
    before = _unchanged(planning)
    decode = Mock(wraps=restore_module.deserialize_snapshot)
    monkeypatch.setattr(restore_module, "deserialize_snapshot", decode)

    with pytest.raises(ValueError, match="expected_revision"):
        restore_plan_into_state(planning.store.get(saved["id"]), planning.state,
                                expected_revision=value, approve_exceptions=True,
                                approval_reason="Private test", approval_author="pytest")

    decode.assert_not_called()
    assert _unchanged(planning) == before


@pytest.mark.parametrize("value", [7, 7.0, "7", " +7 "])
def test_exact_restore_accepts_lossless_revision_without_optimizing(planning, monkeypatch, value):
    saved = _plan(planning)
    before = copy.deepcopy(planning.state.segments)
    optimizer = Mock(side_effect=AssertionError("Exact restore must not optimize"))
    monkeypatch.setattr("backend.cpo.optimizer.optimize", optimizer)

    restore_plan_into_state(planning.store.get(saved["id"]), planning.state,
                            expected_revision=value, recalculate=False,
                            approve_exceptions=True, approval_reason="Private test", approval_author="pytest")

    optimizer.assert_not_called()
    assert planning.state.segments == before


@pytest.mark.parametrize("enabled", [False, True])
def test_api_forwards_actual_recalculation_flag(planning, monkeypatch, enabled):
    saved = _plan(planning)
    restore = Mock(return_value={"plan_revision": planning.state.plan_revision})
    monkeypatch.setattr(plans_api, "restore_plan_into_state", restore)

    response = TestClient(app).post(f"/api/data/plans/{saved['id']}/restore", json={
        "expected_revision": 7, "recalculate": enabled,
    })

    assert response.status_code == 200, response.text
    assert restore.call_args.kwargs["recalculate"] is enabled


@pytest.mark.parametrize("enabled", [None, False, True])
def test_api_restores_exactly_unless_recalculation_is_explicit(planning, monkeypatch, enabled):
    saved = _plan(planning)
    before = copy.deepcopy(planning.state.segments)
    result = ScheduleResult(
        segments=copy.deepcopy(planning.state.segments), lots=copy.deepcopy(planning.state.lots),
        score=copy.deepcopy(planning.state.score), time_ms=0, warnings=[], operator_alerts=[],
    )
    optimizer = Mock(return_value=result)
    monkeypatch.setattr("backend.cpo.optimizer.optimize", optimizer)
    body = {"expected_revision": 7, "request_id": "restore-once", "approve_exceptions": True,
            "approval_reason": "Private test", "approval_author": "pytest"}
    if enabled is not None:
        body["recalculate"] = enabled
    client = TestClient(app)

    restored = client.post(f"/api/data/plans/{saved['id']}/restore", json=body)

    assert restored.status_code == 200, restored.text
    assert optimizer.call_count == int(enabled is True)
    assert planning.state.segments == before
    assert planning.state.plan_revision == 8
    committed = _unchanged(planning)
    repeated = client.post(f"/api/data/plans/{saved['id']}/restore", json=body)
    assert repeated.status_code == 200 and repeated.json() == restored.json()
    assert optimizer.call_count == int(enabled is True)
    assert _unchanged(planning) == committed


def test_api_missing_or_stale_revision_never_decodes_a_plan(planning, monkeypatch):
    saved = _plan(planning)
    before = _unchanged(planning)
    restore = Mock(side_effect=AssertionError("Invalid revision reached restore"))
    monkeypatch.setattr(plans_api, "restore_plan_into_state", restore)
    client = TestClient(app)

    for body, expected_code in [({}, 400), ({"expected_revision": 6}, 409)]:
        response = client.post(f"/api/data/plans/{saved['id']}/restore", json=body)
        assert response.status_code == expected_code, response.text
        assert _unchanged(planning) == before
    restore.assert_not_called()
