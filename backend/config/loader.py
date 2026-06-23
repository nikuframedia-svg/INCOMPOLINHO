"""Factory config loader — Spec 09."""

from __future__ import annotations

from pathlib import Path

import yaml

from .types import FactoryConfig, MachineConfig, ShiftConfig

DEFAULT_CONFIG_PATH = "config/factory.yaml"


def _parse_time(t: str) -> int:
    """Parse HH:MM to minutes from midnight. '00:00' → 1440 (end of day)."""
    h, m = t.split(":")
    mins = int(h) * 60 + int(m)
    return mins if mins > 0 else 1440


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
            )

    # Tools (merge alt_machines + setup_hours format)
    tools_raw = raw.get("tools", {})
    default_tool = tools_raw.get("_default", {})
    if isinstance(default_tool, dict):
        config.default_setup_hours = default_tool.get(
            "setup_hours", config.default_setup_hours,
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

    # Production
    prod = raw.get("production", {})
    if prod:
        config.oee_default = prod.get("oee_default", config.oee_default)
        config.min_prod_min = prod.get("min_prod_min", config.min_prod_min)
        config.eco_lot_mode = prod.get("eco_lot_mode", config.eco_lot_mode)

    subcontract_raw = raw.get("subcontract_skus", {})
    if isinstance(subcontract_raw, dict):
        config.subcontract_skus = {
            str(sku): max(0, int(days))
            for sku, days in subcontract_raw.items()
        }

    # Scheduler
    sched = raw.get("scheduler", {})
    if sched:
        config.max_run_days = sched.get("max_run_days", config.max_run_days)
        config.max_edd_gap = sched.get("max_edd_gap", config.max_edd_gap)
        config.edd_swap_tolerance = sched.get("edd_swap_tolerance", config.edd_swap_tolerance)
        config.lst_safety_buffer = sched.get("lst_safety_buffer", config.lst_safety_buffer)
        config.campaign_window = sched.get("campaign_window", config.campaign_window)
        config.urgency_threshold = sched.get("urgency_threshold", config.urgency_threshold)
        config.interleave_enabled = sched.get("interleave_enabled", config.interleave_enabled)
        config.auto_buffer = sched.get("auto_buffer", config.auto_buffer)

        jit = sched.get("jit", {})
        if jit:
            config.jit_enabled = jit.get("enabled", config.jit_enabled)
            config.jit_buffer_pct = jit.get("buffer_pct", config.jit_buffer_pct)
            config.jit_threshold = jit.get("threshold", config.jit_threshold)
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
            {"id": s.id, "start": _min_to_time(s.start_min),
             "end": _min_to_time(s.end_min), "label": s.label}
            for s in config.shifts
        ],
        "machines": {
            mid: {"group": m.group, "active": m.active,
                  "day_capacity_min": m.day_capacity_min}
            for mid, m in config.machines.items()
        },
        "tools": {"_default": {"setup_hours": config.default_setup_hours},
                  **config.tools},
        "twins": config.twins,
        "operators": {
            group: {shift: count for (g, shift), count in config.operators.items() if g == group}
            for group in sorted(set(g for g, _ in config.operators))
        },
        "setup_crews": config.setup_crews,
        "holidays": config.holidays,
        "production": {
            "oee_default": config.oee_default,
            "eco_lot_mode": config.eco_lot_mode,
            "min_prod_min": config.min_prod_min,
        },
        "subcontract_skus": dict(sorted(config.subcontract_skus.items())),
        "scheduler": {
            "max_run_days": config.max_run_days,
            "max_edd_gap": config.max_edd_gap,
            "edd_swap_tolerance": config.edd_swap_tolerance,
            "lst_safety_buffer": config.lst_safety_buffer,
            "campaign_window": config.campaign_window,
            "urgency_threshold": config.urgency_threshold,
            "interleave_enabled": config.interleave_enabled,
            "auto_buffer": config.auto_buffer,
            "jit": {
                "enabled": config.jit_enabled,
                "buffer_pct": config.jit_buffer_pct,
                "threshold": config.jit_threshold,
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

    for sku, lead_days in config.subcontract_skus.items():
        if not sku:
            errors.append("Subcontrato: SKU vazio")
        if lead_days < 0:
            errors.append(f"Subcontrato {sku}: lead_days {lead_days} deve ser >= 0")

    # Setup crews
    if config.setup_crews < 1:
        errors.append(f"Setup crews = {config.setup_crews} (mínimo 1)")

    return errors
