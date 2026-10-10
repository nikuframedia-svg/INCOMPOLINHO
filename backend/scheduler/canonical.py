"""Reconcile scheduled lots with scenario inputs, not with their own metadata."""

from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict

from backend.config.types import FactoryConfig
from backend.planning_control import execution_cache
from backend.plans.serialize import schedule_fingerprint
from backend.scheduler.lot_sizing import _aggregate_milestones, create_lots
from backend.scheduler.resources import build_setup_override_map, effective_oee, resolve_setup_hours
from backend.scheduler.setup_identity import segment_setup_identity
from backend.types import CommittedSupply

# Version of the per-delivery material contract written on each lot output
# (``quantity_material_version``) and recorded in the planning model identity.
QUANTITY_MATERIAL_VERSION = 1

_FIELD_LABELS = {
    "machine_id": "a máquina",
    "op_id": "a operação",
    "prod_min": "a duração de produção",
    "setup_min": "a duração do setup",
    "material_quantity": "a quantidade com material libertado",
    "edd/tool": "o prazo ou a ferramenta",
    "output_milestones": "as entregas do lote",
    "edd": "o prazo de produção",
    "production_due_day": "o prazo de produção",
    "original_edd": "a data de rutura",
    "delivery_day": "a data de entrega ao cliente",
    "customer_delivery_day": "a data de entrega ao cliente",
    "internal_deadline": "o alvo interno",
    "internal_target_day": "o alvo interno",
    "latest_subcontract_dispatch_day": "o último envio para subcontratação",
    "subcontract_dispatch_day": "o envio planeado para subcontratação",
    "material_reference_day": "a data de referência do material",
    "material_reference_kind": "a referência do material",
    "material_release_day": "a libertação do material",
    "is_subcontracted": "a subcontratação",
}


def has_quantity_material(lots) -> bool:
    """Whether any lot carries the per-delivery material contract."""
    return any(
        output.get("quantity_material_version")
        for lot in lots for output in lot.output_milestones or []
    )


def legacy_material_plan(lots, data, config) -> bool:
    """A plan built before per-delivery material windows that now needs them.

    Its non-twin lots carry no ``quantity_material_version`` while the current
    lot sizing releases the material of the same scenario in several portions.
    Such a plan can still be read, but committing it again needs a rebuild.
    """
    if data is None or not data.ops or not lots:
        return False
    if any(
        not lot.is_twin and any(
            output.get("quantity_material_version") for output in lot.output_milestones or []
        )
        for lot in lots
    ):
        return False
    from backend.scheduler.quantity_dispatch import has_quantity_releases

    return has_quantity_releases(create_lots(data, config or FactoryConfig()))


def _lot_label(lot, machine_id=None):
    """``Referência 8718696125 (PRM042)``: never the internal lot id."""
    reference = lot.sku or lot.op_id
    if lot.twin_outputs:
        reference = " + ".join(
            dict.fromkeys(str(sku or op_id) for op_id, sku, _qty in lot.twin_outputs)
        )
    machine = machine_id or lot.machine_id
    return f"Referência {reference} ({machine})" if machine else f"Referência {reference}"


def _material_message(lot, segment, allowed, data):
    from backend.scheduler.validation import day_label, pt_int

    allowed = int(allowed)
    if allowed <= 0:
        released = "ainda não há peças com material libertado"
    elif allowed == 1:
        released = "só 1 peça tem material libertado"
    else:
        released = f"só {pt_int(allowed)} peças têm material libertado"
    return (
        f"{_lot_label(lot, segment.machine_id)}, {day_label(segment.day_idx, data)}: "
        f"{released}, mas o plano prepara ou produz mais do que isso. "
        "É necessário recalcular o plano (botão «Recalcular plano»)."
    )


def production_lot_obligations(lots):
    """Stable production contract; allocation and machine-dependent times vary."""
    fields = (
        "op_id", "tool_id", "qty", "edd", "is_twin", "twin_outputs",
        "original_edd", "delivery_day", "customer_delivery_day",
        "latest_subcontract_dispatch_day", "production_due_day",
        "output_milestones", "is_subcontracted", "subcontract_company_id",
        "subcontract_lead_time_days", "subcontract_buffer_days",
    )
    return copy.deepcopy({
        lot.id: tuple(getattr(lot, field) for field in fields) for lot in lots
    })


def preserved_lot_proofs(segments, lots):
    by_lot = defaultdict(list)
    for segment in segments:
        by_lot[segment.lot_id].append(segment)
    return {
        lot.id: _lot_proof(by_lot[lot.id], lot) for lot in lots
    }


def _lot_proof(segments, lot):
    """Reuse a digest only after exact equality of all snapshot fields."""
    cache = execution_cache("preserved_lot_proofs")
    previous = cache.get(lot.id)
    if previous is not None and previous[0] == lot and previous[1] == segments:
        return previous[2]
    proof = schedule_fingerprint(segments, [lot])
    cache[lot.id] = (copy.deepcopy(lot), copy.deepcopy(segments), proof)
    if len(cache) > 256:
        del cache[next(iter(cache))]
    return proof


def result_validation_data(data, result):
    if result.preserved_lot_proofs is None:
        return data
    detached = copy.copy(data)
    detached.preserved_lot_proofs = dict(result.preserved_lot_proofs)
    return detached


def source_contract_violations(segments, lots, data, config, *, require_current_material=False):
    # Resource-only subproblems have calendars but no operation catalogue.
    # Full scenario validation receives the original, populated catalogue.
    if data is None or not data.ops or lots is None:
        return []
    config = config or FactoryConfig()
    by_lot = defaultdict(list)
    by_machine = defaultdict(list)
    for segment in segments:
        by_lot[segment.lot_id].append(segment)
        by_machine[segment.machine_id].append(segment)
    for machine_segments in by_machine.values():
        machine_segments.sort(key=lambda s: (s.day_idx, s.start_min, s.end_min))
    ops = {op.id: op for op in data.ops}
    overrides = build_setup_override_map(config)
    violations = []
    remaining = []
    preserved = []

    def fail(lot, field, actual=None, expected=None):
        label = _FIELD_LABELS.get(field, "um dado do lote")
        message = f"{_lot_label(lot)}: {label} não coincide com os dados carregados (ISOP)."
        violations.append({"kind": "source_contract", "lot_id": lot.id, "message": message,
                           "field": field, "actual": actual, "expected": expected})

    def check_material_quantities(lot, contract):
        from backend.scheduler.material_quantities import released_quantity

        produced = 0
        for segment in sorted(by_lot[lot.id], key=lambda s: (s.day_idx, s.start_min)):
            allowed = released_quantity(contract, segment.day_idx)
            premature_setup = segment.setup_min > 0 and produced >= allowed and produced < lot.qty
            produced += segment.qty
            if produced > allowed or premature_setup:
                fail(lot, "material_quantity", produced, allowed)
                violations[-1].update(
                    day_idx=segment.day_idx,
                    message=_material_message(lot, segment, allowed, data),
                )
                break

    for lot in lots:
        physical = by_lot[lot.id]
        proof = data.preserved_lot_proofs.get(lot.id)
        if proof and proof == _lot_proof(physical, lot):
            preserved.append(lot)
            continue
        remaining.append(lot)
        machines = {s.machine_id for s in physical if s.prod_min > 0}
        if len(machines) > 1:
            fail(lot, "machine_id")
        machine = next(iter(machines), lot.machine_id)
        times, setups = [], []
        for op_id, sku, qty in lot.twin_outputs or [(lot.op_id, lot.sku, lot.qty)]:
            op = ops.get(op_id)
            if op is None:
                fail(lot, "op_id", op_id)
                continue
            oee = effective_oee(op, machine, config)
            times.append(qty / (op.pH * oee) * 60.0 if op.pH > 0 and oee > 0 else 0.0)
            setups.append(resolve_setup_hours(op.sku, machine, op.sH, config, overrides) * 60)
        expected_prod = max([config.min_prod_min, *times])
        if not math.isclose(lot.prod_min, expected_prod, rel_tol=1e-6, abs_tol=0.01):
            fail(lot, "prod_min", lot.prod_min, expected_prod)
        expected_setup = max(setups, default=0.0)
        continuation_setup = False
        if physical and lot.setup_min == 0:
            first = min(physical, key=lambda s: (s.day_idx, s.start_min, s.end_min))
            ordered = by_machine[machine]
            index = next((i for i, s in enumerate(ordered) if s is first), 0)
            continuation_setup = (
                index > 0
                and segment_setup_identity(ordered[index - 1]) == segment_setup_identity(first)
                or any(
                    s.machine_id == machine and s.tool_id == lot.tool_id
                    for s in data.current_machine_states
                )
                or sum(s.setup_min for s in physical) + 0.01 >= expected_setup
            )
        if not continuation_setup and not math.isclose(
            lot.setup_min, expected_setup, rel_tol=1e-6, abs_tol=0.01
        ):
            fail(lot, "setup_min", lot.setup_min, expected_setup)

    residual = data
    if preserved:
        residual = copy.copy(data)
        residual.committed_supplies = list(data.committed_supplies)
        for lot in preserved:
            for op_id, sku, qty in lot.twin_outputs or [(lot.op_id, lot.sku, lot.qty)]:
                residual.committed_supplies.append(CommittedSupply(
                    op_id=str(op_id), sku=str(sku), qty=int(qty), available_at="",
                    available_day=0, machine_id=lot.machine_id, tool_id=lot.tool_id,
                ))
    quantity_material = has_quantity_material(remaining)
    # Old snapshots remain readable under their recorded model. Operational
    # persistence and explicit recalculation request the current contract.
    expected_lots = create_lots(residual, config, quantity_material=quantity_material)
    expected_by_id = {lot.id: lot for lot in expected_lots}
    if require_current_material and not quantity_material:
        current_lots = {lot.id: lot for lot in create_lots(residual, config)}
        for lot in remaining:
            expected = current_lots.get(lot.id)
            if expected is None:
                continue
            check_material_quantities(lot, expected)
        # Legal splits/renames must not bypass the current material contract.
        from backend.scheduler.material_quantities import released_quantity

        current_by_op = defaultdict(list)
        actual_by_op = defaultdict(list)
        for lot in current_lots.values():
            if not lot.is_twin:
                current_by_op[lot.op_id].append(lot)
        for lot in remaining:
            if not lot.is_twin:
                actual_by_op[lot.op_id].extend((s, lot) for s in by_lot[lot.id])
        for op_id, entries in actual_by_op.items():
            contracts = current_by_op[op_id]
            if not contracts:
                continue
            produced = 0
            for segment, lot in sorted(
                entries, key=lambda item: (item[0].day_idx, item[0].start_min),
            ):
                produced += segment.qty
                allowed = sum(
                    released_quantity(contract, segment.day_idx) for contract in contracts
                )
                if produced > allowed:
                    fail(lot, "material_quantity", produced, allowed)
                    violations[-1].update(
                        day_idx=segment.day_idx,
                        message=_material_message(lot, segment, allowed, data),
                    )
                    break
    for lot in remaining:
        expected = expected_by_id.get(lot.id)
        if expected is not None and (lot.edd != expected.edd or lot.tool_id != expected.tool_id):
            fail(lot, "edd/tool", [lot.edd, lot.tool_id], [expected.edd, expected.tool_id])

    def obligations(items):
        counts = Counter()
        for lot in items:
            for output in lot.output_milestones or []:
                # Grouping and legal splitting can change lot IDs, but not the
                # quantity attributed to each source delivery/material window.
                key = tuple((k, str(v)) for k, v in sorted(output.items()) if k != "qty")
                counts[key] += int(output.get("qty", 0))
        return counts

    # Historical snapshots without output metadata retain the older quantity
    # check; every newly constructed lot has the full canonical contract.
    if any(lot.output_milestones for lot in remaining):
        available = obligations(expected_lots)
        for lot in remaining:
            if not lot.output_milestones:
                continue
            actual = obligations([lot])
            if any(qty > available.get(key, 0) for key, qty in actual.items()):
                expected = expected_by_id.get(lot.id)
                fail(lot, "output_milestones", copy.deepcopy(lot.output_milestones),
                     copy.deepcopy(expected.output_milestones) if expected is not None else None)
            available.subtract(actual)

    invalid_outputs = {v["lot_id"] for v in violations if v["field"] == "output_milestones"}
    for lot in remaining:
        if not lot.output_milestones or lot.id in invalid_outputs:
            continue
        # Pre-contract snapshots contain only descriptive delivery metadata;
        # they retain the existing physical and total-quantity checks.
        if not any("qty" in output for output in lot.output_milestones):
            continue
        if len({item.get("material_release_day") for item in lot.output_milestones}) > 1:
            check_material_quantities(lot, lot)
        try:
            milestones = _aggregate_milestones(lot.output_milestones)
        except (KeyError, TypeError, ValueError):
            fail(lot, "output_milestones", copy.deepcopy(lot.output_milestones))
            continue
        for field, value in milestones.items():
            if field != "output_milestones" and getattr(lot, field) != value:
                fail(lot, field, getattr(lot, field), value)
        # Older optional aliases may be absent, but cannot contradict the
        # detailed outputs that planning and order tracking both consume.
        for field, target in (
            ("edd", "production_due_day"),
            ("original_edd", "customer_delivery_day"),
            ("delivery_day", "customer_delivery_day"),
            ("internal_deadline", "internal_target_day"),
        ):
            actual = getattr(lot, field)
            if actual is not None and actual != milestones[target]:
                fail(lot, field, actual, milestones[target])
    return violations
