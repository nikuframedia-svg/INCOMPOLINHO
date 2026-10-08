"""Regression tests for API validation and local app contracts."""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.api import data as data_api
from backend.api.copilot import app
from backend.analytics.late_delivery import LateDeliveryReport, TardyAnalysis
from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.copilot.state import state
from backend.loading.jobs import LoadJobManager
from backend.plans.store import PlansStore
from backend.audit.store import AuditStore
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.types import ScheduleResult
from backend.simulator.simulator import DeltaReport
from backend.types import EngineData, EOp, MachineInfo


def _engine() -> EngineData:
    return EngineData(
        ops=[
            EOp(
                id="T1_M1_SKU1",
                sku="SKU1",
                client="CLIENTE",
                designation="Peça teste",
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
                oee=0.66,
                wip=0,
            )
        ],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
        twin_groups=[],
        client_demands={},
        workdays=["2026-03-17", "2026-03-18", "2026-03-19"],
        n_days=3,
        holidays=[],
    )


def _config() -> FactoryConfig:
    config = FactoryConfig()
    config.machines = {"M1": MachineConfig(id="M1", group="Grandes", active=True)}
    config.tools = {"T1": {"primary": "M1", "setup_hours": 0.5}}
    return config


def _mutation(body: dict | None = None) -> dict:
    return {
        "expected_revision": state.plan_revision,
        "approve_exceptions": False,
        "approval_reason": "teste transacional",
        "approval_author": "pytest",
        **(body or {}),
    }


def _previewed_mutation(client, body: dict, preview_path="/api/data/simulate") -> dict:
    preview = client.post(preview_path, json=body)
    assert preview.status_code == 200, preview.text
    identity = preview.json()
    return _mutation(
        {
            **body,
            "candidate_id": identity["candidate_id"],
            "expected_revision": identity["base_revision"],
            "approve_exceptions": True,
        }
    )


def _confirmed_write(client, method, path, *, json):
    result = client.request(method, path, json=json)
    if result.status_code == 409 and isinstance(result.json().get("detail"), dict):
        detail = result.json()["detail"]
        if detail.get("candidate_id"):
            assert detail["gate_report"]["apply_decision"] == "approval_required"
            result = client.request(method, path, json={
                **json, "candidate_id": detail["candidate_id"], "approve_exceptions": True,
            })
    return result


@pytest.fixture(autouse=True)
def loaded_state(tmp_path, monkeypatch):
    previous = state.__dict__.copy()
    previous_manager = getattr(app.state, "load_jobs", None)
    state.plans_store = PlansStore(tmp_path / "plans.db")
    state.audit_store = AuditStore(":memory:")
    manager = LoadJobManager(state, state.plans_store)
    app.state.load_jobs = manager
    state.engine_data = _engine()
    state.config = _config()
    state.segments = []
    state.lots = []
    state.score = {"otd": 100.0, "otd_d": 100.0, "setups": 1, "tardy_count": 0}
    state.default_config = _config()
    state.saved_schedule = None
    state.active_mutations = []
    state.dataset_info = None
    state.trust_index = None
    state.learning_info = None
    state.gate_report = None
    state.late_deliveries = None
    state.approvals = []
    monkeypatch.setattr(
        "backend.config.loader.save_config",
        lambda *_args, **_kwargs: None,
    )
    yield
    manager.executor.shutdown(wait=True, cancel_futures=True)
    state.plans_store.close()
    state.audit_store.close() if hasattr(state.audit_store, "close") else None
    if previous_manager is None:
        del app.state.load_jobs
    else:
        app.state.load_jobs = previous_manager
    state.__dict__.update(previous)


def test_plan_view_returns_one_coherent_revision():
    state.plan_revision = 17

    response = TestClient(app).get("/api/data/plan-view")

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan_revision"] == 17
    assert payload["score"]["plan_revision"] == 17
    assert payload["gate_report"]["plan_revision"] == 17
    assert payload["config"]["plan_revision"] == 17
    assert payload["segments"] == []
    assert payload["placement_reasons"] == {}
    assert payload["lots"] == []
    assert payload["workdays"] == state.engine_data.workdays
    assert payload["blocked_days"]["workdays"] == state.engine_data.workdays


def test_plan_view_is_compressed_without_losing_revision_headers():
    state.plan_revision = 17
    client = TestClient(app)

    compressed = client.get("/api/data/plan-view", headers={"Accept-Encoding": "gzip"})
    plain = client.get("/api/data/plan-view", headers={"Accept-Encoding": "identity"})

    assert compressed.headers.get("content-encoding") == "gzip"
    assert "content-encoding" not in plain.headers
    assert compressed.headers.get("x-plan-revision") == plain.headers.get("x-plan-revision")
    assert compressed.headers.get("x-dataset-id") == plain.headers.get("x-dataset-id")
    assert compressed.json() == plain.json()


def test_blocked_days_exposes_operator_absences_with_counts_and_shifts():
    state.engine_data.operator_blocked_intervals = [{
        "id": "absence-1", "start_day": 1, "start_min": 420,
        "end_day": 1, "end_min": 900, "group": "Grandes",
        "shift": "A", "count": 3, "category": "Outra",
        "reason": "doença", "start_at": "2026-03-18T07:00:00+00:00",
        "end_at": "2026-03-18T15:00:00+00:00",
    }]

    response = TestClient(app).get("/api/data/blocked-days")

    assert response.status_code == 200
    assert response.json()["operator_intervals"] == state.engine_data.operator_blocked_intervals


def test_config_validation_returns_400(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)

    response = client.put(
        "/api/data/config",
        json=_mutation({"jit_threshold": "abc"}),
    )

    assert response.status_code == 400
    assert "jit_threshold" in response.json()["detail"]


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"max_run_days": 0}, "max_run_days"),
        ({"jit_buffer_pct": 1.5}, "jit_buffer_pct"),
        ({"jit_threshold": 101}, "jit_threshold"),
        ({"vns_max_iter": -1}, "vns_max_iter"),
        ({"eco_lot_mode": "unknown"}, "eco_lot_mode"),
    ],
)
def test_config_rejects_values_outside_scheduler_domains(
    monkeypatch,
    update,
    message,
):
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    response = TestClient(app).put(
        "/api/data/config",
        json=_mutation(update),
    )

    assert response.status_code == 400
    assert message in response.text


def test_config_bool_strings_are_parsed(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        data_api,
        "_recompute",
        lambda _config: SimpleNamespace(time_ms=12.3),
    )

    response = client.put(
        "/api/data/config",
        json=_mutation({"jit_enabled": "false"}),
    )

    assert response.status_code == 200
    # JIT is an industrial invariant and is no longer a mutable API setting.
    assert state.config.jit_enabled is True


def test_config_exposes_planning_tunables():
    client = TestClient(app)

    response = client.get("/api/data/config")

    assert response.status_code == 200
    payload = response.json()
    for key in [
        "auto_buffer",
        "vns_enabled",
        "compact_enabled",
        "jit_max_retries",
        "max_edd_span",
        "edd_assign_threshold",
        "setup_crews",
    ]:
        assert key in payload


def test_today_uses_the_configured_factory_timezone(monkeypatch):
    observed = {}

    class FixedDatetime:
        @classmethod
        def now(cls, timezone):
            observed["timezone"] = timezone
            return datetime(2026, 3, 18, 0, 30, tzinfo=timezone)

    state.config.timezone = "Europe/Berlin"
    monkeypatch.setattr(data_api, "datetime", FixedDatetime)

    response = TestClient(app).get("/api/data/today")

    assert response.status_code == 200
    assert response.json() == {"today_idx": 1, "date": "2026-03-18"}
    assert observed["timezone"].key == "Europe/Berlin"


def test_config_rejects_unsupported_multi_setup_crews(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        data_api,
        "_recompute",
        lambda _config: SimpleNamespace(time_ms=12.3),
    )

    response = client.put("/api/data/config", json={"setup_crews": 2})

    assert response.status_code == 400
    assert state.config.setup_crews == 1


def test_config_updates_new_planning_tunable(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        data_api,
        "_recompute",
        lambda _config: SimpleNamespace(time_ms=12.3),
    )

    previous_score = dict(state.score)
    response = client.put(
        "/api/data/config",
        json=_mutation({"compact_enabled": "true"}),
    )

    assert response.status_code == 200
    assert state.config.compact_enabled is True
    assert response.json()["score_previous"] == previous_score


def test_config_updates_shifts(monkeypatch):
    client = TestClient(app)
    state.config.machines["M1"].day_capacity_min = state.config.day_capacity_min
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        data_api,
        "_recompute",
        lambda _config: SimpleNamespace(time_ms=12.3),
    )

    response = client.put(
        "/api/data/config",
        json=_mutation(
            {
                "shifts": [
                    {"id": "A", "label": "Manhã", "start_min": 420, "end_min": 930},
                    {"id": "B", "label": "Tarde", "start_min": 930, "end_min": 0},
                ],
            }
        ),
    )

    assert response.status_code == 200
    assert response.json()["changed"] == ["shifts"]
    assert state.config.shifts == [
        ShiftConfig("A", 420, 930, "Manhã"),
        ShiftConfig("B", 930, 1440, "Tarde"),
    ]
    assert state.config.day_capacity_min == 1020
    assert state.config.machines["M1"].day_capacity_min is None


def test_config_shift_capacity_change_clears_stale_machine_capacity(monkeypatch):
    client = TestClient(app)
    state.config.machines["M1"].day_capacity_min = state.config.day_capacity_min
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        data_api,
        "_recompute",
        lambda _config: SimpleNamespace(time_ms=12.3),
    )

    response = client.put(
        "/api/data/config",
        json=_mutation(
            {
                "shifts": [
                    {"id": "A", "label": "Manhã", "start_min": 420, "end_min": 930},
                    {"id": "B", "label": "Tarde", "start_min": 930, "end_min": 1430},
                ],
            }
        ),
    )

    assert response.status_code == 200
    assert state.config.day_capacity_min == 1010
    assert state.config.machines["M1"].day_capacity_min is None


def test_config_noop_returns_a_valid_score_delta_pair():
    response = TestClient(app).put(
        "/api/data/config",
        json=_mutation(),
    )

    assert response.status_code == 200
    assert response.json()["score_previous"] == response.json()["score"]


def test_persistent_unavailability_crud_rebuilds_engine(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)

    created = _confirmed_write(client, "POST",
        "/api/data/unavailability",
        json={
            **_mutation(),
            "kind": "machine",
            "resource": "M1",
            "from": "2026-03-19",
            "to": "2026-03-19",
            "reason": "Manutenção",
        },
    )

    assert created.status_code == 200
    entry_id = created.json()["entry"]["id"]
    assert state.engine_data.machine_blocked_days == {"M1": {2}}

    listed = client.get("/api/data/unavailability")
    assert listed.status_code == 200
    assert listed.json()["resolved"]["machines"][0]["days"] == [2]

    removed = _confirmed_write(client,
        "DELETE",
        f"/api/data/unavailability/{entry_id}",
        json=_mutation(),
    )
    assert removed.status_code == 200
    assert state.config.machine_unavailability == []
    assert state.engine_data.machine_blocked_days == {}


def test_machine_unavailability_rejects_jit_blocked_operational_candidate(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)

    def fake_compute_schedule(_config):
        result = ScheduleResult(
            segments=[],
            lots=[],
            score={
                "otd": 100.0,
                "otd_d": 100.0,
                "setups": 0,
                "tardy_count": 0,
            },
            time_ms=1.0,
            warnings=[],
            operator_alerts=[],
            journal=[],
        )
        result.gate_report = {
            "status": "jit_window_blocked",
            "apply_decision": "blocked",
            "approval_reasons": ["jit_window_blocked"],
            "physical_gate_passed": True,
            "coverage_gate_passed": True,
            "delivery_gate_passed": True,
            "jit_window_gate_passed": False,
        }
        return result, None

    monkeypatch.setattr(data_api, "_compute_schedule", fake_compute_schedule)

    response = client.post(
        "/api/data/unavailability",
        json={
            "expected_revision": state.plan_revision,
            "kind": "machine",
            "resource": "M1",
            "category": "Avaria",
            "start_at": "2026-03-19T08:00",
            "end_at": "2026-03-19T10:00",
            "reason": "teste avaria",
        },
    )

    assert response.status_code == 409, response.text
    assert "janela JIT" in response.json()["detail"]["message"]
    assert state.config.machine_unavailability == []
    assert state.approvals == []


def test_calendar_range_and_extra_workday_crud(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)

    added_range = _confirmed_write(client, "POST",
        "/api/data/holidays/range",
        json=_mutation({"from": "2026-04-01", "to": "2026-04-03"}),
    )
    assert added_range.status_code == 200
    assert state.config.holidays[-3:] == ["2026-04-01", "2026-04-02", "2026-04-03"]

    removed_range = _confirmed_write(client,
        "DELETE",
        "/api/data/holidays/range",
        json=_mutation({"from": "2026-04-01", "to": "2026-04-03"}),
    )
    assert removed_range.status_code == 200
    assert state.config.holidays == []

    added_workday = _confirmed_write(client, "POST",
        "/api/data/workdays-extra",
        json=_mutation({"date": "2026-03-21"}),
    )
    assert added_workday.status_code == 200
    assert state.config.extra_workdays == ["2026-03-21"]

    removed_workday = _confirmed_write(client,
        "DELETE",
        "/api/data/workdays-extra/2026-03-21",
        json=_mutation(),
    )
    assert removed_workday.status_code == 200
    assert state.config.extra_workdays == []


def test_setup_overrides_and_machine_oee_api(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "backend.copilot.executors_master._persist_config",
        lambda *_args, **_kwargs: None,
    )

    overrides = _confirmed_write(client, "PUT",
        "/api/data/setup-overrides",
        json=_mutation(
            {"items": [{"sku": "SKU1", "machine": "M1", "hours": 1.25}]}
        ),
    )
    assert overrides.status_code == 200, overrides.text
    assert state.config.setup_overrides == [{"sku": "SKU1", "machine": "M1", "hours": 1.25}]

    machine = _confirmed_write(client, "PUT",
        "/api/data/machines/M1",
        json=_mutation({"oee": 0.75}),
    )
    assert machine.status_code == 200
    assert state.config.machines["M1"].oee == 0.75


@pytest.mark.parametrize(
    ("path", "payload", "message"),
    [
        (
            "/api/data/machines/M1",
            {"activa": "talvez"},
            "valor booleano inválido",
        ),
        (
            "/api/data/tools/T1",
            {"setup_hours": "muito"},
            "setup_hours deve ser um número",
        ),
        (
            "/api/data/tools/T1",
            {"setup_hours": 9},
            "intervalo [0, 8]",
        ),
    ],
)
def test_master_data_api_rejects_malformed_values(path, payload, message):
    response = TestClient(app).put(path, json=_mutation(payload))

    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_calendar_api_rejects_invalid_resources_and_weekdays():
    client = TestClient(app)

    unknown_machine = client.post(
        "/api/data/unavailability",
        json={
            **_mutation(),
            "kind": "machine",
            "resource": "M404",
            "from": "2026-03-19",
            "to": "2026-03-19",
        },
    )
    weekday = client.post(
        "/api/data/workdays-extra",
        json=_mutation({"date": "2026-03-18"}),
    )

    assert unknown_machine.status_code == 400
    assert weekday.status_code == 400


def test_capacity_and_blocked_days_api_contracts():
    client = TestClient(app)
    state.engine_data.holidays = [1]
    state.engine_data.machine_blocked_days = {"M1": {2}}

    capacity = client.get("/api/data/capacity?granularity=week")
    blocked = client.get("/api/data/blocked-days")

    assert capacity.status_code == 200
    assert capacity.json()["granularity"] == "week"
    assert capacity.json()["items"]
    assert blocked.status_code == 200
    assert blocked.json()["holidays"][0]["day_idx"] == 1
    assert blocked.json()["machine_blocks"][0] == {
        "machine_id": "M1",
        "day_idx": 2,
        "date": "2026-03-19",
    }


def test_view_access_mode_rejects_mutations_but_allows_previews():
    client = TestClient(app)

    blocked = client.post(
        "/api/data/recalculate",
        json={"expected_revision": state.plan_revision},
        headers={"X-Access-Mode": "view"},
    )
    preview = client.post(
        "/api/data/simulate",
        json={"mutations": []},
        headers={"X-Access-Mode": "view"},
    )

    assert blocked.status_code == 403
    assert "Modo Consulta" in blocked.json()["detail"]
    assert preview.status_code != 403


def test_simulate_rejects_empty_and_unknown_mutations():
    client = TestClient(app)

    empty = client.post("/api/data/simulate", json={"mutations": []})
    unknown = client.post(
        "/api/data/simulate",
        json={"mutations": [{"type": "unknown", "params": {}}]},
    )

    assert empty.status_code == 400
    assert unknown.status_code == 400


def test_simulate_apply_empty_does_not_create_revert_snapshot():
    client = TestClient(app)

    response = client.post("/api/data/simulate-apply", json={"mutations": []})

    assert response.status_code == 400
    assert state.saved_schedule is None


def _simulation_result(score=None, summary="ok", gate_report=None):
    result_score = score or {"otd": 99.0, "otd_d": 99.0, "setups": 1, "tardy_count": 0}
    return SimpleNamespace(
        segments=[],
        lots=[],
        score=result_score,
        delta=DeltaReport(
            otd_before=100.0,
            otd_after=float(result_score.get("otd", 0)),
            otd_d_before=100.0,
            otd_d_after=float(result_score.get("otd_d", 0)),
            setups_before=1,
            setups_after=int(result_score.get("setups", 0)),
            earliness_before=0.0,
            earliness_after=float(result_score.get("earliness_avg_days", 0) or 0),
            tardy_before=0,
            tardy_after=int(result_score.get("tardy_count", 0)),
        ),
        time_ms=5.0,
        summary=summary,
        gate_report=gate_report,
    )


def test_simulate_apply_runs_only_pending_and_revert_restores_active_mutations(monkeypatch):
    client = TestClient(app)
    state.active_mutations = [
        {"type": "machine_down", "params": {"machine_id": "M1", "start": 0, "end": 0}}
    ]
    captured = {}

    def fake_simulate(_engine_data, _score, mutations, config=None, **kwargs):
        captured["types"] = [m.type for m in mutations]
        captured["active_mutations"] = copy.deepcopy(kwargs["active_mutations"])
        captured["baseline_result"] = kwargs["baseline_result"]
        return _simulation_result()

    monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)

    response = client.post(
        "/api/data/simulate-apply",
        json=_previewed_mutation(
            client,
            {
                "mutations": [
                    {
                        "type": "operator_shortage",
                        "params": {
                            "group": "Grandes",
                            "shift": "A",
                            "start": 0,
                            "end": 0,
                            "count": 1,
                            "note": "teste",
                        },
                    }
                ]
            }
        ),
    )

    assert response.status_code == 200
    assert captured["types"] == ["operator_shortage"]
    assert captured["active_mutations"] == [
        {"type": "machine_down", "params": {"machine_id": "M1", "start": 0, "end": 0}}
    ]
    assert captured["baseline_result"].segments == []
    assert [m["type"] for m in state.active_mutations] == ["machine_down", "operator_shortage"]

    reverted = client.post("/api/data/revert", json=_mutation())

    assert reverted.status_code == 200
    assert state.active_mutations == [
        {"type": "machine_down", "params": {"machine_id": "M1", "start": 0, "end": 0}}
    ]


def test_simulate_apply_rejects_concurrent_plan_mutation_without_overwrite(monkeypatch):
    base_revision = state.plan_revision
    entered = threading.Event()
    release = threading.Event()
    authorize = data_api._ensure_result_applicable

    def slow_authorize(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5), "concurrent mutation did not release application"
        return authorize(*args, **kwargs)

    monkeypatch.setattr(
        "backend.simulator.simulator.simulate", lambda *_a, **_kw: _simulation_result()
    )
    body = _previewed_mutation(
        TestClient(app),
        {"mutations": [{"type": "machine_down", "params": {"machine_id": "M1", "start": 0, "end": 0}}]},
    )
    request = data_api.SimulateRequest(**body)
    monkeypatch.setattr(data_api, "_ensure_result_applicable", slow_authorize)

    async def exercise():
        apply_task = asyncio.create_task(data_api.simulate_and_apply(request))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            # Calculation is detached; a newer edit must win at commit.
            async with data_api.plan_mutation_lock:
                state.score = {"sentinel": True}
                state.plan_revision += 1
            release.set()
            with pytest.raises(HTTPException) as rejected:
                await asyncio.wait_for(apply_task, timeout=5)
            assert rejected.value.status_code == 409
        finally:
            release.set()
            if not apply_task.done():
                await asyncio.gather(apply_task, return_exceptions=True)

    try:
        asyncio.run(exercise())
    finally:
        release.set()

    assert state.score == {"sentinel": True}
    assert state.plan_revision == base_revision + 1
    assert state.saved_schedule is None
    assert state.active_mutations == []
    assert state.plans_store.list() == []


def test_simulate_apply_preserves_scheduler_warnings_and_operator_alerts(monkeypatch):
    client = TestClient(app)
    result = _simulation_result()
    result.warnings = ["aviso de planeamento"]
    result.operator_alerts = ["alerta de operador"]
    monkeypatch.setattr(
        "backend.simulator.simulator.simulate",
        lambda *_args, **_kwargs: result,
    )

    response = client.post(
        "/api/data/simulate-apply",
        json=_previewed_mutation(
            client,
            {
                "mutations": [
                    {
                        "type": "machine_down",
                        "params": {"machine_id": "M1", "start": 0, "end": 0},
                    }
                ]
            }
        ),
    )

    assert response.status_code == 200, response.text
    assert state.warnings == ["aviso de planeamento"]
    assert state.operator_alerts == ["alerta de operador"]


def test_simulate_preview_runs_only_new_mutations_and_dedupes(monkeypatch):
    client = TestClient(app)
    state.active_mutations = [
        {"type": "machine_down", "params": {"machine_id": "M1", "start": 0, "end": 0}}
    ]
    captured = {}

    def fake_simulate(_engine_data, _score, mutations, config=None, **kwargs):
        captured["types"] = [m.type for m in mutations]
        return _simulation_result()

    monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)

    response = client.post(
        "/api/data/simulate",
        json={
            "mutations": [
                {
                    "type": "machine_down",
                    "params": {"machine_id": "M1", "start": 0, "end": 0},
                },
                {
                    "type": "operator_shortage",
                    "params": {
                        "group": "Grandes",
                        "shift": "A",
                        "start": 0,
                        "end": 0,
                        "count": 1,
                        "note": "teste",
                    },
                },
            ]
        },
    )

    assert response.status_code == 200
    assert captured["types"] == ["operator_shortage"]


def test_simulate_apply_rejects_failed_gate_without_mutating(monkeypatch):
    client = TestClient(app)
    failed_gate = {
        "status": "invalid_physics",
        "hard_gate_passed": False,
        "delivery_gate_passed": True,
        "metrics": {"setup_crew_overlaps": 1},
        "violations": [],
        "late_detail": [],
        "setup_overlap_detail": [],
        "proposals": [],
    }

    def fake_simulate(_engine_data, _score, _mutations, config=None, **kwargs):
        return _simulation_result(gate_report=failed_gate)

    monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)

    response = client.post(
        "/api/data/simulate-apply",
        json=_previewed_mutation(
            client,
            {
                "mutations": [
                    {
                        "type": "operator_shortage",
                        "params": {
                            "group": "Grandes",
                            "shift": "A",
                            "start": 0,
                            "end": 0,
                            "count": 1,
                            "note": "teste",
                        },
                    }
                ]
            }
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["gate_report"] == failed_gate
    assert state.active_mutations == []
    assert state.saved_schedule is None


def test_recompute_transactional_rolls_back_runtime_state(monkeypatch):
    original_segments = list(state.segments)
    original_score = dict(state.score)

    def broken_recompute(_config):
        state.segments = [object()]
        state.score = {"otd": 0}
        raise ValueError("boom")

    monkeypatch.setattr(data_api, "_recompute", broken_recompute)

    with pytest.raises(ValueError):
        data_api._recompute_transactional(state.config)

    assert state.segments == original_segments
    assert state.score == original_score


def test_unavailability_disk_failure_rolls_back_config_and_engine(monkeypatch):
    original_config = copy.deepcopy(state.config)
    original_engine = copy.deepcopy(state.engine_data)
    original_revision = state.plan_revision

    def fake_recompute(candidate):
        state.config = candidate
        state.engine_data.machine_blocked_days = {"M1": {1}}
        return None

    def fail_save(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(data_api, "_recompute", fake_recompute)
    monkeypatch.setattr("backend.config.loader.save_config", fail_save)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/data/unavailability",
        json={
            **_mutation(),
            "kind": "machine",
            "resource": "M1",
            "start_at": "2026-03-18T08:00:00+00:00",
            "end_at": "2026-03-18T10:00:00+00:00",
            "category": "Avaria",
        },
    )

    assert response.status_code == 500
    assert state.config == original_config
    assert state.engine_data == original_engine
    assert state.plan_revision == original_revision


def test_simulate_apply_disk_failure_leaves_live_and_revert_state_untouched(
    monkeypatch,
):
    client = TestClient(app, raise_server_exceptions=False)
    original_config = copy.deepcopy(state.config)
    original_engine = copy.deepcopy(state.engine_data)
    original_revision = state.plan_revision
    result = _simulation_result()
    result.mutated_data = copy.deepcopy(state.engine_data)
    result.mutated_config = copy.deepcopy(state.config)
    result.mutated_config.jit_threshold += 1

    monkeypatch.setattr(
        "backend.simulator.simulator.simulate",
        lambda *_args, **_kwargs: result,
    )
    monkeypatch.setattr(
        "backend.config.loader.save_config",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    response = client.post(
        "/api/data/simulate-apply",
        json=_previewed_mutation(
            client,
            {
                "mutations": [
                    {
                        "type": "machine_down",
                        "params": {"machine_id": "M1", "start": 0, "end": 0},
                    }
                ]
            }
        ),
    )

    assert response.status_code == 500
    assert state.config == original_config
    assert state.engine_data == original_engine
    assert state.active_mutations == []
    assert state.saved_schedule is None
    assert state.plan_revision == original_revision


def test_revert_persists_saved_config_before_committing_runtime(monkeypatch):
    saved_threshold = state.config.jit_threshold
    state.save_current()
    state.plan_revision += 1
    state.config = copy.deepcopy(state.config)
    state.config.jit_threshold = saved_threshold + 1
    state.active_mutations = [
        {
            "type": "machine_down",
            "params": {"machine_id": "M1", "start": 0, "end": 0},
        }
    ]
    persisted = []
    monkeypatch.setattr(
        "backend.config.loader.save_config",
        lambda config, *_args, **_kwargs: persisted.append(copy.deepcopy(config)),
    )

    response = TestClient(app).post("/api/data/revert", json=_mutation())

    assert response.status_code == 200
    assert persisted[0].jit_threshold == saved_threshold
    assert state.config.jit_threshold == saved_threshold
    assert state.active_mutations == []
    assert state.saved_schedule is None


def test_revert_disk_failure_keeps_current_state_and_snapshot(monkeypatch):
    state.save_current()
    state.plan_revision += 1
    state.config = copy.deepcopy(state.config)
    state.config.jit_threshold += 1
    state.active_mutations = [
        {
            "type": "machine_down",
            "params": {"machine_id": "M1", "start": 0, "end": 0},
        }
    ]
    current_config = copy.deepcopy(state.config)
    current_mutations = copy.deepcopy(state.active_mutations)
    current_revision = state.plan_revision
    monkeypatch.setattr(
        "backend.config.loader.save_config",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/data/revert",
        json=_mutation(),
    )

    assert response.status_code == 500
    assert state.config == current_config
    assert state.active_mutations == current_mutations
    assert state.saved_schedule is not None
    assert state.saved_config is not None
    assert state.plan_revision == current_revision


def test_revert_rejects_when_plan_changed_after_applied_change():
    state.save_current()
    state.plan_revision += 2

    response = TestClient(app).post("/api/data/revert", json=_mutation())

    assert response.status_code == 409
    assert "trabalho posterior" in response.json()["detail"]
    assert state.saved_schedule is not None


def test_config_apply_rejects_failed_gate_and_rolls_back(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    original_threshold = state.config.jit_threshold
    failed_gate = {
        "status": "infeasible_current_conditions",
        "hard_gate_passed": True,
        "delivery_gate_passed": False,
        "metrics": {"tardy_count": 1, "otd": 99.0, "otd_d": 100.0},
        "violations": [],
        "late_detail": [],
        "setup_overlap_detail": [],
        "proposals": [],
    }

    def failed_recompute(config):
        state.config = config
        state.score = {"otd": 99.0, "otd_d": 100.0, "tardy_count": 1}
        return SimpleNamespace(time_ms=12.3, gate_report=failed_gate)

    monkeypatch.setattr(data_api, "_recompute", failed_recompute)

    response = client.put(
        "/api/data/config",
        json=_mutation({"jit_threshold": original_threshold + 1}),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["gate_report"] == failed_gate
    assert state.config.jit_threshold == original_threshold


def test_ctp_rejects_invalid_qty_and_deadline():
    client = TestClient(app)

    bad_qty = client.post("/api/data/ctp", json={"sku": "SKU1", "qty": 0, "deadline": 1})
    bad_deadline = client.post("/api/data/ctp", json={"sku": "SKU1", "qty": 1, "deadline": 99})

    assert bad_qty.status_code == 400
    assert bad_deadline.status_code == 400


def test_ctp_passes_customer_deadline_to_canonical_calculator(monkeypatch):
    client = TestClient(app)
    state.engine_data.ops[0].finish_buffer_days = 2
    captured = {}

    def fake_ctp(sku, qty, deadline, baseline, engine_data, config=None, **kwargs):
        captured["deadline"] = deadline
        return SimpleNamespace(
            sku=sku,
            qty_requested=qty,
            feasible=True,
            latest_day=deadline,
            earliest_end_day=deadline,
            machine="M1",
            confidence="high",
            slack_min=100,
            reason=None,
            date_start=None,
            date_end=None,
            required_min=1,
            prod_days=1,
        ), None

    monkeypatch.setattr("backend.analytics.ctp.verify_ctp", fake_ctp)

    response = client.post("/api/data/ctp", json={"sku": "SKU1", "qty": 10, "deadline": 2})

    assert response.status_code == 200
    assert captured["deadline"] == 2
    assert response.json()["delivery_deadline"] == 2
    assert response.json()["effective_deadline"] == 2
    assert response.json()["customer_delivery_day"] == 2
    assert response.json()["latest_subcontract_dispatch_day"] is None
    assert response.json()["internal_target_day"] == 2
    assert response.json()["material_reference_day"] == 2


def test_ctp_apply_preserves_active_mutations_and_returns_promise(monkeypatch):
    client = TestClient(app)
    state.active_mutations = [{"type": "machine_down", "params": {"machine_id": "M1"}}]
    captured = {}

    def fake_ctp(sku, qty, deadline, segments, engine_data, config=None):
        return SimpleNamespace(
            sku=sku,
            qty_requested=qty,
            feasible=True,
            latest_day=0,
            earliest_end_day=deadline,
            machine="M1",
            confidence="high",
            slack_min=100,
            reason=None,
            date_start=None,
            date_end=None,
            required_min=1,
            prod_days=1,
        )

    def fake_simulate(_engine_data, _score, mutations, config=None, **kwargs):
        captured["types"] = [m.type for m in mutations]
        result = _simulation_result(summary="rush", gate_report={"physical_gate_passed": True, "coverage_gate_passed": True, "apply_decision": "auto_applicable"})
        result.mutated_data = copy.deepcopy(_engine_data)
        result.mutated_data.ops[0].d[2] += 10
        result.mutated_config = copy.deepcopy(config)
        from backend.scheduler.lot_sizing import create_lots
        from backend.scheduler.types import Segment

        result.lots = create_lots(result.mutated_data, config)
        result.segments = [Segment(lot.id, f"run-{index}", lot.machine_id, lot.tool_id, lot.edd, 420, 420 + lot.prod_min + lot.setup_min, "A", lot.qty, lot.prod_min, setup_min=lot.setup_min, sku=lot.sku) for index, lot in enumerate(result.lots)]
        return result

    monkeypatch.setattr("backend.analytics.ctp.compute_ctp", fake_ctp)
    monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)

    response = client.post(
        "/api/data/ctp-apply",
        json=_previewed_mutation(
            client, {"sku": "SKU1", "qty": 10, "deadline": 2}, "/api/data/ctp"
        ),
    )

    assert response.status_code == 200
    assert captured["types"] == ["rush_order"]
    assert [m["type"] for m in state.active_mutations] == ["machine_down", "rush_order"]
    assert state.engine_data.ops[0].d[2] == 10
    assert response.json()["promise"]["effective_deadline"] == 2
    assert response.json()["promise"]["internal_target_day"] == 2
    assert response.json()["promise"]["material_reference_day"] == 2


def test_recalculate_returns_result_time(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(
        data_api,
        "_recompute",
        lambda _config: SimpleNamespace(time_ms=123.4),
    )

    response = client.post("/api/data/recalculate", json=_mutation())

    assert response.status_code == 200
    assert response.json()["time_ms"] == 123.4


def test_recalculate_can_compact_the_active_plan(monkeypatch):
    client = TestClient(app)
    called = []
    monkeypatch.setattr(
        data_api,
        "_compact_active_schedule",
        lambda config: called.append(config) or SimpleNamespace(time_ms=45.6),
    )
    monkeypatch.setattr(
        data_api,
        "_recompute",
        lambda _config: pytest.fail("não deve reconstruir o plano"),
    )

    response = client.post(
        "/api/data/recalculate",
        json=_mutation({"compact_active_plan": True}),
    )

    assert response.status_code == 200, response.text
    assert response.json()["time_ms"] == 45.6
    assert len(called) == 1


def test_operator_validation_returns_400():
    client = TestClient(app)

    response = client.put("/api/data/operators", json={"Grandes A": "abc"})

    assert response.status_code == 400


def test_max_otd_preset_preserves_subcontract_skus(monkeypatch):
    client = TestClient(app)
    state.config.subcontract_skus = ["HAN002"]
    state.default_config = _config()
    state.default_config.subcontract_skus = ["HAN002"]

    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        data_api,
        "_recompute",
        lambda config: setattr(state, "config", config) or SimpleNamespace(time_ms=1.0),
    )

    response = client.post("/api/data/presets/max_otd", json=_mutation())

    assert response.status_code == 200
    assert state.config.subcontract_skus == ["HAN002"]


def test_preset_preserves_runtime_factory_master_data(monkeypatch):
    second_op = copy.deepcopy(state.engine_data.ops[0])
    second_op.id = "T1_M1_SKU2"
    second_op.sku = "SKU2"
    second_op.d = [0, 0, 0]
    state.engine_data.ops.append(second_op)
    state.config.machines["M1"].group = "Medias"
    state.config.machines["M1"].oee = 0.81
    state.config.machines["M2"] = MachineConfig("M2", "Grandes")
    state.config.tools["T2"] = {"primary": "M2", "setup_hours": 0.75}
    state.config.shifts = [
        ShiftConfig("A", 360, 900, "Cedo"),
        ShiftConfig("B", 900, 1380, "Tarde"),
    ]
    state.config.operators = {
        ("Grandes", "A"): 4,
        ("Grandes", "B"): 3,
        ("Medias", "A"): 8,
        ("Medias", "B"): 6,
    }
    state.config.twins = {"T1": ["SKU1", "SKU2"]}
    state.config.holidays = ["2026-04-25"]
    before = copy.deepcopy(state.config)
    monkeypatch.setattr(
        data_api,
        "_recompute",
        lambda config: setattr(state, "config", config)
        or SimpleNamespace(time_ms=1.0, score=state.score, gate_report=None),
    )

    response = TestClient(app).post("/api/data/presets/urgente", json=_mutation())

    assert response.status_code == 200
    for field in ("machines", "tools", "shifts", "operators", "twins", "holidays"):
        assert getattr(state.config, field) == getattr(before, field)
    assert state.config.urgency_threshold == 2


def test_add_twin_builds_complete_valid_group(monkeypatch):
    second_op = copy.deepcopy(state.engine_data.ops[0])
    second_op.id = "T1_M1_SKU2"
    second_op.sku = "SKU2"
    state.engine_data.ops.append(second_op)
    monkeypatch.setattr(
        "backend.copilot.executors_master._reschedule",
        lambda: state.score,
    )

    response = TestClient(app).post(
        "/api/data/twins",
        json=_mutation(
            {"tool_id": "T1", "sku_a": "SKU1", "sku_b": "SKU2"}
        ),
    )

    assert response.status_code == 200
    twin = state.engine_data.twin_groups[0]
    assert (
        twin.tool_id,
        twin.machine_id,
        twin.op_id_1,
        twin.op_id_2,
        twin.sku_1,
        twin.sku_2,
        twin.eco_lot_1,
        twin.eco_lot_2,
    ) == ("T1", "M1", "T1_M1_SKU1", "T1_M1_SKU2", "SKU1", "SKU2", 0, 0)


def test_add_twin_rejects_missing_or_wrong_tool_sku():
    response = TestClient(app).post(
        "/api/data/twins",
        json=_mutation(
            {"tool_id": "T1", "sku_a": "SKU1", "sku_b": "UNKNOWN"}
        ),
    )

    assert response.status_code == 400
    assert "operação única" in response.text
    assert state.config.twins == {}


def _assert_disk_failure_rolls_back_config_endpoint(
    monkeypatch,
    method: str,
    path: str,
    payload: dict,
) -> None:
    original_config = copy.deepcopy(state.config)
    original_engine = copy.deepcopy(state.engine_data)
    original_revision = state.plan_revision

    def fake_recompute(candidate):
        state.config = candidate
        state.engine_data.ops[0].d[0] = 999
        state.plan_revision += 1
        return SimpleNamespace(score={"otd": 99}, gate_report=None)

    monkeypatch.setattr(data_api, "_recompute", fake_recompute)
    monkeypatch.setattr(
        "backend.config.loader.save_config",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    response = TestClient(app, raise_server_exceptions=False).request(
        method,
        path,
        json=payload,
    )

    assert response.status_code == 500
    assert state.config == original_config
    assert state.engine_data == original_engine
    assert state.plan_revision == original_revision


def test_sku_planning_disk_failure_rolls_back(monkeypatch):
    _assert_disk_failure_rolls_back_config_endpoint(
        monkeypatch,
        "PUT",
        "/api/data/skus/SKU1/planning",
        _mutation({"planning_priority": 25}),
    )


def test_subcontracts_disk_failure_rolls_back(monkeypatch):
    _assert_disk_failure_rolls_back_config_endpoint(
        monkeypatch,
        "PUT",
        "/api/data/subcontracts",
        _mutation({"companies": [], "sku_subcontracts": {}}),
    )


def test_operators_disk_failure_rolls_back(monkeypatch):
    _assert_disk_failure_rolls_back_config_endpoint(
        monkeypatch,
        "PUT",
        "/api/data/operators",
        _mutation({"Grandes A": 7}),
    )


def test_preset_disk_failure_rolls_back(monkeypatch):
    _assert_disk_failure_rolls_back_config_endpoint(
        monkeypatch,
        "POST",
        "/api/data/presets/urgente",
        _mutation(),
    )


def test_max_otd_preset_preserves_active_mutations(monkeypatch):
    client = TestClient(app)
    state.active_mutations = [{"type": "machine_down", "params": {"machine_id": "M1"}}]
    state.default_config = _config()

    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        data_api,
        "_recompute_transactional",
        lambda config, _body=None, **_kwargs: setattr(state, "config", config)
        or SimpleNamespace(time_ms=1.0),
    )

    response = client.post("/api/data/presets/max_otd", json=_mutation())

    assert response.status_code == 200
    assert state.active_mutations == [{"type": "machine_down", "params": {"machine_id": "M1"}}]
    assert response.json()["simulation_active"] is True


def test_copilot_without_real_key_returns_503(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("PP1_OPENAI_API_KEY", "dummy")
    monkeypatch.delenv("PP1_LLM_BACKEND", raising=False)

    response = client.post(
        "/api/copilot/chat",
        json={"messages": [{"role": "user", "content": "qual é o score?"}]},
    )

    assert response.status_code == 503


def test_health_without_data_returns_null_dataset(monkeypatch):
    client = TestClient(app)
    state.engine_data = None
    state.segments = []
    state.dataset_info = {"id": "stale"}
    monkeypatch.setenv("PP1_OPENAI_API_KEY", "dummy")
    monkeypatch.delenv("PP1_LLM_BACKEND", raising=False)

    response = client.get("/api/copilot/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["has_data"] is False
    assert payload["n_segments"] == 0
    assert payload["dataset"] is None
    assert payload["copilot"] == {
        "available": False,
        "backend": "openai",
        "reason": "O Copilot ainda não tem uma chave configurada.",
    }


def test_cors_allows_local_frontend_and_rejects_arbitrary_sites():
    client = TestClient(app)
    preflight_headers = {
        "Access-Control-Request-Method": "GET",
    }

    allowed = client.options(
        "/api/copilot/health",
        headers={**preflight_headers, "Origin": "http://localhost:3000"},
    )
    rejected = client.options(
        "/api/copilot/health",
        headers={**preflight_headers, "Origin": "https://malicious.example"},
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_legacy_path_loader_is_disabled():
    response = TestClient(app).post(
        "/api/copilot/load",
        json={
            "isop_path": "/etc/passwd",
            "config_path": "/etc/passwd",
            "master_path": "/etc/passwd",
        },
    )

    assert response.status_code == 410
    assert "estado atual das máquinas" in response.json()["detail"]


def test_upload_api_does_not_expose_server_side_config_paths():
    schema = app.openapi()
    for path in ("/api/data/load/prepare", "/api/data/load"):
        parameter_names = {
            parameter["name"]
            for parameter in schema["paths"][path]["post"].get("parameters", [])
        }
        assert "config_path" not in parameter_names
        assert "master_path" not in parameter_names


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("isop.xls", b"legacy", "ficheiro .xlsx"),
        ("isop.xlsx", b"", "está vazio"),
        ("isop.xlsx", "não é um zip".encode(), "corrompido"),
    ],
)
def test_prepare_upload_rejects_unsupported_or_invalid_files(
    filename,
    content,
    message,
):
    with TestClient(app) as client:
        response = client.post(
            "/api/data/load/prepare",
            files={"file": (filename, content, "application/octet-stream")},
        )
        if filename.endswith(".xlsx") and content:
            assert response.status_code == 202
            job = _poll_load(client, response.json()["job"]["id"], {"failed"})
            assert message in job["error"]["message"]
        else:
            assert response.status_code == 400
            assert message in response.json()["detail"]


def _poll_load(client, job_id, statuses):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/data/load/jobs/{job_id}").json()["job"]
        if job["status"] in statuses:
            return job
        time.sleep(.01)
    raise AssertionError(job)


def test_prepare_upload_rejects_a_workbook_without_production_rows(monkeypatch):
    empty_engine = EngineData(
        ops=[],
        machines=[],
        twin_groups=[],
        client_demands={},
        workdays=["2026-03-17"],
        n_days=1,
    )
    monkeypatch.setattr(
        "backend.parser.isop_reader.read_isop",
        lambda *_args: ([], ["2026-03-17"], False),
    )
    monkeypatch.setattr(
        "backend.transform.transform.transform",
        lambda *_args: empty_engine,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/data/load/prepare",
            files={"file": ("empty.xlsx", b"parser mocked", "application/octet-stream")},
        )
        assert response.status_code == 202
        job = _poll_load(client, response.json()["job"]["id"], {"failed"})
        assert "não contém operações" in job["error"]["message"]


# Confirmation, approval, blocked candidates and dataset replacement are tested
# with their background lifecycle in test_load_jobs.py.


def test_sku_planning_preview_does_not_mutate_state(monkeypatch):
    client = TestClient(app)
    fake_result = ScheduleResult(
        segments=[],
        lots=[],
        score={
            "otd": 100.0,
            "otd_d": 100.0,
            "setups": 1,
            "tardy_count": 0,
            "earliness_avg_days": 0,
            "planning_penalty": 0,
        },
        time_ms=1.0,
        warnings=[],
        operator_alerts=[],
        journal=[],
    )

    monkeypatch.setattr(
        data_api,
        "_compute_schedule_for_preview",
        lambda _engine, _config: (fake_result, None),
    )

    response = client.post(
        "/api/data/skus/SKU1/planning/preview",
        json={"eco_lot": 1000},
    )

    assert response.status_code == 200
    assert state.config.sku_planning_rules == {}
    assert state.engine_data.ops[0].eco_lot == 0


def test_sku_planning_apply_persists_rule_and_recalculates(monkeypatch):
    client = TestClient(app)
    fake_result = ScheduleResult(
        segments=[],
        lots=[],
        score={
            "otd": 100.0,
            "otd_d": 100.0,
            "setups": 1,
            "tardy_count": 0,
            "earliness_avg_days": 0,
            "planning_penalty": 0,
        },
        time_ms=1.0,
        warnings=[],
        operator_alerts=[],
        journal=[],
    )

    def fake_recompute(config, _approval=None, **_kwargs):
        state.config = config
        state.update_schedule(fake_result)
        return fake_result

    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(data_api, "_recompute_transactional", fake_recompute)

    response = client.put(
        "/api/data/skus/SKU1/planning",
        json=_mutation({"eco_lot": 1000, "finish_buffer_days": 2}),
    )

    assert response.status_code == 200
    assert state.config.sku_planning_rules["SKU1"] == {
        "eco_lot": 1000,
        "finish_buffer_days": 2,
    }


def test_subcontracts_apply_persists_rules(monkeypatch):
    client = TestClient(app)
    fake_result = ScheduleResult(
        segments=[],
        lots=[],
        score={
            "otd": 100.0,
            "otd_d": 100.0,
            "setups": 1,
            "tardy_count": 0,
            "earliness_avg_days": 0,
            "planning_penalty": 0,
        },
        time_ms=1.0,
        warnings=[],
        operator_alerts=[],
        journal=[],
    )

    def fake_recompute(config, _approval=None, **_kwargs):
        state.config = config
        state.update_schedule(fake_result)
        return fake_result

    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(data_api, "_recompute_transactional", fake_recompute)

    response = client.put(
        "/api/data/subcontracts",
        json={
            **_mutation(),
            "companies": [{"id": "EXT1", "name": "EXT1", "lead_time_days": 3}],
            "sku_subcontracts": {
                "SKU1": {
                    "enabled": True,
                    "company_id": "EXT1",
                    "lead_time_days": 4,
                    "buffer_days": 1,
                }
            },
        },
    )

    assert response.status_code == 200
    assert state.config.sku_subcontracts["SKU1"]["company_id"] == "EXT1"
    assert state.config.subcontract_skus == ["SKU1"]


def test_subcontracts_simplified_payload_uses_one_week_lead(monkeypatch):
    client = TestClient(app)
    fake_result = ScheduleResult(
        segments=[],
        lots=[],
        score={
            "otd": 100.0,
            "otd_d": 100.0,
            "setups": 1,
            "tardy_count": 0,
            "earliness_avg_days": 0,
            "planning_penalty": 0,
        },
        time_ms=1.0,
        warnings=[],
        operator_alerts=[],
        journal=[],
    )

    def fake_recompute(config, _approval=None, **_kwargs):
        state.config = config
        state.update_schedule(fake_result)
        return fake_result

    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(data_api, "_recompute_transactional", fake_recompute)

    response = client.put(
        "/api/data/subcontracts",
        json={
            **_mutation(),
            "companies": [{"id": "SUBCONTRATO", "name": "Subcontrato", "lead_time_days": 7}],
            "sku_subcontracts": {
                "SKU1": {
                    "enabled": True,
                    "company_id": "SUBCONTRATO",
                    "lead_time_days": 7,
                    "buffer_days": 0,
                }
            },
        },
    )

    assert response.status_code == 200
    assert state.config.sku_subcontracts["SKU1"]["company_id"] == "SUBCONTRATO"
    assert state.config.sku_subcontracts["SKU1"]["lead_time_days"] == 7
    assert state.config.sku_subcontracts["SKU1"]["lead_time_workdays"] == 5
    assert state.config.sku_subcontracts["SKU1"]["buffer_days"] == 0


def test_revert_keeps_subcontract_config(monkeypatch):
    client = TestClient(app)
    state.config.sku_subcontracts = {
        "SKU1": {
            "enabled": True,
            "company_id": "SUBCONTRATO",
            "lead_time_days": 7,
            "buffer_days": 0,
        }
    }
    state.config.subcontract_companies = [
        {"id": "SUBCONTRATO", "name": "Subcontrato", "lead_time_days": 7}
    ]
    state.active_mutations = [
        {
            "type": "machine_down",
            "params": {"machine_id": "M1", "start": 0, "end": 0},
        }
    ]
    state.save_current()
    state.plan_revision += 1
    state.active_mutations = [
        {
            "type": "machine_down",
            "params": {"machine_id": "M1", "start": 0, "end": 0},
        },
        {
            "type": "operator_shortage",
            "params": {
                "group": "Grandes",
                "shift": "A",
                "start": 0,
                "end": 0,
                "count": 1,
                "note": "teste",
            },
        },
    ]

    response = client.post("/api/data/revert", json=_mutation())

    assert response.status_code == 200
    assert state.config.sku_subcontracts["SKU1"]["lead_time_days"] == 7
    assert state.config.subcontract_companies[0]["id"] == "SUBCONTRATO"


def test_subcontracts_apply_rejects_enabled_rule_without_company(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)

    response = client.put(
        "/api/data/subcontracts",
        json={
            **_mutation(),
            "companies": [],
            "sku_subcontracts": {"SKU1": {"enabled": True}},
        },
    )

    assert response.status_code == 400
    assert "empresa" in response.json()["detail"]
    assert state.config.sku_subcontracts == {}


def test_subcontracts_preview_does_not_mutate_state(monkeypatch):
    client = TestClient(app)
    fake_result = ScheduleResult(
        segments=[],
        lots=[],
        score={
            "otd": 100.0,
            "otd_d": 100.0,
            "setups": 1,
            "tardy_count": 0,
            "earliness_avg_days": 0,
            "planning_penalty": 0,
        },
        time_ms=1.0,
        warnings=[],
        operator_alerts=[],
        journal=[],
    )

    monkeypatch.setattr(
        data_api,
        "_compute_schedule_for_preview",
        lambda _engine, _config: (fake_result, None),
    )

    response = client.post(
        "/api/data/subcontracts/preview",
        json={
            "companies": [{"id": "EXT1", "name": "EXT1", "lead_time_days": 3}],
            "sku_subcontracts": {"SKU1": {"enabled": True, "company_id": "EXT1"}},
        },
    )

    assert response.status_code == 200
    assert state.config.sku_subcontracts == {}
    assert state.config.subcontract_companies == []
    assert state.saved_schedule is None
    assert state.active_mutations == []


def test_subcontracts_preview_rejects_unknown_company():
    client = TestClient(app)

    response = client.post(
        "/api/data/subcontracts/preview",
        json={
            "companies": [],
            "sku_subcontracts": {"SKU1": {"enabled": True, "company_id": "EXT1"}},
        },
    )

    assert response.status_code == 400
    assert "desconhecida" in response.json()["detail"]
    assert state.config.sku_subcontracts == {}


def test_ops_catalog_preserve_configured_subcontract_refs_without_isop():
    client = TestClient(app)
    sku = "CF589MMA1A02.20"
    state.config.subcontract_skus = [sku]
    state.config.subcontract_companies = [
        {
            "id": "SUBCONTRATO",
            "name": "Subcontrato",
            "lead_time_days": 7,
            "lead_time_workdays": 5,
        }
    ]
    state.config.sku_subcontracts = {
        sku: {
            "enabled": True,
            "company_id": "SUBCONTRATO",
            "lead_time_days": 7,
            "lead_time_workdays": 5,
            "buffer_days": 0,
        }
    }

    ops = client.get("/api/data/ops")
    catalog = client.get("/api/data/catalog")

    assert ops.status_code == 200
    cf_row = next(row for row in ops.json() if row["sku"] == sku)
    assert cf_row["active"] is False
    assert cf_row["subcontract_company_id"] == "SUBCONTRATO"
    assert cf_row["subcontract_lead_time_calendar_days"] == 7
    assert cf_row["subcontract_lead_time_workdays"] == 5
    assert catalog.status_code == 200
    cf_ref = next(row for row in catalog.json()["references"] if row["id"] == sku)
    assert cf_ref["source"] == "config"
    assert cf_ref["has_override"] is True


def test_late_deliveries_contract_returns_avg_delay_and_explanation():
    client = TestClient(app)
    state.late_deliveries = LateDeliveryReport(
        tardy_count=1,
        avg_delay=2.0,
        by_cause={"capacity": 1},
        analyses=[
            TardyAnalysis(
                lot_id="L1",
                op_id="T1_M1_SKU1",
                sku="SKU1",
                machine_id="M1",
                edd=1,
                completion_day=3,
                delay_days=2,
                root_cause="capacity",
                explanation="Capacidade insuficiente.",
                capacity_gap_min=120.0,
                competing_lots=[],
            )
        ],
        worst_machine="M1",
        suggestion="1 lote em atraso.",
    )

    response = client.get("/api/data/late")

    assert response.status_code == 200
    body = response.json()
    assert body["avg_delay"] == 2.0
    assert body["analyses"][0]["explanation"] == "Capacidade insuficiente."
    assert "suggestion" not in body["analyses"][0]


def test_compacting_the_active_plan_publishes_the_improvement_summary(monkeypatch):
    """The "Recalcular" button path must carry the same explanations as the
    full recalculation (tool transfers kept and why)."""

    from backend.scheduler.types import ScheduleResult
    from backend.types import EngineData

    result = ScheduleResult(
        segments=[], lots=[], score={}, time_ms=1.0, warnings=[], operator_alerts=[],
        improvement_report={"status": "completed", "moves_accepted": 2},
    )
    captured = []
    monkeypatch.setattr(data_api.state, "engine_data", EngineData(
        ops=[], machines=[], twin_groups=[], client_demands={}, workdays=[], n_days=0,
    ))
    monkeypatch.setattr("backend.plans.frozen.compact_preserving_started_lots",
                        lambda *_args, **_kwargs: result)
    monkeypatch.setattr("backend.scheduler.gates.build_gate_report",
                        lambda *_args, **_kwargs: {"status": "best_effort"})
    monkeypatch.setattr("backend.transform.calendars.apply_calendars", lambda *_a, **_k: None)
    monkeypatch.setattr("backend.config.planning.synchronize_active_twin_groups",
                        lambda *_a, **_k: None)
    monkeypatch.setattr(data_api.state, "update_schedule", captured.append)

    data_api._compact_active_schedule(data_api.state.config or FactoryConfig())

    summary = captured[0].gate_report["improvement"]
    assert summary["status"] == "completed"
    assert summary["moves_accepted"] == 2
    assert summary["tool_transfers"]["remaining"] == 0
