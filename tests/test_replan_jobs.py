"""Persistence, recovery, and API tests for re-plan jobs."""

from __future__ import annotations

import os
import sqlite3
import asyncio
import copy

import pytest
from fastapi import HTTPException

from fastapi.testclient import TestClient

from backend.api import replan as replan_api
from backend.api.copilot import app
from backend.config.types import FactoryConfig, MachineConfig
from backend.copilot.state import CopilotState, state
from backend.plans.serialize import serialize_snapshot
from backend.plans.store import PlansStore
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.replan.jobs import (
    ReplanJobManager,
    ReplanJobStore,
    canonical_replan_fingerprint,
    replan_base_fingerprints,
)
from backend.types import EOp, EngineData, MachineInfo


class _RecordingExecutor:
    def __init__(self) -> None:
        self.submissions: list[tuple] = []

    def submit(self, function, *args):
        self.submissions.append((function, args))
        return None

    def shutdown(self, wait: bool = True) -> None:
        return None


def _manager(path, *, retention_limit: int = 100) -> ReplanJobManager:
    store = ReplanJobStore(path, retention_limit=retention_limit)
    manager = ReplanJobManager(store)
    manager.executor.shutdown(wait=True)
    manager.executor = _RecordingExecutor()
    return manager


def _close(manager: ReplanJobManager) -> None:
    manager.executor.shutdown(wait=True)
    manager.store.conn.close()


def test_canonical_replan_fingerprint_ignores_object_key_order():
    first = canonical_replan_fingerprint(
        dataset_id="dataset-a",
        base_revision=7,
        request={
            "reason": "Alterar setup",
            "config_updates": {
                "tool_updates": {"BFP079": {"setup_hours": 1.0, "alt": "PRM039"}},
                "machine_oee": {"PRM039": 0.66},
            },
        },
    )
    reordered = canonical_replan_fingerprint(
        dataset_id="dataset-a",
        base_revision=7,
        request={
            "config_updates": {
                "machine_oee": {"PRM039": 0.66},
                "tool_updates": {"BFP079": {"alt": "PRM039", "setup_hours": 1.0}},
            },
            "reason": "Alterar setup",
        },
    )

    assert first == reordered
    assert first != canonical_replan_fingerprint(
        dataset_id="dataset-a",
        base_revision=8,
        request={"reason": "Alterar setup", "config_updates": {}},
    )


def test_manager_deduplicates_queued_running_and_ready_jobs(tmp_path):
    manager = _manager(tmp_path / "replan.db")
    fingerprint = canonical_replan_fingerprint(
        dataset_id="dataset-a",
        base_revision=3,
        request={"reason": "Mesmo pedido", "config_updates": {"x": 1}},
    )
    start_kwargs = {
        "engine_data": {"input": "data"},
        "config": {"setup": 1},
        "dataset_id": "dataset-a",
        "base_revision": 3,
        "reason": "Mesmo pedido",
        "request_fingerprint": fingerprint,
    }
    try:
        queued = manager.start(**start_kwargs)
        duplicate_queued = manager.start(**start_kwargs)
        manager.store.update(
            queued["id"],
            status="running",
            phase="optimizing",
            message="A calcular",
        )
        duplicate_running = manager.start(**start_kwargs)
        manager.store.update(
            queued["id"],
            status="ready",
            phase="ready",
            message="Pronto",
        )
        duplicate_ready = manager.start(**start_kwargs)

        assert queued["deduplicated"] is False
        assert {
            duplicate_queued["id"],
            duplicate_running["id"],
            duplicate_ready["id"],
        } == {queued["id"]}
        assert duplicate_ready["status"] == "ready"
        assert duplicate_ready["deduplicated"] is True
        assert len(manager.executor.submissions) == 1

        manager.store.update(
            queued["id"],
            status="completed",
            phase="completed",
            message="Aplicado",
        )
        replacement = manager.start(**start_kwargs)
        assert replacement["id"] != queued["id"]
        assert len(manager.executor.submissions) == 2
    finally:
        _close(manager)


def test_reopening_store_classifies_interrupted_job_without_mutating_it(tmp_path):
    path = tmp_path / "replan.db"
    dead_pid = 2_147_483_647
    original = ReplanJobStore(
        path,
        worker_id="old-process",
        worker_pid=dead_pid,
    )
    fingerprint = "same-request"
    job = original.create(
        "Pedido interrompido",
        "dataset-a",
        4,
        request_fingerprint=fingerprint,
    )
    original.update(
        job["id"],
        status="running",
        phase="optimizing",
        message="A calcular",
    )
    original.conn.close()

    reopened = ReplanJobStore(
        path,
        worker_id="new-process",
        worker_pid=os.getpid(),
    )
    try:
        interrupted = reopened.get(job["id"])
        raw_status = reopened.conn.execute(
            "SELECT status FROM replan_jobs WHERE id=?",
            (job["id"],),
        ).fetchone()[0]

        assert interrupted["status"] == "failed"
        assert interrupted["phase"] == "interrupted"
        assert interrupted["stored_status"] == "running"
        assert interrupted["stale"] is True
        assert interrupted["interrupted"] is True
        assert raw_status == "running"

        replacement, created = reopened.create_or_get(
            "Pedido interrompido",
            "dataset-a",
            4,
            request_fingerprint=fingerprint,
        )
        assert created is True
        assert replacement["id"] != job["id"]
    finally:
        reopened.conn.close()


def test_store_retention_keeps_only_bounded_history(tmp_path):
    store = ReplanJobStore(tmp_path / "replan.db", retention_limit=3)
    created_ids = []
    try:
        for index in range(7):
            job = store.create(f"Pedido {index}", "dataset-a", index)
            created_ids.append(job["id"])
            store.update(
                job["id"],
                status="completed",
                phase="completed",
                message="Aplicado",
            )

        rows = store.conn.execute("SELECT id FROM replan_jobs ORDER BY rowid").fetchall()
        assert [row["id"] for row in rows] == created_ids[-3:]
    finally:
        store.conn.close()


def test_replan_jobs_api_lists_only_current_dataset_and_revision(tmp_path, monkeypatch):
    manager = _manager(tmp_path / "replan.db")
    previous_dataset = state.dataset_info
    previous_revision = state.plan_revision
    try:
        state.dataset_info = {"id": "current-dataset"}
        state.plan_revision = 12
        pending_job = manager.store.create("Pendente", "current-dataset", 12)
        completed_job = manager.store.create("Terminado", "current-dataset", 12)
        manager.store.update(
            completed_job["id"],
            status="completed",
            phase="completed",
            message="Aplicado",
        )
        manager.store.create("Revisão antiga", "current-dataset", 11)
        manager.store.create("Outro ISOP", "other-dataset", 12)
        monkeypatch.setattr(replan_api, "manager", manager)
        client = TestClient(app)

        all_jobs = client.get("/api/data/replan-jobs")
        pending_jobs = client.get("/api/data/replan-jobs?pending=true")
        finished_jobs = client.get("/api/data/replan-jobs?pending=false")

        assert all_jobs.status_code == 200, all_jobs.text
        assert {job["id"] for job in all_jobs.json()["jobs"]} == {
            pending_job["id"],
            completed_job["id"],
        }
        assert [job["id"] for job in pending_jobs.json()["jobs"]] == [pending_job["id"]]
        assert [job["id"] for job in finished_jobs.json()["jobs"]] == [completed_job["id"]]
        assert all_jobs.json()["base_revision"] == 12
    finally:
        state.dataset_info = previous_dataset
        state.plan_revision = previous_revision
        _close(manager)


def test_repeated_replan_post_returns_same_job_without_second_submission(
    tmp_path,
    monkeypatch,
):
    manager = _manager(tmp_path / "replan.db")
    fields = (
        "engine_data",
        "config",
        "dataset_info",
        "plan_revision",
        "segments",
        "lots",
        "score",
        "warnings",
        "gate_report",
    )
    previous = {field: getattr(state, field) for field in fields}
    try:
        config = FactoryConfig()
        config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
        state.engine_data = EngineData(
            ops=[
                EOp(
                    id="T1_M1_SKU1",
                    sku="SKU1",
                    client="Cliente",
                    designation="Peça",
                    m="M1",
                    t="T1",
                    pH=100.0,
                    sH=0.5,
                    operators=1,
                    eco_lot=0,
                    alt=None,
                    stk=0,
                    backlog=0,
                    d=[0, 100, 0],
                    oee=0.5,
                    wip=0,
                )
            ],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
            twin_groups=[],
            client_demands={},
            workdays=["2026-07-23", "2026-07-24", "2026-07-27"],
            n_days=3,
            holidays=[],
        )
        state.config = config
        state.dataset_info = {"id": "dataset-http-dedup", "filename": "isop.xlsx"}
        state.plan_revision = 9
        state.segments = []
        state.lots = []
        state.score = {}
        state.warnings = []
        state.gate_report = {}
        monkeypatch.setattr(replan_api, "manager", manager)
        client = TestClient(app)
        body = {
            "expected_revision": 9,
            "reason": "Atualizar OEE",
            "config_updates": {"machine_oee": {"M1": 0.72}},
        }

        first = client.post("/api/data/replan-jobs", json=body)
        repeated = client.post("/api/data/replan-jobs", json=body)

        assert first.status_code == 200, first.text
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["job"]["id"] == first.json()["job"]["id"]
        assert first.json()["deduplicated"] is False
        assert repeated.json()["deduplicated"] is True
        assert len(manager.executor.submissions) == 1
    finally:
        for field, value in previous.items():
            setattr(state, field, value)
        _close(manager)


def test_store_migrates_legacy_database_without_failing_active_jobs(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE replan_jobs (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL,
            phase TEXT NOT NULL,
            message TEXT NOT NULL,
            reason TEXT NOT NULL,
            dataset_id TEXT NOT NULL,
            result_json TEXT,
            warnings_json TEXT,
            error TEXT
        );
        INSERT INTO replan_jobs VALUES (
            'legacy-running','2026-01-01T00:00:00+00:00',
            '2026-01-01T00:00:00+00:00','running',35,'optimizing',
            'A calcular','Legado','dataset-a',NULL,NULL,NULL
        );
        """
    )
    connection.commit()
    connection.close()

    store = ReplanJobStore(path)
    try:
        raw_status = store.conn.execute(
            "SELECT status FROM replan_jobs WHERE id='legacy-running'"
        ).fetchone()[0]
        classified = store.get("legacy-running")

        assert raw_status == "running"
        assert classified["status"] == "failed"
        assert classified["stale"] is True
    finally:
        store.conn.close()


@pytest.fixture
def ready_replan(tmp_path, monkeypatch):
    from backend.config import loader
    from backend.replan import jobs

    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    config.tools = {"T1": {"primary": "M1", "setup_hours": 0.5}}
    engine = EngineData(
        ops=[
            EOp(
                "OP1",
                "SKU1",
                "C",
                "Part",
                "M1",
                "T1",
                100,
                0.5,
                1,
                0,
                None,
                100,
                0,
                [100, 0],
                1.0,
                0,
            )
        ],
        machines=[MachineInfo("M1", "Grandes", 1020)],
        twin_groups=[],
        client_demands={},
        workdays=["2026-03-17", "2026-03-18"],
        n_days=2,
        holidays=[],
    )
    result = ScheduleResult(
        segments=[Segment("L1", "R1", "M1", "T1", 0, 420, 510, "A", 100, 60, 30, sku="SKU1")],
        lots=[Lot("L1", "OP1", "T1", "M1", None, 100, 60, 30, 0, False, sku="SKU1")],
        score={"otd": 100.0, "otd_d": 100.0, "tardy_count": 0, "setups": 1},
        time_ms=0,
        warnings=[],
        operator_alerts=[],
        gate_report={"status": "applicable"},
    )
    live = CopilotState(
        engine_data=engine,
        config=config,
        dataset_info={"id": "fixture", "filename": "fixture.xlsx"},
    )
    monkeypatch.setattr(CopilotState, "_refresh_analytics", lambda self: None)
    live.update_schedule(result)
    plans = PlansStore(tmp_path / "plans.db")
    live.plans_store = plans
    manager = _manager(tmp_path / "replan.db")
    monkeypatch.setattr(jobs, "state", live)
    monkeypatch.setattr(replan_api, "state", live)
    monkeypatch.setattr(replan_api, "manager", manager)
    config_path = tmp_path / "factory.yaml"
    real_save = loader.save_config
    real_save(config, str(config_path))
    monkeypatch.setattr(loader, "DEFAULT_CONFIG_PATH", str(config_path))

    def save_config(value, path=None):
        return real_save(value, str(path or config_path))

    monkeypatch.setattr(loader, "save_config", save_config)
    baseline = serialize_snapshot(live)
    job = manager.store.create(
        "fixture",
        "fixture",
        live.plan_revision,
        base_input_fingerprints=replan_base_fingerprints(baseline),
    )
    candidate_config = copy.deepcopy(config)
    candidate_config.name = "candidate"
    candidate = jobs._result_snapshot(
        engine,
        candidate_config,
        result,
        plan_revision=1,
        dataset_info=live.dataset_info,
        mutations=[],
    )
    manager.store.update(job["id"], status="ready", candidate=candidate)
    yield live, manager, job, result, config_path
    _close(manager)
    plans.close()


def _apply(manager, job_id, revision=1):
    return manager.apply(
        job_id,
        expected_revision=revision,
        approve_exceptions=True,
        approval_reason="test",
        approval_author="test",
    )


def test_start_waits_for_common_lock_and_rechecks_revision(ready_replan, monkeypatch):
    from backend.api.locks import PlanMutationLock

    live, manager, _, _, _ = ready_replan
    lock = PlanMutationLock()
    monkeypatch.setattr(replan_api, "plan_mutation_lock", lock)

    async def scenario():
        async with lock:
            pending = asyncio.create_task(replan_api.start_replan({"expected_revision": 1}))
            await asyncio.sleep(0)
            assert not pending.done()
            live.plan_revision = 2
        with pytest.raises(HTTPException) as exc:
            await pending
        assert exc.value.status_code == 409

    asyncio.run(scenario())
    assert manager.executor.submissions == []


def test_start_never_relabels_captured_inputs_with_a_later_revision(ready_replan, monkeypatch):
    live, manager, _, _, _ = ready_replan
    expected = replan_base_fingerprints(serialize_snapshot(live))
    validate = replan_api.validate_config

    def publish_during_preparation(config, engine):
        live.config = copy.deepcopy(live.config)
        live.config.name = "concurrent"
        live.plan_revision = 2
        return validate(config, engine)

    monkeypatch.setattr(replan_api, "validate_config", publish_during_preparation)
    response = asyncio.run(replan_api.start_replan({"expected_revision": 1}))
    assert response["job"]["base_revision"] == 1
    assert response["job"]["base_input_fingerprints"] == expected
    _, args = manager.executor.submissions[0]
    assert args[2].name != "concurrent"
    assert args[4] == 1


def test_same_revision_changed_config_rejects_candidate(ready_replan):
    live, manager, job, _, _ = ready_replan
    live.config.oee_default = 0.8
    with pytest.raises(ValueError, match="configura"):
        _apply(manager, job["id"])
    assert live.plan_revision == 1
    assert live.plans_store.list() == []
    assert manager.get(job["id"])["status"] == "ready"


def test_legacy_candidate_without_input_fingerprints_requires_recalculation(ready_replan):
    live, manager, job, _, _ = ready_replan
    manager.store.conn.execute("UPDATE replan_jobs SET base_input_fingerprints_json=NULL")
    manager.store.conn.commit()
    with pytest.raises(ValueError, match="recalcula"):
        _apply(manager, job["id"])
    assert live.plan_revision == 1


def test_completed_status_is_deferred_until_commit(ready_replan):
    from backend.plans.context import stage_state
    from backend.plans.transactions import clone_state

    live, manager, job, _, _ = ready_replan
    staged = clone_state(live)
    with stage_state(live, staged) as context:
        response = _apply(manager, job["id"])
        assert response["status"] == "completed"
        assert manager.store.get(job["id"])["status"] == "ready"
    assert live.plan_revision == 1 and staged.plan_revision == 2
    assert len(context.validators) == 1
    assert len(context.callbacks) == 1


def test_cancel_after_staged_calculation_prevents_durable_apply(ready_replan, monkeypatch):
    from backend.plans import transactions
    from backend.plans.context import is_staging

    live, manager, job, _, config_path = ready_replan
    before = serialize_snapshot(live)
    before_config = config_path.read_bytes()
    run_in_threadpool = transactions.run_in_threadpool
    cancelled = []

    async def cancel_after_calculation(function, *args, **kwargs):
        result = await run_in_threadpool(function, *args, **kwargs)
        if function.__name__ == "calculate":
            response, validators, callbacks = result
            assert not is_staging()
            assert response["job"]["status"] == "completed"
            assert len(validators) == len(callbacks) == 1
            assert manager.store.get(job["id"])["status"] == "ready"
            assert serialize_snapshot(live) == before
            assert config_path.read_bytes() == before_config
            cancelled.append(await replan_api.cancel_replan(job["id"]))
        return result

    monkeypatch.setattr(transactions, "run_in_threadpool", cancel_after_calculation)
    body = {
        "expected_revision": 1,
        "approve_exceptions": True,
        "approval_reason": "test",
        "approval_author": "test",
    }
    with pytest.raises(HTTPException) as failure:
        asyncio.run(replan_api.apply_replan(job["id"], body))
    assert failure.value.status_code == 409
    assert "cancelado" in str(failure.value.detail)

    assert len(cancelled) == 1 and cancelled[0]["job"]["status"] == "cancelled"
    assert serialize_snapshot(live) == before
    assert config_path.read_bytes() == before_config
    assert live.plans_store.list() == []
    assert live.plans_store.pending_mutations() == []
    assert live.plans_store.mutation_receipt(f"replan:{job['id']}") is None
    assert live.plans_store.mutation_receipt(f"replan-sync:{job['id']}") is None
    assert manager.store.get(job["id"])["status"] == "cancelled"
    with pytest.raises(ValueError):
        _apply(manager, job["id"])
    assert manager.cancel(job["id"])["status"] == "cancelled"


@pytest.mark.parametrize("terminal", ["completed", "cancelled"])
def test_terminal_jobs_ignore_late_updates_cancel_and_apply_replay(ready_replan, terminal):
    live, manager, job, _, config_path = ready_replan
    if terminal == "completed":
        _apply(manager, job["id"])
    else:
        manager.cancel(job["id"])
    before_job = manager.store.get(job["id"])
    before_plan = serialize_snapshot(live)
    before_config = config_path.read_bytes()
    before_receipt = live.plans_store.mutation_receipt(f"replan-sync:{job['id']}")
    before_plans = live.plans_store.list()

    for status in ("queued", "running", "ready", "completed", "cancelled", "failed"):
        manager.store.update(
            job["id"],
            status=status,
            phase=status,
            progress=35,
            result={"late": True},
            error="late worker update",
        )
        assert manager.store.get(job["id"]) == before_job
    assert manager.cancel(job["id"])["status"] == terminal
    if terminal == "completed":
        assert _apply(manager, job["id"])["status"] == "completed"
    else:
        with pytest.raises(ValueError):
            _apply(manager, job["id"])

    assert manager.store.get(job["id"]) == before_job
    assert serialize_snapshot(live) == before_plan
    assert config_path.read_bytes() == before_config
    assert live.plans_store.mutation_receipt(f"replan-sync:{job['id']}") == before_receipt
    assert live.plans_store.list() == before_plans


def test_commit_failure_does_not_complete_job_or_publish_config(ready_replan, monkeypatch):
    live, manager, job, _, config_path = ready_replan
    before = config_path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("injected commit failure")

    monkeypatch.setattr(live.plans_store, "commit_mutation", fail)
    with pytest.raises(OSError):
        _apply(manager, job["id"])
    assert live.plan_revision == 1 and live.config.name != "candidate"
    assert config_path.read_bytes() == before
    assert manager.store.get(job["id"])["status"] == "ready"
    assert live.plans_store.list() == []


def test_apply_refused_by_the_history_guard_is_a_plain_409(ready_replan, monkeypatch):
    """Small-outage rehearsal of 11/10/2026: the commit refused a candidate
    that changed a started lot and the screen got HTTP 500. It is a 409 in
    plain Portuguese; nothing is published and the job stays ready."""
    from backend.plans.store import HistoricalPlanProtectedError

    live, manager, job, _, config_path = ready_replan
    before_plan = serialize_snapshot(live)
    before_config = config_path.read_bytes()

    def refuse(*_args, **_kwargs):
        raise HistoricalPlanProtectedError(["L1"], ["Referência SKU1 (M1)"])

    monkeypatch.setattr(live.plans_store, "commit_mutation", refuse)
    body = {"expected_revision": 1, "approve_exceptions": True,
            "approval_reason": "test", "approval_author": "test"}
    with pytest.raises(HTTPException) as refused:
        asyncio.run(replan_api.apply_replan(job["id"], body))

    assert refused.value.status_code == 409
    detail = refused.value.detail
    assert detail["code"] == "historical_plan_protected"
    assert detail["message"] == (
        "O plano proposto alteraria a produção anterior a hoje ou já feita hoje, que está "
        "protegida (Referência SKU1 (M1)). O plano ativo não foi alterado; calcule novamente a alteração."
    )
    assert detail["current_revision"] == 1
    assert serialize_snapshot(live) == before_plan
    assert config_path.read_bytes() == before_config
    assert manager.store.get(job["id"])["status"] == "ready"
    assert live.plans_store.list() == []
    assert live.plans_store.pending_mutations() == []


@pytest.mark.parametrize("approval", [{}, {"approve_exceptions": True}])
def test_apply_needing_approval_says_why_in_plain_portuguese(ready_replan, monkeypatch, approval):
    """The approval refusal of a replan apply shows the reasons in plain
    Portuguese, never the internal codes (``operational_sequence_review``);
    the codes stay machine-readable in ``approval_reasons``."""
    from backend.scheduler import gates

    live, manager, job, _, config_path = ready_replan
    before_plan = serialize_snapshot(live)
    build = gates.build_gate_report
    reasons = ["delivery_risk", "operational_sequence_review"]

    def needs_approval(*args, **kwargs):
        return {**build(*args, **kwargs), "requires_approval": True,
                "apply_decision": "approval_required", "approval_reasons": reasons}

    monkeypatch.setattr(gates, "build_gate_report", needs_approval)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(replan_api.apply_replan(job["id"], {"expected_revision": 1, **approval}))

    assert refused.value.status_code == 409
    detail = refused.value.detail
    assert detail["code"] == "approval_required"
    assert detail["requires_approval"] is True
    assert detail["approval_reasons"] == reasons
    assert detail["current_revision"] == 1
    assert not any(code in detail["message"] for code in reasons)
    assert "conflitos físicos" not in detail["message"]
    expected = "motivo e autor" if approval else "há encomendas em risco de atraso"
    assert expected in detail["message"]
    assert serialize_snapshot(live) == before_plan
    assert manager.store.get(job["id"])["status"] == "ready"


def test_durable_receipt_recovers_failed_completion_callback_and_replay(ready_replan, monkeypatch):
    live, manager, job, _, _ = ready_replan
    update = manager.store.update

    def fail_projection(job_id, **changes):
        if changes.get("status") == "completed":
            raise sqlite3.OperationalError("receipt projection unavailable")
        return update(job_id, **changes)

    monkeypatch.setattr(manager.store, "update", fail_projection)
    response = _apply(manager, job["id"])
    assert response["status"] == "completed"
    assert manager.store.get(job["id"])["status"] == "ready"
    assert manager.get(job["id"])["status"] == "completed"
    assert manager.cancel(job["id"])["status"] == "completed"
    assert _apply(manager, job["id"])["status"] == "completed"
    assert live.plan_revision == 2 and len(live.plans_store.list()) == 1
    reopened = _manager(manager.store.path)
    try:
        assert reopened.get(job["id"])["status"] == "completed"
        assert reopened.list_jobs(dataset_id="fixture", base_revision=1, pending=True) == []
    finally:
        _close(reopened)


def test_http_apply_replay_returns_durable_response_once(ready_replan):
    live, _, job, _, _ = ready_replan
    client = TestClient(app)
    body = {
        "expected_revision": 1,
        "approve_exceptions": True,
        "approval_reason": "test",
        "approval_author": "test",
    }
    first = client.post(f"/api/data/replan-jobs/{job['id']}/apply", json=body)
    repeated = client.post(f"/api/data/replan-jobs/{job['id']}/apply", json=body)
    assert first.status_code == repeated.status_code == 200, first.text
    assert first.json() == repeated.json()
    assert live.plan_revision == 2 and len(live.plans_store.list()) == 1


@pytest.mark.parametrize(
    "kind,params,field",
    [
        ("machine_down", {"machine_id": "M1", "start": 1, "end": 1}, "machine_blocked_days"),
        ("tool_down", {"tool_id": "T1", "start": 1, "end": 1}, "tool_blocked_days"),
        (
            "operator_shortage",
            {"group": "Grandes", "shift": "A", "count": 1, "start": 1, "end": 1},
            "operator_blocked_intervals",
        ),
        ("add_holiday", {"day_idx": 1}, "holidays"),
    ],
)
def test_calendar_overlays_survive_candidate_and_apply(
    ready_replan, monkeypatch, kind, params, field
):
    from backend.simulator.mutations import apply_mutation
    from backend.transform.calendars import apply_calendars
    from backend.plans.serialize import deserialize_snapshot

    live, manager, _, result, _ = ready_replan
    apply_calendars(live.engine_data, live.config)
    apply_mutation(live.engine_data, kind, params, config=live.config)
    live.active_mutations = [{"type": kind, "params": params}]
    expected = copy.deepcopy(getattr(live.engine_data, field))
    baseline = serialize_snapshot(live)
    job = manager.store.create(
        "overlay", "fixture", 1, base_input_fingerprints=replan_base_fingerprints(baseline)
    )

    def optimize(engine, **kwargs):
        assert getattr(engine, field) == expected
        return copy.deepcopy(result)

    monkeypatch.setattr("backend.cpo.optimize", optimize)
    manager._run(
        job["id"],
        copy.deepcopy(live.engine_data),
        copy.deepcopy(live.config),
        "fixture",
        1,
        "overlay",
        copy.deepcopy(live.dataset_info),
        baseline_snapshot=baseline,
    )
    current = manager.store.get(job["id"])
    assert current["status"] == "ready", current
    restored = deserialize_snapshot(manager.store.get_candidate(job["id"]))
    assert restored["active_mutations"] == live.active_mutations
    _apply(manager, job["id"])
    assert getattr(live.engine_data, field) == expected


def test_valid_baseline_survives_failed_compaction(ready_replan, monkeypatch):
    from backend.plans.serialize import deserialize_snapshot
    from backend.replan import jobs
    from backend.scheduler.scoring import compute_score
    from backend.scheduler.validation import PlanValidationError

    live, manager, _, result, _ = ready_replan
    baseline = serialize_snapshot(live)
    job = manager.store.create(
        "delivery floor", "fixture", 1,
        base_input_fingerprints=replan_base_fingerprints(baseline),
    )
    late = copy.deepcopy(result)
    late.segments[0].day_idx = 1
    late.lots[0].edd = 0
    late.score = compute_score(
        late.segments, late.lots, live.engine_data, config=live.config
    )
    monkeypatch.setattr(jobs, "optimize_preserving_started_lots", lambda *_args, **_kwargs: late)

    def reject_compaction(*_args, **_kwargs):
        raise PlanValidationError([{"kind": "injected_compaction_failure"}])

    monkeypatch.setattr(jobs, "compact_preserving_started_lots", reject_compaction)

    manager._run(
        job["id"], copy.deepcopy(live.engine_data), copy.deepcopy(live.config),
        "fixture", 1, "delivery floor", copy.deepcopy(live.dataset_info),
        baseline_snapshot=baseline,
    )

    current = manager.store.get(job["id"])
    assert current["status"] == "ready", current
    assert current["result"]["selected_source"] == "normalized_baseline_delivery_floor"
    restored = deserialize_snapshot(manager.store.get_candidate(job["id"]))
    assert restored["result"].segments == result.segments


@pytest.mark.parametrize("relaxed", [False, True])
def test_calendar_candidate_survives_optional_timeout(ready_replan, monkeypatch, relaxed):
    """A valid active plan is never discarded by an optional pass timing out."""
    from backend.planning_control import planning_checkpoint, planning_scope, remaining_time
    from backend.plans.serialize import deserialize_snapshot
    from backend.replan import jobs

    live, manager, _, result, _ = ready_replan
    baseline = serialize_snapshot(live)
    config = copy.deepcopy(live.config)
    config.operators[("Grandes", "A")] += 1
    budgets = []
    clock = [0.0]

    def timed_out(*args, **kwargs):
        budgets.append(remaining_time())
        # A failed optional pass must not mutate the retained candidate.
        target = args[0] if isinstance(args[0], list) else args[2].segments
        target.clear()
        clock[0] += remaining_time() + 0.001
        planning_checkpoint()

    monkeypatch.setattr(jobs, "compact_preserving_started_lots", timed_out)
    monkeypatch.setattr("backend.scheduler.shift_exchange.repair_shift_capacity_exchange", timed_out)
    # With capacity released, the constructor also runs out of time here.
    monkeypatch.setattr(jobs, "optimize_preserving_started_lots", timed_out)
    job = manager.store.create("calendar timeout", "fixture", 1)
    with planning_scope(timeout_s=60, clock=lambda: clock[0]):
        manager._run(
            job["id"], copy.deepcopy(live.engine_data), config,
            "fixture", 1, "calendar timeout", live.dataset_info,
            baseline_snapshot=baseline, prefer_unchanged_baseline=not relaxed,
            reoptimize_relaxed_baseline=relaxed,
        )
        assert remaining_time() > 0
    current = manager.store.get(job["id"])
    assert current["status"] == "ready", current
    # The first optional pass keeps the closing reserve (10 s of 60 s).
    assert budgets and 0 < budgets[0] <= 50
    candidate = deserialize_snapshot(manager.store.get_candidate(job["id"]))
    assert candidate["result"].segments == result.segments
    assert candidate["config"].operators == config.operators
    assert current["result"]["improvement_report"]["status"] != "completed"
    assert live.plan_revision == 1


@pytest.mark.parametrize("outcome", ["complete", "timeout", "cancelled", "invalid", "internal"])
def test_slow_local_repair_keeps_budget_for_complete_pipeline(ready_replan, monkeypatch, outcome):
    """T7: a slow local repair stops at its own budget; the constructor still runs."""
    from backend.planning_control import (
        PlanningCancelled,
        PlanningTimeout,
        planning_checkpoint,
        planning_scope,
        remaining_time,
    )
    from backend.plans.serialize import deserialize_snapshot
    from backend.replan import jobs
    from backend.scheduler.scoring import compute_score
    from backend.scheduler.validation import PlanValidationError, assert_plan_valid

    live, manager, _, result, _ = ready_replan
    baseline = serialize_snapshot(live)
    config = copy.deepcopy(live.config)
    config.machine_unavailability = [{
        "id": "stop", "resource": "M1",
        "start_at": "2026-03-17T00:00+00:00", "end_at": "2026-03-18T00:00+00:00",
    }]
    clock = [0.0]
    local_budgets = []
    optimizer_budgets = []
    optimizer_started = []

    def slow_local_repair(segments, *_args, **_kwargs):
        local_budgets.append(remaining_time())
        clock[0] += remaining_time() + 0.001  # would run on: only its scope stops it
        planning_checkpoint()
        return segments

    def complete_pipeline(data, config, history, **kwargs):
        optimizer_budgets.append(remaining_time())
        optimizer_started.append(clock[0])
        assert history.segments == result.segments
        if outcome == "timeout":
            raise PlanningTimeout("Planning deadline expired; candidate not committed.")
        if outcome == "cancelled":
            raise PlanningCancelled("cancelled before candidate")
        if outcome == "invalid":
            raise PlanValidationError([{"kind": "x", "message": "Conflito injetado."}])
        if outcome == "internal":
            raise KeyError("unexpected english failure")
        candidate = copy.deepcopy(result)
        candidate.segments[0].day_idx = 1
        candidate.score = compute_score(candidate.segments, candidate.lots, data, config=config)
        assert_plan_valid(candidate.segments, data, config, lots=candidate.lots)
        return candidate

    monkeypatch.setattr(jobs, "_current_planning_day", lambda *_: 0)
    monkeypatch.setattr(jobs, "optimize_preserving_started_lots", complete_pipeline)
    monkeypatch.setattr("backend.scheduler.scheduler._repair_hard_constraints", slow_local_repair)
    job = manager.store.create("calendar constraint", "fixture", 1)
    with planning_scope(timeout_s=60.0, clock=lambda: clock[0]):
        manager._run(
            job["id"], copy.deepcopy(live.engine_data), config,
            "fixture", 1, "calendar constraint", live.dataset_info,
            baseline_snapshot=baseline, prefer_unchanged_baseline=True,
        )
    current = manager.store.get(job["id"])
    # Local repair: remaining − closing reserve (10 s) − constructor reserve.
    assert local_budgets and 0 < local_budgets[0] <= 60.0 - 10.0 - jobs.LOCAL_REPAIR_OPTIMIZER_RESERVE_S
    # The constructor still receives the reserved time ...
    assert optimizer_budgets and optimizer_budgets[0] >= jobs.LOCAL_REPAIR_OPTIMIZER_RESERVE_S - 0.01
    # ... and leaves the closing reserve (10 s) for gate, score, audit and save.
    outer_remaining = 60.0 - optimizer_started[0]
    assert optimizer_budgets[0] <= outer_remaining - 10.0 + 1e-6
    if outcome == "complete":
        assert current["status"] == "ready", current
        assert current["result"]["selected_source"] == "optimized"
        assert any("ajuste rápido não terminou" in w for w in current["warnings"])
        candidate = deserialize_snapshot(manager.store.get_candidate(job["id"]))
        assert candidate["result"].segments[0].day_idx == 1
    elif outcome == "cancelled":
        assert current["status"] == "cancelled", current
        assert manager.store.get_candidate(job["id"]) is None
    else:
        expected = {
            "timeout": "planning_timeout", "invalid": "invalid_plan", "internal": "internal_error",
        }[outcome]
        assert current["status"] == "failed", current
        assert current["code"] == expected
        assert current["message"] == jobs.FAILURE_TEXTS[expected][0]
        assert "não foram alterados" in current["error"]
        if outcome == "invalid":
            assert current["error"].endswith("Primeiros conflitos: Conflito injetado.")
        assert manager.store.get_candidate(job["id"]) is None
    assert live.plan_revision == 1
    assert live.segments == result.segments


@pytest.mark.parametrize("stopped", ["outer_timeout", "internal"])
def test_failed_job_text_is_portuguese_never_raw_exception(ready_replan, monkeypatch, stopped):
    """T8: no job error shows "Planning deadline expired" or other raw text."""
    from backend.planning_control import planning_checkpoint, planning_scope
    from backend.replan import jobs

    live, manager, _, _, _ = ready_replan
    clock = [0.0]

    def fail(*_args, **_kwargs):
        if stopped == "outer_timeout":
            clock[0] += 1_000.0
            planning_checkpoint()
        raise RuntimeError("Planning deadline expired; candidate not committed.")

    monkeypatch.setattr(jobs, "optimize_preserving_started_lots", fail)
    job = manager.store.create("raw text", "fixture", 1)
    with planning_scope(clock=lambda: clock[0]):
        manager._run(
            job["id"], copy.deepcopy(live.engine_data), copy.deepcopy(live.config),
            "fixture", 1, "raw text", live.dataset_info,
        )
    current = manager.store.get(job["id"])
    assert current["status"] == "failed", current
    assert current["code"] == ("planning_timeout" if stopped == "outer_timeout" else "internal_error")
    for text in (current["message"], current["error"]):
        assert "Planning deadline expired" not in text
        assert "candidate not committed" not in text


def test_legacy_material_baseline_is_rebuilt_not_reused(ready_replan, monkeypatch):
    """A5: a plan without per-delivery material is recalculated, not kept unchanged."""
    from backend.replan import jobs

    live, manager, _, result, _ = ready_replan
    baseline = serialize_snapshot(live)
    assert not any(lot.output_milestones for lot in result.lots)
    monkeypatch.setattr(
        "backend.scheduler.quantity_dispatch.has_quantity_releases", lambda _lots: True,
    )
    rebuilt = []

    def constructor(data, config, history, **kwargs):
        rebuilt.append(history)
        return copy.deepcopy(result)

    monkeypatch.setattr(jobs, "optimize_preserving_started_lots", constructor)
    config = copy.deepcopy(live.config)
    config.operators[("Grandes", "A")] += 1
    job = manager.store.create("legacy", "fixture", 1)
    manager._run(
        job["id"], copy.deepcopy(live.engine_data), config,
        "fixture", 1, "legacy", live.dataset_info,
        baseline_snapshot=baseline, prefer_unchanged_baseline=True,
    )
    current = manager.store.get(job["id"])
    assert rebuilt, "a legacy baseline must go through the constructor"
    assert current["status"] == "ready", current
    assert current["result"]["selected_source"] == "optimized"
    assert any("libertado por entrega; por isso foi recalculado de raiz" in w for w in current["warnings"])


def test_unchanged_replan_keeps_the_better_compacted_baseline(ready_replan, monkeypatch):
    from dataclasses import replace

    from backend.plans.serialize import deserialize_snapshot
    from backend.replan import jobs
    from backend.scheduler.scoring import compute_score

    live, manager, _, result, _ = ready_replan
    live.engine_data.ops[0].stk = 0
    result.segments = [replace(result.segments[0], start_min=600, end_min=690)]
    result.score = compute_score(result.segments, result.lots, live.engine_data, config=live.config)
    live.update_schedule(result)
    baseline = serialize_snapshot(live)
    compacted = copy.deepcopy(result)
    compacted.segments = [replace(result.segments[0], start_min=420, end_min=510)]
    compacted.score = compute_score(
        compacted.segments, compacted.lots, live.engine_data, config=live.config,
    )
    extra = copy.deepcopy(compacted)
    extra.segments = [
        replace(extra.segments[0], end_min=480, qty=50, prod_min=30),
        replace(extra.segments[0], run_id="R2", start_min=900, end_min=960, qty=50, prod_min=30),
    ]
    extra.score = compute_score(extra.segments, extra.lots, live.engine_data, config=live.config)
    monkeypatch.setattr(jobs, "optimize_preserving_started_lots", lambda *_a, **_k: extra)
    monkeypatch.setattr(jobs, "compact_preserving_started_lots", lambda *_a, **_k: compacted)
    job = manager.store.create("same inputs", "fixture", live.plan_revision)

    manager._run(
        job["id"], copy.deepcopy(live.engine_data), copy.deepcopy(live.config),
        "fixture", live.plan_revision, "same inputs", copy.deepcopy(live.dataset_info),
        baseline_snapshot=baseline,
    )

    current = manager.store.get(job["id"])
    assert current["status"] == "ready", current
    restored = deserialize_snapshot(manager.store.get_candidate(job["id"]))
    assert restored["result"].segments == compacted.segments
    assert current["result"]["selected_source"] == "normalized_baseline_delivery_floor"


def test_unchanged_plan_comparison_rejects_individual_loss_with_equal_otd(ready_replan):
    from dataclasses import replace

    from backend.replan.jobs import _prefer_no_loss_plan
    from backend.scheduler.scoring import compute_score

    live, _, _, result, _ = ready_replan
    data = copy.deepcopy(live.engine_data)
    data.ops[0].stk = 0
    data.ops.append(replace(data.ops[0], id="OP2", sku="SKU2", t="T2"))
    before = copy.deepcopy(result)
    before.segments.append(replace(
        before.segments[0], lot_id="L2", run_id="R2", tool_id="T2", sku="SKU2", day_idx=1,
    ))
    before.lots.append(replace(
        before.lots[0], id="L2", op_id="OP2", tool_id="T2", sku="SKU2",
    ))
    after = copy.deepcopy(before)
    after.segments = [replace(s, day_idx=1 - s.day_idx) for s in after.segments]
    for plan in (before, after):
        plan.score = compute_score(plan.segments, plan.lots, data, config=live.config)

    assert after.score["otd"] == before.score["otd"]
    assert not _prefer_no_loss_plan(after, before, data)


def test_submission_failure_is_terminal_and_does_not_poison_deduplication(tmp_path, monkeypatch):
    manager = _manager(tmp_path / "replan.db")
    original_submit = manager.executor.submit

    def fail(*args):
        raise RuntimeError("executor closed")

    kwargs = dict(
        engine_data={},
        config={},
        dataset_id="fixture",
        base_revision=1,
        reason="test",
        request_fingerprint="same",
    )
    try:
        monkeypatch.setattr(manager.executor, "submit", fail)
        with pytest.raises(RuntimeError, match="executor closed"):
            manager.start(**kwargs)
        failed = manager.store.list_jobs(dataset_id="fixture", base_revision=1)
        assert len(failed) == 1 and failed[0]["status"] == "failed"
        monkeypatch.setattr(manager.executor, "submit", original_submit)
        replacement = manager.start(**kwargs)
        assert replacement["id"] != failed[0]["id"]
        assert not replacement["deduplicated"]
    finally:
        _close(manager)


def test_failure_summary_is_plain_portuguese_without_internal_tuples():
    """The detail reuses the validator's plain messages, not identity tuples."""
    from backend.replan import jobs
    from backend.scheduler.types import Segment
    from backend.scheduler.validation import PlanValidationError, validate_plan
    from backend.types import EngineData, MachineInfo

    def seg(lot, tool, sku, day, setup):
        return Segment(
            lot_id=lot, run_id=f"R_{lot}", machine_id="PRM042", tool_id=tool, day_idx=day,
            start_min=420, end_min=600, shift="A", qty=10, prod_min=180.0 - setup,
            setup_min=float(setup), sku=sku, run_setup_min=60.0,
        )

    data = EngineData(
        ops=[], machines=[MachineInfo(id="PRM042", group="Médias", day_capacity=1020)],
        twin_groups=[], client_demands={},
        workdays=[f"2026-10-{day:02d}" for day in range(5, 25)], n_days=20, holidays=[],
    )
    violations = validate_plan(
        [seg("LOT_JDE", "JDE001", "JD471512-0071", 4, 60),
         seg("LOT_VUL115_PRM042_8718696125_1", "VUL115", "8718696125", 8, 0)],
        data,
    )
    summary = jobs._violation_summary(PlanValidationError(violations))
    assert "('" not in summary and "LOT_" not in summary
    assert "ferramenta VUL115 (ref. 8718696125) entra na PRM042 depois da JDE001" in summary
    assert summary.endswith(".")
    assert "Primeiros conflitos" not in summary  # the caller adds the heading once


def test_failure_texts_are_plain_and_say_nothing_changed():
    from backend.replan import jobs

    for code, (message, detail) in jobs.FAILURE_TEXTS.items():
        for text in (message, detail):
            assert "processo" not in text and "reparação local" not in text, (code, text)
        assert "não foram alterados" in detail, code
    assert "Pode iniciar novamente" in jobs.FAILURE_TEXTS["interrupted"][1]


def test_one_legacy_material_rule(monkeypatch):
    """jobs and the store share canonical.legacy_material_plan."""
    from backend.replan import jobs

    seen = []

    def fake(lots, data, config):
        seen.append((lots, data, config))
        return True

    monkeypatch.setattr("backend.scheduler.canonical.legacy_material_plan", fake)

    class Result:
        lots = ["L"]

    assert jobs._baseline_needs_material_rebuild(
        {"result": Result(), "engine_data": "D", "config": "C"}
    ) is True
    assert seen == [(["L"], "D", "C")]


def test_wide_calendar_edit_goes_straight_to_the_complete_constructor(ready_replan, monkeypatch):
    """An edit that invalidates more segments than the quick repair handles
    gives the complete constructor the whole budget (rehearsal of 11/10/2026)."""
    from backend.planning_control import planning_scope, remaining_time
    from backend.replan import jobs
    from backend.scheduler.scoring import compute_score

    live, manager, _, result, _ = ready_replan
    baseline = serialize_snapshot(live)
    config = copy.deepcopy(live.config)
    config.machine_unavailability = [{
        "id": "stop", "resource": "M1",
        "start_at": "2026-03-17T00:00+00:00", "end_at": "2026-03-18T00:00+00:00",
    }]
    budgets = []

    def no_quick_repair(*_args, **_kwargs):
        raise AssertionError("the quick repair must not run for a wide edit")

    def complete_pipeline(data, config, history, **kwargs):
        budgets.append(remaining_time())
        candidate = copy.deepcopy(result)
        candidate.segments[0].day_idx = 1
        candidate.score = compute_score(candidate.segments, candidate.lots, data, config=config)
        return candidate

    monkeypatch.setattr(jobs, "LOCAL_REPAIR_MAX_INVALID_SEGMENTS", 0)
    monkeypatch.setattr(jobs.ReplanJobManager, "_local_calendar_repair",
                        staticmethod(no_quick_repair))
    monkeypatch.setattr(jobs, "_current_planning_day", lambda *_: 0)
    monkeypatch.setattr(jobs, "optimize_preserving_started_lots", complete_pipeline)
    clock = [0.0]
    job = manager.store.create("wide edit", "fixture", 1)
    with planning_scope(timeout_s=60.0, clock=lambda: clock[0]):
        manager._run(
            job["id"], copy.deepcopy(live.engine_data), config,
            "fixture", 1, "wide edit", live.dataset_info,
            baseline_snapshot=baseline, prefer_unchanged_baseline=True,
        )
    current = manager.store.get(job["id"])
    assert current["status"] == "ready", current
    assert current["result"]["selected_source"] == "optimized"
    assert "A alteração afeta 1 segmento do plano ativo; o plano foi recalculado por completo." in (
        current["warnings"]
    )
    # Everything but the closing reserve (10 s of 60 s) goes to the constructor.
    assert budgets == [pytest.approx(50.0)]


def test_invalidated_segments_counts_distinct_segments():
    from backend.replan.jobs import _invalidated_segments
    from backend.scheduler.validation import PlanValidationError

    one = {"lot_id": "L1", "machine_id": "M1", "day_idx": 3, "start_min": 420}
    error = PlanValidationError([one, dict(one, kind="other"), {**one, "start_min": 600},
                                 {"kind": "coverage", "message": "sem segmento"}])
    assert _invalidated_segments(error) == 2
    assert _invalidated_segments(TypeError("x")) == 0


def test_stale_legacy_note_is_dropped_from_a_current_plan():
    from backend.replan.jobs import _without_stale_legacy_warnings
    from backend.scheduler.lot_sizing import QUANTITY_MATERIAL_VERSION

    note = ("O plano ativo foi calculado antes de o material das peças gémeas passar a ser "
            "libertado por entrega; por isso foi recalculado de raiz.")
    restore_note = "Este plano foi calculado antes de o material passar a ser libertado por entrega."
    other = "Plano anterior preservado: 1 lote iniciado antes do dia 2."
    current = Lot("L1", "OP1", "T1", "M1", None, 100, 60, 30, 0, False, output_milestones=[
        {"qty": 100, "quantity_material_version": QUANTITY_MATERIAL_VERSION},
    ])
    legacy = Lot("L1", "OP1", "T1", "M1", None, 100, 60, 30, 0, False)
    warnings = [note, other, restore_note]
    # A kept plan already under the current contract: the old note is stale.
    assert _without_stale_legacy_warnings(warnings, [current], []) == [other]
    # The calculation that rebuilt it keeps its own note.
    assert _without_stale_legacy_warnings(warnings, [current], [note]) == [note, other]
    # Still a legacy plan: the notes stay true.
    assert _without_stale_legacy_warnings(warnings, [legacy], []) == warnings


# ── Capacity released with late deliveries (13/10/2026, revision 127) ────
# The 35 s are kept for the constructor only when a late delivery has idle
# capacity (``jobs._late_with_idle_capacity``); the helper stands it in.

STALE_REBUILD_NOTE = (
    "A alteração afeta 18 segmentos do plano ativo; o plano foi recalculado por completo."
)


def _late_active_plan(live, result):
    """The active plan with its only order a day late, as after an outage."""
    from dataclasses import replace

    from backend.scheduler.scoring import compute_score

    live.engine_data.ops[0].stk = 0
    late = copy.deepcopy(result)
    late.segments = [replace(result.segments[0], day_idx=1)]
    late.score = compute_score(late.segments, late.lots, live.engine_data, config=live.config)
    late.warnings = [STALE_REBUILD_NOTE]
    live.update_schedule(late)
    on_time = copy.deepcopy(result)
    on_time.score = compute_score(
        on_time.segments, on_time.lots, live.engine_data, config=live.config,
    )
    return late, on_time


def _late(plan, engine_data) -> bool:
    from backend.scheduler.priority import delivery_is_complete, with_order_delivery

    return not delivery_is_complete(
        with_order_delivery(plan.score, plan.segments, plan.lots, engine_data),
    )


def _release_capacity(
    live, manager, monkeypatch, *, compaction, constructor, clock=None, idle=None,
):
    """Release capacity through the job. ``idle(plan)`` stands for the
    idle-capacity check (default: every late plan has idle capacity, as the
    fixture's late order on day 1 leaves day 0 free)."""
    from backend.planning_control import planning_scope, remaining_time
    from backend.replan import jobs

    budgets = []
    engine_data = live.engine_data
    idle = idle if idle is not None else (lambda plan: _late(plan, engine_data))
    monkeypatch.setattr(jobs, "_late_with_idle_capacity", lambda plan, *_args: idle(plan))

    def compact(data, config, plan, **_kwargs):
        budgets.append(("compaction", remaining_time()))
        assert STALE_REBUILD_NOTE not in plan.warnings
        compacted = compaction(plan)
        compacted.warnings = [
            *compacted.warnings, "Capacidade libertada: o plano ativo foi novamente compactado.",
        ]
        return compacted

    def rebuild(*_args, **_kwargs):
        budgets.append(("constructor", remaining_time()))
        return constructor()

    monkeypatch.setattr(jobs, "compact_preserving_started_lots", compact)
    monkeypatch.setattr(jobs, "optimize_preserving_started_lots", rebuild)
    baseline = serialize_snapshot(live)
    job = manager.store.create("capacity released", "fixture", live.plan_revision)
    clock = clock if clock is not None else [0.0]
    # One more operator: capacity released, so the inputs differ from the plan's.
    config = copy.deepcopy(live.config)
    config.operators[("Grandes", "A")] += 1
    with planning_scope(timeout_s=60.0, clock=lambda: clock[0]):
        manager._run(
            job["id"], copy.deepcopy(live.engine_data), config,
            "fixture", live.plan_revision, "capacity released", copy.deepcopy(live.dataset_info),
            baseline_snapshot=baseline, reoptimize_relaxed_baseline=True,
        )
    current = manager.store.get(job["id"])
    assert current["status"] == "ready", current
    assert STALE_REBUILD_NOTE not in current["warnings"]
    return current, budgets


def test_capacity_release_rebuilds_when_compaction_leaves_orders_late(ready_replan, monkeypatch):
    """The compaction keeps time for the constructor; the constructor's plan
    is taken because the single comparator prefers it with no order losing."""
    from backend.plans.serialize import deserialize_snapshot

    live, manager, _, result, _ = ready_replan
    late, on_time = _late_active_plan(live, result)

    current, budgets = _release_capacity(
        live, manager, monkeypatch,
        compaction=copy.deepcopy, constructor=lambda: copy.deepcopy(on_time),
    )

    assert current["result"]["selected_source"] == "optimized_after_capacity_release"
    restored = deserialize_snapshot(manager.store.get_candidate(current["id"]))
    assert restored["result"].segments == on_time.segments
    # 60 s minus the closing reserve (10 s); the compaction leaves 35 s.
    assert budgets == [("compaction", pytest.approx(15.0)), ("constructor", pytest.approx(50.0))]
    assert any(w.startswith("Capacidade libertada: o recálculo completo") for w in current["warnings"])


def test_capacity_release_keeps_the_compaction_unless_the_rebuild_is_better(
    ready_replan, monkeypatch,
):
    from backend.plans.serialize import deserialize_snapshot

    live, manager, _, result, _ = ready_replan
    late, _on_time = _late_active_plan(live, result)

    current, budgets = _release_capacity(
        live, manager, monkeypatch,
        compaction=copy.deepcopy, constructor=lambda: copy.deepcopy(late),
    )

    assert current["result"]["selected_source"] == "compacted_baseline_after_capacity_release"
    assert [name for name, _budget in budgets] == ["compaction", "constructor"]
    restored = deserialize_snapshot(manager.store.get_candidate(current["id"]))
    assert restored["result"].segments == late.segments
    assert not any("recálculo completo" in w for w in current["warnings"])


def test_capacity_release_keeps_the_compaction_when_the_rebuild_times_out(
    ready_replan, monkeypatch,
):
    from backend.planning_control import planning_checkpoint, remaining_time
    from backend.plans.serialize import deserialize_snapshot

    live, manager, _, result, _ = ready_replan
    late, _on_time = _late_active_plan(live, result)
    clock = [0.0]

    def timed_out():
        clock[0] += remaining_time() + 0.001
        planning_checkpoint()

    current, _budgets = _release_capacity(
        live, manager, monkeypatch, compaction=copy.deepcopy, constructor=timed_out, clock=clock,
    )

    assert current["result"]["selected_source"] == "compacted_baseline_after_capacity_release"
    restored = deserialize_snapshot(manager.store.get_candidate(current["id"]))
    assert restored["result"].segments == late.segments


def test_capacity_release_without_late_orders_left_compacts_again(ready_replan, monkeypatch):
    """Nothing late after the compaction: the constructor does not run and the
    compaction goes on with the time it kept for it."""
    from backend.plans.serialize import deserialize_snapshot

    live, manager, _, result, _ = ready_replan
    _late, on_time = _late_active_plan(live, result)
    passes = []

    def compaction(plan):
        passes.append(plan.segments)
        return copy.deepcopy(on_time)

    def constructor():
        raise AssertionError("nothing is late: the constructor must not run")

    current, budgets = _release_capacity(
        live, manager, monkeypatch, compaction=compaction, constructor=constructor,
    )

    assert current["result"]["selected_source"] == "compacted_baseline_after_capacity_release"
    assert budgets == [("compaction", pytest.approx(15.0)), ("compaction", pytest.approx(50.0))]
    assert passes[1] == on_time.segments  # the second pass starts from the first
    restored = deserialize_snapshot(manager.store.get_candidate(current["id"]))
    assert restored["result"].segments == on_time.segments


def test_structural_lateness_gives_the_compaction_the_whole_budget(ready_replan, monkeypatch):
    """Late only for lack of capacity (no idle time before the deadline): the
    constructor has nothing to recover, so no time is kept for it (rehearsal
    of 13/10/2026 on revision 128: the reserve cost 3 setups)."""
    live, manager, _, result, _ = ready_replan
    _late_active_plan(live, result)

    def constructor():
        raise AssertionError("no idle capacity: the constructor must not run")

    _current, budgets = _release_capacity(
        live, manager, monkeypatch, compaction=copy.deepcopy, constructor=constructor,
        idle=lambda _plan: False,
    )

    assert budgets == [("compaction", pytest.approx(50.0))]


def test_failing_idle_capacity_check_reserves_nothing(ready_replan, monkeypatch):
    from backend.replan import jobs
    from backend.scheduler import idle_capacity

    live, _manager, _, result, _ = ready_replan
    late, _on_time = _late_active_plan(live, result)

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(idle_capacity, "late_with_idle_capacity", broken)
    assert jobs._late_with_idle_capacity(late, live.engine_data, live.config, 0) is False


def test_on_time_active_plan_gives_the_compaction_the_whole_budget(ready_replan, monkeypatch):
    live, manager, _, result, _ = ready_replan
    live.engine_data.ops[0].stk = 0

    def constructor():
        raise AssertionError("nothing is late: the constructor must not run")

    _current, budgets = _release_capacity(
        live, manager, monkeypatch, compaction=copy.deepcopy, constructor=constructor,
    )

    assert budgets == [("compaction", pytest.approx(50.0))]


def test_calculation_notes_of_an_earlier_plan_are_dropped():
    from backend.plans.frozen import without_calculation_notes

    kept = ["Plano anterior preservado: 1 lote iniciado antes do dia 2.", "Outro aviso."]
    stale = [
        STALE_REBUILD_NOTE,
        "O ajuste rápido não terminou a tempo; o plano foi recalculado por completo.",
        "Calendário aplicado com um ajuste rápido do plano ativo.",
        "Capacidade libertada: o plano ativo foi novamente compactado.",
    ]
    assert without_calculation_notes([*stale, *kept]) == kept
