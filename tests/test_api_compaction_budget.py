"""The actual recalculate path budgets compaction and its final checks; no robustness."""

import copy
from threading import Event

import pytest

from backend.api import data as data_api
from backend.copilot.state import CopilotState
from backend.planning_control import (
    PlanningCancelled, PlanningTimeout, current_planning_control, planning_checkpoint,
    planning_scope, remaining_time,
)
from tests.test_named_planning_workflows import named_planning_case


@pytest.fixture
def compact_state(monkeypatch):
    _, _, data, config, baseline = named_planning_case("bfp082_initial_priority")
    target = CopilotState(engine_data=data, config=config, segments=baseline.segments,
                          lots=baseline.lots, score=baseline.score, gate_report=baseline.gate_report)
    monkeypatch.setattr(data_api, "state", target)
    monkeypatch.setattr("backend.plans.frozen.compact_preserving_started_lots",
                        lambda *_args: copy.deepcopy(baseline))
    return target, baseline


def _observe_final_gate(monkeypatch, observe):
    from backend.scheduler import gates

    build = gates.build_gate_report

    def wrapped(*args, **kwargs):
        observe()
        return build(*args, **kwargs)

    monkeypatch.setattr("backend.scheduler.gates.build_gate_report", wrapped)


def _no_robustness_battery(monkeypatch):
    def battery(*_args, **_kwargs):
        raise AssertionError("robustness is informational and never runs in recalculation")

    monkeypatch.setattr("backend.risk.robustness.run_robustness_battery", battery)


def test_direct_compaction_establishes_one_total_budget(compact_state, monkeypatch):
    target, _ = compact_state
    observed = []

    def observe():
        control = current_planning_control()
        assert control is not None, "Recalculate leaves the final gate unbounded"
        observed.append(remaining_time())

    _no_robustness_battery(monkeypatch)
    _observe_final_gate(monkeypatch, observe)
    data_api._compact_active_schedule(target.config)
    assert len(observed) == 1
    assert 0 < observed[0] <= 60
    assert current_planning_control() is None


@pytest.mark.parametrize("persisted", [
    {"robustness_evaluated_samples": 0},
    {"robustness_evaluated_samples": 100, "robustness_gate_passed": False,
     "robustness_success_probability_pct": 10.0, "robustness_threshold_pct": 95.0},
])
def test_old_robustness_keys_never_drive_approval(compact_state, monkeypatch, persisted):
    target, baseline = compact_state
    baseline.score.update(persisted)
    _no_robustness_battery(monkeypatch)
    result = data_api._compact_active_schedule(target.config)
    assert result.gate_report["physical_gate_passed"]
    assert result.gate_report["robustness_gate_passed"] is None
    assert not any(
        reason.startswith("robustness") for reason in result.gate_report["approval_reasons"]
    )
    assert not any(key.startswith("robustness_") for key in result.gate_report["metrics"])
    assert result.segments == baseline.segments


def test_nested_compaction_cannot_restart_the_callers_deadline(compact_state, monkeypatch):
    target, _ = compact_state
    clock = [0.0]
    observed = []

    _observe_final_gate(monkeypatch, lambda: observed.append(remaining_time()))
    with planning_scope(timeout_s=12, clock=lambda: clock[0]):
        data_api._compact_active_schedule(target.config)
    assert len(observed) == 1
    assert 0 < observed[0] <= 12


def test_cancelling_the_final_gate_does_not_publish_the_candidate(compact_state, monkeypatch):
    target, baseline = compact_state
    original = copy.deepcopy((target.segments, target.lots, target.score, target.plan_revision))
    event = Event()

    def cancel():
        event.set()
        planning_checkpoint()

    _observe_final_gate(monkeypatch, cancel)
    with pytest.raises(PlanningCancelled), planning_scope(timeout_s=60, cancel_event=event):
        data_api._compact_active_schedule(target.config)
    assert (target.segments, target.lots, target.score, target.plan_revision) == original
    assert baseline.segments == original[0]


@pytest.mark.parametrize("cancel", [False, True])
def test_interruption_during_final_analytics_rolls_back_transaction(compact_state, monkeypatch, cancel):
    target, _ = compact_state
    fields = (
        "engine_data", "config", "segments", "lots", "score", "plan_revision",
        "gate_report", "improvement_report", "approvals", "manual_edits",
        "stock_projections", "expedition", "risk_result", "late_deliveries",
        "coverage", "order_tracking", "stress_map",
    )
    original = copy.deepcopy({key: getattr(target, key) for key in fields})
    clock, event = [0.0], Event()
    update = target.update_schedule

    def interrupted_update(result):
        update(result)
        if cancel:
            event.set()
        else:
            clock[0] = 61.0

    monkeypatch.setattr("backend.plans.context.is_staging", lambda: True)
    monkeypatch.setattr(target, "update_schedule", interrupted_update)
    error = PlanningCancelled if cancel else PlanningTimeout
    with pytest.raises(error), planning_scope(timeout_s=60, clock=lambda: clock[0], cancel_event=event):
        data_api._recompute_transactional(target.config, {"compact_active_plan": True})
    assert {key: getattr(target, key) for key in fields} == original
