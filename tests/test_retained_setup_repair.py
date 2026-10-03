"""Legacy setup repair changes accounting, never production or obligations."""

import copy
import sqlite3
from datetime import date, timedelta

import pytest

from backend.config.types import FactoryConfig
from backend.plans.serialize import serialize_result_snapshot
from backend.plans.store import PlansStore
from backend.scheduler.canonical import preserved_lot_proofs
from backend.scheduler.gates import build_gate_report
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.scoring import compute_score
from backend.scheduler.validation import validate_plan
from scripts import repair_retained_setup
from tests.test_simulator import _engine, _eop


def test_retained_cleanup_keeps_both_parts_of_one_required_setup():
    from backend.scheduler.scheduler import _remove_redundant_retained_tool_setups
    from tests.test_manual_move import _segment

    setup = _segment(day=0, start=900, setup=30)
    setup.end_min, setup.prod_min, setup.qty = 930, 0, 0
    setup.run_setup_min = 60
    production = _segment(day=0, start=930, setup=30)
    production.shift = "B"
    production.run_setup_min = 60
    original = copy.deepcopy([setup, production])

    cleaned = _remove_redundant_retained_tool_setups([setup, production])

    assert cleaned == original
    assert sum(item.setup_min for item in cleaned) == 60


def test_retained_cleanup_removes_all_parts_of_a_redundant_setup():
    from backend.scheduler.scheduler import _remove_redundant_retained_tool_setups
    from tests.test_manual_move import _segment

    previous = _segment("PREVIOUS", day=0, start=420, run_id="PREVIOUS-RUN")
    setup = _segment(day=0, start=900, setup=30)
    setup.end_min, setup.prod_min, setup.qty = 930, 0, 0
    setup.run_setup_min = 60
    production = _segment(day=0, start=930, setup=30)
    production.shift = "B"
    production.run_setup_min = 60
    original_window = (production.start_min + production.setup_min, production.end_min)

    cleaned = _remove_redundant_retained_tool_setups([previous, setup, production])

    current = [item for item in cleaned if item.lot_id == production.lot_id]
    assert sum(item.setup_min for item in current) == 0
    assert sum(item.qty for item in current) == production.qty
    assert sum(item.prod_min for item in current) == production.prod_min
    assert [(item.start_min, item.end_min) for item in current] == [original_window]


@pytest.fixture
def legacy():
    data = _engine(ops=[_eop(d=[0, 300, 0, 300, 0, 0])])
    weeks_ahead = max(0, (date.today() - date.fromisoformat(data.workdays[0])).days // 7 + 8)
    data.workdays = [
        (date.fromisoformat(day) + timedelta(weeks=weeks_ahead)).isoformat()
        for day in data.workdays
    ]
    config = FactoryConfig()
    result = schedule_all(data, config)
    target = result.lots[1].id
    second = next(segment for segment in result.segments if segment.lot_id == target)
    second.day_idx = 1
    second.start_min = 420
    second.end_min = 723
    second.prod_min = 273
    second.qty = 300
    second.setup_min = 30
    second.run_setup_min = 30
    second.run_id = "legacy-split"
    result.segments = [
        segment for segment in result.segments if segment.lot_id != target
    ] + [second]
    data.preserved_lot_proofs = preserved_lot_proofs(result.segments, result.lots)
    assert not validate_plan(result.segments, data, config, lots=result.lots)
    result.score = compute_score(result.segments, result.lots, data, config)
    result.gate_report = build_gate_report(
        result.segments, result.lots, result.score, data, config,
    )
    payload = serialize_result_snapshot(
        data, config, result, plan_revision=9,
        dataset_info={"id": "dataset", "n_ops": 1},
    )
    return payload, target


def test_repair_preserves_production_and_rebinds_only_target_proof(legacy):
    payload, target = legacy
    before = copy.deepcopy(payload)
    repaired, report = repair_retained_setup.repair_payload(payload, lot_id=target)
    assert payload == before
    assert repaired["plan_revision"] == 10
    assert report["removed_setup_min"] == 30
    assert report["physical_violations"] == 0
    assert repair_retained_setup.production_fingerprint(payload["segments"]) == (
        repair_retained_setup.production_fingerprint(repaired["segments"])
    )
    assert repaired["lots"] == payload["lots"]
    assert repaired["config"] == payload["config"]
    assert repaired["active_mutations"] == payload["active_mutations"]
    assert repaired["score"]["setups"] == payload["score"]["setups"] - 1
    assert repaired["engine_data"]["preserved_lot_proofs"][target] != (
        payload["engine_data"]["preserved_lot_proofs"][target]
    )
    assert all(
        repaired["engine_data"]["preserved_lot_proofs"][lot] == proof
        for lot, proof in payload["engine_data"]["preserved_lot_proofs"].items()
        if lot != target
    )


def test_repair_requires_matching_historical_proof(legacy):
    payload, target = legacy
    payload["engine_data"]["preserved_lot_proofs"].pop(target)
    from backend.plans.serialize import _finalize_snapshot

    _finalize_snapshot(payload)
    with pytest.raises(ValueError, match="proof"):
        repair_retained_setup.repair_payload(payload, lot_id=target)


def test_repair_refuses_a_productive_move(monkeypatch, legacy):
    payload, target = legacy
    original = repair_retained_setup._remove_redundant_retained_tool_setups

    def moving_cleanup(segments):
        cleaned = original(segments)
        next(segment for segment in cleaned if segment.lot_id == target).end_min += 1
        return cleaned

    monkeypatch.setattr(repair_retained_setup, "_remove_redundant_retained_tool_setups", moving_cleanup)
    with pytest.raises(ValueError, match="Production, resources or obligations"):
        repair_retained_setup.repair_payload(payload, lot_id=target)


def test_store_is_idempotent_and_revision_bound(tmp_path, legacy):
    payload, target = legacy
    store = PlansStore(tmp_path / "plans.db")
    try:
        store.save(
            name="Before", source="auto", origin="", note="", payload=payload,
            score=payload["score"], gate_report=payload["gate_report"],
            is_auto=True, activate=True,
        )
        args = {
            "expected_revision": 9,
            "expected_schedule": payload["fingerprints"]["schedule"],
            "lot_id": target,
        }
        with pytest.raises(ValueError, match="active plan changed"):
            repair_retained_setup.repair_store(store, **{**args, "expected_revision": 8})
        report = repair_retained_setup.repair_store(store, **args)
        assert repair_retained_setup.repair_store(store, **args) == report
        assert store.active()["payload"]["plan_revision"] == 10
        assert store.mutation_receipt(repair_retained_setup.OPERATION_ID)["status"] == "committed"
    finally:
        store.close()


def test_failed_commit_keeps_active_snapshot(tmp_path, legacy):
    payload, target = legacy
    store = PlansStore(tmp_path / "plans.db")
    try:
        store.save(
            name="Before", source="auto", origin="", note="", payload=payload,
            score=payload["score"], gate_report=payload["gate_report"],
            is_auto=True, activate=True,
        )
        before = store.runtime_identity()
        store._conn.execute(
            "CREATE TRIGGER fail_repair BEFORE UPDATE ON plan_runtime "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
            repair_retained_setup.repair_store(
                store, expected_revision=9,
                expected_schedule=payload["fingerprints"]["schedule"], lot_id=target,
            )
        assert store.runtime_identity() == before
        assert store.active()["payload"] == payload
        assert store.mutation_receipt(repair_retained_setup.OPERATION_ID) is None
    finally:
        store.close()


def test_final_scheduler_pass_compacts_time_freed_by_late_setup_cleanup(monkeypatch):
    from backend.scheduler import shift_exchange

    data = _engine(ops=[_eop(d=[0, 300, 0, 300, 0, 0])])
    config = FactoryConfig()

    def late_split(segments, lots, _data, _config):
        result = copy.deepcopy(segments)
        target = lots[1].id
        second = next(segment for segment in result if segment.lot_id == target)
        second.day_idx = 1
        second.start_min = 420
        second.end_min = 723
        second.prod_min = 273
        second.qty = 300
        second.setup_min = 30
        second.run_setup_min = 30
        second.run_id = "late-split"
        return [segment for segment in result if segment.lot_id != target] + [second]

    monkeypatch.setattr(shift_exchange, "repair_shift_capacity_exchange", late_split)
    result = schedule_all(data, config)
    second_segments = [
        segment for segment in result.segments if segment.lot_id == result.lots[1].id
    ]
    assert min((segment.day_idx, segment.start_min) for segment in second_segments) < (1, 450)
    assert all(segment.setup_min == segment.run_setup_min == 0 for segment in second_segments)
    assert not validate_plan(result.segments, data, config, lots=result.lots)
