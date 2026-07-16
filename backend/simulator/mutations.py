"""Mutation application — Spec 04 §2.

Each mutation modifies EngineData in-place (on a deepcopy).
Returns a Portuguese summary string.

v2 fixes:
- machine_down: per-machine blocked days (not global holidays)
- tool_down: per-tool blocked days (not demand zeroing)
- third_shift/overtime: modify config.shifts (not MachineInfo)
- operator_shortage: advisory only (no scheduler effect)
"""

from __future__ import annotations

import logging

from backend.config.types import FactoryConfig, ShiftConfig
from backend.types import EngineData

logger = logging.getLogger(__name__)

# Mutation type → handler
_HANDLERS: dict[str, callable] = {}


def valid_mutation_types() -> set[str]:
    """Return mutation names accepted by the simulator API."""
    return set(_HANDLERS)


def _register(name: str):
    def decorator(fn):
        _HANDLERS[name] = fn
        return fn

    return decorator


def apply_mutation(
    data: EngineData,
    mutation_type: str,
    params: dict,
    config: FactoryConfig | None = None,
) -> str:
    """Apply a single mutation to EngineData (in-place). Returns summary string.

    Some mutations (third_shift, overtime) need to modify config.shifts,
    so config is passed as optional parameter.
    """
    handler = _HANDLERS.get(mutation_type)
    if handler is None:
        raise ValueError(f"Unknown mutation type: {mutation_type}")
    # Pass config to handlers that accept it
    import inspect

    sig = inspect.signature(handler)
    if "config" in sig.parameters:
        return handler(data, params, config=config)
    return handler(data, params)


def mutation_summary(mutation_type: str, params: dict) -> str:
    """Generate a Portuguese description of a mutation without applying it."""
    summaries = {
        "machine_down": lambda p: (
            f"Máquina {p.get('machine_id', '?')} parada dias "
            f"{p.get('start', '?')}-{p.get('end', '?')}"
        ),
        "tool_down": lambda p: (
            f"Ferramenta {p.get('tool_id', '?')} indisponível dias "
            f"{p.get('start', '?')}-{p.get('end', '?')}"
        ),
        "operator_shortage": lambda p: f"Falta de operadores (advisory): {p.get('note', '?')}",
        "oee_change": lambda p: (
            f"OEE alterado para {p.get('new_oee', '?')} em ferramenta {p.get('tool_id', '?')}"
        ),
        "rush_order": lambda p: (
            f"Encomenda urgente: {p.get('qty', '?')} pç SKU {p.get('sku', '?')} "
            f"dia {p.get('deadline_day', '?')}"
        ),
        "demand_change": lambda p: (
            f"Procura alterada: factor {p.get('factor', '?')}x SKU {p.get('sku', '?')}"
        ),
        "cancel_order": lambda p: (
            f"Cancelar encomendas SKU {p.get('sku', '?')} dias "
            f"{p.get('from_day', '?')}-{p.get('to_day', '?')}"
        ),
        "third_shift": lambda p: "3º turno activado (+420 min, todas as máquinas)",
        "overtime": lambda p: f"Horas extra (+{p.get('extra_min', '?')} min, todas as máquinas)",
        "add_holiday": lambda p: f"Feriado adicionado dia {p.get('day_idx', '?')}",
        "remove_holiday": lambda p: f"Feriado removido dia {p.get('day_idx', '?')}",
        "force_machine": lambda p: (
            f"Forçar ferramenta {p.get('tool_id', '?')} para máquina {p.get('to_machine', '?')}"
        ),
        "change_eco_lot": lambda p: (
            f"Eco lot alterado para {p.get('new_eco_lot', '?')} em SKU {p.get('sku', '?')}"
        ),
        "advance_edd": lambda p: (
            f"EDD antecipada {p.get('days', '?')} dias para SKU {p.get('sku', '?')}"
        ),
        "delay_edd": lambda p: (
            f"EDD atrasada {p.get('days', '?')} dias para SKU {p.get('sku', '?')}"
        ),
    }
    fn = summaries.get(mutation_type)
    return fn(params) if fn else f"Mutação desconhecida: {mutation_type}"


# ── Handlers ──


@_register("machine_down")
def _machine_down(data: EngineData, params: dict) -> str:
    """Block specific machine on given days (per-machine, not global)."""
    machine_id = params["machine_id"]
    start = int(params["start"])
    end = int(params["end"])
    blocked = set(range(start, end + 1))
    if machine_id not in data.machine_blocked_days:
        data.machine_blocked_days[machine_id] = set()
    data.machine_blocked_days[machine_id] |= blocked
    return f"Máquina {machine_id} parada dias {start}-{end}"


@_register("tool_down")
def _tool_down(data: EngineData, params: dict) -> str:
    """Block tool capacity on given days (per-tool, demand preserved)."""
    tool_id = params["tool_id"]
    start = int(params["start"])
    end = int(params["end"])
    blocked = set(range(start, end + 1))
    if tool_id not in data.tool_blocked_days:
        data.tool_blocked_days[tool_id] = set()
    data.tool_blocked_days[tool_id] |= blocked
    return f"Ferramenta {tool_id} indisponível dias {start}-{end}"


@_register("operator_shortage")
def _operator_shortage(data: EngineData, params: dict) -> str:
    """Advisory only — no effect on scheduler v1."""
    note = params.get("note", "sem detalhe")
    logger.warning("Operator shortage (advisory): %s", note)
    return f"Falta de operadores (advisory): {note}"


@_register("oee_change")
def _oee_change(data: EngineData, params: dict) -> str:
    """Change OEE for ops matching tool_id."""
    tool_id = params["tool_id"]
    new_oee = float(params["new_oee"])
    if not (0 < new_oee <= 1.0):
        raise ValueError(f"OEE deve estar entre 0 e 1.0, recebido: {new_oee}")
    count = 0
    for op in data.ops:
        if op.t == tool_id:
            op.oee = new_oee
            op.oee_source = "whatif"  # takes precedence over per-machine OEE
            count += 1
    return f"OEE alterado para {new_oee} em {count} ops (ferramenta {tool_id})"


@_register("rush_order")
def _rush_order(data: EngineData, params: dict) -> str:
    """Add demand for a SKU at a specific day (all matching ops)."""
    sku = params["sku"]
    qty = int(params["qty"])
    deadline_day = int(params["deadline_day"])
    count = 0
    for op in data.ops:
        if op.sku == sku:
            while len(op.d) <= deadline_day:
                op.d.append(0)
            op.d[deadline_day] += qty
            count += 1
    if count == 0:
        return f"Encomenda urgente: SKU {sku} não encontrado"
    return f"Encomenda urgente: +{qty} pç {sku} dia {deadline_day} ({count} ops)"


@_register("demand_change")
def _demand_change(data: EngineData, params: dict) -> str:
    """Scale demand for a SKU by a factor (all matching ops)."""
    sku = params["sku"]
    factor = float(params["factor"])
    count = 0
    for op in data.ops:
        if op.sku == sku:
            op.d = [round(d * factor) for d in op.d]
            count += 1
    if count == 0:
        return f"Procura: SKU {sku} não encontrado"
    return f"Procura {sku}: factor {factor}x aplicado ({count} ops)"


@_register("cancel_order")
def _cancel_order(data: EngineData, params: dict) -> str:
    """Zero demand for a SKU in a day range."""
    sku = params["sku"]
    from_day = int(params["from_day"])
    to_day = int(params["to_day"])
    count = 0
    for op in data.ops:
        if op.sku == sku:
            for day in range(from_day, min(to_day + 1, len(op.d))):
                if op.d[day] > 0:
                    count += 1
                    op.d[day] = 0
    return f"Canceladas {count} encomendas {sku} dias {from_day}-{to_day}"


@_register("third_shift")
def _third_shift(data: EngineData, params: dict, config: FactoryConfig | None = None) -> str:
    """Add night shift (00:00-07:00 = 420 min) to config.shifts.

    This extends the allocator timeline: shift_b_end stays at 1440,
    and a new shift C runs 0-420 (next day morning mapped as 1440-1860).
    The allocator sees day_capacity_min = sum(shifts) = 1440.
    """
    machine_id = params["machine_id"]
    if not any(m.id == machine_id for m in data.machines):
        return f"3º turno: máquina {machine_id} não encontrada"
    if config is None:
        return "3º turno: config não disponível (sem efeito)"
    # Only add once
    if not any(s.id == "C" for s in config.shifts):
        config.shifts.append(ShiftConfig("C", 1440, 1860, "Noite"))
    new_cap = config.day_capacity_min
    return f"3º turno activado — capacidade global → {new_cap} min/dia (todas as máquinas)"


@_register("overtime")
def _overtime(data: EngineData, params: dict, config: FactoryConfig | None = None) -> str:
    """Extend last shift by extra_min to add overtime capacity.

    E.g. +120 min → shift B ends at 1560 (02:00) instead of 1440 (00:00).
    """
    machine_id = params["machine_id"]
    extra_min = int(params["extra_min"])
    if not any(m.id == machine_id for m in data.machines):
        return f"Horas extra: máquina {machine_id} não encontrada"
    if config is None:
        return "Horas extra: config não disponível (sem efeito)"
    # Extend last shift's end_min
    last_shift = config.shifts[-1]
    last_shift.end_min += extra_min
    new_cap = config.day_capacity_min
    return (
        f"Horas extra: +{extra_min} min — capacidade global → {new_cap} min/dia (todas as máquinas)"
    )


@_register("add_holiday")
def _add_holiday(data: EngineData, params: dict) -> str:
    """Add a holiday day."""
    day_idx = int(params["day_idx"])
    if day_idx not in data.holidays:
        data.holidays.append(day_idx)
    return f"Feriado adicionado: dia {day_idx}"


@_register("remove_holiday")
def _remove_holiday(data: EngineData, params: dict) -> str:
    """Remove a holiday day."""
    day_idx = int(params["day_idx"])
    if day_idx in data.holidays:
        data.holidays.remove(day_idx)
        return f"Feriado removido: dia {day_idx}"
    return f"Dia {day_idx} não era feriado"


@_register("force_machine")
def _force_machine(data: EngineData, params: dict) -> str:
    """Force all ops with a tool to a specific machine."""
    tool_id = params["tool_id"]
    to_machine = params["to_machine"]
    if not any(m.id == to_machine for m in data.machines):
        raise ValueError(
            f"Máquina {to_machine} não existe. Válidas: {[m.id for m in data.machines]}"
        )
    count = 0
    for op in data.ops:
        if op.t == tool_id:
            op.m = to_machine
            op.alt = None
            count += 1
    return f"Forçar {count} ops (ferramenta {tool_id}) → máquina {to_machine}"


@_register("change_eco_lot")
def _change_eco_lot(
    data: EngineData,
    params: dict,
    config: FactoryConfig | None = None,
) -> str:
    """Change eco lot size for a SKU."""
    sku = params["sku"]
    new_eco_lot = int(params["new_eco_lot"])
    if new_eco_lot < 0:
        raise ValueError(f"Eco lot não pode ser negativo: {new_eco_lot}")
    for op in data.ops:
        if op.sku == sku:
            old = op.eco_lot
            if config is not None:
                rule = dict(config.sku_planning_rules.get(sku, {}))
                rule["eco_lot"] = new_eco_lot
                config.sku_planning_rules[sku] = rule
            op.eco_lot = new_eco_lot
            op.eco_lot_effective = new_eco_lot
            return f"Eco lot {sku}: {old} → {new_eco_lot}"
    return f"Eco lot: SKU {sku} não encontrado"


@_register("advance_edd")
def _advance_edd(data: EngineData, params: dict) -> str:
    """Shift demand earlier by N days for a SKU (move deadlines forward).

    Demand that would fall before day 0 is clamped to day 0.
    """
    sku = params["sku"]
    days = int(params["days"])
    if days <= 0:
        return "Dias deve ser > 0"
    for op in data.ops:
        if op.sku == sku:
            shifted = [0] * len(op.d)
            for i, v in enumerate(op.d):
                new_i = max(0, i - days)
                shifted[new_i] += v  # accumulate if clamped to day 0
            op.d = shifted
            return f"EDD antecipada {days}d para {sku}"
    return f"SKU {sku} não encontrado"


@_register("delay_edd")
def _delay_edd(data: EngineData, params: dict) -> str:
    """Shift demand later by N days for a SKU (push deadlines back)."""
    sku = params["sku"]
    days = int(params["days"])
    if days <= 0:
        return "Dias deve ser > 0"
    for op in data.ops:
        if op.sku == sku:
            # Shift demand array right: prepend zeros, keep ALL demand
            op.d = [0] * days + op.d
            return f"EDD atrasada {days}d para {sku}"
    return f"SKU {sku} não encontrado"
