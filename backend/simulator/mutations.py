"""Mutation application — Spec 04 §2.

Each mutation modifies EngineData in-place (on a deepcopy).
Returns a Portuguese summary string.

v2 fixes:
- machine_down: per-machine blocked days (not global holidays)
- tool_down: per-tool blocked days (not demand zeroing)
- third_shift/overtime: modify config.shifts (not MachineInfo)
- operator_shortage: real group+shift capacity block
"""

from __future__ import annotations

import copy
import logging
from datetime import date, timedelta

from backend.config.shifts import ordered_shifts
from backend.config.types import FactoryConfig, ShiftConfig
from backend.transform.calendars import apply_calendars
from backend.types import ClientDemandEntry, EngineData
from backend.validation import finite_float
from backend.validation import strict_int as _strict_int

logger = logging.getLogger(__name__)

# Mutation type → handler
_HANDLERS: dict[str, callable] = {}
MAX_MUTATION_EXTENSION_DAYS = 366
MAX_MUTATION_QTY = 100_000_000
MAX_DEMAND_FACTOR = 10.0


def valid_mutation_types() -> set[str]:
    """Return mutation names accepted by the simulator API."""
    return set(_HANDLERS)


def _day_range(params: dict, *, prefix: str = "") -> tuple[int, int]:
    start_key = f"{prefix}start" if prefix else "start"
    end_key = f"{prefix}end" if prefix else "end"
    start = _strict_int(
        params.get(start_key, params.get("start_day", params.get("day_idx"))), start_key
    )
    end = _strict_int(params.get(end_key, params.get("end_day", start)), end_key)
    return start, end


def normalize_mutation_params(mutation_type: str, params: dict) -> dict:
    """Canonicalize syntax only, without engine/config or capacity checks."""
    if not isinstance(params, dict):
        raise ValueError("Os parâmetros da mutação devem ser um objeto.")
    params = dict(params)
    for key in ("sku", "machine_id", "tool_id", "to_machine"):
        if key in params:
            params[key] = str(params[key]).strip()
    if mutation_type in {"machine_down", "tool_down", "operator_shortage"}:
        start, end = _day_range(params)
        for alias in ("start_day", "end_day", "day_idx"):
            params.pop(alias, None)
        params.update(start=start, end=end)
    if mutation_type == "operator_shortage":
        params["group"] = str(params.get("group", params.get("machine_group", ""))).strip()
        params["shift"] = str(params.get("shift", params.get("shift_id", ""))).strip()
        params["count"] = params.get("count", params.get("operators", 1))
        for alias in ("machine_group", "shift_id", "operators"):
            params.pop(alias, None)
    integer_fields = {
        "rush_order": ("qty", "deadline_day"),
        "cancel_order": ("from_day", "to_day"),
        "advance_edd": ("days",),
        "delay_edd": ("days",),
        "change_eco_lot": ("new_eco_lot",),
        "overtime": ("extra_min",),
        "add_holiday": ("day_idx",),
        "remove_holiday": ("day_idx",),
        "operator_shortage": ("count",),
    }.get(mutation_type, ())
    if mutation_type == "operator_shortage":
        integer_fields += tuple(key for key in ("start_min", "end_min") if key in params)
    for key in integer_fields:
        params[key] = _strict_int(params.get(key), f"{mutation_type}: {key}")
    float_key = {"oee_change": "new_oee", "demand_change": "factor"}.get(mutation_type)
    if float_key is not None:
        params[float_key] = finite_float(params.get(float_key), f"{mutation_type}: {float_key}")
    return params


def validate_mutation(
    data: EngineData,
    mutation_type: str,
    params: dict,
    config: FactoryConfig | None = None,
) -> dict:
    """Return canonical parameters after validating references and domains.

    The caller's parameters are never changed. Handlers consume this exact
    representation so aliases, defaults and resource identifiers agree.
    """

    if mutation_type not in _HANDLERS:
        raise ValueError(f"Unknown mutation type: {mutation_type}")
    params = normalize_mutation_params(mutation_type, params)

    machine_ids = {machine.id for machine in data.machines}
    tool_ids = {op.t for op in data.ops} | (set(config.tools) if config else set())

    def unique_sku_op():
        sku = str(params.get("sku", "")).strip()
        matches = [op for op in data.ops if op.sku == sku]
        if not matches:
            raise ValueError(f"SKU desconhecido: {sku or '(vazio)'}")
        if len(matches) != 1:
            raise ValueError(
                f"SKU ambíguo: {sku} corresponde a {len(matches)} operações; "
                "corrija os dados mestre."
            )
        return matches[0]

    if mutation_type in {"machine_down", "tool_down"}:
        resource_key = "machine_id" if mutation_type == "machine_down" else "tool_id"
        resource = str(params.get(resource_key, "")).strip()
        known = machine_ids if mutation_type == "machine_down" else tool_ids
        label = "Máquina" if mutation_type == "machine_down" else "Ferramenta"
        if resource not in known:
            raise ValueError(f"{label} desconhecida: {resource or '(vazia)'}")
        start, end = _day_range(params)
        params.update(start=start, end=end)
        if not 0 <= start <= end < data.n_days:
            raise ValueError(
                f"{mutation_type}: intervalo deve cumprir 0 <= start <= end < {data.n_days}."
            )

    if mutation_type == "operator_shortage":
        group = str(params.get("group", params.get("machine_group", ""))).strip()
        shift_id = str(params.get("shift", params.get("shift_id", ""))).strip()
        if config is None or (group, shift_id) not in config.operators:
            raise ValueError(
                f"Grupo/turno desconhecido: {group or '(vazio)'} "
                f"{shift_id or '(vazio)'}"
            )
        count = _strict_int(
            params.get("count", params.get("operators", 1)), "operator_shortage: count"
        )
        base = int(config.operators[(group, shift_id)])
        if not 1 <= count <= base:
            raise ValueError(f"operator_shortage: count deve estar entre 1 e {base}.")
        start, end = _day_range(params)
        if not 0 <= start <= end < data.n_days:
            raise ValueError(
                f"operator_shortage: intervalo deve cumprir 0 <= start <= end < {data.n_days}."
            )
        shift = next(item for item in config.shifts if item.id == shift_id)
        start_min = _strict_int(
            params.get("start_min", shift.start_min), "operator_shortage: start_min"
        )
        end_min = _strict_int(
            params.get("end_min", shift.end_min), "operator_shortage: end_min"
        )
        params.update(
            group=group, shift=shift_id, count=count, start=start, end=end,
            start_min=start_min, end_min=end_min,
        )
        if not shift.start_min <= start_min < end_min <= shift.end_min:
            raise ValueError(
                f"operator_shortage: intervalo deve caber no turno {shift_id} "
                f"({shift.start_min}-{shift.end_min})."
            )
        for day_idx in range(start, end + 1):
            boundaries = {start_min, end_min}
            relevant = []
            for block in data.operator_blocked_intervals:
                if (
                    int(block.get("start_day", -1)) == day_idx
                    and str(block.get("group", "")) == group
                    and str(block.get("shift", "")) == shift_id
                    and start_min < int(block.get("end_min", 0))
                    and int(block.get("start_min", 0)) < end_min
                ):
                    relevant.append(block)
                    boundaries.update(
                        {
                            max(start_min, int(block.get("start_min", 0))),
                            min(end_min, int(block.get("end_min", 0))),
                        }
                    )
            points = sorted(boundaries)
            for left, right in zip(points, points[1:]):
                unavailable = sum(
                    max(0, int(block.get("count", 1)))
                    for block in relevant
                    if left < int(block.get("end_min", 0))
                    and int(block.get("start_min", 0)) < right
                )
                if right > left and unavailable + count > base:
                    raise ValueError(
                        f"operator_shortage: ausências excedem equipa {base} "
                        f"no dia {day_idx}."
                    )

    if mutation_type in {"third_shift", "overtime"}:
        if mutation_type == "third_shift":
            raise ValueError(
                "O terceiro turno após a meia-noite não é suportado; "
                "define turnos dentro do mesmo dia civil."
            )
        extra_min = params["extra_min"]
        shifts = ordered_shifts(config) if config is not None else []
        remaining = 1440 - shifts[-1].end_min if shifts else 0
        if extra_min <= 0 or extra_min > remaining:
            raise ValueError(
                f"overtime: extra_min deve estar entre 1 e {max(0, remaining)} "
                "para terminar até às 24:00."
            )

    if mutation_type in {"add_holiday", "remove_holiday"}:
        day_idx = params["day_idx"]
        if not 0 <= day_idx < data.n_days:
            raise ValueError(f"{mutation_type}: day_idx fora do horizonte.")

    if mutation_type == "oee_change":
        tool_id = str(params.get("tool_id", "")).strip()
        if tool_id not in tool_ids:
            raise ValueError(f"Ferramenta desconhecida: {tool_id or '(vazia)'}")
        new_oee = params["new_oee"]
        if not 0 < new_oee <= 1:
            raise ValueError("oee_change: new_oee deve estar no intervalo (0, 1].")

    if mutation_type == "rush_order":
        op = unique_sku_op()
        qty = params["qty"]
        deadline = params["deadline_day"]
        current_last_day = max(data.n_days, len(op.d)) - 1
        if not 1 <= qty <= MAX_MUTATION_QTY:
            raise ValueError(
                f"rush_order: qty deve estar entre 1 e {MAX_MUTATION_QTY}."
            )
        if not 0 <= deadline <= current_last_day + MAX_MUTATION_EXTENSION_DAYS:
            raise ValueError(
                "rush_order: deadline_day deve ser não negativo e não pode "
                f"estender o horizonte em mais de {MAX_MUTATION_EXTENSION_DAYS} dias."
            )

    if mutation_type == "demand_change":
        unique_sku_op()
        factor = params["factor"]
        if not 0 < factor <= MAX_DEMAND_FACTOR:
            raise ValueError(
                f"demand_change: factor deve estar no intervalo (0, {MAX_DEMAND_FACTOR}]."
            )

    if mutation_type == "cancel_order":
        op = unique_sku_op()
        from_day = params["from_day"]
        to_day = params["to_day"]
        horizon = max(data.n_days, len(op.d))
        if not 0 <= from_day <= to_day < horizon:
            raise ValueError(
                f"cancel_order: intervalo deve cumprir 0 <= from_day <= to_day < {horizon}."
            )

    if mutation_type == "force_machine":
        tool_id = str(params.get("tool_id", "")).strip()
        machine_id = str(params.get("to_machine", "")).strip()
        if tool_id not in tool_ids:
            raise ValueError(f"Ferramenta desconhecida: {tool_id or '(vazia)'}")
        if machine_id not in machine_ids:
            raise ValueError(f"Máquina desconhecida: {machine_id or '(vazia)'}")

    if mutation_type == "change_eco_lot":
        unique_sku_op()
        eco_lot = params["new_eco_lot"]
        if not 0 <= eco_lot <= MAX_MUTATION_QTY:
            raise ValueError(
                f"change_eco_lot: new_eco_lot deve estar entre 0 e {MAX_MUTATION_QTY}."
            )

    if mutation_type in {"advance_edd", "delay_edd"}:
        unique_sku_op()
        days = params["days"]
        if not 1 <= days <= MAX_MUTATION_EXTENSION_DAYS:
            raise ValueError(
                f"{mutation_type}: days deve estar entre 1 e "
                f"{MAX_MUTATION_EXTENSION_DAYS}."
            )
    return params


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
    params = validate_mutation(data, mutation_type, params, config)
    if data.calendar_base_holidays is None:
        data.calendar_base_holidays = sorted(set(data.holidays))
    previous_calendar = None
    if config is not None and mutation_type in {"overtime", "rush_order", "delay_edd"}:
        previous_calendar = copy.copy(data)
        apply_calendars(previous_calendar, config)
    # Pass config to handlers that accept it
    import inspect

    sig = inspect.signature(handler)
    if "config" in sig.parameters:
        summary = handler(data, params, config=config)
    else:
        summary = handler(data, params)
    extended = _extend_horizon(data) if mutation_type in {"rush_order", "delay_edd"} else False
    _sync_client_demands(data, mutation_type, params)
    if previous_calendar is not None and (extended or mutation_type == "overtime"):
        _rebuild_calendar_preserving_overlays(data, config, previous_calendar)
    return summary


def _sync_client_demands(data: EngineData, mutation_type: str, params: dict) -> None:
    """Keep the client trace on the same demand and dates as the scheduler."""
    if mutation_type not in {
        "rush_order",
        "cancel_order",
        "demand_change",
        "advance_edd",
        "delay_edd",
    }:
        return
    sku = params["sku"]
    entries = data.client_demands.setdefault(sku, [])

    def day_date(day):
        if 0 <= day < len(data.workdays):
            return data.workdays[day]
        return ((date.fromisoformat(data.workdays[0][:10]) + timedelta(days=day)).isoformat()
                if data.workdays else "")

    if mutation_type == "rush_order":
        op = next(op for op in data.ops if op.sku == sku)
        day, qty = params["deadline_day"], params["qty"]
        entries.append(ClientDemandEntry(op.client, sku, day, day_date(day), qty, -qty))
    elif mutation_type == "cancel_order":
        entries = [
            entry
            for entry in entries
            if not params["from_day"] <= entry.day_idx <= params["to_day"]
        ]
    elif mutation_type in {"advance_edd", "delay_edd"}:
        offset = params["days"] * (-1 if mutation_type == "advance_edd" else 1)
        for entry in entries:
            entry.day_idx = max(0, entry.day_idx + offset)
            entry.date = day_date(entry.day_idx)
    else:
        # Apportion the rounded canonical daily total without gaining/losing
        # pieces when several clients share the same operation and date.
        op = next(op for op in data.ops if op.sku == sku)
        by_day = {}
        for entry in entries:
            by_day.setdefault(entry.day_idx, []).append(entry)
        for day, daily in by_day.items():
            weights = [abs(entry.np_value) for entry in daily]
            total = sum(weights)
            target = op.d[day] if 0 <= day < len(op.d) else 0
            allocated = [(target * weight // total if total else 0) for weight in weights]
            if total:
                ranked = sorted(
                    range(len(daily)), key=lambda i: (-(target * weights[i] % total), i)
                )
                for index in ranked[:target - sum(allocated)]:
                    allocated[index] += 1
            for entry, qty in zip(daily, allocated, strict=True):
                credit = max(0, entry.order_qty - abs(entry.np_value))
                entry.order_qty, entry.np_value = qty + credit, -qty
        entries = [entry for entry in entries if entry.order_qty > 0]
    if entries:
        data.client_demands[sku] = entries
    else:
        data.client_demands.pop(sku, None)


def _extend_horizon(data: EngineData) -> bool:
    horizon = max([data.n_days, *(len(op.d) for op in data.ops)])
    if horizon <= data.n_days:
        return False
    old_days = len(data.workdays)
    if data.workdays:
        last = date.fromisoformat(str(data.workdays[-1])[:10])
        data.workdays.extend(
            (last + timedelta(days=offset)).isoformat()
            for offset in range(1, horizon - old_days + 1)
        )
    new_weekends = {
        idx for idx in range(old_days, len(data.workdays))
        if date.fromisoformat(data.workdays[idx]).weekday() >= 5
    }
    if data.calendar_base_holidays is None:
        data.calendar_base_holidays = sorted(set(data.holidays))
    data.holidays = sorted(set(data.holidays) | new_weekends)
    data.calendar_base_holidays = sorted(set(data.calendar_base_holidays) | new_weekends)
    data.n_days = horizon
    for op in data.ops:
        op.d.extend([0] * (horizon - len(op.d)))
    return True


def _rebuild_calendar_preserving_overlays(
    data: EngineData, config: FactoryConfig, previous: EngineData
) -> None:
    """Reproject persistent intervals without losing already-applied what-ifs."""
    new_base_holidays = set(data.calendar_base_holidays or []) - set(
        previous.calendar_base_holidays or []
    )
    added_holidays = set(data.holidays) - set(previous.holidays) - new_base_holidays
    removed_holidays = set(previous.holidays) - set(data.holidays)
    extra_days = {
        attr: {
            resource: days - getattr(previous, attr).get(resource, set())
            for resource, days in getattr(data, attr).items()
        }
        for attr in ("machine_blocked_days", "tool_blocked_days")
    }
    extra_intervals = {
        attr: {
            resource: [
                item for item in entries
                if item not in getattr(previous, attr).get(resource, [])
            ]
            for resource, entries in getattr(data, attr).items()
        }
        for attr in ("machine_blocked_intervals", "tool_blocked_intervals")
    }
    extra_operators = [
        item for item in data.operator_blocked_intervals
        if item not in previous.operator_blocked_intervals
    ]
    apply_calendars(data, config)
    data.holidays = sorted((set(data.holidays) | added_holidays) - removed_holidays)
    for attr, resources in extra_days.items():
        for resource, days in resources.items():
            if days:
                getattr(data, attr).setdefault(resource, set()).update(days)
    for attr, resources in extra_intervals.items():
        for resource, entries in resources.items():
            if entries:
                getattr(data, attr).setdefault(resource, []).extend(entries)
    data.operator_blocked_intervals.extend(extra_operators)


def reapply_calendar_mutations(
    data: EngineData,
    mutations: list[dict],
    config: FactoryConfig,
) -> None:
    """Restore availability mutations erased by a persistent-calendar rebuild."""

    for mutation in mutations:
        mutation_type = str(mutation.get("type", ""))
        if mutation_type not in {
            "machine_down",
            "tool_down",
            "operator_shortage",
            "add_holiday",
            "remove_holiday",
        }:
            continue
        apply_mutation(
            data,
            mutation_type,
            dict(mutation.get("params", {})),
            config=config,
        )


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
        "operator_shortage": lambda p: (
            f"Falta de {p.get('count', 1)} operador(es) em "
            f"{p.get('group', p.get('machine_group', 'Grandes'))} "
            f"turno {p.get('shift', 'A')} dias "
            f"{p.get('start', p.get('start_day', p.get('day_idx', '?')))}-"
            f"{p.get('end', p.get('end_day', p.get('day_idx', '?')))}"
        ),
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
def _operator_shortage(
    data: EngineData,
    params: dict,
    config: FactoryConfig | None = None,
) -> str:
    """Block operator capacity for a machine group and shift."""
    group = str(params.get("group", params.get("machine_group", "Grandes"))).strip()
    shift = str(params.get("shift", params.get("shift_id", "A"))).strip()
    if not group:
        group = "Grandes"
    if not shift:
        shift = "A"
    try:
        count = max(1, int(params.get("count", params.get("operators", 1))))
        start_day = int(params.get("start", params.get("start_day", params.get("day_idx", 0))))
        end_day = int(params.get("end", params.get("end_day", start_day)))
    except (TypeError, ValueError) as exc:
        raise ValueError("operator_shortage exige count/start/end inteiros.") from exc
    shift_config = None
    if config is not None:
        shift_config = next((item for item in config.shifts if item.id == shift), None)
    default_start = 420 if shift == "A" else 930
    default_end = 930 if shift == "A" else 1440
    start_min = int(
        params.get(
            "start_min",
            shift_config.start_min if shift_config is not None else default_start,
        )
    )
    end_min = int(
        params.get(
            "end_min",
            shift_config.end_min if shift_config is not None else default_end,
        )
    )
    if end_min <= start_min:
        raise ValueError("operator_shortage exige end_min > start_min.")

    added = 0
    for day_idx in range(start_day, end_day + 1):
        if day_idx < 0 or day_idx >= data.n_days:
            continue
        data.operator_blocked_intervals.append(
            {
                "id": f"whatif-operator-{group}-{shift}-{day_idx}",
                "group": group,
                "shift": shift,
                "start_day": day_idx,
                "start_min": start_min,
                "end_day": day_idx,
                "end_min": end_min,
                "count": count,
                "category": "What-if",
                "reason": str(params.get("note", "Falta de operadores")),
            }
        )
        added += 1
    logger.info(
        "Operator shortage what-if: %s/%s count=%d days=%d-%d",
        group,
        shift,
        count,
        start_day,
        end_day,
    )
    return (
        f"Falta de {count} operador(es): {group} turno {shift}, "
        f"dias {start_day}-{end_day} ({added} intervalo(s))"
    )


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
    """Add demand for one unambiguous SKU operation at a specific day."""
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
    return f"Encomenda urgente: +{qty} pç {sku} dia {deadline_day}"


@_register("demand_change")
def _demand_change(data: EngineData, params: dict) -> str:
    """Scale demand for one unambiguous SKU operation by a factor."""
    sku = params["sku"]
    factor = float(params["factor"])
    count = 0
    for op in data.ops:
        if op.sku == sku:
            op.d = [round(d * factor) for d in op.d]
            count += 1
    if count == 0:
        return f"Procura: SKU {sku} não encontrado"
    return f"Procura {sku}: factor {factor}x aplicado"


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
    """Extend the final factory shift within the same calendar day."""
    extra_min = int(params["extra_min"])
    if config is None:
        return "Horas extra: config não disponível (sem efeito)"
    last_shift = ordered_shifts(config)[-1]
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
def _force_machine(
    data: EngineData, params: dict, config: FactoryConfig | None = None
) -> str:
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
    for group in data.twin_groups:
        if group.tool_id == tool_id:
            group.machine_id = to_machine
    if config is not None:
        tool = dict(config.tools.get(tool_id, {}))
        tool.update(primary=to_machine, alt=None)
        config.tools[tool_id] = tool
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
