"""CTP — Capable to Promise — Spec 03 §2.

"Can we fit N more pieces of SKU X by day D?"
Uses REAL capacity (DAY_CAP - minutes already used in segments).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP, DEFAULT_OEE
from backend.scheduler.types import Segment
from backend.types import EngineData


@dataclass(slots=True)
class CTPResult:
    feasible: bool
    sku: str
    qty_requested: int
    latest_day: int | None        # latest day to START production (JIT)
    earliest_end_day: int | None  # earliest day production can END
    machine: str | None
    confidence: str               # "high" | "medium" | "low"
    slack_min: float
    reason: str | None
    date_start: str | None = None  # real date of latest_day
    date_end: str | None = None    # real date of earliest_end_day
    required_min: float = 0.0      # total minutes needed (setup + prod)
    prod_days: int = 0             # number of production days needed


def compute_ctp(
    sku: str,
    qty: int,
    deadline_day: int,
    segments: list[Segment],
    engine_data: EngineData,
    config: FactoryConfig | None = None,
) -> CTPResult:
    """CTP based on REAL free capacity from schedule segments."""
    day_cap = config.day_capacity_min if config else DAY_CAP
    oee_default = config.oee_default if config else DEFAULT_OEE
    workdays = getattr(engine_data, "workdays", []) or []

    def _day_to_date(d: int) -> str | None:
        """Map day index to real date string."""
        if 0 <= d < len(workdays):
            return workdays[d]
        return None

    def _fail(reason: str, machine: str | None = None) -> CTPResult:
        return CTPResult(
            feasible=False, sku=sku, qty_requested=qty,
            latest_day=None, earliest_end_day=None,
            machine=machine, confidence="low",
            slack_min=0, reason=reason,
        )

    # Find op for SKU
    op = next((o for o in engine_data.ops if o.sku == sku), None)
    if op is None:
        return _fail(f"SKU {sku} não encontrado")

    if op.pH <= 0:
        return _fail("pH = 0, cadência desconhecida", machine=op.m)

    oee = op.oee or oee_default
    setup_min = op.sH * 60
    prod_min = (qty / op.pH) * 60 / oee
    required_min = setup_min + prod_min
    prod_days_needed = max(1, math.ceil(required_min / day_cap))

    # Build used capacity per (machine, day) from segments
    # Include buffer days (negative day_idx)
    cap_used: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for seg in segments:
        cap_used[seg.machine_id][seg.day_idx] += seg.prod_min + seg.setup_min

    n_days = engine_data.n_days
    holidays = set(engine_data.holidays)

    # Determine scan range: include buffer days (negative indices from segments)
    min_day = 0
    for seg in segments:
        if seg.day_idx < min_day:
            min_day = seg.day_idx

    def _find_slot(machine_id: str) -> tuple[int | None, int | None]:
        """Scan backwards from deadline, accumulate free capacity (JIT).

        Returns (start_day, end_day) or (None, None).
        """
        accumulated = 0.0
        start_day = None
        for d in range(min(deadline_day, n_days - 1), min_day - 1, -1):
            if d in holidays:
                continue
            used = cap_used.get(machine_id, {}).get(d, 0)
            free = max(0, day_cap - used)
            accumulated += free
            if accumulated >= required_min:
                start_day = d
                break

        if start_day is None:
            return None, None

        # Find end day: scan forward from start, accumulate until required_min
        acc = 0.0
        end_day = start_day
        for d in range(start_day, min(deadline_day + 1, n_days)):
            if d in holidays:
                continue
            used = cap_used.get(machine_id, {}).get(d, 0)
            free = max(0, day_cap - used)
            acc += free
            end_day = d
            if acc >= required_min:
                break

        return start_day, end_day

    # Try primary machine, then alternative
    machines = [op.m]
    if op.alt:
        machines.append(op.alt)

    for machine in machines:
        start_day, end_day = _find_slot(machine)
        if start_day is not None and start_day <= deadline_day:
            # Total free capacity from slot start to deadline
            total_free = 0.0
            for d in range(start_day, min(deadline_day + 1, n_days)):
                if d in holidays:
                    continue
                used = cap_used.get(machine, {}).get(d, 0)
                total_free += max(0, day_cap - used)
            slack = total_free - required_min
            confidence = (
                "high" if slack > day_cap * 0.3
                else "medium" if slack > day_cap * 0.1
                else "low"
            )
            return CTPResult(
                feasible=True, sku=sku, qty_requested=qty,
                latest_day=start_day, earliest_end_day=end_day,
                machine=machine,
                confidence=confidence, slack_min=max(0, slack),
                reason=None,
                date_start=_day_to_date(start_day),
                date_end=_day_to_date(end_day) if end_day is not None else None,
                required_min=round(required_min, 1),
                prod_days=prod_days_needed,
            )

    return _fail(f"Sem capacidade em {' ou '.join(machines)} até dia {deadline_day}")
