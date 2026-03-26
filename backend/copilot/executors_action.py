"""Action executors — Spec 10.

8 executors that may modify state (schedule, config, rules).
"""

from __future__ import annotations

import copy
import json
import logging

from backend.copilot.state import state

logger = logging.getLogger(__name__)


def _dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _guard() -> str | None:
    if state.engine_data is None:
        return _dumps({"error": "Sem dados carregados. Carrega um ISOP primeiro."})
    return None


# ─── 1. recalcular_plano ─────────────────────────────────────────────────

def exec_recalcular_plano(args: dict) -> str:
    if (err := _guard()):
        return err

    from backend.cpo import optimize

    old_score = dict(state.score) if state.score else {}
    result = optimize(state.engine_data, mode="quick", audit=True, config=state.config)
    state.update_schedule(result)

    return _dumps({
        "status": "ok",
        "score": result.score,
        "score_anterior": old_score,
        "time_ms": result.time_ms,
        "warnings": result.warnings[:10],
    })


# ─── 2. mover_referencia ─────────────────────────────────────────────────

def exec_mover_referencia(args: dict) -> str:
    if (err := _guard()):
        return err

    from backend.cpo import optimize

    sku = args.get("sku", "")
    dest = args.get("maquina_destino", "")

    # Validate machine exists
    machine_ids = {m.id for m in state.engine_data.machines}
    if dest not in machine_ids:
        return _dumps({"error": f"Máquina {dest} não existe. Válidas: {sorted(machine_ids)}"})

    # Find ops for this SKU
    ops_found = [o for o in state.engine_data.ops if o.sku == sku]
    if not ops_found:
        return _dumps({"error": f"SKU {sku} não encontrado."})

    # Deep copy and mutate
    mutated = copy.deepcopy(state.engine_data)
    for op in mutated.ops:
        if op.sku == sku:
            op.m = dest
            op.alt = None

    # Re-schedule on mutated data
    result = optimize(mutated, mode="quick", audit=True, config=state.config)

    # Reject if tardy_count worsens
    old_tardy = state.score.get("tardy_count", 0)
    new_tardy = result.score.get("tardy_count", 0)
    if new_tardy > old_tardy:
        return _dumps({
            "status": "rejeitado",
            "razao": f"Tardiness pioraria: {old_tardy} → {new_tardy}",
            "score_proposto": result.score,
        })

    # Accept: update state with mutated data
    state.engine_data = mutated
    state.update_schedule(result)

    return _dumps({
        "status": "aceite",
        "sku": sku,
        "maquina_anterior": ops_found[0].m,
        "maquina_nova": dest,
        "score": result.score,
    })


# ─── 3. adicionar_regra ──────────────────────────────────────────────────

def exec_adicionar_regra(args: dict) -> str:
    rule = {
        "descricao": args.get("descricao", ""),
        "tipo": args.get("tipo", "preferencia"),
    }
    rule_id = state.add_rule(rule)
    return _dumps({"status": "ok", "regra_id": rule_id, "regra": rule})


# ─── 4. remover_regra ────────────────────────────────────────────────────

def exec_remover_regra(args: dict) -> str:
    rule_id = args.get("regra_id", "")
    removed = state.remove_rule(rule_id)
    if removed:
        return _dumps({"status": "ok", "regra_id": rule_id})
    return _dumps({"error": f"Regra {rule_id} não encontrada."})


# ─── 5. alterar_config ───────────────────────────────────────────────────

_ALLOWED_KEYS = {
    "oee_default": float,
    "jit_enabled": bool,
    "jit_buffer_pct": float,
    "jit_threshold": float,
    "max_run_days": int,
    "max_edd_gap": int,
    "edd_swap_tolerance": int,
    "campaign_window": int,
    "urgency_threshold": int,
    "interleave_enabled": bool,
    "weight_earliness": float,
    "weight_setups": float,
    "weight_balance": float,
}


def exec_alterar_config(args: dict) -> str:
    if state.config is None:
        return _dumps({"error": "Configuração não carregada."})

    chave = args.get("chave", "")
    valor = args.get("valor")

    if chave not in _ALLOWED_KEYS:
        return _dumps({
            "error": f"Chave '{chave}' não permitida.",
            "chaves_validas": list(_ALLOWED_KEYS.keys()),
        })

    expected_type = _ALLOWED_KEYS[chave]
    try:
        typed_value = expected_type(valor)
    except (TypeError, ValueError):
        return _dumps({"error": f"Valor '{valor}' inválido para {chave} (esperado {expected_type.__name__})."})

    old_value = getattr(state.config, chave)
    setattr(state.config, chave, typed_value)

    return _dumps({
        "status": "ok",
        "chave": chave,
        "valor_anterior": old_value,
        "valor_novo": typed_value,
        "nota": "Configuração alterada. Usa recalcular_plano para aplicar.",
    })


# ─── 6. simular_cenario ──────────────────────────────────────────────────

def exec_simular_cenario(args: dict) -> str:
    if (err := _guard()):
        return err

    from backend.simulator.simulator import Mutation, simulate

    mutacoes_raw = args.get("mutacoes", [])
    mutations = [
        Mutation(type=m["type"], params=m.get("params", {}))
        for m in mutacoes_raw
    ]

    result = simulate(
        state.engine_data, state.score, mutations, config=state.config,
    )

    return _dumps({
        "score_actual": state.score,
        "score_cenario": result.score,
        "delta": {
            "otd": f"{result.delta.otd_before:.1f}% → {result.delta.otd_after:.1f}%",
            "otd_d": f"{result.delta.otd_d_before:.1f}% → {result.delta.otd_d_after:.1f}%",
            "setups": f"{result.delta.setups_before} → {result.delta.setups_after}",
            "tardy": f"{result.delta.tardy_before} → {result.delta.tardy_after}",
        },
        "time_ms": result.time_ms,
        "resumo": result.summary,
    })


# ─── 7. simular_overtime ─────────────────────────────────────────────────

def exec_simular_overtime(args: dict) -> str:
    if (err := _guard()):
        return err

    from backend.simulator.simulator import Mutation, simulate

    maquina = args.get("maquina", "")
    minutos = args.get("minutos_extra", 0)

    mutations = [Mutation(type="overtime", params={
        "machine_id": maquina,
        "extra_min": minutos,
    })]

    result = simulate(
        state.engine_data, state.score, mutations, config=state.config,
    )

    return _dumps({
        "maquina": maquina,
        "minutos_extra": minutos,
        "score_actual": state.score,
        "score_cenario": result.score,
        "delta": {
            "otd": f"{result.delta.otd_before:.1f}% → {result.delta.otd_after:.1f}%",
            "tardy": f"{result.delta.tardy_before} → {result.delta.tardy_after}",
        },
        "resumo": result.summary,
    })


# ─── 8. check_ctp ────────────────────────────────────────────────────────

def exec_check_ctp(args: dict) -> str:
    if (err := _guard()):
        return err

    from backend.analytics.ctp import compute_ctp

    sku = args.get("sku", "")
    qty = args.get("quantidade", 0)
    deadline = args.get("dia_deadline", 0)

    result = compute_ctp(
        sku, qty, deadline,
        state.segments, state.engine_data, config=state.config,
    )

    return _dumps({
        "sku": result.sku,
        "qty_pedida": result.qty_requested,
        "feasible": result.feasible,
        "dia_mais_tarde": result.latest_day,
        "maquina": result.machine,
        "confianca": result.confidence,
        "slack_min": result.slack_min,
        "razao": result.reason,
    })
