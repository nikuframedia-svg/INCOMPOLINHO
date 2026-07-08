"""Operator alerts — Spec 02 §8.

Advisory only: never blocks scheduling.
Counts operators per (day, shift, machine_group), alerts if over capacity.
"""

from __future__ import annotations

from backend.config.types import FactoryConfig
from backend.scheduler.constants import MACHINE_GROUP, OPERATOR_CAP
from backend.scheduler.types import OperatorAlert, Segment
from backend.types import EngineData


def compute_operator_alerts(
    segments: list[Segment],
    engine_data: EngineData,
    config: FactoryConfig | None = None,
) -> list[OperatorAlert]:
    """Check operator demand vs shift capacity.

    Groups segments by (day, machine_group, shift).
    Alert if count > capacity.
    """
    machine_group = config.machine_groups if config else MACHINE_GROUP
    operator_cap = dict(config.operators) if config else OPERATOR_CAP

    alerts: list[OperatorAlert] = []

    # Count distinct machines per (day, group, shift) — 1 machine = 1 operator
    machines_seen: dict[tuple[int, str, str], set[str]] = {}
    for seg in segments:
        if seg.setup_min > 0 and seg.qty == 0:
            continue  # pure setup block, crew handles it
        group = machine_group.get(seg.machine_id, "Grandes")
        shift = seg.shift
        key = (seg.day_idx, group, shift)
        if key not in machines_seen:
            machines_seen[key] = set()
        machines_seen[key].add(seg.machine_id)

    counts: dict[tuple[int, str, str], int] = {k: len(v) for k, v in machines_seen.items()}

    for (day_idx, group, shift), required in counts.items():
        cap = operator_cap.get((group, shift), 6)
        if required > cap:
            date = ""
            if day_idx < len(engine_data.workdays):
                date = engine_data.workdays[day_idx]
            alerts.append(
                OperatorAlert(
                    day_idx=day_idx,
                    date=date,
                    shift=shift,
                    machine_group=group,
                    required=required,
                    available=cap,
                    deficit=required - cap,
                )
            )

    return sorted(alerts, key=lambda a: (a.day_idx, a.machine_group, a.shift))
