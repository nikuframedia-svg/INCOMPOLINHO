"""Factory config loader — Spec 09."""

from __future__ import annotations

import os
import tempfile
from dataclasses import fields
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from backend.validation import finite_float, strict_bool, strict_int

from .planning import (
    clean_sku_planning_config,
    clean_sku_subcontracts,
    enforce_machine_scope,
    normalize_subcontract_company,
)
from .types import (
    JIT_EARLINESS_POLICY,
    JIT_MAX_ANTICIPATION_WORKDAYS,
    JIT_WINDOW_ENFORCEMENT,
    OUT_OF_SCOPE_MACHINES,
    FactoryConfig,
    MachineConfig,
    ShiftConfig,
)

DEFAULT_CONFIG_PATH = os.environ.get("PP1_CONFIG_PATH", "config/factory.yaml")


def _parse_time(t: str, *, end_of_day: bool = False) -> int:
    """Parse ``HH:MM`` while disambiguating midnight starts and ends."""
    h, m = t.split(":")
    mins = int(h) * 60 + int(m)
    return 1440 if end_of_day and mins == 0 else mins


def _normalize_setup_overrides(raw) -> list[dict]:
    """Normalize production.setup_overrides entries to {sku, machine, hours}."""
    result: list[dict] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        sku = str(entry.get("sku", "")).strip()
        machine = str(entry.get("machine", "")).strip()
        hours = entry.get("hours")
        if not sku or not machine or hours is None:
            continue
        result.append({"sku": sku, "machine": machine, "hours": finite_float(hours, "setup.hours")})
    return result


def normalize_setup_families(raw) -> dict[str, list[list[str]]]:
    """Normalize compatible setup references by physical tool."""

    if not isinstance(raw, dict):
        return {}
    result: dict[str, list[list[str]]] = {}
    for raw_tool, raw_groups in raw.items():
        tool_id = str(raw_tool).strip()
        if not tool_id or not isinstance(raw_groups, list):
            continue
        groups = [raw_groups] if all(isinstance(item, str) for item in raw_groups) else raw_groups
        normalized_groups: list[list[str]] = []
        for raw_group in groups:
            if not isinstance(raw_group, list):
                continue
            members = sorted(
                {
                    str(member).strip()
                    for member in raw_group
                    if str(member).strip()
                }
            )
            if members:
                normalized_groups.append(members)
        if normalized_groups:
            result[tool_id] = sorted(normalized_groups)
    return result


def _local_iso(value: object, timezone: str, *, end_of_legacy_range: bool = False) -> str:
    """Normalise a date/datetime to an aware ISO timestamp.

    Legacy ``to`` dates were inclusive.  Their migrated end is therefore
    midnight of the following day, which keeps the exact old full-day meaning
    with an end-exclusive interval.
    """

    text = str(value or "").strip()
    if not text:
        return ""
    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    if end_of_legacy_range and len(text) == 10:
        try:
            parsed_date = date.fromisoformat(text) + timedelta(days=1)
            return datetime.combine(parsed_date, time.min, tzinfo=tz).isoformat(
                timespec="minutes"
            )
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError:
            return text
        if end_of_legacy_range:
            parsed_date += timedelta(days=1)
        parsed = datetime.combine(parsed_date, time.min)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz).isoformat(timespec="minutes")


def _normalize_unavailability(
    raw,
    operators: bool = False,
    timezone: str = "Europe/Lisbon",
    kind: str | None = None,
) -> list[dict]:
    """Normalize unavailability entries.

    The persisted/runtime contract is a timezone-aware, end-exclusive timestamp
    interval. Legacy date ranges are migrated once and their aliases are
    deliberately discarded.
    """
    result: list[dict] = []
    entry_kind = kind or ("operator" if operators else "resource")
    for idx, entry in enumerate(raw or []):
        if not isinstance(entry, dict):
            continue
        legacy = not bool(entry.get("start_at"))
        legacy_from = str(entry.get("from", "")).strip()
        legacy_to = str(entry.get("to", "")).strip()
        start_at = _local_iso(
            entry.get("start_at", legacy_from),
            timezone,
        )
        raw_end = entry.get("end_at")
        if raw_end is None and legacy and legacy_to:
            raw_end = legacy_to
        end_at = _local_iso(
            raw_end,
            timezone,
            end_of_legacy_range=legacy and bool(raw_end),
        )
        base = {
            "id": str(entry.get("id") or f"{entry_kind}-u{idx + 1}").strip(),
            "start_at": start_at,
            "end_at": end_at,
            "category": str(entry.get("category") or "Outra"),
            "reason": str(entry.get("reason", "")),
        }
        if operators:
            base["group"] = str(entry.get("group", "")).strip()
            base["shift"] = str(entry.get("shift", "")).strip()
            base["count"] = strict_int(entry.get("count", 1), "count")
        else:
            base["resource"] = str(entry.get("resource", "")).strip()
        result.append(base)
    return result


def load_config(path: str = DEFAULT_CONFIG_PATH) -> FactoryConfig:
    """Load factory YAML. Missing file or sections → defaults (Incompol)."""
    raw: dict = {}
    p = Path(path)
    if p.exists():
        with open(p) as f:
            raw = yaml.safe_load(f) or {}

    config = FactoryConfig()

    # Factory identity
    factory = raw.get("factory", {})
    if factory:
        config.name = factory.get("name", config.name)
        config.site = factory.get("site", config.site)
        config.timezone = factory.get("timezone", config.timezone)

    # Shifts
    shifts_raw = raw.get("shifts", [])
    if shifts_raw:
        config.shifts = sorted([
            ShiftConfig(
                id=s["id"],
                start_min=_parse_time(s["start"]),
                end_min=_parse_time(s["end"], end_of_day=True),
                label=s.get("label", ""),
            )
            for s in shifts_raw
        ], key=lambda shift: (shift.start_min, shift.id))

    # Machines
    for mid, mdata in raw.get("machines", {}).items():
        if isinstance(mdata, dict):
            config.machines[mid] = MachineConfig(
                id=mid,
                group=mdata.get("group", "Grandes"),
                active=mdata.get("active", True),
                day_capacity_min=mdata.get("day_capacity_min"),
                oee=mdata.get("oee"),
            )

    # Tools (merge alt_machines + setup_hours format)
    tools_raw = raw.get("tools", {})
    default_tool = tools_raw.get("_default", {})
    if isinstance(default_tool, dict):
        config.default_setup_hours = default_tool.get(
            "setup_hours",
            config.default_setup_hours,
        )
    for tid, tdata in tools_raw.items():
        if tid == "_default" or not isinstance(tdata, dict):
            continue
        config.tools[tid] = tdata

    # Twins
    twins_raw = raw.get("twins", {})
    if twins_raw:
        config.twins = twins_raw

    # Operators
    operators_raw = raw.get("operators", {})
    if operators_raw:
        ops: dict[tuple[str, str], int] = {}
        for group, shifts in operators_raw.items():
            if isinstance(shifts, dict):
                for shift_id, count in shifts.items():
                    ops[(group, shift_id)] = strict_int(count, f"operators.{group}.{shift_id}")
        if ops:
            config.operators = ops

    # Setup crews.  Old global capacity is intentionally migrated to one crew
    # in every existing group: the factory has independent Grandes/Médias
    # teams, not N interchangeable global teams.
    config.setup_crews = 1
    groups = sorted(set(config.machine_groups.values()))
    raw_by_group = raw.get("setup_crews_by_group")
    if isinstance(raw_by_group, dict) and raw_by_group:
        config.setup_crews_by_group = {
            str(group): strict_int(count, f"setup_crews.{group}")
            for group, count in raw_by_group.items()
        }
    else:
        config.setup_crews_by_group = {group: 1 for group in groups}

    # Holidays
    holidays_raw = raw.get("holidays", [])
    if holidays_raw:
        config.holidays = holidays_raw

    # Extra workdays (force-open specific weekend dates)
    config.extra_workdays = [str(d) for d in raw.get("extra_workdays", []) or []]

    # Unavailability calendars
    unavail = raw.get("unavailability", {}) or {}
    config.machine_unavailability = _normalize_unavailability(
        unavail.get("machines"), timezone=config.timezone, kind="machine"
    )
    config.tool_unavailability = _normalize_unavailability(
        unavail.get("tools"), timezone=config.timezone, kind="tool"
    )
    config.operator_unavailability = _normalize_unavailability(
        unavail.get("operators"),
        operators=True,
        timezone=config.timezone,
        kind="operator",
    )

    # Production
    prod = raw.get("production", {})
    if prod:
        config.oee_default = prod.get("oee_default", config.oee_default)
        config.min_prod_min = prod.get("min_prod_min", config.min_prod_min)
        config.eco_lot_mode = prod.get("eco_lot_mode", config.eco_lot_mode)
        config.subcontract_skus = list(prod.get("subcontract_skus", config.subcontract_skus))
        config.sku_planning_rules = clean_sku_planning_config(
            prod.get("sku_planning_rules", config.sku_planning_rules)
        )
        companies_raw = prod.get("subcontract_companies", config.subcontract_companies)
        config.subcontract_companies = [
            normalize_subcontract_company(c) for c in companies_raw if isinstance(c, dict)
        ]
        config.sku_subcontracts = clean_sku_subcontracts(
            prod.get("sku_subcontracts", config.sku_subcontracts)
        )
        config.setup_overrides = _normalize_setup_overrides(prod.get("setup_overrides"))
        config.setup_families = normalize_setup_families(
            prod.get("setup_families", config.setup_families)
        )

    # Scheduler
    sched = raw.get("scheduler", {})
    if sched:
        # Legacy YAML may still contain the previous soft/window policy.  The
        # five-working-day JIT rule is now an invariant and overrides it.
        config.earliness_policy = JIT_EARLINESS_POLICY
        config.material_release_days = JIT_MAX_ANTICIPATION_WORKDAYS
        config.early_window_enforcement = JIT_WINDOW_ENFORCEMENT
        config.max_run_days = sched.get("max_run_days", config.max_run_days)
        config.max_edd_gap = sched.get("max_edd_gap", config.max_edd_gap)
        config.max_edd_span = sched.get("max_edd_span", config.max_edd_span)
        config.edd_swap_tolerance = sched.get("edd_swap_tolerance", config.edd_swap_tolerance)
        config.edd_assign_threshold = sched.get(
            "edd_assign_threshold",
            config.edd_assign_threshold,
        )
        config.lst_safety_buffer = sched.get("lst_safety_buffer", config.lst_safety_buffer)
        config.campaign_window = sched.get("campaign_window", config.campaign_window)
        config.urgency_threshold = sched.get("urgency_threshold", config.urgency_threshold)
        config.interleave_enabled = sched.get("interleave_enabled", config.interleave_enabled)
        config.auto_buffer = sched.get("auto_buffer", config.auto_buffer)
        config.global_jit_enabled = sched.get(
            "global_jit_enabled",
            config.global_jit_enabled,
        )
        config.global_jit_time_limit_s = finite_float(
            sched.get("global_jit_time_limit_s", config.global_jit_time_limit_s)
        )
        config.vns_enabled = sched.get("vns_enabled", config.vns_enabled)
        config.vns_block_moves_enabled = sched.get(
            "vns_block_moves_enabled",
            config.vns_block_moves_enabled,
        )
        config.vns_max_iter = sched.get("vns_max_iter", config.vns_max_iter)
        config.compact_enabled = sched.get("compact_enabled", config.compact_enabled)
        config.productivity_earliness_ceiling_days = sched.get(
            "productivity_earliness_ceiling_days",
            config.productivity_earliness_ceiling_days,
        )

        jit = sched.get("jit", {})
        if jit:
            config.jit_enabled = True
            config.jit_buffer_pct = jit.get("buffer_pct", config.jit_buffer_pct)
            config.jit_threshold = jit.get("threshold", config.jit_threshold)
            config.jit_max_retries = jit.get("max_retries", config.jit_max_retries)
            config.jit_earliness_target = jit.get("earliness_target", config.jit_earliness_target)

    # Scoring
    scoring = raw.get("scoring", {})
    if scoring:
        weights = scoring.get("weights", {})
        if weights:
            config.weight_earliness = weights.get("earliness", config.weight_earliness)
            config.weight_setups = weights.get("setups", config.weight_setups)
            config.weight_balance = weights.get("utilization_balance", config.weight_balance)

    # Risk
    risk = raw.get("risk", {})
    if risk:
        oee_dist = risk.get("oee_distribution", {})
        if oee_dist:
            config.risk_oee_alpha = oee_dist.get("alpha", config.risk_oee_alpha)
            config.risk_oee_beta = oee_dist.get("beta", config.risk_oee_beta)
        config.risk_setup_cv = risk.get("setup_cv", config.risk_setup_cv)
        config.risk_processing_cv = risk.get("processing_cv", config.risk_processing_cv)

    normalize_config_numbers(config)
    enforce_machine_scope(config)
    return config


def normalize_config_numbers(config: FactoryConfig) -> None:
    """Normalize only numeric syntax; validate_config owns the domain limits."""
    for item in fields(FactoryConfig):
        parse = {"int": strict_int, "float": finite_float, "bool": strict_bool}.get(item.type)
        if parse is not None:
            setattr(config, item.name, parse(getattr(config, item.name), item.name))
    for shift in config.shifts:
        shift.start_min = strict_int(shift.start_min, f"{shift.id}.start_min")
        shift.end_min = strict_int(shift.end_min, f"{shift.id}.end_min")
    for machine in config.machines.values():
        if machine.oee is not None:
            machine.oee = finite_float(machine.oee, f"{machine.id}.oee")
        if machine.day_capacity_min is not None:
            machine.day_capacity_min = strict_int(
                machine.day_capacity_min, f"{machine.id}.day_capacity_min"
            )
    config.operators = {
        key: strict_int(value, f"operators.{key}") for key, value in config.operators.items()
    }
    config.setup_crews_by_group = {
        key: strict_int(value, f"setup_crews.{key}")
        for key, value in config.setup_crews_by_group.items()
    }
    for tool_id, tool in config.tools.items():
        if "setup_hours" in tool:
            tool["setup_hours"] = finite_float(tool["setup_hours"], f"{tool_id}.setup_hours")
    for entry in config.setup_overrides:
        entry["hours"] = finite_float(entry.get("hours"), "setup.hours")
    for entry in config.operator_unavailability:
        entry["count"] = strict_int(entry.get("count", 1), "unavailability.count")


def _min_to_time(mins: int | float) -> str:
    """Convert an in-day minute to ``HH:MM`` without lossy wrapping."""
    rounded_mins = int(round(float(mins)))
    if not 0 <= rounded_mins <= 1440:
        raise ValueError(f"Minuto fora do dia: {rounded_mins}")
    if rounded_mins == 1440:
        rounded_mins = 0
    return f"{rounded_mins // 60:02d}:{rounded_mins % 60:02d}"


def save_config(config: FactoryConfig, path: str = DEFAULT_CONFIG_PATH) -> None:
    """Serialize FactoryConfig back to YAML."""
    from backend.plans.context import is_staging
    from backend.runtime_guard import assert_writable

    if is_staging():
        return
    assert_writable(path)
    machine_unavailability = _normalize_unavailability(
        config.machine_unavailability,
        timezone=config.timezone,
        kind="machine",
    )
    tool_unavailability = _normalize_unavailability(
        config.tool_unavailability,
        timezone=config.timezone,
        kind="tool",
    )
    operator_unavailability = _normalize_unavailability(
        config.operator_unavailability,
        operators=True,
        timezone=config.timezone,
        kind="operator",
    )
    data = {
        "factory": {"name": config.name, "site": config.site, "timezone": config.timezone},
        "shifts": [
            {
                "id": s.id,
                "start": _min_to_time(s.start_min),
                "end": _min_to_time(s.end_min),
                "label": s.label,
            }
            for s in config.shifts
        ],
        "machines": {
            mid: {
                "group": m.group,
                "active": m.active,
                "day_capacity_min": m.day_capacity_min,
                "oee": m.oee,
            }
            for mid, m in config.machines.items()
        },
        "tools": {"_default": {"setup_hours": config.default_setup_hours}, **config.tools},
        "twins": config.twins,
        "operators": {
            group: {shift: count for (g, shift), count in config.operators.items() if g == group}
            for group in sorted(set(g for g, _ in config.operators))
        },
        "setup_crews_by_group": config.setup_crews_by_group,
        "holidays": config.holidays,
        "extra_workdays": config.extra_workdays,
        "unavailability": {
            "machines": machine_unavailability,
            "tools": tool_unavailability,
            "operators": operator_unavailability,
        },
        "production": {
            "oee_default": config.oee_default,
            "eco_lot_mode": config.eco_lot_mode,
            "min_prod_min": config.min_prod_min,
            "subcontract_skus": config.subcontract_skus,
            "sku_planning_rules": config.sku_planning_rules,
            "subcontract_companies": config.subcontract_companies,
            "sku_subcontracts": config.sku_subcontracts,
            "setup_overrides": config.setup_overrides,
            "setup_families": config.setup_families,
        },
        "scheduler": {
            "earliness_policy": config.earliness_policy,
            "material_release_days": config.material_release_days,
            "early_window_enforcement": config.early_window_enforcement,
            "max_run_days": config.max_run_days,
            "max_edd_gap": config.max_edd_gap,
            "max_edd_span": config.max_edd_span,
            "edd_swap_tolerance": config.edd_swap_tolerance,
            "edd_assign_threshold": config.edd_assign_threshold,
            "lst_safety_buffer": config.lst_safety_buffer,
            "campaign_window": config.campaign_window,
            "urgency_threshold": config.urgency_threshold,
            "interleave_enabled": config.interleave_enabled,
            "auto_buffer": config.auto_buffer,
            "global_jit_enabled": config.global_jit_enabled,
            "global_jit_time_limit_s": config.global_jit_time_limit_s,
            "vns_enabled": config.vns_enabled,
            "vns_block_moves_enabled": config.vns_block_moves_enabled,
            "vns_max_iter": config.vns_max_iter,
            "compact_enabled": config.compact_enabled,
            "productivity_earliness_ceiling_days": config.productivity_earliness_ceiling_days,
            "jit": {
                "enabled": config.jit_enabled,
                "buffer_pct": config.jit_buffer_pct,
                "threshold": config.jit_threshold,
                "max_retries": config.jit_max_retries,
                "earliness_target": config.jit_earliness_target,
            },
        },
        "scoring": {
            "weights": {
                "earliness": config.weight_earliness,
                "setups": config.weight_setups,
                "utilization_balance": config.weight_balance,
            },
        },
        "risk": {
            "oee_distribution": {
                "type": "beta",
                "alpha": config.risk_oee_alpha,
                "beta": config.risk_oee_beta,
            },
            "setup_cv": config.risk_setup_cv,
            "processing_cv": config.risk_processing_cv,
        },
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            yaml.dump(
                data,
                temporary,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _valid_iso_datetime(value: str, timezone: str) -> datetime | None:
    """Parse an ISO date/datetime and attach the factory timezone if needed."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        try:
            parsed = datetime.combine(date.fromisoformat(str(value)), time.min)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return parsed


def validate_config(config: FactoryConfig, engine_data: object | None = None) -> list[str]:
    """Validate config. Returns list of errors (empty = valid)."""
    errors: list[str] = []
    try:
        normalize_config_numbers(config)
    except ValueError as exc:
        message = str(exc)
        return [
            message.replace("deve ser inteiro.", "deve ser inteiro >= 0.")
            if message.startswith("operators.")
            else message
        ]
    timezone = str(config.timezone or "").strip()
    try:
        ZoneInfo(timezone)
        calendar_timezone = timezone
    except (ZoneInfoNotFoundError, ValueError):
        errors.append(f"Timezone IANA inválido: {timezone or '(vazio)'}")
        calendar_timezone = "UTC"

    # Shifts
    if not config.shifts:
        errors.append("Nenhum turno definido")
    if config.day_capacity_min <= 0:
        errors.append(f"DAY_CAP = {config.day_capacity_min} (deve ser > 0)")
    seen_shift_ids: set[str] = set()
    previous_end = -1
    for shift in sorted(config.shifts, key=lambda item: item.start_min):
        if not shift.id or shift.id in seen_shift_ids:
            errors.append(f"Turno repetido ou sem ID: {shift.id!r}")
        seen_shift_ids.add(shift.id)
        if not 0 <= shift.start_min < 1440:
            errors.append(f"Turno {shift.id}: início fora do dia")
        if shift.end_min <= shift.start_min:
            errors.append(f"Turno {shift.id}: início deve ser anterior ao fim")
        if shift.end_min > 1440:
            errors.append(f"Turno {shift.id}: fim deve estar no mesmo dia")
        if shift.start_min < previous_end:
            errors.append(f"Turno {shift.id}: sobrepõe-se ao turno anterior")
        previous_end = max(previous_end, shift.end_min)

    # Machines
    for machine_id in OUT_OF_SCOPE_MACHINES & config.machines.keys():
        errors.append(f"{machine_id} está fora do âmbito da análise")
    if config.machines:
        active = [m for m in config.machines.values() if m.active]
        if not active:
            errors.append("Nenhuma máquina activa")
        for machine in active:
            if (
                machine.day_capacity_min is not None
                and machine.day_capacity_min != config.day_capacity_min
            ):
                errors.append(
                    f"Máquina {machine.id}: day_capacity_min específico "
                    "é incompatível com o calendário comum; usa null para herdar turnos"
                )
    for tool_id, tool in config.tools.items():
        if isinstance(tool, dict) and any(
            tool.get(field) in OUT_OF_SCOPE_MACHINES for field in ("primary", "alt")
        ):
            errors.append(f"Ferramenta {tool_id}: PRM020 está fora do âmbito da análise")
    if config.productivity_earliness_ceiling_days < 0:
        errors.append("productivity_earliness_ceiling_days deve ser >= 0")
    if config.min_prod_min <= 0:
        errors.append("min_prod_min deve ser > 0")
    if not 0 <= config.default_setup_hours <= 8:
        errors.append("default_setup_hours deve estar no range [0, 8]")
    if config.eco_lot_mode not in {"hard", "soft"}:
        errors.append("eco_lot_mode deve ser 'hard' ou 'soft'")

    # Scheduler numeric domains. Invalid values otherwise reach deep arithmetic
    # and can produce empty windows, negative retries or nonsensical scores.
    for field_name in ("max_run_days", "max_edd_span"):
        if int(getattr(config, field_name)) < 1:
            errors.append(f"{field_name} deve ser >= 1")
    for field_name in (
        "max_edd_gap",
        "edd_swap_tolerance",
        "edd_assign_threshold",
        "lst_safety_buffer",
        "campaign_window",
        "urgency_threshold",
        "jit_max_retries",
        "vns_max_iter",
        "robustness_reserve_workdays",
    ):
        if int(getattr(config, field_name)) < 0:
            errors.append(f"{field_name} deve ser >= 0")
    if not 0 <= config.jit_buffer_pct <= 1:
        errors.append("jit_buffer_pct deve estar no range [0, 1]")
    if not 0 <= config.jit_threshold <= 100:
        errors.append("jit_threshold deve estar no range [0, 100]")
    if config.jit_earliness_target < 0:
        errors.append("jit_earliness_target deve ser >= 0")
    if config.global_jit_time_limit_s <= 0:
        errors.append("global_jit_time_limit_s deve ser > 0")
    if config.risk_oee_alpha <= 0 or config.risk_oee_beta <= 0:
        errors.append("Parâmetros beta do OEE devem ser > 0")
    if config.risk_setup_cv < 0 or config.risk_processing_cv < 0:
        errors.append("Coeficientes de variação de risco devem ser >= 0")

    # Tools: primary machine must exist
    if config.machines and config.tools:
        for tid, tdata in config.tools.items():
            primary = tdata.get("primary", "")
            if primary and primary not in config.machines:
                errors.append(f"Ferramenta {tid}: máquina primária {primary} não existe")
            alt = tdata.get("alt")
            if alt and alt not in config.machines:
                errors.append(f"Ferramenta {tid}: máquina alternativa {alt} não existe")
            try:
                setup_hours = float(
                    tdata.get("setup_hours", config.default_setup_hours)
                )
            except (TypeError, ValueError):
                errors.append(f"Ferramenta {tid}: setup_hours deve ser um número")
            else:
                if not 0 <= setup_hours <= 8:
                    errors.append(
                        f"Ferramenta {tid}: setup_hours {setup_hours} "
                        "fora do range [0, 8]"
                    )

    # Twin definitions are a factory catalog: a pair becomes active only when
    # both references exist in the current ISOP. Validate catalog structure
    # unconditionally, then enforce physical compatibility for active pairs.
    engine_ops = list(getattr(engine_data, "ops", [])) if engine_data is not None else []
    twin_known_tools = set(config.tools) | {str(op.t) for op in engine_ops}
    for tid, skus in config.twins.items():
        if len(skus) != 2:
            errors.append(f"Twin {tid}: deve ter 2 SKUs, tem {len(skus)}")
            continue
        sku_a, sku_b = (str(sku).strip() for sku in skus)
        if not sku_a or not sku_b or sku_a == sku_b:
            errors.append(f"Twin {tid}: os 2 SKUs devem ser distintos e não vazios")
            continue
        if not engine_ops:
            continue
        matches_a = [op for op in engine_ops if op.sku == sku_a]
        matches_b = [op for op in engine_ops if op.sku == sku_b]
        if not matches_a or not matches_b:
            continue
        if len(matches_a) != 1 or len(matches_b) != 1:
            errors.append(
                f"Twin {tid}: cada SKU deve ter uma operação única "
                f"({sku_a}={len(matches_a)}, {sku_b}={len(matches_b)})"
            )
            continue
        if tid not in twin_known_tools:
            errors.append(f"Twin {tid}: ferramenta não existe")
        op_a, op_b = matches_a[0], matches_b[0]
        if op_a.t != tid or op_b.t != tid:
            errors.append(f"Twin {tid}: ambos os SKUs devem usar esta ferramenta")
        common_machines = {
            machine for machine in (op_a.m, op_a.alt) if machine
        } & {machine for machine in (op_b.m, op_b.alt) if machine}
        if not common_machines:
            errors.append(f"Twin {tid}: os SKUs não têm uma máquina comum")

    # Scoring weights should sum to ~1.0
    w_sum = config.weight_earliness + config.weight_setups + config.weight_balance
    if abs(w_sum - 1.0) > 0.01:
        errors.append(f"Scoring weights somam {w_sum:.2f}, deviam somar 1.0")

    # OEE range
    if not 0.1 <= config.oee_default <= 1.0:
        errors.append(f"OEE default {config.oee_default} fora do range 0.1-1.0")

    # Planning rules
    try:
        clean_sku_planning_config(config.sku_planning_rules)
        clean_sku_subcontracts(config.sku_subcontracts)
        for company in config.subcontract_companies:
            if isinstance(company, dict):
                normalize_subcontract_company(company)
    except ValueError as exc:
        errors.append(str(exc))

    # Setup crews are independent cumulative resources per machine group.
    if config.setup_crews != 1:
        errors.append(
            f"Setup crews global = {config.setup_crews}; o campo antigo aceita exatamente 1"
        )
    configured_groups = set(config.machine_groups.values())
    missing_groups = configured_groups - set(config.setup_crews_by_group)
    if missing_groups:
        errors.append(
            "Faltam equipas de setup para: " + ", ".join(sorted(missing_groups))
        )
    for group, count in config.setup_crews_by_group.items():
        try:
            crew_count = int(count)
        except (TypeError, ValueError):
            crew_count = 0
        if crew_count < 1:
            errors.append(f"Equipas de setup {group}: deve ser >= 1")

    # Every active machine group needs an explicit, non-negative headcount for
    # every shift. Missing keys must never turn into implicit capacity.
    known_shift_ids = {shift.id for shift in config.shifts}
    valid_operator_keys: set[tuple[str, str]] = set()
    for key, count in config.operators.items():
        if not isinstance(key, tuple) or len(key) != 2:
            errors.append(f"Operadores: chave inválida {key!r}")
            continue
        group, shift_id = str(key[0]), str(key[1])
        valid_operator_keys.add((group, shift_id))
        if shift_id not in known_shift_ids:
            errors.append(f"Operadores: turno desconhecido {shift_id}")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            errors.append(
                f"Operadores {group}/{shift_id}: deve ser um inteiro >= 0"
            )
    missing_operator_keys = {
        (group, shift_id)
        for group in configured_groups
        for shift_id in known_shift_ids
    } - valid_operator_keys
    if missing_operator_keys:
        errors.append(
            "Faltam operadores para: "
            + ", ".join(
                f"{group}/{shift_id}"
                for group, shift_id in sorted(missing_operator_keys)
            )
        )

    # Earliness policy / material window
    if config.earliness_policy != JIT_EARLINESS_POLICY:
        errors.append("earliness_policy é uma regra industrial fixa: 'jit'")
    if config.early_window_enforcement != JIT_WINDOW_ENFORCEMENT:
        errors.append("early_window_enforcement é uma regra industrial fixa: 'hard'")
    if config.material_release_days != JIT_MAX_ANTICIPATION_WORKDAYS:
        errors.append("material_release_days é uma regra industrial fixa: 5 dias úteis")
    if not config.jit_enabled:
        errors.append("jit_enabled é uma regra industrial fixa: true")

    # Setup overrides
    for ov in config.setup_overrides:
        sku, machine, hours = ov.get("sku"), ov.get("machine"), ov.get("hours", 0)
        if config.machines and machine not in config.machines:
            errors.append(f"Setup override {sku}: máquina {machine} não existe")
        if not 0 < float(hours) <= 8:
            errors.append(f"Setup override {sku}@{machine}: horas {hours} fora do range (0, 8]")

    # Setup families are explicit exceptions to the default one-adjustment-per-SKU rule.
    setup_memberships: set[tuple[str, str]] = set()
    setup_known_tools = set(config.tools) | {
        str(op.t) for op in getattr(engine_data, "ops", [])
    }
    for tool_id, groups in config.setup_families.items():
        if setup_known_tools and tool_id not in setup_known_tools:
            errors.append(f"Família de afinação {tool_id}: ferramenta não existe")
        for members in groups:
            if len(members) < 2:
                errors.append(
                    f"Família de afinação {tool_id}: deve ter pelo menos 2 SKUs"
                )
                continue
            for sku in members:
                membership = (tool_id, sku)
                if membership in setup_memberships:
                    errors.append(
                        f"Família de afinação {tool_id}: SKU {sku} aparece em mais de um grupo"
                    )
                setup_memberships.add(membership)
                matching_ops = [
                    op for op in getattr(engine_data, "ops", []) if op.sku == sku
                ]
                if matching_ops and any(op.t != tool_id for op in matching_ops):
                    errors.append(
                        f"Família de afinação {tool_id}: SKU {sku} usa outra ferramenta"
                    )

    # Per-machine OEE
    for mid, m in config.machines.items():
        if m.oee is not None and not 0.1 <= m.oee <= 1.0:
            errors.append(f"Máquina {mid}: OEE {m.oee} fora do range 0.1-1.0")

    # Calendar entries. IDs are public mutation handles, so they must be unique
    # across all resource kinds rather than only inside one YAML list.
    calendar_ids: set[str] = set()
    operator_ranges: dict[tuple[str, str], list[tuple[datetime, datetime, int, str]]] = {}
    known_tools = set(config.tools)
    if engine_data is not None:
        known_tools.update(str(getattr(op, "t", "")) for op in getattr(engine_data, "ops", []))
    known_groups = set(config.machine_groups.values()) | {
        str(key[0])
        for key in config.operators
        if isinstance(key, tuple) and len(key) == 2
    }
    known_shifts = {shift.id for shift in config.shifts}
    for label, entries in (
        ("unavailability.machines", config.machine_unavailability),
        ("unavailability.tools", config.tool_unavailability),
        ("unavailability.operators", config.operator_unavailability),
    ):
        for entry in entries:
            entry_id = str(entry.get("id", "")).strip()
            if not entry_id:
                errors.append(f"{label}: ID obrigatório")
            elif entry_id in calendar_ids:
                errors.append(f"Indisponibilidade com ID repetido: {entry_id}")
            else:
                calendar_ids.add(entry_id)
            if entry.get("start_at") and ("from" in entry or "to" in entry):
                errors.append(
                    f"{label} {entry_id}: não misturar start_at/end_at com from/to"
                )
            legacy = bool(entry.get("from")) and not entry.get("start_at")
            has_open_end = False
            d_from: datetime | None = None
            d_to: datetime | None = None
            if legacy:
                try:
                    legacy_from = date.fromisoformat(str(entry.get("from", "")))
                    legacy_to = date.fromisoformat(str(entry.get("to", "")))
                except (TypeError, ValueError):
                    errors.append(f"{label} {entry.get('id')}: datas inválidas")
                    continue
                if legacy_from > legacy_to:
                    errors.append(f"{label} {entry.get('id')}: 'from' posterior a 'to'")
                tz = ZoneInfo(calendar_timezone)
                d_from = datetime.combine(legacy_from, time.min, tzinfo=tz)
                d_to = datetime.combine(legacy_to + timedelta(days=1), time.min, tzinfo=tz)
            else:
                start_at = entry.get("start_at", entry.get("from", ""))
                end_at = entry.get("end_at", entry.get("to", ""))
                has_open_end = not bool(end_at)
                d_from = _valid_iso_datetime(start_at, calendar_timezone)
                d_to = _valid_iso_datetime(end_at, calendar_timezone) if end_at else None
                if d_from is None or (end_at and d_to is None):
                    errors.append(f"{label} {entry.get('id')}: data/hora inválida")
                    continue
                if d_to is not None and d_from >= d_to:
                    errors.append(f"{label} {entry.get('id')}: início deve ser anterior ao fim")
            category = str(entry.get("category", "Outra"))
            if category not in {"Avaria", "Manutenção", "Ensaio", "Outra"}:
                errors.append(f"{label} {entry.get('id')}: categoria inválida")
            if has_open_end and label != "unavailability.machines":
                errors.append(f"{label} {entry.get('id')}: fim obrigatório")
            if label == "unavailability.machines":
                res = str(entry.get("resource", "")).strip()
                if config.machines and res not in config.machines:
                    errors.append(f"{label} {entry.get('id')}: máquina {res} não existe")
            elif label == "unavailability.tools":
                res = str(entry.get("resource", "")).strip()
                if not res:
                    errors.append(f"{label} {entry_id}: ferramenta obrigatória")
                elif known_tools and res not in known_tools:
                    errors.append(f"{label} {entry_id}: ferramenta {res} não existe")
            else:
                group = str(entry.get("group", "")).strip()
                shift_id = str(entry.get("shift", "")).strip()
                try:
                    count = int(entry.get("count", 0))
                except (TypeError, ValueError):
                    count = 0
                if group not in known_groups:
                    errors.append(f"{label} {entry_id}: grupo {group or '(vazio)'} não existe")
                if shift_id not in known_shifts or (group, shift_id) not in config.operators:
                    errors.append(
                        f"{label} {entry_id}: grupo/turno {group} {shift_id} não existe"
                    )
                if count < 1:
                    errors.append(f"{label} {entry_id}: count deve ser >= 1")
                try:
                    base = int(config.operators.get((group, shift_id), 0))
                except (TypeError, ValueError):
                    base = 0
                if count > base:
                    errors.append(
                        f"{label} {entry_id}: count {count} excede equipa {base}"
                    )
                if d_from is not None and d_to is not None and shift_id in known_shifts:
                    shift_cfg = next(shift for shift in config.shifts if shift.id == shift_id)
                    clipped_ranges: list[tuple[datetime, datetime]] = []
                    cursor = d_from.date()
                    last = (d_to - timedelta(microseconds=1)).date()
                    tz = ZoneInfo(calendar_timezone)
                    while cursor <= last:
                        shift_start = datetime.combine(cursor, time.min, tzinfo=tz) + timedelta(
                            minutes=shift_cfg.start_min
                        )
                        shift_end = datetime.combine(cursor, time.min, tzinfo=tz) + timedelta(
                            minutes=shift_cfg.end_min
                        )
                        clipped_start = max(d_from, shift_start)
                        clipped_end = min(d_to, shift_end)
                        if clipped_start < clipped_end:
                            clipped_ranges.append((clipped_start, clipped_end))
                        cursor += timedelta(days=1)
                    if not clipped_ranges:
                        errors.append(
                            f"{label} {entry_id}: intervalo não toca no turno {shift_id}"
                        )
                    operator_ranges.setdefault((group, shift_id), []).extend(
                        (start, end, max(0, count), entry_id)
                        for start, end in clipped_ranges
                    )

    for (group, shift_id), ranges in operator_ranges.items():
        events: list[tuple[datetime, int, str]] = []
        for start, end, count, entry_id in ranges:
            events.extend(((start, count, entry_id), (end, -count, entry_id)))
        unavailable = 0
        try:
            base = int(config.operators.get((group, shift_id), 0))
        except (TypeError, ValueError):
            base = 0
        for instant, delta, entry_id in sorted(
            events,
            key=lambda item: (item[0], item[1] > 0),
        ):
            unavailable += delta
            if unavailable > base:
                errors.append(
                    f"Ausências {group}/{shift_id} excedem equipa {base} em "
                    f"{instant.isoformat(timespec='minutes')} (inclui {entry_id})"
                )
                break

    for field_name, values in (
        ("holidays", config.holidays),
        ("extra_workdays", config.extra_workdays),
    ):
        for value in values:
            try:
                valid_date = date.fromisoformat(str(value))
            except (TypeError, ValueError):
                valid_date = None
            if valid_date is None:
                errors.append(f"{field_name}: data inválida '{value}'")

    return errors
