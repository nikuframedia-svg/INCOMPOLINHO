"""Policy presets — Spec 12 §7.

Named config profiles for common scheduling scenarios.
"""

from __future__ import annotations

import copy

from backend.config.types import FactoryConfig

PRESETS: dict[str, dict] = {
    "urgente": {
        "jit_enabled": False,
        "urgency_threshold": 2,
        "interleave_enabled": True,
        "lst_safety_buffer": 0,
    },
    "equilibrado": {},  # factory defaults
    "min_setups": {
        "campaign_window": 30,
        "max_edd_gap": 15,
        "edd_swap_tolerance": 10,
    },
    "max_otd": {
        "jit_enabled": True,
        "jit_threshold": 80.0,
        "lst_safety_buffer": 3,
        "urgency_threshold": 3,
    },
}

PRESET_OWNED_FIELDS: set[str] = {
    key for overrides in PRESETS.values() for key in overrides
}


def list_presets() -> list[str]:
    """Return available preset names."""
    return list(PRESETS.keys())


def get_preset(name: str) -> dict:
    """Return override dict for a preset. Raises KeyError if unknown."""
    if name not in PRESETS:
        raise KeyError(f"Preset desconhecido: {name!r}. Disponíveis: {list_presets()}")
    return PRESETS[name].copy()


def apply_preset(
    config: FactoryConfig,
    name: str,
    base_config: FactoryConfig | None = None,
) -> FactoryConfig:
    """Return a copy of config with preset-owned scheduling fields applied.

    Presets are scheduling/scoring profiles. They must not wipe persistent
    user/master-data choices such as subcontract_skus, machine/tool changes,
    twins, holidays, operators, or shifts.
    """
    overrides = get_preset(name)
    result = copy.deepcopy(config)
    if base_config is not None:
        for key in PRESET_OWNED_FIELDS:
            if hasattr(result, key) and hasattr(base_config, key):
                setattr(result, key, copy.deepcopy(getattr(base_config, key)))
    for key, value in overrides.items():
        if not hasattr(result, key):
            raise KeyError(f"FactoryConfig não tem atributo {key!r}")
        setattr(result, key, value)
    return result
