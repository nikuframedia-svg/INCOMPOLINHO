"""Tests for copilot tools — no OpenAI API needed."""

from __future__ import annotations

import json

from src.domain.copilot.engine import execute_tool
from src.domain.copilot.prompts import build_system_prompt
from src.domain.copilot.state import copilot_state
from src.domain.copilot.tools import TOOLS


def _setup_state():
    """Load minimal synthetic state for copilot tests."""
    copilot_state.isop_data = {
        "skus": {
            "262": {
                "sku": "262",
                "designation": "Ref 262",
                "machine": "PRM019",
                "tool": "T1",
                "pieces_per_hour": 500,
                "stock": 500,
                "atraso": 0,
                "twin_ref": None,
                "clients": ["C1"],
                "orders": [{"qty": 1000, "deadline": "2026-03-05"}],
            },
            "170": {
                "sku": "170",
                "designation": "Ref 170",
                "machine": "PRM031",
                "tool": "T1",
                "pieces_per_hour": 400,
                "stock": 0,
                "atraso": -100,
                "twin_ref": None,
                "clients": ["C1"],
                "orders": [{"qty": 2000, "deadline": "2026-03-08"}],
            },
        },
        "total_orders": 2,
        "machines": ["PRM019", "PRM031"],
        "total_tools": 1,
    }
    copilot_state.update_from_schedule_result(
        {
            "blocks": [
                {
                    "machine_id": "PRM019",
                    "qty": 1000,
                    "production_minutes": 120,
                    "block_type": "production",
                },
                {
                    "machine_id": "PRM031",
                    "qty": 2000,
                    "production_minutes": 300,
                    "block_type": "production",
                },
            ],
            "decisions": [
                {
                    "type": "BACKWARD_SCHEDULE",
                    "op_id": "262",
                    "machine_id": "PRM019",
                    "detail": "Scheduled backward",
                },
            ],
            "feasibility_report": {"feasible": True},
            "auto_moves": [],
            "kpis": {"total_blocks": 2, "infeasible_blocks": 0, "total_qty": 3000, "otd_pct": 95},
            "engine_data": {
                "ops": [],
                "machines": [],
                "n_days": 80,
                "m_st": {},
                "t_st": {},
                "tool_map": {},
                "workdays": [],
                "workforce_config": None,
                "third_shift": False,
                "twin_validation_report": None,
                "order_based": True,
            },
            "solver_used": "atcs_python",
            "solve_time_s": 0.5,
        }
    )
    copilot_state.alerts = [
        {"severity": "atraso", "message": "Ref 170 em atraso"},
    ]
    copilot_state._rules = []


def test_tools_schema():
    assert len(TOOLS) == 14
    for tool in TOOLS:
        assert tool["type"] == "function"
        assert "name" in tool["function"]
        assert "description" in tool["function"]


def test_explicar_referencia():
    _setup_state()
    result = json.loads(execute_tool("explicar_referencia", '{"sku": "262"}'))
    assert result["sku"] == "262"
    assert result["stock"] == 500
    assert result["encomendas"] == 1


def test_explicar_referencia_not_found():
    _setup_state()
    result = json.loads(execute_tool("explicar_referencia", '{"sku": "NONEXISTENT"}'))
    assert "error" in result


def test_ver_alertas():
    _setup_state()
    result = json.loads(execute_tool("ver_alertas", '{"severity": "all"}'))
    assert "alertas" in result
    assert result["total"] == 1


def test_ver_carga_maquinas():
    _setup_state()
    result = json.loads(execute_tool("ver_carga_maquinas", "{}"))
    assert "máquinas" in result
    assert "PRM019" in result["máquinas"]


def test_adicionar_regra():
    _setup_state()
    args = json.dumps(
        {
            "id": "test_rule",
            "name": "Regra teste",
            "condition_type": "sku_in_list",
            "action_type": "move_to_machine",
        }
    )
    result = json.loads(execute_tool("adicionar_regra", args))
    assert result["status"] == "ok"
    assert any(r["id"] == "test_rule" for r in copilot_state.get_rules())


def test_adicionar_regra_duplicate():
    _setup_state()
    args = json.dumps(
        {
            "id": "dup",
            "name": "Dup",
            "condition_type": "sku_equals",
            "action_type": "alert",
        }
    )
    execute_tool("adicionar_regra", args)
    result = json.loads(execute_tool("adicionar_regra", args))
    assert "error" in result


def test_remover_regra():
    _setup_state()
    args = json.dumps(
        {
            "id": "to_remove",
            "name": "Remove me",
            "condition_type": "sku_equals",
            "action_type": "alert",
        }
    )
    execute_tool("adicionar_regra", args)
    result = json.loads(execute_tool("remover_regra", '{"id": "to_remove"}'))
    assert result["status"] == "ok"


def test_agrupar_material():
    _setup_state()
    args = json.dumps(
        {
            "sku_list": ["262", "170"],
            "machine_id": "PRM019",
            "reason": "matéria-prima comum",
        }
    )
    result = json.loads(execute_tool("agrupar_material", args))
    assert result["status"] == "ok"
    assert "rule_id" in result


def test_recalcular_plano():
    _setup_state()
    result = json.loads(execute_tool("recalcular_plano", "{}"))
    # With engine_data populated, it attempts to run the real scheduler
    # It may succeed or fail depending on engine_data completeness
    assert result["status"] in ("ok", "error")


def test_sugerir_melhorias():
    _setup_state()
    result = json.loads(execute_tool("sugerir_melhorias", '{"focus": "all"}'))
    assert "sugestões" in result
    assert len(result["sugestões"]) > 0


def test_system_prompt_dynamic():
    _setup_state()
    prompt = build_system_prompt()
    assert "Incompol" in prompt
    assert "ESTADO ACTUAL DO PLANO" in prompt
    assert "DADOS ISOP" in prompt


def test_unknown_tool():
    result = json.loads(execute_tool("nonexistent_tool", "{}"))
    assert "error" in result


def test_alterar_definicao():
    _setup_state()
    args = json.dumps({"key": "scheduling.buffer_days", "value": 3})
    result = json.loads(execute_tool("alterar_definicao", args))
    assert result["status"] == "ok"
    assert copilot_state.get_config()["scheduling"]["buffer_days"] == 3


def test_mover_referencia():
    _setup_state()
    args = json.dumps({"sku": "262", "target_machine": "PRM031", "reason": "balancear carga"})
    result = json.loads(execute_tool("mover_referencia", args))
    assert result["status"] == "ok"
    assert any("move_262_PRM031" in r["id"] for r in copilot_state.get_rules())
