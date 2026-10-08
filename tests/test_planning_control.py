"""Deterministic cooperative limits; no persisted factory data or live services."""

from __future__ import annotations

import copy
import importlib
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend import planning_control as control


class FakeClock:
    now = 0.0

    def __call__(self):
        return self.now


class FakeEvent:
    value = False

    def is_set(self):
        return self.value

    def set(self):
        self.value = True


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    # Import application modules only after relative data/config paths are isolated.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    assert control.current_planning_control() is None
    yield
    assert control.current_planning_control() is None


@pytest.fixture
def planning_modules():
    return SimpleNamespace(
        optimizer=importlib.import_module("backend.cpo.optimizer"),
        scheduler=importlib.import_module("backend.scheduler.scheduler"),
        robustness=importlib.import_module("backend.risk.robustness"),
        polish=importlib.import_module("backend.cpo.cpsat_polish"),
        jit=importlib.import_module("backend.scheduler.global_jit"),
    )


def empty_data():
    from backend.types import EngineData

    return EngineData([], [], [], {}, [], 0)


def candidate():
    from backend.scheduler.types import Lot, ScheduleResult

    lot = Lot("L1", "OP1", "T1", "M1", None, 10, 10, 0, 2, False)
    return ScheduleResult([], [lot], {"otd": 100.0}, 0.0, [], [])


def test_unscoped_checkpoints_have_no_deadline():
    control.planning_checkpoint()
    assert control.remaining_time() is None
    assert control.remaining_time(300) == 300


def test_deadline_inclusive_and_scope_restored():
    clock = FakeClock()
    with pytest.raises(control.PlanningTimeout):
        with control.planning_scope(timeout_s=10, clock=clock):
            clock.now = 9
            assert control.remaining_time() == 1
            assert control.remaining_time(0.25) == 0.25
            clock.now = 10
            control.planning_checkpoint()
    assert control.current_planning_control() is None


def test_zero_budget_never_enters_work():
    with pytest.raises(control.PlanningTimeout):
        with control.planning_scope(timeout_s=0, clock=FakeClock()):
            pytest.fail("Expired scope entered")


def test_nested_scope_cannot_extend_parent_and_restores_it():
    clock = FakeClock()
    with control.planning_scope(timeout_s=10, clock=clock) as parent:
        with pytest.raises(control.PlanningTimeout):
            with control.planning_scope(timeout_s=2):
                clock.now = 2
                control.planning_checkpoint()
        assert control.current_planning_control() is parent
        with control.planning_scope(timeout_s=100):
            assert control.remaining_time() == 8


def test_cancellation_wins_even_when_parent_also_expired():
    clock, event = FakeClock(), FakeEvent()
    with pytest.raises(control.PlanningCancelled):
        with control.planning_scope(timeout_s=1, clock=clock, cancel_event=event):
            with control.planning_scope(timeout_s=100):
                clock.now = 1
                event.set()
                control.planning_checkpoint()


def test_control_does_not_leak_to_other_worker():
    with control.planning_scope(timeout_s=10, clock=FakeClock()):
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(control.current_planning_control).result() is None


@pytest.mark.parametrize("observed", [False, True])
def test_telemetry_checks_normal_exit_without_masking_errors(observed):
    from contextlib import nullcontext

    from backend.telemetry import observe_phases, phase

    clock = FakeClock()
    events = []
    observer = observe_phases(lambda *args: events.append(args)) if observed else nullcontext()
    with observer:
        with pytest.raises(control.PlanningTimeout):
            with control.planning_scope(timeout_s=1, clock=clock):
                with phase("work"):
                    clock.now = 1
    if observed:
        assert [event[1] for event in events] == ["start", "end"]
    with pytest.raises(ValueError, match="original"):
        with control.planning_scope(timeout_s=1, clock=clock):
            with phase("work"):
                clock.now += 1
                raise ValueError("original")


@pytest.mark.parametrize("stop_kind", ["timeout", "cancel"])
def test_cpsat_watchdog_stops_before_solution_and_joins(monkeypatch, stop_kind):
    clock, event = FakeClock(), FakeEvent()
    threads = []
    stop_calls = []

    class CompletionEvent(FakeEvent):
        def wait(self, _interval):
            # Simulate a lost stop request before the native solver is ready.
            return self.is_set() or len(stop_calls) >= 2

    class Watcher:
        def __init__(self, *, target, **_kwargs):
            self.target = target
            self.joined = False
            threads.append(self)

        def start(self):
            pass

        def join(self):
            self.joined = True

    def solve(_model):
        assert solver.parameters.max_time_in_seconds == 3
        if stop_kind == "timeout":
            clock.now = 3
        else:
            event.set()
        threads[0].target()
        return "FEASIBLE"  # A solution at interruption is not validated output.

    solver = SimpleNamespace(
        parameters=SimpleNamespace(max_time_in_seconds=20),
        solve=solve,
        stop_search=lambda: stop_calls.append(True),
    )
    monkeypatch.setattr(control, "Event", CompletionEvent)
    monkeypatch.setattr(control, "Thread", Watcher)
    error = control.PlanningTimeout if stop_kind == "timeout" else control.PlanningCancelled
    with pytest.raises(error):
        with control.planning_scope(timeout_s=3, clock=clock, cancel_event=event):
            control.solve_cpsat(solver, object())
    assert len(stop_calls) == 2
    assert threads[0].joined


def test_cpsat_cleanup_on_solver_exception(monkeypatch):
    watcher = Mock()
    monkeypatch.setattr(control, "Thread", Mock(return_value=watcher))
    solver = SimpleNamespace(
        parameters=SimpleNamespace(max_time_in_seconds=0.25),
        solve=Mock(side_effect=ValueError("native failure")),
    )
    with pytest.raises(ValueError, match="native failure"):
        with control.planning_scope(timeout_s=2, clock=FakeClock()):
            control.solve_cpsat(solver, None)
    assert solver.parameters.max_time_in_seconds == 0.25
    watcher.join.assert_called_once()


def test_watchdog_captures_control_across_real_thread_boundary(monkeypatch):
    from threading import Event, Thread

    event, stopped = FakeEvent(), Event()
    watchers = []

    def make_thread(**kwargs):
        thread = Thread(**kwargs)
        watchers.append(thread)
        return thread

    def solve(_model):
        event.set()
        assert stopped.wait(5), "watchdog did not interrupt native search"
        return "UNKNOWN"

    monkeypatch.setattr(control, "Thread", make_thread)
    solver = SimpleNamespace(
        parameters=SimpleNamespace(max_time_in_seconds=10),
        solve=solve,
        stop_search=stopped.set,
    )
    with pytest.raises(control.PlanningCancelled):
        with control.planning_scope(cancel_event=event, clock=FakeClock()):
            control.solve_cpsat(solver, None)
    assert len(watchers) == 1
    assert not watchers[0].is_alive()


def test_cpsat_standalone_does_not_create_watchdog(monkeypatch):
    monkeypatch.setattr(control, "Thread", Mock(side_effect=AssertionError("watchdog")))
    solver = SimpleNamespace(solve=Mock(return_value="OPTIMAL"))
    assert control.solve_cpsat(solver, None) == "OPTIMAL"


def test_optimize_precancelled_does_no_construction(planning_modules, monkeypatch):
    event = FakeEvent()
    event.set()
    construct = Mock(side_effect=AssertionError("construction started"))
    monkeypatch.setattr(planning_modules.optimizer, "schedule_all", construct)
    with pytest.raises(control.PlanningCancelled):
        planning_modules.optimizer.optimize(empty_data(), cancel_event=event)
    construct.assert_not_called()


def test_total_budget_includes_construction_and_preserves_inputs(planning_modules, monkeypatch):
    from backend.config.types import FactoryConfig

    clock = FakeClock()
    data, config = empty_data(), FactoryConfig()
    before = copy.deepcopy((data, config))

    def construct(working_data, *, config, **_kwargs):
        assert control.remaining_time() == 60
        working_data.holidays.append(17)
        config.global_jit_time_limit_s = 999
        clock.now = 61
        return candidate()

    monkeypatch.setattr(planning_modules.optimizer, "schedule_all", construct)
    robustness = Mock(side_effect=AssertionError("planning never runs the robustness battery"))
    monkeypatch.setattr(planning_modules.robustness, "run_robustness_battery", robustness)
    with pytest.raises(control.PlanningTimeout):
        with control.planning_scope(clock=clock):
            planning_modules.optimizer.optimize(data, mode="normal", config=config)
    assert (data, config) == before
    robustness.assert_not_called()


@pytest.mark.parametrize("error", [control.PlanningTimeout, control.PlanningCancelled])
def test_advisory_polish_cancel_propagates_timeout_keeps_validated_candidate(planning_modules, monkeypatch, error):
    optimizer = planning_modules.optimizer
    monkeypatch.setattr(optimizer, "assert_plan_valid", lambda *_a, **_kw: None)
    monkeypatch.setitem(
        optimizer.MODE_CONFIG, "normal", {**optimizer.MODE_CONFIG["normal"], "candidate_search": False}
    )
    monkeypatch.setattr(optimizer, "schedule_all", lambda *_args, **_kwargs: candidate())
    monkeypatch.setattr(optimizer, "_build_local_machine_runs", lambda *_args: {})
    monkeypatch.setattr(planning_modules.polish, "cpsat_polish", Mock(side_effect=error("stop")))
    if error is control.PlanningCancelled:
        with pytest.raises(error, match="stop"):
            optimizer.optimize(empty_data())
    else:
        result = optimizer.optimize(empty_data())
        assert result.lots == candidate().lots
        assert result.solver_status == "timeout_with_candidate"


def test_standalone_schedule_remains_unbounded(planning_modules, monkeypatch):
    from backend.config.types import FactoryConfig

    original = planning_modules.scheduler.validate_input

    def validate(*args):
        assert control.current_planning_control() is None
        return original(*args)

    monkeypatch.setattr(planning_modules.scheduler, "validate_input", validate)
    assert planning_modules.scheduler.schedule_all(empty_data(), config=FactoryConfig()).lots == []


def test_global_model_build_cannot_overrun_parent_into_solve(planning_modules, monkeypatch):
    from backend.config.types import FactoryConfig

    clock = FakeClock()
    jit = planning_modules.jit

    def build(*_args, **_kwargs):
        clock.now = 10
        return object()

    monkeypatch.setattr(jit, "HAS_ORTOOLS", True)
    monkeypatch.setattr(jit, "_build_model", build)
    solve = Mock(side_effect=AssertionError("solver started after construction timeout"))
    monkeypatch.setattr(jit, "_solve", solve)
    with pytest.raises(control.PlanningTimeout):
        with control.planning_scope(timeout_s=10, clock=clock):
            jit.solve_global_jit([object()] * 60, empty_data(), FactoryConfig())
    solve.assert_not_called()


def test_normalization_stop_does_not_mutate_input(planning_modules, monkeypatch):
    from backend.config.types import FactoryConfig
    from backend.scheduler.types import Segment

    clock = FakeClock()
    scheduler = planning_modules.scheduler
    segments = [Segment("L1", "R1", "M1", "T1", 0, 420, 430, "A", 10, 10)]
    before = copy.deepcopy(segments)

    def repair(working, *_args, **_kwargs):
        working[0].qty = 0
        clock.now = 1
        return working

    monkeypatch.setattr(scheduler, "split_production_at_shift_boundaries", lambda s, *_a, **_k: s)
    monkeypatch.setattr(scheduler, "repair_same_reference_interruptions", repair)
    next_repair = Mock(side_effect=AssertionError("repair after timeout"))
    monkeypatch.setattr(scheduler, "_repair_interrupted_tool_campaigns", next_repair)
    with pytest.raises(control.PlanningTimeout):
        with control.planning_scope(timeout_s=1, clock=clock):
            scheduler.normalize_earliest_legal_plan(segments, [], empty_data(), FactoryConfig())
    assert segments == before
    next_repair.assert_not_called()


def test_robustness_can_stop_inside_one_replay(planning_modules):
    event = FakeEvent()

    class BlockedDays(set):
        def __contains__(self, _day):
            event.set()
            return True

    with pytest.raises(control.PlanningCancelled):
        with control.planning_scope(cancel_event=event):
            planning_modules.robustness._advance_work_with_intervals(0, 100, BlockedDays(), 60, [])


def test_incomplete_robustness_battery_raises_instead_of_partial_result(
    planning_modules, monkeypatch,
):
    from backend.config.types import FactoryConfig

    clock = FakeClock()
    result = candidate()
    before = copy.deepcopy(result)
    calls = []

    def replay(index, seed, *_args):
        calls.append(index)
        clock.now += 1
        return planning_modules.robustness.ScenarioOutcome(index, seed, 100, 0, 0, 0, [], {})

    monkeypatch.setattr(planning_modules.robustness, "replay_scenario", replay)
    with pytest.raises(control.PlanningTimeout):
        with control.planning_scope(timeout_s=2, clock=clock):
            planning_modules.robustness.run_robustness_battery(
                result.segments, result.lots, empty_data(), FactoryConfig(),
                n_samples=100, seed=42, profile="quick",
            )
    assert calls == [0, 1]
    assert result == before


def test_legacy_battery_callback_stops_inside_replay(planning_modules, monkeypatch):
    from backend.config.types import FactoryConfig

    event = FakeEvent()

    def replay(*_args):
        event.set()
        planning_modules.robustness._advance_work_with_intervals(0, 10, set(), 60, [])
        pytest.fail("Cancelled replay completed")

    monkeypatch.setattr(planning_modules.robustness, "replay_scenario", replay)
    result = planning_modules.robustness.run_robustness_battery(
        [], [], empty_data(), FactoryConfig(), n_samples=100, cancelled=event.is_set
    )
    assert result["completed_samples"] == 0
    assert result["requested_samples"] == 100


def test_legacy_battery_callback_does_not_swallow_parent_cancellation(planning_modules, monkeypatch):
    from backend.config.types import FactoryConfig

    event = FakeEvent()

    def replay(*_args):
        event.set()
        control.planning_checkpoint()

    monkeypatch.setattr(planning_modules.robustness, "replay_scenario", replay)
    with pytest.raises(control.PlanningCancelled):
        with control.planning_scope(cancel_event=event):
            planning_modules.robustness.run_robustness_battery(
                [], [], empty_data(), FactoryConfig(), n_samples=100, cancelled=lambda: False
            )
