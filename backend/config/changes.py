"""Small edits of a candidate configuration, shared by every entry point.

The direct endpoints, the Copilot and ``POST /api/data/replan-jobs`` (many
changes in one recalculation) all call these helpers, so a change is checked
the same way wherever it comes from. Each helper changes only the
configuration it is given and raises ``ValueError`` (``LookupError`` for an
unknown reference) with the pt-PT text shown to the planner.
"""

from __future__ import annotations

from datetime import date as dt_date

from backend.config.planning import (
    clean_sku_subcontracts,
    normalize_sku_planning_rule,
    normalize_subcontract_company,
)
from backend.config.types import FactoryConfig
from backend.types import EngineData
from backend.validation import strict_int

# Parameters the planner may tune (PUT /config and ``config_params``).
TUNABLE_CONFIG_KEYS = (
    "oee_default",
    "jit_buffer_pct",
    "jit_threshold",
    "jit_max_retries",
    "max_edd_gap",
    "max_edd_span",
    "edd_swap_tolerance",
    "edd_assign_threshold",
    "campaign_window",
    "urgency_threshold",
    "interleave_enabled",
    "auto_buffer",
    "vns_enabled",
    "vns_max_iter",
    "compact_enabled",
    "setup_crews_by_group",
    "weight_earliness",
    "weight_setups",
    "weight_balance",
    "eco_lot_mode",
)
# Chaves retiradas do contrato: clientes antigos ainda as podem enviar.
# São ignoradas (não alteram nada) em vez de rejeitarem a gravação.
# ``max_run_days`` (limite de dias seguidos) foi retirado a 09/10/2026.
RETIRED_CONFIG_KEYS = frozenset({"max_run_days"})


def coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "sim", "on"}:
            return True
        if normalized in {"false", "0", "no", "nao", "não", "off"}:
            return False
    raise ValueError(f"valor booleano inválido: {value!r}")


def coerce_tunable_value(key: str, current_value, new_value):
    if isinstance(current_value, bool):
        return coerce_bool(new_value)
    try:
        coerced = type(current_value)(new_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key}: valor inválido {new_value!r}") from exc
    if key == "eco_lot_mode" and coerced not in {"hard", "soft"}:
        raise ValueError("eco_lot_mode deve ser 'hard' ou 'soft'")
    return coerced


# ─── Calendário ───────────────────────────────────────────────────────────


def add_holiday(config: FactoryConfig, date: str) -> None:
    if date in config.holidays:
        raise ValueError(f"Feriado {date} já existe.")
    config.holidays.append(date)


def remove_holiday(config: FactoryConfig, date: str) -> None:
    if date not in config.holidays:
        raise ValueError(f"Feriado {date} não existe.")
    config.holidays.remove(date)


def add_extra_workday(config: FactoryConfig, date_str: str) -> None:
    """Open a normally closed weekend date (a repeated date changes nothing)."""
    try:
        parsed = dt_date.fromisoformat(date_str)
    except ValueError as exc:
        raise ValueError("A data deve usar o formato YYYY-MM-DD.") from exc
    if parsed.weekday() < 5:
        raise ValueError("Só sábados ou domingos podem ser dias extra.")
    if date_str not in config.extra_workdays:
        config.extra_workdays.append(date_str)
        config.extra_workdays.sort()


def remove_extra_workday(config: FactoryConfig, date: str) -> None:
    if date not in config.extra_workdays:
        raise LookupError(f"Dia de trabalho extra {date} não existe.")
    config.extra_workdays.remove(date)


# ─── Peças gémeas ─────────────────────────────────────────────────────────


def add_twin(
    config: FactoryConfig,
    engine_data: EngineData,
    tool_id: str,
    sku_a: str,
    sku_b: str,
):
    """Register a twin pair in ``config.twins``.

    Returns ``(machine_id, op_a, op_b)`` so a caller that keeps live engine
    data can add the matching twin group.
    """
    if tool_id in config.twins:
        raise ValueError(f"Twin para ferramenta {tool_id} já existe.")
    if sku_a == sku_b:
        raise ValueError("Uma gémea exige duas referências distintas.")
    known_tools = set(config.tools) | {op.t for op in engine_data.ops}
    if tool_id not in known_tools:
        raise ValueError(f"Ferramenta {tool_id} não existe.")

    matches_a = [op for op in engine_data.ops if op.sku == sku_a]
    matches_b = [op for op in engine_data.ops if op.sku == sku_b]
    if len(matches_a) != 1 or len(matches_b) != 1:
        raise ValueError(
            "Cada SKU gémea deve corresponder a uma operação única; "
            f"{sku_a}={len(matches_a)}, {sku_b}={len(matches_b)}."
        )
    op_a, op_b = matches_a[0], matches_b[0]
    if op_a.t != tool_id or op_b.t != tool_id:
        raise ValueError(
            f"As duas referências têm de usar a ferramenta {tool_id}; "
            f"{sku_a} usa {op_a.t} e {sku_b} usa {op_b.t}."
        )
    machines_a = {machine for machine in (op_a.m, op_a.alt) if machine}
    machines_b = {machine for machine in (op_b.m, op_b.alt) if machine}
    common_machines = machines_a & machines_b
    if not common_machines:
        raise ValueError("As referências gémeas não têm uma máquina elegível comum.")
    configured_primary = str(config.tools.get(tool_id, {}).get("primary", ""))
    machine_id = (
        configured_primary if configured_primary in common_machines else sorted(common_machines)[0]
    )
    config.twins[tool_id] = [sku_a, sku_b]
    return machine_id, op_a, op_b


def remove_twin(config: FactoryConfig, tool_id: str) -> None:
    if tool_id not in config.twins:
        raise ValueError(f"Twin para ferramenta {tool_id} não existe.")
    del config.twins[tool_id]


# ─── Setups, operadores, referências, subcontratação ──────────────────────


def normalize_setup_overrides(raw_items: list) -> list[dict]:
    """The full list of SKU × machine setup exceptions."""
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ValueError("Cada override deve ser um objeto.")
        try:
            item = {
                "sku": str(raw.get("sku", "")).strip(),
                "machine": str(raw.get("machine", "")).strip(),
                "hours": float(raw.get("hours")),
            }
        except (TypeError, ValueError) as exc:
            raise ValueError("hours deve ser um número.") from exc
        if not item["sku"] or not item["machine"]:
            raise ValueError("sku e machine são obrigatórios.")
        items.append(item)
    return items


def apply_operator_counts(config: FactoryConfig, counts: dict) -> list[str]:
    """Set operator counts (``{"Grandes A": 6, ...}``); returns the keys changed."""
    changed = []
    for key, count in counts.items():
        try:
            parsed_count = strict_int(count, key)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Operadores inválidos para {key}: {count!r}") from exc
        if parsed_count < 0:
            raise ValueError(f"Operadores inválidos para {key}: deve ser >= 0")

        if key in config.operators:
            config.operators[key] = parsed_count
            changed.append(key)
            continue
        # Tuple key format: "Grandes A" → ("Grandes", "A")
        parts = key.rsplit(" ", 1)
        if len(parts) == 2:
            group, shift = parts
            if shift not in {item.id for item in config.shifts}:
                raise ValueError(f"Turno desconhecido para {key}: {shift}")
            if group not in set(config.machine_groups.values()):
                raise ValueError(f"Grupo desconhecido para {key}: {group}")
            config.operators[(group, shift)] = parsed_count
            changed.append(key)
    return changed


def set_sku_planning(
    config: FactoryConfig,
    engine_data: EngineData,
    sku: str,
    raw_rule: dict,
) -> dict:
    """Set (or, when the rule is empty, clear) one reference's planning rule."""
    if not any(op.sku == sku for op in engine_data.ops):
        raise LookupError(f"SKU {sku} não encontrado.")
    rule = normalize_sku_planning_rule(sku, raw_rule)
    if rule:
        config.sku_planning_rules[sku] = rule
    else:
        config.sku_planning_rules.pop(sku, None)
    return rule


def validate_subcontract_rules(companies: list[dict], sku_subcontracts: dict[str, dict]) -> None:
    company_ids = {str(company.get("id")) for company in companies if company.get("id")}
    for sku, rule in sku_subcontracts.items():
        if not rule.get("enabled", True):
            continue
        company_id = str(rule.get("company_id") or "").strip()
        if not company_id:
            raise ValueError(f"{sku}: escolhe uma empresa antes de ativar a subcontratação.")
        if company_id not in company_ids:
            raise ValueError(f"{sku}: empresa de subcontratação desconhecida: {company_id}.")


def normalize_subcontracts(body: dict) -> tuple[list[dict], dict[str, dict]]:
    """``(companies, sku_subcontracts)`` of a PUT /subcontracts body, checked."""
    companies = [
        normalize_subcontract_company(company)
        for company in body.get("companies", [])
        if isinstance(company, dict)
    ]
    sku_subcontracts = clean_sku_subcontracts(body.get("sku_subcontracts", {}))
    validate_subcontract_rules(companies, sku_subcontracts)
    return companies, sku_subcontracts


def apply_subcontracts(
    config: FactoryConfig,
    companies: list[dict],
    sku_subcontracts: dict[str, dict],
) -> None:
    config.subcontract_companies = companies
    config.sku_subcontracts = sku_subcontracts
    config.subcontract_skus = [
        sku for sku, rule in sku_subcontracts.items() if rule.get("enabled", True)
    ]
