"""Detached plan writers, SQLite atomicity, and durable mutation recovery."""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
import threading
from datetime import datetime, timedelta
from uuid import UUID
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import yaml
from fastapi import HTTPException

from backend.api import locks
from backend.config import loader
from backend.config.types import FactoryConfig, MachineConfig
from backend.copilot.state import CopilotState, state
from backend.plans import transactions
from backend.plans.context import after_commit, is_staging, redirected_state, stage_state
from backend.plans.serialize import _finalize_snapshot, assert_snapshot_integrity, serialize_snapshot
from backend.plans.store import PlansStore
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.scheduler.validation import PlanValidationError
from backend.types import EngineData, EOp, MachineInfo


def _loaded_state() -> CopilotState:
    """The minimal valid plan shape used by test_plans, without API startup."""
    config = FactoryConfig(
        machines={"M1": MachineConfig("M1", "Grandes")},
        tools={"T1": {"primary": "M1", "setup_hours": 0.5}},
    )
    engine = EngineData(
        ops=[
            EOp(
                id="OP1",
                sku="SKU1",
                client="CLIENT",
                designation="Part",
                m="M1",
                t="T1",
                pH=100,
                sH=0.5,
                operators=1,
                eco_lot=0,
                alt=None,
                stk=100,
                backlog=0,
                d=[100, 0],
                oee=0.66,
                wip=0,
            )
        ],
        machines=[MachineInfo("M1", "Grandes", 1020)],
        twin_groups=[],
        client_demands={},
        workdays=["2026-03-17", "2026-03-18"],
        n_days=2,
    )
    production_minutes = 60 / 0.66
    lot = Lot("LOT1", "OP1", "T1", "M1", None, 100, production_minutes, 30, 0, False, sku="SKU1")
    segment = Segment(
        "LOT1",
        "RUN1",
        "M1",
        "T1",
        0,
        420,
        541,
        "A",
        100,
        production_minutes,
        setup_min=30,
        sku="SKU1",
    )
    loaded = CopilotState(engine_data=engine, config=config, default_config=copy.deepcopy(config))
    loaded.dataset_info = {
        "id": "dataset-1",
        "filename": "isop.xlsx",
        "n_ops": 1,
        "n_segments": 1,
        "trust_score": 100,
        "trust_gate": "full_auto",
        "otd": 100,
        "tardy_count": 0,
    }
    loaded.update_schedule(
        ScheduleResult(
            segments=[segment],
            lots=[lot],
            score={"otd": 100, "otd_d": 100, "setups": 1},
            time_ms=0,
            warnings=[],
            operator_alerts=[],
            gate_report={"status": "applicable", "apply_decision": "apply"},
        )
    )
    loaded.plan_revision = 7
    loaded.approvals = [{"author": "baseline"}]
    loaded.rules = [{"id": "baseline-rule", "value": 1}]
    loaded.learning_info = {"source": "baseline"}
    loaded.prepared_load = {"filename": "prepared.xlsx"}
    loaded.trust_index = {"score": 100}
    loaded.feasibility = {"status": "feasible"}
    loaded.solver_status = "OPTIMAL"
    loaded.schedule_id = "baseline-audit"
    loaded.save_current()
    return loaded


@pytest.fixture
def planning(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "factory.yaml"
    database_path = tmp_path / "plans.db"
    monkeypatch.setattr(loader, "DEFAULT_CONFIG_PATH", str(config_path))
    # save_config historically captures its default at import time. Isolate
    # that destination too; the dedicated path test makes the two disagree.
    monkeypatch.setattr(loader.save_config, "__defaults__", (str(config_path),))
    lock = locks.PlanMutationLock()
    monkeypatch.setattr(locks, "plan_mutation_lock", lock)
    monkeypatch.setattr(transactions, "plan_mutation_lock", lock)
    store = PlansStore(database_path)
    live = _loaded_state()
    live.plans_store = store
    live.audit_store = object()
    monkeypatch.setattr(state, "__dict__", live.__dict__)
    loader.save_config(state.config, path=str(config_path))
    assert_snapshot_integrity(serialize_snapshot(state))
    try:
        yield SimpleNamespace(
            state=state,
            store=store,
            config_path=config_path,
            database_path=database_path,
        )
    finally:
        store.close()


@pytest.mark.parametrize("offsets", [(-1, 0, 1), (-3, -2, -1)])
def test_durable_commit_rejects_retroactive_historical_move(planning, offsets):
    today = datetime.now(ZoneInfo("Europe/Lisbon")).date()
    planning.state.engine_data.workdays = [
        (today + timedelta(days=offset)).isoformat() for offset in offsets
    ]
    baseline = serialize_snapshot(planning.state)
    planning.store.save(
        name="Before", source="auto", origin="isop.xlsx", note="baseline",
        payload=baseline, score=baseline["score"], gate_report=baseline["gate_report"],
        is_auto=True, activate=True,
    )
    before = planning.store.runtime_identity()
    candidate = copy.deepcopy(baseline)
    candidate["segments"][0]["start_min"] += 10
    candidate["segments"][0]["end_min"] += 10
    candidate["plan_revision"] += 1
    _finalize_snapshot(candidate)
    planning.store.prepare_mutation("retroactive", "fingerprint", {"plan_revision": 8})

    with pytest.raises(ValueError, match="historical_plan_protected"):
        planning.store.commit_mutation("retroactive", candidate, {}, source="auto")

    assert planning.store.runtime_identity() == before
    assert planning.store.active()["payload"] == baseline
    planning.store.abort_mutation("retroactive")


@pytest.mark.parametrize("conflict", ["machine_down", "operator_capacity"])
@pytest.mark.parametrize("dataset_identity", [True, False])
def test_stale_gate_cannot_activate_physically_invalid_plan(planning, conflict, dataset_identity):
    baseline = serialize_snapshot(planning.state)
    planning.store.save(
        name="Before", source="auto", origin="isop.xlsx", note="baseline",
        payload=baseline, score=baseline["score"], gate_report=baseline["gate_report"],
        is_auto=True, activate=True,
    )
    before = planning.store.runtime_identity()
    candidate = copy.deepcopy(baseline)
    if conflict == "machine_down":
        candidate["engine_data"]["machine_blocked_days"] = {"M1": [0]}
    else:
        candidate["engine_data"]["operator_blocked_intervals"] = [{
            "group": "Grandes", "shift": "A", "count": 6,
            "start_day": 0, "start_min": 420, "end_day": 0, "end_min": 930,
        }]
    candidate["plan_revision"] += 1
    if not dataset_identity:
        candidate["dataset_info"] = None
    _finalize_snapshot(candidate)
    assert candidate["gate_report"]["apply_decision"] == "apply"

    with pytest.raises(PlanValidationError) as direct:
        planning.store.save(
            name="Invalid", source="auto", origin="isop.xlsx", note="stale gate",
            payload=candidate, score=candidate["score"],
            gate_report=candidate["gate_report"], is_auto=True, activate=True,
        )
    assert any(v["kind"] == conflict for v in direct.value.violations)

    planning.store.prepare_mutation("invalid-machine", "fingerprint", {"plan_revision": 8})
    with pytest.raises(PlanValidationError):
        planning.store.commit_mutation("invalid-machine", candidate, {}, source="auto")
    assert planning.store.runtime_identity() == before
    assert planning.store.active()["payload"] == baseline
    assert planning.store.mutation_receipt("invalid-machine")["status"] == "preparing"
    planning.store.abort_mutation("invalid-machine")

    load = {
        "id": "invalid-load", "filename": "isop.xlsx", "status": "running",
        "result": {"score": candidate["score"]}, "gate_report": candidate["gate_report"],
    }
    planning.store.create_load_job(load, "fingerprint")
    planning.store.prepare_mutation("load:invalid-load", "fingerprint", {"plan_revision": 8})
    with pytest.raises(PlanValidationError):
        planning.store.commit_load(
            {**load, "status": "applied"}, plan_id="invalid-snapshot",
            payload_json=json.dumps(candidate),
        )
    assert planning.store.runtime_identity() == before
    assert planning.store.active()["payload"] == baseline
    assert planning.store.load_job("invalid-load")["status"] == "running"
    assert planning.store.get("invalid-snapshot") is None
    assert planning.store.mutation_receipt("load:invalid-load")["status"] == "preparing"
    planning.store.abort_mutation("load:invalid-load")


def _runtime_values(live=state) -> dict:
    return copy.deepcopy(
        {
            item.name: getattr(live, item.name)
            for item in fields(CopilotState)
            if item.name not in {"plans_store", "audit_store"}
        }
    )


def _mutate(marker: str, *, change_config: bool = False) -> dict:
    state.save_current()
    state.engine_data.ops[0].stk += 1
    state.segments[0].start_min += 5
    state.segments[0].end_min += 5
    state.lots[0].planning_source = marker
    state.plan_revision += 10
    state.dataset_info["marker"] = marker
    state.approvals.append({"author": marker})
    state.active_mutations.append({"type": "test", "params": {"marker": marker}})
    state.manual_edits.append({"lot_id": "LOT1", "reason": marker})
    state.score["marker"] = marker
    state.warnings.append(marker)
    state.journal_entries = [{"marker": marker}]
    state.solver_status = marker
    state.feasibility = {"marker": marker}
    state.gate_report["marker"] = marker
    state.schedule_id = marker
    state.default_config.name = marker
    state.prepared_load["marker"] = marker
    state.trust_index = {"marker": marker}
    state.learning_info = {"marker": marker}
    state.rules[0]["value"] += 1
    for name in (
        "stock_projections",
        "expedition",
        "risk_result",
        "late_deliveries",
        "coverage",
        "order_tracking",
        "stress_map",
        "operator_alerts",
    ):
        setattr(state, name, [{"marker": marker}])
    if change_config:
        state.config.name = marker
    return {"status": "applied", "marker": marker}


def _run(fn, operation_id="operation-1", fingerprint="fingerprint-1"):
    return transactions.run_sync_mutation(
        state,
        fn,
        operation_id=operation_id,
        request_fingerprint=fingerprint,
    )


def test_rule_ids_are_unique_after_deletion_and_persist_with_revision(planning):
    first = state.add_rule({"text": "first"})
    second = state.add_rule({"text": "second"})
    assert state.remove_rule(first)
    third = state.add_rule({"text": "third"})
    assert len({first, second, third}) == 3
    assert all(UUID(value) for value in (first, second, third))
    stored = json.loads(transactions._rules_path().read_text())
    assert stored["rules"] == state.rules
    assert stored["plan_revision"] == state.plan_revision
    assert planning.store.active()["payload"]["plan_revision"] == state.plan_revision


def test_rule_duplicate_migration_is_stable_and_preserves_content(planning):
    legacy = [{"id": "rule_2", "text": "one"}, {"id": "rule_2", "text": "two"}]
    transactions._atomic_text(transactions._rules_path(), json.dumps({"rules": legacy}))
    state._load_rules()
    migrated = copy.deepcopy(state.rules)
    assert migrated[0] == legacy[0]
    assert migrated[1]["text"] == "two"
    assert migrated[1]["id"] != "rule_2"
    state._load_rules()
    assert state.rules == migrated


@pytest.mark.parametrize("failure", ["second_rename", "commit"])
def test_config_and_rules_recover_together(planning, monkeypatch, failure):
    rules_path = transactions._rules_path()
    transactions._atomic_text(rules_path, json.dumps({"rules": state.rules}))
    before = _runtime_values()
    old_rules, old_yaml = rules_path.read_bytes(), planning.config_path.read_bytes()
    replace = transactions.os.replace

    def fail_replace(source, target):
        if Path(target) == rules_path and ".prepared-" in str(source):
            raise OSError("rules rename failed")
        return replace(source, target)

    if failure == "second_rename":
        monkeypatch.setattr(transactions.os, "replace", fail_replace)
    else:
        monkeypatch.setattr(planning.store, "commit_mutation", lambda *a, **k: (_ for _ in ()).throw(OSError("commit failed")))
    with pytest.raises(OSError):
        _run(lambda: _mutate("candidate", change_config=True))
    assert rules_path.read_bytes() == old_rules
    assert planning.config_path.read_bytes() == old_yaml
    assert _runtime_values() == before
    assert not planning.store.pending_mutations()
    assert planning.store.mutation_receipt("operation-1") is None


def test_interrupted_multifile_journal_restores_both_files(planning):
    rules_path = transactions._rules_path()
    original_rules = json.dumps({"rules": state.rules})
    original_yaml = planning.config_path.read_text()
    planning.store.prepare_mutation("crash", "crash", {
        "config_path": str(planning.config_path), "config_changed": True,
        "old_config_text": original_yaml,
        "files": [{"path": str(rules_path), "old_text": original_rules}],
    })
    transactions._atomic_text(planning.config_path, "factory: candidate")
    transactions._atomic_text(rules_path, '{"rules": []}')
    transactions.recover_pending_mutations(planning.store)
    assert planning.config_path.read_text() == original_yaml
    assert rules_path.read_text() == original_rules
    assert not planning.store.pending_mutations()


def _save_snapshot(store, payload):
    return store.save(
        name="Test plan",
        source="auto",
        origin="isop.xlsx",
        note="test",
        is_auto=True,
        payload=payload,
        score=payload["score"],
        gate_report=payload["gate_report"],
    )


def _journal(planning, *, old_text=None):
    return {
        "config_path": str(planning.config_path),
        "config_changed": True,
        "old_config_text": old_text,
    }


def test_clone_detaches_all_runtime_fields_but_shares_service_handles(planning):
    baseline = _runtime_values()
    staged = transactions.clone_state(state)
    assert staged.plans_store is planning.store
    assert staged.audit_store is state.audit_store
    with stage_state(state, staged):
        _mutate("staged", change_config=True)
        state.saved_config.name = "changed-revert"
        state.saved_engine_data.ops[0].stk = 0
        state.saved_schedule.segments[0].qty = 0
        state.saved_mutations.append({"type": "staged-revert"})
        state.saved_manual_edits.append({"reason": "staged-revert"})
    assert _runtime_values() == baseline
    assert staged.config.name == "staged"
    assert staged.saved_config.name == "changed-revert"


def test_singleton_alias_reads_writes_and_methods_redirect_only_in_context(planning):
    alias = state
    unrelated = CopilotState(plan_revision=99)
    baseline = _runtime_values()
    staged = transactions.clone_state(state)
    callbacks = []
    with stage_state(state, staged) as context:
        assert is_staging()
        assert redirected_state(alias) is staged
        assert alias.config is staged.config
        alias.plan_revision = 20
        alias.config.name = "detached"
        alias.save_current()
        assert staged.saved_plan_revision == 20
        assert unrelated.plan_revision == 99
        assert redirected_state(unrelated) is None
        after_commit(lambda: callbacks.append("committed"))
        assert callbacks == []
    assert not is_staging()
    assert redirected_state(alias) is None
    assert _runtime_values() == baseline
    assert len(context.callbacks) == 1
    after_commit(lambda: callbacks.append("immediate"))
    assert callbacks == ["immediate"]


def test_nested_staging_restores_outer_context_even_on_exception(planning):
    outer, inner = transactions.clone_state(state), transactions.clone_state(state)
    baseline = _runtime_values()
    with stage_state(state, outer):
        state.config.name = "outer"
        with pytest.raises(RuntimeError, match="inner failure"):
            with stage_state(state, inner):
                state.config.name = "inner"
                raise RuntimeError("inner failure")
        assert redirected_state(state) is outer
        assert state.config.name == "outer"
    assert not is_staging()
    assert _runtime_values() == baseline


def test_concurrent_writers_publish_once_and_reject_lost_update_with_409(planning):
    baseline = _runtime_values()
    entered = {name: threading.Event() for name in ("winner", "loser")}
    release = {name: threading.Event() for name in entered}
    callbacks = []

    @transactions.plan_writer
    async def writer(body: dict):
        marker = body["marker"]
        response = _mutate(marker)
        after_commit(lambda: callbacks.append(marker))
        entered[marker].set()
        assert release[marker].wait(5), "writer was never released"
        return response

    async def scenario():
        tasks = {
            marker: asyncio.create_task(writer({"request_id": marker, "marker": marker}))
            for marker in entered
        }
        try:
            for event in entered.values():
                assert await asyncio.to_thread(event.wait, 5), "writers did not stage concurrently"
            assert _runtime_values() == baseline
            assert planning.store.list() == []
            release["winner"].set()
            winner = await asyncio.wait_for(tasks["winner"], 5)
            release["loser"].set()
            with pytest.raises(HTTPException) as caught:
                await asyncio.wait_for(tasks["loser"], 5)
            assert caught.value.status_code == 409
            assert caught.value.detail["code"] == "stale_revision"
            assert caught.value.detail["current_revision"] == 8
            assert winner["plan_revision"] == 8
        finally:
            for event in release.values():
                event.set()
            await asyncio.gather(*tasks.values(), return_exceptions=True)

    asyncio.run(scenario())
    assert state.plan_revision == 8
    assert state.dataset_info["marker"] == "winner"
    assert state.score["marker"] == "winner"
    assert state.approvals[-1]["author"] == "winner"
    assert callbacks == ["winner"]
    assert len(planning.store.list()) == 1
    assert planning.store.latest()["payload"]["score"]["marker"] == "winner"
    assert planning.store.mutation_receipt("winner")["status"] == "committed"
    assert planning.store.mutation_receipt("loser") is None
    assert planning.store.pending_mutations() == []


@pytest.mark.parametrize("failure", ["yaml_before_write", "yaml_after_replace", "snapshot_save", "active_pointer"])
def test_save_failure_rolls_back_full_staged_metadata_and_yaml(planning, monkeypatch, failure):
    baseline = _runtime_values()
    original_dict = object.__getattribute__(state, "__dict__")
    original_yaml = planning.config_path.read_bytes()
    saved_config = loader.save_config
    callbacks = []

    def failing_save(config, *args, **kwargs):
        if failure == "yaml_after_replace":
            saved_config(config, path=str(planning.config_path))
        raise OSError("injected save failure")

    def failing_commit(*args, **kwargs):
        assert yaml.safe_load(planning.config_path.read_text())["factory"]["name"] == "candidate"
        raise OSError("injected save failure")

    if failure == "active_pointer":
        planning.store._conn.execute("""CREATE TRIGGER fail_activation BEFORE UPDATE ON plan_runtime
            BEGIN SELECT RAISE(ABORT, 'injected save failure'); END;""")
    elif failure == "snapshot_save":
        monkeypatch.setattr(planning.store, "commit_mutation", failing_commit)
    else:
        monkeypatch.setattr(loader, "save_config", failing_save)

    def mutate():
        result = _mutate("candidate", change_config=True)
        state.saved_config.name = "changed-revert"
        state.saved_engine_data.ops[0].stk = 0
        state.saved_schedule.warnings.append("changed-revert")
        after_commit(lambda: callbacks.append("published"))
        return result

    with pytest.raises((OSError, sqlite3.IntegrityError), match="injected save failure"):
        _run(mutate)
    assert _runtime_values() == baseline
    assert object.__getattribute__(state, "__dict__") is original_dict
    assert planning.config_path.read_bytes() == original_yaml
    assert state.plans_store is planning.store
    assert callbacks == []
    assert planning.store.list() == []
    assert planning.store.pending_mutations() == []
    assert planning.store.mutation_receipt("operation-1") is None
    assert not planning.store._conn.in_transaction
    assert not is_staging()


def test_legacy_persistence_is_suppressed_until_outer_commit(planning, monkeypatch):
    original_yaml = planning.config_path.read_bytes()
    legacy_saves = []
    monkeypatch.setattr(planning.store, "save", lambda **kwargs: legacy_saves.append(kwargs))

    def mutate():
        response = _mutate("candidate", change_config=True)
        loader.save_config(state.config)
        saved = state.persist_current_plan(name="staged", source="auto", is_auto=True)
        assert saved["id"] is None
        assert planning.config_path.read_bytes() == original_yaml
        assert planning.store.list() == []
        return response

    response = _run(mutate)
    assert response["plan_revision"] == 8
    assert legacy_saves == []
    assert len(planning.store.list()) == 1
    assert yaml.safe_load(planning.config_path.read_text())["factory"]["name"] == "candidate"


@pytest.mark.parametrize("operation", ["save", "commit_mutation"])
@pytest.mark.parametrize("fault", ["statement", "commit_denied", "commit_busy"])
def test_store_rolls_back_sql_and_commit_failures(planning, operation, fault):
    store, connection = planning.store, planning.store._conn
    payload = serialize_snapshot(state)
    if operation == "commit_mutation":
        store.prepare_mutation("sql-operation", "sql-fingerprint", {"config_changed": False})

    def write():
        if operation == "save":
            return _save_snapshot(store, payload)
        return store.commit_mutation("sql-operation", payload, {"ok": True}, source="auto")

    reader = None
    rejected = []

    def authorize(action, first, second, _database, _source):
        forbidden = (
            (
                fault == "commit_denied"
                and action == sqlite3.SQLITE_TRANSACTION
                and first == "COMMIT"
            )
            or (
                fault == "statement"
                and operation == "save"
                and action == sqlite3.SQLITE_READ
                and first == "plans"
            )
            or (
                fault == "statement"
                and operation == "commit_mutation"
                and action == sqlite3.SQLITE_UPDATE
                and first == "plan_mutations"
            )
        )
        if forbidden:
            rejected.append((action, first, second))
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    if fault == "commit_busy":
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA busy_timeout=0")
        reader = sqlite3.connect(planning.database_path, timeout=0)
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM plans").fetchall()
    else:
        connection.set_authorizer(authorize)
    try:
        with pytest.raises(sqlite3.DatabaseError) as caught:
            write()
        if fault == "commit_busy":
            assert caught.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
        else:
            assert rejected
    finally:
        connection.set_authorizer(None)
        if reader is not None:
            reader.rollback()
            reader.close()
    assert not connection.in_transaction
    assert store.list() == []
    with sqlite3.connect(planning.database_path) as observer:
        assert observer.execute("SELECT count(*) FROM plans").fetchone()[0] == 0
    if operation == "commit_mutation":
        assert store.mutation_receipt("sql-operation")["status"] == "preparing"
        assert len(store.pending_mutations()) == 1
    write()
    assert len(store.list()) == 1
    assert not connection.in_transaction
    if operation == "commit_mutation":
        assert store.mutation_receipt("sql-operation")["status"] == "committed"
        assert store.pending_mutations() == []


@pytest.mark.parametrize("original_exists", [True, False])
def test_restart_recovers_yaml_replaced_before_snapshot_commit(planning, original_exists):
    if not original_exists:
        planning.config_path.unlink()
    old_text = planning.config_path.read_text() if original_exists else None
    planning.store.prepare_mutation(
        "interrupted", "fingerprint", _journal(planning, old_text=old_text)
    )
    changed = copy.deepcopy(state.config)
    changed.name = "uncommitted"
    loader.save_config(changed, path=str(planning.config_path))
    assert yaml.safe_load(planning.config_path.read_text())["factory"]["name"] == "uncommitted"
    reopened = PlansStore(planning.database_path)
    try:
        assert reopened.pending_mutations()[0]["id"] == "interrupted"
        transactions.recover_pending_mutations(reopened)
        assert reopened.pending_mutations() == []
        assert reopened.mutation_receipt("interrupted") is None
        assert reopened.list() == []
        if original_exists:
            assert planning.config_path.read_text() == old_text
        else:
            assert not planning.config_path.exists()
        transactions.recover_pending_mutations(reopened)
        assert reopened.pending_mutations() == []
    finally:
        reopened.close()


def test_recovery_preserves_yaml_when_committed_receipt_exists(planning):
    old_text = planning.config_path.read_text()
    planning.store.prepare_mutation(
        "committed", "fingerprint", _journal(planning, old_text=old_text)
    )
    staged = transactions.clone_state(state)
    staged.config.name = "committed"
    staged.plan_revision = 8
    loader.save_config(staged.config, path=str(planning.config_path))
    planning.store.commit_mutation(
        "committed",
        serialize_snapshot(staged),
        {"plan_revision": 8},
        source="auto",
    )
    committed_yaml = planning.config_path.read_bytes()
    reopened = PlansStore(planning.database_path)
    try:
        transactions.recover_pending_mutations(reopened)
        assert planning.config_path.read_bytes() == committed_yaml
        assert reopened.mutation_receipt("committed")["status"] == "committed"
        assert reopened.latest()["payload"]["config"]["name"] == "committed"
        assert len(reopened.list()) == 1
    finally:
        reopened.close()


@pytest.mark.parametrize("adapter", ["sync", "async"])
def test_lost_commit_acknowledgement_replays_durable_receipt_once(planning, monkeypatch, adapter):
    original_commit = planning.store.commit_mutation
    calls, projections = [], []

    def commit_then_disconnect(*args, **kwargs):
        original_commit(*args, **kwargs)
        raise OSError("lost COMMIT acknowledgement")

    monkeypatch.setattr(planning.store, "commit_mutation", commit_then_disconnect)

    def mutate():
        calls.append("calculated")
        result = _mutate("committed", change_config=True)
        after_commit(lambda: projections.append(state.plan_revision))
        return result

    @transactions.plan_writer
    async def writer(body: dict):
        return mutate()

    def invoke():
        if adapter == "sync":
            return _run(mutate, "stable-operation", "stable-fingerprint")
        return asyncio.run(writer({"request_id": "stable-operation", "value": 1}))

    first = invoke()
    before_replay = _runtime_values()
    assert first == invoke()
    assert calls == ["calculated"]
    assert projections == [8]
    assert state.plan_revision == 8
    assert _runtime_values() == before_replay
    assert planning.store.mutation_receipt("stable-operation")["response"] == first
    assert planning.store.pending_mutations() == []
    assert len(planning.store.list()) == 1
    reopened = PlansStore(planning.database_path)
    try:
        state.plans_store = reopened
        assert invoke() == first
        assert calls == ["calculated"]
        assert projections == [8]
        assert len(reopened.list()) == 1
        assert reopened.latest()["payload"]["plan_revision"] == 8
    finally:
        state.plans_store = planning.store
        reopened.close()


@pytest.mark.parametrize("adapter", ["sync", "async"])
def test_stable_operation_id_rejects_different_request_fingerprint(planning, adapter):
    calls = []

    def mutate(value):
        calls.append(value)
        return _mutate(str(value))

    @transactions.plan_writer
    async def writer(body: dict):
        return mutate(body["value"])

    def invoke(value):
        if adapter == "sync":
            return _run(lambda: mutate(value), "stable-id", f"fingerprint-{value}")
        return asyncio.run(writer({"request_id": "stable-id", "value": value}))

    invoke(1)
    committed = _runtime_values()
    with pytest.raises(HTTPException) as caught:
        invoke(2)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "different_input"
    assert calls == [1]
    assert _runtime_values() == committed
    assert len(planning.store.list()) == 1


def test_commit_writes_same_config_path_as_recovery_journal(planning, monkeypatch):
    captured_default = planning.config_path.with_name("import-time-default.yaml")
    captured_default.write_text("factory: {name: untouched}\n")
    original = captured_default.read_bytes()
    monkeypatch.setattr(loader.save_config, "__defaults__", (str(captured_default),))
    _run(lambda: _mutate("new-config", change_config=True))
    receipt = planning.store.mutation_receipt("operation-1")
    assert receipt["config_path"] == str(planning.config_path)
    assert yaml.safe_load(planning.config_path.read_text())["factory"]["name"] == "new-config"
    assert captured_default.read_bytes() == original


@pytest.mark.parametrize("adapter", ["sync", "async"])
def test_pending_recovery_journal_blocks_new_writers(planning, adapter):
    old_text = planning.config_path.read_text()
    planning.store.prepare_mutation(
        "interrupted", "fingerprint", _journal(planning, old_text=old_text)
    )
    changed = copy.deepcopy(state.config)
    changed.name = "interrupted"
    loader.save_config(changed, path=str(planning.config_path))
    baseline, before_yaml, calls = _runtime_values(), planning.config_path.read_bytes(), []

    def mutate():
        calls.append("calculated")
        return _mutate("new-change", change_config=True)

    @transactions.plan_writer
    async def writer(body: dict):
        return mutate()

    with pytest.raises(HTTPException) as caught:
        if adapter == "sync":
            _run(mutate, "new-operation", "new-fingerprint")
        else:
            asyncio.run(writer({"request_id": "new-operation"}))
    assert caught.value.status_code == 503
    assert calls == []
    assert _runtime_values() == baseline
    assert planning.config_path.read_bytes() == before_yaml
    assert [item["id"] for item in planning.store.pending_mutations()] == ["interrupted"]
    assert planning.store.list() == []
