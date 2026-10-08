"""Recalculation from D0 is explicit, not a client-controlled history bypass."""

import copy
from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from backend.api import data as data_api
from backend.plans import frozen
from backend.plans.serialize import _finalize_snapshot, serialize_snapshot
from backend.planning_control import PlanningCancelled, PlanningTimeout
from backend.types import CurrentMachineState, PlanAnchor
from tests import test_frozen_planning as frozen_fixtures
from tests import test_plan_transactions as transaction_fixtures
from tests import test_recompute_approval_identity as approval_fixtures


@pytest.fixture
def frozen_plan():
    return frozen_fixtures.frozen_plan.__wrapped__()


@pytest.fixture
def planning(tmp_path, monkeypatch):
    yield from transaction_fixtures.planning.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def services(tmp_path, monkeypatch):
    yield from approval_fixtures.services.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def compact(services, monkeypatch):
    return approval_fixtures.compact.__wrapped__(services, monkeypatch)


@pytest.fixture
def client(services):
    return approval_fixtures.client.__wrapped__(services)


@pytest.mark.parametrize("anchored", [False, True])
def test_full_compaction_releases_planned_history_only(frozen_plan, monkeypatch, anchored):
    data, config, baseline = frozen_plan
    data.preserved_lot_proofs = {"L1": {"old": "date-derived"}}
    baseline.preserved_lot_proofs = copy.deepcopy(data.preserved_lot_proofs)
    if anchored:
        data.plan_anchors = [PlanAnchor("L1", "M1", "2026-09-16T07:30", "fixed", "test")]
    before = copy.deepcopy((data, baseline))
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)

    def improve(result, engine, original, cfg, segments, lots, freeze_day, **kwargs):
        assert freeze_day == 0
        assert engine.preserved_lot_proofs == original.preserved_lot_proofs == {}
        assert result.preserved_lot_proofs == {}
        assert {lot.id for lot in lots} == ({"L1"} if anchored else set())
        assert engine.plan_anchors == data.plan_anchors
        return result, {"moves_accepted": 0}

    monkeypatch.setattr(frozen, "improve_preserving_protected_lots", improve)
    monkeypatch.setattr("backend.scheduler.validation.assert_plan_valid", lambda *_a, **_k: None)
    frozen.compact_preserving_started_lots(data, config, baseline, recalculate_from_start=True)
    assert (data, baseline) == before


def test_full_optimizer_has_no_elapsed_reservations_or_stale_proofs(frozen_plan, monkeypatch):
    data, config, baseline = frozen_plan
    data.preserved_lot_proofs = {"L1": {"old": "date-derived"}}
    baseline.preserved_lot_proofs = copy.deepcopy(data.preserved_lot_proofs)
    before = copy.deepcopy((data, baseline))
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)
    monkeypatch.setattr("backend.scheduler.validation.assert_plan_valid", lambda *_a, **_k: None)
    monkeypatch.setattr("backend.scheduler.gates.build_gate_report", lambda *_a, **_k: {
        "physical_gate_passed": True, "coverage_gate_passed": True,
    })
    monkeypatch.setattr(frozen, "improve_preserving_protected_lots",
                        lambda result, *_a, **_k: (result, {"moves_accepted": 0}))

    def solve(engine, **kwargs):
        assert not engine.preserved_lot_proofs
        assert not engine.committed_supplies
        assert not engine.machine_blocked_days.get("M1")
        return copy.deepcopy(baseline)

    result = frozen.optimize_preserving_started_lots(
        data, config, baseline, optimizer=solve, recalculate_from_start=True,
    )
    assert result.preserved_lot_proofs == {}
    assert (data, baseline) == before


@pytest.mark.parametrize("error", [PlanningCancelled, PlanningTimeout])
def test_full_recalculation_interruption_leaves_source_intact(frozen_plan, error):
    data, config, baseline = frozen_plan
    before = copy.deepcopy((data, baseline))

    def solve(engine, **kwargs):
        engine.ops[0].d[0] += 100
        raise error("interrupted")

    with pytest.raises(error):
        frozen.optimize_preserving_started_lots(
            data, config, baseline, optimizer=solve, recalculate_from_start=True,
        )
    assert (data, baseline) == before


def _dated_active(planning):
    today = datetime.now(ZoneInfo("Europe/Lisbon")).date()
    planning.state.engine_data.workdays = [(today + timedelta(days=d)).isoformat() for d in (-1, 0)]
    for anchor in planning.state.engine_data.plan_anchors:
        anchor.start_at = planning.state.engine_data.workdays[0] + "T07:30"
    baseline = serialize_snapshot(planning.state)
    planning.store.save(name="Before", source="auto", origin="isop.xlsx", note="baseline",
                        payload=baseline, score=baseline["score"], gate_report=baseline["gate_report"],
                        is_auto=True, activate=True)
    candidate = copy.deepcopy(baseline)
    candidate["segments"][0]["start_min"] += 10
    candidate["segments"][0]["end_min"] += 10
    candidate["plan_revision"] += 1
    _finalize_snapshot(candidate)
    return baseline, candidate


def test_full_recalculation_durable_commit_and_restart(planning):
    _, candidate = _dated_active(planning)
    planning.store.prepare_mutation("full", "fingerprint", {
        "plan_revision": 8, "recalculate_from_start": True,
    })
    planning.store.commit_mutation("full", candidate, {"plan_revision": 8}, source="auto",
                                   recalculate_from_start=True)
    assert planning.store.active()["payload"] == candidate
    assert planning.store.mutation_receipt("full")["status"] == "committed"
    from backend.plans.store import PlansStore

    restored = PlansStore(planning.database_path)
    try:
        assert restored.active()["payload"] == candidate
    finally:
        restored.close()


def test_recalculation_requires_server_journal_not_payload_flag(planning):
    baseline, candidate = _dated_active(planning)
    candidate["recalculate_from_start"] = True
    planning.store.prepare_mutation("forged", "fingerprint", {"plan_revision": 8})
    with pytest.raises(ValueError, match="recalculation_scope"):
        planning.store.commit_mutation("forged", candidate, {}, source="auto",
                                       recalculate_from_start=True)
    assert planning.store.active()["payload"] == baseline


def test_recalculation_cannot_remove_a_manual_anchor(planning):
    planning.state.engine_data.plan_anchors = [PlanAnchor("LOT1", "M1", "2026-03-17T07:30")]
    baseline, candidate = _dated_active(planning)
    candidate["engine_data"]["plan_anchors"] = []
    _finalize_snapshot(candidate)
    planning.store.prepare_mutation("anchor", "fingerprint", {
        "plan_revision": 8, "recalculate_from_start": True,
    })
    with pytest.raises(ValueError, match="recalculation_context"):
        planning.store.commit_mutation("anchor", candidate, {}, source="auto",
                                       recalculate_from_start=True)
    assert planning.store.active()["payload"] == baseline


def test_recalculation_cannot_discard_observed_machine_state(planning):
    planning.state.engine_data.current_machine_states = [CurrentMachineState("M1", "idle")]
    baseline, candidate = _dated_active(planning)
    candidate["engine_data"]["current_machine_states"] = []
    _finalize_snapshot(candidate)
    planning.store.prepare_mutation("observed", "fingerprint", {
        "plan_revision": 8, "recalculate_from_start": True,
    })
    with pytest.raises(ValueError, match="recalculation_context"):
        planning.store.commit_mutation("observed", candidate, {}, source="auto",
                                       recalculate_from_start=True)
    assert planning.store.active()["payload"] == baseline


def test_recalculate_route_sets_scope_for_exact_approval(client, compact, monkeypatch):
    original = data_api._recompute_transactional
    from backend.plans.context import recalculation_from_start

    def calculate(*args, **kwargs):
        assert recalculation_from_start()
        return original(*args, **kwargs)

    monkeypatch.setattr(data_api, "_recompute_transactional", calculate)
    body = {"expected_revision": 7, "compact_active_plan": True, "request_id": "full-recalc"}
    preview = client.post("/api/data/recalculate", json=body)
    assert preview.status_code == 409, preview.text
    candidate_id = preview.json()["detail"]["candidate_id"]
    response = client.post("/api/data/recalculate", json={
        **body, "candidate_id": candidate_id, "approve_exceptions": True,
        "approval_reason": "Reviewed", "approval_author": "test",
    })
    assert response.status_code == 200, response.text
    compact.assert_called_once()


def test_calendar_recompute_does_not_take_scope_from_client(client, monkeypatch):
    from backend.plans.context import recalculation_from_start

    def calculate(*_a, **_k):
        assert not recalculation_from_start()
        return None

    operation = Mock(side_effect=calculate)
    monkeypatch.setattr(data_api, "_recompute_transactional", operation)
    response = client.put("/api/data/config", json={
        "expected_revision": 7, "oee_default": .66, "recalculate_from_start": True,
    })
    assert response.status_code == 200, response.text
    operation.assert_called_once()


def test_final_gate_uses_candidate_protection(services, monkeypatch):
    from backend.copilot.state import state
    from backend.scheduler.types import ScheduleResult
    from tests.test_candidate_api import _plan

    segments, lots = _plan(start=600)
    result = ScheduleResult(segments, lots, {}, 0, [], [], preserved_lot_proofs={})
    state.engine_data.preserved_lot_proofs = {"obsolete": {"old": True}}
    monkeypatch.setattr(frozen, "compact_preserving_started_lots", lambda *_a, **_k: result)

    def check(*args, **kwargs):
        engine = args[3]
        assert engine.preserved_lot_proofs == result.preserved_lot_proofs
        return copy.deepcopy(services.gate)

    monkeypatch.setattr("backend.scheduler.gates.build_gate_report", check)
    monkeypatch.setattr("backend.scheduler.improvement.improvement_gate_summary", lambda *_a, **_k: {})
    data_api._compact_active_schedule(state.config)
    assert state.engine_data.preserved_lot_proofs == {}


def test_real_compaction_moves_past_planned_production_and_keeps_quantities(monkeypatch):
    from backend.scheduler.canonical import production_lot_obligations, result_validation_data
    from backend.scheduler.improvement import production_windows
    from backend.scheduler.validation import validate_plan
    from backend.transform.calendars import apply_calendars

    loaded = transaction_fixtures._loaded_state()
    data, config = loaded.engine_data, loaded.config
    from backend.scheduler.types import ScheduleResult

    baseline = ScheduleResult(copy.deepcopy(loaded.segments), copy.deepcopy(loaded.lots),
                              copy.deepcopy(loaded.score), 0, [], [])
    baseline.segments[0].start_min += 180
    baseline.segments[0].end_min += 180
    apply_calendars(data, config)
    assert not validate_plan(baseline.segments, data, config, lots=baseline.lots)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)
    before = copy.deepcopy((data, baseline))
    kept = frozen.compact_preserving_started_lots(data, config, baseline)
    moved = frozen.compact_preserving_started_lots(data, config, baseline,
                                                  recalculate_from_start=True)
    assert production_windows(kept.segments) == production_windows(baseline.segments)
    assert production_windows(moved.segments)["LOT1"][0] == 450
    assert production_lot_obligations(moved.lots) == production_lot_obligations(baseline.lots)
    view = result_validation_data(data, moved)
    assert not validate_plan(moved.segments, view, config, lots=moved.lots)
    assert (data, baseline) == before


@pytest.mark.parametrize("stale", [True, False])
def test_recalculate_rebuilds_lots_when_protected_durations_are_stale(
    client, compact, monkeypatch, stale,
):
    """After an OEE change, "Recalcular" from D0 cannot compact lots planned
    under the old configuration; it must rebuild them instead of failing."""
    rebuild = Mock(side_effect=lambda config: compact.side_effect(config))
    monkeypatch.setattr(data_api, "_recompute", rebuild)
    monkeypatch.setattr(data_api, "_recalculation_needs_rebuild", lambda _config: stale)
    body = {"expected_revision": 7, "compact_active_plan": True, "request_id": f"recalc-{stale}"}

    response = client.post("/api/data/recalculate", json=body)

    assert response.status_code in (200, 409), response.text
    assert rebuild.call_count == (1 if stale else 0)
    assert compact.call_count == (0 if stale else 1)


def test_accepted_risk_recalculation_then_ordinary_write_freezes_past_placement(monkeypatch):
    """Documents the risk accepted on 07/10/2026 (AGENTS.md §5): with an ISOP
    older than today, "Recalcular" may place production on an elapsed day,
    and the next ordinary write protects it as if it had been executed. The
    UI warns before recalculating with an old ISOP. Changing this behaviour
    must be a deliberate decision that updates this test."""
    from backend.transform.calendars import apply_calendars

    loaded = transaction_fixtures._loaded_state()
    data, config = loaded.engine_data, loaded.config
    from backend.scheduler.types import ScheduleResult

    baseline = ScheduleResult(copy.deepcopy(loaded.segments), copy.deepcopy(loaded.lots),
                              copy.deepcopy(loaded.score), 0, [], [])
    baseline.segments[0].start_min += 180
    baseline.segments[0].end_min += 180
    apply_calendars(data, config)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)
    moved = frozen.compact_preserving_started_lots(data, config, baseline,
                                                  recalculate_from_start=True)
    assert min(s.day_idx for s in moved.segments if s.lot_id == "LOT1") == 0

    _segments, protected, _anchored = frozen._protected_lots(moved, 1, data, config)

    assert "LOT1" in {lot.id for lot in protected}
