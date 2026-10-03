"""Visualization executors — Spec 10.

8 executors returning JSON with viz_type + data for frontend widgets.
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
    if state.engine_data is None:
        return _dumps({"error": "Sem dados carregados. Carrega um ISOP primeiro."})
    return None


# ─── 1. visualizar_stock ─────────────────────────────────────────────────


def exec_visualizar_stock(args: dict) -> str:
    if err := _guard():
        return err

    from backend.analytics.stock_projection import compute_stock_projections

    sku = args.get("sku", "")
    projections = state.stock_projections or compute_stock_projections(
        state.segments,
        state.lots,
        state.engine_data,
    )

    proj = next((p for p in projections if p.sku == sku), None)
    if not proj:
        return _dumps({"error": f"SKU {sku} não encontrado nas projecções."})

    days = []
    stock_series = []
    demand_series = []
    produced_series = []

    for d in proj.days:
        days.append(d.date or str(d.day_idx))
        stock_series.append(d.stock)
        demand_series.append(d.cum_demand)
        produced_series.append(d.cum_produced)

    return _dumps(
        {
            "viz_type": "line_chart",
            "title": f"Stock — {sku} ({proj.client})",
            "data": {
                "labels": days,
                "series": [
                    {"name": "Stock", "values": stock_series},
                    {"name": "Procura acumulada", "values": demand_series},
                    {"name": "Produção acumulada", "values": produced_series},
                ],
            },
            "meta": {
                "stock_inicial": proj.initial_stock,
                "stockout_day": proj.stockout_day,
                "cobertura_dias": proj.coverage_days,
            },
        }
    )


# ─── 2. visualizar_carga_temporal ────────────────────────────────────────


def exec_visualizar_carga_temporal(args: dict) -> str:
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

    machines = sorted(load.keys())
    days = list(range(dia_inicio, dia_fim))

    series = []
    for mid in machines:
        values = []
        for day_idx in days:
            capacity = available_machine_capacity(
                mid,
                day_idx,
                state.engine_data,
                state.config,
            )
            values.append(
                round(load[mid].get(day_idx, 0) / capacity * 100, 1)
                if capacity > 0
                else 0.0
            )
        series.append({"name": mid, "values": values})

    return _dumps(
        {
            "viz_type": "bar_chart",
            "title": "Carga máquinas (%)",
            "data": {
                "labels": [str(d) for d in days],
                "series": series,
            },
            "meta": {"day_cap": day_cap, "capacity_rule": "factory_real_available"},
        }
    )


# ─── 3. visualizar_risco_heatmap ─────────────────────────────────────────


def exec_visualizar_risco_heatmap(args: dict) -> str:
    if err := _guard():
        return err

    from backend.risk import compute_risk

    risk = state.risk_result or compute_risk(
        state.segments, state.lots, state.engine_data, config=state.config
    )

    cells = []
    for cell in risk.heatmap:
        cells.append(
            {
                "maquina": cell.machine_id,
                "dia": cell.day_idx,
                "utilizacao": round(cell.utilization, 2),
                "risco": cell.risk_level,
            }
        )

    return _dumps(
        {
            "viz_type": "heatmap",
            "title": "Risco (máquina × dia)",
            "data": {"cells": cells},
            "meta": {
                "health_score": risk.health_score,
                "critical_count": risk.critical_count,
                "bottleneck": risk.bottleneck,
            },
        }
    )


# ─── 4. visualizar_encomendas ────────────────────────────────────────────


def exec_visualizar_encomendas(args: dict) -> str:
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

    rows = []
    for co in client_orders:
        for o in co.orders:
            rows.append(
                {
                    "cliente": o.client,
                    "sku": o.sku,
                    "qty": o.order_qty,
                    "dia_entrega": o.delivery_day,
                    "data_entrega": o.delivery_date,
                    "status": o.status,
                    "maquina": o.production_machine,
                    "cobertura": f"{getattr(o, 'days_early', 0)}d early",
                }
            )

    return _dumps(
        {
            "viz_type": "table",
            "title": "Encomendas",
            "data": {
                "columns": [
                    "cliente",
                    "sku",
                    "qty",
                    "dia_entrega",
                    "data_entrega",
                    "status",
                    "maquina",
                    "cobertura",
                ],
                "rows": rows,
            },
        }
    )


# ─── 5. visualizar_expedicao ─────────────────────────────────────────────


def exec_visualizar_expedicao(args: dict) -> str:
    if err := _guard():
        return err

    from backend.analytics.expedition import compute_expedition

    kpis = state.expedition or compute_expedition(state.segments, state.lots, state.engine_data)

    dia_inicio = args.get("dia_inicio", 0)
    dia_fim = args.get("dia_fim", len(kpis.days))

    rows = []
    for day in kpis.days:
        if dia_inicio <= day.day_idx < dia_fim:
            rows.append(
                {
                    "dia": day.day_idx,
                    "data": day.date,
                    "total_encomendas": day.total_orders,
                    "prontas": day.total_ready,
                    "parciais": day.total_partial,
                    "nao_planeadas": day.total_not_planned,
                }
            )

    return _dumps(
        {
            "viz_type": "table",
            "title": "Expedição",
            "data": {
                "columns": [
                    "dia",
                    "data",
                    "total_encomendas",
                    "prontas",
                    "parciais",
                    "nao_planeadas",
                ],
                "rows": rows,
            },
            "meta": {
                "fill_rate": round(kpis.fill_rate, 2),
                "at_risk_count": kpis.at_risk_count,
            },
        }
    )


# ─── 6. visualizar_gantt ─────────────────────────────────────────────────


def exec_visualizar_gantt(args: dict) -> str:
    if err := _guard():
        return err

    maquina_filter = args.get("maquina")
    dia_inicio = args.get("dia_inicio", 0)
    dia_fim = args.get("dia_fim", 10)

    events = []
    for s in state.segments:
        if s.day_idx < dia_inicio or s.day_idx >= dia_fim:
            continue
        if maquina_filter and s.machine_id != maquina_filter:
            continue

        events.append(
            {
                "maquina": s.machine_id,
                "tool": s.tool_id,
                "sku": s.sku,
                "dia": s.day_idx,
                "inicio_min": s.start_min,
                "fim_min": s.end_min,
                "turno": s.shift,
                "qty": s.qty,
                "setup_min": round(s.setup_min, 1),
                "prod_min": round(s.prod_min, 1),
            }
        )

    return _dumps(
        {
            "viz_type": "timeline",
            "title": "Gantt",
            "data": {"events": events},
        }
    )


# ─── 7. visualizar_comparacao ─────────────────────────────────────────────


def exec_visualizar_comparacao(args: dict) -> str:
    if err := _guard():
        return err

    from backend.simulator.simulator import Mutation, simulate

    mutacoes_raw = args.get("mutacoes", [])
    mutations = [Mutation(type=m["type"], params=m.get("params", {})) for m in mutacoes_raw]

    result = simulate(
        state.engine_data,
        state.score,
        mutations,
        config=state.config,
    )

    return _dumps(
        {
            "viz_type": "kpi_compare",
            "title": "Comparação: actual vs cenário",
            "data": {
                "baseline": {
                    "otd": result.delta.otd_before,
                    "otd_d": result.delta.otd_d_before,
                    "setups": result.delta.setups_before,
                    "tardy": result.delta.tardy_before,
                    "earliness": result.delta.earliness_before,
                },
                "cenario": {
                    "otd": result.delta.otd_after,
                    "otd_d": result.delta.otd_d_after,
                    "setups": result.delta.setups_after,
                    "tardy": result.delta.tardy_after,
                    "earliness": result.delta.earliness_after,
                },
            },
            "meta": {
                "time_ms": result.time_ms,
                "resumo": result.summary,
            },
        }
    )


# ─── 8. visualizar_learning ──────────────────────────────────────────────


def exec_visualizar_learning(args: dict) -> str:
    from backend.learning.store import LearnStore

    store = LearnStore()
    history = store.load_history(limit=20)

    labels = []
    reward_series = []
    baseline_series = []

    for entry in history:
        labels.append(entry.get("created_at", ""))
        reward_series.append(entry.get("reward", 0))
        baseline_series.append(entry.get("baseline_reward", 0))

    return _dumps(
        {
            "viz_type": "line_chart",
            "title": "Aprendizagem ao longo do tempo",
            "data": {
                "labels": labels,
                "series": [
                    {"name": "Reward (optimizado)", "values": reward_series},
                    {"name": "Reward (baseline)", "values": baseline_series},
                ],
            },
        }
    )


# ─── 9. visualizar_atrasos ──────────────────────────────────────────────


def exec_visualizar_atrasos(args: dict) -> str:
    if err := _guard():
        return err

    from backend.analytics.late_delivery import analyze_late_deliveries

    late = state.late_deliveries or analyze_late_deliveries(
        state.segments,
        state.lots,
        state.engine_data,
        state.config,
    )

    rows = []
    for a in late.analyses:
        rows.append(
            {
                "lot_id": a.lot_id,
                "sku": a.sku,
                "edd": a.edd,
                "completion_day": a.completion_day,
                "delay_days": a.delay_days,
                "root_cause": a.root_cause,
                "explanation": a.explanation,
            }
        )

    return _dumps(
        {
            "viz_type": "table",
            "title": f"Atrasos ({late.tardy_count} lots)",
            "data": {
                "columns": [
                    "lot_id",
                    "sku",
                    "edd",
                    "completion_day",
                    "delay_days",
                    "root_cause",
                    "explanation",
                ],
                "rows": rows,
            },
            "meta": {
                "tardy_count": late.tardy_count,
                "avg_delay": late.avg_delay,
                "summary": late.suggestion,
            },
        }
    )


# ─── 10. visualizar_workforce ────────────────────────────────────────────


def exec_visualizar_workforce(args: dict) -> str:
    if err := _guard():
        return err

    from backend.analytics.workforce_forecast import forecast_workforce

    window = args.get("window", 5)
    from backend.calendar import current_factory_day

    wf = forecast_workforce(state.segments, state.engine_data, state.config, window=window,
                            start_day=current_factory_day(state.engine_data, state.config))

    by_day: dict[int, dict[str, int]] = {}
    for item in wf.daily:
        row = by_day.setdefault(item.day_idx, {"required": 0, "available": 0})
        row["required"] += item.required
        row["available"] += item.available
    days = sorted(by_day)

    return _dumps(
        {
            "viz_type": "bar_chart",
            "title": f"Workforce (próximos {window} dias)",
            "data": {
                "labels": [str(day) for day in days],
                "series": [
                    {
                        "name": "Necessários",
                        "values": [by_day[day]["required"] for day in days],
                    },
                    {
                        "name": "Disponíveis",
                        "values": [by_day[day]["available"] for day in days],
                    },
                ],
            },
            "meta": {
                "peak_day": wf.peak_day,
                "peak_operators": wf.peak_required,
                "trend": wf.trend,
                "deficit_days": wf.deficit_days,
            },
        }
    )


# ─── 11. visualizar_cobertura ────────────────────────────────────────────


def exec_visualizar_cobertura(args: dict) -> str:
    if err := _guard():
        return err

    from backend.analytics.coverage_audit import compute_coverage_audit

    cov = state.coverage or compute_coverage_audit(
        state.segments,
        state.lots,
        state.engine_data,
    )

    rows = []
    for c in cov.clients:
        rows.append(
            {
                "cliente": c.client,
                "total_encomendas": c.total_orders,
                "cobertas": c.covered_orders,
                "cobertura_pct": c.coverage_pct,
                "em_risco": c.at_risk_orders,
                "pior_sku": c.worst_sku,
            }
        )

    return _dumps(
        {
            "viz_type": "table",
            "title": f"Cobertura ({cov.overall_coverage_pct:.0f}%)",
            "data": {
                "columns": [
                    "cliente",
                    "total_encomendas",
                    "cobertas",
                    "cobertura_pct",
                    "em_risco",
                    "pior_sku",
                ],
                "rows": rows,
            },
            "meta": {
                "overall_coverage_pct": cov.overall_coverage_pct,
                "fill_rate": cov.overall_fill_rate,
                "stockout_count": cov.stockout_count,
                "health_score": cov.health_score,
                "summary": cov.summary,
            },
        }
    )


# ─── 12. visualizar_propostas ────────────────────────────────────────────


def exec_visualizar_propostas(args: dict) -> str:
    if err := _guard():
        return err

    from backend.analytics.replan_proposals import generate_proposals

    report = generate_proposals(
        state.segments,
        state.lots,
        state.engine_data,
        state.score,
        state.config,
    )

    rows = []
    for p in report.proposals:
        rows.append(
            {
                "id": p.id,
                "tipo": p.type,
                "descricao": p.description,
                "impacto": p.estimated_impact,
                "prioridade": p.priority,
                "maquina_de": p.machine_from,
                "maquina_para": p.machine_to,
            }
        )

    return _dumps(
        {
            "viz_type": "table",
            "title": f"Propostas de Melhoria ({len(report.proposals)})",
            "data": {
                "columns": [
                    "id",
                    "tipo",
                    "descricao",
                    "impacto",
                    "prioridade",
                    "maquina_de",
                    "maquina_para",
                ],
                "rows": rows,
            },
            "meta": {
                "current_tardy": report.current_tardy,
                "current_setups": report.current_setups,
                "summary": report.summary,
            },
        }
    )
