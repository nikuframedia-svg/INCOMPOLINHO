"""Loading must survive slow calculations, retries and disconnects without re-applying."""

import asyncio
import copy
import os
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import data as data_api
from backend.audit.store import AuditStore
from backend.config.types import FactoryConfig, MachineConfig
from backend.copilot.state import CopilotState
from backend.loading.jobs import LoadJobError, LoadJobManager, parse_upload
from backend.plans.serialize import deserialize_snapshot
from backend.plans.store import PlansStore
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.types import EOp, EngineData, MachineInfo, TwinGroup


def load_fixture():
    config = FactoryConfig()
    config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
    config.tools = {"T1": {"primary": "M1", "setup_hours": 0.5}}
    engine = EngineData(
        ops=[
            EOp(
                id="OP1",
                sku="SKU1",
                client="Client",
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
                d=[100, 0],
                oee=0.66,
                wip=0,
            )
        ],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[],
        client_demands={},
        workdays=["2026-03-17", "2026-03-18"],
        n_days=2,
    )
    result = ScheduleResult(
        lots=[
            Lot(
                id="LOT1",
                op_id="OP1",
                tool_id="T1",
                machine_id="M1",
                alt_machine_id=None,
                qty=100,
                prod_min=60 / 0.66,
                setup_min=30,
                edd=0,
                is_twin=False,
            )
        ],
        segments=[
            Segment(
                lot_id="LOT1",
                run_id="RUN1",
                machine_id="M1",
                tool_id="T1",
                day_idx=0,
                start_min=420,
                end_min=541,
                shift="A",
                qty=100,
                prod_min=60 / 0.66,
                setup_min=30,
                edd=0,
                sku="SKU1",
            )
        ],
        score={
            "otd": 100.0,
            "otd_d": 100.0,
            "tardy_count": 0,
            "setups": 1,
            "earliness_avg_days": 0.0,
            "early_window_violations": 0,
        },
        time_ms=1,
        warnings=[],
        operator_alerts=[],
        gate_report={
            "status": "applicable",
            "apply_decision": "auto_applicable",
            "physical_gate_passed": True,
            "coverage_gate_passed": True,
            "requires_approval": False,
            "approval_reasons": [],
            "metrics": {},
        },
    )
    return engine, config, result


def test_parse_upload_uses_current_factory_twin_classifications(
    tmp_path,
    monkeypatch,
):
    engine, config, _result = load_fixture()
    second = copy.deepcopy(engine.ops[0])
    second.id = "OP2"
    second.sku = "SKU2"
    second.eco_lot = 200
    engine.ops.append(second)
    engine.twin_groups = [
        TwinGroup(
            tool_id="T1",
            machine_id="M1",
            op_id_1="OP1",
            op_id_2="OP2",
            sku_1="SKU1",
            sku_2="SKU2",
            eco_lot_1=0,
            eco_lot_2=200,
        )
    ]
    config.twins = {}
    master_path = tmp_path / "incompol.yaml"
    master_path.write_text("twins:\n  T1: [SKU1, SKU2]\n")

    monkeypatch.setattr("backend.config.loader.load_config", lambda _path: config)
    monkeypatch.setattr(
        "backend.parser.isop_reader.read_isop",
        lambda _path: ([], engine.workdays, False),
    )
    monkeypatch.setattr(
        "backend.transform.transform.transform",
        lambda *_args: copy.deepcopy(engine),
    )

    parsed, parsed_config, _trust, warnings = parse_upload(
        b"fixture",
        "factory.yaml",
        str(master_path),
    )

    assert parsed_config is config
    assert parsed.twin_groups == []
    assert warnings == []


def test_parse_upload_harmonizes_imported_twin_eco_lots(tmp_path, monkeypatch):
    engine, config, _result = load_fixture()
    first = engine.ops[0]
    first.eco_lot = 100
    second = copy.deepcopy(first)
    second.id = "OP2"
    second.sku = "SKU2"
    second.eco_lot = 240
    engine.ops.append(second)
    config.twins = {"T1": [first.sku, second.sku]}
    master_path = tmp_path / "incompol.yaml"
    master_path.write_text("twins:\n  T1: [SKU1, SKU2]\n")

    monkeypatch.setattr("backend.config.loader.load_config", lambda _path: config)
    monkeypatch.setattr(
        "backend.parser.isop_reader.read_isop",
        lambda _path: ([], engine.workdays, False),
    )
    monkeypatch.setattr(
        "backend.transform.transform.transform",
        lambda *_args: copy.deepcopy(engine),
    )

    parsed, parsed_config, _trust, warnings = parse_upload(
        b"fixture", "factory.yaml", str(master_path)
    )

    assert [op.eco_lot_isop for op in parsed.ops] == [100, 240]
    assert [op.eco_lot_effective for op in parsed.ops] == [240, 240]
    assert parsed_config.sku_planning_rules["SKU1"]["eco_lot"] == 240
    assert parsed_config.sku_planning_rules["SKU2"]["eco_lot"] == 240
    assert warnings == [
        "Eco-lote das gémeas T1 harmonizado para 240 (SKU1: 100; SKU2: 240)."
    ]


@pytest.fixture
def loading(tmp_path, monkeypatch):
    engine, config, result = load_fixture()
    store = PlansStore(tmp_path / "plans.db")
    live = CopilotState(
        engine_data=copy.deepcopy(engine),
        config=copy.deepcopy(config),
        plan_revision=7,
        dataset_info={"id": "old", "filename": "old.xlsx"},
        score={"otd": 91.0},
        segments=copy.deepcopy(result.segments),
        lots=copy.deepcopy(result.lots),
        plans_store=store,
        audit_store=AuditStore(":memory:"),
        active_mutations=[{"type": "machine_down", "params": {}}],
    )
    from backend.config.loader import save_config

    config_path = tmp_path / "factory.yaml"
    save_config(config, str(config_path))
    manager = LoadJobManager(live, store, config_path=str(config_path))
    calls = {"parse": 0, "optimize": 0}

    def parse(*_):
        calls["parse"] += 1
        return (
            copy.deepcopy(engine),
            copy.deepcopy(config),
            SimpleNamespace(score=100, gate="full_auto"),
        )

    def optimize(*_, **__):
        calls["optimize"] += 1
        return copy.deepcopy(result)

    monkeypatch.setattr("backend.loading.jobs.parse_upload", parse)
    monkeypatch.setattr("backend.cpo.optimize", optimize)
    harness = SimpleNamespace(
        manager=manager,
        live=live,
        store=store,
        calls=calls,
        result=result,
        optimize=optimize,
        parse=parse,
    )
    yield harness
    manager.executor.shutdown(wait=True, cancel_futures=True)
    store.close()


async def until(manager, job_id, statuses, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job["status"] in statuses:
            return job
        await asyncio.sleep(0.01)
    pytest.fail(f"Task did not reach {statuses}: {manager.get(job_id)}")


async def prepared(manager):
    job = manager.start(b"fixture", "isop.xlsx", str(uuid4()))
    return await until(manager, job["id"], {"prepared"})


def run(manager, scenario):
    async def wrapped():
        try:
            await scenario()
        finally:
            await manager.close()

    asyncio.run(wrapped())


def test_apply_once_and_receipt_survives_restart(loading):
    m = loading.manager

    async def scenario():
        job = await prepared(m)
        before = loading.live.dataset_info
        assert before["id"] == "old"
        assert m.start(b"fixture", "isop.xlsx", job["id"])["id"] == job["id"]
        m.confirm(job["id"], 7, "all_free")
        m.confirm(job["id"], 7, "all_free")
        applied = await until(m, job["id"], {"applied", "failed"})
        assert applied["status"] == "applied", applied
        assert loading.calls == {"parse": 1, "optimize": 1}
        assert loading.live.plan_revision == 8
        assert loading.live.dataset_info["filename"] == "isop.xlsx"
        assert loading.live.active_mutations == []
        assert m.confirm(job["id"], 7, "all_free")["result"] == applied["result"]
        assert m.cancel(job["id"])["status"] == "applied"
        assert len(loading.store.list()) == 1
        saved = loading.store.get(applied["plan_id"])
        assert deserialize_snapshot(saved["payload"])["dataset_info"]["load_job_id"] == job["id"]
        restarted = LoadJobManager(loading.live, loading.store)
        try:
            assert restarted.get(job["id"])["status"] == "applied"
            assert restarted.start(b"fixture", "isop.xlsx", job["id"])["status"] == "applied"
        finally:
            await restarted.close()

    run(m, scenario)


def test_imported_rules_and_warnings_survive_restart(loading):
    from backend.config.loader import load_config
    from backend.plans.transactions import recover_pending_mutations

    m = loading.manager

    async def scenario():
        job = await prepared(m)
        m.inputs[job["id"]].config.sku_planning_rules = {"SKU1": {"eco_lot": 240}}
        m.inputs[job["id"]].warnings = ["Imported twin lots harmonized"]
        m.confirm(job["id"], 7, "all_free")
        applied = await until(m, job["id"], {"applied", "failed"})
        assert applied["status"] == "applied", applied
        assert loading.store.mutation_receipt(f"load:{job['id']}")["status"] == "committed"
        recover_pending_mutations(loading.store)
        saved = deserialize_snapshot(loading.store.get(applied["plan_id"])["payload"])
        assert load_config(m.config_path).sku_planning_rules == saved["config"].sku_planning_rules
        assert "Imported twin lots harmonized" in saved["result"].warnings

    run(m, scenario)


@pytest.mark.parametrize("boundary", ["yaml", "commit"])
def test_import_config_failure_rolls_back_everything(loading, monkeypatch, boundary):
    from pathlib import Path
    from backend.loading import jobs

    m = loading.manager
    original_config = Path(m.config_path).read_bytes()
    original_save = jobs.save_config

    def fail_save(config, path):
        original_save(config, path)
        raise OSError("lost file acknowledgement")

    def fail_commit(*_args, **_kwargs):
        raise OSError("SQLITE_BUSY")

    if boundary == "yaml":
        monkeypatch.setattr(jobs, "save_config", fail_save)
    else:
        monkeypatch.setattr(loading.store, "commit_load", fail_commit)

    async def scenario():
        job = await prepared(m)
        m.inputs[job["id"]].config.sku_planning_rules = {"SKU1": {"eco_lot": 240}}
        m.confirm(job["id"], 7, "all_free")
        await until(m, job["id"], {"failed"})
        assert Path(m.config_path).read_bytes() == original_config
        assert loading.live.plan_revision == 7
        assert loading.live.config.sku_planning_rules == {}
        assert loading.store.list() == []
        assert loading.store.pending_mutations() == []

    run(m, scenario)


def test_planning_timeout_has_actionable_error_and_preserves_plan(loading, monkeypatch):
    from backend.planning_control import PlanningTimeout

    def timeout(*_args, **_kwargs):
        raise PlanningTimeout("Planning deadline expired; candidate not committed.")

    monkeypatch.setattr("backend.cpo.optimize", timeout)

    async def scenario():
        job = await prepared(loading.manager)
        loading.manager.confirm(job["id"], 7, "all_free")
        failed = await until(loading.manager, job["id"], {"failed"})
        assert failed["error"]["code"] == "planning_timeout"
        assert "tempo disponível" in failed["error"]["message"]
        assert loading.live.plan_revision == 7
        assert loading.live.dataset_info["id"] == "old"
        assert loading.store.list() == []

    run(loading.manager, scenario)


def test_approval_reuses_candidate_and_requires_reason_author(loading):
    m = loading.manager
    loading.result.gate_report.update(
        status="best_effort",
        apply_decision="approval_required",
        requires_approval=True,
        approval_reasons=["delivery_risk"],
    )

    async def scenario():
        job = await prepared(m)
        m.confirm(job["id"], 7, "all_free")
        await until(m, job["id"], {"awaiting_approval"})
        assert loading.live.plan_revision == 7
        with pytest.raises(LoadJobError, match="motivo e autor"):
            m.approve(job["id"], 7, reason="", author="")
        m.approve(job["id"], 7, reason="Risco aceite", author="planeador")
        m.approve(job["id"], 7, reason="Risco aceite", author="planeador")
        applied = await until(m, job["id"], {"applied", "failed"})
        assert applied["status"] == "applied", applied
        assert loading.calls["optimize"] == 1
        assert loading.live.approvals[0]["reason"] == "Risco aceite"
        assert loading.live.approvals[0]["approval_reasons"] == ["delivery_risk"]

    run(m, scenario)


@pytest.mark.parametrize("reason", ["invalid_physics", "jit_window_blocked"])
def test_blocked_plan_cannot_be_approved(loading, reason):
    m = loading.manager
    loading.result.gate_report.update(
        status=reason, apply_decision="blocked", approval_reasons=[reason]
    )

    async def scenario():
        job = await prepared(m)
        m.confirm(job["id"], 7, "all_free")
        blocked = await until(m, job["id"], {"blocked"})
        assert blocked["gate_report"]["apply_decision"] == "blocked"
        with pytest.raises(LoadJobError):
            m.approve(job["id"], 7, reason="override", author="test")
        assert loading.live.dataset_info["id"] == "old"
        assert loading.store.list() == []

    run(m, scenario)


@pytest.mark.parametrize("action", ["cancel", "revision", "config"])
def test_changes_during_calculation_never_replace_the_live_plan(loading, monkeypatch, action):
    m = loading.manager
    release = threading.Event()
    entered = threading.Event()

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return loading.optimize(*args, **kwargs)

    monkeypatch.setattr("backend.cpo.optimize", slow)

    async def scenario():
        job = await prepared(m)
        m.confirm(job["id"], 7, "all_free")
        while not entered.is_set():
            await asyncio.sleep(0.01)
        if action == "cancel":
            assert m.cancel(job["id"])["status"] == "cancelled"
        elif action == "revision":
            loading.live.plan_revision += 1
        else:
            loading.live.config.machines["M1"].active = False
        release.set()
        await until(m, job["id"], {"cancelled", "stale"})
        await asyncio.sleep(0.05)
        assert loading.live.dataset_info["id"] == "old"
        assert loading.store.list() == []

    try:
        run(m, scenario)
    finally:
        release.set()


def test_persistence_failure_rolls_back_snapshot_and_preserves_live_state(loading):
    m = loading.manager
    # Fail after the snapshot INSERT, when updating its receipt.
    loading.store._conn.execute("""CREATE TRIGGER fail_load_receipt BEFORE UPDATE ON load_jobs
        WHEN NEW.status='applied' BEGIN SELECT RAISE(ABORT, 'test disk failure'); END;""")

    async def scenario():
        job = await prepared(m)
        m.confirm(job["id"], 7, "all_free")
        failure = await until(m, job["id"], {"failed"})
        assert failure["error"]["code"] == "application_failed"
        assert loading.live.dataset_info["id"] == "old"
        assert loading.live.plan_revision == 7
        assert loading.store.list() == []

    run(m, scenario)


def test_upload_identity_and_one_active_load(loading):
    m = loading.manager

    async def scenario():
        job = await prepared(m)
        with pytest.raises(LoadJobError) as conflict:
            m.start(b"different", "isop.xlsx", job["id"])
        assert conflict.value.detail["code"] == "different_input"
        with pytest.raises(LoadJobError) as busy:
            m.start(b"fixture", "second.xlsx", str(uuid4()))
        assert busy.value.detail["job_id"] == job["id"]
        with pytest.raises(LoadJobError):
            m.confirm(job["id"], 7, "manual")
        assert loading.calls["optimize"] == 0

    run(m, scenario)


def test_restart_marks_unfinished_jobs_interrupted(loading):
    m = loading.manager

    async def scenario():
        job = await prepared(m)
        await m.close()
        restarted = LoadJobManager(loading.live, loading.store)
        try:
            recovered = restarted.get(job["id"])
            assert recovered["status"] == "failed"
            assert recovered["error"]["code"] == "interrupted"
            assert loading.live.dataset_info["id"] == "old"
        finally:
            await restarted.close()

    run(m, scenario)


@pytest.mark.parametrize("action", ["cancel", "revision", "file_config"])
def test_final_check_after_analytics_preserves_concurrent_changes(
    loading,
    monkeypatch,
    tmp_path,
    action,
):
    m = loading.manager
    master = tmp_path / "master.yaml"
    master.write_text("version: 1")
    m.master_path = str(master)
    entered, release = threading.Event(), threading.Event()

    def analytics(_staged):
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(CopilotState, "_refresh_analytics", analytics)

    async def scenario():
        job = await prepared(m)
        m.confirm(job["id"], 7, "all_free")
        while not entered.is_set():
            await asyncio.sleep(0.01)
        if action == "cancel":
            m.cancel(job["id"])
        elif action == "revision":
            loading.live.plan_revision += 1
        else:
            master.write_text("version: 2")
        release.set()
        await until(m, job["id"], {"cancelled", "stale"})
        await asyncio.sleep(0.05)
        assert loading.store.list() == []
        assert loading.live.dataset_info["id"] == "old"

    try:
        run(m, scenario)
    finally:
        release.set()


def test_approval_rechecks_revision(loading):
    m = loading.manager
    loading.result.gate_report.update(
        apply_decision="approval_required",
        requires_approval=True,
        approval_reasons=["delivery_risk"],
    )

    async def scenario():
        job = await prepared(m)
        m.confirm(job["id"], 7, "all_free")
        await until(m, job["id"], {"awaiting_approval"})
        loading.live.plan_revision += 1
        response = m.approve(job["id"], 7, reason="Aceite", author="planeador")
        assert response["status"] == "stale"
        assert loading.live.dataset_info["id"] == "old"
        assert loading.calls["optimize"] == 1

    run(m, scenario)


def test_committed_receipt_recovers_failed_acknowledgement_and_restart(loading, monkeypatch):
    from backend.config.loader import load_config
    from backend.plans.transactions import recover_pending_mutations

    m = loading.manager
    commit = loading.store.commit_load

    def commit_then_interrupt(*args, **kwargs):
        commit(*args, **kwargs)
        raise RuntimeError("simulate failed acknowledgement after the durable transaction")

    monkeypatch.setattr(loading.store, "commit_load", commit_then_interrupt)

    async def scenario():
        job = await prepared(m)
        m.inputs[job["id"]].config.sku_planning_rules = {"SKU1": {"eco_lot": 240}}
        m.confirm(job["id"], 7, "all_free")
        receipt = await until(m, job["id"], {"applied"})
        # A durable receipt publishes the same candidate once even when the
        # commit acknowledgement fails; startup also has that exact snapshot.
        assert loading.live.dataset_info["id"] == receipt["result"]["dataset"]["id"]
        assert loading.live.plan_revision == 8
        assert m.active_id is None
        snapshot = loading.store.latest()
        assert snapshot["id"] == receipt["plan_id"]
        restored = deserialize_snapshot(snapshot["payload"])
        assert restored["dataset_info"]["id"] == receipt["result"]["dataset"]["id"]
        assert restored["plan_revision"] == 8
        recover_pending_mutations(loading.store)
        assert load_config(m.config_path).sku_planning_rules == {"SKU1": {"eco_lot": 240}}
        restarted = LoadJobManager(loading.live, loading.store)
        try:
            assert restarted.get(job["id"])["status"] == "applied"
            assert restarted.start(b"fixture", "isop.xlsx", job["id"])["status"] == "applied"
            assert len(loading.store.list()) == 1
        finally:
            await restarted.close()

    run(m, scenario)


def test_legacy_loader_uses_jobs_and_requires_explicit_initial_state(loading, monkeypatch):
    monkeypatch.setattr(data_api, "state", loading.live)
    app = FastAPI()
    app.include_router(data_api.router)
    app.state.load_jobs = loading.manager
    with TestClient(app) as client:
        try:
            job_id = str(uuid4())
            files = {"file": ("legacy.xlsx", b"fixture")}
            refused = client.post("/api/data/load", params={"expected_revision": 7}, files=files)
            assert refused.status_code == 409
            params = {"expected_revision": 7, "assume_machines_free": True}
            response = client.post(
                "/api/data/load", params=params, data={"request_id": job_id}, files=files
            )
            assert response.status_code == 202
            invalid_approval = client.post(
                f"/api/data/load/jobs/{job_id}/approve",
                json={"expected_revision": 7, "approval_reason": None, "approval_author": None},
            )
            assert invalid_approval.status_code == 400
            applied = client.portal.call(until, loading.manager, job_id, {"applied", "failed"})
            assert applied["status"] == "applied", applied
            retry = client.post(
                "/api/data/load", params=params, data={"request_id": job_id}, files=files
            )
            assert retry.status_code == 202
            assert retry.json()["job"]["result"] == applied["result"]
            assert loading.calls == {"parse": 1, "optimize": 1}
        finally:
            client.portal.call(loading.manager.close)


def test_phase_observations_are_scoped_to_the_current_worker():
    from backend.telemetry import measured, observe_phases

    observations = []

    @measured("construction")
    def calculate():
        return 42

    assert calculate() == 42
    with observe_phases(lambda *event: observations.append(event)):
        other = threading.Thread(target=calculate)
        other.start()
        other.join()
        assert observations == []
        assert calculate() == 42
    assert [event[:2] for event in observations] == [
        ("construction", "start"),
        ("construction", "end"),
    ]
    assert observations[-1][2] >= 0


@pytest.mark.parametrize(
    "hold_seconds",
    [
        0.1,
        pytest.param(
            151,
            marks=pytest.mark.skipif(
                os.getenv("INCOMPOL_LONG_LOAD_TEST") != "1",
                reason="151-second acceptance test, opt in explicitly",
            ),
        ),
    ],
)
def test_http_remains_responsive_during_slow_calculation(loading, monkeypatch, hold_seconds):
    m = loading.manager
    entered = threading.Event()

    def slow(*args, **kwargs):
        entered.set()
        time.sleep(hold_seconds)
        return loading.optimize(*args, **kwargs)

    monkeypatch.setattr("backend.cpo.optimize", slow)
    monkeypatch.setattr(data_api, "state", loading.live)
    app = FastAPI()
    app.include_router(data_api.router)
    app.state.load_jobs = m
    with TestClient(app) as client:
        try:
            job_id = str(uuid4())
            t0 = time.monotonic()
            response = client.post(
                "/api/data/load/prepare",
                data={"request_id": job_id},
                files={"file": ("isop.xlsx", b"fixture")},
            )
            assert response.status_code == 202
            assert time.monotonic() - t0 < 2
            client.portal.call(until, m, job_id, {"prepared"})
            t0 = time.monotonic()
            response = client.post(
                "/api/data/load/confirm",
                json={"token": job_id, "expected_revision": 7, "mode": "all_free"},
            )
            assert response.status_code == 202
            assert time.monotonic() - t0 < 2
            assert entered.wait(2)
            deadline = time.monotonic() + hold_seconds
            while time.monotonic() < deadline:
                t0 = time.monotonic()
                job = client.get(f"/api/data/load/jobs/{job_id}").json()["job"]
                score = client.get("/api/data/score")
                assert time.monotonic() - t0 < 2
                if job["status"] == "running":
                    assert score.json()["otd"] == 91.0
                time.sleep(min(0.05 if hold_seconds < 1 else 1, hold_seconds))
            applied = client.portal.call(until, m, job_id, {"applied", "failed"})
            assert applied["status"] == "applied", applied
        finally:
            client.portal.call(m.close)
