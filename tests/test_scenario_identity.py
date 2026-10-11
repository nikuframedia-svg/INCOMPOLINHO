"""Detached named scenarios and exact application, using temporary storage."""

from __future__ import annotations

import asyncio
import copy
import threading
from dataclasses import asdict
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import data as data_api
from backend.api import locks, scenarios
from backend.config import loader
from backend.config.planning import apply_effective_planning_config
from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.copilot.state import CopilotState, state
from backend.plans import candidates, transactions
from backend.plans.context import is_staging
from backend.plans.serialize import (
    assert_snapshot_integrity,
    deserialize_snapshot,
    serialize_snapshot,
)
from backend.plans.store import PlansStore
from backend.plans.transactions import input_identity
from backend.simulator import simulate
from backend.simulator.mutations import apply_mutation
from backend.transform.calendars import apply_calendars
from backend.types import EOp, EngineData, MachineInfo


BASE = "/api/data/scenarios"
MUTATIONS = [{"type": "rush_order", "params": {"sku": "S1", "qty": 40, "deadline_day": 9}}]


@pytest.fixture
def services(tmp_path, monkeypatch):
    config = FactoryConfig(
        shifts=[ShiftConfig("A", 480, 720), ShiftConfig("B", 780, 1020)],
        machines={"M1": MachineConfig("M1", "Grandes", oee=1.0)},
        tools={"T1": {"primary": "M1", "setup_hours": 0.25}},
        operators={("Grandes", "A"): 3, ("Grandes", "B"): 3},
    )
    demand = [0] * 14
    demand[7] = 100
    engine = EngineData(
        ops=[
            EOp(
                id="OP1",
                sku="S1",
                client="C",
                designation="Part",
                m="M1",
                t="T1",
                pH=100,
                sH=0.25,
                operators=1,
                eco_lot=0,
                alt=None,
                stk=0,
                backlog=0,
                d=demand,
                oee=1.0,
                wip=0,
            )
        ],
        machines=[MachineInfo("M1", "Grandes", 480)],
        twin_groups=[],
        client_demands={},
        workdays=[(date(2026, 10, 5) + timedelta(days=idx)).isoformat() for idx in range(14)],
        n_days=14,
        holidays=[5, 6, 12, 13],
    )
    apply_effective_planning_config(engine, config)
    apply_calendars(engine, config)
    result = simulate(engine, {}, [], config)
    store = PlansStore(tmp_path / "scenarios.db")
    config_path = tmp_path / "factory.yaml"
    monkeypatch.setattr(loader, "DEFAULT_CONFIG_PATH", str(config_path))
    loader.save_config(config, path=str(config_path))
    previous = object.__getattribute__(state, "__dict__")
    loaded = CopilotState(
        engine_data=engine,
        config=config,
        default_config=copy.deepcopy(config),
        segments=result.segments,
        lots=result.lots,
        score=result.score,
        warnings=result.warnings,
        operator_alerts=result.operator_alerts,
        gate_report=result.gate_report,
        plan_revision=7,
        dataset_info={"id": "scenario-dataset", "filename": "fixture.xlsx", "n_ops": 1},
        plans_store=store,
    )
    object.__setattr__(state, "__dict__", loaded.__dict__)
    lock = locks.PlanMutationLock()
    monkeypatch.setattr(scenarios, "plan_mutation_lock", lock)
    monkeypatch.setattr(transactions, "plan_mutation_lock", lock)
    monkeypatch.setattr(locks, "plan_mutation_lock", lock)
    monkeypatch.setattr(candidates, "previews", candidates.PreviewStore())
    monkeypatch.setattr(CopilotState, "_refresh_analytics", lambda _self: None)
    service = SimpleNamespace(store=store, lock=lock, before_compute=None, last_result=None)

    def calculate(engine_data, score, mutations, config=None, **kwargs):
        assert is_staging()
        assert kwargs["baseline_result"].segments == state.segments
        assert kwargs["active_mutations"] == state.active_mutations
        if service.before_compute is not None:
            service.before_compute()
        output = simulate(engine_data, score, mutations, config, **kwargs)
        service.last_result = copy.deepcopy(output)
        return output

    service.simulate = Mock(side_effect=calculate)
    monkeypatch.setattr("backend.simulator.simulator.simulate", service.simulate)
    app = FastAPI()
    app.include_router(scenarios.router)
    app.include_router(data_api.router)
    service.client = TestClient(app)  # No application lifespan or production workers.
    try:
        yield service
    finally:
        service.client.close()
        object.__setattr__(state, "__dict__", previous)
        store.close()


def _save(services, **extra):
    if "candidate_id" not in extra:
        preview = services.client.post("/api/data/simulate", json={"mutations": extra.get("mutations", copy.deepcopy(MUTATIONS))})
        assert preview.status_code == 200, preview.text
        extra["candidate_id"] = preview.json()["candidate_id"]
    response = services.client.post(
        BASE, json={"name": "Scenario", "mutations": copy.deepcopy(MUTATIONS), **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _apply(services, scenario_id, **extra):
    return services.client.post(
        f"{BASE}/{scenario_id}/apply",
        json={
            "expected_revision": state.plan_revision,
            "approve_exceptions": True,
            "approval_reason": "Reviewed fixture",
            "approval_author": "pytest",
            **extra,
        },
    )


def _snapshot(services):
    return serialize_snapshot(state), services.store.list()


def test_save_captures_full_origin_without_changing_live_plan(services):
    before = serialize_snapshot(state)
    origin = input_identity(state)
    saved = _save(services, name=" Scenario ", note=" Note ")
    plan = services.store.get(saved["scenario"]["id"])
    assert saved["status"] == "saved"
    assert {"scenario", "score_baseline", "score_scenario", "delta", "gate_report"} <= saved.keys()
    assert plan["name"] == "Scenario" and plan["note"] == "Note"
    assert plan["source"] == "scenario" and plan["origin"] == "fixture.xlsx"
    assert plan["payload"]["scenario_origin"] == origin
    assert plan["payload"]["active_mutations"] == MUTATIONS
    assert plan["payload"]["engine_data"]["ops"][0]["d"][9] == 40
    assert saved["score_baseline"] == before["score"]
    assert serialize_snapshot(state) == before
    assert_snapshot_integrity(plan["payload"], origin=plan["origin"])
    assert services.simulate.call_count == 1


def test_validation_and_serialization_stay_on_captured_state_while_writers_run(
    services, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    original_validate = data_api._validate_mutations
    origin = input_identity(state)
    before = serialize_snapshot(state)
    preview = services.client.post("/api/data/simulate", json={"mutations": MUTATIONS}).json()

    def paused_validate(*args, **kwargs):
        assert is_staging()
        entered.set()
        assert release.wait(5), "Test writer failed to release validation"
        assert input_identity(state) == origin
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(data_api, "_validate_mutations", paused_validate)

    async def exercise():
        task = asyncio.create_task(
            scenarios.save_scenario(
                scenarios.SaveScenarioRequest(
                    name="Concurrent",
                    mutations=MUTATIONS,
                    candidate_id=preview["candidate_id"],
                )
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 5)

            async def writer():
                async with services.lock:
                    with locks.commit_lock:
                        state.config.lst_safety_buffer += 1
                        state.engine_data.ops[0].d[0] = 17
                        state.active_mutations.append(
                            {"type": "add_holiday", "params": {"day_idx": 4}}
                        )
                        state.plan_revision += 1
                        state.dataset_info["filename"] = "replacement.xlsx"

            await asyncio.wait_for(writer(), timeout=1)
            expected_live = serialize_snapshot(state)
        finally:
            release.set()
        result = await asyncio.wait_for(task, timeout=10)
        assert serialize_snapshot(state) == expected_live
        return result

    saved = asyncio.run(exercise())
    plan = services.store.get(saved["scenario"]["id"])
    assert plan["origin"] == "fixture.xlsx"
    assert plan["payload"]["scenario_origin"] == origin
    assert plan["payload"]["plan_revision"] == 7
    assert plan["payload"]["config"] == before["config"]
    assert plan["payload"]["engine_data"]["ops"][0]["d"][0] == 0
    assert plan["payload"]["engine_data"]["ops"][0]["d"][9] == 40
    assert plan["payload"]["active_mutations"] == MUTATIONS


@pytest.mark.parametrize(
    "changed", ["revision", "dataset", "engine", "config", "schedule", "mutations"]
)
def test_apply_rejects_every_origin_change_before_restoring(services, monkeypatch, changed):
    saved = _save(services)
    if changed == "revision":
        state.plan_revision += 1
    elif changed == "dataset":
        state.dataset_info["id"] = "replacement"
    elif changed == "engine":
        state.engine_data.ops[0].d[0] += 1
    elif changed == "config":
        state.config.lst_safety_buffer += 1
    elif changed == "schedule":
        state.segments[0].end_min += 1
    else:
        state.active_mutations.append({"type": "add_holiday", "params": {"day_idx": 2}})
    before = _snapshot(services)
    restore = Mock(side_effect=AssertionError("Stale scenario reached restore"))
    monkeypatch.setattr(scenarios, "restore_plan_into_state", restore)
    response = _apply(services, saved["scenario"]["id"])
    assert response.status_code == 409, response.text
    assert _snapshot(services) == before
    restore.assert_not_called()


@pytest.mark.parametrize(
    "origin", [None, {}, {"dataset_id": "scenario-dataset", "base_revision": 7}, "legacy"]
)
def test_apply_rejects_legacy_or_incomplete_origin(services, monkeypatch, origin):
    saved = _save(services)
    original = services.store.get(saved["scenario"]["id"])
    payload = original["payload"]
    if origin is None:
        payload.pop("scenario_origin")
    else:
        payload["scenario_origin"] = origin
    legacy = services.store.save(
        name="Legacy",
        source="scenario",
        origin="fixture.xlsx",
        note="",
        payload=payload,
        score=payload["score"],
        gate_report=payload["gate_report"],
        is_auto=False,
    )
    before = _snapshot(services)
    restore = Mock(side_effect=AssertionError("Legacy scenario reached restore"))
    monkeypatch.setattr(scenarios, "restore_plan_into_state", restore)
    response = _apply(services, legacy["id"])
    assert response.status_code == 409, response.text
    assert _snapshot(services) == before
    restore.assert_not_called()


def test_apply_requests_exact_autosaved_restore_and_keeps_saved_schedule(services, monkeypatch):
    saved = _save(services)
    plan = services.store.get(saved["scenario"]["id"])
    expected = deserialize_snapshot(plan["payload"])
    original_restore = scenarios.restore_plan_into_state
    restore = Mock(wraps=original_restore)
    monkeypatch.setattr(scenarios, "restore_plan_into_state", restore)
    services.simulate.side_effect = AssertionError("Apply must not simulate again")
    import backend.plans.restore as restore_module

    # Restoring never optimizes: the repair routines are not even reachable.
    for name in (
        "normalize_earliest_legal_plan",
        "repair_short_runs_after_merged_campaigns",
        "_merge_detached_setup_segments",
    ):
        assert not hasattr(restore_module, name)
    response = _apply(services, plan["id"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "applied"
    assert restore.call_args.kwargs["preserve_exact"] is True
    assert restore.call_args.kwargs["autosave"] is True
    assert restore.call_args.kwargs["expected_revision"] == 7
    assert state.plan_revision == 8
    assert state.dataset_info["id"] == "scenario-dataset"
    assert state.segments == expected["result"].segments
    assert state.lots == expected["result"].lots
    assert state.engine_data == expected["engine_data"]
    assert state.config == expected["config"]
    autosaved = services.store.latest()
    assert autosaved["payload"]["segments"] == plan["payload"]["segments"]
    assert autosaved["payload"]["lots"] == plan["payload"]["lots"]
    assert services.store.get(plan["id"])["payload"] == plan["payload"]


def _gate_override(monkeypatch, **changes):
    import backend.plans.restore as restore_module

    real = restore_module.build_gate_report

    def report(*args, **kwargs):
        return {**real(*args, **kwargs), **changes}

    monkeypatch.setattr(restore_module, "build_gate_report", report)


def test_apply_needing_approval_is_not_reported_as_physical_conflicts(services, monkeypatch):
    """Rehearsal of 11/10/2026: a saved scenario whose only reason to stop is an
    approval (operational_sequence_review) was refused as "conflitos físicos"."""
    saved = _save(services)
    _gate_override(
        monkeypatch, physical_gate_passed=True, coverage_gate_passed=True,
        apply_decision="approval_required", requires_approval=True,
        approval_reasons=["operational_sequence_review"],
    )
    before = _snapshot(services)

    response = _apply(services, saved["scenario"]["id"], approve_exceptions=False,
                      approval_reason="", approval_author="")

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "approval_required"
    assert detail["requires_approval"] is True
    assert detail["approval_reasons"] == ["operational_sequence_review"]
    assert detail["gate_report"]["requires_approval"] is True
    assert "não tem conflitos físicos" in detail["message"]
    assert "conflitos físicos e não pode" not in detail["message"]
    assert "operational_sequence_review" not in detail["message"]
    assert "a sequência das máquinas" in detail["message"]
    assert _snapshot(services) == before

    incomplete = _apply(services, saved["scenario"]["id"], approval_reason=" ")
    assert incomplete.status_code == 409, incomplete.text
    assert incomplete.json()["detail"]["code"] == "approval_required"
    assert "motivo e autor" in incomplete.json()["detail"]["message"]
    assert _snapshot(services) == before

    approved = _apply(services, saved["scenario"]["id"])
    assert approved.status_code == 200, approved.text
    assert state.approvals[-1]["approval_reasons"] == ["operational_sequence_review"]


def test_apply_of_a_physically_blocked_scenario_explains_the_block(services, monkeypatch):
    saved = _save(services)
    _gate_override(monkeypatch, physical_gate_passed=False, apply_decision="blocked",
                   requires_approval=False)
    before = _snapshot(services)

    response = _apply(services, saved["scenario"]["id"])

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "blocked"
    assert detail["message"] == (
        "O cenário não pode ser aplicado: O candidato tem conflitos físicos e não pode "
        "substituir o plano."
    )
    assert _snapshot(services) == before


def test_restore_rejection_keeps_live_state_and_store_unchanged(services, monkeypatch):
    saved = _save(services)
    before = _snapshot(services)
    monkeypatch.setattr(
        scenarios, "restore_plan_into_state", Mock(side_effect=ValueError("invalid candidate"))
    )
    response = _apply(services, saved["scenario"]["id"])
    assert response.status_code == 409, response.text
    assert _snapshot(services) == before


def test_save_can_reuse_optional_preview_without_calculating(services):
    baseline = transactions.clone_state(state)
    result = simulate(
        baseline.engine_data, baseline.score, data_api._mutation_models(MUTATIONS), baseline.config
    )
    candidate = candidates.previews.put("simulation", baseline, {"mutations": MUTATIONS}, result)
    services.simulate.side_effect = AssertionError("Saving a preview must not recalculate")
    saved = _save(services, candidate_id=candidate.id)
    plan = services.store.get(saved["scenario"]["id"])
    assert plan["payload"]["segments"] == [asdict(segment) for segment in result.segments]
    assert plan["payload"]["lots"] == [asdict(lot) for lot in result.lots]
    assert plan["payload"]["scenario_origin"] == candidate.origin
    services.simulate.assert_not_called()


@pytest.mark.parametrize("invalid", ["missing", "expired", "parameters", "origin"])
def test_invalid_optional_preview_is_rejected_without_fallback(services, invalid):
    baseline = transactions.clone_state(state)
    result = simulate(
        baseline.engine_data, baseline.score, data_api._mutation_models(MUTATIONS), baseline.config
    )
    candidate = candidates.previews.put("simulation", baseline, {"mutations": MUTATIONS}, result)
    candidate_id = candidate.id
    if invalid == "missing":
        candidate_id = "unknown"
    elif invalid == "expired":
        candidates.previews.ttl_seconds = -1
    elif invalid == "parameters":
        candidate.parameters = {"mutations": []}
    else:
        state.config.lst_safety_buffer += 1
    before = _snapshot(services)
    response = services.client.post(
        BASE, json={"name": "Scenario", "mutations": MUTATIONS, "candidate_id": candidate_id}
    )
    assert response.status_code == 409, response.text
    assert _snapshot(services) == before
    services.simulate.assert_not_called()


def test_already_materialized_mutations_are_not_applied_twice(services):
    active = {"type": "add_holiday", "params": {"day_idx": 2}}
    apply_mutation(state.engine_data, active["type"], active["params"], state.config)
    state.active_mutations = [active]
    before = serialize_snapshot(state)
    saved = _save(services, mutations=[{"type": "add_holiday", "params": {"day_idx": "2"}}])
    assert services.simulate.call_args.args[2] == []
    assert services.simulate.call_args.kwargs["active_mutations"] == [active]
    plan = services.store.get(saved["scenario"]["id"])
    assert plan["payload"]["active_mutations"] == [active]
    assert plan["payload"]["segments"] == before["segments"]
    assert serialize_snapshot(state) == before


def test_invalid_mutation_does_not_save_or_mutate(services):
    before = _snapshot(services)
    response = services.client.post(
        BASE,
        json={
            "name": "Invalid",
            "mutations": [
                {"type": "rush_order", "params": {"sku": "UNKNOWN", "qty": 1, "deadline_day": 9}}
            ],
        },
    )
    assert response.status_code == 400, response.text
    assert _snapshot(services) == before
    services.simulate.assert_not_called()
