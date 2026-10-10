"""Idempotency cache — Spec 12 §8.

Hash EngineData + config → cache key. Same input → cached ScheduleResult.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict

from backend.config.types import FactoryConfig
from backend.scheduler.types import ScheduleResult
from backend.types import EngineData

_cache: OrderedDict[str, ScheduleResult] = OrderedDict()
_MAX_CACHE = 8


def _hash_input(data: EngineData, config: FactoryConfig | None = None) -> str:
    """Deterministic hash of scheduling inputs."""
    parts: list[str] = []

    # Hash ops (sorted by id for determinism)
    for op in sorted(data.ops, key=lambda o: o.id):
        parts.append(f"{op.id}|{op.m}|{op.pH}|{op.eco_lot}|{op.stk}|{tuple(op.d)}")

    # Hash machines
    for m in sorted(data.machines, key=lambda m: m.id):
        parts.append(f"M:{m.id}|{m.group}|{m.day_capacity}")

    # Hash twin groups
    for tg in data.twin_groups:
        parts.append(f"TG:{tg.tool_id}|{tg.machine_id}|{tg.op_id_1},{tg.op_id_2}")

    parts.append(f"n_days:{data.n_days}")
    parts.append(f"holidays:{sorted(data.holidays)}")

    # Hash config tunables that affect scheduling
    if config:
        parts.append(
            f"cfg:{config.jit_enabled}|{config.jit_threshold}|{config.lst_safety_buffer}|"
            f"{config.campaign_window}|{config.urgency_threshold}|{config.max_edd_gap}|"
            f"{config.edd_swap_tolerance}|{config.interleave_enabled}|{config.max_edd_span}"
        )

    raw = "\n".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached(data: EngineData, config: FactoryConfig | None = None) -> ScheduleResult | None:
    """Return cached result if input matches, else None."""
    key = _hash_input(data, config)
    return _cache.get(key)


def put_cache(
    data: EngineData,
    config: FactoryConfig | None,
    result: ScheduleResult,
) -> None:
    """Store result. Evicts oldest if over _MAX_CACHE."""
    key = _hash_input(data, config)
    _cache[key] = result
    while len(_cache) > _MAX_CACHE:
        _cache.popitem(last=False)


def clear_cache() -> None:
    """Clear all cached results."""
    _cache.clear()
