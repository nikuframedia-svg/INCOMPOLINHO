"""Machine-dependent resource resolution — Fase 1.2.

Setup hours and OEE are baked into lots at creation time (Phase 1, lot_sizing)
BEFORE the machine is chosen (Phase 3, assign_machines). With per-(sku, machine)
setup overrides and per-machine OEE, those values depend on the CHOSEN machine,
so they must be re-resolved ("rebound") at assignment time.

`rebind_runs_to_machines` is an absolute, idempotent recompute: every value is
a pure function of (lot, chosen machine, config, engine_data). Rebinding the
same objects again — with the same or a different machine — always yields the
same result as a single rebind. This matters because ToolRun/Lot objects are
shared across CPO chromosomes and VNS candidates.

Known limitation: optimizer-internal neighborhoods that move a run across
machines without calling `clone_run_for_machine` keep the previous machine's
values until the next rebind. Physics gates still validate the result; the
drift only affects override/per-machine-OEE deltas, never the defaults.

Resolution chains:
  setup:  (sku, machine) override → live per-tool op.sH → default_setup_hours
  oee:    what-if per-tool (op.oee_source == "whatif") → machine.oee →
          op.oee (master) → oee_default
Twins: one physical setup per run — the worst (max) of the two SKUs governs.
"""

from __future__ import annotations

import copy
import math

from backend.config.types import FactoryConfig
from backend.scheduler.types import Lot, ToolRun
from backend.types import EngineData, EOp


def build_setup_override_map(config: FactoryConfig) -> dict[tuple[str, str], float]:
    """Precompute {(sku, machine): hours} from config.setup_overrides."""
    return {
        (ov["sku"], ov["machine"]): float(ov["hours"])
        for ov in config.setup_overrides
        if isinstance(ov, dict) and "sku" in ov and "machine" in ov
    }


def reserved_setup_segments(data):
    """Read-only crew occupancy of protected lots in a residual calculation."""
    from backend.scheduler.types import Segment

    return [Segment(
        str(block["id"]), str(block["id"]), block["machine_id"], block["tool_id"],
        int(block["start_day"]), int(block["start_min"]), math.ceil(block["end_min"]),
        "", 0, 0, setup_min=float(block["end_min"] - block["start_min"]),
    ) for block in data.setup_crew_reservations] if data is not None else []


def resolve_setup_hours(
    sku: str,
    machine_id: str,
    fallback_hours: float,
    config: FactoryConfig,
    override_map: dict[tuple[str, str], float] | None = None,
) -> float:
    """Setup hours for producing `sku` on `machine_id`."""
    if override_map is None:
        override_map = build_setup_override_map(config)
    hours = override_map.get((sku, machine_id))
    if hours is not None:
        return hours
    if fallback_hours is not None:
        return fallback_hours
    return config.default_setup_hours


def effective_oee(op: EOp, machine_id: str, config: FactoryConfig) -> float:
    """OEE for running `op` on `machine_id` (see resolution chain above)."""
    if getattr(op, "oee_source", "default") == "whatif" and op.oee:
        return op.oee
    machine = config.machines.get(machine_id) if config.machines else None
    if machine is not None and machine.oee is not None:
        return machine.oee
    return op.oee or config.oee_default


def _machine_dependent_config(config: FactoryConfig | None) -> bool:
    """True when any config value can differ per chosen machine."""
    if config is None:
        return False
    if config.setup_overrides:
        return True
    return any(m.oee is not None for m in config.machines.values())


def rebind_runs_to_machines(
    machine_runs: dict[str, list[ToolRun]],
    engine_data: EngineData,
    config: FactoryConfig | None,
) -> dict[str, list[ToolRun]]:
    """Re-resolve setup/OEE of every run against its assigned (dict-key) machine.

    Mutates lots/runs in place (absolute recompute — idempotent). Fast no-op
    when nothing in the config is machine-dependent, which keeps the historical
    pipeline byte-identical.
    """
    if not _machine_dependent_config(config):
        return machine_runs

    ops_by_id = {op.id: op for op in engine_data.ops}
    override_map = build_setup_override_map(config)
    for machine_id, runs in machine_runs.items():
        for run in runs:
            _rebind_run(run, machine_id, ops_by_id, config, override_map)
    return machine_runs


def clone_run_for_machine(
    run: ToolRun,
    machine_id: str,
    engine_data: EngineData,
    config: FactoryConfig | None,
) -> ToolRun:
    """Clone a run (and its lots) rebound to `machine_id`.

    Used by cross-machine moves on shared candidate structures (VNS): the
    original object may still live inside sibling candidates and must not be
    mutated.
    """
    new_lots = []
    for lot in run.lots:
        new_lot = copy.copy(lot)
        if new_lot.twin_outputs is not None:
            new_lot.twin_outputs = list(new_lot.twin_outputs)
        if new_lot.output_milestones is not None:
            new_lot.output_milestones = [
                dict(item) for item in new_lot.output_milestones
            ]
        new_lots.append(new_lot)
    new_run = copy.copy(run)
    new_run.lots = new_lots
    new_run.machine_id = machine_id

    if _machine_dependent_config(config):
        ops_by_id = {op.id: op for op in engine_data.ops}
        _rebind_run(new_run, machine_id, ops_by_id, config, build_setup_override_map(config))
    return new_run


def _rebind_run(
    run: ToolRun,
    machine_id: str,
    ops_by_id: dict[str, EOp],
    config: FactoryConfig,
    override_map: dict[tuple[str, str], float],
) -> None:
    min_prod = config.min_prod_min
    for lot in run.lots:
        op = ops_by_id.get(lot.op_id)
        if op is None:
            continue
        if lot.is_twin and lot.twin_outputs:
            _rebind_twin_lot(lot, op, machine_id, ops_by_id, config, override_map, min_prod)
        else:
            lot.setup_min = (
                resolve_setup_hours(op.sku, machine_id, op.sH, config, override_map) * 60.0
            )
            oee = effective_oee(op, machine_id, config)
            if op.pH > 0 and oee > 0:
                lot.prod_min = max(min_prod, (lot.qty / (op.pH * oee)) * 60.0)
            else:
                lot.prod_min = min_prod
    if run.lots:
        run.setup_min = max(lot.setup_min for lot in run.lots)
    run.total_prod_min = sum(lot.prod_min for lot in run.lots)
    run.total_min = run.setup_min + run.total_prod_min


def _rebind_twin_lot(
    lot: Lot,
    primary_op: EOp,
    machine_id: str,
    ops_by_id: dict[str, EOp],
    config: FactoryConfig,
    override_map: dict[tuple[str, str], float],
    min_prod: float,
) -> None:
    """Twin lot: one physical setup (max of the two SKUs) + max production time."""
    setup_hours: list[float] = []
    times: list[float] = []
    for op_id, sku, qty in lot.twin_outputs or []:
        op = ops_by_id.get(op_id, primary_op)
        setup_hours.append(resolve_setup_hours(sku, machine_id, op.sH, config, override_map))
        oee = effective_oee(op, machine_id, config)
        if qty > 0 and op.pH > 0 and oee > 0:
            times.append((qty / (op.pH * oee)) * 60.0)
    lot.setup_min = (max(setup_hours) if setup_hours else primary_op.sH) * 60.0
    lot.prod_min = max(min_prod, max(times) if times else 0.0)
