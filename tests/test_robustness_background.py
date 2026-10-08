"""Automatic robustness after each commit: information only, never the plan."""

from __future__ import annotations

import asyncio
import copy
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.copilot.state import CopilotState, state
from backend.plans.serialize import planning_state_identity, schedule_fingerprint
from backend.risk import jobs as risk_jobs
from backend.risk.jobs import RobustnessJobManager, RobustnessJobStore
from backend.risk.robustness import ROBUSTNESS_HORIZON_WORKDAYS, ROBUSTNESS_MODEL_VERSION
from tests import test_load_jobs as load_fixtures
from tests import test_plan_transactions as transaction_fixtures
from tests.test_load_jobs import prepared, run, until
from tests.test_plan_transactions import _mutate, _run

# Reuse the isolated live-state fixtures of the commit and ISOP-load suites.
planning = transaction_fixtures.planning
loading = load_fixtures.loading


@pytest.fixture
def auto(monkeypatch):
    """A private job manager with the automatic trigger switched on."""

    monkeypatch.setenv(risk_jobs.AUTO_ENV, "1")
    store = RobustnessJobStore(":memory:")
    manager = RobustnessJobManager(store)
    monkeypatch.setattr(risk_jobs, "manager", manager)
    monkeypatch.setattr("backend.api.robustness.manager", manager)
    try:
        yield manager
    finally:
        manager.shutdown(wait_s=5)
        store._conn.close()


def _auto_jobs(manager) -> list[dict]:
    rows = manager.store._conn.execute(
        "SELECT id FROM robustness_jobs WHERE trigger='auto' ORDER BY created_at, rowid"
    ).fetchall()
    return [manager.store.get(row["id"]) for row in rows]


def _wait(manager, job_id, statuses=("completed", "failed", "cancelled"), timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.store.get(job_id)
        if job["status"] in statuses:
            return job
        time.sleep(0.01)
    pytest.fail(f"Job did not finish: {manager.store.get(job_id)}")


def _publish(marker: str) -> dict:
    """A new revision that keeps the (already historical) schedule unchanged."""

    state.dataset_info["marker"] = marker
    state.plan_revision += 1
    return {"status": "ok", "marker": marker}


def _change_inputs(marker: str) -> dict:
    """A new revision whose replayed inputs really changed."""

    state.engine_data.ops[0].stk += 1
    return _publish(marker)


def _plan_view() -> dict:
    return {
        "segments": copy.deepcopy(state.segments),
        "lots": copy.deepcopy(state.lots),
        "score": copy.deepcopy(state.score),
        "gate_report": copy.deepcopy(state.gate_report),
        "plan_revision": state.plan_revision,
        "schedule": schedule_fingerprint(state.segments, state.lots),
        "identity": planning_state_identity(state),
    }


def test_commit_enqueues_exactly_one_auto_job_for_the_new_revision(planning, auto):
    _run(lambda: _mutate("committed"))

    jobs = _auto_jobs(auto)
    assert len(jobs) == 1
    job = jobs[0]
    assert job["trigger"] == "auto"
    assert job["plan_revision"] == state.plan_revision == 8
    assert job["model_version"] == ROBUSTNESS_MODEL_VERSION == 5
    assert job["horizon_workdays"] == ROBUSTNESS_HORIZON_WORKDAYS == 10
    finished = _wait(auto, job["id"])
    assert finished["status"] == "completed", finished
    assert finished["result"]["model_version"] == 5
    assert finished["result"]["horizon_workdays"] == 10


def test_no_op_replay_and_failed_result_do_not_enqueue(planning, auto):
    _run(lambda: {"status": "ok"}, "no-op", "no-op")
    _run(lambda: {"error": "falhou"}, "failed", "failed")
    assert _auto_jobs(auto) == []

    first = _run(lambda: _mutate("committed"), "stable", "stable")
    assert len(_auto_jobs(auto)) == 1
    assert _run(lambda: pytest.fail("replay must not recalculate"), "stable", "stable") == first
    assert len(_auto_jobs(auto)) == 1


def test_switch_off_starts_nothing(planning, auto, monkeypatch):
    monkeypatch.setenv(risk_jobs.AUTO_ENV, "0")
    _run(lambda: _mutate("committed"))
    assert _auto_jobs(auto) == []


def test_sandbox_state_never_replaces_the_live_analysis(planning, auto):
    other = CopilotState(engine_data=state.engine_data, config=state.config)
    assert risk_jobs.enqueue_after_commit(other) is None
    assert _auto_jobs(auto) == []


def test_job_never_changes_the_plan_score_gate_or_identity(planning, auto):
    _run(lambda: _mutate("committed"))
    before = _plan_view()
    job = _wait(auto, _auto_jobs(auto)[0]["id"])

    assert job["status"] == "completed", job
    assert _plan_view() == before
    assert not any(key.startswith("robustness_") for key in state.score)
    assert not any(
        key.startswith("robustness_") for key in (state.gate_report.get("metrics") or {})
    )


def test_job_reads_a_detached_copy_of_the_published_plan(planning, auto, monkeypatch):
    seen, release = [], threading.Event()

    def battery(segments, lots, *_args, **_kwargs):
        assert release.wait(5)
        seen.append((segments[0].start_min, lots[0].planning_source))
        return {"model_version": 5, "horizon_workdays": 10}

    monkeypatch.setattr("backend.risk.jobs.run_robustness_battery", battery)
    _run(lambda: _mutate("committed"))
    published = (state.segments[0].start_min, state.lots[0].planning_source)
    state.segments[0].start_min += 100
    state.lots[0].planning_source = "edited after the snapshot"
    release.set()
    _wait(auto, _auto_jobs(auto)[0]["id"])
    assert seen == [published]


def test_newer_revision_supersedes_the_running_auto_job(planning, auto, monkeypatch):
    calls = []

    def battery(*_args, cancelled=None, **_kwargs):
        calls.append(len(calls))
        deadline = time.monotonic() + 5
        while len(calls) == 1 and not cancelled() and time.monotonic() < deadline:
            time.sleep(0.01)
        return {"model_version": 5, "horizon_workdays": 10}

    monkeypatch.setattr("backend.risk.jobs.run_robustness_battery", battery)
    _run(lambda: _mutate("first"), "first", "first")
    first = _auto_jobs(auto)[0]
    deadline = time.monotonic() + 5
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    _run(lambda: _change_inputs("second"), "second", "second")

    old, new = _auto_jobs(auto)
    assert old["id"] == first["id"]
    assert _wait(auto, old["id"])["status"] == "cancelled"
    assert _wait(auto, new["id"])["status"] == "completed"
    assert (old["plan_revision"], new["plan_revision"]) == (8, 9)
    assert auto.store.latest(trigger="auto")["id"] == new["id"]


@pytest.mark.parametrize("stage", ["capture_auto_snapshot", "submit_auto_snapshot"])
def test_robustness_failure_never_fails_the_commit(planning, auto, monkeypatch, stage):
    def broken(*_args, **_kwargs):
        raise RuntimeError("robustness store unavailable")

    monkeypatch.setattr(risk_jobs, stage, broken)
    response = _run(lambda: _mutate("committed"))
    assert response["plan_revision"] == state.plan_revision == 8
    assert planning.store.active()["payload"]["plan_revision"] == 8
    assert _auto_jobs(auto) == []


def test_commit_lock_only_covers_the_snapshot(planning, auto, monkeypatch):
    from backend.api.locks import commit_lock

    held = {}
    real_capture, real_submit = risk_jobs.capture_auto_snapshot, risk_jobs.submit_auto_snapshot

    def lock_is_held() -> bool:
        # RLock: another thread can take it only when nobody holds it.
        free = []
        probe = threading.Thread(
            target=lambda: free.append(commit_lock.acquire(timeout=0.5) and (
                commit_lock.release() or True
            ))
        )
        probe.start()
        probe.join()
        return not free[0]

    def capture(live):
        held["capture"] = lock_is_held()
        return real_capture(live)

    def submit(snapshot, **kwargs):
        held["submit"] = lock_is_held()
        return real_submit(snapshot, **kwargs)

    monkeypatch.setattr(risk_jobs, "capture_auto_snapshot", capture)
    monkeypatch.setattr(risk_jobs, "submit_auto_snapshot", submit)
    _run(lambda: _mutate("committed"))
    assert held == {"capture": True, "submit": False}
    assert len(_auto_jobs(auto)) == 1


def test_unchanged_schedule_reuses_the_analysis_for_the_newer_revision(planning, auto):
    _run(lambda: _mutate("committed"))
    first = _wait(auto, _auto_jobs(auto)[0]["id"])

    # E.g. a rule added or removed: new revision, identical replayed inputs.
    _run(lambda: _publish("rule edit"), "rule", "rule")

    jobs = _auto_jobs(auto)
    assert [job["id"] for job in jobs] == [first["id"]]
    reused = jobs[0]
    assert reused["status"] == "completed"
    assert reused["plan_revision"] == state.plan_revision == 9
    assert reused["result"] == first["result"]
    from backend.api.robustness import current_dataset_fingerprint

    assert reused["dataset_fingerprint"] == current_dataset_fingerprint()


def test_cancelled_analysis_is_not_moved_to_the_newer_revision(planning, auto):
    _run(lambda: _mutate("committed"))
    first = _wait(auto, _auto_jobs(auto)[0]["id"])
    with auto.store._lock, auto.store._conn:  # noqa: SLF001 - cancel lands before rebind
        auto.store._conn.execute(  # noqa: SLF001
            "UPDATE robustness_jobs SET status='cancelled' WHERE id=?", (first["id"],)
        )

    _run(lambda: _publish("rule edit"), "rule", "rule")

    jobs = _auto_jobs(auto)
    assert len(jobs) == 2
    fresh = next(job for job in jobs if job["id"] != first["id"])
    assert fresh["plan_revision"] == state.plan_revision
    assert auto.store.get(first["id"])["plan_revision"] == first["plan_revision"]


def test_older_snapshot_never_replaces_a_newer_revision(planning, auto):
    older = risk_jobs.capture_auto_snapshot(state)
    _run(lambda: _mutate("committed"))
    newest = _auto_jobs(auto)[0]
    assert risk_jobs.submit_auto_snapshot(older) is None
    assert [job["id"] for job in _auto_jobs(auto)] == [newest["id"]]


def test_new_planning_day_starts_a_new_analysis_without_staling_the_plan(
    planning, auto, monkeypatch,
):
    from backend.api.robustness import current_dataset_fingerprint

    first = risk_jobs.enqueue_after_commit(state)
    _wait(auto, first["id"])
    assert risk_jobs.enqueue_after_commit(state)["id"] == first["id"]

    anchor = first["anchor_day"]
    monkeypatch.setattr(
        "backend.risk.plan_identity.planning_anchor_day", lambda *_args: anchor + 1,
    )
    moved = risk_jobs.enqueue_after_commit(state)
    assert moved["id"] != first["id"]
    assert moved["anchor_day"] == anchor + 1
    assert moved["plan_revision"] == first["plan_revision"]
    # The anchor is not part of the plan identity: same plan, not stale.
    assert moved["dataset_fingerprint"] == first["dataset_fingerprint"]
    assert moved["dataset_fingerprint"] == current_dataset_fingerprint()
    assert _wait(auto, moved["id"])["result"]["horizon_start_day"] == min(
        anchor + 1, state.engine_data.n_days - 1,
    )


def test_latest_auto_requeues_when_the_planning_day_moved(planning, auto, monkeypatch):
    from backend.api.robustness import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    first = risk_jobs.enqueue_after_commit(state)
    _wait(auto, first["id"])

    url = "/api/data/robustness-runs/latest"
    same_day = client.get(url, params={"trigger": "auto"}).json()
    assert (same_day["job"]["id"], same_day["refreshing"]) == (first["id"], False)

    anchor = first["anchor_day"]
    monkeypatch.setattr(
        "backend.api.robustness.planning_anchor_day", lambda *_args: anchor + 1,
    )
    monkeypatch.setattr(
        "backend.risk.plan_identity.planning_anchor_day", lambda *_args: anchor + 1,
    )
    # The request only queues the refresh; it answers with the current job.
    real_refresh, queued = risk_jobs.request_refresh, []
    monkeypatch.setattr(risk_jobs, "request_refresh", lambda live: queued.append(live) or True)
    moved_day = client.get(url, params={"trigger": "auto"}).json()
    assert moved_day["job"]["id"] == first["id"]
    assert moved_day["refreshing"] is True
    assert queued == [state]
    # Unfiltered and manual reads never trigger it.
    assert client.get(url).json()["refreshing"] is False
    assert client.get(url, params={"trigger": "manual"}).json()["refreshing"] is False
    assert queued == [state]

    monkeypatch.setattr(risk_jobs, "request_refresh", real_refresh)
    assert client.get(url, params={"trigger": "auto"}).json()["refreshing"] is True
    deadline = time.monotonic() + 10
    while len(_auto_jobs(auto)) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    old, new = _auto_jobs(auto)
    assert old["id"] == first["id"]
    assert new["anchor_day"] == anchor + 1
    assert _wait(auto, new["id"])["status"] == "completed"
    deadline = time.monotonic() + 5
    while risk_jobs.refresh_pending() and time.monotonic() < deadline:
        time.sleep(0.01)
    after = client.get(url, params={"trigger": "auto"}).json()
    assert (after["job"]["id"], after["refreshing"]) == (new["id"], False)


def test_startup_refreshes_only_a_missing_or_unusable_job(planning, auto, monkeypatch):
    first = risk_jobs.enqueue_after_commit(state)
    assert risk_jobs.enqueue_after_commit(state)["id"] == first["id"]
    _wait(auto, first["id"])
    assert risk_jobs.enqueue_after_commit(state)["id"] == first["id"]

    auto.store._conn.execute("UPDATE robustness_jobs SET status='failed'")
    auto.store._conn.commit()
    retried = risk_jobs.enqueue_after_commit(state)
    assert retried["id"] != first["id"]
    assert len(_auto_jobs(auto)) == 2


def test_startup_hook_enqueues_for_the_restored_plan(planning, auto, monkeypatch):
    from backend.api import copilot

    calls = []
    monkeypatch.setattr(risk_jobs, "enqueue_after_commit", lambda live: calls.append(live))

    async def start_and_stop():
        async with copilot.lifespan(SimpleNamespace(state=SimpleNamespace())):
            pass

    asyncio.run(start_and_stop())
    assert calls == [state]


def test_isop_load_commit_enqueues_for_the_loaded_state(loading, monkeypatch):
    calls, submitted = [], []
    marker = object()

    def capture(live):
        calls.append((live, live.plan_revision))
        return marker

    def submit(snapshot):
        submitted.append((snapshot, threading.current_thread() is threading.main_thread()))

    monkeypatch.setattr(risk_jobs, "capture_auto_snapshot", capture)
    monkeypatch.setattr(risk_jobs, "submit_auto_snapshot", submit)
    manager = loading.manager

    async def scenario():
        job = await prepared(manager)
        manager.confirm(job["id"], 7, "all_free")
        applied = await until(manager, job["id"], {"applied", "failed"})
        assert applied["status"] == "applied", applied

    run(manager, scenario)
    assert calls == [(loading.live, 8)]
    # Fingerprints and the job row are built off the event-loop thread.
    assert submitted == [(marker, False)]


def test_api_exposes_trigger_revision_horizon_and_staleness(planning, auto, monkeypatch):
    from backend.api.robustness import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    _run(lambda: _mutate("committed"))
    job_id = _auto_jobs(auto)[0]["id"]
    _wait(auto, job_id)

    latest = client.get("/api/data/robustness-runs/latest", params={"trigger": "auto"})
    assert latest.status_code == 200, latest.text
    job = latest.json()["job"]
    assert job["id"] == job_id
    assert job["trigger"] == "auto"
    assert job["plan_revision"] == 8
    assert job["horizon_workdays"] == 10
    assert job["model_version"] == 5
    assert job["stale"] is False
    assert client.get("/api/data/robustness-runs/latest").json()["job"]["id"] == job_id
    assert client.get(
        "/api/data/robustness-runs/latest", params={"trigger": "manual"}
    ).json()["job"] is None
    assert client.get(
        "/api/data/robustness-runs/latest", params={"trigger": "other"}
    ).status_code == 400

    manual = client.post(
        "/api/data/robustness-runs", json={"profile": "quick", "samples": 10}
    )
    assert manual.status_code == 200, manual.text
    started = manual.json()["job"]
    assert (started["trigger"], started["plan_revision"]) == ("manual", 8)
    _wait(auto, started["id"])

    monkeypatch.setenv(risk_jobs.AUTO_ENV, "0")  # keep the old job as the latest
    _run(lambda: _publish("newer"), "newer", "newer")
    stale = client.get(f"/api/data/robustness-runs/{job_id}").json()["job"]
    assert stale["stale"] is True
    assert stale["plan_revision"] == 8
