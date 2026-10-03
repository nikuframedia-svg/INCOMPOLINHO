"""ISOP context extraction — Spec 08 §2."""

from __future__ import annotations

from backend.calendar import available_machine_capacity
from backend.config.types import PLANNING_POLICY_VERSION, FactoryConfig
from backend.scheduler.constants import DEFAULT_OEE
from backend.types import EngineData

from .types import ISContext


def extract_context(data: EngineData, config: FactoryConfig | None = None) -> ISContext:
    """Extract feature vector from an ISOP for transfer learning."""
    oee_default = config.oee_default if config else DEFAULT_OEE

    n_ops = len(data.ops)
    n_machines = len(data.machines)
    n_days = data.n_days

    # Total demand (sum of positive d values = actual demand)
    total_demand = 0
    demand_days: list[int] = []
    for op in data.ops:
        for day_idx, d in enumerate(op.d):
            if d > 0:
                total_demand += d
                demand_days.append(day_idx)

    # Average OEE
    oees = [op.oee for op in data.ops if op.oee and op.oee > 0]
    avg_oee = sum(oees) / len(oees) if oees else oee_default

    # Twin fraction
    twin_op_ids: set[str] = set()
    for tg in data.twin_groups:
        twin_op_ids.add(tg.op_id_1)
        twin_op_ids.add(tg.op_id_2)
    twin_pct = len(twin_op_ids) / max(n_ops, 1)

    # Alt machine fraction
    alt_count = sum(1 for op in data.ops if op.alt)
    alt_pct = alt_count / max(n_ops, 1)

    # Average EDD (day index of demands)
    avg_edd = sum(demand_days) / len(demand_days) if demand_days else 0.0

    # Demand density: total load in minutes / total capacity
    total_load_min = 0.0
    for op in data.ops:
        oee = op.oee if op.oee and op.oee > 0 else oee_default
        ph = max(op.pH, 1)
        op_demand = sum(max(0, d) for d in op.d)
        total_load_min += (op_demand / ph / oee) * 60.0

    total_capacity = sum(
        available_machine_capacity(machine.id, day_idx, data, config)
        for machine in data.machines
        for day_idx in range(n_days)
    )
    demand_density = total_load_min / total_capacity if total_capacity > 0 else 0.0

    return ISContext(
        n_ops=n_ops,
        n_machines=n_machines,
        n_days=n_days,
        total_demand=total_demand,
        avg_oee=round(avg_oee, 3),
        twin_pct=round(twin_pct, 3),
        alt_pct=round(alt_pct, 3),
        avg_edd=round(avg_edd, 1),
        demand_density=round(demand_density, 4),
        planning_policy_version=PLANNING_POLICY_VERSION,
    )
