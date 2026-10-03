"""Effective planning configuration applied before scheduling.

The ISOP remains the source of truth for imported master data. User changes
live in FactoryConfig and are projected onto EngineData immediately before
lot sizing so every setting changes the real scheduler input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.config.types import (
    JIT_MAX_ANTICIPATION_WORKDAYS,
    OUT_OF_SCOPE_MACHINES,
    FactoryConfig,
)
from backend.types import EngineData, MachineInfo

SKU_RULE_FIELDS = {
    "eco_lot",
    "start_buffer_days",
    "finish_buffer_days",
    "min_campaign_qty",
    "min_campaign_prod_min",
    "max_group_gap_days",
}

SUBCONTRACT_READ_LEAD_TIME_DAYS = 7
SUBCONTRACT_PLAN_LEAD_TIME_WORKDAYS = 5


@dataclass(frozen=True, slots=True)
class PlanningMilestones:
    """Named dates for one demand without overloading the legacy EDD fields."""

    customer_delivery_day: int
    latest_subcontract_dispatch_day: int | None
    subcontract_dispatch_day: int | None
    production_due_day: int
    internal_target_day: int
    material_reference_day: int
    material_reference_kind: str
    material_release_day: int


def _blank(value: Any) -> bool:
    return value is None or value == ""


def _tool_value(raw: Any, field: str, default: Any = None) -> Any:
    if isinstance(raw, dict):
        return raw.get(field, default)
    return getattr(raw, field, default)


def enforce_machine_scope(
    config: FactoryConfig,
    engine_data: EngineData | None = None,
    segments: list | None = None,
) -> None:
    """Discard legacy empty resources; never discard production or demand."""

    if engine_data is not None:
        excluded_ops = [
            op for op in engine_data.ops
            if op.m in OUT_OF_SCOPE_MACHINES or op.alt in OUT_OF_SCOPE_MACHINES
        ]
        if excluded_ops:
            raise ValueError(
                "PRM020 fora do âmbito: operação atribuída a esta máquina "
                f"({excluded_ops[0].sku}). Corrija o ISOP antes de calcular."
            )
        if any(group.machine_id in OUT_OF_SCOPE_MACHINES for group in engine_data.twin_groups):
            raise ValueError("O plano contém peças gémeas na PRM020, fora do âmbito atual.")
        if any(
            supply.machine_id in OUT_OF_SCOPE_MACHINES
            for supply in engine_data.committed_supplies
        ):
            raise ValueError("O plano contém produção em curso na PRM020, fora do âmbito atual.")
    if segments is not None and any(
        segment.machine_id in OUT_OF_SCOPE_MACHINES for segment in segments
    ):
        raise ValueError("O plano contém produção na PRM020, fora do âmbito atual.")

    for tool_id, raw in config.tools.items():
        if _tool_value(raw, "primary") in OUT_OF_SCOPE_MACHINES:
            raise ValueError(
                f"A ferramenta {tool_id} usa a PRM020 como máquina principal; "
                "corrija o encaminhamento antes de continuar."
            )
        if isinstance(raw, dict) and raw.get("alt") in OUT_OF_SCOPE_MACHINES:
            raw.pop("alt")

    for machine_id in OUT_OF_SCOPE_MACHINES:
        config.machines.pop(machine_id, None)
        if engine_data is not None:
            engine_data.machine_blocked_days.pop(machine_id, None)
            engine_data.machine_blocked_intervals.pop(machine_id, None)
    config.machine_unavailability = [
        entry for entry in config.machine_unavailability
        if entry.get("resource") not in OUT_OF_SCOPE_MACHINES
    ]
    config.setup_overrides = [
        entry for entry in config.setup_overrides
        if entry.get("machine") not in OUT_OF_SCOPE_MACHINES
    ]
    if engine_data is not None:
        engine_data.machines = [
            machine for machine in engine_data.machines
            if machine.id not in OUT_OF_SCOPE_MACHINES
        ]
        engine_data.current_machine_states = [
            state for state in engine_data.current_machine_states
            if state.machine_id not in OUT_OF_SCOPE_MACHINES
        ]
        engine_data.plan_anchors = [
            anchor for anchor in engine_data.plan_anchors
            if anchor.machine_id not in OUT_OF_SCOPE_MACHINES
        ]


def _ensure_machine_info(engine_data: EngineData, config: FactoryConfig, machine_id: str) -> None:
    if any(machine.id == machine_id for machine in engine_data.machines):
        return
    machine_cfg = config.machines.get(machine_id) if config.machines else None
    group = (
        machine_cfg.group
        if machine_cfg is not None
        else config.machine_groups.get(machine_id, "Grandes")
    )
    day_capacity = (
        machine_cfg.day_capacity_min
        if machine_cfg is not None and machine_cfg.day_capacity_min is not None
        else config.day_capacity_min
    )
    engine_data.machines.append(
        MachineInfo(id=machine_id, group=group, day_capacity=day_capacity)
    )


def _apply_tool_config(engine_data: EngineData, config: FactoryConfig) -> None:
    """Project configured tool routing/setup into loaded operations.

    ISOP rows provide the active references and tools. The editable factory
    configuration is the source of truth for the current primary machine,
    alternative machine and setup hours of those tools. Re-applying it here keeps
    old in-memory plans and replan candidates consistent after a machine is
    re-enabled or a tool routing is changed.
    """

    if not config.tools:
        return

    def is_active(machine_id: str | None) -> bool:
        if not machine_id:
            return False
        machine = config.machines.get(machine_id) if config.machines else None
        return machine.active if machine is not None else True

    ops_by_id = {op.id: op for op in engine_data.ops}
    for op in engine_data.ops:
        tool = config.tools.get(op.t)
        if not tool:
            continue

        configured_primary = str(_tool_value(tool, "primary", "") or "").strip()
        configured_alt = str(_tool_value(tool, "alt", "") or "").strip() or None
        if configured_alt == configured_primary:
            configured_alt = None
        setup_hours = _tool_value(tool, "setup_hours", None)

        primary = configured_primary
        alt = configured_alt
        if configured_primary and not is_active(configured_primary):
            if is_active(configured_alt):
                primary = str(configured_alt)
                alt = None
            else:
                alt = None
        elif not is_active(configured_alt):
            alt = None

        if primary:
            op.m = primary
            _ensure_machine_info(engine_data, config, primary)
        if alt:
            _ensure_machine_info(engine_data, config, alt)
        op.alt = alt
        if setup_hours is not None:
            op.sH = float(setup_hours)

    for twin_group in engine_data.twin_groups:
        first = ops_by_id.get(twin_group.op_id_1)
        if first is not None:
            twin_group.machine_id = first.m


def synchronize_active_twin_groups(
    engine_data: EngineData,
    twins_config: dict[str, list[str]],
) -> EngineData:
    """Rebuild active twin groups from the current factory configuration.

    Persisted plans retain the groups that were active when they were saved.
    Rebuilding them at operational boundaries prevents an old snapshot from
    reviving a pair that has since been deactivated or reclassified.
    """

    from backend.transform.twins import identify_twins_from_master

    engine_data.twin_groups = identify_twins_from_master(
        engine_data.ops,
        twins_config,
    )
    return engine_data


def harmonize_imported_twin_eco_lots(
    engine_data: EngineData,
    config: FactoryConfig,
) -> list[str]:
    """Give each imported twin pair one conservative effective eco-lot.

    Twin cycles always produce both references 1:1.  ISOP files can still carry
    different commercial lot sizes for those references, so retain those source
    values on the operations and project the larger value into the planning
    rules used by the new dataset.
    """

    ops_by_id = {op.id: op for op in engine_data.ops}
    warnings: list[str] = []
    for twin in engine_data.twin_groups:
        first = ops_by_id.get(twin.op_id_1)
        second = ops_by_id.get(twin.op_id_2)
        if first is None or second is None:
            continue

        first_rule = normalize_sku_planning_rule(
            first.sku, config.sku_planning_rules.get(first.sku)
        )
        second_rule = normalize_sku_planning_rule(
            second.sku, config.sku_planning_rules.get(second.sku)
        )
        first_eco = int(first_rule.get("eco_lot", first.eco_lot) or 0)
        second_eco = int(second_rule.get("eco_lot", second.eco_lot) or 0)
        if first_eco == second_eco:
            continue

        shared_eco = max(first_eco, second_eco)
        first_rule["eco_lot"] = shared_eco
        second_rule["eco_lot"] = shared_eco
        config.sku_planning_rules[first.sku] = first_rule
        config.sku_planning_rules[second.sku] = second_rule
        warnings.append(
            f"Eco-lote das gémeas {twin.tool_id} harmonizado para {shared_eco} "
            f"({first.sku}: {first_eco}; {second.sku}: {second_eco})."
        )

    return warnings


def _non_negative_int(value: Any, field: str, sku: str) -> int | None:
    if _blank(value):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{sku}: {field} inválido: {value!r}") from exc
    if parsed < 0:
        raise ValueError(f"{sku}: {field} deve ser >= 0")
    return parsed


def _non_negative_float(value: Any, field: str, sku: str) -> float | None:
    if _blank(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{sku}: {field} inválido: {value!r}") from exc
    if parsed < 0:
        raise ValueError(f"{sku}: {field} deve ser >= 0")
    return parsed


def _calendar_days_to_nominal_workdays(days: int) -> int:
    """Convert a calendar-day subcontract reading lead into planning workdays."""
    full_weeks, remainder = divmod(max(0, days), 7)
    return full_weeks * 5 + min(remainder, 5)


def _workdays_to_nominal_calendar_days(workdays: int) -> int:
    """Return the calendar-day reading lead shown for a workday planning lead."""
    full_weeks, remainder = divmod(max(0, workdays), 5)
    return full_weeks * 7 + remainder


def normalize_sku_planning_rule(sku: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return a validated, compact SKU planning rule."""
    raw = raw or {}
    rule: dict[str, Any] = {}

    if "eco_lot_override" in raw and "eco_lot" not in raw:
        raw = {**raw, "eco_lot": raw.get("eco_lot_override")}

    for field in (
        "eco_lot",
        "start_buffer_days",
        "finish_buffer_days",
        "min_campaign_qty",
        "planning_priority",
    ):
        parsed = _non_negative_int(raw.get(field), field, sku)
        if parsed is not None:
            rule[field] = parsed

    for field in ("min_campaign_prod_min",):
        parsed_f = _non_negative_float(raw.get(field), field, sku)
        if parsed_f is not None:
            rule[field] = parsed_f

    parsed_gap = _non_negative_int(raw.get("max_group_gap_days"), "max_group_gap_days", sku)
    if parsed_gap is not None:
        rule["max_group_gap_days"] = parsed_gap

    return rule


def normalize_subcontract_rule(sku: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return a validated subcontract rule for one SKU."""
    raw = raw or {}
    enabled = raw.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in {"0", "false", "no", "nao", "não", "off"}

    rule: dict[str, Any] = {"enabled": bool(enabled)}
    company_id = raw.get("company_id") or raw.get("company") or raw.get("empresa")
    if not _blank(company_id):
        rule["company_id"] = str(company_id)

    parsed_workdays = _non_negative_int(
        raw.get("lead_time_workdays"),
        "lead_time_workdays",
        sku,
    )
    parsed_calendar = None
    for field in ("lead_time_days", "external_lead_time_days"):
        parsed_calendar = _non_negative_int(raw.get(field), field, sku)
        if parsed_calendar is not None:
            break
    if parsed_workdays is not None:
        rule["lead_time_workdays"] = parsed_workdays
        rule["lead_time_days"] = (
            parsed_calendar
            if parsed_calendar is not None
            else _workdays_to_nominal_calendar_days(parsed_workdays)
        )
    elif parsed_calendar is not None:
        rule["lead_time_days"] = parsed_calendar
        rule["lead_time_workdays"] = _calendar_days_to_nominal_workdays(
            parsed_calendar
        )

    for field in ("buffer_days", "internal_buffer_days"):
        parsed = _non_negative_int(raw.get(field), field, sku)
        if parsed is not None:
            rule["buffer_days"] = parsed
            break

    return rule


def normalize_subcontract_company(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate one subcontract company entry."""
    company_id = raw.get("id") or raw.get("company_id") or raw.get("name") or raw.get("nome")
    if _blank(company_id):
        raise ValueError("Empresa de subcontratação sem id/nome")
    cid = str(company_id)
    lead_workdays = _non_negative_int(
        raw.get("lead_time_workdays"),
        "lead_time_workdays",
        cid,
    )
    lead_calendar = None
    for field in ("lead_time_days", "default_lead_time_days"):
        lead_calendar = _non_negative_int(raw.get(field), field, cid)
        if lead_calendar is not None:
            break
    if lead_workdays is None:
        lead_workdays = (
            _calendar_days_to_nominal_workdays(lead_calendar)
            if lead_calendar is not None
            else 0
        )
    if lead_calendar is None:
        lead_calendar = _workdays_to_nominal_calendar_days(lead_workdays)
    return {
        "id": cid,
        "name": str(raw.get("name") or raw.get("nome") or cid),
        "lead_time_workdays": lead_workdays or 0,
        "lead_time_days": lead_calendar or 0,
    }


def apply_effective_planning_config(
    engine_data: EngineData,
    config: FactoryConfig | None,
) -> EngineData:
    """Apply user planning rules onto EngineData in-place and return it."""
    if config is None:
        validate_active_twin_eco_lots(engine_data)
        return engine_data

    enforce_machine_scope(config, engine_data)

    companies: dict[str, dict[str, Any]] = {}
    for raw_company in config.subcontract_companies:
        if isinstance(raw_company, dict):
            company = normalize_subcontract_company(raw_company)
            companies[company["id"]] = company

    legacy_subcontract = set(config.subcontract_skus or [])

    _apply_tool_config(engine_data, config)

    for op in engine_data.ops:
        isop_eco = op.eco_lot_isop if op.eco_lot_isop is not None else op.eco_lot
        op.eco_lot_isop = int(isop_eco or 0)

        rule = normalize_sku_planning_rule(
            op.sku,
            config.sku_planning_rules.get(op.sku) or {},
        )
        op.eco_lot = int(rule.get("eco_lot", op.eco_lot_isop))
        op.eco_lot_effective = op.eco_lot
        op.start_buffer_days = int(rule.get("start_buffer_days", 0))
        op.finish_buffer_days = int(rule.get("finish_buffer_days", 0))
        op.min_campaign_qty = rule.get("min_campaign_qty")
        op.min_campaign_prod_min = rule.get("min_campaign_prod_min")
        op.max_group_gap_days = rule.get("max_group_gap_days")
        op.planning_priority = int(rule.get("planning_priority", 0) or 0)

        sub_raw = config.sku_subcontracts.get(op.sku)
        if sub_raw is None and op.sku in legacy_subcontract:
            sub_raw = {"enabled": True}
        sub = normalize_subcontract_rule(op.sku, sub_raw) if sub_raw is not None else {}

        if sub.get("enabled"):
            company_id = sub.get("company_id")
            company = companies.get(company_id or "", {})
            lead = sub.get("lead_time_workdays")
            if lead is None:
                lead = company.get("lead_time_workdays", 0)
            op.subcontract_company_id = company_id
            op.subcontract_lead_time_days = int(lead or 0)
            op.subcontract_buffer_days = int(sub.get("buffer_days", 0))
            op.is_subcontracted = True
        else:
            op.subcontract_company_id = None
            op.subcontract_lead_time_days = 0
            op.subcontract_buffer_days = 0
            op.is_subcontracted = False

    validate_active_twin_eco_lots(engine_data)
    return engine_data


def validate_active_twin_eco_lots(engine_data: EngineData) -> None:
    """Reject active twin pairs whose effective hard lot sizes differ."""

    ops_by_id = {op.id: op for op in engine_data.ops}
    mismatches: list[str] = []
    for twin in engine_data.twin_groups:
        first = ops_by_id.get(twin.op_id_1)
        second = ops_by_id.get(twin.op_id_2)
        if first is None or second is None:
            continue
        first_eco = int(
            first.eco_lot_effective
            if first.eco_lot_effective is not None
            else first.eco_lot
        )
        second_eco = int(
            second.eco_lot_effective
            if second.eco_lot_effective is not None
            else second.eco_lot
        )
        if first_eco != second_eco:
            mismatches.append(
                f"{twin.tool_id}: {first.sku}={first_eco}, "
                f"{second.sku}={second_eco}"
            )

    if mismatches:
        raise ValueError(
            "Definição de peças gémeas incompatível: os eco-lotes efetivos "
            "têm de ser iguais (" + "; ".join(mismatches) + ")."
        )


def effective_internal_deadline_for_op(
    op: Any,
    delivery_day: int,
    holidays: set[int] | None = None,
) -> int:
    """Compatibility accessor for the named internal planning target."""

    return planning_milestones_for_op(op, delivery_day, holidays).internal_target_day


def planning_milestones_for_op(
    op: Any,
    delivery_day: int,
    holidays: set[int] | None = None,
) -> PlanningMilestones:
    """Derive customer, subcontract, production and material milestones.

    Semantic dates may fall before day zero. Day zero is an execution boundary,
    not a valid replacement for an already missed dispatch or release date.
    """

    non_working = holidays or set()
    customer_day = int(delivery_day)
    lead_days = max(0, int(getattr(op, "subcontract_lead_time_days", 0) or 0))
    subcontract_buffer = max(
        0,
        int(getattr(op, "subcontract_buffer_days", 0) or 0),
    )
    finish_buffer = max(0, int(getattr(op, "finish_buffer_days", 0) or 0))
    is_subcontracted = bool(
        getattr(op, "is_subcontracted", False)
        or getattr(op, "subcontract_company_id", None)
        or lead_days
        or subcontract_buffer
    )

    latest_dispatch = (
        _on_or_previous_workday(
            _subtract_workdays(customer_day, lead_days, non_working),
            non_working,
        )
        if is_subcontracted
        else None
    )
    planned_dispatch = (
        _subtract_workdays(latest_dispatch, subcontract_buffer, non_working)
        if latest_dispatch is not None
        else None
    )
    production_due = (
        planned_dispatch
        if planned_dispatch is not None
        else _on_or_previous_workday(customer_day, non_working)
    )
    internal_target = _subtract_workdays(production_due, finish_buffer, non_working)
    material_reference = planned_dispatch if planned_dispatch is not None else customer_day
    reference_kind = "subcontract_dispatch" if planned_dispatch is not None else "customer_delivery"
    material_release = _subtract_workdays(
        material_reference,
        JIT_MAX_ANTICIPATION_WORKDAYS,
        non_working,
    )

    return PlanningMilestones(
        customer_delivery_day=customer_day,
        latest_subcontract_dispatch_day=latest_dispatch,
        subcontract_dispatch_day=planned_dispatch,
        production_due_day=production_due,
        internal_target_day=internal_target,
        material_reference_day=material_reference,
        material_reference_kind=reference_kind,
        material_release_day=material_release,
    )


def _subtract_workdays(day_idx: int, days: int, holidays: set[int]) -> int:
    current = int(day_idx)
    remaining = max(0, int(days))
    while remaining:
        current -= 1
        if current not in holidays:
            remaining -= 1
    return current


def _on_or_previous_workday(day_idx: int, holidays: set[int]) -> int:
    current = int(day_idx)
    while current in holidays:
        current -= 1
    return current


def clean_sku_planning_config(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate a full sku_planning_rules mapping."""
    cleaned: dict[str, dict[str, Any]] = {}
    for sku, rule in (raw or {}).items():
        normalized = normalize_sku_planning_rule(str(sku), rule if isinstance(rule, dict) else {})
        if normalized:
            cleaned[str(sku)] = normalized
    return cleaned


def clean_sku_subcontracts(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate a full sku_subcontracts mapping."""
    cleaned: dict[str, dict[str, Any]] = {}
    for sku, rule in (raw or {}).items():
        if not isinstance(rule, dict):
            continue
        normalized = normalize_subcontract_rule(str(sku), rule)
        if normalized.get("enabled") or len(normalized) > 1:
            cleaned[str(sku)] = normalized
    return cleaned
