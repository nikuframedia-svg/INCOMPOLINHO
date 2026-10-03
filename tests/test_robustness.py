"""Deterministic, non-mutating robustness battery regressions."""

from __future__ import annotations

import copy
import os
import threading
import time

import pytest

from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.risk.jobs import RobustnessJobManager, RobustnessJobStore
from backend.risk.robustness import (
    PROFILE_SAMPLES,
    ScenarioOutcome,
    _absolute_intervals,
    _advance_work_with_intervals,
    _reserve_operator_work,
    replay_scenario,
    run_robustness_battery,
)
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData, EOp, MachineInfo


def _fixture():
    config = FactoryConfig()
    data = EngineData(
        ops=[
            EOp(
                id="OP1",
                sku="SKU1",
                client="C1",
                designation="Peça",
                m="M1",
                t="T1",
                pH=100,
                sH=0.5,
                operators=1,
                eco_lot=0,
                alt=None,
                stk=0,
                backlog=0,
                d=[0, 0, 100, 0, 0],
                oee=0.66,
                wip=0,
            )
        ],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-03-{17 + day:02d}" for day in range(5)],
        n_days=5,
        holidays=[],
    )
    lot = Lot(
        id="LOT1",
        op_id="OP1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=30,
        edd=2,
        is_twin=False,
        delivery_day=2,
    )
    segment = Segment(
        lot_id="LOT1",
        run_id="RUN1",
        machine_id="M1",
        tool_id="T1",
        day_idx=2,
        start_min=1320,
        end_min=1410,
        shift="B",
        qty=100,
        prod_min=60,
        setup_min=30,
        edd=2,
        sku="SKU1",
    )
    return [segment], [lot], data, config


def test_profiles_are_exactly_100_500_2000():
    assert PROFILE_SAMPLES == {"quick": 100, "standard": 500, "intensive": 2000}


def test_common_seed_is_reproducible_and_plan_is_not_mutated():
    segments, lots, data, config = _fixture()
    before = copy.deepcopy((segments, lots, data, config))
    first = run_robustness_battery(
        segments, lots, data, config, n_samples=25, seed=73
    )
    second = run_robustness_battery(
        segments, lots, data, config, n_samples=25, seed=73
    )
    assert first == second
    assert (segments, lots, data, config) == before
    assert first["requested_samples"] == first["completed_samples"] == 25
    assert len(first["worst_scenarios"]) <= 20


def test_existing_late_lot_does_not_force_robustness_to_zero(monkeypatch):
    segments, lots, data, config = _fixture()
    lots[0].edd = 1
    lots[0].delivery_day = 1

    def replay(index, seed, *_args):
        return ScenarioOutcome(
            index=index,
            seed=seed,
            otd=0,
            tardy_count=1,
            total_tardiness=1,
            max_tardiness=1,
            affected_lots=["LOT1"],
            manifest={},
            tardy_lot_ids=frozenset({"LOT1"}),
        )

    monkeypatch.setattr("backend.risk.robustness.replay_scenario", replay)
    result = run_robustness_battery(
        segments, lots, data, config, n_samples=10, seed=73
    )

    assert result["success_definition"] == "no_additional_tardy_lots"
    assert result["baseline_tardy_count"] == 1
    assert result["success_probability_pct"] == 100.0
    assert result["additional_tardy_p95"] == 0.0


def test_scenario_contains_all_supported_disturbance_families():
    segments, lots, data, config = _fixture()
    outcome = replay_scenario(0, 42, segments, lots, data, config)
    assert set(outcome.manifest) == {
        "machine_efficiency",
        "processing_factor",
        "setup_factor",
        "operator_factor",
        "machine_down",
        "tool_down",
        "material_delays",
        "demand_factors",
        "stock_factors",
        "subcontract_delays",
    }


def _stable_manifest(segments):
    return {
        "machine_efficiency": {
            segment.machine_id: 1.0 for segment in segments
        },
        "processing_factor": {
            segment.machine_id: 1.0 for segment in segments
        },
        "setup_factor": 1.0,
        "operator_factor": 1.0,
        "machine_down": {},
        "tool_down": {},
        "material_delays": {},
        "demand_factors": {},
        "stock_factors": {},
        "subcontract_delays": {},
    }


def test_replay_respects_exact_machine_calendar(monkeypatch):
    segments, lots, data, config = _fixture()
    data.machine_blocked_intervals = {
        "M1": [
            {
                "start_day": 2,
                "start_min": 420,
                "end_day": 2,
                "end_min": 1440,
            }
        ]
    }
    monkeypatch.setattr(
        "backend.risk.robustness._scenario_manifest",
        lambda *_args, **_kwargs: _stable_manifest(segments),
    )

    outcome = replay_scenario(0, 42, segments, lots, data, config)

    assert outcome.tardy_count == 1
    assert outcome.total_tardiness == 1


def test_robustness_coordinates_compress_closed_shift_gap():
    config = FactoryConfig(
        shifts=[
            ShiftConfig("A", 420, 720),
            ShiftConfig("B", 780, 1020),
        ]
    )
    intervals = _absolute_intervals(
        [
            {
                "start_day": 0,
                "start_min": 780,
                "end_day": 0,
                "end_min": 840,
            }
        ],
        config,
    )

    assert intervals == [(300.0, 360.0)]
    assert _advance_work_with_intervals(300, 60, set(), 540, intervals) == 420


def test_replay_respects_persistent_full_resource_day(monkeypatch):
    segments, lots, data, config = _fixture()
    data.machine_blocked_days = {"M1": {2}}
    monkeypatch.setattr(
        "backend.risk.robustness._scenario_manifest",
        lambda *_args, **_kwargs: _stable_manifest(segments),
    )

    outcome = replay_scenario(0, 42, segments, lots, data, config)

    assert outcome.tardy_count == 1
    assert outcome.total_tardiness == 1


def test_replay_serializes_concurrent_operator_demand(monkeypatch):
    config = FactoryConfig(
        shifts=[ShiftConfig("A", 420, 1440)],
        machines={
            "M1": MachineConfig("M1", "Grandes"),
            "M2": MachineConfig("M2", "Grandes"),
        },
        operators={("Grandes", "A"): 1},
    )
    data = EngineData(
        ops=[
            EOp(
                id=f"OP{index}",
                sku=f"SKU{index}",
                client="C",
                designation="Peça",
                m=f"M{index}",
                t=f"T{index}",
                pH=100,
                sH=0,
                operators=1,
                eco_lot=0,
                alt=None,
                stk=0,
                backlog=0,
                d=[100, 0],
                oee=1,
                wip=0,
            )
            for index in (1, 2)
        ],
        machines=[
            MachineInfo(f"M{index}", "Grandes", 1020) for index in (1, 2)
        ],
        twin_groups=[],
        client_demands={},
        workdays=["2026-03-17", "2026-03-18"],
        n_days=2,
        holidays=[],
    )
    lots = [
        Lot(
            id=f"LOT{index}",
            op_id=f"OP{index}",
            sku=f"SKU{index}",
            tool_id=f"T{index}",
            machine_id=f"M{index}",
            alt_machine_id=None,
            qty=100,
            prod_min=600,
            setup_min=0,
            edd=0,
            is_twin=False,
            delivery_day=0,
        )
        for index in (1, 2)
    ]
    segments = [
        Segment(
            lot_id=f"LOT{index}",
            run_id=f"RUN{index}",
            machine_id=f"M{index}",
            tool_id=f"T{index}",
            day_idx=0,
            start_min=420,
            end_min=1020,
            shift="A",
            qty=100,
            prod_min=600,
            sku=f"SKU{index}",
        )
        for index in (1, 2)
    ]
    monkeypatch.setattr(
        "backend.risk.robustness._scenario_manifest",
        lambda *_args, **_kwargs: _stable_manifest(segments),
    )

    outcome = replay_scenario(0, 42, segments, lots, data, config)

    assert outcome.tardy_count == 1
    assert outcome.total_tardiness == 1


def test_completion_exactly_at_factory_close_stays_on_same_day(monkeypatch):
    segments, lots, data, config = _fixture()
    lots[0].edd = 0
    lots[0].delivery_day = 0
    segments[0].day_idx = 0
    segments[0].start_min = 1380
    segments[0].end_min = 1440
    segments[0].setup_min = 0
    segments[0].prod_min = 60
    monkeypatch.setattr(
        "backend.risk.robustness._scenario_manifest",
        lambda *_args, **_kwargs: _stable_manifest(segments),
    )

    outcome = replay_scenario(0, 42, segments, lots, data, config)

    assert outcome.tardy_count == 0


def test_impossible_operator_demand_stops_at_finite_horizon():
    config = FactoryConfig(
        shifts=[ShiftConfig("A", 420, 1440)],
        operators={("Grandes", "A"): 1},
    )
    assert _reserve_operator_work(
        0,
        60,
        demand=2,
        group="Grandes",
        blocked_days=set(),
        blocked_intervals=[],
        absences=[],
        reservations=[],
        config=config,
        horizon=2040,
    ) == 2040


def test_replay_uses_setup_crew_capacity_per_group(monkeypatch):
    segments, lots, data, config = _fixture()
    data.workdays = ["2026-03-17", "2026-03-18"]
    data.n_days = 2
    data.ops.append(
        EOp(
            id="OP2",
            sku="SKU2",
            client="C2",
            designation="Peça",
            m="M2",
            t="T2",
            pH=100,
            sH=0.5,
            operators=1,
            eco_lot=0,
            alt=None,
            stk=0,
            backlog=0,
            d=[100, 0],
            oee=1.0,
            wip=0,
        )
    )
    data.machines.append(
        MachineInfo(id="M2", group="Grandes", day_capacity=1020)
    )
    lots = [
        Lot(
            id=f"LOT{index}",
            op_id=f"OP{index}",
            sku=f"SKU{index}",
            tool_id=f"T{index}",
            machine_id=f"M{index}",
            alt_machine_id=None,
            qty=100,
            prod_min=500,
            setup_min=500,
            edd=0,
            is_twin=False,
            delivery_day=0,
        )
        for index in (1, 2)
    ]
    segments = [
        Segment(
            lot_id=f"LOT{index}",
            run_id=f"RUN{index}",
            machine_id=f"M{index}",
            tool_id=f"T{index}",
            day_idx=0,
            start_min=420,
            end_min=1420,
            shift="A",
            qty=100,
            prod_min=500,
            setup_min=500,
            edd=0,
            sku=f"SKU{index}",
        )
        for index in (1, 2)
    ]
    config.machines = {
        machine.id: MachineConfig(machine.id, "Grandes")
        for machine in data.machines
    }
    monkeypatch.setattr(
        "backend.risk.robustness._scenario_manifest",
        lambda *_args, **_kwargs: _stable_manifest(segments),
    )

    config.setup_crews_by_group["Grandes"] = 1
    one_crew = replay_scenario(0, 42, segments, lots, data, config)
    config.setup_crews_by_group["Grandes"] = 2
    two_crews = replay_scenario(0, 42, segments, lots, data, config)

    assert one_crew.tardy_count == 1
    assert two_crews.tardy_count == 0


def test_background_job_persists_progress_and_result(tmp_path):
    segments, lots, data, config = _fixture()
    store = RobustnessJobStore(tmp_path / "robustness-test.db")
    manager = RobustnessJobManager(store)
    job = manager.start(
        profile="quick",
        samples=20,
        seed=42,
        dataset_fingerprint="fixture-v1",
        segments=segments,
        lots=lots,
        engine_data=data,
        config=config,
    )
    deadline = time.monotonic() + 5
    current = job
    while current["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
        time.sleep(0.01)
        current = store.get(job["id"])
    manager._executor.shutdown(wait=True)
    assert current["status"] == "completed", current
    assert current["progress"] == 100
    assert current["result"]["completed_samples"] == 20
    store._conn.close()


def _job(store):
    return store.create(profile="quick", samples=1, seed=42, dataset_fingerprint="fixture")


def test_reopening_store_does_not_reset_another_live_worker(tmp_path):
    path = tmp_path / "robustness.db"
    original = RobustnessJobStore(path)
    job = _job(original)
    original.update(job["id"], status="running", progress=25)
    before = original.get(job["id"])
    reopened = RobustnessJobStore(path)
    try:
        assert reopened.get(job["id"]) == before
        assert original.get(job["id"]) == before
        reopened.update(job["id"], status="completed")
        assert original.get(job["id"]) == before
    finally:
        reopened._conn.close()
        original._conn.close()


@pytest.mark.parametrize("reused_pid", [False, True])
def test_interrupted_ownership_is_classified_without_rewriting_rows(tmp_path, reused_pid):
    path = tmp_path / "robustness.db"
    original = RobustnessJobStore(path, worker_pid=os.getpid() if reused_pid else 2_147_483_647)
    job = _job(original)
    original.update(job["id"], status="running")
    if reused_pid:
        original._conn.execute("UPDATE robustness_jobs SET worker_started='previous-boot'")
        original._conn.commit()
    reopened = RobustnessJobStore(path)
    try:
        current = reopened.get(job["id"])
        assert current["status"] == "interrupted"
        assert current["stored_status"] == "running"
        assert reopened._conn.execute("SELECT status FROM robustness_jobs").fetchone()[0] == "running"
    finally:
        reopened._conn.close()
        original._conn.close()


def test_cancel_cannot_overwrite_terminal_worker_result(monkeypatch):
    store = RobustnessJobStore(":memory:")
    manager = RobustnessJobManager(store)
    job = _job(store)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    event = threading.Event()
    manager._cancel[job["id"]] = event

    def battery(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"completed_samples": 0}

    def worker():
        try:
            manager._run(job["id"], "quick", 1, 42, [], [], None, None, event)
        finally:
            finished.set()

    original_set = event.set

    def signal_and_wait():
        original_set()
        release.set()
        assert finished.wait(5)

    monkeypatch.setattr("backend.risk.jobs.run_robustness_battery", battery)
    monkeypatch.setattr(event, "set", signal_and_wait)
    thread = threading.Thread(target=worker)
    try:
        thread.start()
        assert entered.wait(5)
        assert manager.cancel(job["id"])["status"] == "cancelled"
        thread.join(5)
        assert not thread.is_alive()
        assert manager.cancel(job["id"])["status"] == "cancelled"
        for status in ("running", "failed", "completed", "cancelling"):
            assert store.update(job["id"], status=status)["status"] == "cancelled"
        assert not manager._cancel
    finally:
        release.set()
        thread.join(5)
        manager._executor.shutdown(wait=True)
        store._conn.close()


def test_queued_cancellation_never_runs_battery(monkeypatch):
    store = RobustnessJobStore(":memory:")
    manager = RobustnessJobManager(store)
    job = _job(store)
    event = threading.Event()
    manager._cancel[job["id"]] = event
    monkeypatch.setattr("backend.risk.jobs.run_robustness_battery", lambda *a, **k: pytest.fail("cancelled worker ran"))
    try:
        manager.cancel(job["id"])
        manager._run(job["id"], "quick", 1, 42, [], [], None, None, event)
        assert store.get(job["id"])["status"] == "cancelled"
        assert not manager._cancel
    finally:
        manager._executor.shutdown(wait=True)
        store._conn.close()


@pytest.mark.parametrize("late_status", ["completed", "failed"])
def test_cancellation_wins_a_late_worker_transition(late_status):
    store = RobustnessJobStore(":memory:")
    try:
        job = _job(store)
        store.update(job["id"], status="running")
        store.request_cancel(job["id"])
        assert store.update(job["id"], status=late_status)["status"] == "cancelled"
    finally:
        store._conn.close()


def test_submission_failure_clears_worker_and_marks_job_failed(monkeypatch):
    store = RobustnessJobStore(":memory:")
    manager = RobustnessJobManager(store)

    def fail(*args):
        raise RuntimeError("executor closed")

    monkeypatch.setattr(manager._executor, "submit", fail)
    try:
        with pytest.raises(RuntimeError, match="executor closed"):
            manager.start(profile="quick", samples=1, seed=42, dataset_fingerprint="test",
                          segments=[], lots=[], engine_data=None, config=None)
        assert store.latest()["status"] == "failed"
        assert not manager._cancel
    finally:
        manager._executor.shutdown(wait=True)
        store._conn.close()
