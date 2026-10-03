"""The approved legacy repair cannot change an executable production plan."""

import copy
import json
import sqlite3

import pytest

from backend.config.types import FactoryConfig
from backend.plans.serialize import _finalize_snapshot, serialize_result_snapshot
from backend.plans.store import PlansStore
from backend.scheduler.scheduler import schedule_all
from scripts.repair_material_metadata import (
    OPERATION_ID,
    execution_fingerprint,
    repair_payload,
    repair_store,
)
from tests.test_simulator import _engine, _eop


@pytest.fixture
def legacy():
    data = _engine(ops=[_eop(d=[0, 0, 0, 300, 0, 0])])
    config = FactoryConfig()
    result = schedule_all(data, config)
    payload = serialize_result_snapshot(data, config, result, plan_revision=75,
                                        dataset_info={"id": "dataset", "n_ops": 1})
    lot = payload["lots"][0]
    new = lot["material_release_day"]
    changes = {lot["id"]: (new - 3, new)}
    for item in [lot, *payload["segments"]]:
        item["material_release_day"] -= 3
        for output in item["output_milestones"]:
            output["material_release_day"] -= 3
    payload["active_mutations"] = [{"type": "audit-marker", "params": {}}]
    payload["manual_edits"] = [{"note": "preserve"}]
    return _finalize_snapshot(payload), changes


def test_repair_only_changes_approved_material_dates_and_keeps_source_intact(legacy):
    payload, changes = legacy
    before = copy.deepcopy(payload)
    repaired, report = repair_payload(payload, changes)
    assert payload == before
    assert repaired["plan_revision"] == 76
    assert execution_fingerprint(payload) == execution_fingerprint(repaired)
    for key in ("config", "active_mutations", "manual_edits", "dataset_info", "approvals"):
        assert repaired[key] == payload[key]
    for item in [*repaired["lots"], *repaired["segments"]]:
        assert item["material_release_day"] == next(iter(changes.values()))[1]
        assert all(o["material_release_day"] == item["material_release_day"] for o in item["output_milestones"])
    assert report["physical_violations"] == 0


@pytest.mark.parametrize("field", ["qty", "customer_delivery_day", "production_due_day"])
def test_repair_refuses_non_material_obligation_changes(legacy, field):
    payload, changes = legacy
    payload["lots"][0]["output_milestones"][0][field] = 999
    _finalize_snapshot(payload)
    with pytest.raises(ValueError, match="Non-material"):
        repair_payload(payload, changes)


def test_repair_refuses_missing_approval_and_unexpected_segment_dates(legacy):
    payload, changes = legacy
    with pytest.raises(ValueError):
        repair_payload(payload, {})
    payload["segments"][0]["material_release_day"] -= 1
    _finalize_snapshot(payload)
    with pytest.raises(ValueError, match="Unexpected legacy"):
        repair_payload(payload, changes)


def test_repair_keeps_empty_continuation_material_date(legacy):
    payload, changes = legacy
    payload["segments"][0]["material_release_day"] = None
    _finalize_snapshot(payload)
    repaired, _ = repair_payload(payload, changes)
    assert repaired["segments"][0]["material_release_day"] is None
    assert execution_fingerprint(repaired) == execution_fingerprint(payload)


def test_repair_refuses_physical_conflicts_and_preserved_proofs(legacy):
    payload, changes = legacy
    payload["segments"].append(copy.deepcopy(payload["segments"][0]))
    _finalize_snapshot(payload)
    with pytest.raises(ValueError, match="violations"):
        repair_payload(payload, changes)
    payload["engine_data"]["preserved_lot_proofs"] = {"lot": "proof"}
    _finalize_snapshot(payload)
    with pytest.raises(ValueError, match="Historical proofs"):
        repair_payload(payload, changes)


def _seed_legacy_store(store, payload, changes):
    repaired, _ = repair_payload(payload, changes)
    saved = store.save(
        name="Before", source="auto", payload=repaired, activate=True,
        origin="", note="", score=repaired["score"],
        gate_report=repaired["gate_report"], is_auto=True,
    )
    with store._conn:
        store._conn.execute(
            "UPDATE plans SET payload_json=? WHERE id=?",
            (json.dumps(payload), saved["id"]),
        )
        store._conn.execute(
            "UPDATE plan_runtime SET plan_revision=? WHERE singleton=1",
            (payload["plan_revision"],),
        )


def test_repair_is_durable_idempotent_and_protects_expected_identity(tmp_path, legacy):
    payload, changes = legacy
    store = PlansStore(str(tmp_path / "plans.db"))
    try:
        _seed_legacy_store(store, payload, changes)
        args = {"expected_revision": 75, "expected_schedule": payload["fingerprints"]["schedule"],
                "approved_dates": changes}
        with pytest.raises(ValueError, match="changed since approval"):
            repair_store(store, **{**args, "expected_revision": 74})
        report = repair_store(store, **args)
        assert repair_store(store, **args) == report
        assert store.active()["payload"]["plan_revision"] == 76
        assert store.mutation_receipt(OPERATION_ID)["status"] == "committed"
    finally:
        store.close()


def test_failed_snapshot_commit_preserves_active_plan(tmp_path, legacy):
    payload, changes = legacy
    store = PlansStore(str(tmp_path / "plans.db"))
    try:
        _seed_legacy_store(store, payload, changes)
        before = store.runtime_identity()
        store._conn.execute("CREATE TRIGGER fail_repair BEFORE UPDATE ON plan_runtime "
                            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
            repair_store(store, expected_revision=75, expected_schedule=payload["fingerprints"]["schedule"],
                         approved_dates=changes)
        assert store.runtime_identity() == before
        assert store.active()["payload"] == payload
        assert store.mutation_receipt(OPERATION_ID) is None
    finally:
        store.close()
