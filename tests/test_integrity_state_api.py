"""Integrity regressions for simulation/config state and API hard gates."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.data import router
from backend.config.presets import apply_preset
from backend.config.types import FactoryConfig
from backend.copilot.state import CopilotState, state
from backend.scheduler.types import ScheduleResult
from backend.simulator.simulator import DeltaReport, SimulateResponse
from backend.types import EOp, EngineData, MachineInfo


def _schedule(score: dict | None = None) -> ScheduleResult:
    return ScheduleResult(
        segments=[],
        lots=[],
        score=score or {"otd": 100.0, "otd_d": 100.0},
        warnings=[],
        operator_alerts=[],
        time_ms=0.0,
    )


def test_subcontract_survives_max_otd():
    current = FactoryConfig()
    current.subcontract_skus = {"HAN002": 5}
    default = FactoryConfig()

    updated = apply_preset(current, "max_otd", base_config=default)

    assert updated.subcontract_skus == {"HAN002": 5}
    assert updated.jit_enabled is True


def test_revert_simulation_does_not_revert_subcontract():
    local = CopilotState()
    local.config = FactoryConfig()
    local.config.subcontract_skus = {"HAN002": 5}
    local.update_schedule(_schedule({"otd": 100.0}))

    local.save_current(kind="simulation")
    local.config.subcontract_skus = {"HAN002": 7}
    kind = local.restore_saved("simulation")

    assert kind == "simulation"
    assert local.config.subcontract_skus == {"HAN002": 7}


def test_revert_config_does_not_hide_active_mutations():
    local = CopilotState()
    local.config = FactoryConfig()
    local.active_mutations = [
        {"type": "machine_down", "params": {"machine_id": "PRM031", "start": -6, "end": -1}},
    ]
    local.active_simulation_summary = ["Máquina PRM031 parada dias -6--1"]
    local.update_schedule(_schedule({"otd": 100.0}))

    local.save_current(kind="config")
    local.config.jit_enabled = not local.config.jit_enabled
    kind = local.restore_saved("config")

    assert kind == "config"
    assert local.active_mutations == [
        {"type": "machine_down", "params": {"machine_id": "PRM031", "start": -6, "end": -1}},
    ]
    assert local.active_simulation_summary == ["Máquina PRM031 parada dias -6--1"]


def test_simulate_apply_uses_safe_mode_and_rejects_invalid(monkeypatch):
    captured: dict[str, str] = {}

    def fake_simulate(engine_data, baseline_score, mutations, config=None, mode="quick"):
        captured["mode"] = mode
        return SimulateResponse(
            segments=[],
            lots=[],
            score={"otd": 100.0, "otd_d": 100.0, "tardy_count": 0, "tool_conflicts": 1},
            delta=DeltaReport(
                otd_before=100.0,
                otd_after=100.0,
                otd_d_before=100.0,
                otd_d_after=100.0,
                setups_before=0,
                setups_after=0,
                earliness_before=0.0,
                earliness_after=0.0,
                tardy_before=0,
                tardy_after=0,
            ),
            time_ms=1.0,
            summary=["invalid"],
        )

    monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)

    old = {
        "engine_data": state.engine_data,
        "config": state.config,
        "segments": state.segments,
        "lots": state.lots,
        "score": state.score,
        "active_mutations": state.active_mutations,
        "active_simulation_summary": state.active_simulation_summary,
        "simulation_snapshot": state.simulation_snapshot,
        "config_snapshot": state.config_snapshot,
        "saved_schedule": state.saved_schedule,
        "saved_snapshot": state.saved_snapshot,
    }
    try:
        state.engine_data = object()
        state.config = FactoryConfig()
        state.update_schedule(_schedule({"otd": 100.0, "otd_d": 100.0}))
        state.active_mutations = []
        state.active_simulation_summary = []
        state.clear_revert()

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.post(
            "/api/data/simulate-apply",
            json={"mutations": [{"type": "machine_down", "params": {"machine_id": "PRM031"}}]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "invalid"
        assert body["hard_gate_violations"] == {"tool_conflicts": 1}
        assert body["plan_violations"] == {"tool_conflicts": 1}
        assert captured["mode"] == "normal"
        assert state.active_mutations == []
        assert state.simulation_snapshot is None
    finally:
        for key, value in old.items():
            setattr(state, key, value)


def test_simulate_apply_rejects_otd_regression_without_physical_gates(monkeypatch):
    def fake_simulate(engine_data, baseline_score, mutations, config=None, mode="quick"):
        return SimulateResponse(
            segments=[],
            lots=[],
            score={
                "otd": 100.0,
                "otd_d": 73.0,
                "tardy_count": 21,
                "otd_d_failures": 27,
                "tool_conflicts": 0,
                "machine_overlaps": 0,
                "day_cap_violations": 0,
                "ghost_segments": 0,
                "blocked_machine_segments": 0,
                "blocked_tool_segments": 0,
                "setup_sequence_violations": 0,
                "run_lot_order_violations": 0,
            },
            delta=DeltaReport(
                otd_before=100.0,
                otd_after=100.0,
                otd_d_before=100.0,
                otd_d_after=73.0,
                setups_before=0,
                setups_after=0,
                earliness_before=0.0,
                earliness_after=0.0,
                tardy_before=0,
                tardy_after=21,
            ),
            time_ms=1.0,
            summary=["OTD-D desceu 27.0%"],
        )

    monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)

    old = {
        "engine_data": state.engine_data,
        "config": state.config,
        "segments": state.segments,
        "lots": state.lots,
        "score": state.score,
        "active_mutations": state.active_mutations,
        "active_simulation_summary": state.active_simulation_summary,
        "simulation_snapshot": state.simulation_snapshot,
        "config_snapshot": state.config_snapshot,
        "saved_schedule": state.saved_schedule,
        "saved_snapshot": state.saved_snapshot,
    }
    try:
        state.engine_data = object()
        state.config = FactoryConfig()
        state.update_schedule(_schedule({"otd": 100.0, "otd_d": 100.0, "tardy_count": 0}))
        state.active_mutations = []
        state.active_simulation_summary = []
        state.clear_revert()

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.post(
            "/api/data/simulate-apply",
            json={"mutations": [{"type": "machine_down", "params": {"machine_id": "PRM031"}}]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "invalid"
        assert body["hard_gate_violations"] == {}
        assert body["plan_violations"] == {
            "otd_d_below_100": 73.0,
            "tardy_count": 21,
            "otd_d_failures": 27,
        }
        assert state.active_mutations == []
        assert state.simulation_snapshot is None
    finally:
        for key, value in old.items():
            setattr(state, key, value)


def test_config_update_rejects_invalid_recompute_with_active_mutations(monkeypatch):
    saved_configs: list[FactoryConfig] = []

    def fake_simulate(engine_data, baseline_score, mutations, config=None, mode="quick"):
        return SimulateResponse(
            segments=[],
            lots=[],
            score={
                "otd": 100.0,
                "otd_d": 70.0,
                "tardy_count": 38,
                "otd_d_failures": 30,
                "tool_conflicts": 3,
                "machine_overlaps": 0,
                "day_cap_violations": 0,
                "ghost_segments": 0,
                "blocked_machine_segments": 0,
                "blocked_tool_segments": 0,
                "setup_sequence_violations": 0,
                "run_lot_order_violations": 0,
            },
            delta=DeltaReport(
                otd_before=100.0,
                otd_after=100.0,
                otd_d_before=100.0,
                otd_d_after=70.0,
                setups_before=0,
                setups_after=0,
                earliness_before=0.0,
                earliness_after=0.0,
                tardy_before=0,
                tardy_after=38,
            ),
            time_ms=1.0,
            summary=["OTD-D desceu 30.0%"],
        )

    monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)
    monkeypatch.setattr("backend.config.loader.save_config", lambda config: saved_configs.append(config))

    old = {
        "engine_data": state.engine_data,
        "config": state.config,
        "segments": state.segments,
        "lots": state.lots,
        "score": state.score,
        "active_mutations": state.active_mutations,
        "active_simulation_summary": state.active_simulation_summary,
        "simulation_snapshot": state.simulation_snapshot,
        "config_snapshot": state.config_snapshot,
        "saved_schedule": state.saved_schedule,
        "saved_snapshot": state.saved_snapshot,
    }
    try:
        state.engine_data = object()
        state.config = FactoryConfig()
        state.update_schedule(_schedule({"otd": 100.0, "otd_d": 100.0, "tardy_count": 0}))
        state.active_mutations = [
            {"type": "tool_down", "params": {"tool_id": "NO_TOOL_QA", "start": "-1", "end": "-1"}},
        ]
        state.active_simulation_summary = ["Ferramenta NO_TOOL_QA indisponível dias -1--1"]
        state.clear_revert()
        original_max_run_days = state.config.max_run_days

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.put("/api/data/config", json={"max_run_days": 1})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "invalid"
        assert body["hard_gate_violations"] == {"tool_conflicts": 3}
        assert body["plan_violations"] == {
            "tool_conflicts": 3,
            "otd_d_below_100": 70.0,
            "tardy_count": 38,
            "otd_d_failures": 30,
        }
        assert state.config.max_run_days == original_max_run_days
        assert state.score == {"otd": 100.0, "otd_d": 100.0, "tardy_count": 0}
        assert state.config_snapshot is None
        assert saved_configs == []
    finally:
        for key, value in old.items():
            setattr(state, key, value)


def test_master_data_edit_reapplies_active_mutations(monkeypatch):
    captured: dict[str, object] = {}

    def fake_simulate(engine_data, baseline_score, mutations, config=None, mode="quick"):
        captured["mode"] = mode
        captured["mutations"] = [(m.type, m.params) for m in mutations]
        return SimulateResponse(
            segments=[],
            lots=[],
            score={
                "otd": 100.0,
                "otd_d": 100.0,
                "tardy_count": 0,
                "tool_conflicts": 0,
                "machine_overlaps": 0,
                "day_cap_violations": 0,
                "ghost_segments": 0,
                "blocked_machine_segments": 0,
                "blocked_tool_segments": 0,
                "setup_sequence_violations": 0,
                "run_lot_order_violations": 0,
            },
            delta=DeltaReport(
                otd_before=100.0,
                otd_after=100.0,
                otd_d_before=100.0,
                otd_d_after=100.0,
                setups_before=0,
                setups_after=0,
                earliness_before=0.0,
                earliness_after=0.0,
                tardy_before=0,
                tardy_after=0,
            ),
            time_ms=1.0,
            summary=["Máquina PRM019 parada dias -1--1", "Sem alterações significativas nos KPIs."],
        )

    monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)
    monkeypatch.setattr("backend.copilot.executors_master.save_config", lambda config: None)

    old = {
        "engine_data": state.engine_data,
        "config": state.config,
        "segments": state.segments,
        "lots": state.lots,
        "score": state.score,
        "active_mutations": state.active_mutations,
        "active_simulation_summary": state.active_simulation_summary,
        "simulation_snapshot": state.simulation_snapshot,
        "config_snapshot": state.config_snapshot,
        "saved_schedule": state.saved_schedule,
        "saved_snapshot": state.saved_snapshot,
    }
    try:
        op = EOp(
            id="OP1_M1_SKU1",
            sku="SKU1",
            client="CLIENT",
            designation="Part",
            m="M1",
            t="T1",
            pH=100.0,
            sH=0.5,
            operators=1,
            eco_lot=100,
            alt=None,
            stk=0,
            backlog=0,
            d=[0, 100],
            oee=0.66,
            wip=0,
        )
        state.engine_data = EngineData(
            ops=[op],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
            twin_groups=[],
            client_demands={},
            workdays=["2026-03-02", "2026-03-03"],
            n_days=2,
            holidays=[],
        )
        state.config = FactoryConfig()
        state.config.tools["T1"] = {"primary": "M1", "alt": None, "setup_hours": 0.5}
        state.update_schedule(_schedule({"otd": 100.0, "otd_d": 100.0, "tardy_count": 0}))
        state.active_mutations = [
            {"type": "machine_down", "params": {"machine_id": "PRM019", "start": "-1", "end": "-1"}},
        ]
        state.active_simulation_summary = ["old summary"]
        state.clear_revert()

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.put("/api/data/tools/T1", json={"setup_hours": 0.5})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert captured["mode"] == "normal"
        assert captured["mutations"] == [
            ("machine_down", {"machine_id": "PRM019", "start": "-1", "end": "-1"}),
        ]
        assert state.active_mutations == [
            {"type": "machine_down", "params": {"machine_id": "PRM019", "start": "-1", "end": "-1"}},
        ]
        assert state.active_simulation_summary == [
            "Máquina PRM019 parada dias -1--1",
            "Sem alterações significativas nos KPIs.",
        ]
        assert state.score["otd_d"] == 100.0
    finally:
        for key, value in old.items():
            setattr(state, key, value)


def test_subcontract_accepts_op_prefix_alias(monkeypatch):
    monkeypatch.setattr("backend.api.data._recompute", lambda config: None)
    monkeypatch.setattr("backend.config.loader.save_config", lambda config: None)

    old = {
        "engine_data": state.engine_data,
        "config": state.config,
        "segments": state.segments,
        "lots": state.lots,
        "score": state.score,
        "active_mutations": state.active_mutations,
        "active_simulation_summary": state.active_simulation_summary,
        "simulation_snapshot": state.simulation_snapshot,
        "config_snapshot": state.config_snapshot,
        "saved_schedule": state.saved_schedule,
        "saved_snapshot": state.saved_snapshot,
    }
    try:
        op = EOp(
            id="HAN002_PRM043_CF589MMA1A02.20",
            sku="CF589MMA1A02.20",
            client="HANON",
            designation="HV Protection Sheet",
            m="PRM043",
            t="BFP000",
            pH=100.0,
            sH=0.5,
            operators=1,
            eco_lot=100,
            alt=None,
            stk=0,
            backlog=0,
            d=[0, 100],
            oee=0.66,
            wip=0,
        )
        state.engine_data = EngineData(
            ops=[op],
            machines=[MachineInfo(id="PRM043", group="Grandes", day_capacity=1020)],
            twin_groups=[],
            client_demands={},
            workdays=["2026-03-02", "2026-03-03"],
            n_days=2,
            holidays=[],
        )
        state.config = FactoryConfig()
        state.update_schedule(_schedule({"otd": 100.0, "otd_d": 100.0}))
        state.clear_revert()

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        response = client.put(
            "/api/data/subcontract",
            json={"sku": "HAN002", "enabled": True, "lead_days": 5},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["sku"] == "CF589MMA1A02.20"
        assert body["alias"] == "HAN002"
        assert state.config.subcontract_skus == {"CF589MMA1A02.20": 5}
    finally:
        for key, value in old.items():
            setattr(state, key, value)
