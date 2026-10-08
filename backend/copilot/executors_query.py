"""Query executors — Spec 10.

10 read-only executors. Each receives args dict, returns JSON string.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

from backend.calendar import available_machine_capacity
from backend.copilot.state import state

logger = logging.getLogger(__name__)


def _dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _guard() -> str | None:
    """Return error JSON if state is not initialized, else None."""
    if state.engine_data is None:
        return _dumps({"error": "Sem dados carregados. Carrega um ISOP primeiro."})
    return None


# ─── 1. ver_producao_dia ──────────────────────────────────────────────────


def exec_ver_producao_dia(args: dict) -> str:
    if err := _guard():
        return err

    day = args.get("dia", 0)
    by_machine: dict[str, list[dict]] = defaultdict(list)

    for s in state.segments:
        if s.day_idx == day:
            by_machine[s.machine_id].append(
                {
                    "lot_id": s.lot_id,
                    "tool_id": s.tool_id,
                    "sku": s.sku,
                    "qty": s.qty,
                    "prod_min": round(s.prod_min, 1),
                    "setup_min": round(s.setup_min, 1),
                    "start_min": s.start_min,
                    "end_min": s.end_min,
                    "shift": s.shift,
                }
            )

    return _dumps(
        {
            "dia": day,
            "maquinas": dict(by_machine),
            "total_segments": sum(len(v) for v in by_machine.values()),
        }
    )


# ─── 2. ver_carga_maquinas ───────────────────────────────────────────────


def exec_ver_carga_maquinas(args: dict) -> str:
    if err := _guard():
        return err

    dia_inicio = args.get("dia_inicio", 0)
    dia_fim = args.get("dia_fim", state.engine_data.n_days)
    day_cap = state.config.day_capacity_min if state.config else 1020

    # machine → day → total_min
    load: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for s in state.segments:
        if dia_inicio <= s.day_idx < dia_fim:
            load[s.machine_id][s.day_idx] += s.prod_min + s.setup_min

    result = {}
    for mid, days in sorted(load.items()):
        result[mid] = {}
        for day_idx, minutes in sorted(days.items()):
            capacity = available_machine_capacity(
                mid,
                day_idx,
                state.engine_data,
                state.config,
            )
            result[mid][str(day_idx)] = {
                "min": round(minutes, 1),
                "pct": round(minutes / capacity * 100, 1) if capacity > 0 else 0.0,
            }

    return _dumps({
        "carga": result,
        "day_cap": day_cap,
        "capacity_rule": "factory_real_available",
    })


# ─── 3. ver_alertas ──────────────────────────────────────────────────────


def exec_ver_alertas(args: dict) -> str:
    if err := _guard():
        return err

    from backend.risk import compute_risk

    risk = state.risk_result or compute_risk(
        state.segments, state.lots, state.engine_data, config=state.config
    )

    alerts = []
    tardy = state.score.get("tardy_count", 0)
    if tardy > 0:
        alerts.append({"tipo": "tardiness", "mensagem": f"{tardy} lots em atraso"})

    if risk.critical_count > 0:
        alerts.append(
            {
                "tipo": "risco_critico",
                "mensagem": f"{risk.critical_count} lots com risco crítico",
            }
        )

    if risk.bottleneck:
        alerts.append(
            {
                "tipo": "bottleneck",
                "mensagem": f"Bottleneck: {risk.bottleneck}",
            }
        )

    alerts.append(
        {
            "tipo": "health_score",
            "mensagem": f"Health score: {risk.health_score}/100",
        }
    )

    # Operator alerts (crew conflicts)
    if state.operator_alerts:
        for oa in state.operator_alerts[:5]:
            alerts.append(
                {
                    "tipo": "operadores",
                    "mensagem": (
                        f"Dia {oa.day_idx} turno {oa.shift}: faltam {oa.deficit} operador(es)"
                    ),
                }
            )

    # Stress critical recommendations
    if state.stress_map:
        from backend.scheduler.stress import stress_recommendations

        recs = stress_recommendations(state.stress_map, state.lots, state.segments)
        for rec in recs[:3]:
            alerts.append(
                {
                    "tipo": "stress",
                    "mensagem": f"[P{rec['priority']}] {rec['machine']}: {rec['action']}",
                }
            )

    return _dumps({"alertas": alerts, "health_score": risk.health_score})


# ─── 4. ver_score ────────────────────────────────────────────────────────


def exec_ver_score(args: dict) -> str:
    if err := _guard():
        return err
    return _dumps({**state.score, "plan_revision": state.plan_revision})


# ─── 5. ver_config ───────────────────────────────────────────────────────


def exec_ver_config(args: dict) -> str:
    if state.config is None:
        return _dumps({"error": "Configuração não carregada."})

    c = state.config
    return _dumps(
        {
            "nome": c.name,
            "site": c.site,
            "timezone": c.timezone,
            "plan_revision": state.plan_revision,
            "turnos": [
                {
                    "id": s.id,
                    "inicio_min": s.start_min,
                    "fim_min": s.end_min,
                    "duracao_min": s.duration_min,
                    "label": s.label,
                }
                for s in c.shifts
            ],
            "day_capacity_min": c.day_capacity_min,
            "maquinas": {
                mid: {"grupo": m.group, "activa": m.active} for mid, m in c.machines.items()
            },
            "n_ferramentas": len(c.tools),
            "n_twins": len(c.twins),
            "n_feriados": len(c.holidays),
            "oee_default": c.oee_default,
            "jit_enabled": c.jit_enabled,
            "eco_lot_mode": c.eco_lot_mode,
        }
    )


# ─── 6. explicar_referencia ──────────────────────────────────────────────


def exec_explicar_referencia(args: dict) -> str:
    if err := _guard():
        return err

    sku = args.get("sku", "")
    op = next((o for o in state.engine_data.ops if o.sku == sku), None)
    if not op:
        return _dumps({"error": f"SKU {sku} não encontrado."})

    n_lots = sum(1 for lot in state.lots if lot.op_id == op.id)
    n_segs = sum(1 for s in state.segments if s.sku == sku)
    total_demand = sum(d for d in op.d if d > 0)

    return _dumps(
        {
            "sku": sku,
            "cliente": op.client,
            "designacao": op.designation,
            "maquina": op.m,
            "ferramenta": op.t,
            "alt_maquina": op.alt,
            "pecas_hora": op.pH,
            "setup_horas": op.sH,
            "eco_lot": op.eco_lot,
            "stock_inicial": op.stk,
            "oee": op.oee,
            "demand_total": total_demand,
            "n_lots": n_lots,
            "n_segments": n_segs,
        }
    )


# ─── 7. explicar_decisao ─────────────────────────────────────────────────


def exec_explicar_decisao(args: dict) -> str:
    if err := _guard():
        return err

    if not state.audit_store or not state.schedule_id:
        return _dumps(
            {
                "aviso": "Sem decisões registadas. Usa recalcular_plano primeiro.",
            }
        )

    sku = args.get("sku", "")
    # Find tool_id for this SKU to use as subject_id
    op = next((o for o in state.engine_data.ops if o.sku == sku), None)
    subject_id = op.t if op else sku

    decisions = state.audit_store.load_decisions(
        state.schedule_id,
        subject_id=subject_id,
    )

    return _dumps(
        {
            "sku": sku,
            "ferramenta": subject_id,
            "schedule_id": state.schedule_id,
            "decisoes": decisions[:20],  # limit to 20
        }
    )


# ─── 8. explicar_logica ──────────────────────────────────────────────────

_LOGIC_EXPLANATIONS = {
    "jit": (
        "Política JIT de libertação simulada de material: a produção começa no primeiro intervalo "
        "viável após a data permitida. Essa data fica cinco dias úteis antes da "
        "entrega ao cliente nos artigos normais e cinco dias úteis antes do envio "
        "ao fornecedor nos artigos subcontratados. O prazo de produção é a entrega "
        "nos artigos normais e o envio nos subcontratados."
    ),
    "campaign": (
        "Campaign sequencing: agrupar runs com a mesma ferramenta consecutivamente "
        "para eliminar setups. Nearest-neighbour por tool family. "
        "Interrompido quando há runs com prazo de produção mais urgente."
    ),
    "eco_lot": (
        "Eco lot HARD: cada lot é arredondado para cima ao múltiplo do lote económico. "
        "Carry-forward: surplus de um lot reduz a demand do lot seguinte do mesmo SKU."
    ),
    "twins": (
        "Peças gémeas: 2 SKUs produzidos em simultâneo com a mesma ferramenta. "
        "1 ciclo → 2 peças. Tempo = max(tempo_A, tempo_B). "
        "Cada SKU recebe exactamente o que precisa."
    ),
    "scoring": (
        "Scoring: 3 componentes com pesos — earliness (0.40), setups (0.30), "
        "utilization_balance (0.30). OTD e OTD-D são calculados mas não entram no score "
        "(são constraints, não objectivos)."
    ),
    "oee": (
        "OEE (Overall Equipment Effectiveness): default 0.66. "
        "prod_min = (qty / (pH × OEE)) × 60. OEE NÃO se aplica ao setup."
    ),
    "interleave": (
        "Interleave: quando um run urgente (EDD próximo) está bloqueado por uma "
        "campanha longa, o scheduler interrompe a campanha para produzir o urgente primeiro."
    ),
    "2opt": (
        "2-opt: optimização local que tenta trocar pares de runs na sequência "
        "para reduzir o número total de setups, respeitando a tolerância EDD."
    ),
    "lot_sizing": (
        "Lot sizing (Phase 1): converte EOps em Lots. Para cada demand > 0 num dia, "
        "cria um lot com qty = max(demand - surplus, eco_lot arredondado). "
        "Twins geram super-ops com twin_outputs."
    ),
    "tool_grouping": (
        "Tool grouping (Phase 2): agrupa Lots por ferramenta+máquina em ToolRuns. "
        "Split se gap EDD > 10 dias ou se produção excede capacidade até EDD."
    ),
}


def exec_explicar_logica(args: dict) -> str:
    conceito = args.get("conceito", "")
    text = _LOGIC_EXPLANATIONS.get(conceito)
    if not text:
        return _dumps(
            {
                "error": f"Conceito '{conceito}' desconhecido.",
                "disponiveis": list(_LOGIC_EXPLANATIONS.keys()),
            }
        )
    return _dumps({"conceito": conceito, "explicacao": text})


# ─── 9. ver_encomendas ───────────────────────────────────────────────────


def exec_ver_encomendas(args: dict) -> str:
    if err := _guard():
        return err

    from backend.analytics.order_tracking import compute_order_tracking

    client_orders = state.order_tracking or compute_order_tracking(
        state.segments,
        state.lots,
        state.engine_data,
    )

    cliente_filter = args.get("cliente")
    if cliente_filter:
        client_orders = [co for co in client_orders if cliente_filter.lower() in co.client.lower()]

    result = []
    for co in client_orders:
        orders = []
        for o in co.orders[:50]:  # limit per client
            orders.append(
                {
                    "sku": o.sku,
                    "qty": o.order_qty,
                    "dia_entrega": o.delivery_day,
                    "data_entrega": o.delivery_date,
                    "status": o.status,
                    "maquina": o.production_machine,
                    "dias_antecipacao": o.days_early,
                    "razao": o.reason,
                }
            )
        result.append(
            {
                "cliente": co.client,
                "total_encomendas": co.total_orders,
                "total_prontas": co.total_ready,
                "encomendas": orders,
            }
        )

    return _dumps({"clientes": result})


# ─── 10. ver_historico ───────────────────────────────────────────────────


def exec_ver_historico(args: dict) -> str:
    from backend.learning.store import LearnStore

    limite = args.get("limite", 20)
    store = LearnStore()
    history = store.load_history(limit=limite)

    return _dumps({"estudos": history})


# ─── 11. ver_stress ──────────────────────────────────────────────────────


def exec_ver_stress(args: dict) -> str:
    if err := _guard():
        return err

    from backend.scheduler.stress import (
        compute_stress_map,
        stress_recommendations,
        stress_summary,
    )

    smap = state.stress_map or compute_stress_map(
        state.segments,
        state.lots,
        state.engine_data.n_days,
        n_holidays=len(getattr(state.engine_data, "holidays", []) or []),
    )
    summary = stress_summary(smap)
    recs = stress_recommendations(smap, state.lots, state.segments)

    return _dumps({"resumo": summary, "recomendacoes": recs})


# ─── 12. e_se (counterfactual) ──────────────────────────────────────────


def exec_e_se(args: dict) -> str:
    """Counterfactual: 'E se a BFP079 estivesse na PRM039?'"""
    if err := _guard():
        return err

    from backend.audit.counterfactual import compute_counterfactual

    question_type = args.get("tipo", "force_machine")
    params = args.get("params", {})

    result = compute_counterfactual(
        question_type,
        params,
        state.engine_data,
        state.score,
        config=state.config,
    )

    return _dumps(
        {
            "pergunta": f"{question_type}: {params}",
            "score_original": result.original_score,
            "score_alternativo": result.alternative_score,
            "conclusao": result.conclusion,
            "time_ms": result.time_ms,
        }
    )
