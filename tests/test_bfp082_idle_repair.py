"""A preserved lot can use a legal idle slot without changing other lots."""

import copy
import sqlite3
from datetime import date, timedelta

import pytest

from backend.config.types import FactoryConfig
from backend.plans.serialize import (
    _finalize_snapshot, deserialize_snapshot, serialize_result_snapshot,
)
from backend.plans.store import PlansStore
from backend.scheduler.canonical import preserved_lot_proofs
from backend.scheduler.gates import build_gate_report
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.scoring import compute_score
from backend.scheduler.validation import validate_plan
from scripts import repair_bfp082_idle, repair_bfp112_early_start
from tests.test_simulator import _engine, _eop


@pytest.fixture
def idle_snapshot():
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
    second.start_min = 450
    second.end_min = 723
    second.prod_min = 273
    second.setup_min = 0
    second.run_setup_min = 0
    second.qty = 300
    second.run_id = "late-split"
    second.material_release_day = 1
    result.lots[1].material_release_day = 1
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


def test_repair_fills_idle_slot_without_changing_other_lots(idle_snapshot):
    payload, target = idle_snapshot
    before = copy.deepcopy(payload)
    repaired, report = repair_bfp082_idle.repair_payload(
        payload, lot_id=target, first_gap=(1, 420, 450, 1, 450),
    )

    assert payload == before
    assert repaired["plan_revision"] == 10
    assert report["first_start"] == [1, 420]
    assert report["quantity"] == 300
    assert repaired["lots"] == payload["lots"]
    assert repaired["config"] == payload["config"]
    assert [segment for segment in repaired["segments"] if segment["lot_id"] != target] == [
        segment for segment in payload["segments"] if segment["lot_id"] != target
    ]
    assert all(
        repaired["engine_data"]["preserved_lot_proofs"][lot] == proof
        for lot, proof in payload["engine_data"]["preserved_lot_proofs"].items()
        if lot != target
    )


def test_repair_refuses_changed_gap_and_proof(idle_snapshot):
    payload, target = idle_snapshot
    with pytest.raises(ValueError, match="expected retained-tool gap"):
        repair_bfp082_idle.repair_payload(
            payload, lot_id=target, first_gap=(1, 421, 450, 1, 450),
        )
    payload["engine_data"]["preserved_lot_proofs"].pop(target)
    _finalize_snapshot(payload)
    with pytest.raises(ValueError, match="proof"):
        repair_bfp082_idle.repair_payload(
            payload, lot_id=target, first_gap=(1, 420, 450, 1, 450),
        )


def test_commit_failure_preserves_active_plan(tmp_path, monkeypatch, idle_snapshot):
    payload, target = idle_snapshot
    monkeypatch.setattr(repair_bfp082_idle, "LOT_ID", target)
    monkeypatch.setattr(repair_bfp082_idle, "FIRST_GAP", (1, 420, 450, 1, 450))
    original_repair = repair_bfp082_idle.repair_payload
    monkeypatch.setattr(
        repair_bfp082_idle, "repair_payload",
        lambda plan: original_repair(
            plan, lot_id=target, first_gap=(1, 420, 450, 1, 450),
        ),
    )
    store = PlansStore(tmp_path / "plans.db")
    try:
        store.save(
            name="Before", source="auto", origin="", note="", payload=payload,
            score=payload["score"], gate_report=payload["gate_report"],
            is_auto=True, activate=True,
        )
        original = store.active()
        args = {
            "expected_revision": 9,
            "expected_schedule": payload["fingerprints"]["schedule"],
        }
        with pytest.raises(ValueError, match="active plan changed"):
            repair_bfp082_idle.repair_store(
                store, expected_revision=8,
                expected_schedule=payload["fingerprints"]["schedule"],
            )
        store._conn.execute(
            "CREATE TRIGGER fail_repair BEFORE UPDATE ON plan_runtime "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
            repair_bfp082_idle.repair_store(store, **args)
        assert store.active() == original
        assert store.mutation_receipt(repair_bfp082_idle.OPERATION_ID) is None
        store._conn.execute("DROP TRIGGER fail_repair")
        report = repair_bfp082_idle.repair_store(store, **args)
        assert repair_bfp082_idle.repair_store(store, **args) == report
        assert store.active()["payload"]["plan_revision"] == 10
    finally:
        store.close()


def test_early_start_repair_preserves_other_lots_and_rejects_physical_drift(
    monkeypatch, idle_snapshot,
):
    payload, target = idle_snapshot
    candidate, _ = repair_bfp082_idle.repair_payload(
        payload, lot_id=target, first_gap=(1, 420, 450, 1, 450),
    )
    candidate_segments = deserialize_snapshot(candidate)["result"].segments
    monkeypatch.setattr(repair_bfp112_early_start, "EXPECTED_OLD_FIRST", (1, 450))
    monkeypatch.setattr(repair_bfp112_early_start, "EXPECTED_NEW_FIRST", (1, 420))
    monkeypatch.setattr(
        repair_bfp112_early_start, "normalize_earliest_legal_plan",
        lambda *_args: copy.deepcopy(candidate_segments),
    )
    repaired, report = repair_bfp112_early_start.repair_payload(payload, lot_id=target)
    assert report["first_start"] == [1, 420]
    assert report["other_lots_unchanged"] == 1
    assert repaired["plan_revision"] == payload["plan_revision"] + 1
    assert [s for s in repaired["segments"] if s["lot_id"] != target] == [
        s for s in payload["segments"] if s["lot_id"] != target
    ]
    assert repaired["dataset_info"]["n_segments"] == len(repaired["segments"])

    changed = copy.deepcopy(candidate_segments)
    other = next(segment for segment in changed if segment.lot_id != target)
    other.qty += 1
    monkeypatch.setattr(
        repair_bfp112_early_start, "normalize_earliest_legal_plan",
        lambda *_args: changed,
    )
    with pytest.raises(ValueError, match="changed another lot"):
        repair_bfp112_early_start.repair_payload(payload, lot_id=target)
