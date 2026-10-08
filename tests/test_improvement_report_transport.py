"""Improvement evidence survives preview, persistence, apply and recovery."""

import copy
from contextlib import closing
from dataclasses import replace

import pytest

from backend.api import data as data_api
from backend.copilot.state import CopilotState
from backend.plans.serialize import (
    _finalize_snapshot,
    assert_snapshot_integrity,
    deserialize_snapshot,
    serialize_result_snapshot,
    serialize_simulation_snapshot,
    serialize_snapshot,
)
from backend.scheduler.gates import build_gate_report
from backend.scheduler.improvement import improve_plan, improvement_gate_summary
from backend.scheduler.scoring import compute_score
from backend.simulator.simulator import simulate
from tests.test_plans import _loaded_state
from tests.test_replan_jobs import _apply, ready_replan  # noqa: F401


@pytest.fixture
def reported_state(monkeypatch):
    monkeypatch.setattr(CopilotState, "_refresh_analytics", lambda self: None)
    loaded = _loaded_state()
    restored = deserialize_snapshot(serialize_snapshot(loaded))
    result = restored["result"]
    rows, lots, report = improve_plan(
        result.segments, result.lots, loaded.engine_data, loaded.config, time_budget_s=0,
    )
    assert report["status"] == "partial", report
    result.segments, result.lots, result.improvement_report = rows, lots, report
    result.gate_report = build_gate_report(rows, lots, result.score, loaded.engine_data, loaded.config)
    result.gate_report["improvement"] = improvement_gate_summary(
        report, rows, lots, loaded.engine_data, loaded.config,
    )
    loaded.update_schedule(result)
    return loaded, result, copy.deepcopy(report)


@pytest.mark.parametrize("writer", ["state", "result", "simulation"])
def test_report_round_trip_preserves_full_evidence(reported_state, writer):
    loaded, result, report = reported_state
    if writer == "state":
        payload = serialize_snapshot(loaded)
    elif writer == "result":
        payload = serialize_result_snapshot(
            loaded.engine_data, loaded.config, result,
            plan_revision=loaded.plan_revision, dataset_info=loaded.dataset_info,
        )
    else:
        simulation = simulate(
            loaded.engine_data, loaded.score, [], loaded.config, baseline_result=result,
        )
        payload = serialize_simulation_snapshot(loaded, simulation, [])
    before = copy.deepcopy(payload)
    assert payload["improvement_report"] == report
    restored = deserialize_snapshot(payload)["result"]
    assert restored.improvement_report == report
    assert restored.gate_report["improvement"]["status"] == "partial"
    restored.improvement_report["scopes"].clear()
    assert payload == before
    assert_snapshot_integrity(payload)


def test_report_is_covered_by_snapshot_fingerprint(reported_state):
    loaded, _result, report = reported_state
    payload = serialize_snapshot(loaded)
    assert payload["improvement_report"] == report
    payload["improvement_report"]["status"] = "completed"
    with pytest.raises(ValueError, match="conteúdo do plano"):
        assert_snapshot_integrity(payload)


def test_old_snapshot_without_report_keeps_valid_fingerprint(reported_state):
    loaded, _result, _report = reported_state
    legacy = serialize_snapshot(loaded)
    legacy.pop("improvement_report", None)
    legacy = _finalize_snapshot(legacy)
    before = copy.deepcopy(legacy)
    restored = deserialize_snapshot(legacy)
    assert restored["result"].improvement_report is None
    assert legacy == before
    assert_snapshot_integrity(legacy)


def test_state_capture_and_revert_preserve_independent_report(reported_state, monkeypatch):
    loaded, _result, report = reported_state
    monkeypatch.setattr(data_api, "state", loaded)
    captured = data_api._schedule_result_from_state()
    assert captured.improvement_report == report
    loaded.save_current()
    assert loaded.saved_schedule.improvement_report == report
    loaded.improvement_report["scopes"].clear()
    assert loaded.saved_schedule.improvement_report == report
    loaded.update_schedule(loaded.saved_schedule)
    assert loaded.improvement_report == report


@pytest.mark.parametrize("new_calculation", [False, True])
def test_simulation_result_and_conversion_keep_full_report(reported_state, monkeypatch, new_calculation):
    loaded, result, report = reported_state
    monkeypatch.setattr("backend.simulator.simulator.optimize", lambda *_a, **_k: copy.deepcopy(result))
    response = simulate(
        loaded.engine_data, loaded.score, [], loaded.config,
        baseline_result=None if new_calculation else result,
    )
    assert response.improvement_report == report
    assert data_api._schedule_result_from_simulation(response).improvement_report == report


@pytest.mark.parametrize("status", ["completed", "partial"])
def test_changed_candidate_does_not_inherit_verification_status(reported_state, status):
    loaded, result, report = reported_state
    report["status"] = status
    rows = [replace(result.segments[0], start_min=600, end_min=690)]
    summary = improvement_gate_summary(report, rows, result.lots, loaded.engine_data, loaded.config)
    assert summary["status"] == "not_evaluated"
    assert summary["stop_reason"] == "candidate_changed"
    assert summary["moves_accepted"] == 0
    assert report["status"] == status


def test_job_capacity_release_keeps_report_through_apply_and_reopening(ready_replan, monkeypatch):  # noqa: F811
    from datetime import datetime
    from unittest.mock import Mock

    from backend.plans.store import PlansStore
    from backend.replan import jobs

    live, manager, _old_job, result, _config_path = ready_replan
    live.engine_data.workdays = ["2026-10-05", "2026-10-06"]
    clock = Mock(wraps=datetime)
    fixed = datetime.fromisoformat(live.engine_data.workdays[0] + "T12:00:00+01:00")
    clock.now.side_effect = lambda tz: fixed.astimezone(tz)
    monkeypatch.setattr("backend.plans.frozen.datetime", clock)
    live.engine_data.ops[0].stk = 0
    result.segments = [replace(result.segments[0], start_min=600, end_min=690)]
    result.score = compute_score(result.segments, result.lots, live.engine_data, live.config)
    live.update_schedule(result)
    baseline = serialize_snapshot(live)
    config = copy.deepcopy(live.config)
    config.operators[("Grandes", "A")] += 1
    captured = {}
    real_compact = jobs.compact_preserving_started_lots
    monkeypatch.setattr("backend.planning_control.improvement_time_budget", lambda *_: 0.0)

    def compact(*args, **kwargs):
        candidate = real_compact(*args, **kwargs)
        captured["report"] = copy.deepcopy(candidate.improvement_report)
        return candidate

    monkeypatch.setattr(jobs, "compact_preserving_started_lots", compact)
    job = manager.store.create(
        "release", "fixture", live.plan_revision,
        base_input_fingerprints=jobs.replan_base_fingerprints(baseline),
    )
    manager._run(
        job["id"], copy.deepcopy(live.engine_data), config,
        "fixture", live.plan_revision, "release", copy.deepcopy(live.dataset_info),
        baseline_snapshot=baseline, reoptimize_relaxed_baseline=True,
    )
    current = manager.get(job["id"])
    assert current["status"] == "ready", current
    assert current["result"]["selected_source"] == "compacted_baseline_after_capacity_release"
    assert captured["report"]["status"] == "partial"
    assert current["result"]["gate_report"].get("improvement", {}).get("status") == "partial"
    report = captured["report"]
    payload = manager.store.get_candidate(job["id"])
    assert payload["improvement_report"] == report
    assert current["result"]["improvement_report"] == report
    _apply(manager, job["id"], revision=live.plan_revision)
    assert live.improvement_report == report
    assert live.gate_report["improvement"]["status"] == "partial"
    database = live.plans_store._conn.execute("PRAGMA database_list").fetchone()[2]
    with closing(PlansStore(database)) as reopened:
        active = reopened.active()["payload"]
        restored = deserialize_snapshot(active)["result"]
        assert restored.improvement_report == report
        assert restored.gate_report["improvement"] == live.gate_report["improvement"]


@pytest.mark.parametrize("case", ["exact", "legacy", "changed_inputs"])
def test_restore_preserves_evidence_without_running_improvement(reported_state, monkeypatch, case):
    from backend.plans.restore import restore_plan_into_state

    loaded, _result, report = reported_state
    payload = serialize_snapshot(loaded)
    if case == "legacy":
        payload.pop("improvement_report")
        payload = _finalize_snapshot(payload)
    config = copy.deepcopy(loaded.config)
    if case == "changed_inputs":
        config.operators[("Grandes", "A")] += 1
    target = CopilotState(config=config)

    def unexpected_search(*_a, **_k):
        pytest.fail("Restoring exact stored production must not run an improvement search")

    monkeypatch.setattr("backend.scheduler.improvement.improve_plan", unexpected_search)
    response = restore_plan_into_state(
        {"id": "stored", "name": "stored", "origin": "isop.xlsx", "payload": payload},
        target, prefer_current_config=True, preserve_exact=True, recover_existing=True,
    )
    assert target.segments == loaded.segments
    assert target.lots == loaded.lots
    assert response["improvement_report"] == target.improvement_report
    if case == "exact":
        assert target.improvement_report == report
        assert target.gate_report["improvement"]["status"] == "partial"
    else:
        assert target.gate_report["improvement"]["status"] == "not_evaluated"
        if case == "changed_inputs":
            assert target.improvement_report["stop_reason"] == "inputs_changed"
