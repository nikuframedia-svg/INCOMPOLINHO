"""Tool execution engine — Spec 10.

Routes tool calls to the correct executor. Returns (json_result, is_widget).
"""

from __future__ import annotations

import json
import logging

from backend.copilot.executors_action import (
    exec_adicionar_regra,
    exec_alterar_config,
    exec_check_ctp,
    exec_monte_carlo,
    exec_mover_referencia,
    exec_recalcular_plano,
    exec_remover_regra,
    exec_simular_avaria,
    exec_simular_cenario,
    exec_simular_overtime,
)
from backend.copilot.executors_master import (
    exec_adicionar_feriado,
    exec_adicionar_ferramenta,
    exec_adicionar_maquina,
    exec_adicionar_turno,
    exec_adicionar_twin,
    exec_editar_ferramenta,
    exec_editar_maquina,
    exec_editar_turno,
    exec_remover_feriado,
    exec_remover_twin,
)
from backend.copilot.executors_query import (
    exec_e_se,
    exec_explicar_decisao,
    exec_explicar_logica,
    exec_explicar_referencia,
    exec_ver_alertas,
    exec_ver_carga_maquinas,
    exec_ver_config,
    exec_ver_encomendas,
    exec_ver_historico,
    exec_ver_producao_dia,
    exec_ver_score,
    exec_ver_stress,
)
from backend.copilot.executors_viz import (
    exec_visualizar_atrasos,
    exec_visualizar_carga_temporal,
    exec_visualizar_cobertura,
    exec_visualizar_comparacao,
    exec_visualizar_encomendas,
    exec_visualizar_expedicao,
    exec_visualizar_gantt,
    exec_visualizar_learning,
    exec_visualizar_propostas,
    exec_visualizar_risco_heatmap,
    exec_visualizar_stock,
    exec_visualizar_workforce,
)

logger = logging.getLogger(__name__)

# All 40 executors
EXECUTORS: dict[str, callable] = {
    # Query (10)
    "ver_producao_dia": exec_ver_producao_dia,
    "ver_carga_maquinas": exec_ver_carga_maquinas,
    "ver_alertas": exec_ver_alertas,
    "ver_score": exec_ver_score,
    "ver_config": exec_ver_config,
    "explicar_referencia": exec_explicar_referencia,
    "explicar_decisao": exec_explicar_decisao,
    "explicar_logica": exec_explicar_logica,
    "ver_encomendas": exec_ver_encomendas,
    "ver_historico": exec_ver_historico,
    "ver_stress": exec_ver_stress,
    "e_se": exec_e_se,
    # Action (10)
    "recalcular_plano": exec_recalcular_plano,
    "mover_referencia": exec_mover_referencia,
    "adicionar_regra": exec_adicionar_regra,
    "remover_regra": exec_remover_regra,
    "alterar_config": exec_alterar_config,
    "simular_cenario": exec_simular_cenario,
    "simular_overtime": exec_simular_overtime,
    "check_ctp": exec_check_ctp,
    "simular_avaria": exec_simular_avaria,
    "monte_carlo": exec_monte_carlo,
    # Master Data (10)
    "adicionar_maquina": exec_adicionar_maquina,
    "editar_maquina": exec_editar_maquina,
    "adicionar_ferramenta": exec_adicionar_ferramenta,
    "editar_ferramenta": exec_editar_ferramenta,
    "adicionar_twin": exec_adicionar_twin,
    "remover_twin": exec_remover_twin,
    "adicionar_feriado": exec_adicionar_feriado,
    "remover_feriado": exec_remover_feriado,
    "editar_turno": exec_editar_turno,
    "adicionar_turno": exec_adicionar_turno,
    # Viz (8)
    "visualizar_stock": exec_visualizar_stock,
    "visualizar_carga_temporal": exec_visualizar_carga_temporal,
    "visualizar_risco_heatmap": exec_visualizar_risco_heatmap,
    "visualizar_encomendas": exec_visualizar_encomendas,
    "visualizar_expedicao": exec_visualizar_expedicao,
    "visualizar_gantt": exec_visualizar_gantt,
    "visualizar_comparacao": exec_visualizar_comparacao,
    "visualizar_learning": exec_visualizar_learning,
    "visualizar_atrasos": exec_visualizar_atrasos,
    "visualizar_workforce": exec_visualizar_workforce,
    "visualizar_cobertura": exec_visualizar_cobertura,
    "visualizar_propostas": exec_visualizar_propostas,
}

WIDGET_TOOLS = {
    "visualizar_stock",
    "visualizar_carga_temporal",
    "visualizar_risco_heatmap",
    "visualizar_encomendas",
    "visualizar_expedicao",
    "visualizar_gantt",
    "visualizar_comparacao",
    "visualizar_learning",
    "visualizar_atrasos",
    "visualizar_workforce",
    "visualizar_cobertura",
    "visualizar_propostas",
}


def execute_tool(name: str, arguments: str) -> tuple[str, bool]:
    """Execute a tool by name. Returns (json_result, is_widget)."""
    executor = EXECUTORS.get(name)
    if executor is None:
        result = json.dumps({"error": f"Tool '{name}' desconhecida."}, ensure_ascii=False)
        return result, False

    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        result = json.dumps({"error": f"Argumentos inválidos: {arguments}"}, ensure_ascii=False)
        return result, False

    try:
        from backend.copilot.state import state
        from backend.plans.transactions import run_sync_mutation

        if executor.__module__ in {
            "backend.copilot.executors_master", "backend.copilot.executors_action"
        } and name not in {"check_ctp", "monte_carlo"}:
            mode = args.get("modo", "quick") if name == "recalcular_plano" else "normal"
            result = run_sync_mutation(state, lambda: executor(args), planning_mode=mode)
        else:
            result = executor(args)
    except Exception as e:
        logger.exception("Error executing tool %s", name)
        result = json.dumps({"error": f"Erro ao executar {name}: {e}"}, ensure_ascii=False)

    is_widget = name in WIDGET_TOOLS
    return result, is_widget
