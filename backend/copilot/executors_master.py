"""Master data executors — Spec 10.

10 executors for factory master data changes.
Pattern: validate → update config → SYNC EngineData → save YAML → re-schedule → return impact.
"""

from __future__ import annotations

import json
import logging

from backend.config.loader import _parse_time, save_config
from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.copilot.state import state
from backend.types import MachineInfo, TwinGroup

logger = logging.getLogger(__name__)


def _dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _guard() -> str | None:
    if state.engine_data is None:
        return _dumps({"error": "Sem dados carregados. Carrega um ISOP primeiro."})
    if state.config is None:
        return _dumps({"error": "Configuração não carregada."})
    return None


def _reschedule() -> dict:
    """Re-schedule and return new score."""
    from backend.cpo import optimize

    result = optimize(state.engine_data, mode="quick", audit=True, config=state.config)
    state.update_schedule(result)
    return result.score


def _sync_day_capacity() -> None:
    """Sync EngineData machine capacities from config shifts."""
    new_cap = state.config.day_capacity_min
    for m in state.engine_data.machines:
        m.day_capacity = new_cap


# ─── 1. adicionar_maquina ────────────────────────────────────────────────

def exec_adicionar_maquina(args: dict) -> str:
    if (err := _guard()):
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
    if (err := _guard()):
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
    if (err := _guard()):
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

    return _dumps({"status": "ok", "ferramenta": tid, "score": new_score, "score_anterior": old_score})


# ─── 4. editar_ferramenta ────────────────────────────────────────────────

def exec_editar_ferramenta(args: dict) -> str:
    if (err := _guard()):
        return err

    tid = args["id"]
    if tid not in state.config.tools:
        return _dumps({"error": f"Ferramenta {tid} não existe."})

    tool_data = state.config.tools[tid]

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

    return _dumps({"status": "ok", "ferramenta": tid, "score": new_score, "score_anterior": old_score})


# ─── 5. adicionar_twin ───────────────────────────────────────────────────

def exec_adicionar_twin(args: dict) -> str:
    if (err := _guard()):
        return err

    tid = args["tool_id"]
    sku_a = args["sku_a"]
    sku_b = args["sku_b"]

    if tid in state.config.twins:
        return _dumps({"error": f"Twin para ferramenta {tid} já existe."})

    # Find ops for these SKUs
    op_a = next((o for o in state.engine_data.ops if o.sku == sku_a), None)
    op_b = next((o for o in state.engine_data.ops if o.sku == sku_b), None)

    # 1. Update config
    state.config.twins[tid] = [sku_a, sku_b]

    # 2. Sync EngineData — add TwinGroup if both ops exist
    if op_a and op_b:
        state.engine_data.twin_groups.append(
            TwinGroup(tool_id=tid, machine_id=op_a.m, op_id_1=op_a.id, op_id_2=op_b.id),
        )

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps({"status": "ok", "twin": tid, "skus": [sku_a, sku_b], "score": new_score, "score_anterior": old_score})


# ─── 6. remover_twin ─────────────────────────────────────────────────────

def exec_remover_twin(args: dict) -> str:
    if (err := _guard()):
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

    return _dumps({"status": "ok", "twin_removido": tid, "score": new_score, "score_anterior": old_score})


# ─── 7. adicionar_feriado ────────────────────────────────────────────────

def exec_adicionar_feriado(args: dict) -> str:
    if (err := _guard()):
        return err

    data = args["data"]
    if data in state.config.holidays:
        return _dumps({"error": f"Feriado {data} já existe."})

    # 1. Update config
    state.config.holidays.append(data)

    # 2. Sync EngineData — convert date to workday index
    workdays = state.engine_data.workdays
    if data in workdays:
        idx = workdays.index(data)
        if idx not in state.engine_data.holidays:
            state.engine_data.holidays.append(idx)
            state.engine_data.holidays.sort()

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps({"status": "ok", "feriado": data, "score": new_score, "score_anterior": old_score})


# ─── 8. remover_feriado ──────────────────────────────────────────────────

def exec_remover_feriado(args: dict) -> str:
    if (err := _guard()):
        return err

    data = args["data"]
    if data not in state.config.holidays:
        return _dumps({"error": f"Feriado {data} não existe."})

    # 1. Update config
    state.config.holidays.remove(data)

    # 2. Sync EngineData
    workdays = state.engine_data.workdays
    if data in workdays:
        idx = workdays.index(data)
        if idx in state.engine_data.holidays:
            state.engine_data.holidays.remove(idx)

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps({"status": "ok", "feriado_removido": data, "score": new_score, "score_anterior": old_score})


# ─── 9. editar_turno ─────────────────────────────────────────────────────

def exec_editar_turno(args: dict) -> str:
    if (err := _guard()):
        return err

    tid = args["turno_id"]
    shift = next((s for s in state.config.shifts if s.id == tid), None)
    if not shift:
        return _dumps({"error": f"Turno {tid} não existe."})

    # 1. Update config
    if "inicio" in args:
        shift.start_min = _parse_time(args["inicio"])
    if "fim" in args:
        shift.end_min = _parse_time(args["fim"])

    # 2. Sync EngineData — day_capacity changes
    _sync_day_capacity()

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps({
        "status": "ok", "turno": tid,
        "day_capacity_min": state.config.day_capacity_min,
        "score": new_score, "score_anterior": old_score,
    })


# ─── 10. adicionar_turno ─────────────────────────────────────────────────

def exec_adicionar_turno(args: dict) -> str:
    if (err := _guard()):
        return err

    tid = args["id"]
    if any(s.id == tid for s in state.config.shifts):
        return _dumps({"error": f"Turno {tid} já existe."})

    inicio = _parse_time(args["inicio"])
    fim = _parse_time(args["fim"])
    label = args.get("label", "")

    # 1. Update config
    state.config.shifts.append(ShiftConfig(id=tid, start_min=inicio, end_min=fim, label=label))

    # 2. Sync EngineData
    _sync_day_capacity()

    # 3. Save + re-schedule
    old_score = dict(state.score)
    save_config(state.config)
    new_score = _reschedule()

    return _dumps({
        "status": "ok", "turno": tid,
        "day_capacity_min": state.config.day_capacity_min,
        "score": new_score, "score_anterior": old_score,
    })
