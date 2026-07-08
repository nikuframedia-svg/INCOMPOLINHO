"""Regression tests for API validation and local app contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.api import data as data_api
from backend.api.copilot import app
from backend.analytics.late_delivery import LateDeliveryReport, TardyAnalysis
from backend.config.types import FactoryConfig, MachineConfig
from backend.copilot.state import state
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


@pytest.fixture(autouse=True)
def loaded_state():
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "segments": state.segments,
        "lots": state.lots,
        "score": state.score,
        "default_config": state.default_config,
        "saved_schedule": state.saved_schedule,
        "saved_mutations": state.saved_mutations,
        "active_mutations": state.active_mutations,
        "dataset_info": state.dataset_info,
        "trust_index": state.trust_index,
        "learning_info": state.learning_info,
        "gate_report": state.gate_report,
        "late_deliveries": state.late_deliveries,
    }
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
    yield
    for key, value in previous.items():
        setattr(state, key, value)


def test_config_validation_returns_400(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)

    response = client.put("/api/data/config", json={"jit_threshold": "abc"})

    assert response.status_code == 400
    assert "jit_threshold" in response.json()["detail"]


def test_config_bool_strings_are_parsed(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        data_api,
        "_recompute",
        lambda _config: SimpleNamespace(time_ms=12.3),
    )

    response = client.put("/api/data/config", json={"jit_enabled": "false"})

    assert response.status_code == 200
    assert state.config.jit_enabled is False


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

    response = client.put("/api/data/config", json={"compact_enabled": "true"})

    assert response.status_code == 200
    assert state.config.compact_enabled is True


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


def test_simulate_apply_composes_and_revert_restores_active_mutations(monkeypatch):
    client = TestClient(app)
    state.active_mutations = [{"type": "machine_down", "params": {"machine_id": "M1"}}]
    captured = {}

    def fake_simulate(_engine_data, _score, mutations, config=None):
        captured["types"] = [m.type for m in mutations]
        return _simulation_result()

    monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)

    response = client.post(
        "/api/data/simulate-apply",
        json={"mutations": [{"type": "operator_shortage", "params": {"note": "teste"}}]},
    )

    assert response.status_code == 200
    assert captured["types"] == ["machine_down", "operator_shortage"]
    assert [m["type"] for m in state.active_mutations] == ["machine_down", "operator_shortage"]

    reverted = client.post("/api/data/revert")

    assert reverted.status_code == 200
    assert state.active_mutations == [{"type": "machine_down", "params": {"machine_id": "M1"}}]


def test_simulate_preview_composes_active_mutations_and_dedupes(monkeypatch):
    client = TestClient(app)
    state.active_mutations = [{"type": "machine_down", "params": {"machine_id": "M1"}}]
    captured = {}

    def fake_simulate(_engine_data, _score, mutations, config=None):
        captured["types"] = [m.type for m in mutations]
        return _simulation_result()

    monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)

    response = client.post(
        "/api/data/simulate",
        json={
            "mutations": [
                {"type": "machine_down", "params": {"machine_id": "M1"}},
                {"type": "operator_shortage", "params": {"note": "teste"}},
            ]
        },
    )

    assert response.status_code == 200
    assert captured["types"] == ["machine_down", "operator_shortage"]


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

    def fake_simulate(_engine_data, _score, _mutations, config=None):
        return _simulation_result(gate_report=failed_gate)

    monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)

    response = client.post(
        "/api/data/simulate-apply",
        json={"mutations": [{"type": "operator_shortage", "params": {"note": "teste"}}]},
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

    response = client.put("/api/data/config", json={"jit_threshold": original_threshold + 1})

    assert response.status_code == 409
    assert response.json()["detail"]["gate_report"] == failed_gate
    assert state.config.jit_threshold == original_threshold


def test_ctp_rejects_invalid_qty_and_deadline():
    client = TestClient(app)

    bad_qty = client.post("/api/data/ctp", json={"sku": "SKU1", "qty": 0, "deadline": 1})
    bad_deadline = client.post("/api/data/ctp", json={"sku": "SKU1", "qty": 1, "deadline": 99})

    assert bad_qty.status_code == 400
    assert bad_deadline.status_code == 400


def test_ctp_uses_effective_internal_deadline(monkeypatch):
    client = TestClient(app)
    state.engine_data.ops[0].finish_buffer_days = 2
    captured = {}

    def fake_ctp(sku, qty, deadline, segments, engine_data, config=None):
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
        )

    monkeypatch.setattr("backend.analytics.ctp.compute_ctp", fake_ctp)

    response = client.post("/api/data/ctp", json={"sku": "SKU1", "qty": 10, "deadline": 2})

    assert response.status_code == 200
    assert captured["deadline"] == 0
    assert response.json()["delivery_deadline"] == 2
    assert response.json()["effective_deadline"] == 0


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

    def fake_simulate(_engine_data, _score, mutations, config=None):
        captured["types"] = [m.type for m in mutations]
        return _simulation_result(summary="rush")

    monkeypatch.setattr("backend.analytics.ctp.compute_ctp", fake_ctp)
    monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)

    response = client.post("/api/data/ctp-apply", json={"sku": "SKU1", "qty": 10, "deadline": 2})

    assert response.status_code == 200
    assert captured["types"] == ["machine_down", "rush_order"]
    assert [m["type"] for m in state.active_mutations] == ["machine_down", "rush_order"]
    assert response.json()["promise"]["effective_deadline"] == 2


def test_recalculate_returns_result_time(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(
        data_api,
        "_recompute",
        lambda _config: SimpleNamespace(time_ms=123.4),
    )

    response = client.post("/api/data/recalculate", json={})

    assert response.status_code == 200
    assert response.json()["time_ms"] == 123.4


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

    response = client.post("/api/data/presets/max_otd", json={})

    assert response.status_code == 200
    assert state.config.subcontract_skus == ["HAN002"]


def test_max_otd_preset_preserves_active_mutations(monkeypatch):
    client = TestClient(app)
    state.active_mutations = [{"type": "machine_down", "params": {"machine_id": "M1"}}]
    state.default_config = _config()

    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        data_api,
        "_recompute_transactional",
        lambda config: setattr(state, "config", config) or SimpleNamespace(time_ms=1.0),
    )

    response = client.post("/api/data/presets/max_otd", json={})

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


def test_health_without_data_returns_null_dataset():
    client = TestClient(app)
    state.engine_data = None
    state.segments = []
    state.dataset_info = {"id": "stale"}

    response = client.get("/api/copilot/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "has_data": False,
        "n_segments": 0,
        "dataset": None,
    }


def test_upload_returns_dataset_metadata_and_clears_simulation(monkeypatch):
    client = TestClient(app)
    fake_result = ScheduleResult(
        segments=[],
        lots=[],
        score={"otd": 100.0, "otd_d": 100.0, "setups": 1, "tardy_count": 0},
        time_ms=12.3,
        warnings=[],
        operator_alerts=[],
        journal=[],
    )
    trust = SimpleNamespace(score=100, gate="full_auto")

    monkeypatch.setattr("backend.config.loader.load_config", lambda *_args, **_kwargs: _config())
    monkeypatch.setattr("backend.parser.isop_reader.read_isop", lambda *_args: ([], [], False))
    monkeypatch.setattr("backend.transform.transform.transform", lambda *_args: _engine())
    monkeypatch.setattr("backend.cpo.optimize", lambda *_args, **_kwargs: fake_result)
    monkeypatch.setattr("backend.dqa.compute_trust_index", lambda *_args, **_kwargs: trust)

    state.saved_schedule = SimpleNamespace()
    state.active_mutations = [{"type": "machine_down", "params": {"machine_id": "M1"}}]

    first = client.post(
        "/api/data/load",
        files={"file": ("first_isop.xlsx", b"fake", "application/octet-stream")},
    )
    first_body = first.json()
    first_dataset_id = first_body["dataset"]["id"]

    state.saved_schedule = SimpleNamespace()
    state.active_mutations = [{"type": "machine_down", "params": {"machine_id": "M1"}}]
    second = client.post(
        "/api/data/load",
        files={"file": ("second_isop.xlsx", b"fake", "application/octet-stream")},
    )
    second_body = second.json()

    assert first.status_code == 200
    assert first_body["dataset"]["filename"] == "first_isop.xlsx"
    assert first_body["dataset"]["n_ops"] == 1
    assert first_body["dataset"]["trust_score"] == 100
    assert first_body["dataset"]["otd"] == 100.0
    assert second.status_code == 200
    assert second_body["dataset"]["filename"] == "second_isop.xlsx"
    assert second_body["dataset"]["id"] != first_dataset_id


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

    def fake_recompute(config):
        state.config = config
        state.update_schedule(fake_result)
        return fake_result

    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(data_api, "_recompute_transactional", fake_recompute)

    response = client.put(
        "/api/data/skus/SKU1/planning",
        json={"eco_lot": 1000, "finish_buffer_days": 2},
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

    def fake_recompute(config):
        state.config = config
        state.update_schedule(fake_result)
        return fake_result

    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(data_api, "_recompute_transactional", fake_recompute)

    response = client.put(
        "/api/data/subcontracts",
        json={
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

    def fake_recompute(config):
        state.config = config
        state.update_schedule(fake_result)
        return fake_result

    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(data_api, "_recompute_transactional", fake_recompute)

    response = client.put(
        "/api/data/subcontracts",
        json={
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
    state.active_mutations = [{"type": "machine_down", "params": {"machine_id": "M1"}}]
    state.save_current()
    state.active_mutations = [
        {"type": "machine_down", "params": {"machine_id": "M1"}},
        {"type": "operator_shortage", "params": {"note": "teste"}},
    ]

    response = client.post("/api/data/revert")

    assert response.status_code == 200
    assert state.config.sku_subcontracts["SKU1"]["lead_time_days"] == 7
    assert state.config.subcontract_companies[0]["id"] == "SUBCONTRATO"


def test_subcontracts_apply_rejects_enabled_rule_without_company(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)

    response = client.put(
        "/api/data/subcontracts",
        json={
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
