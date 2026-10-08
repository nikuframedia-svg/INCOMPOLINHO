"""Preview identity, exact application, durable receipts and read-only routing."""

from __future__ import annotations

import copy
import math
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.api.copilot import _read_only_preview, app
from backend.copilot.state import CopilotState, state
from backend.plans import candidates
from backend.plans.serialize import serialize_snapshot
from backend.plans.store import PlansStore
from backend.scheduler.types import Lot, Segment
from tests.test_api_validation import _config, _engine, _simulation_result


ROUTES = {"simulation": "/api/data/simulate", "ctp": "/api/data/ctp"}
PARAMETERS = {
    "simulation": {
        "mutations": [
            {"type": "machine_down", "params": {"machine_id": "M1", "start": 0, "end": 0}}
        ]
    },
    "ctp": {"sku": "SKU1", "qty": 10, "deadline": 2},
}


def _plan(start=420, qty=100):
    production_minutes = qty * 60 / 100 / 0.66
    lot = Lot("L1", "T1_M1_SKU1", "T1", "M1", None, qty, production_minutes, 30, 2, False, sku="SKU1")
    segment = Segment("L1", "R1", "M1", "T1", 1, start, start + 30 + math.ceil(production_minutes), "A", qty, production_minutes, setup_min=30)
    return [segment], [lot]


@pytest.fixture
def services(tmp_path, monkeypatch):
    previous = state.__dict__.copy()
    store = PlansStore(tmp_path / "candidate-plans.db")
    segments, lots = _plan()
    clean = CopilotState(
        engine_data=_engine(), config=_config(), default_config=_config(),
        segments=segments, lots=lots,
        score={"otd": 100.0, "otd_d": 100.0, "setups": 1, "tardy_count": 0},
        plan_revision=7, dataset_info={"id": "candidate-dataset", "filename": "fixture.xlsx"},
        plans_store=store,
    )
    object.__setattr__(state, "__dict__", clean.__dict__.copy())
    monkeypatch.setattr(candidates, "previews", candidates.PreviewStore())
    monkeypatch.setattr(CopilotState, "_refresh_analytics", lambda _self: None)
    services = SimpleNamespace(
        gate={
            "status": "trusted", "physical_gate_passed": True, "coverage_gate_passed": True,
            "delivery_gate_passed": True, "robustness_gate_passed": None,
            "apply_decision": "apply", "requires_approval": False,
            "metrics": {},
        },
        last_simulation=None,
    )

    def simulate(engine_data, score, mutations, config=None, **kwargs):
        assert kwargs["baseline_result"].segments == state.segments
        assert kwargs["active_mutations"] == state.active_mutations
        result = _simulation_result(score={**score, "earliness_avg_days": 0.25},
                                    gate_report=copy.deepcopy(services.gate))
        result.mutated_data = copy.deepcopy(engine_data)
        result.mutated_config = copy.deepcopy(config)
        qty = 100
        for mutation in mutations:
            if mutation.type == "rush_order":
                amount = int(mutation.params["qty"])
                result.mutated_data.ops[0].d[int(mutation.params["deadline_day"])] += amount
                qty += amount
            elif mutation.type == "machine_down":
                result.mutated_data.machine_blocked_days = {"M1": {0}}
        result.segments, result.lots = _plan(start=600, qty=qty)
        result.warnings = ["preview warning"]
        result.operator_alerts = []
        services.last_simulation = copy.deepcopy(result)
        return result

    def ctp(sku, qty, deadline, _segments, _data, config=None):
        return SimpleNamespace(
            sku=sku, qty_requested=qty, feasible=True, latest_day=1, earliest_end_day=deadline,
            machine="M1", confidence="high", slack_min=100, reason=None,
            date_start=None, date_end=None, required_min=10, prod_days=1,
        )

    services.simulate = Mock(side_effect=simulate)
    services.ctp = Mock(side_effect=ctp)
    monkeypatch.setattr("backend.simulator.simulator.simulate", services.simulate)
    monkeypatch.setattr("backend.analytics.ctp.compute_ctp", services.ctp)
    monkeypatch.setattr(
        "backend.simulator.simulator.optimize",
        Mock(side_effect=AssertionError("Unexpected optimizer invocation")),
    )
    yield services
    object.__setattr__(state, "__dict__", previous)
    store.close()


@pytest.fixture
def client(services):
    # Do not start app lifespan workers or restore persisted production state.
    return TestClient(app)


def _preview(client, kind, **kwargs):
    response = client.post(ROUTES[kind], json=copy.deepcopy(PARAMETERS[kind]), **kwargs)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["candidate_id"]
    assert payload["dataset_id"] == "candidate-dataset"
    assert payload["base_revision"] == 7
    assert payload["input_fingerprint"]
    assert payload["candidate_fingerprint"]
    return payload


def _apply_body(kind, preview, **extra):
    return {
        **copy.deepcopy(PARAMETERS[kind]),
        "candidate_id": preview["candidate_id"],
        "expected_revision": preview["base_revision"],
        **extra,
    }


def _snapshot():
    return (
        serialize_snapshot(state),
        copy.deepcopy((state.saved_schedule, state.saved_config, state.saved_engine_data,
                       state.saved_mutations, state.saved_plan_revision)),
        state.plans_store.list(),
    )


def test_simulation_applies_exact_preview_without_rescheduling(client, services):
    kind = "simulation"
    before = _snapshot()
    preview = _preview(client, kind)
    assert _snapshot() == before, "Preview mutated the active plan"
    assert services.simulate.call_count == 1, "The executable candidate must be built during preview"
    expected = copy.deepcopy(services.last_simulation)
    assert preview["segments"] == [asdict(item) for item in expected.segments]
    assert preview["lots"] == [asdict(item) for item in expected.lots]
    assert preview["score_scenario"] == expected.score
    services.simulate.side_effect = AssertionError("Apply must not rerun the optimizer")

    applied = client.post(ROUTES[kind] + "-apply", json=_apply_body(kind, preview))

    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    assert applied.json()["plan_revision"] == 8
    assert state.segments == expected.segments
    assert state.lots == expected.lots
    assert state.score == expected.score
    assert state.gate_report == expected.gate_report
    assert state.engine_data == expected.mutated_data
    assert state.config == expected.mutated_config
    assert state.warnings == expected.warnings
    assert services.simulate.call_count == 1
    assert len(state.plans_store.list()) == 1


def test_ctp_builds_once_on_preview_and_reuses_candidate_for_approval_retry(client, services):
    services.gate.update(
        status="best_effort", delivery_gate_passed=False, requires_approval=True,
        apply_decision="approval_required", approval_reasons=["delivery_risk"],
    )
    before = _snapshot()
    preview = _preview(client, "ctp")
    assert _snapshot() == before
    services.simulate.assert_called_once()
    services.ctp.assert_not_called()  # The heuristic is no longer a promise proof.
    body = _apply_body("ctp", preview, request_id="ctp-approval-retry")

    confirmation = client.post("/api/data/ctp-apply", json=body)

    assert confirmation.status_code == 409, confirmation.text
    assert confirmation.json()["detail"]["gate_report"]["requires_approval"] is True
    assert _snapshot() == before
    assert state.plans_store.mutation_receipt(body["request_id"]) is None
    services.simulate.assert_called_once()
    expected = copy.deepcopy(services.last_simulation)
    services.simulate.side_effect = AssertionError("Approval retry must reuse the cached schedule")
    approved_body = {
        **body, "approve_exceptions": True,
        "approval_reason": "Accept the previewed delivery risk", "approval_author": "pytest",
    }

    applied = client.post("/api/data/ctp-apply", json=approved_body)

    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    assert applied.json()["plan_revision"] == 8
    assert state.segments == expected.segments
    assert state.lots == expected.lots
    assert state.score == expected.score
    assert state.gate_report == expected.gate_report
    assert state.engine_data == expected.mutated_data
    assert state.config == expected.mutated_config
    assert state.warnings == expected.warnings
    assert len(state.approvals) == 1
    assert state.approvals[0]["author"] == "pytest"
    assert applied.json()["promise"]["promised_machine"] == preview["machine"]
    assert applied.json()["promise"]["promised_end_day"] == preview["earliest_end_day"]
    services.simulate.assert_called_once()
    committed = _snapshot()
    repeated = client.post("/api/data/ctp-apply", json=approved_body)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == applied.json()
    assert _snapshot() == committed
    assert len(state.plans_store.list()) == 1
    services.simulate.assert_called_once()


@pytest.mark.parametrize("kind", ROUTES)
@pytest.mark.parametrize("candidate_id", [None, "unknown-candidate"])
def test_apply_requires_preview_identity(client, services, kind, candidate_id):
    before = _snapshot()
    response = client.post(
        ROUTES[kind] + "-apply",
        json={**PARAMETERS[kind], "expected_revision": 7, "candidate_id": candidate_id},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "preview_required"
    assert _snapshot() == before
    services.simulate.assert_not_called()


@pytest.mark.parametrize("kind", ROUTES)
@pytest.mark.parametrize("changed", ["revision", "dataset", "config", "engine", "schedule", "mutations"])
def test_stale_preview_rejected_even_with_current_revision(client, services, kind, changed):
    preview = _preview(client, kind)
    if changed == "revision":
        state.plan_revision += 1
    elif changed == "dataset":
        state.dataset_info["id"] = "replacement-dataset"
    elif changed == "config":
        state.config.lst_safety_buffer += 1
    elif changed == "engine":
        state.engine_data.ops[0].d[1] += 1
    elif changed == "schedule":
        state.segments[0].end_min += 1
    else:
        state.active_mutations.append(
            {"type": "machine_down", "params": {"machine_id": "M1", "start": 2, "end": 2}}
        )
    before = _snapshot()
    services.simulate.reset_mock()
    response = client.post(
        ROUTES[kind] + "-apply",
        json=_apply_body(kind, preview, expected_revision=state.plan_revision),
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "stale_preview"
    assert _snapshot() == before
    services.simulate.assert_not_called()


@pytest.mark.parametrize("kind", ROUTES)
def test_changed_parameters_do_not_reuse_candidate(client, services, kind):
    preview = _preview(client, kind)
    body = _apply_body(kind, preview)
    if kind == "simulation":
        body["mutations"][0]["params"]["end"] = 1
    else:
        body["qty"] += 1
    before = _snapshot()
    services.simulate.reset_mock()
    response = client.post(ROUTES[kind] + "-apply", json=body)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "stale_preview"
    assert _snapshot() == before
    services.simulate.assert_not_called()


@pytest.mark.parametrize("kind", ROUTES)
def test_expired_preview_requires_new_calculation(client, services, kind):
    preview = _preview(client, kind)
    candidates.previews.ttl_seconds = -1
    before = _snapshot()
    services.simulate.reset_mock()
    response = client.post(ROUTES[kind] + "-apply", json=_apply_body(kind, preview))
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "preview_required"
    assert _snapshot() == before
    services.simulate.assert_not_called()


@pytest.mark.parametrize("kind", ROUTES)
def test_preview_from_other_workflow_cannot_be_applied(client, services, kind):
    other = "ctp" if kind == "simulation" else "simulation"
    preview = _preview(client, other)
    before = _snapshot()
    response = client.post(ROUTES[kind] + "-apply", json=_apply_body(kind, preview))
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "stale_preview"
    assert _snapshot() == before


@pytest.mark.parametrize("kind", ROUTES)
def test_request_id_replays_durable_receipt_after_preview_expiry(client, services, kind):
    preview = _preview(client, kind)
    body = _apply_body(kind, preview, request_id="apply-once")
    applied = client.post(ROUTES[kind] + "-apply", json=body)
    assert applied.status_code == 200, applied.text
    receipt = state.plans_store.mutation_receipt("apply-once")
    assert receipt["status"] == "committed"
    assert receipt["response"] == applied.json()
    before = _snapshot()
    candidates.previews.ttl_seconds = -1
    services.simulate.reset_mock()
    services.ctp.reset_mock()
    # The original expected_revision is deliberately stale after the commit.
    retried = client.post(ROUTES[kind] + "-apply", json=body)
    assert retried.status_code == 200, retried.text
    assert retried.json() == applied.json()
    assert _snapshot() == before
    assert len(state.plans_store.list()) == 1
    services.simulate.assert_not_called()
    services.ctp.assert_not_called()


@pytest.mark.parametrize("kind", ROUTES)
def test_request_id_cannot_be_reused_for_different_parameters(client, services, kind):
    preview = _preview(client, kind)
    body = _apply_body(kind, preview, request_id="same-request")
    applied = client.post(ROUTES[kind] + "-apply", json=body)
    assert applied.status_code == 200, applied.text
    if kind == "simulation":
        body["mutations"][0]["params"]["end"] = 1
    else:
        body["qty"] += 1
    before = _snapshot()
    services.simulate.reset_mock()
    response = client.post(ROUTES[kind] + "-apply", json=body)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "different_input"
    assert _snapshot() == before
    services.simulate.assert_not_called()


@pytest.mark.parametrize("kind", ROUTES)
@pytest.mark.parametrize("gate", ["physical_gate_passed", "coverage_gate_passed"])
def test_candidate_identity_and_approval_cannot_bypass_blocked_gate(client, services, kind, gate):
    services.gate.update({gate: False, "apply_decision": "blocked"})
    preview = _preview(client, kind)
    before = _snapshot()
    response = client.post(
        ROUTES[kind] + "-apply",
        json=_apply_body(kind, preview, approve_exceptions=True,
                         approval_reason="Cannot override hard gates", approval_author="pytest"),
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["gate_report"][gate] is False
    assert _snapshot() == before


@pytest.mark.parametrize("kind", ROUTES)
def test_read_only_allows_preview_but_not_exact_candidate_apply(client, services, kind):
    before = _snapshot()
    preview = _preview(client, kind, headers={"X-Access-Mode": "view"})
    calls = services.simulate.call_count
    response = client.post(
        ROUTES[kind] + "-apply", json=_apply_body(kind, preview),
        headers={"X-Access-Mode": "view"},
    )
    assert response.status_code == 403, response.text
    assert _snapshot() == before
    assert services.simulate.call_count == calls


@pytest.mark.parametrize("path", [
    "/api/data/simulate", "/api/data/ctp", "/api/data/plan/move-preview",
    "/api/data/plan/move-preview-jobs", "/api/data/subcontracts/preview",
    "/api/data/skus/SKU1/planning/preview", "/api/data/plan/move-preview-jobs/job-1/cancel",
])
def test_read_only_preview_allowlist_is_post_only(path):
    assert _read_only_preview("POST", path) is True
    for method in ("PUT", "PATCH", "DELETE"):
        assert _read_only_preview(method, path) is False


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/data/simulate-apply/preview"),
    ("POST", "/api/data/ctp-apply/preview"),
    ("POST", "/api/data/recalculate/preview"),
    ("POST", "/api/data/load/preview"),
    ("POST", "/api/data/skus/SKU1/planning/preview/apply"),
    ("POST", "/api/data/skus/SKU1/extra/planning/preview"),
    ("POST", "/api/data/subcontracts/preview/extra"),
    ("POST", "/api/data/plan/move-preview-jobs/job/extra/cancel"),
    ("PUT", "/api/data/simulate"),
    ("DELETE", "/api/data/subcontracts/preview"),
])
def test_read_only_blocks_preview_suffix_and_method_bypasses(client, method, path):
    before = _snapshot()
    response = client.request(method, path, json={}, headers={"X-Access-Mode": "view"})
    assert response.status_code == 403, response.text
    assert _snapshot() == before


@pytest.fixture
def manual_move(services, monkeypatch):
    from backend.api import manual_plan
    from backend.plans.manual_move import ManualMoveResult

    segments, lots = _plan(start=570)
    result = ManualMoveResult(
        segments=segments, lots=lots, score=copy.deepcopy(state.score),
        delta=_simulation_result().delta, gate_report=copy.deepcopy(services.gate),
        lot_id="L1", source_days=[1], target_day=1, target_start_min=600,
        target_machine="M1", requires_confirmation=False, delivery_warnings=[], time_ms=1.0,
    )
    calculate = Mock(return_value=result)
    monkeypatch.setattr(manual_plan, "move_lot", calculate)
    return SimpleNamespace(
        calculate=calculate, result=result,
        parameters={"lot_id": "L1", "target_day": 1, "target_start_min": 600, "target_machine": "M1"},
    )


def test_legacy_manual_apply_requires_candidate_id(client, manual_move):
    before = _snapshot()
    response = client.post(
        "/api/data/plan/move-apply",
        json={**manual_move.parameters, "expected_revision": state.plan_revision},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "preview_required"
    assert _snapshot() == before
    manual_move.calculate.assert_not_called()


def test_legacy_manual_apply_uses_exact_preview_without_recalculation(client, manual_move):
    before = _snapshot()
    preview = client.post("/api/data/plan/move-preview", json=manual_move.parameters)
    assert preview.status_code == 200, preview.text
    assert preview.json()["candidate_id"]
    assert _snapshot() == before
    manual_move.calculate.assert_called_once()
    manual_move.calculate.side_effect = AssertionError("Manual apply must not calculate again")
    applied = client.post(
        "/api/data/plan/move-apply",
        json={**manual_move.parameters, "candidate_id": preview.json()["candidate_id"],
              "expected_revision": preview.json()["base_revision"]},
    )
    assert applied.status_code == 200, applied.text
    assert state.segments == manual_move.result.segments
    assert state.lots == manual_move.result.lots
    assert state.plan_revision == 8
    assert len(state.manual_edits) == 1
    manual_move.calculate.assert_called_once()


def test_legacy_manual_changed_target_rejected(client, manual_move):
    preview = client.post("/api/data/plan/move-preview", json=manual_move.parameters)
    assert preview.status_code == 200, preview.text
    before = _snapshot()
    response = client.post(
        "/api/data/plan/move-apply",
        json={**manual_move.parameters, "target_start_min": 610,
              "candidate_id": preview.json()["candidate_id"], "expected_revision": 7},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "stale_preview"
    assert _snapshot() == before
    manual_move.calculate.assert_called_once()
