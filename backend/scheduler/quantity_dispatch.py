"""Allocate material portions without changing the persisted production lots."""

from __future__ import annotations

import copy
from dataclasses import replace

from backend.planning_control import planning_checkpoint
from backend.scheduler.alternative_repair import _schedule_run_earliest
from backend.scheduler.lot_sizing import _aggregate_milestones
from backend.scheduler.priority import lot_priority_key
from backend.scheduler.resources import clone_run_for_machine
from backend.scheduler.types import ToolRun
from backend.scheduler.validation import assert_plan_valid


def has_quantity_releases(lots):
    return any(
        not lot.is_twin
        and len({output.get("material_release_day") for output in lot.output_milestones or []}) > 1
        for lot in lots
    )


def _run(lot, identity):
    return ToolRun(
        id=identity,
        tool_id=lot.tool_id,
        machine_id=lot.machine_id,
        alt_machine_id=lot.alt_machine_id,
        lots=[lot],
        setup_min=lot.setup_min,
        total_prod_min=lot.prod_min,
        total_min=lot.prod_min + lot.setup_min,
        edd=lot.edd,
    )


def schedule_quantity_releases(lots, data, config):
    """Schedule released portions in commercial order, using the shared allocator.

    Temporary portions are never returned as new lots. Each economic lot keeps
    one chosen machine, its full quantity, and its original delivery identity.
    Different portions have distinct physical runs so reinstalls are explicit.
    """
    originals = {lot.id: copy.deepcopy(lot) for lot in lots}
    portions = []
    for lot in lots:
        outputs = lot.output_milestones or []
        if lot.is_twin or len(outputs) <= 1:
            portions.append((copy.deepcopy(lot), lot.id, 0))
            continue
        for index, output in enumerate(outputs):
            qty = int(output["qty"])
            portion = replace(lot, qty=qty, prod_min=lot.prod_min * qty / lot.qty)
            for field, value in _aggregate_milestones([output]).items():
                setattr(portion, field, value)
            portion.edd = int(output["production_due_day"])
            portion.original_edd = int(output["customer_delivery_day"])
            portion.delivery_day = portion.original_edd
            portion.internal_deadline = int(output["internal_target_day"])
            portions.append((portion, lot.id, index))

    active = {
        machine.id
        for machine in data.machines
        if machine.id not in config.machines or config.machines[machine.id].active
    }
    chosen_lots = {}
    cursors = {}
    segments = []
    for portion, parent_id, index in sorted(
        portions, key=lambda item: (lot_priority_key(item[0]), item[2])
    ):
        planning_checkpoint()
        original = originals[parent_id]
        machines = (
            [chosen_lots[parent_id].machine_id]
            if parent_id in chosen_lots
            else list(
                dict.fromkeys(
                    m for m in (original.machine_id, original.alt_machine_id) if m in active
                )
            )
        )
        best = None
        for machine in machines:
            planning_checkpoint()
            parent = clone_run_for_machine(_run(original, parent_id), machine, data, config).lots[0]
            parent.machine_id = machine
            trial = copy.deepcopy(portion)
            trial.prod_min = parent.prod_min * trial.qty / parent.qty
            trial.setup_min = parent.setup_min
            trial.machine_id = machine
            run = _run(trial, f"quantity:{parent_id}:{index}")
            scheduled = _schedule_run_earliest(
                run,
                machine,
                segments,
                data,
                config,
                not_before_abs=cursors.get(parent_id),
            )
            if scheduled is None:
                continue
            _allocated_run, created = scheduled
            rank = (
                min(s.day_idx * 1440 + s.production_start_min for s in created if s.prod_min > 0),
                max(s.day_idx * 1440 + s.end_min for s in created),
                machine,
            )
            if best is None or rank < best[0]:
                best = (rank, parent, created)
        if best is None:
            raise ValueError(
                f"Nao foi possivel alocar as quantidades libertadas do lote {parent_id}."
            )
        rank, parent, created = best
        chosen_lots[parent_id] = parent
        cursors[parent_id] = rank[1]
        # Integer clock slots can round a portion up. Preserve exact productive
        # minutes as well as pieces; the extra fraction remains reserved time.
        productive = sum(s.prod_min for s in created)
        expected = parent.prod_min * portion.qty / parent.qty
        for segment in created:
            segment.prod_min *= expected / productive
            segment.lot_qty = parent.qty
            segment.output_milestones = copy.deepcopy(parent.output_milestones)
            for field in (
                "edd",
                "original_edd",
                "delivery_day",
                "internal_deadline",
                "customer_delivery_day",
                "production_due_day",
                "internal_target_day",
                "material_reference_day",
                "material_release_day",
            ):
                setattr(segment, field, getattr(parent, field))
        segments.extend(created)

    result_lots = [chosen_lots[lot.id] for lot in lots]
    segments.sort(key=lambda s: (s.day_idx, s.start_min, s.machine_id))
    assert_plan_valid(segments, data, config, lots=result_lots)
    return segments, result_lots
