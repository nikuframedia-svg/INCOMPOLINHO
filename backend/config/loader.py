"""Factory config loader — Spec 09."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from .planning import (
    clean_sku_planning_config,
    clean_sku_subcontracts,
    normalize_subcontract_company,
)
from .types import FactoryConfig, MachineConfig, ShiftConfig

DEFAULT_CONFIG_PATH = "config/factory.yaml"


def _parse_time(t: str) -> int:
    """Parse HH:MM to minutes from midnight. '00:00' → 1440 (end of day)."""
    h, m = t.split(":")
    mins = int(h) * 60 + int(m)
    return mins if mins > 0 else 1440


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
        result.append({"sku": sku, "machine": machine, "hours": float(hours)})
    return result


def _normalize_unavailability(raw, operators: bool = False) -> list[dict]:
    """Normalize unavailability entries.

    machines/tools: {id, resource, from, to, reason}
    operators:      {id, group, shift, from, to, count, reason}
    Date strings stay as-is (validated in validate_config).
    """
    result: list[dict] = []
    for idx, entry in enumerate(raw or []):
        if not isinstance(entry, dict):
            continue
        base = {
            "id": str(entry.get("id") or f"u{idx + 1}"),
            "from": str(entry.get("from", "")),
            "to": str(entry.get("to", entry.get("from", ""))),
            "reason": str(entry.get("reason", "")),
        }
        if operators:
            base["group"] = str(entry.get("group", ""))
            base["shift"] = str(entry.get("shift", ""))
            base["count"] = int(entry.get("count", 1))
        else:
            base["resource"] = str(entry.get("resource", ""))
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
        config.shifts = [
            ShiftConfig(
                id=s["id"],
                start_min=_parse_time(s["start"]),
                end_min=_parse_time(s["end"]),
                label=s.get("label", ""),
            )
            for s in shifts_raw
        ]

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
                    ops[(group, shift_id)] = count
        if ops:
            config.operators = ops

    # Setup crews
    config.setup_crews = raw.get("setup_crews", config.setup_crews)

    # Holidays
    holidays_raw = raw.get("holidays", [])
    if holidays_raw:
        config.holidays = holidays_raw

    # Extra workdays (force-open specific weekend dates)
    config.extra_workdays = [str(d) for d in raw.get("extra_workdays", []) or []]

    # Unavailability calendars
    unavail = raw.get("unavailability", {}) or {}
    config.machine_unavailability = _normalize_unavailability(unavail.get("machines"))
    config.tool_unavailability = _normalize_unavailability(unavail.get("tools"))
    config.operator_unavailability = _normalize_unavailability(
        unavail.get("operators"), operators=True
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

    # Scheduler
    sched = raw.get("scheduler", {})
    if sched:
        config.earliness_policy = sched.get("earliness_policy", config.earliness_policy)
        config.material_release_days = sched.get(
            "material_release_days", config.material_release_days
        )
        config.early_window_enforcement = sched.get(
            "early_window_enforcement", config.early_window_enforcement
        )
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
            config.jit_enabled = jit.get("enabled", config.jit_enabled)
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

    return config


def _min_to_time(mins: int) -> str:
    """Convert minutes from midnight to HH:MM string. 420 → '07:00', 1440 → '00:00'."""
    if mins >= 1440:
        mins = 0
    return f"{mins // 60:02d}:{mins % 60:02d}"


def save_config(config: FactoryConfig, path: str = DEFAULT_CONFIG_PATH) -> None:
    """Serialize FactoryConfig back to YAML."""
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
        "setup_crews": config.setup_crews,
        "holidays": config.holidays,
        "extra_workdays": config.extra_workdays,
        "unavailability": {
            "machines": config.machine_unavailability,
            "tools": config.tool_unavailability,
            "operators": config.operator_unavailability,
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
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _valid_iso_date(value: str) -> date | None:
    """Parse an ISO date string; None if invalid."""
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def validate_config(config: FactoryConfig) -> list[str]:
    """Validate config. Returns list of errors (empty = valid)."""
    errors: list[str] = []

    # Shifts
    if not config.shifts:
        errors.append("Nenhum turno definido")
    if config.day_capacity_min <= 0:
        errors.append(f"DAY_CAP = {config.day_capacity_min} (deve ser > 0)")

    # Machines
    if config.machines:
        active = [m for m in config.machines.values() if m.active]
        if not active:
            errors.append("Nenhuma máquina activa")
    if config.productivity_earliness_ceiling_days < 0:
        errors.append("productivity_earliness_ceiling_days deve ser >= 0")

    # Tools: primary machine must exist
    if config.machines and config.tools:
        for tid, tdata in config.tools.items():
            primary = tdata.get("primary", "")
            if primary and primary not in config.machines:
                errors.append(f"Ferramenta {tid}: máquina primária {primary} não existe")
            alt = tdata.get("alt")
            if alt and alt not in config.machines:
                errors.append(f"Ferramenta {tid}: máquina alternativa {alt} não existe")

    # Twins must be pairs
    for tid, skus in config.twins.items():
        if len(skus) != 2:
            errors.append(f"Twin {tid}: deve ter 2 SKUs, tem {len(skus)}")

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

    # Setup crews
    if config.setup_crews != 1:
        errors.append(
            f"Setup crews = {config.setup_crews}; a Incompol tem exatamente 1 equipa de setup"
        )

    # Earliness policy / material window
    if config.earliness_policy not in {"jit", "window"}:
        errors.append(f"earliness_policy '{config.earliness_policy}' inválida (jit|window)")
    if config.early_window_enforcement not in {"off", "soft", "hard"}:
        errors.append(
            f"early_window_enforcement '{config.early_window_enforcement}' "
            "inválido (off|soft|hard)"
        )
    if not isinstance(config.material_release_days, int) or config.material_release_days < 0:
        errors.append("material_release_days deve ser um inteiro >= 0")

    # Setup overrides
    for ov in config.setup_overrides:
        sku, machine, hours = ov.get("sku"), ov.get("machine"), ov.get("hours", 0)
        if config.machines and machine not in config.machines:
            errors.append(f"Setup override {sku}: máquina {machine} não existe")
        if not 0 < float(hours) <= 8:
            errors.append(f"Setup override {sku}@{machine}: horas {hours} fora do range (0, 8]")

    # Per-machine OEE
    for mid, m in config.machines.items():
        if m.oee is not None and not 0.1 <= m.oee <= 1.0:
            errors.append(f"Máquina {mid}: OEE {m.oee} fora do range 0.1-1.0")

    # Calendar entries (dates + ranges)
    for label, entries in (
        ("unavailability.machines", config.machine_unavailability),
        ("unavailability.tools", config.tool_unavailability),
        ("unavailability.operators", config.operator_unavailability),
    ):
        for entry in entries:
            d_from = _valid_iso_date(entry.get("from", ""))
            d_to = _valid_iso_date(entry.get("to", ""))
            if d_from is None or d_to is None:
                errors.append(f"{label} {entry.get('id')}: datas inválidas")
                continue
            if d_from > d_to:
                errors.append(f"{label} {entry.get('id')}: 'from' posterior a 'to'")
            if label == "unavailability.machines":
                res = entry.get("resource", "")
                if config.machines and res not in config.machines:
                    errors.append(f"{label} {entry.get('id')}: máquina {res} não existe")
            if label == "unavailability.operators" and int(entry.get("count", 0)) < 1:
                errors.append(f"{label} {entry.get('id')}: count deve ser >= 1")

    for d in config.extra_workdays:
        if _valid_iso_date(str(d)) is None:
            errors.append(f"extra_workdays: data inválida '{d}'")

    return errors
