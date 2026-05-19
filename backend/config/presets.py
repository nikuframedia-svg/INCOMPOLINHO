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
        "compact_enabled": True,
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


def list_presets() -> list[str]:
    """Return available preset names."""
    return list(PRESETS.keys())


def get_preset(name: str) -> dict:
    """Return override dict for a preset. Raises KeyError if unknown."""
    if name not in PRESETS:
        raise KeyError(f"Preset desconhecido: {name!r}. Disponíveis: {list_presets()}")
    return PRESETS[name].copy()


def apply_preset(config: FactoryConfig, name: str) -> FactoryConfig:
    """Return a copy of config with preset overrides applied."""
    overrides = get_preset(name)
    result = copy.deepcopy(config)
    for key, value in overrides.items():
        if not hasattr(result, key):
            raise KeyError(f"FactoryConfig não tem atributo {key!r}")
        setattr(result, key, value)
    return result
