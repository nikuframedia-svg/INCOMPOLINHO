"""Interruption cannot become a successful partial analytics/production write."""

import asyncio
import copy
import importlib
import json
from threading import Event
from unittest.mock import Mock

import pytest

from backend import planning_control as control
from backend.copilot.state import CopilotState
from backend.plans import transactions
from backend.plans.serialize import serialize_snapshot
from tests.test_named_planning_workflows import named_planning_case
from tests.test_plan_transactions import planning as _planning_fixture

planning = _planning_fixture

ANALYTICS = (
    "backend.analytics.expedition.compute_expedition",
    "backend.analytics.stock_projection.compute_stock_projections",
    "backend.analytics.order_tracking.compute_order_tracking",
    "backend.risk.compute_risk",
    "backend.analytics.late_delivery.analyze_late_deliveries",
    "backend.analytics.coverage_audit.compute_coverage_audit",
    "backend.copilot.state._compute_stress",
)


def replace_analytics(monkeypatch, path, fn):
    module, name = path.rsplit(".", 1)
    monkeypatch.setattr(importlib.import_module(module), name, fn)


@pytest.mark.parametrize("index", range(len(ANALYTICS)))
@pytest.mark.parametrize("error", [control.PlanningTimeout, control.PlanningCancelled])
def test_analytics_propagates_planning_interruption(monkeypatch, index, error):
    _, _, data, config, _ = named_planning_case("bfp082_initial_priority")
    target = CopilotState(engine_data=data, config=config)
    calls = []
    for position, path in enumerate(ANALYTICS):
        fn = Mock(side_effect=error("interrupted") if position == index else None, return_value=[])
        calls.append(fn)
        replace_analytics(monkeypatch, path, fn)
    with pytest.raises(error):
        target._refresh_analytics()
    assert all(fn.call_count == 0 for fn in calls[index + 1:])


def test_unrelated_analytics_error_remains_isolated(monkeypatch):
    _, _, data, config, _ = named_planning_case("bfp082_initial_priority")
    target = CopilotState(engine_data=data, config=config)
    monkeypatch.setattr(ANALYTICS[0], Mock(side_effect=ValueError("bad indicator")))
    stock = Mock(return_value=["healthy indicator"])
    monkeypatch.setattr(ANALYTICS[1], stock)
    target._refresh_analytics()
    assert target.expedition is None
    assert target.stock_projections == ["healthy indicator"]
    stock.assert_called_once()


@pytest.fixture
def writer_clock(monkeypatch):
    now, event = [0.0], Event()
    scope = control.planning_scope

    def timed_scope(**options):
        options.setdefault("clock", lambda: now[0])
        options.setdefault("cancel_event", event)
        return scope(**options)

    monkeypatch.setattr(transactions, "planning_scope", timed_scope, raising=False)
    return now, event


@pytest.mark.parametrize("adapter", ["sync", "async"])
def test_each_writer_establishes_deadline_for_entire_callback(planning, writer_clock, adapter):
    observed = []

    def calculate():
        observed.append(control.remaining_time())
        return {"status": "unchanged"}

    if adapter == "sync":
        response = transactions.run_sync_mutation(planning.state, calculate)
    else:
        state = planning.state

        @transactions.plan_writer
        async def write(body: dict):
            assert state is planning.state
            return calculate()

        response = asyncio.run(write({"expected_revision": 7}))
    assert response["status"] == "unchanged"
    assert observed == [60.0]


@pytest.mark.parametrize("adapter", ["sync", "async"])
@pytest.mark.parametrize("cancel", [False, True])
def test_interrupted_callback_cannot_commit_state_or_files(planning, writer_clock, adapter, cancel):
    now, event = writer_clock
    live = planning.state
    baseline = serialize_snapshot(live)
    before_config = planning.config_path.read_bytes()

    def calculate():
        live.rules.append({"id": "pending", "value": 2})
        live.config.name = "pending configuration"
        live.plan_revision += 1
        if cancel:
            event.set()
        else:
            now[0] = 61.0
        return {"status": "ok"}

    error = control.PlanningCancelled if cancel else control.PlanningTimeout
    with pytest.raises(error):
        if adapter == "sync":
            transactions.run_sync_mutation(live, calculate, operation_id="interrupted")
        else:
            state = live

            @transactions.plan_writer
            async def write(body: dict):
                assert state is live
                return calculate()

            asyncio.run(write({"request_id": "interrupted", "expected_revision": 7}))
    assert serialize_snapshot(live) == baseline
    assert planning.config_path.read_bytes() == before_config
    assert planning.store.mutation_receipt("interrupted") is None
    assert not planning.store.pending_mutations()


@pytest.mark.parametrize("cancel", [False, True])
def test_interruption_in_precommit_validation_keeps_live_state(planning, writer_clock, monkeypatch, cancel):
    from backend.plans.context import before_commit

    now, event = writer_clock
    live = planning.state
    baseline = serialize_snapshot(live)

    def validation():
        if cancel:
            event.set()
        else:
            now[0] = 61.0

    def calculate():
        live.rules.append({"id": "pending", "value": 2})
        live.plan_revision += 1
        before_commit(validation)
        return {"status": "ok"}

    error = control.PlanningCancelled if cancel else control.PlanningTimeout
    with pytest.raises(error):
        transactions.run_sync_mutation(live, calculate, operation_id="before-commit")
    assert serialize_snapshot(live) == baseline
    assert planning.store.mutation_receipt("before-commit") is None


@pytest.mark.parametrize("adapter", ["sync", "async"])
def test_commit_acknowledged_after_deadline_returns_durable_receipt(planning, writer_clock, monkeypatch, adapter):
    now, _ = writer_clock
    live = planning.state
    commit = planning.store.commit_mutation
    calls = []

    def late_ack(*args, **kwargs):
        commit(*args, **kwargs)
        now[0] = 61.0

    def calculate():
        calls.append(1)
        live.rules.append({"id": "committed", "value": 3})
        live.plan_revision += 1
        return {"status": "ok"}

    monkeypatch.setattr(planning.store, "commit_mutation", late_ack)
    if adapter == "sync":
        def run():
            return transactions.run_sync_mutation(live, calculate, operation_id="late-ack", request_fingerprint="same")
    else:
        state = live

        @transactions.plan_writer
        async def write(body: dict):
            assert state is live
            return calculate()

        def run():
            return asyncio.run(write({"request_id": "late-ack", "expected_revision": 7}))

    result = run()
    assert result["status"] == "ok"
    assert planning.store.mutation_receipt("late-ack")["status"] == "committed"
    assert live.plan_revision == 8
    repeated = run()
    assert repeated == result
    assert calls == [1]


@pytest.mark.parametrize("mode,budget", [("quick", 60), ("normal", 60), ("smart", 60), ("deep", 300), ("max", 600)])
def test_sync_writer_keeps_existing_calculation_profiles(planning, writer_clock, mode, budget):
    observed = []

    def calculate():
        observed.append(control.remaining_time())
        return {"status": "unchanged"}

    transactions.run_sync_mutation(planning.state, calculate, planning_mode=mode)
    assert observed == [budget]


def test_writer_never_extends_outer_deadline(planning, writer_clock):
    now, _ = writer_clock
    observed = []
    with control.planning_scope(timeout_s=12, clock=lambda: now[0]):
        transactions.run_sync_mutation(planning.state, lambda: observed.append(control.remaining_time()))
    assert observed == [12]


@pytest.mark.parametrize("adapter", ["action", "engine"])
@pytest.mark.parametrize("mode,budget", [("quick", 60), ("normal", 60), ("smart", 60), ("deep", 300), ("max", 600)])
def test_copilot_dispatch_preserves_profile_budget(planning, writer_clock, monkeypatch, adapter, mode, budget):
    from backend.copilot import engine, executors_action

    observed = []

    def exec_recalcular_plano(args):
        observed.append(control.remaining_time())
        return json.dumps({"status": "unchanged"})

    monkeypatch.setattr(executors_action, "state", planning.state)
    replace_analytics(monkeypatch, "backend.copilot.state.state", planning.state)
    exec_recalcular_plano.__module__ = "backend.copilot.executors_action"
    executor = executors_action._production_action(exec_recalcular_plano)
    if adapter == "action":
        executor({"modo": mode})
    else:
        monkeypatch.setitem(engine.EXECUTORS, "recalcular_plano", executor)
        response, _ = engine.execute_tool("recalcular_plano", json.dumps({"modo": mode}))
        assert json.loads(response)["status"] == "unchanged"
    assert observed == [budget]


def test_manual_move_reserves_the_same_close_budget(monkeypatch):
    from backend.plans import frozen, manual_move

    _, _, data, config, result = named_planning_case("bfp082_initial_priority")
    now, observed = [0.0], []

    def improve(candidate, *_args, time_budget_s):
        observed.append(time_budget_s)
        return candidate, {"status": "partial"}

    monkeypatch.setattr(frozen, "improve_preserving_protected_lots", improve)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 0)
    with control.planning_scope(timeout_s=60, clock=lambda: now[0]):
        now[0] = 48
        manual_move._finalize_move_candidate(result, data, config, result.lots)
    assert observed == [2]


@pytest.mark.parametrize("adapter", ["sync", "async"])
@pytest.mark.parametrize("error", [control.PlanningTimeout, control.PlanningCancelled])
def test_master_executor_keeps_interruption_identity(planning, writer_clock, monkeypatch, adapter, error):
    from backend.api.data import _exec_result
    from backend.copilot import executors_master

    live = planning.state
    before = serialize_snapshot(live)
    monkeypatch.setattr(executors_master, "state", live)

    @executors_master._transactional_master
    def calculate(args):
        live.config.name = "pending configuration"
        live.plan_revision += 1
        raise error("child calculation interrupted")

    with pytest.raises(error):
        if adapter == "sync":
            calculate({"expected_revision": 7})
        else:
            state = live

            @transactions.plan_writer
            async def write(body: dict):
                assert state is live
                return _exec_result(calculate(body))

            asyncio.run(write({"expected_revision": 7}))
    assert serialize_snapshot(live) == before
    assert not planning.store.pending_mutations()


@pytest.mark.parametrize("error,status,code", [
    (control.PlanningTimeout, 504, "planning_timeout"),
    (control.PlanningCancelled, 409, "planning_cancelled"),
])
def test_legacy_api_preserves_planning_error_response(planning, writer_clock, monkeypatch, error, status, code):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.copilot import planning_cancelled_handler, planning_timeout_handler
    from backend.api.data import _exec_result
    from backend.copilot import executors_master

    live = planning.state
    before = serialize_snapshot(live)
    monkeypatch.setattr(executors_master, "state", live)
    app = FastAPI()
    app.add_exception_handler(control.PlanningTimeout, planning_timeout_handler)
    app.add_exception_handler(control.PlanningCancelled, planning_cancelled_handler)

    @executors_master._transactional_master
    def calculate(args):
        live.config.name = "pending configuration"
        raise error("child calculation interrupted")

    state = live

    @app.put("/legacy")
    @transactions.plan_writer
    async def write(body: dict):
        assert state is live
        return _exec_result(calculate(body))

    with TestClient(app) as client:
        response = client.put("/legacy", json={"expected_revision": 7})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert serialize_snapshot(live) == before
    assert not planning.store.pending_mutations()


@pytest.mark.parametrize("cancel", [False, True])
def test_analytics_checks_deadline_even_without_an_explicit_exception(monkeypatch, cancel):
    _, _, data, config, _ = named_planning_case("bfp082_initial_priority")
    target = CopilotState(engine_data=data, config=config)
    now, event = [0.0], Event()
    stock = Mock(return_value=[])

    def late_expedition(*_args, **_kwargs):
        if cancel:
            event.set()
        else:
            now[0] = 61.0
        return "incomplete"

    monkeypatch.setattr(ANALYTICS[0], late_expedition)
    monkeypatch.setattr(ANALYTICS[1], stock)
    error = control.PlanningCancelled if cancel else control.PlanningTimeout
    with pytest.raises(error), control.planning_scope(timeout_s=60, clock=lambda: now[0], cancel_event=event):
        target._refresh_analytics()
    assert target.expedition is None
    stock.assert_not_called()


@pytest.mark.parametrize("cancel", [False, True])
def test_interruption_after_file_preparation_rolls_back_every_file(planning, writer_clock, monkeypatch, cancel):
    now, event = writer_clock
    live = planning.state
    baseline = serialize_snapshot(live)
    before_config = planning.config_path.read_bytes()
    rules_path = transactions._rules_path()
    before_rules = rules_path.read_bytes() if rules_path.exists() else None
    before_runtime = planning.store.runtime_identity()
    prepare = transactions._prepare_files

    def interrupted_preparation(*args, **kwargs):
        result = prepare(*args, **kwargs)
        if cancel:
            event.set()
        else:
            now[0] = 61.0
        return result

    def calculate():
        live.config.name = "pending configuration"
        live.rules.append({"id": "pending", "value": 2})
        live.plan_revision += 1
        return {"status": "ok"}

    monkeypatch.setattr(transactions, "_prepare_files", interrupted_preparation)
    error = control.PlanningCancelled if cancel else control.PlanningTimeout
    with pytest.raises(error):
        transactions.run_sync_mutation(live, calculate, operation_id="late-files")
    assert serialize_snapshot(live) == baseline
    assert planning.config_path.read_bytes() == before_config
    assert (rules_path.read_bytes() if rules_path.exists() else None) == before_rules
    assert planning.store.runtime_identity() == before_runtime
    assert planning.store.mutation_receipt("late-files") is None
    assert not planning.store.pending_mutations()
    assert not list(planning.config_path.parent.glob("*.prepared-*"))


@pytest.mark.parametrize("path", ["direct", "protected"])
@pytest.mark.parametrize("mode", ["normal", "deep", "max"])
def test_improvement_reserve_closes_budget(monkeypatch, path, mode):
    from backend.cpo import optimizer
    from backend.plans import frozen

    _, _, data, config, baseline = named_planning_case("bfp082_initial_priority")
    now, observed = [0.0], {}
    total = optimizer.MODE_CONFIG[mode]["time_budget_s"]

    def robustness(*_args, **_kwargs):
        raise AssertionError("robustness is informational and never runs in planning")

    monkeypatch.setattr("backend.risk.robustness.run_robustness_battery", robustness)
    with control.planning_scope(timeout_s=total, clock=lambda: now[0]):
        if path == "direct":
            def improve(segments, lots, *_args, time_budget_s):
                observed["improvement"] = time_budget_s
                return segments, lots, {"moves_accepted": 1, "status": "partial"}

            monkeypatch.setattr("backend.scheduler.improvement.improve_plan", improve)
            now[0] = total - 12
            optimizer._apply_improvement_phase(baseline, data, config, mode=mode, seed=42)
        else:
            def construct(*_args, **_kwargs):
                now[0] = total - 12
                return copy.deepcopy(baseline)

            def improve(result, *_args, time_budget_s):
                observed["improvement"] = time_budget_s
                return result, {"moves_accepted": 0, "status": "partial"}

            monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 0)
            monkeypatch.setattr(frozen, "improve_preserving_protected_lots", improve)
            frozen.optimize_preserving_started_lots(data, config, baseline, mode=mode, optimizer=construct)
    assert 0 < observed["improvement"] <= 2


@pytest.mark.parametrize("outcome", ["completed", "no_time"])
def test_improvement_preserves_solver_evidence(monkeypatch, outcome):
    from backend.cpo import optimizer

    _, _, data, config, result = named_planning_case("bfp082_initial_priority")
    now = [0.0]
    trace = {"final_source": "candidate_search", "candidate_search": {"evaluated": 3}}
    result.gate_report = {
        "solver_trace": copy.deepcopy(trace), "solver_status": "timeout_with_candidate",
        "feasibility": "best_effort", "physical_gate_passed": False,
    }

    def improve(segments, lots, *_args, **_kwargs):
        if outcome == "no_time":
            now[0] = 51.0
        return segments, lots, {"moves_accepted": 1, "status": "completed"}

    monkeypatch.setattr("backend.scheduler.improvement.improve_plan", improve)
    with control.planning_scope(timeout_s=60, clock=lambda: now[0]):
        optimizer._apply_improvement_phase(result, data, config, mode="normal", seed=123)
    assert result.gate_report["physical_gate_passed"] is True
    assert result.gate_report["solver_trace"] == trace
    assert result.gate_report["solver_status"] == "timeout_with_candidate"
    assert result.gate_report["feasibility"] == "best_effort"
    assert result.gate_report["improvement"]["status"] == "completed"


def test_native_polisher_uses_fixed_single_worker_seed(monkeypatch):
    from backend.cpo import cpsat_polish as polish
    from tests.test_cpsat_polish import _make_data, _make_segments_and_lots

    observed = []

    def solve(solver, _model):
        observed.append((
            solver.parameters.num_workers or solver.parameters.num_search_workers,
            solver.parameters.random_seed,
        ))
        return polish.cp_model.UNKNOWN

    monkeypatch.setattr(polish, "solve_cpsat", solve)
    _, _, runs = _make_segments_and_lots(_make_data())
    assert polish._resequence_machine_cpsat(runs["PRM019"], 30, 1020) is None
    assert observed == [(1, 42)]


@pytest.mark.parametrize("seed", [0, 123])
def test_optimizer_passes_seed_to_native_polisher(monkeypatch, seed):
    import time

    from backend.cpo import cpsat_polish as polish
    from backend.cpo import optimizer

    _, _, data, config, baseline = named_planning_case("bfp082_initial_priority")
    observed = []

    def native(segments, lots, *_args, **kwargs):
        observed.append(kwargs.get("seed"))
        return segments, lots, copy.deepcopy(baseline.score)

    monkeypatch.setattr(polish, "cpsat_polish", native)
    cfg = {**optimizer.MODE_CONFIG["normal"], "candidate_search": False}
    result = optimizer._improve_baseline(
        data, config, baseline, "normal", cfg, seed, time.perf_counter(), time.monotonic() + 60,
    )
    assert result.segments == baseline.segments
    assert observed == [seed]
