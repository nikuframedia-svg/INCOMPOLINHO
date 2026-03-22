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
        try:
            recalc = _exec_recalcular_plano({})
            return _dumps(
                {
                    "status": "ok",
                    "message": f"Regra '{args['name']}' criada.",
                    "recalculo": json.loads(recalc),
                }
            )
        except Exception:
            logger.exception("Auto-recalculate failed after adding rule '%s'", args["name"])
    return _dumps({"status": "ok", "message": f"Regra '{args['name']}' criada."})


def _exec_remover_regra(args: dict) -> str:
    removed = copilot_state.remove_rule(args["id"])
    if not removed:
        return _dumps({"error": f"Regra {args['id']} não encontrada."})

    if copilot_state.engine_data is not None:
        try:
            recalc = _exec_recalcular_plano({})
            return _dumps(
                {
                    "status": "ok",
                    "message": f"Regra {args['id']} removida.",
                    "recalculo": json.loads(recalc),
                }
            )
        except Exception:
            logger.exception("Auto-recalculate failed after removing rule '%s'", args["id"])
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
        try:
            recalc = _exec_recalcular_plano({})
            return _dumps(
                {
                    "status": "ok",
                    "message": f"Regra de agrupamento criada: {rule_id}",
                    "rule_id": rule_id,
                    "recalculo": json.loads(recalc),
                }
            )
        except Exception:
            logger.exception("Auto-recalculate failed after grouping material")
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
        try:
            recalc = _exec_recalcular_plano({})
            return _dumps(
                {
                    "status": "ok",
                    "message": f"Referência {sku} movida para {target}.",
                    "recalculo": json.loads(recalc),
                }
            )
        except Exception:
            logger.exception("Auto-recalculate failed after moving ref '%s'", sku)
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

    try:
        from ..scheduling.overflow.auto_route_overflow import auto_route_overflow
        from ..scheduling.types import EngineData, MoveAction

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


def _exec_ver_robustez(_args: dict) -> str:
    """Show Monte Carlo robustness analysis from the optimal pipeline."""
    sr = copilot_state.solver_result
    if sr is None:
        return _dumps(
            {
                "error": "Nenhuma análise de robustez disponível. "
                "Execute o solver CP-SAT (pipeline óptimo) primeiro."
            }
        )

    robustness = sr.get("robustness")
    if robustness is None:
        return _dumps(
            {
                "info": "Solver CP-SAT executou mas sem análise Monte Carlo.",
                "solver_status": sr.get("status"),
                "tardiness": sr.get("tardiness"),
            }
        )

    vulnerable = robustness.get("vulnerable_jobs", [])
    buffers = robustness.get("suggested_buffers", [])

    return _dumps(
        {
            "robustez": {
                "P(OTD=100%)": f"{robustness.get('p_otd_100', 0)}%",
                "P(OTD>=95%)": f"{robustness.get('p_otd_95', 0)}%",
                "tardiness_média": f"{robustness.get('mean_tardiness', 0)} min",
                "cenários": robustness.get("n_scenarios", 0),
                "tempo_análise": f"{robustness.get('elapsed_s', 0)}s",
            },
            "jobs_vulneráveis": [
                {
                    "job": v.get("job_id"),
                    "atrasado_em": f"{v.get('late_pct', 0)}% dos cenários",
                    "atraso_médio": f"{v.get('avg_tardiness_min', 0)} min",
                }
                for v in vulnerable[:10]
            ],
            "buffers_sugeridos": [
                {
                    "job": b.get("job_id"),
                    "buffer": f"{b.get('buffer_min', 0)} min",
                    "razão": b.get("reason", ""),
                }
                for b in buffers[:10]
            ],
        }
    )


def _exec_check_ctp(args: dict) -> str:
    """CTP analysis via backend endpoint logic."""
    nikufra_data = copilot_state.nikufra_data
    if not nikufra_data:
        return _dumps({"error": "Sem dados ISOP carregados. Carrega o ISOP primeiro."})

    try:
        from ...api.v1.schedule import _nikufra_to_plan_state
        from ..scheduling.mrp.ctp import CTPInput, compute_ctp
        from ..scheduling.mrp.mrp_ctp_sku import CTPSkuInput, compute_ctp_sku
        from ..scheduling.mrp.mrp_engine import compute_mrp
        from ..scheduling.transform import transform_plan_state

        plan_state = _nikufra_to_plan_state(nikufra_data)
        engine = transform_plan_state(plan_state, demand_semantics="raw_np", order_based=True)
        mrp = compute_mrp(engine)

        sku = args["sku"]
        qty = args["quantity"]
        target_day = args["target_day"]

        best = compute_ctp_sku(
            CTPSkuInput(sku=sku, quantity=qty, target_day=target_day),
            mrp,
            engine,
        )
        if not best:
            return _dumps({"error": f"SKU {sku} não encontrado ou sem dados CTP."})

        result: dict[str, Any] = {
            "sku": sku,
            "quantidade": qty,
            "dia_alvo": target_day,
            "viável": best.feasible,
            "dia_mais_cedo": best.earliest_feasible_day,
            "data": engine.dates[best.earliest_feasible_day]
            if best.earliest_feasible_day is not None
            and best.earliest_feasible_day < len(engine.dates)
            else None,
            "máquina": best.machine,
            "minutos_necessários": best.required_min,
            "minutos_disponíveis": best.available_min_on_day,
            "confiança": best.confidence,
            "razão": best.reason,
        }

        # Try alt machine if best is not ideal
        op = next((o for o in engine.ops if o.sku == sku), None)
        tool = engine.tool_map.get(op.t) if op else None
        if (
            tool
            and tool.alt
            and tool.alt != "-"
            and (not best.feasible or (best.earliest_feasible_day or 99) > target_day)
        ):
            alt = compute_ctp(
                CTPInput(tool_code=tool.id, quantity=qty, target_day=target_day),
                mrp,
                engine,
            )
            if alt and alt.feasible and alt.machine != best.machine:
                result["alternativa"] = {
                    "máquina": alt.machine,
                    "dia_mais_cedo": alt.earliest_feasible_day,
                    "confiança": alt.confidence,
                }

        return _dumps(result)
    except Exception as e:
        logger.exception("check_ctp error")
        return _dumps({"error": str(e)})


def _exec_schedule_whatif(args: dict) -> str:
    """What-if simulation via backend logic."""
    nikufra_data = copilot_state.nikufra_data
    if not nikufra_data:
        return _dumps({"error": "Sem dados ISOP carregados."})

    try:
        import copy
        import time as _time

        from ...api.v1.schedule import _compute_delta, _solve_and_analyze

        mutations = args.get("mutations", [])
        settings = copilot_state.get_config()

        t0 = _time.perf_counter()
        baseline = _solve_and_analyze(nikufra_data, settings)

        # Apply mutations
        mutated_data = copy.deepcopy(nikufra_data)
        mutated_settings = copy.deepcopy(settings)
        for m in mutations:
            m_type = m.get("type", "")
            target = m.get("target_id", "")
            params = m.get("params", {})

            if m_type == "machine_down":
                m_st = mutated_settings.get("m_st", {})
                m_st[target] = "down"
                mutated_settings["m_st"] = m_st
            elif m_type in ("add_demand", "rush_order"):
                ops = mutated_data.get("operations", [])
                for op in ops:
                    if op.get("id") == target or op.get("sku") == target:
                        day_idx = params.get("day_idx", 0)
                        qty = params.get("qty", 0)
                        d = op.get("d", [])
                        while len(d) <= day_idx:
                            d.append(None)
                        d[day_idx] = -abs(qty)
                        op["d"] = d
                        break
            elif m_type == "remove_demand":
                ops = mutated_data.get("operations", [])
                for op in ops:
                    if op.get("id") == target or op.get("sku") == target:
                        day_idx = params.get("day_idx", 0)
                        d = op.get("d", [])
                        if day_idx < len(d):
                            d[day_idx] = None
                        op["d"] = d
                        break

        scenario = _solve_and_analyze(mutated_data, mutated_settings)
        delta = _compute_delta(baseline, scenario)
        elapsed = _time.perf_counter() - t0

        return _dumps(
            {
                "status": "ok",
                "tempo": f"{elapsed:.1f}s",
                "baseline_kpis": {
                    k: baseline.get("score", {}).get(k)
                    for k in ("otdDelivery", "otdGlobal", "tardyBlocks", "makespan")
                },
                "cenário_kpis": {
                    k: scenario.get("score", {}).get(k)
                    for k in ("otdDelivery", "otdGlobal", "tardyBlocks", "makespan")
                },
                "delta": delta,
                "mutações": len(mutations),
            }
        )
    except Exception as e:
        logger.exception("schedule_whatif error")
        return _dumps({"error": str(e)})


def _exec_simulate_overtime(args: dict) -> str:
    """Simulate 3rd shift (night) on one or all machines."""
    nikufra_data = copilot_state.nikufra_data
    if not nikufra_data:
        return _dumps({"error": "Sem dados ISOP carregados."})

    try:
        import time as _time

        from ...api.v1.schedule import _solve_and_analyze

        settings_base = copilot_state.get_config()
        settings_overtime = {**settings_base, "thirdShift": True}
        machine_id = args.get("machine_id")

        t0 = _time.perf_counter()
        baseline = _solve_and_analyze(nikufra_data, settings_base)
        overtime_result = _solve_and_analyze(nikufra_data, settings_overtime)
        elapsed = _time.perf_counter() - t0

        bs = baseline.get("score", {})
        os_score = overtime_result.get("score", {})

        result: dict[str, Any] = {
            "status": "ok",
            "tempo": f"{elapsed:.1f}s",
            "sem_3o_turno": {
                "otd_delivery": bs.get("otdDelivery"),
                "blocos_atrasados": bs.get("tardyBlocks"),
                "total_blocos": baseline.get("n_blocks"),
            },
            "com_3o_turno": {
                "otd_delivery": os_score.get("otdDelivery"),
                "blocos_atrasados": os_score.get("tardyBlocks"),
                "total_blocos": overtime_result.get("n_blocks"),
            },
        }

        tardy_diff = (bs.get("tardyBlocks", 0) or 0) - (os_score.get("tardyBlocks", 0) or 0)
        if tardy_diff > 0:
            result["impacto"] = f"3º turno resolve {tardy_diff} blocos atrasados."
        elif tardy_diff == 0:
            result["impacto"] = "3º turno não melhora atrasos — capacidade já é suficiente."
        else:
            result["impacto"] = "Resultado inesperado — verificar manualmente."

        if machine_id:
            result["nota"] = (
                f"Simulação global (3º turno em todas). "
                f"Filtro por {machine_id} requer análise per-machine."
            )

        return _dumps(result)
    except Exception as e:
        logger.exception("simulate_overtime error")
        return _dumps({"error": str(e)})


def _exec_explicar_decisao_id(args: dict) -> str:
    """Explain a specific decision by ID with detailed reasoning."""
    if not copilot_state.decisions:
        return _dumps({"error": "Plano não calculado. Sem decisões disponíveis."})

    decision_id = args["decision_id"]

    match = None
    partial_matches: list[dict] = []
    for d in copilot_state.decisions:
        d_id = d.get("id", d.get("op_id", ""))
        if d_id == decision_id:
            match = d
            break
        if (
            decision_id.lower() in str(d_id).lower()
            or decision_id.lower() in str(d.get("type", "")).lower()
        ):
            partial_matches.append(d)

    if match:
        reasoning = _build_decision_reasoning(match)
        return _dumps(
            {
                "decisão": {
                    "id": match.get("id", match.get("op_id", "?")),
                    "tipo": match.get("type", "?"),
                    "detalhe": match.get("detail", "?"),
                    "máquina": match.get("machine_id", "?"),
                    "dia": match.get("day_idx"),
                    "turno": match.get("shift"),
                    "sku": match.get("sku", match.get("op_id", "?")),
                },
                "raciocínio": reasoning,
            }
        )

    if partial_matches:
        return _dumps(
            {
                "info": f"ID exacto '{decision_id}' não encontrado. {len(partial_matches)} parciais.",
                "resultados": [
                    {
                        "id": d.get("id", d.get("op_id", "?")),
                        "tipo": d.get("type", "?"),
                        "detalhe": d.get("detail", "?"),
                    }
                    for d in partial_matches[:5]
                ],
            }
        )

    return _dumps({"error": f"Decisão '{decision_id}' não encontrada."})


def _build_decision_reasoning(decision: dict) -> str:
    """Build human-readable reasoning for a scheduling decision."""
    d_type = decision.get("type", "")
    detail = decision.get("detail", "")

    reasons = {
        "OVERFLOW_ROUTE": "A máquina principal não tinha capacidade. Produção movida para alternativa.",
        "ADVANCE_PRODUCTION": "Produção antecipada para cumprir o prazo — dia anterior com capacidade.",
        "TWIN_MERGE": "Peças gémeas agrupadas para produção simultânea, optimizando tempo de máquina.",
        "TOOL_CONTENTION": "Conflito de ferramenta — duas operações no mesmo período, uma reagendada.",
        "INFEASIBLE": "Impossível alocar dentro das restrições de capacidade e prazo.",
        "BATCH_ADVANCE": "Lote inteiro avançado para resolver conflito de capacidade.",
        "ALT_MACHINE": "Produção movida para máquina alternativa por falta de capacidade na principal.",
    }

    base = reasons.get(d_type, f"Decisão do tipo '{d_type}' — gerada pelo solver CP-SAT.")
    if detail:
        base += f" Detalhe: {detail}"
    return base


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
