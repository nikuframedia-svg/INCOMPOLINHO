"""Action executors — Spec 10.

8 executors that may modify state (schedule, config, rules).
"""

from __future__ import annotations

import copy
import json
import logging
from functools import wraps

from backend.copilot.state import state
from backend.validation import strict_bool, strict_int

logger = logging.getLogger(__name__)


def _production_action(fn):
    @wraps(fn)
    def wrapped(args):
        from backend.plans.transactions import run_sync_mutation

        mode = args.get("modo", "quick") if fn.__name__ == "exec_recalcular_plano" else "normal"
        return run_sync_mutation(state, lambda: fn(args), planning_mode=mode)

    return wrapped


def _dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _guard() -> str | None:
    if state.engine_data is None:
        return _dumps({"error": "Sem dados carregados. Carrega um ISOP primeiro."})
    return None


def _require_revision(args: dict) -> str | None:
    if "expected_revision" not in args:
        return _dumps({"error": "expected_revision é obrigatório."})
    try:
        expected = strict_int(args["expected_revision"], "expected_revision")
    except (TypeError, ValueError):
        return _dumps({"error": "expected_revision deve ser um inteiro."})
    if expected != int(state.plan_revision):
        return _dumps(
            {
                "error": "Revisão obsoleta: o plano mudou entretanto.",
                "current_revision": state.plan_revision,
            }
        )
    return None


def _authorize(result, args: dict, action: str) -> dict | None:
    from backend.scheduler.gates import authorize_application

    approval = authorize_application(
        result.gate_report,
        approve_exceptions=strict_bool(
            args.get(
                "approve_exceptions",
                args.get("confirm_delivery_risk", False),
            )
        ),
        approval_reason=str(args.get("approval_reason", args.get("reason", ""))),
        approval_author=str(args.get("approval_author", args.get("author", ""))),
    )
    return {**approval, "action": action} if approval is not None else None


# ─── 1. recalcular_plano ─────────────────────────────────────────────────


@_production_action
def exec_recalcular_plano(args: dict) -> str:
    if err := _guard():
        return err
    if err := _require_revision(args):
        return err

    from backend.api.data import _schedule_result_from_state
    from backend.plans.frozen import optimize_preserving_started_lots
    from backend.simulator.mutations import reapply_calendar_mutations
    from backend.transform.calendars import apply_calendars

    modo = args.get("modo", "quick")
    old_segments = list(state.segments)
    old_score = dict(state.score) if state.score else {}

    apply_calendars(state.engine_data, state.config)
    reapply_calendar_mutations(state.engine_data, state.active_mutations, state.config)
    optimizer = None
    if modo == "smart":
        try:
            from backend.learning import smart_schedule

            def optimizer(data, **options):
                return smart_schedule(data, learn=True, config=options["config"], audit=True)
        except ImportError:
            pass
    result = optimize_preserving_started_lots(
        state.engine_data,
        state.config,
        _schedule_result_from_state(),
        mode="normal" if modo == "smart" else modo,
        audit=True,
        optimizer=optimizer,
    )

    try:
        approval = _authorize(result, args, "recalculate")
    except ValueError as exc:
        return _dumps(
            {
                "error": str(exc),
                "gate_report": result.gate_report,
                "current_revision": state.plan_revision,
            }
        )
    if approval is not None:
        state.approvals.append(approval)
    state.manual_edits = []
    state.update_schedule(result, plan_source="auto", plan_note=f"Recalcular ({modo})")

    # Compute lot-level diff
    alteracoes = None
    if old_segments:
        try:
            from backend.audit.diff import compute_diff

            diff = compute_diff(old_segments, result.segments, old_score, result.score)
            alteracoes = {
                "lots_movidos": len(diff.moved),
                "lots_retimed": len(diff.retimed),
                "lots_added": len(diff.added),
                "lots_removed": len(diff.removed),
            }
        except Exception:
            pass

    return _dumps(
        {
            "status": "ok",
            "modo": modo,
            "score": result.score,
            "score_anterior": old_score,
            "alteracoes": alteracoes,
            "time_ms": result.time_ms,
            "warnings": result.warnings[:10],
            "plan_revision": state.plan_revision,
        }
    )


# ─── 2. mover_referencia ─────────────────────────────────────────────────


@_production_action
def exec_mover_referencia(args: dict) -> str:
    if err := _guard():
        return err
    if err := _require_revision(args):
        return err

    from backend.api.data import _schedule_result_from_state
    from backend.plans.frozen import optimize_preserving_started_lots
    from backend.simulator.mutations import apply_mutation, reapply_calendar_mutations
    from backend.transform.calendars import apply_calendars

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
    candidate_config = copy.deepcopy(state.config)
    from backend.plans.frozen import _current_planning_day, _frozen_started_lots

    baseline = _schedule_result_from_state()
    _, frozen_lots = _frozen_started_lots(
        baseline,
        _current_planning_day(mutated, candidate_config),
    )
    tools = {op.t for op in ops_found}
    if any(lot.tool_id in tools for lot in frozen_lots):
        return _dumps({"error": "Nao e permitido mover lotes ja iniciados."})
    for tool_id in tools:
        apply_mutation(
            mutated, "force_machine", {"tool_id": tool_id, "to_machine": dest}, candidate_config
        )
    apply_calendars(mutated, candidate_config)
    reapply_calendar_mutations(mutated, state.active_mutations, candidate_config)

    # Re-schedule on mutated data
    result = optimize_preserving_started_lots(
        mutated,
        candidate_config,
        _schedule_result_from_state(),
        audit=True,
    )

    try:
        approval = _authorize(result, args, "move_reference")
    except ValueError as exc:
        return _dumps(
            {
                "error": str(exc),
                "score_proposto": result.score,
                "gate_report": result.gate_report,
                "current_revision": state.plan_revision,
            }
        )

    # Accept: update state with mutated data
    if approval is not None:
        state.approvals.append(approval)
    state.engine_data = mutated
    state.config = candidate_config
    state.manual_edits = []
    state.update_schedule(result, plan_source="auto", plan_note=f"Mover {sku} para {dest}")

    return _dumps(
        {
            "status": "aceite",
            "sku": sku,
            "maquina_anterior": ops_found[0].m,
            "maquina_nova": dest,
            "score": result.score,
            "plan_revision": state.plan_revision,
        }
    )


# ─── 3. adicionar_regra ──────────────────────────────────────────────────


def exec_adicionar_regra(args: dict) -> str:
    from backend.plans.context import is_staging
    from backend.plans.transactions import run_sync_mutation

    if not is_staging():
        return run_sync_mutation(state, lambda: exec_adicionar_regra(args))
    if err := _require_revision(args):
        return err
    rule = {
        "descricao": args.get("descricao", ""),
        "tipo": args.get("tipo", "preferencia"),
    }
    rule_id = state.add_rule(rule)
    state.plan_revision += 1
    return _dumps(
        {
            "status": "ok",
            "regra_id": rule_id,
            "regra": rule,
            "plan_revision": state.plan_revision,
        }
    )


# ─── 4. remover_regra ────────────────────────────────────────────────────


def exec_remover_regra(args: dict) -> str:
    from backend.plans.context import is_staging
    from backend.plans.transactions import run_sync_mutation

    if not is_staging():
        return run_sync_mutation(state, lambda: exec_remover_regra(args))
    if err := _require_revision(args):
        return err
    rule_id = args.get("regra_id", "")
    removed = state.remove_rule(rule_id)
    if removed:
        state.plan_revision += 1
        return _dumps(
            {
                "status": "ok",
                "regra_id": rule_id,
                "plan_revision": state.plan_revision,
            }
        )
    return _dumps({"error": f"Regra {rule_id} não encontrada."})


# ─── 5. alterar_config ───────────────────────────────────────────────────

_ALLOWED_KEYS = {
    "oee_default": float,
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


def _coerce_config_value(key: str, expected_type: type, value):
    if expected_type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "sim"}:
                return True
            if normalized in {"false", "0", "no", "não", "nao"}:
                return False
        raise ValueError(f"Valor '{value}' inválido para {key} (esperado booleano).")
    try:
        return expected_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Valor '{value}' inválido para {key} (esperado {expected_type.__name__})."
        ) from exc


@_production_action
def exec_alterar_config(args: dict) -> str:
    if state.config is None:
        return _dumps({"error": "Configuração não carregada."})
    if err := _guard():
        return err
    if err := _require_revision(args):
        return err

    chave = args.get("chave", "")
    valor = args.get("valor")

    if chave not in _ALLOWED_KEYS:
        return _dumps(
            {
                "error": f"Chave '{chave}' não permitida.",
                "chaves_validas": list(_ALLOWED_KEYS.keys()),
            }
        )

    expected_type = _ALLOWED_KEYS[chave]
    try:
        typed_value = _coerce_config_value(chave, expected_type, valor)
    except ValueError as exc:
        return _dumps({"error": str(exc)})

    candidate_config = copy.deepcopy(state.config)
    candidate_data = copy.deepcopy(state.engine_data)
    old_value = getattr(candidate_config, chave)
    setattr(candidate_config, chave, typed_value)

    from backend.api.data import _schedule_result_from_state
    from backend.config.loader import save_config, validate_config
    from backend.plans.frozen import optimize_preserving_started_lots
    from backend.simulator.mutations import reapply_calendar_mutations
    from backend.transform.calendars import apply_calendars

    config_errors = validate_config(candidate_config, candidate_data)
    if config_errors:
        return _dumps(
            {
                "error": "Configuração inválida.",
                "details": config_errors,
            }
        )

    apply_calendars(candidate_data, candidate_config)
    reapply_calendar_mutations(candidate_data, state.active_mutations, candidate_config)
    result = optimize_preserving_started_lots(
        candidate_data,
        candidate_config,
        _schedule_result_from_state(),
        audit=True,
    )
    try:
        approval = _authorize(result, args, "config_change")
    except ValueError as exc:
        return _dumps(
            {
                "error": str(exc),
                "gate_report": result.gate_report,
                "current_revision": state.plan_revision,
            }
        )

    # Persist and commit only after the candidate has passed the physical
    # gates and, where required, received an explicit approval.
    save_config(candidate_config)
    if approval is not None:
        state.approvals.append(approval)
    state.config = candidate_config
    state.engine_data = candidate_data
    state.manual_edits = []
    state.update_schedule(
        result,
        plan_source="auto",
        plan_note=f"Configuração: {chave}",
    )

    return _dumps(
        {
            "status": "ok",
            "chave": chave,
            "valor_anterior": old_value,
            "valor_novo": typed_value,
            "score": result.score,
            "gate_report": result.gate_report,
            "plan_revision": state.plan_revision,
        }
    )


# ─── 6. simular_cenario ──────────────────────────────────────────────────


def exec_simular_cenario(args: dict) -> str:
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
        }
    )


# ─── 7. simular_overtime ─────────────────────────────────────────────────


def exec_simular_overtime(args: dict) -> str:
    if err := _guard():
        return err

    from backend.simulator.simulator import Mutation, simulate

    maquina = args.get("maquina", "")
    minutos = args.get("minutos_extra", 0)

    mutations = [
        Mutation(
            type="overtime",
            params={
                "machine_id": maquina,
                "extra_min": minutos,
            },
        )
    ]

    result = simulate(
        state.engine_data,
        state.score,
        mutations,
        config=state.config,
    )

    return _dumps(
        {
            "maquina": maquina,
            "minutos_extra": minutos,
            "score_actual": state.score,
            "score_cenario": result.score,
            "delta": {
                "otd": f"{result.delta.otd_before:.1f}% → {result.delta.otd_after:.1f}%",
                "tardy": f"{result.delta.tardy_before} → {result.delta.tardy_after}",
            },
            "resumo": result.summary,
        }
    )


# ─── 8. check_ctp ────────────────────────────────────────────────────────


def exec_check_ctp(args: dict) -> str:
    if err := _guard():
        return err

    from backend.analytics.ctp import verify_ctp
    from backend.api.data import _schedule_result_from_state

    sku = args.get("sku", "")
    qty = args.get("quantidade", 0)
    deadline = args.get("dia_deadline", 0)

    result, _candidate = verify_ctp(
        sku,
        qty,
        deadline,
        _schedule_result_from_state(),
        state.engine_data,
        config=state.config,
        active_mutations=state.active_mutations,
    )

    return _dumps(
        {
            "sku": result.sku,
            "qty_pedida": result.qty_requested,
            "feasible": result.feasible,
            "dia_mais_tarde": result.latest_day,
            "maquina": result.machine,
            "confianca": result.confidence,
            "slack_min": result.slack_min,
            "razao": result.reason,
            "entrega_cliente_dia": result.customer_delivery_day,
            "ultimo_envio_subcontratado_dia": (result.latest_subcontract_dispatch_day),
            "prazo_producao_dia": result.production_due_day,
            "envio_subcontratado_dia": result.subcontract_dispatch_day,
            "alvo_interno_dia": result.internal_target_day,
            "referencia_material_dia": result.material_reference_day,
            "tipo_referencia_material": result.material_reference_kind,
            "libertacao_material_dia": result.material_release_day,
        }
    )


# ─── 9. simular_avaria ─────────────────────────────────────────────────


def exec_simular_avaria(args: dict) -> str:
    if err := _guard():
        return err

    from backend.simulator.breakdown import simulate_breakdown

    machine_id = args.get("maquina", "")
    start_day = args.get("dia_inicio", 0)
    duration = args.get("duracao_dias", 1)

    report = simulate_breakdown(
        state.engine_data,
        state.score,
        machine_id=machine_id,
        start_day=start_day,
        end_day=start_day + duration - 1,
        config=state.config,
    )

    return _dumps(
        {
            "impacto": report.impact_level,
            "resumo": report.summary_pt,
            "operacoes_afectadas": report.affected_ops[:10],
            "delta": {
                "otd": f"{report.delta.otd_before:.1f}% → {report.delta.otd_after:.1f}%",
                "tardy": f"{report.delta.tardy_before} → {report.delta.tardy_after}",
                "setups": f"{report.delta.setups_before} → {report.delta.setups_after}",
            },
            "time_ms": report.time_ms,
        }
    )


# ─── 10. monte_carlo ───────────────────────────────────────────────────


def exec_monte_carlo(args: dict) -> str:
    if err := _guard():
        return err

    try:
        from backend.cpo import optimize
        from backend.risk.monte_carlo import monte_carlo_risk

        def schedule_fn(data):
            return optimize(data, mode="quick", config=state.config)

        n = min(args.get("amostras", 200), 500)
        mc = monte_carlo_risk(state.engine_data, schedule_fn, n_samples=n)
        return _dumps(mc)
    except ImportError:
        return _dumps({"erro": "scipy/numpy não instalados. Monte Carlo indisponível."})
