"""Tests for Copilot — Spec 10."""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from backend.config.loader import _min_to_time, load_config, save_config
from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.copilot.engine import EXECUTORS, WIDGET_TOOLS, execute_tool
from backend.copilot.state import CopilotState, state
from backend.copilot.tools import TOOLS
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData, EOp, MachineInfo, TwinGroup


# ─── Fixtures ─────────────────────────────────────────────────────────────

def _eop(
    op_id: str = "T1_M1_SKU1",
    sku: str = "SKU1",
    machine: str = "M1",
    tool: str = "T1",
    d: list[int] | None = None,
    pH: float = 100.0,
    sH: float = 0.5,
    oee: float = 0.66,
    alt: str | None = None,
    eco_lot: int = 0,
) -> EOp:
    return EOp(
        id=op_id, sku=sku, client="CLIENTE", designation="Peça teste",
        m=machine, t=tool, pH=pH, sH=sH, operators=1,
        eco_lot=eco_lot, alt=alt, stk=0, backlog=0,
        d=d or [0, 500, 0, 300, 0, 200, 0, 0, 0, 0], oee=oee, wip=0,
    )


def _engine(
    ops: list[EOp] | None = None,
    n_days: int = 10,
    twin_groups: list[TwinGroup] | None = None,
) -> EngineData:
    if ops is None:
        ops = [
            _eop("T1_M1_SKU1", "SKU1", "M1", "T1", alt="M2"),
            _eop("T2_M2_SKU2", "SKU2", "M2", "T2", d=[0, 0, 400, 0, 300, 0, 0, 0, 0, 0]),
            _eop("T3_M1_SKU3", "SKU3", "M1", "T3", d=[0, 600, 0, 0, 400, 0, 0, 0, 0, 0]),
        ]
    machine_ids = list({op.m for op in ops})
    for op in ops:
        if op.alt and op.alt not in machine_ids:
            machine_ids.append(op.alt)
    machines = [MachineInfo(id=m, group="Grandes", day_capacity=DAY_CAP) for m in machine_ids]
    return EngineData(
        ops=ops, machines=machines, twin_groups=twin_groups or [],
        client_demands={},
        workdays=[f"2026-03-{i+5:02d}" for i in range(n_days)],
        n_days=n_days, holidays=[],
    )


def _setup_state():
    """Initialize state with test data."""
    config = FactoryConfig()
    config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes", active=True),
        "M2": MachineConfig(id="M2", group="Grandes", active=True),
    }
    config.tools = {
        "T1": {"primary": "M1", "alt": "M2", "setup_hours": 0.5},
        "T2": {"primary": "M2", "setup_hours": 0.5},
        "T3": {"primary": "M1", "setup_hours": 0.5},
    }

    engine = _engine()
    result = schedule_all(engine, audit=True, config=config)

    state.engine_data = engine
    state.config = config
    state.active_mutations = []
    state.clear_revert()
    state.update_schedule(result)
    return engine, config, result


# ─── TestSaveConfig ───────────────────────────────────────────────────────

class TestSaveConfig:
    def test_min_to_time(self):
        assert _min_to_time(420) == "07:00"
        assert _min_to_time(930) == "15:30"
        assert _min_to_time(1440) == "00:00"
        assert _min_to_time(0) == "00:00"
        assert _min_to_time(60) == "01:00"

    def test_roundtrip(self):
        """load → save → load produces equivalent config."""
        original = FactoryConfig()
        original.machines = {
            "PRM019": MachineConfig("PRM019", "Grandes", True, 1020),
            "PRM042": MachineConfig("PRM042", "Medias", True, 1020),
        }
        original.tools = {"BFP079": {"primary": "PRM019", "alt": "PRM042", "setup_hours": 1.0}}
        original.twins = {"BFP079": ["SKU_A", "SKU_B"]}
        original.holidays = ["2026-01-01", "2026-12-25"]
        original.subcontract_skus = {"SKU_A": 5}

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name

        try:
            save_config(original, path)
            loaded = load_config(path)

            assert loaded.day_capacity_min == original.day_capacity_min
            assert len(loaded.tools) == len(original.tools)
            assert loaded.subcontract_skus == {"SKU_A": 5}
            assert len(loaded.twins) == len(original.twins)
            assert loaded.oee_default == original.oee_default
            assert loaded.jit_enabled == original.jit_enabled
            assert len(loaded.holidays) == len(original.holidays)
        finally:
            os.unlink(path)


# ─── TestToolSchemas ──────────────────────────────────────────────────────

class TestToolSchemas:
    def test_tool_count(self):
        assert len(TOOLS) == 44

    def test_all_tools_have_executor(self):
        for tool in TOOLS:
            name = tool["function"]["name"]
            assert name in EXECUTORS, f"Tool {name} has no executor"


# ─── TestQueryExecutors ───────────────────────────────────────────────────

class TestQueryExecutors:
    def setup_method(self):
        _setup_state()

    def test_ver_score(self):
        result, is_widget = execute_tool("ver_score", "{}")
        data = json.loads(result)
        assert "otd" in data
        assert "tardy_count" in data
        assert not is_widget

    def test_explicar_referencia_found(self):
        result, _ = execute_tool("explicar_referencia", json.dumps({"sku": "SKU1"}))
        data = json.loads(result)
        assert data["sku"] == "SKU1"
        assert data["maquina"] == "M1"
        assert data["ferramenta"] == "T1"
        assert "error" not in data

    def test_explicar_referencia_not_found(self):
        result, _ = execute_tool("explicar_referencia", json.dumps({"sku": "NOPE"}))
        data = json.loads(result)
        assert "error" in data

    def test_ver_producao_dia(self):
        result, _ = execute_tool("ver_producao_dia", json.dumps({"dia": 1}))
        data = json.loads(result)
        assert "maquinas" in data

    def test_ver_carga_maquinas(self):
        result, _ = execute_tool("ver_carga_maquinas", "{}")
        data = json.loads(result)
        assert "carga" in data
        assert "day_cap" in data

    def test_ver_config(self):
        result, _ = execute_tool("ver_config", "{}")
        data = json.loads(result)
        assert data["day_capacity_min"] == 1020

    def test_explicar_logica(self):
        result, _ = execute_tool("explicar_logica", json.dumps({"conceito": "jit"}))
        data = json.loads(result)
        assert "explicacao" in data
        assert "JIT" in data["explicacao"]

    def test_explicar_logica_unknown(self):
        result, _ = execute_tool("explicar_logica", json.dumps({"conceito": "xpto"}))
        data = json.loads(result)
        assert "error" in data

    def test_explicar_decisao_with_audit(self):
        result, _ = execute_tool("explicar_decisao", json.dumps({"sku": "SKU1"}))
        data = json.loads(result)
        assert "schedule_id" in data
        assert state.schedule_id  # should have been set by _setup_state


# ─── TestActionExecutors ──────────────────────────────────────────────────

class TestActionExecutors:
    def setup_method(self):
        _setup_state()

    def test_recalcular_plano(self):
        result, _ = execute_tool("recalcular_plano", "{}")
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "score" in data
        assert "score_anterior" in data

    def test_check_ctp(self):
        result, _ = execute_tool("check_ctp", json.dumps({
            "sku": "SKU1", "quantidade": 100, "dia_deadline": 5,
        }))
        data = json.loads(result)
        assert "feasible" in data
        assert "sku" in data

    def test_alterar_config(self):
        result, _ = execute_tool("alterar_config", json.dumps({
            "chave": "oee_default", "valor": 0.75,
        }))
        data = json.loads(result)
        assert data["status"] == "ok"
        assert state.config.oee_default == 0.75

    def test_alterar_config_invalid_key(self):
        result, _ = execute_tool("alterar_config", json.dumps({
            "chave": "nope", "valor": 1,
        }))
        data = json.loads(result)
        assert "error" in data

    def test_rules(self):
        result, _ = execute_tool("adicionar_regra", json.dumps({
            "descricao": "Priorizar FAURECIA", "tipo": "prioridade",
        }))
        data = json.loads(result)
        rule_id = data["regra_id"]
        assert rule_id
        assert len(state.rules) == 1

        result, _ = execute_tool("remover_regra", json.dumps({"regra_id": rule_id}))
        data = json.loads(result)
        assert data["status"] == "ok"
        assert len(state.rules) == 0


# ─── TestMasterExecutors ─────────────────────────────────────────────────

class TestMasterExecutors:
    def setup_method(self):
        _setup_state()
        # Patch save_config to avoid overwriting real factory.yaml
        self._patcher = patch("backend.copilot.executors_master.save_config")
        self._mock_save = self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def test_editar_ferramenta_sync_sH(self):
        """CRITICAL: editar_ferramenta must sync op.sH in EngineData."""
        old_sH = state.engine_data.ops[0].sH
        assert old_sH == 0.5

        result, _ = execute_tool("editar_ferramenta", json.dumps({
            "id": "T1", "setup_hours": 1.5,
        }))
        data = json.loads(result)
        assert data["status"] == "ok"

        # Verify EngineData sync
        for op in state.engine_data.ops:
            if op.t == "T1":
                assert op.sH == 1.5, f"Sync failed: op.sH = {op.sH}"

    def test_editar_ferramenta_sync_alt(self):
        """editar_ferramenta must sync op.alt in EngineData."""
        result, _ = execute_tool("editar_ferramenta", json.dumps({
            "id": "T1", "alt": "M2",
        }))
        data = json.loads(result)
        assert data["status"] == "ok"

        for op in state.engine_data.ops:
            if op.t == "T1":
                assert op.alt == "M2"

    def test_editar_ferramenta_nonexistent(self):
        result, _ = execute_tool("editar_ferramenta", json.dumps({"id": "NOPE"}))
        data = json.loads(result)
        assert "error" in data

    def test_adicionar_feriado_sync(self):
        """adicionar_feriado must sync EngineData.holidays."""
        date = "2026-03-07"  # workday index 2
        assert date in state.engine_data.workdays

        result, _ = execute_tool("adicionar_feriado", json.dumps({"data": date}))
        data = json.loads(result)
        assert data["status"] == "ok"

        idx = state.engine_data.workdays.index(date)
        assert idx in state.engine_data.holidays

    def test_remover_feriado(self):
        # First add
        execute_tool("adicionar_feriado", json.dumps({"data": "2026-03-07"}))
        assert "2026-03-07" in state.config.holidays

        result, _ = execute_tool("remover_feriado", json.dumps({"data": "2026-03-07"}))
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "2026-03-07" not in state.config.holidays

    def test_adicionar_maquina(self):
        result, _ = execute_tool("adicionar_maquina", json.dumps({
            "id": "M3", "grupo": "Medias",
        }))
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "M3" in state.config.machines
        assert any(m.id == "M3" for m in state.engine_data.machines)

    def test_editar_turno_sync_capacity(self):
        """editar_turno must sync EngineData machine capacities."""
        old_cap = state.config.day_capacity_min
        assert old_cap == 1020

        # Extend shift A to 16:00 (480 → 540 min, total = 540 + 510 = 1050)
        result, _ = execute_tool("editar_turno", json.dumps({
            "turno_id": "A", "fim": "16:00",
        }))
        data = json.loads(result)
        assert data["status"] == "ok"

        new_cap = state.config.day_capacity_min
        assert new_cap != old_cap

        # Check all machines synced
        for m in state.engine_data.machines:
            assert m.day_capacity == new_cap

    def test_snapshot_revert_restores_config_and_schedule_exactly(self):
        state.save_current(kind="config")
        old_cap = state.config.day_capacity_min
        old_segments = [
            (s.lot_id, s.day_idx, s.start_min, s.end_min)
            for s in state.segments
        ]

        state.config.shifts[0].end_min += 30
        state.segments[0].start_min += 15
        state.active_mutations = [{"type": "machine_down", "params": {"machine_id": "M1"}}]

        kind = state.restore_saved()

        assert kind == "config"
        assert state.config.day_capacity_min == old_cap
        assert [
            (s.lot_id, s.day_idx, s.start_min, s.end_min)
            for s in state.segments
        ] == old_segments
        assert state.active_mutations == []


# ─── TestVizExecutors ─────────────────────────────────────────────────────

class TestVizExecutors:
    def setup_method(self):
        _setup_state()

    def test_visualizar_stock(self):
        result, is_widget = execute_tool("visualizar_stock", json.dumps({"sku": "SKU1"}))
        data = json.loads(result)
        assert is_widget
        assert data["viz_type"] == "line_chart"
        assert len(data["data"]["series"]) == 3

    def test_visualizar_stock_not_found(self):
        result, is_widget = execute_tool("visualizar_stock", json.dumps({"sku": "NOPE"}))
        data = json.loads(result)
        assert "error" in data

    def test_visualizar_carga_temporal(self):
        result, is_widget = execute_tool("visualizar_carga_temporal", "{}")
        data = json.loads(result)
        assert is_widget
        assert data["viz_type"] == "bar_chart"

    def test_visualizar_gantt(self):
        result, is_widget = execute_tool("visualizar_gantt", json.dumps({"dia_fim": 5}))
        data = json.loads(result)
        assert is_widget
        assert data["viz_type"] == "timeline"
        assert "events" in data["data"]

    def test_visualizar_encomendas(self):
        result, is_widget = execute_tool("visualizar_encomendas", "{}")
        data = json.loads(result)
        assert is_widget
        assert data["viz_type"] == "table"

    def test_visualizar_expedicao(self):
        result, is_widget = execute_tool("visualizar_expedicao", "{}")
        data = json.loads(result)
        assert is_widget
        assert data["viz_type"] == "table"

    def test_visualizar_risco_heatmap(self):
        result, is_widget = execute_tool("visualizar_risco_heatmap", "{}")
        data = json.loads(result)
        assert is_widget
        assert data["viz_type"] == "heatmap"


# ─── TestEngine ───────────────────────────────────────────────────────────

class TestEngine:
    def test_unknown_tool(self):
        result, is_widget = execute_tool("tool_inexistente", "{}")
        data = json.loads(result)
        assert "error" in data
        assert not is_widget

    def test_widget_flag(self):
        for name in WIDGET_TOOLS:
            assert name in EXECUTORS
            assert name.startswith("visualizar_")

    def test_invalid_json_args(self):
        _setup_state()
        result, _ = execute_tool("ver_score", "not json {{{")
        data = json.loads(result)
        assert "error" in data


# ─── TestState ────────────────────────────────────────────────────────────

class TestState:
    def test_update_schedule_saves_audit(self):
        engine = _engine()
        config = FactoryConfig()
        result = schedule_all(engine, audit=True, config=config)

        s = CopilotState()
        s.engine_data = engine
        s.config = config
        s.update_schedule(result)

        assert s.schedule_id
        assert s.audit_store is not None

    def test_rules_persistence(self):
        s = CopilotState()
        rule_id = s.add_rule({"descricao": "Test rule", "tipo": "restricao"})
        assert len(s.rules) == 1

        s2 = CopilotState()
        s2._load_rules()
        assert len(s2.rules) == 1
        assert s2.rules[0]["id"] == rule_id

        # Cleanup
        s.remove_rule(rule_id)


# ─── TestProviderFactory ─────────────────────────────────────────────────

class TestProviderFactory:
    def test_default_openai(self):
        from backend.copilot.llm_provider import OpenAIProvider, get_provider

        os.environ.pop("PP1_LLM_BACKEND", None)
        # get_provider() will try to import openai — skip if not installed
        try:
            provider = get_provider()
            assert isinstance(provider, OpenAIProvider)
        except ImportError:
            pytest.skip("openai not installed")

    def test_ollama_backend(self):
        from backend.copilot.llm_provider import OllamaProvider, get_provider

        os.environ["PP1_LLM_BACKEND"] = "ollama"
        try:
            provider = get_provider()
            assert isinstance(provider, OllamaProvider)
        except ImportError:
            pytest.skip("httpx not installed")
        finally:
            os.environ.pop("PP1_LLM_BACKEND", None)


# ─── TestPrompts ──────────────────────────────────────────────────────────

class TestPrompts:
    def test_build_system_prompt(self):
        from backend.copilot.prompts import build_system_prompt

        _setup_state()
        prompt = build_system_prompt(state)
        assert "Incompol" in prompt
        assert "OTD" in prompt

    def test_build_system_prompt_no_data(self):
        from backend.copilot.prompts import build_system_prompt

        s = CopilotState()
        prompt = build_system_prompt(s)
        assert "SEM DADOS" in prompt
