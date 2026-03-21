"""Quick Validate — port of analysis/quick-validate.ts.

Fast sanity checks on a schedule: tool uniqueness,
setup crew overlap, and machine overcapacity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..constants import DAY_CAP
from ..types import Block, EMachine, ETool


@dataclass
class QuickValidateResult:
    critical_count: int = 0
    high_count: int = 0
    warnings: list[str] = field(default_factory=list)


def quick_validate(
    blocks: list[Block],
    machines: list[EMachine],
    tool_map: dict[str, ETool],
) -> QuickValidateResult:
    """Quick sanity checks on a schedule.

    Checks:
    1. Tool Uniqueness — same tool on 2+ machines at the same time
    2. Setup Crew Overlap — 2+ setups on different machines simultaneously
    3. Machine Overcapacity — total load > DAY_CAP per day
    """
    critical_count = 0
    high_count = 0
    warnings: list[str] = []
    ok_blocks = [b for b in blocks if b.type == "ok"]

    # ── Check 1: Tool Uniqueness (same tool on 2+ machines, overlapping) ──
    tool_by_m: dict[str, list[dict]] = {}
    for b in ok_blocks:
        if b.tool_id not in tool_by_m:
            tool_by_m[b.tool_id] = []
        tool_by_m[b.tool_id].append({
            "m": b.machine_id,
            "s": b.day_idx * 1440 + (b.setup_s if b.setup_s is not None else b.start_min),
            "e": b.day_idx * 1440 + b.end_min,
        })

    for tid, slots in tool_by_m.items():
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                if slots[i]["m"] == slots[j]["m"]:
                    continue
                if slots[i]["s"] < slots[j]["e"] and slots[j]["s"] < slots[i]["e"]:
                    critical_count += 1
                    warnings.append(
                        f"{tid} em {slots[i]['m']} e {slots[j]['m']} ao mesmo tempo"
                    )

    # ── Check 2: Setup Crew Overlap (2+ setups on different machines simultaneously) ──
    setups: list[dict] = []
    for b in ok_blocks:
        if b.setup_s is not None and b.setup_e is not None:
            setups.append({
                "s": b.day_idx * 1440 + b.setup_s,
                "e": b.day_idx * 1440 + b.setup_e,
                "m": b.machine_id,
                "t": b.tool_id,
            })

    for i in range(len(setups)):
        for j in range(i + 1, len(setups)):
            if setups[i]["m"] == setups[j]["m"]:
                continue
            if setups[i]["s"] < setups[j]["e"] and setups[j]["s"] < setups[i]["e"]:
                high_count += 1
                warnings.append(
                    f"Setups sobrepostos: {setups[i]['t']}/{setups[i]['m']} "
                    f"∩ {setups[j]['t']}/{setups[j]['m']}"
                )

    # ── Check 3: Machine Overcapacity (>DAY_CAP min/day) ──
    m_day_load: dict[str, float] = {}
    for b in ok_blocks:
        key = f"{b.machine_id}:{b.day_idx}"
        dur = b.end_min - b.start_min
        if b.setup_s is not None and b.setup_e is not None:
            dur += b.setup_e - b.setup_s
        m_day_load[key] = m_day_load.get(key, 0) + dur

    for key, load in m_day_load.items():
        if round(load) > DAY_CAP:
            high_count += 1
            mid, di = key.split(":")
            warnings.append(
                f"{mid} excede capacidade dia {di} ({round(load)}/{DAY_CAP}min)"
            )

    return QuickValidateResult(
        critical_count=critical_count,
        high_count=high_count,
        warnings=warnings,
    )
