"""CTP (Capable-to-Promise) based on REAL schedule block capacity.

Unlike RCCP-based CTP, this uses actual free minutes per machine/day
computed from the scheduled blocks — no theoretical 300% utilisation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from ..constants import DAY_CAP, DEFAULT_OEE


@dataclass
class CTPRealResult:
    """Result of a real-capacity CTP check."""

    feasible: bool
    machine: str
    earliest_day: int | None
    required_min: float
    free_min_on_target: float
    confidence: str  # "high" | "medium" | "low"
    reason: str
    alt_machine: str | None = None
    alt_earliest_day: int | None = None


def compute_ctp_real(
    sku: str,
    qty: int,
    deadline_day: int,
    blocks: list[Any],
    engine_data: Any,
) -> CTPRealResult:
    """CTP based on REAL free capacity from schedule blocks."""
    # Find the op and tool for this SKU
    op = next((o for o in engine_data.ops if o.sku == sku), None)
    if not op:
        return CTPRealResult(
            feasible=False,
            machine="",
            earliest_day=None,
            required_min=0,
            free_min_on_target=0,
            confidence="low",
            reason=f"SKU {sku} não encontrado",
        )

    tool = engine_data.tool_map.get(op.t)
    if not tool:
        return CTPRealResult(
            feasible=False,
            machine=op.m,
            earliest_day=None,
            required_min=0,
            free_min_on_target=0,
            confidence="low",
            reason=f"Ferramenta {op.t} não encontrada",
        )

    pH = tool.pH
    if pH <= 0:
        return CTPRealResult(
            feasible=False,
            machine=tool.m,
            earliest_day=None,
            required_min=0,
            free_min_on_target=0,
            confidence="low",
            reason="pH = 0, cadência desconhecida",
        )

    oee = tool.oee or DEFAULT_OEE
    setup_min = tool.sH * 60
    prod_min = (qty / pH * 60) / oee
    required = setup_min + prod_min

    # Build used capacity per machine per day
    cap_used: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for b in blocks:
        if getattr(b, "type", "ok") == "ok":
            cap_used[b.machine_id][b.day_idx] += b.prod_min + b.setup_min

    n_days = engine_data.n_days
    workdays = engine_data.workdays

    def _find_slot(machine_id: str) -> int | None:
        """Scan backwards from deadline, accumulate free capacity (JIT)."""
        accumulated = 0.0
        for d in range(min(deadline_day, n_days - 1), -1, -1):
            if d < len(workdays) and not workdays[d]:
                continue
            used = cap_used.get(machine_id, {}).get(d, 0)
            free = max(0, DAY_CAP - used)
            accumulated += free
            if accumulated >= required:
                return d
        return None

    free_on_target = max(
        0, DAY_CAP - cap_used.get(tool.m, {}).get(min(deadline_day, n_days - 1), 0)
    )

    # Try primary machine
    primary_day = _find_slot(tool.m)

    if primary_day is not None and primary_day <= deadline_day:
        slack = free_on_target - required
        confidence = (
            "high" if slack > DAY_CAP * 0.3 else "medium" if slack > DAY_CAP * 0.1 else "low"
        )
        return CTPRealResult(
            feasible=True,
            machine=tool.m,
            earliest_day=primary_day,
            required_min=round(required, 1),
            free_min_on_target=round(free_on_target, 1),
            confidence=confidence,
            reason="Capacidade disponível na máquina primária",
        )

    # Try alt machine
    alt = tool.alt if tool.alt and tool.alt != "-" else None
    if alt:
        alt_day = _find_slot(alt)
        if alt_day is not None and alt_day <= deadline_day:
            alt_free = max(0, DAY_CAP - cap_used.get(alt, {}).get(min(deadline_day, n_days - 1), 0))
            return CTPRealResult(
                feasible=True,
                machine=alt,
                earliest_day=alt_day,
                required_min=round(required, 1),
                free_min_on_target=round(alt_free, 1),
                confidence="medium",
                reason="Capacidade disponível na máquina alternativa",
                alt_machine=alt,
                alt_earliest_day=alt_day,
            )

    # Not feasible
    best_day = primary_day
    reason = (
        f"Primeiro dia possível: {best_day}"
        if best_day is not None
        else "Sem capacidade suficiente no horizonte"
    )
    return CTPRealResult(
        feasible=False,
        machine=tool.m,
        earliest_day=best_day,
        required_min=round(required, 1),
        free_min_on_target=round(free_on_target, 1),
        confidence="low",
        reason=reason,
        alt_machine=alt,
    )
