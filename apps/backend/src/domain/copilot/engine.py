"""Copilot engine — tool execution dispatcher."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from .state import copilot_state

logger = logging.getLogger(__name__)


class _DateEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return super().default(o)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, cls=_DateEncoder, ensure_ascii=False)


# ─── Rule → Scheduler Bridge ────────────────────────────────────────────────


def _rules_to_user_moves(rules: list[dict]) -> list[dict]:
    """Translate copilot rules into user_moves for auto_route_overflow."""
    moves: list[dict] = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        action = rule.get("action", {})
        condition = rule.get("condition", {})
        if action.get("type") != "move_to_machine":
            continue
        target = action.get("params", {}).get("machine", "")
        if not target:
            continue

        if condition.get("type") == "sku_equals":
            sku = condition.get("params", {}).get("sku", "")
            if sku:
                moves.append({"op_id": sku, "target_machine": target})
        elif condition.get("type") == "sku_in_list":
            for sku in condition.get("params", {}).get("skus", []):
                moves.append({"op_id": sku, "target_machine": target})
    return moves


def _apply_rules_to_ops(ops: list[Any], rules: list[dict]) -> list[Any]:
    """Apply copilot rules that modify ops before scheduling."""
    skip_skus: set[str] = set()
    priority_boosts: dict[str, float] = {}

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        action = rule.get("action", {})
        condition = rule.get("condition", {})
        action_type = action.get("type", "")

        if action_type == "skip_scheduling":
            if condition.get("type") == "sku_equals":
                sku = condition.get("params", {}).get("sku", "")
                if sku:
                    skip_skus.add(sku)
        elif action_type == "set_priority":
            boost = action.get("params", {}).get("boost", 2.0)
            if condition.get("type") == "sku_equals":
                sku = condition.get("params", {}).get("sku", "")
                if sku:
                    priority_boosts[sku] = boost

    if skip_skus:
        ops = [op for op in ops if getattr(op, "sku", getattr(op, "id", "")) not in skip_skus]

    if priority_boosts:
        for op in ops:
            op_sku = getattr(op, "sku", getattr(op, "id", ""))
            if op_sku in priority_boosts and hasattr(op, "w"):
                op.w = getattr(op, "w", 1.0) * priority_boosts[op_sku]

    return ops


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

    # Auto-recalculate if engine_data available
    if copilot_state.engine_data is not None:
        recalc = _exec_recalcular_plano({})
        return _dumps(
            {
                "status": "ok",
                "message": f"Regra '{args['name']}' criada.",
                "recalculo": json.loads(recalc),
            }
        )
    return _dumps({"status": "ok", "message": f"Regra '{args['name']}' criada."})


def _exec_remover_regra(args: dict) -> str:
    removed = copilot_state.remove_rule(args["id"])
    if not removed:
        return _dumps({"error": f"Regra {args['id']} não encontrada."})

    if copilot_state.engine_data is not None:
        recalc = _exec_recalcular_plano({})
        return _dumps(
            {
                "status": "ok",
                "message": f"Regra {args['id']} removida.",
                "recalculo": json.loads(recalc),
            }
        )
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
    sku_code = args["sku"]

    # Try ISOP data first
    isop = copilot_state.isop_data
    if isinstance(isop, dict) and sku_code in isop.get("skus", {}):
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

    # Fallback: try EngineData ops
    ed = copilot_state.engine_data
    if isinstance(ed, dict) and ed.get("ops"):
        for op in ed["ops"]:
            op_id = op.get("id", "") if isinstance(op, dict) else getattr(op, "id", "")
            op_sku = op.get("sku", "") if isinstance(op, dict) else getattr(op, "sku", "")
            if op_id == sku_code or op_sku == sku_code:
                g = op.get if isinstance(op, dict) else lambda k, d=None: getattr(op, k, d)
                return _dumps(
                    {
                        "sku": g("sku", op_id),
                        "designação": g("nm", "?"),
                        "máquina": g("m", "?"),
                        "ferramenta": g("t", "?"),
                        "peças/hora": g("pH", "?"),
                        "stock": 0,
                        "atraso": g("atr", 0),
                        "gémea": g("twin", None),
                        "fonte": "engine_data (parcial — carrega ISOP para dados completos)",
                    }
                )

    if copilot_state.isop_data is None and copilot_state.engine_data is None:
        return _dumps({"error": "Sem dados carregados. Carrega o ISOP primeiro."})
    return _dumps({"error": f"Referência {sku_code} não encontrada."})


def _exec_ver_alertas(args: dict) -> str:
    alerts = copilot_state.alerts or []
    severity = args.get("severity", "all")
    limit = args.get("limit", 10)
    if severity != "all":
        alerts = [a for a in alerts if a.get("severity") == severity]
    if not alerts and copilot_state.isop_data is None and copilot_state.engine_data is None:
        return _dumps({"info": "Sem dados carregados. Carrega o ISOP para ver alertas."})
    if not alerts:
        return _dumps({"info": "Tudo OK — sem alertas activos.", "total": 0})
    return _dumps({"alertas": alerts[:limit], "total": len(alerts)})


def _exec_ver_carga_maquinas(args: dict) -> str:
    if not copilot_state.blocks:
        return _dumps({"error": "Plano não carregado."})
    machine_id = args.get("machine_id")
    machines: dict[str, dict] = {}
    for b in copilot_state.blocks:
        m_id = b.get("machine_id", b.get("machine", ""))
        if machine_id and m_id != machine_id:
            continue
        if m_id not in machines:
            machines[m_id] = {"jobs": 0, "minutos_producao": 0, "pecas_total": 0}
        machines[m_id]["jobs"] += 1
        machines[m_id]["minutos_producao"] += b.get("production_minutes", 0)
        machines[m_id]["pecas_total"] += b.get("qty", 0)
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

    # Auto-recalculate
    if copilot_state.engine_data is not None:
        recalc = _exec_recalcular_plano({})
        return _dumps(
            {
                "status": "ok",
                "message": f"Regra de agrupamento criada: {rule_id}",
                "rule_id": rule_id,
                "recalculo": json.loads(recalc),
            }
        )
    return _dumps(
        {
            "status": "ok",
            "message": f"Regra de agrupamento criada: {rule_id}",
            "rule_id": rule_id,
        }
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

    # Auto-recalculate
    if copilot_state.engine_data is not None:
        recalc = _exec_recalcular_plano({})
        return _dumps(
            {
                "status": "ok",
                "message": f"Referência {sku} movida para {target}.",
                "recalculo": json.loads(recalc),
            }
        )
    return _dumps({"status": "ok", "message": f"Referência {sku} movida para {target}."})


def _exec_recalcular_plano(_args: dict) -> str:
    """Run Python scheduler with current engine_data + copilot rules."""
    if copilot_state.engine_data is None:
        return _dumps(
            {
                "status": "error",
                "message": "Sem dados de engine. Carrega o ISOP e corre o scheduling primeiro.",
            }
        )

    import time

    from ..scheduling.overflow.auto_route_overflow import auto_route_overflow
    from ..scheduling.types import EngineData, MoveAction

    try:
        # Reconstruct EngineData from stored dict
        ed_raw = copilot_state.engine_data
        ed = EngineData(**ed_raw) if isinstance(ed_raw, dict) else ed_raw

        # Apply copilot rules
        rules = copilot_state.get_rules()
        ops = _apply_rules_to_ops(list(ed.ops), rules)
        user_moves = [MoveAction(**m) for m in _rules_to_user_moves(rules)]

        old_kpis = copilot_state.kpis

        t0 = time.perf_counter()
        result = auto_route_overflow(
            ops=ops,
            m_st=ed.m_st,
            t_st=ed.t_st,
            user_moves=user_moves,
            machines=ed.machines,
            tool_map=ed.tool_map,
            workdays=ed.workdays,
            n_days=ed.n_days,
            workforce_config=ed.workforce_config,
            rule="EDD",
            third_shift=ed.third_shift,
            twin_validation_report=ed.twin_validation_report,
            order_based=ed.order_based,
            max_tier=4,
        )
        elapsed = time.perf_counter() - t0

        blocks = result.get("blocks", [])
        total = len(blocks)
        infeasible = sum(1 for b in blocks if getattr(b, "block_type", None) == "infeasible")
        total_qty = sum(getattr(b, "qty", 0) for b in blocks)
        otd_pct = round((1 - infeasible / max(total, 1)) * 100, 1) if total > 0 else 100.0

        new_kpis: dict[str, Any] = {
            "total_blocks": total,
            "infeasible_blocks": infeasible,
            "total_qty": total_qty,
            "otd_pct": otd_pct,
        }

        # Update copilot state
        copilot_state.update_from_schedule_result(
            {
                "blocks": blocks,
                "decisions": result.get("decisions", []),
                "feasibility_report": result.get("feasibility_report"),
                "auto_moves": result.get("auto_moves", []),
                "kpis": new_kpis,
                "engine_data": copilot_state.engine_data,
                "solver_used": "atcs_python",
                "solve_time_s": round(elapsed, 3),
            }
        )

        return _dumps(
            {
                "status": "ok",
                "message": f"Plano recalculado. {total} blocos, OTD {otd_pct}%.",
                "kpis": new_kpis,
                "kpis_anteriores": old_kpis,
                "solve_time_s": round(elapsed, 3),
                "n_rules_applied": len(rules),
            }
        )

    except Exception as e:
        logger.exception("recalcular_plano error")
        return _dumps({"status": "error", "message": str(e)})


def _exec_explicar_decisao(args: dict) -> str:
    """Explain why a production block is scheduled where it is."""
    if not copilot_state.decisions:
        return _dumps({"error": "Plano não calculado. Sem decisões disponíveis."})

    sku = args["sku"]
    machine = args.get("machine_id")
    day = args.get("day_idx")

    relevant = copilot_state.get_decisions_for_sku(sku)

    if machine:
        relevant = [d for d in relevant if d.get("machine_id", "") == machine]
    if day is not None:
        relevant = [d for d in relevant if d.get("day_idx") == day]

    if not relevant:
        return _dumps({"info": f"Sem decisões registadas para {sku}."})

    formatted = []
    for d in relevant:
        formatted.append(
            {
                "tipo": d.get("type", "?"),
                "detalhe": d.get("detail", "?"),
                "máquina": d.get("machine_id", "?"),
                "dia": d.get("day_idx"),
                "turno": d.get("shift"),
                "op_id": d.get("op_id", "?"),
            }
        )

    return _dumps({"decisões": formatted, "total": len(formatted), "sku": sku})


def _exec_explicar_logica(args: dict) -> str:
    """Explain scheduling logic for a given aspect."""
    aspecto = args.get("aspecto", "geral")

    explicacoes = {
        "geral": (
            "O scheduling usa um pipeline de 8 passos:\n"
            "1. Backward scheduling (calcular quando começar com base no lead time)\n"
            "2. Agrupar demand por ferramenta/máquina/deadline\n"
            "3. Merge de peças gémeas (mesma ferramenta = 1 produção)\n"
            "4. Ordenar pela dispatch rule (ATCS por defeito)\n"
            "5. Alocar turno a turno, respeitando 4 constraints\n"
            "6. Nivelar carga entre máquinas\n"
            "7. Merge de blocos adjacentes\n"
            "8. Verificar deadlines e marcar infeasible"
        ),
        "dispatch": (
            "ATCS (Apparent Tardiness Cost with Setups):\n"
            "Prioridade = (peso/tempo) × exp(-folga/(k1×média)) × exp(-setup/(k2×média_setup))\n"
            "Combina urgência de entrega com custo de setup.\n"
            "5 regras disponíveis: ATCS, EDD, CR, SPT, WSPT.\n"
            "UCB1 bandit selecciona a melhor automaticamente."
        ),
        "constraints": (
            "4 constraints HARD:\n"
            "1. SetupCrew: max 1 setup simultâneo em toda a fábrica\n"
            "2. ToolTimeline: ferramenta em 1 máquina de cada vez\n"
            "3. CalcoTimeline: calço em 1 máquina de cada vez\n"
            "4. OperatorPool: capacidade por turno (advisory, não bloqueia)"
        ),
        "overflow": (
            "Quando uma operação não cabe:\n"
            "Tier 1: Avançar produção ou mover para alternativa\n"
            "Tier 2: Tardiness — advance + alt + combo + batch\n"
            "Tier 3: OTD-Delivery — 7 fases A-G com multi-regra\n"
            "Se nada resulta → infeasible (sinalizado no Gantt)"
        ),
        "twins": (
            "Peças gémeas = mesma ferramenta + máquina.\n"
            "Produção simultânea: qty = max(A, B), tempo = 1x.\n"
            "Excedente da gémea menor → stock.\n"
            "Emparelhamento cross-EDD: 1ª-1ª, 2ª-2ª por deadline."
        ),
        "alertas": (
            "ATRASO: coluna ATRASO negativa no ISOP → falha já aconteceu (prioridade #1)\n"
            "RED: faltam peças para amanhã\n"
            "YELLOW: faltam peças dentro de 2-3 dias\n"
            "GREEN: sem problema (stock cobre)"
        ),
        "replan": (
            "4 níveis de replaneamento:\n"
            "1. Right-shift (<30min): empurrar blocos seguintes\n"
            "2. Match-up (30min-2h): reagendar zona afectada\n"
            "3. Parcial (>2h): recalcular parte do plano\n"
            "4. Regeneração total: recalcular tudo"
        ),
    }

    return _dumps({"lógica": explicacoes.get(aspecto, explicacoes["geral"])})


def _exec_ver_decisoes(args: dict) -> str:
    """Return audit trail of scheduling decisions."""
    if not copilot_state.decisions:
        return _dumps({"error": "Plano não calculado. Sem decisões disponíveis."})

    decisions = list(copilot_state.decisions)
    tipo = args.get("tipo")
    machine_id = args.get("machine_id")
    limit = args.get("limit", 20)

    if tipo:
        decisions = [d for d in decisions if d.get("type") == tipo]
    if machine_id:
        decisions = [d for d in decisions if d.get("machine_id") == machine_id]

    return _dumps(
        {
            "decisões": decisions[:limit],
            "total": len(decisions),
            "filtros": {"tipo": tipo, "machine_id": machine_id},
        }
    )


def _exec_sugerir_melhorias(args: dict) -> str:
    if not copilot_state.blocks:
        return _dumps({"error": "Plano não carregado."})
    kpis = copilot_state.kpis or {}
    suggestions: list[str] = []

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

    machine_loads: dict[str, int] = {}
    for b in copilot_state.blocks:
        m = b.get("machine_id", b.get("machine", "?"))
        machine_loads[m] = machine_loads.get(m, 0) + b.get("production_minutes", 0)
    if machine_loads:
        max_m = max(machine_loads, key=lambda k: machine_loads[k])
        min_m = min(machine_loads, key=lambda k: machine_loads[k])
        if machine_loads[max_m] > machine_loads[min_m] * 1.5:
            suggestions.append(
                f"Desequilíbrio de carga: {max_m} ({machine_loads[max_m]}min) vs "
                f"{min_m} ({machine_loads[min_m]}min). Considerar mover referências."
            )

    if not suggestions:
        suggestions.append("Plano parece equilibrado. Sem sugestões imediatas.")

    return _dumps({"sugestões": suggestions})


def _exec_ver_producao_hoje(args: dict) -> str:
    """Show today's planned production grouped by machine."""
    if not copilot_state.blocks:
        return _dumps({"error": "Plano não carregado."})
    day_idx = args.get("day_idx", 0)
    machines: dict[str, list[dict]] = {}
    for b in copilot_state.blocks:
        b_day = b.get("day_idx", b.get("dayIdx", -1))
        if b_day != day_idx:
            continue
        m_id = b.get("machine_id", b.get("machineId", b.get("machine", "")))
        if m_id not in machines:
            machines[m_id] = []
        machines[m_id].append(
            {
                "op_id": b.get("op_id", b.get("opId", "?")),
                "tool": b.get("tool_id", b.get("toolId", "?")),
                "qty": b.get("qty", 0),
                "start": b.get("start_min", b.get("startMin", 0)),
                "end": b.get("end_min", b.get("endMin", 0)),
                "turno": b.get("shift", "?"),
            }
        )
    if not machines:
        return _dumps({"info": f"Sem produção planeada para o dia {day_idx}.", "day_idx": day_idx})
    total_qty = sum(item["qty"] for items in machines.values() for item in items)
    total_blocks = sum(len(items) for items in machines.values())
    return _dumps(
        {
            "day_idx": day_idx,
            "máquinas": machines,
            "total_blocos": total_blocks,
            "total_peças": total_qty,
        }
    )


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
