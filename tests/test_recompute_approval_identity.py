"""Approval must consume the recomputed candidate, not run the engine twice."""

import copy
from unittest.mock import Mock

import pytest

from backend.copilot.state import state
from backend.plans import candidates
from backend.scheduler.types import ScheduleResult
from tests import test_candidate_api as candidate_fixtures
from tests.test_candidate_api import _plan, _snapshot


@pytest.fixture
def services(tmp_path, monkeypatch):
    yield from candidate_fixtures.services.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def client(services):
    return candidate_fixtures.client.__wrapped__(services)


@pytest.fixture
def compact(services, monkeypatch):
    services.gate.update(
        status="best_effort", delivery_gate_passed=False, requires_approval=True,
        apply_decision="approval_required", approval_reasons=["delivery_risk"],
    )

    def calculate(config):
        segments, lots = _plan(start=600)
        result = ScheduleResult(
            segments, lots, {"otd": 90, "otd_d": 90, "setups": 1, "tardy_count": 1},
            0, [], [], gate_report=copy.deepcopy(services.gate),
        )
        state.config = copy.deepcopy(config)
        state.update_schedule(result)
        return result

    function = Mock(side_effect=calculate)
    monkeypatch.setattr("backend.api.data._compact_active_schedule", function)
    return function


def test_recalculate_approval_reuses_the_exact_presented_candidate(client, compact):
    body = {"expected_revision": 7, "compact_active_plan": True, "request_id": "recalc-approval"}
    before = _snapshot()
    preview = client.post("/api/data/recalculate", json=body)
    assert preview.status_code == 409, preview.text
    assert _snapshot() == before
    detail = preview.json()["detail"]
    assert detail["gate_report"]["requires_approval"] is True
    assert detail.get("candidate_id"), "The confirmation must identify the calculated candidate"
    assert detail["dataset_id"] == "candidate-dataset"
    assert detail["base_revision"] == 7
    compact.assert_called_once()
    compact.side_effect = AssertionError("Approval must not calculate another schedule")
    approved = {**body, "candidate_id": detail["candidate_id"], "approve_exceptions": True,
                "approval_reason": "Accept this exact candidate", "approval_author": "pytest"}
    applied = client.post("/api/data/recalculate", json=approved)
    assert applied.status_code == 200, applied.text
    assert state.segments == _plan(start=600)[0]
    assert state.lots == _plan(start=600)[1]
    compact.assert_called_once()
    assert applied.json()["plan_revision"] == 8
    after = _snapshot()
    replay = client.post("/api/data/recalculate", json=approved)
    assert replay.status_code == 200, replay.text
    assert replay.json() == applied.json()
    assert _snapshot() == after


def test_recalculate_cannot_approve_an_unidentified_calculation(client, compact):
    before = _snapshot()
    response = client.post("/api/data/recalculate", json={
        "expected_revision": 7, "compact_active_plan": True, "approve_exceptions": True,
        "approval_reason": "No presented candidate", "approval_author": "pytest",
    })
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "preview_required"
    assert _snapshot() == before
    compact.assert_not_called()


def _preview_recompute(client, **extra):
    body = {"expected_revision": 7, "compact_active_plan": True, **extra}
    response = client.post("/api/data/recalculate", json=body)
    assert response.status_code == 409, response.text
    return body, response.json()["detail"]


@pytest.mark.parametrize("change", ["revision", "dataset", "config", "data", "rules", "manual"])
def test_recompute_rejects_changed_origin_without_another_calculation(client, compact, change):
    body, preview = _preview_recompute(client)
    if change == "revision":
        state.plan_revision += 1
    elif change == "dataset":
        state.dataset_info["id"] = "another-dataset"
    elif change == "config":
        state.config.oee_default = 0.33
    elif change == "data":
        state.engine_data.ops[0].d[0] += 10
    elif change == "rules":
        state.rules.append({"id": "new-rule", "content": "new"})
    else:
        state.manual_edits.append({"lot_id": "L1", "day_idx": 2})
    before = _snapshot()
    response = client.post("/api/data/recalculate", json={
        **body, "candidate_id": preview["candidate_id"], "approve_exceptions": True,
        "approval_reason": "Reviewed", "approval_author": "pytest",
    })
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "stale_preview"
    assert _snapshot() == before
    compact.assert_called_once()


@pytest.mark.parametrize("change", ["parameters", "route", "expired", "corrupted", "missing"])
def test_recompute_rejects_other_or_expired_candidates(client, compact, change):
    body, preview = _preview_recompute(client)
    url = "/api/data/recalculate"
    if change == "parameters":
        body["compact_active_plan"] = False
    elif change == "route":
        url = "/api/data/config"
        body["oee_default"] = 0.44
    elif change == "expired":
        candidates.previews._items[preview["candidate_id"]].created_at -= 1801
    elif change == "corrupted":
        candidates.previews._items[preview["candidate_id"]].result.values["segments"][0].start_min += 1
    else:
        candidates.previews._items.clear()
    before = _snapshot()
    response = client.request("PUT" if change == "route" else "POST", url, json={
        **body, "candidate_id": preview["candidate_id"], "approve_exceptions": True,
        "approval_reason": "Reviewed", "approval_author": "pytest",
    })
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] in {"preview_required", "stale_preview"}
    assert _snapshot() == before
    compact.assert_called_once()


def test_recompute_repeat_without_approval_returns_same_candidate(client, compact):
    body, preview = _preview_recompute(client)
    before = _snapshot()
    retry = client.post("/api/data/recalculate", json={**body, "candidate_id": preview["candidate_id"]})
    assert retry.status_code == 409, retry.text
    assert retry.json()["detail"]["candidate_id"] == preview["candidate_id"]
    assert _snapshot() == before
    compact.assert_called_once()


def test_recompute_failed_commit_can_retry_exact_candidate(client, compact, monkeypatch):
    body, preview = _preview_recompute(client)
    approved = {**body, "request_id": "failed-commit", "candidate_id": preview["candidate_id"],
                "approve_exceptions": True, "approval_reason": "Reviewed", "approval_author": "pytest"}
    before = _snapshot()
    store = state.plans_store
    commit = store.commit_mutation
    with monkeypatch.context() as patch:
        patch.setattr(store, "commit_mutation", Mock(side_effect=RuntimeError("SQLITE_BUSY")))
        with pytest.raises(RuntimeError, match="SQLITE_BUSY"):
            client.post("/api/data/recalculate", json=approved)
    assert _snapshot() == before
    assert not store.pending_mutations()
    monkeypatch.setattr(store, "commit_mutation", commit)
    response = client.post("/api/data/recalculate", json=approved)
    assert response.status_code == 200, response.text
    assert state.segments == _plan(start=600)[0]
    compact.assert_called_once()


def test_recompute_hard_conflict_never_becomes_approvable(client, compact, services):
    services.gate.update(physical_gate_passed=False, apply_decision="blocked")
    before = _snapshot()
    response = client.post("/api/data/recalculate", json={
        "expected_revision": 7, "compact_active_plan": True,
    })
    assert response.status_code == 409, response.text
    assert not response.json()["detail"].get("candidate_id")
    assert not candidates.previews._items
    assert _snapshot() == before


def test_recompute_trusted_result_still_applies_without_confirmation(client, compact, services):
    services.gate.update(requires_approval=False, delivery_gate_passed=True, apply_decision="apply")
    response = client.post("/api/data/recalculate", json={
        "expected_revision": 7, "compact_active_plan": True,
    })
    assert response.status_code == 200, response.text
    assert response.json()["plan_revision"] == 8
    assert state.segments == _plan(start=600)[0]
    assert not candidates.previews._items


def test_operator_write_accepts_request_identity_without_parsing_it_as_a_count(
    client, compact, monkeypatch,
):
    monkeypatch.setattr("backend.api.data._recompute", compact)
    body = {"expected_revision": 7, "Grandes A": "3", "request_id": "operator-approval"}
    first = client.put("/api/data/operators", json=body)
    assert first.status_code == 409, first.text
    preview = first.json()["detail"]
    assert preview["candidate_id"]
    applied = client.put("/api/data/operators", json={
        **body, "candidate_id": preview["candidate_id"], "approve_exceptions": True,
        "approval_reason": "Reviewed", "approval_author": "pytest",
    })
    assert applied.status_code == 200, applied.text
    assert state.config.operators[("Grandes", "A")] == 3
    compact.assert_called_once()


@pytest.mark.parametrize("count", [True, 3.1, "3.0", "NaN", "Infinity", -1])
def test_operator_write_rejects_non_integral_counts(client, compact, count):
    before = _snapshot()
    response = client.put("/api/data/operators", json={
        "expected_revision": 7, "Grandes A": count,
    })
    assert response.status_code == 400, response.text
    assert _snapshot() == before
    compact.assert_not_called()


@pytest.mark.parametrize(("path", "payload"), [
    ("/api/data/machines/M1", {"oee": 0.44}),
    ("/api/data/tools/T1", {"setup_hours": 1}),
])
def test_legacy_master_writer_approval_reuses_exact_schedule(
    client, services, monkeypatch, path, payload,
):
    from backend.scheduler.scheduler import schedule_all

    services.gate.update(
        status="best_effort", requires_approval=True, apply_decision="approval_required",
        approval_reasons=["delivery_risk"],
    )
    expected = []

    def calculate(_data, config, *_args, **_kwargs):
        result = schedule_all(copy.deepcopy(_data), config=config)
        result.gate_report = copy.deepcopy(services.gate)
        expected.append(copy.deepcopy(result))
        return result

    optimizer = Mock(side_effect=calculate)
    monkeypatch.setattr("backend.plans.frozen.optimize_preserving_started_lots", optimizer)
    body = {"expected_revision": 7, **payload}
    before = _snapshot()
    first = client.put(path, json=body)
    assert first.status_code == 409, first.text
    assert _snapshot() == before
    preview = first.json()["detail"]
    optimizer.side_effect = AssertionError("Do not optimize the approved master-data candidate again")
    response = client.put(path, json={
        **body, "candidate_id": preview["candidate_id"], "approve_exceptions": True,
        "approval_reason": "Reviewed", "approval_author": "pytest",
    })
    assert response.status_code == 200, response.text
    assert state.segments == expected[0].segments
    assert state.lots == expected[0].lots
    assert state.approvals[-1]["action"] == "master_data"
    assert state.approvals[-1]["candidate_id"] == preview["candidate_id"]
    optimizer.assert_called_once()


@pytest.mark.parametrize(("method", "path", "payload", "check"), [
    ("post", "/api/data/holidays", {"data": "2026-09-16"},
     lambda: "2026-09-16" in state.config.holidays),
    ("post", "/api/data/holidays/range", {"from": "2026-09-16", "to": "2026-09-17"},
     lambda: {"2026-09-16", "2026-09-17"} <= set(state.config.holidays)),
    ("post", "/api/data/workdays-extra", {"date": "2026-09-19"},
     lambda: "2026-09-19" in state.config.extra_workdays),
])
def test_calendar_writer_approval_reuses_exact_schedule(
    client, services, monkeypatch, method, path, payload, check,
):
    """NOK #5 (07/10/2026): non-working days need explicit approval like any
    other plan change; the approved request applies the presented candidate."""
    from backend.scheduler.scheduler import schedule_all

    services.gate.update(
        status="best_effort", requires_approval=True, apply_decision="approval_required",
        approval_reasons=["delivery_risk", "long_production"],
    )
    expected = []

    def calculate(_data, config, *_args, **_kwargs):
        result = schedule_all(copy.deepcopy(_data), config=config)
        result.gate_report = copy.deepcopy(services.gate)
        expected.append(copy.deepcopy(result))
        return result

    optimizer = Mock(side_effect=calculate)
    monkeypatch.setattr("backend.plans.frozen.optimize_preserving_started_lots", optimizer)
    body = {"expected_revision": 7, **payload}
    before = _snapshot()
    first = getattr(client, method)(path, json=body)
    assert first.status_code == 409, first.text
    assert _snapshot() == before
    preview = first.json()["detail"]
    assert preview["gate_report"]["approval_reasons"] == ["delivery_risk", "long_production"]
    optimizer.side_effect = AssertionError("Do not optimize the approved calendar candidate again")
    response = getattr(client, method)(path, json={
        **body, "candidate_id": preview["candidate_id"], "approve_exceptions": True,
        "approval_reason": "Fecho acordado", "approval_author": "pytest",
    })
    assert response.status_code == 200, response.text
    assert check()
    assert state.plan_revision == 8
    assert state.segments == expected[0].segments
    assert state.approvals[-1]["candidate_id"] == preview["candidate_id"]
    optimizer.assert_called_once()
