"""A Gantt move on a plan saved before per-delivery material is refused at once.

Rehearsal of 11/10/2026: on the legacy revision 123 the move preview spent its
whole budget (52 s) and only then the commit refused the plan with
``LegacyMaterialPlanError``. The preview job, the immediate preview and the
apply now refuse before any planning, with the same Portuguese message.
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from backend.api.copilot import app
from backend.copilot.state import state
from backend.plans import serialize
from backend.plans.manual_move_jobs import manager as move_job_manager
from backend.plans.store import PlansStore
from backend.scheduler.canonical import legacy_material_plan
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import ScheduleResult
from tests.test_legacy_material_plan import CONFIG, _legacy_plan


@pytest.fixture
def legacy_state(tmp_path):
    previous = {key: getattr(state, key) for key in state.__dataclass_fields__}
    store = PlansStore(tmp_path / "legacy-move.db")
    data, segments, lots = _legacy_plan()
    assert legacy_material_plan(lots, data, CONFIG)
    config = copy.deepcopy(CONFIG)
    score = compute_score(segments, lots, data, config=config, include_operational_audit=False)
    state.engine_data = data
    state.config = config
    state.default_config = config
    state.dataset_info = None
    state.active_mutations = []
    state.manual_edits = []
    state.saved_schedule = None
    state.saved_mutations = None
    state.saved_manual_edits = None
    state.plans_store = store
    state.update_schedule(ScheduleResult(
        segments=segments, lots=lots, score=score, time_ms=1, warnings=[], operator_alerts=[],
    ))
    yield lots[0].id
    store.close()
    for key, value in previous.items():
        setattr(state, key, value)


def _assert_legacy_refusal(response):
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "legacy_material_plan"
    assert detail["requires_recalculation"] is True
    message = detail["message"]
    assert message.startswith(
        "Este plano foi calculado antes de o material passar a ser libertado por entrega"
    )
    assert "«Recalcular plano»" in message and "O plano ativo não foi alterado." in message


def test_move_on_a_legacy_plan_is_refused_before_planning(legacy_state, monkeypatch):
    def no_planning(*_args, **_kwargs):
        raise AssertionError("a legacy plan must be refused before planning")

    monkeypatch.setattr("backend.api.manual_plan.move_lot", no_planning)
    monkeypatch.setattr(move_job_manager, "start", no_planning)
    body = {"lot_id": legacy_state, "target_day": 8, "target_start_min": 420,
            "target_machine": "MACHINE"}
    before = serialize.serialize_snapshot(state), state.plan_revision
    client = TestClient(app, raise_server_exceptions=False)
    try:
        _assert_legacy_refusal(client.post("/api/data/plan/move-preview-jobs", json=body))
        _assert_legacy_refusal(client.post("/api/data/plan/move-preview", json=body))
        _assert_legacy_refusal(client.post("/api/data/plan/move-apply", json={
            **body, "preview_job_id": "job-from-before", "expected_revision": state.plan_revision,
        }))
    finally:
        client.close()
    assert (serialize.serialize_snapshot(state), state.plan_revision) == before


def test_current_plan_is_not_refused_as_legacy(legacy_state, monkeypatch):
    """Control: the same request on a current plan reaches the move planner."""
    from backend.scheduler.scheduler import schedule_all
    from tests.test_legacy_material_plan import _scenario

    data = _scenario()
    result = schedule_all(data, config=copy.deepcopy(CONFIG))
    assert not legacy_material_plan(result.lots, data, CONFIG)
    state.engine_data = data
    state.update_schedule(result)
    started = []

    def record(**kwargs):
        started.append(kwargs["lot_id"])
        raise RuntimeError("stop after the legacy check")

    monkeypatch.setattr(move_job_manager, "start", record)
    lot_id = result.lots[0].id
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post("/api/data/plan/move-preview-jobs", json={
            "lot_id": lot_id, "target_day": 8, "target_start_min": 420,
        })
    finally:
        client.close()
    assert started == [lot_id]  # the job was started: no legacy refusal
    assert "legacy_material_plan" not in response.text


def test_plan_view_shows_the_legacy_note_until_the_plan_is_rebuilt(legacy_state):
    """The planner sees why moves are refused (rehearsal: the note stayed in
    ``state.warnings`` only). The note follows the plan, not a stored flag."""
    from backend.scheduler.scheduler import schedule_all
    from tests.test_legacy_material_plan import _scenario

    client = TestClient(app)
    try:
        legacy = client.get("/api/data/plan-view")
        assert legacy.status_code == 200, legacy.text
        notices = legacy.json()["plan_notices"]
        assert len(notices) == 1
        assert notices[0].startswith(
            "Este plano foi calculado antes de o material passar a ser libertado por entrega."
        )
        assert "«Recalcular plano»" in notices[0]

        data = _scenario()
        state.engine_data = data
        state.update_schedule(schedule_all(data, config=copy.deepcopy(CONFIG)))
        current = client.get("/api/data/plan-view")
        assert current.status_code == 200, current.text
        assert current.json()["plan_notices"] == []
    finally:
        client.close()
