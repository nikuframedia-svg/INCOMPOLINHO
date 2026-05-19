"""Phase 1 — Lot Sizing: Spec 02 v6 §3.

Converts EOps → Lots with eco lot HARD and twin super-ops.
surplus=0 (first negative NP already has stock deducted).
Fix 5: prod_min minimum = MIN_PROD_MIN to avoid micro-lots.
"""

from __future__ import annotations

import math

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DEFAULT_OEE, MIN_PROD_MIN
from backend.scheduler.types import Lot
from backend.types import EngineData, EOp, TwinGroup


def create_lots(data: EngineData, config: FactoryConfig | None = None) -> list[Lot]:
    """Create Lots from EngineData.

    1. Twin ops → super-ops (TWIN lots)
    2. Remaining ops → solo lots
    3. Eco lot carry-forward applied to both
    """
    oee_default = config.oee_default if config else DEFAULT_OEE
    min_prod = config.min_prod_min if config else MIN_PROD_MIN

    twin_op_ids: set[str] = set()
    for tg in data.twin_groups:
        twin_op_ids.add(tg.op_id_1)
        twin_op_ids.add(tg.op_id_2)

    ops_by_id: dict[str, EOp] = {op.id: op for op in data.ops}
    lots: list[Lot] = []

    # Twin lots first
    for tg in data.twin_groups:
        op_a = ops_by_id.get(tg.op_id_1)
        op_b = ops_by_id.get(tg.op_id_2)
        if op_a and op_b:
            lots.extend(_create_twin_lots(op_a, op_b, tg, oee_default, min_prod))

    # Solo lots for non-twin ops
    for op in data.ops:
        if op.id not in twin_op_ids:
            lots.extend(_create_solo_lots(op, oee_default, min_prod))

    # Adjust EDDs that fall on holidays (weekends/feriados) to previous workday
    holidays = set(getattr(data, "holidays", []))
    if holidays:
        for lot in lots:
            while lot.edd in holidays and lot.edd > 0:
                lot.edd -= 1

    return lots


def _create_solo_lots(op: EOp, oee_default: float = DEFAULT_OEE, min_prod: float = MIN_PROD_MIN) -> list[Lot]:
    """Create lots for a solo (non-twin) operation.

    Eco lot HARD: each lot qty = max(demand, eco_lot), rounded up.
    Carry-forward: surplus from earlier lot reduces demand of later lots.
    """
    lots: list[Lot] = []
    surplus = 0  # First negative NP already has stock deducted
    oee = op.oee or oee_default

    for day_idx, demand in enumerate(op.d):
        if demand <= 0:
            continue

        if surplus >= demand:
            surplus -= demand
            continue

        deficit = demand - surplus
        qty = _apply_eco_lot(deficit, op.eco_lot)
        surplus = qty - deficit

        if op.pH > 0 and oee > 0:
            prod_min = max(min_prod, (qty / (op.pH * oee)) * 60.0)
        else:
            prod_min = min_prod
        setup_min = op.sH * 60.0

        lots.append(Lot(
            id=f"LOT_{op.t}_{op.m}_{op.sku}_{day_idx}",
            op_id=op.id,
            tool_id=op.t,
            machine_id=op.m,
            alt_machine_id=op.alt,
            qty=qty,
            prod_min=prod_min,
            setup_min=setup_min,
            edd=day_idx,
            is_twin=False,
        ))

    return lots


def _create_twin_lots(op_a: EOp, op_b: EOp, tg: TwinGroup, oee_default: float = DEFAULT_OEE, min_prod: float = MIN_PROD_MIN) -> list[Lot]:
    """Create twin super-op lots.

    Factory rules for twin (peças gémeas) production:
    - Both have demand → SAME qty for both (max eco lot). Smaller demand gets surplus.
    - Only one has demand → only that one produces, other gets 0.
    - Time = ONE run for max(time_a, time_b).
    """
    lots: list[Lot] = []
    surplus_a = 0  # First negative NP already has stock deducted
    surplus_b = 0
    oee = op_a.oee or oee_default

    all_days: set[int] = set()
    for day_idx, d in enumerate(op_a.d):
        if d > 0:
            all_days.add(day_idx)
    for day_idx, d in enumerate(op_b.d):
        if d > 0:
            all_days.add(day_idx)

    for day_idx in sorted(all_days):
        demand_a = op_a.d[day_idx] if day_idx < len(op_a.d) else 0
        demand_b = op_b.d[day_idx] if day_idx < len(op_b.d) else 0

        need_a = max(0, demand_a - surplus_a)
        need_b = max(0, demand_b - surplus_b)

        if need_a <= 0 and need_b <= 0:
            surplus_a -= max(demand_a, 0)
            surplus_b -= max(demand_b, 0)
            continue

        # Apply eco lot to each need independently
        eco_a = _apply_eco_lot(need_a, op_a.eco_lot) if need_a > 0 else 0
        eco_b = _apply_eco_lot(need_b, op_b.eco_lot) if need_b > 0 else 0

        if eco_a > 0 and eco_b > 0:
            # BOTH need production → max eco lot for BOTH (same qty)
            qty = max(eco_a, eco_b)
            qty_a, qty_b = qty, qty
        elif eco_a > 0:
            # Only A needs → solo A production
            qty_a, qty_b = eco_a, 0
        else:
            # Only B needs → solo B production
            qty_a, qty_b = 0, eco_b

        surplus_a = (qty_a - need_a) if qty_a > 0 else max(0, surplus_a - max(demand_a, 0))
        surplus_b = (qty_b - need_b) if qty_b > 0 else max(0, surplus_b - max(demand_b, 0))

        time_a = (qty_a / (op_a.pH * oee)) * 60.0 if qty_a > 0 else 0.0
        time_b = (qty_b / (op_b.pH * oee)) * 60.0 if qty_b > 0 else 0.0
        prod_min = max(min_prod, max(time_a, time_b))
        setup_min = op_a.sH * 60.0

        primary_qty = max(qty_a, qty_b)
        primary_op = op_a if qty_a >= qty_b else op_b

        twin_outputs = [
            (op_a.id, op_a.sku, qty_a),
            (op_b.id, op_b.sku, qty_b),
        ]

        lots.append(Lot(
            id=f"LOT_TWIN_{tg.tool_id}_{day_idx}",
            op_id=primary_op.id,
            tool_id=tg.tool_id,
            machine_id=tg.machine_id,
            alt_machine_id=op_a.alt,
            qty=primary_qty,
            prod_min=prod_min,
            setup_min=setup_min,
            edd=day_idx,
            is_twin=True,
            twin_outputs=twin_outputs,
        ))

    lots = _merge_complementary_twin_lots(lots, op_a, op_b, oee)
    return lots


def _merge_complementary_twin_lots(
    lots: list[Lot], op_a: EOp, op_b: EOp, oee: float, max_gap: int = 5,
) -> list[Lot]:
    """Merge complementary twin lots into single co-produced runs.

    BUG 4 fix: the previous logic only merged *consecutive* complementary lots
    (solo-A immediately followed by solo-B). When demand patterns interleave
    irregularly — e.g. A/A/B/A/B/A — runs of same-side solo lots left some
    solo-A lots unmerged, producing separate single-SKU blocks on the same
    tool+machine instead of one co-produced run.

    New logic: a GLOBAL pairing pass. Each solo-A lot is paired with the
    nearest still-unpaired solo-B lot within ``max_gap`` days (and vice
    versa). Pairing a solo lot keeps eco-lot HARD per SKU (qty already
    computed independently) and independent per-SKU surplus carry-forward
    (already baked into each lot's qty before this pass). Merging only
    combines ``twin_outputs`` and recomputes time = max(time_a, time_b).
    EDD = min of the pair so neither deadline is missed.
    """
    if len(lots) <= 1:
        return lots

    def side(lot: Lot) -> str | None:
        """'A' = only A produces, 'B' = only B produces, None = joint/empty."""
        if not lot.twin_outputs:
            return None
        qa, qb = lot.twin_outputs[0][2], lot.twin_outputs[1][2]
        if qa > 0 and qb == 0:
            return "A"
        if qb > 0 and qa == 0:
            return "B"
        return None

    solo_a = sorted((i for i, lot in enumerate(lots) if side(lot) == "A"))
    solo_b = sorted((i for i, lot in enumerate(lots) if side(lot) == "B"))

    # Greedy nearest-neighbour pairing between solo-A and solo-B lots.
    paired: dict[int, int] = {}  # idx_a -> idx_b
    used_b: set[int] = set()
    for ia in solo_a:
        best_ib = None
        best_gap = max_gap + 1
        for ib in solo_b:
            if ib in used_b:
                continue
            gap = abs(lots[ib].edd - lots[ia].edd)
            if gap <= max_gap and gap < best_gap:
                best_gap = gap
                best_ib = ib
        if best_ib is not None:
            paired[ia] = best_ib
            used_b.add(best_ib)

    if not paired:
        return lots

    consumed: set[int] = set()
    merged: list[Lot] = []
    for idx, lot in enumerate(lots):
        if idx in consumed:
            continue
        if idx in paired:
            partner_idx = paired[idx]
            lot_a, lot_b = lot, lots[partner_idx]
            consumed.add(partner_idx)

            qty_a = lot_a.twin_outputs[0][2]  # type: ignore[index]
            qty_b = lot_b.twin_outputs[1][2]  # type: ignore[index]
            qty = max(qty_a, qty_b)

            time_a = (qty_a / (op_a.pH * oee)) * 60.0 if qty_a > 0 and op_a.pH > 0 else 0.0
            time_b = (qty_b / (op_b.pH * oee)) * 60.0 if qty_b > 0 and op_b.pH > 0 else 0.0
            prod_min = max(1.0, max(time_a, time_b))

            primary_op = op_a if qty_a >= qty_b else op_b
            edd = min(lot_a.edd, lot_b.edd)

            merged.append(Lot(
                id=f"{lot_a.id}_m",
                op_id=primary_op.id,
                tool_id=lot_a.tool_id,
                machine_id=lot_a.machine_id,
                alt_machine_id=lot_a.alt_machine_id,
                qty=qty,
                prod_min=prod_min,
                setup_min=lot_a.setup_min,
                edd=edd,
                is_twin=True,
                twin_outputs=[
                    (op_a.id, op_a.sku, qty_a),
                    (op_b.id, op_b.sku, qty_b),
                ],
            ))
        else:
            merged.append(lot)

    merged.sort(key=lambda x: x.edd)
    return merged


def _apply_eco_lot(demand: int, eco_lot: int) -> int:
    """Apply eco lot HARD: round up to eco lot multiple."""
    if eco_lot <= 0 or demand <= 0:
        return demand
    return math.ceil(demand / eco_lot) * eco_lot
