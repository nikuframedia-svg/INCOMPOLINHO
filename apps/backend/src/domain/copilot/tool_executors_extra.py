"""Copilot engine — heavy computation tool executors (CTP, what-if, overtime, decision ID)."""

from __future__ import annotations

import logging
from typing import Any

from .state import copilot_state
from .tool_helpers import (
    _apply_rules_to_ops,
    _build_decision_reasoning,
    _dumps,
    _rules_to_user_moves,
)

logger = logging.getLogger(__name__)


# ─── Heavy Tool Executors ────────────────────────────────────────────────────


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


def _exec_check_ctp(args: dict) -> str:
    """CTP analysis via backend endpoint logic."""
    nikufra_data = copilot_state.nikufra_data
    if not nikufra_data:
        return _dumps({"error": "Sem dados ISOP carregados. Carrega o ISOP primeiro."})

    try:
        from ..nikufra.utils import nikufra_to_plan_state as _nikufra_to_plan_state
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
