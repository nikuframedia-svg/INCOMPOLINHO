"""Copilot engine — tool execution dispatcher."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

from .state import copilot_state

logger = logging.getLogger(__name__)


class _DateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return super().default(o)


def _dumps(obj) -> str:
    return json.dumps(obj, cls=_DateEncoder, ensure_ascii=False)


# ─── Tool Executors ───────────────────────────────────────────────────────────


def _exec_adicionar_regra(args: dict) -> str:
    rule = {
        "id": args["id"],
        "name": args["name"],
        "condition": {
            "type": args["condition_type"],
            "params": args.get("condition_params", {}),
        },
        "action": {
            "type": args["action_type"],
            "params": args.get("action_params", {}),
        },
        "enabled": True,
    }
    existing = copilot_state.get_rules()
    if any(r.get("id") == rule["id"] for r in existing):
        return _dumps({"error": f"Regra {rule['id']} já existe."})
    copilot_state.add_rule(rule)
    return _dumps({"status": "ok", "message": f"Regra '{args['name']}' criada."})


def _exec_remover_regra(args: dict) -> str:
    removed = copilot_state.remove_rule(args["id"])
    if not removed:
        return _dumps({"error": f"Regra {args['id']} não encontrada."})
    return _dumps({"status": "ok", "message": f"Regra {args['id']} removida."})


def _exec_alterar_definicao(args: dict) -> str:
    config = copilot_state.get_config()
    keys = args["key"].split(".")
    target = config
    for k in keys[:-1]:
        if k not in target or not isinstance(target[k], dict):
            target[k] = {}
        target = target[k]
    target[keys[-1]] = args["value"]
    copilot_state.set_config(config)
    return _dumps({"status": "ok", "message": f"Definição {args['key']} alterada."})


def _exec_explicar_referencia(args: dict) -> str:
    if copilot_state.isop_data is None:
        return _dumps({"error": "ISOP não carregado."})
    sku_code = args["sku"]
    isop = copilot_state.isop_data
    if not isinstance(isop, dict) or sku_code not in isop.get("skus", {}):
        return _dumps({"error": f"Referência {sku_code} não encontrada."})
    s = isop["skus"][sku_code]
    return _dumps(
        {
            "sku": s.get("sku", sku_code),
            "designação": s.get("designation", "?"),
            "máquina": s.get("machine", "?"),
            "ferramenta": s.get("tool", "?"),
            "peças/hora": s.get("pieces_per_hour", "?"),
            "stock": s.get("stock", 0),
            "atraso": s.get("atraso", 0),
            "gémea": s.get("twin_ref"),
            "encomendas": len(s.get("orders", [])),
            "procura_total": sum(o.get("qty", 0) for o in s.get("orders", [])),
            "clientes": s.get("clients", []),
        }
    )


def _exec_ver_alertas(args: dict) -> str:
    alerts = copilot_state.alerts or []
    severity = args.get("severity", "all")
    limit = args.get("limit", 10)
    if severity != "all":
        alerts = [a for a in alerts if a.get("severity") == severity]
    return _dumps({"alertas": alerts[:limit], "total": len(alerts)})


def _exec_ver_carga_maquinas(args: dict) -> str:
    if copilot_state.schedule is None:
        return _dumps({"error": "Plano não carregado."})
    gantt = copilot_state.schedule
    machine_id = args.get("machine_id")
    machines = {}
    for m_id in gantt.get("machines", []):
        if machine_id and m_id != machine_id:
            continue
        m_jobs = [j for j in gantt.get("jobs", []) if j.get("machine") == m_id]
        machines[m_id] = {
            "jobs": len(m_jobs),
            "minutos_producao": sum(j.get("production_minutes", 0) for j in m_jobs),
            "pecas_total": sum(j.get("qty", 0) for j in m_jobs),
        }
    return _dumps({"máquinas": machines})


def _exec_agrupar_material(args: dict) -> str:
    sku_list = args["sku_list"]
    machine_id = args["machine_id"]
    reason = args.get("reason", "agrupamento de matéria-prima")
    rule_id = f"mp_{'_'.join(sku_list[:3])}"
    rule = {
        "id": rule_id,
        "name": f"Agrupar {', '.join(sku_list)} em {machine_id}",
        "condition": {"type": "sku_in_list", "params": {"skus": sku_list}},
        "action": {"type": "move_to_machine", "params": {"machine": machine_id}},
        "enabled": True,
        "reason": reason,
    }
    copilot_state.add_rule(rule)
    return _dumps(
        {"status": "ok", "message": f"Regra de agrupamento criada: {rule_id}", "rule_id": rule_id}
    )


def _exec_mover_referencia(args: dict) -> str:
    sku = args["sku"]
    target = args["target_machine"]
    reason = args.get("reason", "movido pelo copilot")
    rule_id = f"move_{sku}_{target}"
    rule = {
        "id": rule_id,
        "name": f"Mover {sku} → {target}",
        "condition": {"type": "sku_equals", "params": {"sku": sku}},
        "action": {"type": "move_to_machine", "params": {"machine": target}},
        "enabled": True,
        "reason": reason,
    }
    copilot_state.add_rule(rule)
    return _dumps({"status": "ok", "message": f"Referência {sku} movida para {target}."})


def _exec_recalcular_plano(_args: dict) -> str:
    return _dumps(
        {
            "status": "info",
            "message": "Recálculo de plano disponível via frontend (scheduling é client-side).",
        }
    )


def _exec_sugerir_melhorias(args: dict) -> str:
    if copilot_state.schedule is None:
        return _dumps({"error": "Plano não carregado."})
    gantt = copilot_state.schedule
    kpis = gantt.get("kpis", {})
    suggestions = []

    otd = kpis.get("otd_pct", 100)
    if otd < 100:
        suggestions.append(
            f"OTD está a {otd}%. Considerar antecipar produção ou adicionar turno extra."
        )

    alerts = copilot_state.alerts or []
    atraso_count = sum(1 for a in alerts if a.get("severity") == "atraso")
    if atraso_count > 0:
        suggestions.append(
            f"Existem {atraso_count} referências em ATRASO. Priorizar estas na próxima iteração."
        )

    jobs = gantt.get("jobs", [])
    machine_loads: dict[str, int] = {}
    for j in jobs:
        m = j.get("machine", "?")
        machine_loads[m] = machine_loads.get(m, 0) + j.get("production_minutes", 0)
    if machine_loads:
        max_m = max(machine_loads, key=lambda k: machine_loads[k])
        min_m = min(machine_loads, key=lambda k: machine_loads[k])
        if machine_loads[max_m] > machine_loads[min_m] * 1.5:
            suggestions.append(
                f"Desequilíbrio de carga: {max_m} ({machine_loads[max_m]}min) vs {min_m} ({machine_loads[min_m]}min). "
                "Considerar mover referências."
            )

    if not suggestions:
        suggestions.append("Plano parece equilibrado. Sem sugestões imediatas.")

    return _dumps({"sugestões": suggestions})


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
