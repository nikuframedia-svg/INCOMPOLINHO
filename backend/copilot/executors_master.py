"""Master data executors — Spec 10.

10 executors for factory master data changes.
Pattern: validate → update config → SYNC EngineData → save YAML → re-schedule → return impact.
"""

from __future__ import annotations

import copy
import json
import logging
from contextvars import ContextVar
from functools import wraps

from backend.config.loader import _parse_time
from backend.config.loader import save_config as _persist_config
from backend.config.types import MachineConfig, ShiftConfig
from backend.copilot.state import state
from backend.planning_control import PlanningStopped
from backend.types import MachineInfo, TwinGroup
from backend.validation import strict_bool, strict_int

logger = logging.getLogger(__name__)
_PENDING_CONFIG = ContextVar("master_config", default=None)
_PENDING_APPROVAL_BODY = ContextVar("master_approval", default=None)


def _dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def save_config(config) -> None:
    """Defer YAML persistence until the reschedule has succeeded."""
    _PENDING_CONFIG.set(copy.deepcopy(config))


def _snapshot_state() -> dict:
    return {
        "engine_data": copy.deepcopy(state.engine_data),
        "config": copy.deepcopy(state.config),
        "default_config": copy.deepcopy(state.default_config),
        "segments": copy.deepcopy(state.segments),
        "lots": copy.deepcopy(state.lots),
        "score": copy.deepcopy(state.score),
        "warnings": copy.deepcopy(state.warnings),
        "journal_entries": copy.deepcopy(state.journal_entries),
        "trust_index": copy.deepcopy(state.trust_index),
        "stock_projections": copy.deepcopy(state.stock_projections),
        "expedition": copy.deepcopy(state.expedition),
        "risk_result": copy.deepcopy(state.risk_result),
        "late_deliveries": copy.deepcopy(state.late_deliveries),
        "coverage": copy.deepcopy(state.coverage),
        "order_tracking": copy.deepcopy(state.order_tracking),
        "stress_map": copy.deepcopy(state.stress_map),
        "operator_alerts": copy.deepcopy(state.operator_alerts),
        "gate_report": copy.deepcopy(state.gate_report),
        "improvement_report": copy.deepcopy(state.improvement_report),
        "solver_status": state.solver_status,
        "feasibility": copy.deepcopy(state.feasibility),
        "plan_revision": state.plan_revision,
        "approvals": copy.deepcopy(state.approvals),
        "schedule_id": state.schedule_id,
        "saved_schedule": copy.deepcopy(state.saved_schedule),
        "saved_mutations": copy.deepcopy(state.saved_mutations),
        "saved_manual_edits": copy.deepcopy(state.saved_manual_edits),
        "saved_plan_revision": state.saved_plan_revision,
        "active_mutations": copy.deepcopy(state.active_mutations),
        "manual_edits": copy.deepcopy(state.manual_edits),
    }


def _restore_state(snapshot: dict) -> None:
    for key, value in snapshot.items():
        setattr(state, key, value)


def _transactional_master(fn):
    @wraps(fn)
    def wrapper(args: dict) -> str:
        from backend.plans.context import is_staging
        from backend.plans.transactions import run_sync_mutation

        if not is_staging():
            try:
                return run_sync_mutation(state, lambda: wrapper(args))
            except PlanningStopped:
                raise
            except Exception as exc:
                logger.exception("Master executor %s failed to commit", fn.__name__)
                return _dumps({"error": str(exc)})
        snapshot = _snapshot_state()
        config_token = _PENDING_CONFIG.set(None)
        approval_token = _PENDING_APPROVAL_BODY.set(dict(args))
        try:
            if "expected_revision" not in args:
                return _dumps({"error": "expected_revision é obrigatório."})
            if strict_int(args["expected_revision"], "expected_revision") != int(
                state.plan_revision
            ):
                return _dumps(
                    {
                        "error": "Revisão obsoleta: o plano mudou entretanto.",
                        "current_revision": state.plan_revision,
                    }
                )
            return fn(args)
        except Exception as exc:
            _restore_state(snapshot)
            from fastapi import HTTPException

            from backend.plans.context import api_write_context

            if isinstance(exc, PlanningStopped) or (
                isinstance(exc, HTTPException) and api_write_context() is not None
            ):
                raise
            logger.exception("Master executor %s rolled back", fn.__name__)
            return _dumps({"error": str(exc)})
        finally:
            _PENDING_CONFIG.reset(config_token)
            _PENDING_APPROVAL_BODY.reset(approval_token)

    return wrapper


def _guard() -> str | None:
    if state.engine_data is None:
        return _dumps({"error": "Sem dados carregados. Carrega um ISOP primeiro."})
    if state.config is None:
        return _dumps({"error": "Configuração não carregada."})
    return None


def _reschedule() -> dict:
    """Re-schedule and return new score."""
    from backend.api.data import (
        _authorize_recomputed_candidate,
        _require_recompute_preview,
        _schedule_result_from_state,
    )
    from backend.config.loader import validate_config
    from backend.config.planning import synchronize_active_twin_groups
    from backend.plans.context import api_write_context
    from backend.plans.frozen import optimize_preserving_started_lots
    from backend.transform.calendars import apply_calendars

    approval_body = _PENDING_APPROVAL_BODY.get() or {}
    _require_recompute_preview(approval_body)

    config_errors = validate_config(state.config, state.engine_data)
    if config_errors:
        raise ValueError("Configuração inválida: " + "; ".join(config_errors))
    synchronize_active_twin_groups(state.engine_data, state.config.twins)
    apply_calendars(state.engine_data, state.config)
    if state.active_mutations:
        from backend.simulator.mutations import reapply_calendar_mutations

        reapply_calendar_mutations(state.engine_data, state.active_mutations, state.config)
    result = optimize_preserving_started_lots(
        state.engine_data,
        state.config,
        _schedule_result_from_state(),
        audit=True,
    )
    from backend.scheduler.gates import authorize_application

    if api_write_context():
        approval = _authorize_recomputed_candidate(result, approval_body, action="master_data")
    else:
        approval = authorize_application(
            result.gate_report,
            approve_exceptions=strict_bool(
                approval_body.get(
                    "approve_exceptions",
                    approval_body.get("confirm_delivery_risk", False),
                )
            ),
            approval_reason=str(
                approval_body.get(
                    "approval_reason",
                    approval_body.get("reason", ""),
                )
            ),
            approval_author=str(
                approval_body.get(
                    "approval_author",
                    approval_body.get("author", ""),
                )
            ),
        )
    if approval is not None:
        state.approvals.append({**approval, "action": "master_data"})
    state.manual_edits = []
    state.update_schedule(result, plan_source="auto", plan_note="Dados mestre alterados")
    if _PENDING_CONFIG.get() is not None:
        _persist_config(_PENDING_CONFIG.get())
        _PENDING_CONFIG.set(None)
    return result.score


def _sync_day_capacity() -> None:
    """Sync EngineData machine capacities from config shifts."""
    new_cap = state.config.day_capacity_min
    for m in state.engine_data.machines:
        m.day_capacity = new_cap


# ─── 1. adicionar_maquina ────────────────────────────────────────────────


def exec_adicionar_maquina(args: dict) -> str:
    if err := _guard():
        return err

    mid = args["id"]
    grupo = args.get("grupo", "Grandes")
    activa = args.get("activa", True)

    if mid in state.config.machines:
        return _dumps({"error": f"Máquina {mid} já existe."})

    # 1. Update config
    state.config.machines[mid] = MachineConfig(id=mid, group=grupo, active=activa)

    # 2. Sync EngineData
    if activa:
        state.engine_data.machines.append(
            MachineInfo(id=mid, group=grupo, day_capacity=state.config.day_capacity_min),
        )

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps({"status": "ok", "maquina": mid, "score": new_score, "score_anterior": old_score})


# ─── 2. editar_maquina ───────────────────────────────────────────────────


def exec_editar_maquina(args: dict) -> str:
    if err := _guard():
        return err

    mid = args["id"]
    if mid not in state.config.machines:
        return _dumps({"error": f"Máquina {mid} não existe."})

    mc = state.config.machines[mid]

    # 1. Update config
    if "activa" in args:
        mc.active = args["activa"]
    if "grupo" in args:
        mc.group = args["grupo"]
    if "oee" in args:
        mc.oee = args["oee"]

    # 2. Sync EngineData
    if "activa" in args and not args["activa"]:
        state.engine_data.machines = [m for m in state.engine_data.machines if m.id != mid]
    elif "activa" in args and args["activa"]:
        # Re-add if not present
        if not any(m.id == mid for m in state.engine_data.machines):
            state.engine_data.machines.append(
                MachineInfo(id=mid, group=mc.group, day_capacity=state.config.day_capacity_min),
            )
    if "grupo" in args:
        for m in state.engine_data.machines:
            if m.id == mid:
                m.group = args["grupo"]

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps({"status": "ok", "maquina": mid, "score": new_score, "score_anterior": old_score})


# ─── 3. adicionar_ferramenta ─────────────────────────────────────────────


def exec_adicionar_ferramenta(args: dict) -> str:
    if err := _guard():
        return err

    tid = args["id"]
    primary = args["primary"]
    alt = args.get("alt")
    setup_h = args.get("setup_hours", 0.5)

    if tid in state.config.tools:
        return _dumps({"error": f"Ferramenta {tid} já existe."})
    if primary not in state.config.machines:
        return _dumps({"error": f"Máquina primária {primary} não existe."})
    if alt and alt not in state.config.machines:
        return _dumps({"error": f"Máquina alternativa {alt} não existe."})

    # 1. Update config
    tool_data = {"primary": primary, "setup_hours": setup_h}
    if alt:
        tool_data["alt"] = alt
    state.config.tools[tid] = tool_data

    # 2. No EngineData sync needed (no ops use this new tool yet)

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps(
        {"status": "ok", "ferramenta": tid, "score": new_score, "score_anterior": old_score}
    )


# ─── 4. editar_ferramenta ────────────────────────────────────────────────


def exec_editar_ferramenta(args: dict) -> str:
    if err := _guard():
        return err

    tid = args["id"]
    if tid not in state.config.tools:
        return _dumps({"error": f"Ferramenta {tid} não existe."})

    tool_data = state.config.tools[tid]

    setup_unchanged = "setup_hours" not in args or float(args["setup_hours"]) == float(
        tool_data.get("setup_hours", state.config.default_setup_hours)
    )
    alt_unchanged = "alt" not in args or args["alt"] == tool_data.get("alt")
    if setup_unchanged and alt_unchanged:
        return _dumps(
            {
                "status": "unchanged",
                "ferramenta": tid,
                "score": state.score,
                "score_anterior": state.score,
                "plan_revision": state.plan_revision,
            }
        )

    # 1. Update config
    if "setup_hours" in args:
        tool_data["setup_hours"] = args["setup_hours"]
    if "alt" in args:
        new_alt = args["alt"]
        if new_alt and new_alt not in state.config.machines:
            return _dumps({"error": f"Máquina {new_alt} não existe."})
        tool_data["alt"] = new_alt

    # 2. SYNC EngineData — CRITICAL
    for op in state.engine_data.ops:
        if op.t == tid:
            if "setup_hours" in args:
                op.sH = args["setup_hours"]
            if "alt" in args:
                op.alt = args["alt"]

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps(
        {"status": "ok", "ferramenta": tid, "score": new_score, "score_anterior": old_score}
    )


# ─── 5. adicionar_twin ───────────────────────────────────────────────────


def exec_adicionar_twin(args: dict) -> str:
    if err := _guard():
        return err

    tid = args["tool_id"]
    sku_a = args["sku_a"]
    sku_b = args["sku_b"]

    if tid in state.config.twins:
        return _dumps({"error": f"Twin para ferramenta {tid} já existe."})
    if sku_a == sku_b:
        return _dumps({"error": "Uma gémea exige duas referências distintas."})
    known_tools = set(state.config.tools) | {op.t for op in state.engine_data.ops}
    if tid not in known_tools:
        return _dumps({"error": f"Ferramenta {tid} não existe."})

    matches_a = [op for op in state.engine_data.ops if op.sku == sku_a]
    matches_b = [op for op in state.engine_data.ops if op.sku == sku_b]
    if len(matches_a) != 1 or len(matches_b) != 1:
        return _dumps(
            {
                "error": (
                    "Cada SKU gémea deve corresponder a uma operação única; "
                    f"{sku_a}={len(matches_a)}, {sku_b}={len(matches_b)}."
                )
            }
        )
    op_a, op_b = matches_a[0], matches_b[0]
    if op_a.t != tid or op_b.t != tid:
        return _dumps(
            {
                "error": (
                    f"As duas referências têm de usar a ferramenta {tid}; "
                    f"{sku_a} usa {op_a.t} e {sku_b} usa {op_b.t}."
                )
            }
        )
    machines_a = {machine for machine in (op_a.m, op_a.alt) if machine}
    machines_b = {machine for machine in (op_b.m, op_b.alt) if machine}
    common_machines = machines_a & machines_b
    if not common_machines:
        return _dumps({"error": "As referências gémeas não têm uma máquina elegível comum."})
    configured_primary = str(state.config.tools.get(tid, {}).get("primary", ""))
    machine_id = (
        configured_primary if configured_primary in common_machines else sorted(common_machines)[0]
    )

    # 1. Update config
    state.config.twins[tid] = [sku_a, sku_b]

    # 2. Sync EngineData
    state.engine_data.twin_groups.append(
        TwinGroup(
            tool_id=tid,
            machine_id=machine_id,
            op_id_1=op_a.id,
            op_id_2=op_b.id,
            sku_1=op_a.sku,
            sku_2=op_b.sku,
            eco_lot_1=op_a.eco_lot,
            eco_lot_2=op_b.eco_lot,
        ),
    )

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps(
        {
            "status": "ok",
            "twin": tid,
            "skus": [sku_a, sku_b],
            "score": new_score,
            "score_anterior": old_score,
        }
    )


# ─── 6. remover_twin ─────────────────────────────────────────────────────


def exec_remover_twin(args: dict) -> str:
    if err := _guard():
        return err

    tid = args["tool_id"]
    if tid not in state.config.twins:
        return _dumps({"error": f"Twin para ferramenta {tid} não existe."})

    # 1. Update config
    del state.config.twins[tid]

    # 2. Sync EngineData
    state.engine_data.twin_groups = [
        tg for tg in state.engine_data.twin_groups if tg.tool_id != tid
    ]

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps(
        {"status": "ok", "twin_removido": tid, "score": new_score, "score_anterior": old_score}
    )


# ─── 7. adicionar_feriado ────────────────────────────────────────────────


def exec_adicionar_feriado(args: dict) -> str:
    if err := _guard():
        return err

    data = args["data"]
    if data in state.config.holidays:
        return _dumps({"error": f"Feriado {data} já existe."})

    # 1. Update config
    state.config.holidays.append(data)

    # 2. Save + re-schedule. _reschedule() rebuilds EngineData calendars from
    # their immutable baseline, avoiding stale indices after later removals.
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps(
        {"status": "ok", "feriado": data, "score": new_score, "score_anterior": old_score}
    )


# ─── 8. remover_feriado ──────────────────────────────────────────────────


def exec_remover_feriado(args: dict) -> str:
    if err := _guard():
        return err

    data = args["data"]
    if data not in state.config.holidays:
        return _dumps({"error": f"Feriado {data} não existe."})

    # 1. Update config
    state.config.holidays.remove(data)

    # 2. Save + re-schedule. _reschedule() rebuilds the effective holiday set.
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps(
        {"status": "ok", "feriado_removido": data, "score": new_score, "score_anterior": old_score}
    )


# ─── 9. editar_turno ─────────────────────────────────────────────────────


def exec_editar_turno(args: dict) -> str:
    if err := _guard():
        return err

    tid = args["turno_id"]
    shift = next((s for s in state.config.shifts if s.id == tid), None)
    if not shift:
        return _dumps({"error": f"Turno {tid} não existe."})

    # 1. Update config
    if "inicio" in args:
        shift.start_min = _parse_time(args["inicio"])
    if "fim" in args:
        shift.end_min = _parse_time(args["fim"], end_of_day=True)

    # 2. Sync EngineData — day_capacity changes
    _sync_day_capacity()

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps(
        {
            "status": "ok",
            "turno": tid,
            "day_capacity_min": state.config.day_capacity_min,
            "score": new_score,
            "score_anterior": old_score,
        }
    )


# ─── 10. adicionar_turno ─────────────────────────────────────────────────


def exec_adicionar_turno(args: dict) -> str:
    if err := _guard():
        return err

    tid = args["id"]
    if any(s.id == tid for s in state.config.shifts):
        return _dumps({"error": f"Turno {tid} já existe."})

    inicio = _parse_time(args["inicio"])
    fim = _parse_time(args["fim"], end_of_day=True)
    label = args.get("label", "")

    # 1. Update config
    state.config.shifts.append(ShiftConfig(id=tid, start_min=inicio, end_min=fim, label=label))

    # 2. Sync EngineData
    _sync_day_capacity()

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps(
        {
            "status": "ok",
            "turno": tid,
            "day_capacity_min": state.config.day_capacity_min,
            "score": new_score,
            "score_anterior": old_score,
        }
    )


exec_adicionar_maquina = _transactional_master(exec_adicionar_maquina)
exec_editar_maquina = _transactional_master(exec_editar_maquina)
exec_adicionar_ferramenta = _transactional_master(exec_adicionar_ferramenta)
exec_editar_ferramenta = _transactional_master(exec_editar_ferramenta)
exec_adicionar_twin = _transactional_master(exec_adicionar_twin)
exec_remover_twin = _transactional_master(exec_remover_twin)
exec_adicionar_feriado = _transactional_master(exec_adicionar_feriado)
exec_remover_feriado = _transactional_master(exec_remover_feriado)
exec_editar_turno = _transactional_master(exec_editar_turno)
exec_adicionar_turno = _transactional_master(exec_adicionar_turno)
