"""Tests for CLOSE-01 — copilot state wiring after scheduling + ISOP load."""

from __future__ import annotations

import json

from src.domain.copilot.engine import execute_tool
from src.domain.copilot.state import CopilotState, copilot_state
from src.domain.copilot.tools import TOOLS


def _reset_state():
    """Reset copilot state to blank."""
    copilot_state.__init__()


def _setup_with_schedule():
    """Simulate copilot_state after a scheduling run."""
    _reset_state()
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
        },
        "total_orders": 1,
        "machines": ["PRM019"],
        "total_tools": 1,
    }
    copilot_state.isop_date = "2026-03-01"
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
                    "detail": "Scheduled backward from deadline",
                    "day_idx": 3,
                    "shift": "A",
                },
                {
                    "type": "OVERFLOW_ROUTE",
                    "op_id": "170",
                    "machine_id": "PRM031",
                    "detail": "Moved to alt machine",
                    "day_idx": 5,
                    "shift": "B",
                },
            ],
            "feasibility_report": {"feasible": True, "infeasible_ops": []},
            "auto_moves": [],
            "kpis": {
                "total_blocks": 2,
                "infeasible_blocks": 0,
                "total_qty": 3000,
                "otd_pct": 100.0,
            },
            "engine_data": {"ops": [], "machines": [], "n_days": 80},
            "solver_used": "atcs_python",
            "solve_time_s": 0.42,
        }
    )
    copilot_state.alerts = [{"severity": "atraso", "message": "Ref 170 em atraso"}]


# ── Tests ──


def test_state_has_all_fields():
    """CopilotState has all required decision intelligence fields."""
    state = CopilotState()
    assert state.engine_data is None
    assert state.decisions == []
    assert state.kpis is None
    assert state.blocks == []
    assert state.feasibility_report is None
    assert state.last_schedule_at is None
    assert state.solver_used == ""
    assert state.solve_time_s == 0.0


def test_update_from_schedule_result():
    """update_from_schedule_result hydrates all fields."""
    _setup_with_schedule()

    assert copilot_state.kpis is not None
    assert copilot_state.kpis["total_blocks"] == 2
    assert copilot_state.kpis["otd_pct"] == 100.0
    assert len(copilot_state.blocks) == 2
    assert len(copilot_state.decisions) == 2
    assert copilot_state.solver_used == "atcs_python"
    assert copilot_state.solve_time_s == 0.42
    assert copilot_state.last_schedule_at is not None
    assert copilot_state.engine_data is not None
    assert copilot_state.schedule is not None  # backward compat


def test_schedule_populates_kpis():
    """KPIs computed correctly from blocks."""
    _setup_with_schedule()
    kpis = copilot_state.kpis
    assert kpis["total_blocks"] == 2
    assert kpis["infeasible_blocks"] == 0
    assert kpis["total_qty"] == 3000
    assert kpis["otd_pct"] == 100.0


def test_isop_populates_state():
    """After ISOP data set, copilot_state.isop_data is available."""
    _setup_with_schedule()
    assert copilot_state.isop_data is not None
    assert "skus" in copilot_state.isop_data
    assert copilot_state.isop_date == "2026-03-01"


def test_alerts_available():
    """Alerts are populated after scheduling."""
    _setup_with_schedule()
    assert copilot_state.alerts is not None
    assert len(copilot_state.alerts) == 1
    assert copilot_state.alerts[0]["severity"] == "atraso"


def test_decisions_available():
    """Decisions are populated after scheduling."""
    _setup_with_schedule()
    assert len(copilot_state.decisions) == 2
    assert copilot_state.decisions[0]["type"] == "BACKWARD_SCHEDULE"
    assert copilot_state.decisions[1]["type"] == "OVERFLOW_ROUTE"


def test_get_decisions_for_sku():
    """get_decisions_for_sku filters correctly."""
    _setup_with_schedule()
    d262 = copilot_state.get_decisions_for_sku("262")
    assert len(d262) == 1
    assert d262[0]["op_id"] == "262"

    d170 = copilot_state.get_decisions_for_sku("170")
    assert len(d170) == 1
    assert d170[0]["type"] == "OVERFLOW_ROUTE"


def test_get_context_summary():
    """get_context_summary returns expected structure."""
    _setup_with_schedule()
    summary = copilot_state.get_context_summary()
    assert summary["has_isop"] is True
    assert summary["has_schedule"] is True
    assert summary["n_blocks"] == 2
    assert summary["n_decisions"] == 2
    assert summary["n_alerts"] == 1
    assert summary["solver_used"] == "atcs_python"


def test_tools_count():
    """Tools list has 13 entries (10 original + 3 new)."""
    assert len(TOOLS) == 14


def test_explicar_decisao_tool():
    """explicar_decisao returns decision chain for SKU."""
    _setup_with_schedule()
    result = json.loads(execute_tool("explicar_decisao", json.dumps({"sku": "262"})))
    assert "decisões" in result
    assert result["total"] == 1
    assert result["decisões"][0]["tipo"] == "BACKWARD_SCHEDULE"


def test_explicar_decisao_not_found():
    """explicar_decisao returns info when SKU has no decisions."""
    _setup_with_schedule()
    result = json.loads(execute_tool("explicar_decisao", json.dumps({"sku": "NONEXISTENT"})))
    assert "info" in result


def test_explicar_logica_all_aspects():
    """explicar_logica covers all 7 aspects."""
    aspects = ["geral", "dispatch", "constraints", "overflow", "twins", "alertas", "replan"]
    for aspect in aspects:
        result = json.loads(execute_tool("explicar_logica", json.dumps({"aspecto": aspect})))
        assert "lógica" in result
        assert len(result["lógica"]) > 50


def test_ver_decisoes_all():
    """ver_decisoes returns all decisions."""
    _setup_with_schedule()
    result = json.loads(execute_tool("ver_decisoes", "{}"))
    assert result["total"] == 2
    assert len(result["decisões"]) == 2


def test_ver_decisoes_filter_type():
    """ver_decisoes filters by type."""
    _setup_with_schedule()
    result = json.loads(execute_tool("ver_decisoes", json.dumps({"tipo": "OVERFLOW_ROUTE"})))
    assert result["total"] == 1
    assert result["decisões"][0]["type"] == "OVERFLOW_ROUTE"


def test_ver_decisoes_filter_machine():
    """ver_decisoes filters by machine."""
    _setup_with_schedule()
    result = json.loads(execute_tool("ver_decisoes", json.dumps({"machine_id": "PRM019"})))
    assert result["total"] == 1


def test_ver_carga_maquinas_uses_blocks():
    """ver_carga_maquinas works with new blocks-based state."""
    _setup_with_schedule()
    result = json.loads(execute_tool("ver_carga_maquinas", "{}"))
    assert "máquinas" in result
    assert "PRM019" in result["máquinas"]
    assert result["máquinas"]["PRM019"]["jobs"] == 1
    assert result["máquinas"]["PRM019"]["pecas_total"] == 1000
