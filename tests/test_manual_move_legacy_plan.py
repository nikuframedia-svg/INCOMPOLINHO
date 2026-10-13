"""A Gantt move on a plan saved under an older material contract.

Rehearsal of 11/10/2026: on the legacy revision 123 the move preview spent its
whole budget (52 s) and only then the commit refused the plan with
``LegacyMaterialPlanError``; from then on such a move was refused before any
planning. Since material version 3 (13/10/2026, economic lot = one
production) every older plan obeys the current contract: the move is planned
(the plan is taken over as version 3) and no note asks to recalculate.
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from backend.api.copilot import app
from backend.copilot.state import state
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
    assert not legacy_material_plan(lots, data, CONFIG)
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


def test_move_on_an_older_plan_reaches_the_move_planner(legacy_state, monkeypatch):
    started = []

    def record(**kwargs):
        started.append(kwargs["lot_id"])
        raise RuntimeError("stop after the legacy check")

    monkeypatch.setattr(move_job_manager, "start", record)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post("/api/data/plan/move-preview-jobs", json={
            "lot_id": legacy_state, "target_day": 8, "target_start_min": 420,
            "target_machine": "MACHINE",
        })
    finally:
        client.close()
    assert started == [legacy_state]
    assert "legacy_material_plan" not in response.text


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


def test_plan_view_has_no_legacy_note_for_an_older_plan(legacy_state, monkeypatch):
    from tests.test_stale_isop_notice import _pin_today

    # Today = the ISOP's first day, so no old-ISOP note either
    # (covered in tests/test_stale_isop_notice.py).
    _pin_today(monkeypatch, "2026-10-07")
    client = TestClient(app)
    try:
        response = client.get("/api/data/plan-view")
        assert response.status_code == 200, response.text
        assert response.json()["plan_notices"] == []
    finally:
        client.close()
