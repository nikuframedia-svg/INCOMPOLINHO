"""Copilot engine — tool execution dispatcher."""

from __future__ import annotations

import json
import logging

from .tool_executors import (
    _exec_adicionar_regra,
    _exec_agrupar_material,
    _exec_alterar_definicao,
    _exec_check_ctp,
    _exec_explicar_decisao,
    _exec_explicar_decisao_id,
    _exec_explicar_logica,
    _exec_explicar_referencia,
    _exec_mover_referencia,
    _exec_recalcular_plano,
    _exec_remover_regra,
    _exec_schedule_whatif,
    _exec_simulate_overtime,
    _exec_sugerir_melhorias,
    _exec_ver_alertas,
    _exec_ver_carga_maquinas,
    _exec_ver_decisoes,
    _exec_ver_producao_hoje,
    _exec_ver_robustez,
)
from .tool_helpers import _dumps

logger = logging.getLogger(__name__)


# ─── Tool Dispatcher ──────────────────────────────────────────────────────────


EXECUTORS = {
    "adicionar_regra": _exec_adicionar_regra,
    "remover_regra": _exec_remover_regra,
    "alterar_definicao": _exec_alterar_definicao,
    "explicar_referencia": _exec_explicar_referencia,
    "ver_alertas": _exec_ver_alertas,
    "ver_carga_maquinas": _exec_ver_carga_maquinas,
    "agrupar_material": _exec_agrupar_material,
    "mover_referencia": _exec_mover_referencia,
    "recalcular_plano": _exec_recalcular_plano,
    "sugerir_melhorias": _exec_sugerir_melhorias,
    "explicar_decisao": _exec_explicar_decisao,
    "explicar_logica": _exec_explicar_logica,
    "ver_decisoes": _exec_ver_decisoes,
    "ver_producao_hoje": _exec_ver_producao_hoje,
    "ver_robustez": _exec_ver_robustez,
    "check_ctp": _exec_check_ctp,
    "schedule_whatif": _exec_schedule_whatif,
    "simulate_overtime": _exec_simulate_overtime,
    "explicar_decisao_id": _exec_explicar_decisao_id,
}


def execute_tool(name: str, arguments: str) -> str:
    """Execute a copilot tool by name. Returns JSON string."""
    executor = EXECUTORS.get(name)
    if executor is None:
        return _dumps({"error": f"Tool '{name}' não existe."})
    try:
        args = json.loads(arguments) if arguments else {}
        return executor(args)
    except Exception as e:
        logger.exception("Tool execution error: %s", name)
        return _dumps({"error": str(e)})
