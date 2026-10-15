"""Version history with names and multi-step «Desfazer» (decisão de 15/10/2026).

Incompol, 15/10/2026: after 8 manual moves the planner could not get back to
the morning plan. «Desfazer» undid one step only (a single copy in memory),
every automatic version in «Planos» was called «Plano aplicado» (revision 148
could not be told apart from 149-158) and only the 20 most recent were kept.
Now each version says what changed, records the version before it, and
«Desfazer» walks back that chain through «Repor» (same protections).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.api.copilot import app
from backend.config import loader
from backend.copilot.state import state
from backend.plans import history
from backend.plans.serialize import serialize_snapshot
from backend.plans.store import HISTORY_KEEP_STEPS, HistoricalPlanProtectedError, PlansStore
from backend.scheduler.gates import build_gate_report
from backend.scheduler.types import ScheduleResult
from tests import test_manual_move as move_fixtures
from tests.test_plan_transactions import _loaded_state


def _future_workdays(count: int) -> list[str]:
    day, days = date.today() + timedelta(days=7), []
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    return days


@pytest.fixture
def plan_api(tmp_path: Path, monkeypatch):
    """One lot (SKU1) on M1, day 0, in the future; an initial active version."""
    config_path = tmp_path / "factory.yaml"
    monkeypatch.setattr(loader, "DEFAULT_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(loader.save_config, "__defaults__", (str(config_path),))
    previous = {key: getattr(state, key) for key in state.__dataclass_fields__}
    store = PlansStore(tmp_path / "history.db")
    data = move_fixtures._engine(demand_day=3)
    data.workdays = _future_workdays(4)
    config = move_fixtures._config()
    lots = [move_fixtures._lot(edd=3)]
    lots[0].sku = "SKU1"  # as in a real plan: names and causes show the reference
    segments = [move_fixtures._segment(edd=3)]
    score = move_fixtures._baseline(data, config, segments, lots)
    result = ScheduleResult(
        segments=segments, lots=lots, score=score, time_ms=1, warnings=[],
        operator_alerts=[], gate_report=build_gate_report(segments, lots, score, data, config),
    )
    state.engine_data, state.config, state.default_config = data, config, config
    state.dataset_info = None
    state.active_mutations, state.manual_edits, state.approvals = [], [], []
    state.saved_schedule = state.saved_mutations = state.saved_manual_edits = None
    state.plans_store = store
    state.update_schedule(result)
    loader.save_config(config, path=str(config_path))
    initial = store.save(
        name="Plano da manhã", source="auto", origin="", note="", payload=serialize_snapshot(state),
        score=state.score, gate_report=state.gate_report, is_auto=True, activate=True,
    )
    yield SimpleNamespace(store=store, initial=initial, client=TestClient(app))
    store.close()
    for key, value in previous.items():
        setattr(state, key, value)


def _placement():
    return sorted(
        (s.lot_id, s.machine_id, s.day_idx, s.start_min, s.end_min, s.qty)
        for s in state.segments
    )


def _move(client, machine: str, day: int) -> dict:
    # A replan («Soltar», «Recalcular») may rebuild the lot under a new id.
    body = {"lot_id": state.lots[0].id, "target_day": day, "target_machine": machine}
    preview = client.post("/api/data/plan/move-preview", json=body)
    assert preview.status_code == 200, preview.text
    applied = client.post("/api/data/plan/move-apply", json={
        **body, "candidate_id": preview.json()["candidate_id"],
        "expected_revision": state.plan_revision, "confirm_delivery_risk": True,
        "reason": "teste", "author": "pytest",
    })
    assert applied.status_code == 200, applied.text
    return applied.json()


def _undo(client):
    return client.post("/api/data/undo", json={"expected_revision": state.plan_revision})


def _active(store) -> dict:
    return store.active()


def _undo_view(client) -> dict:
    view = client.get("/api/data/plan-view")
    assert view.status_code == 200, view.text
    return view.json()["undo"]


def test_three_moves_then_three_undos_return_to_the_starting_plan(plan_api):
    client, store = plan_api.client, plan_api.store
    start = _placement()
    labels = []
    for machine, day in (("M2", 1), ("M1", 2), ("M2", 0)):
        response = _move(client, machine, day)
        active = _active(store)
        # The name says what changed: reference, machine, date and time, no lot id.
        when = history.day_month(state.engine_data.workdays[day])
        assert active["name"].startswith(f"Movido Referência SKU1 · T1 ({machine}) → {when} ")
        assert "LOT1" not in active["name"]
        assert response["edit"]["previous_version_id"] == active["previous_snapshot_id"]
        labels.append(active["name"])
        assert _undo_view(client) == {"available": True, "label": active["name"]}
    assert _placement() != start

    for expected in reversed(labels):
        undone = _undo(client)
        assert undone.status_code == 200, undone.text
        assert undone.json()["undone"] == expected
        assert _active(store)["name"] == f"Desfeito: {expected}"
    assert _placement() == start
    assert state.manual_edits == []
    assert state.engine_data.plan_anchors == []
    # The chain ends at the morning plan: nothing before it to undo.
    assert _undo_view(client) == {"available": False, "label": ""}
    nothing = _undo(client)
    assert nothing.status_code == 409
    assert nothing.json()["detail"]["code"] == "nothing_to_undo"


def test_previous_version_of_a_manual_move_is_the_active_version_before_it(plan_api):
    response = _move(plan_api.client, "M2", 1)
    assert response["edit"]["previous_version_id"] == plan_api.initial["id"]
    assert state.manual_edits[0]["previous_version_id"] == plan_api.initial["id"]
    assert _active(plan_api.store)["previous_snapshot_id"] == plan_api.initial["id"]
    listed = {plan["id"]: plan for plan in plan_api.store.list()}
    assert listed[_active(plan_api.store)["id"]]["previous_snapshot_id"] == plan_api.initial["id"]


def test_undo_that_would_change_started_production_is_refused_with_causes(
    plan_api, monkeypatch,
):
    _move(plan_api.client, "M2", 1)
    before = (_placement(), state.plan_revision, _active(plan_api.store)["id"])
    monkeypatch.setattr(
        "backend.plans.frozen.historical_schedule_changes", lambda *_a, **_k: ["LOT1"],
    )
    refused = _undo(plan_api.client)
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "historical_plan_protected"
    assert "Não é possível desfazer «Movido Referência SKU1 · T1 (M2)" in detail["message"]
    assert detail["causes"] and "Referência SKU1" in detail["causes"][0]
    assert "LOT1" not in detail["message"] + " ".join(detail["causes"])
    assert (_placement(), state.plan_revision, _active(plan_api.store)["id"]) == before


def test_commit_refusal_of_protected_history_carries_its_causes():
    from backend.plans.transactions import _commit_refusal

    refusal = _commit_refusal(
        HistoricalPlanProtectedError(["LOT_X"], ["Referência 6800016767A.10 (PRM043)"]), 9,
    )
    assert refusal.status_code == 409
    assert refusal.detail["causes"] == [
        "Referência 6800016767A.10 (PRM043): a produção já começou ou é anterior "
        "a agora e ficaria diferente."
    ]


def test_recalculate_release_and_holiday_name_their_versions(plan_api):
    client, store = plan_api.client, plan_api.store
    _move(client, "M2", 1)
    released = client.post("/api/data/manual-edits/release", json={
        "lot_ids": [state.lots[0].id], "expected_revision": state.plan_revision,
    })
    assert released.status_code == 200, released.text
    assert _active(store)["name"].startswith("Lote solto: Referência SKU1")

    _move(client, "M2", 1)
    everything = client.post("/api/data/manual-edits/release", json={
        "expected_revision": state.plan_revision,
    })
    assert everything.status_code == 200, everything.text
    assert _active(store)["name"] == "Todos os lotes soltos"

    recalculated = client.post("/api/data/recalculate", json={
        "expected_revision": state.plan_revision,
    })
    assert recalculated.status_code == 200, recalculated.text
    assert _active(store)["name"] == "Recalcular plano"
    assert _active(store)["kind"] == "recalculate"

    holiday = state.engine_data.workdays[2]
    body = {"from": holiday, "to": holiday, "expected_revision": state.plan_revision}
    added = client.post("/api/data/holidays/range", json=body)
    if added.status_code == 409 and added.json()["detail"].get("candidate_id"):
        added = client.post("/api/data/holidays/range", json={
            **body, "candidate_id": added.json()["detail"]["candidate_id"],
            "approve_exceptions": True, "approval_reason": "teste", "approval_author": "pytest",
        })
    assert added.status_code == 200, added.text
    assert _active(store)["name"] == f"Feriado {history.day_month(holiday)} adicionado"
    assert _undo_view(client)["label"] == f"Feriado {history.day_month(holiday)} adicionado"


def test_isop_load_is_named_after_its_file(tmp_path):
    loaded = _loaded_state()
    loaded.dataset_info = {**loaded.dataset_info, "filename": "ISOP_ Nikufra_13.10.xlsx"}
    store = PlansStore(tmp_path / "load.db")
    try:
        job = {
            "id": "job-1", "status": "running", "filename": "ISOP_ Nikufra_13.10.xlsx",
            "result": {"score": {}},
        }
        store.create_load_job(job, "fingerprint")
        store.commit_load(
            job, plan_id=uuid4().hex, payload_json=json.dumps(serialize_snapshot(loaded)),
        )
        active = store.active()
        assert active["name"] == "ISOP ISOP_ Nikufra_13.10.xlsx carregado"
        assert active["kind"] == "load"
    finally:
        store.close()


def _save(store, payload, name, *, activate=True, source="auto", kind="", origin="isop.xlsx"):
    return store.save(
        name=name, source=source, origin=origin, note="", payload=payload, score={},
        gate_report=None, is_auto=True, activate=activate, kind=kind,
    )["id"]


def test_retention_keeps_the_undo_chain_the_latest_load_and_recalculation(tmp_path):
    payload = serialize_snapshot(_loaded_state())
    other = _loaded_state()
    other.dataset_info = {**other.dataset_info, "filename": "outro.xlsx"}
    other_payload = serialize_snapshot(other)
    store = PlansStore(tmp_path / "retention.db")
    try:
        orphans = [_save(store, payload, f"Solto {index}", activate=False) for index in range(5)]
        old_load = _save(store, payload, "ISOP antigo carregado", source="load")
        load = _save(store, payload, "ISOP carregado", source="load")
        other_load = _save(store, other_payload, "Outro ISOP", source="load", origin="outro.xlsx")
        recalculation = _save(store, payload, "Recalcular plano", kind="recalculate")
        moves = [_save(store, payload, f"Movido {index}") for index in range(HISTORY_KEEP_STEPS + 4)]
        store.prune_auto()
        kept = {plan["id"] for plan in store.list(500)}
        # The active version and the 30 before it, as «Desfazer» walks them.
        assert set(moves[-(HISTORY_KEEP_STEPS + 1):]) <= kept
        assert not set(moves[: -(HISTORY_KEEP_STEPS + 1)]) & kept
        assert {load, other_load, recalculation} <= kept
        assert old_load not in kept
        assert not set(orphans) & kept
    finally:
        store.close()


def test_undo_label_walks_back_and_never_forward(tmp_path):
    payload = serialize_snapshot(_loaded_state())
    store = PlansStore(tmp_path / "chain.db")
    try:
        first = _save(store, payload, "Plano da manhã")
        _save(store, payload, "Movido A")
        _save(store, payload, "Movido B")
        assert store.undo_target()["label"] == "Movido B"
        # «Desfazer» B: the new version takes the place of «Movido A».
        target = store.undo_target()["id"]
        store.prepare_mutation("undo-b", "f", {"plan_revision": 1})
        store.commit_mutation(
            "undo-b", payload, {}, source="auto", name="Desfeito: Movido B",
            undo_restores=target,
        )
        assert store.undo_target()["label"] == "Movido A"
        store.prepare_mutation("undo-a", "f", {"plan_revision": 1})
        store.commit_mutation(
            "undo-a", payload, {}, source="auto", name="Desfeito: Movido A",
            undo_restores=store.undo_target()["id"],
        )
        assert store.active()["name"] == "Desfeito: Movido A"
        assert store.undo_target() is None
        assert store.get(first)["name"] == "Plano da manhã"
    finally:
        store.close()


def test_calendar_changes_are_named_in_plain_portuguese():
    before = SimpleNamespace(holidays=[], extra_workdays=[], machine_unavailability=[],
                             tool_unavailability=[], operator_unavailability=[])
    after = SimpleNamespace(
        holidays=["2026-12-07"], extra_workdays=[], tool_unavailability=[],
        operator_unavailability=[],
        machine_unavailability=[{
            "id": "u1", "resource": "PRM043", "category": "Avaria",
            "start_at": "2026-10-16T07:00", "end_at": "2026-10-18T15:30",
        }],
    )
    assert history.config_change_label(before, after) == (
        "Feriado 07/12 adicionado; Avaria PRM043 16/10 07:00–18/10 15:30"
    )
    assert history.config_change_label(after, before) == (
        "Feriado 07/12 retirado; Retirada: Avaria PRM043 16/10 07:00–18/10 15:30"
    )
    range_after = SimpleNamespace(**{**vars(before), "holidays": ["2026-12-07", "2026-12-08"]})
    assert history.config_change_label(before, range_after) == "Feriados 07/12–08/12 adicionados"
    assert history.config_change_label(before, before) is None
    # An endpoint's label wins; then a recognised calendar change; then the default.
    assert history.snapshot_name({"label": "Recalcular plano"}, before, after) == "Recalcular plano"
    assert history.snapshot_name({"default_label": "Replaneamento"}, before, after).startswith(
        "Feriado 07/12"
    )
    assert history.snapshot_name({"default_label": "Replaneamento"}, before, before) == (
        "Replaneamento"
    )
    assert history.snapshot_name({}) == "Plano aplicado"
