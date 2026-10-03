"""Phase 1 — Lot Sizing: Spec 02 v6 §3.

Converts EOps → Lots with eco lot HARD and twin super-ops.
surplus=0 (first negative NP already has stock deducted).
Fix 5: prod_min minimum = MIN_PROD_MIN to avoid micro-lots.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from backend.config.planning import (
    PlanningMilestones,
    planning_milestones_for_op,
    validate_active_twin_eco_lots,
)
from backend.config.types import FactoryConfig
from backend.scheduler.constants import DEFAULT_OEE, MIN_PROD_MIN
from backend.scheduler.jit_policy import calendar_holidays
from backend.scheduler.setup_identity import configured_setup_family
from backend.scheduler.types import Lot
from backend.types import EngineData, EOp, TwinGroup

TWIN_MAX_PAIR_GAP_DAYS = 5


@dataclass(slots=True)
class _TwinDemandEvent:
    op: EOp
    side: int
    day_idx: int
    demand: int
    remaining: int
    milestones: PlanningMilestones


def create_lots(data: EngineData, config: FactoryConfig | None = None) -> list[Lot]:
    """Create Lots from EngineData.

    1. Twin ops → super-ops (TWIN lots)
    2. Remaining ops → solo lots
    3. Eco lot carry-forward applied to both
    """
    validate_active_twin_eco_lots(data)
    oee_default = config.oee_default if config else DEFAULT_OEE
    min_prod = config.min_prod_min if config else MIN_PROD_MIN

    twin_op_ids: set[str] = set()
    for tg in data.twin_groups:
        twin_op_ids.add(tg.op_id_1)
        twin_op_ids.add(tg.op_id_2)

    ops_by_id: dict[str, EOp] = {
        op.id: _op_after_committed_supply(op, data) for op in data.ops
    }
    max_backward_workdays = max(
        (
            5
            + max(0, int(op.subcontract_lead_time_days or 0))
            + max(0, int(op.subcontract_buffer_days or 0))
            + max(0, int(op.finish_buffer_days or 0))
            for op in ops_by_id.values()
        ),
        default=5,
    )
    first_calendar_day = -(14 + math.ceil(max_backward_workdays / 5) * 7)
    planning_holidays = calendar_holidays(
        data,
        first_calendar_day,
        data.n_days + 14,
    )
    lots: list[Lot] = []

    # Twin lots first
    for tg in data.twin_groups:
        op_a = ops_by_id.get(tg.op_id_1)
        op_b = ops_by_id.get(tg.op_id_2)
        if op_a and op_b:
            lots.extend(
                _create_twin_lots(
                    op_a,
                    op_b,
                    tg,
                    oee_default,
                    min_prod,
                    planning_holidays,
                )
            )

    # Solo lots for non-twin ops
    for source_op in data.ops:
        op = ops_by_id[source_op.id]
        if op.id not in twin_op_ids:
            lots.extend(
                _create_solo_lots(
                    op,
                    oee_default,
                    min_prod,
                    planning_holidays,
                    config,
                )
            )

    return lots


def _create_solo_lots(
    op: EOp,
    oee_default: float = DEFAULT_OEE,
    min_prod: float = MIN_PROD_MIN,
    holidays: set[int] | None = None,
    config: FactoryConfig | None = None,
) -> list[Lot]:
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
        requested_qty, campaign_source = _requested_qty_with_campaign(op, day_idx, deficit, oee)
        qty = _apply_eco_lot(requested_qty, op.eco_lot)
        surplus = qty - deficit

        if op.pH > 0 and oee > 0:
            prod_min = max(min_prod, (qty / (op.pH * oee)) * 60.0)
        else:
            prod_min = min_prod
        setup_min = op.sH * 60.0
        milestones = planning_milestones_for_op(op, day_idx, holidays)
        milestone_fields = _aggregate_milestones(
            [_output_milestone(op, qty, milestones)]
        )
        planning_source = _planning_source(op, deficit, requested_qty, qty, campaign_source)

        lots.append(
            Lot(
                id=f"LOT_{op.t}_{op.m}_{op.sku}_{day_idx}",
                op_id=op.id,
                tool_id=op.t,
                machine_id=op.m,
                alt_machine_id=op.alt,
                qty=qty,
                prod_min=prod_min,
                setup_min=setup_min,
                edd=milestones.production_due_day,
                is_twin=False,
                sku=op.sku,
                setup_family=configured_setup_family(config, op.t, op.sku),
                original_edd=milestones.customer_delivery_day,
                internal_deadline=milestones.internal_target_day,
                delivery_day=milestones.customer_delivery_day,
                **milestone_fields,
                eco_lot_isop=op.eco_lot_isop,
                eco_lot_effective=op.eco_lot_effective
                if op.eco_lot_effective is not None
                else op.eco_lot,
                start_buffer_days=op.start_buffer_days,
                finish_buffer_days=op.finish_buffer_days,
                target_start_day=_target_start_day(op, day_idx),
                min_campaign_qty=op.min_campaign_qty,
                min_campaign_prod_min=op.min_campaign_prod_min,
                max_group_gap_days=op.max_group_gap_days,
                planning_priority=op.planning_priority,
                planning_source=planning_source,
                economic_warning=_economic_warning(
                    deficit,
                    qty,
                    prod_min,
                    setup_min,
                    planning_source,
                ),
                subcontract_company_id=op.subcontract_company_id,
                subcontract_lead_time_days=op.subcontract_lead_time_days,
                subcontract_buffer_days=op.subcontract_buffer_days,
            )
        )

    return lots


def _create_twin_lots(
    op_a: EOp,
    op_b: EOp,
    tg: TwinGroup,
    oee_default: float = DEFAULT_OEE,
    min_prod: float = MIN_PROD_MIN,
    holidays: set[int] | None = None,
) -> list[Lot]:
    """Create deterministic twin cycles with equal output in every joint run."""
    lots: list[Lot] = []
    events = [
        _TwinDemandEvent(
            op=op,
            side=side,
            day_idx=day_idx,
            demand=int(demand),
            remaining=int(demand),
            milestones=planning_milestones_for_op(op, day_idx, holidays),
        )
        for side, op in enumerate((op_a, op_b))
        for day_idx, demand in enumerate(op.d)
        if demand > 0
    ]
    events_by_side = {
        side: sorted(
            (event for event in events if event.side == side),
            key=lambda event: event.day_idx,
        )
        for side in (0, 1)
    }
    demand_totals = {
        side: sum(event.demand for event in side_events)
        for side, side_events in events_by_side.items()
    }
    produced_totals = {0: 0, 1: 0}
    terminal_surplus = {0: 0, 1: 0}
    used_lot_ids: set[str] = set()

    while pending := [event for event in events if event.remaining > 0]:
        current = min(pending, key=_twin_event_priority)
        partner_candidates = [
            event
            for event in pending
            if event.side != current.side
            and abs(event.day_idx - current.day_idx) <= TWIN_MAX_PAIR_GAP_DAYS
        ]
        partner = (
            min(
                partner_candidates,
                key=lambda event: (
                    abs(event.day_idx - current.day_idx),
                    _twin_event_priority(event),
                ),
            )
            if partner_candidates
            else None
        )

        current_qty = _apply_eco_lot(current.remaining, current.op.eco_lot)
        active_events = [current]
        if partner is not None:
            partner_qty = _apply_eco_lot(partner.remaining, partner.op.eco_lot)
            run_qty = max(current_qty, partner_qty)
            active_events.append(partner)
            planning_source = "twin_joint"
        else:
            run_qty = current_qty
            planning_source = "twin_joint_surplus"

        # A real twin tool always produces one piece of each reference per
        # cycle. A side without nearby demand is intentional co-produced stock,
        # never a physically unilateral run.
        qty_by_side = {0: run_qty, 1: run_qty}

        for side, qty in qty_by_side.items():
            if qty <= 0:
                continue
            produced_totals[side] += qty
            terminal_surplus[side] += _consume_twin_output(
                events_by_side[side],
                qty,
            )
        if current.remaining > 0 or (partner is not None and partner.remaining > 0):
            raise RuntimeError("Falha ao consumir o evento controlador de gémeas.")

        active_by_side = {event.side: event for event in active_events}
        output_milestones = []
        for side, op in enumerate((op_a, op_b)):
            event = active_by_side.get(side)
            if event is not None:
                output_milestones.append(
                    _output_milestone(op, run_qty, event.milestones)
                )
            else:
                output_milestones.append(
                    _coproduced_surplus_milestone(
                        op,
                        run_qty,
                        current.milestones,
                    )
                )
        milestone_fields = _aggregate_milestones(output_milestones)
        primary_event = min(
            active_events,
            key=lambda event: (
                event.milestones.production_due_day,
                event.milestones.customer_delivery_day,
                event.op.id,
            ),
        )
        primary_op = primary_event.op
        active_ops = [event.op for event in active_events]
        subcontracted_outputs = [
            item for item in output_milestones if item.get("is_subcontracted")
        ]
        company_ids = {
            str(item["subcontract_company_id"])
            for item in subcontracted_outputs
            if item.get("subcontract_company_id")
        }
        quantities = (qty_by_side[0], qty_by_side[1])
        prod_times = [
            (qty / (op.pH * (op.oee or oee_default))) * 60.0
            for op, qty in zip((op_a, op_b), quantities)
            if op.pH > 0 and (op.oee or oee_default) > 0
        ]
        prod_min = max(min_prod, max(prod_times, default=0.0))
        lot_id = f"LOT_TWIN_{tg.tool_id}_{primary_event.day_idx}"
        if lot_id in used_lot_ids:
            lot_id = f"{lot_id}_{len(lots) + 1}"
        used_lot_ids.add(lot_id)

        lots.append(
            Lot(
                id=lot_id,
                op_id=primary_op.id,
                tool_id=tg.tool_id,
                machine_id=tg.machine_id,
                alt_machine_id=primary_op.alt,
                qty=run_qty,
                prod_min=prod_min,
                setup_min=max(op_a.sH, op_b.sH) * 60.0,
                edd=int(milestone_fields["production_due_day"]),
                is_twin=True,
                sku=primary_op.sku,
                twin_outputs=[
                    (op_a.id, op_a.sku, quantities[0]),
                    (op_b.id, op_b.sku, quantities[1]),
                ],
                original_edd=int(milestone_fields["customer_delivery_day"]),
                internal_deadline=int(milestone_fields["internal_target_day"]),
                delivery_day=int(milestone_fields["customer_delivery_day"]),
                **milestone_fields,
                eco_lot_isop=primary_op.eco_lot_isop,
                eco_lot_effective=primary_op.eco_lot_effective
                if primary_op.eco_lot_effective is not None
                else primary_op.eco_lot,
                start_buffer_days=max(op.start_buffer_days for op in active_ops),
                finish_buffer_days=max(op.finish_buffer_days for op in active_ops),
                target_start_day=min(
                    _target_start_day(event.op, event.day_idx)
                    for event in active_events
                ),
                min_campaign_qty=primary_op.min_campaign_qty,
                min_campaign_prod_min=primary_op.min_campaign_prod_min,
                max_group_gap_days=primary_op.max_group_gap_days,
                planning_priority=max(op.planning_priority for op in active_ops),
                planning_source=planning_source,
                subcontract_company_id=(
                    next(iter(company_ids)) if len(company_ids) == 1 else None
                ),
                subcontract_lead_time_days=max(
                    (
                        int(item.get("subcontract_lead_time_days", 0) or 0)
                        for item in subcontracted_outputs
                    ),
                    default=0,
                ),
                subcontract_buffer_days=max(
                    (
                        int(item.get("subcontract_buffer_days", 0) or 0)
                        for item in subcontracted_outputs
                    ),
                    default=0,
                ),
            )
        )

    for side in (0, 1):
        if produced_totals[side] != demand_totals[side] + terminal_surplus[side]:
            raise RuntimeError("Falha de conservação no dimensionamento de gémeas.")
    return sorted(
        lots,
        key=lambda lot: (
            lot.edd,
            lot.original_edd if lot.original_edd is not None else lot.edd,
            lot.id,
        ),
    )


def _twin_event_priority(event: _TwinDemandEvent) -> tuple[int, int, int, int, str]:
    return (
        event.milestones.production_due_day,
        event.milestones.customer_delivery_day,
        -max(0, int(event.op.planning_priority or 0)),
        event.day_idx,
        event.op.id,
    )


def _consume_twin_output(events: list[_TwinDemandEvent], qty: int) -> int:
    """Apply one output FIFO and return surplus beyond the visible demand."""

    remaining_output = int(qty)
    for event in events:
        if remaining_output <= 0:
            break
        consumed = min(event.remaining, remaining_output)
        event.remaining -= consumed
        remaining_output -= consumed
    return remaining_output


def _op_after_committed_supply(op: EOp, data: EngineData) -> EOp:
    """Offset only demand available at or after each committed-supply ETA."""

    supplies_by_day: dict[int, int] = {}
    for supply in data.committed_supplies:
        if supply.op_id == op.id and supply.qty > 0:
            supplies_by_day[supply.available_day] = (
                supplies_by_day.get(supply.available_day, 0) + supply.qty
            )
    if not supplies_by_day:
        return op

    available = 0
    adjusted: list[int] = []
    for day_idx, demand in enumerate(op.d):
        available += supplies_by_day.get(day_idx, 0)
        positive_demand = max(0, int(demand))
        credit = min(positive_demand, available)
        available -= credit
        adjusted.append(positive_demand - credit if demand > 0 else int(demand))
    return replace(op, d=adjusted)


def _apply_eco_lot(demand: int, eco_lot: int) -> int:
    """Apply eco lot HARD: round up to eco lot multiple."""
    if eco_lot <= 0 or demand <= 0:
        return demand
    return math.ceil(demand / eco_lot) * eco_lot


def _output_milestone(
    op: EOp,
    qty: int,
    milestones: PlanningMilestones,
) -> dict[str, object]:
    """Return an auditable milestone record for one active lot output."""

    return {
        "op_id": op.id,
        "sku": op.sku,
        "qty": int(qty),
        "is_subcontracted": bool(
            op.is_subcontracted
            or op.subcontract_company_id
            or op.subcontract_lead_time_days
            or op.subcontract_buffer_days
        ),
        "subcontract_company_id": op.subcontract_company_id,
        "subcontract_lead_time_days": int(op.subcontract_lead_time_days or 0),
        "subcontract_buffer_days": int(op.subcontract_buffer_days or 0),
        "customer_delivery_day": milestones.customer_delivery_day,
        "latest_subcontract_dispatch_day": milestones.latest_subcontract_dispatch_day,
        "subcontract_dispatch_day": milestones.subcontract_dispatch_day,
        "production_due_day": milestones.production_due_day,
        "internal_target_day": milestones.internal_target_day,
        "material_reference_day": milestones.material_reference_day,
        "material_reference_kind": milestones.material_reference_kind,
        "material_release_day": milestones.material_release_day,
    }


def _coproduced_surplus_milestone(
    op: EOp,
    qty: int,
    controlling_milestones: PlanningMilestones,
) -> dict[str, object]:
    """Describe physical twin output that has no nearby demand to pair."""

    output = _output_milestone(op, qty, controlling_milestones)
    output["is_coproduced_surplus"] = True
    return output


def _aggregate_milestones(outputs: list[dict[str, object]]) -> dict[str, object]:
    """Build one shared-material window for all outputs of a physical cycle."""

    if not outputs:
        raise ValueError("A production lot must contain at least one active output")

    def values(field: str) -> list[int]:
        return [int(item[field]) for item in outputs if item.get(field) is not None]

    kinds = {str(item["material_reference_kind"]) for item in outputs}
    latest_dispatches = values("latest_subcontract_dispatch_day")
    dispatches = values("subcontract_dispatch_day")
    return {
        "customer_delivery_day": min(values("customer_delivery_day")),
        "latest_subcontract_dispatch_day": (
            min(latest_dispatches) if latest_dispatches else None
        ),
        "subcontract_dispatch_day": min(dispatches) if dispatches else None,
        "production_due_day": min(values("production_due_day")),
        "internal_target_day": min(values("internal_target_day")),
        # Twin outputs share the raw material already released for the most
        # urgent output. A later output's isolated window cannot delay the run.
        "material_reference_day": min(values("material_reference_day")),
        "material_reference_kind": next(iter(kinds)) if len(kinds) == 1 else "mixed",
        "material_release_day": min(values("material_release_day")),
        "output_milestones": [dict(item) for item in outputs],
        "is_subcontracted": any(bool(item.get("is_subcontracted")) for item in outputs),
    }


def _target_start_day(op: EOp, delivery_day: int) -> int:
    """Target start day used for scoring/advisory windows."""
    return max(0, delivery_day - op.start_buffer_days)


def _requested_qty_with_campaign(
    op: EOp,
    day_idx: int,
    deficit: int,
    oee: float,
) -> tuple[int, str | None]:
    """Apply per-SKU campaign minima before eco-lot rounding."""
    requested = deficit
    source = None

    if op.max_group_gap_days is not None and op.max_group_gap_days > 0:
        grouped = deficit
        end_day = min(len(op.d), day_idx + op.max_group_gap_days + 1)
        for future_day in range(day_idx + 1, end_day):
            grouped += max(0, op.d[future_day])
        if grouped > requested:
            requested = grouped
            source = "campaign_window"

    if op.min_campaign_qty is not None and op.min_campaign_qty > requested:
        requested = op.min_campaign_qty
        source = "min_campaign_qty"

    if (
        op.min_campaign_prod_min is not None
        and op.min_campaign_prod_min > 0
        and op.pH > 0
        and oee > 0
    ):
        min_qty_for_time = math.ceil((op.min_campaign_prod_min / 60.0) * op.pH * oee)
        if min_qty_for_time > requested:
            requested = min_qty_for_time
            source = "min_campaign_prod_min"

    return requested, source


def _planning_source(
    op: EOp,
    deficit: int,
    requested_qty: int,
    final_qty: int,
    campaign_source: str | None,
) -> str:
    if op.subcontract_company_id:
        return "subcontract"
    if campaign_source is not None and requested_qty > deficit:
        return campaign_source
    if final_qty > requested_qty:
        if op.eco_lot_isop != op.eco_lot_effective:
            return "eco_lot_override"
        return "eco_lot"
    if final_qty == deficit:
        return "exact_shortfall"
    return "planning_rule"


def _economic_warning(
    deficit: int,
    qty: int,
    prod_min: float,
    setup_min: float,
    planning_source: str,
) -> str | None:
    if planning_source != "exact_shortfall":
        return None
    if qty <= max(deficit, 0) and setup_min >= 15 and prod_min < 10 and setup_min >= prod_min * 3:
        return (
            "Micro-produção por falta exacta: cobre procura pendente, "
            "mas o setup é alto face ao tempo produtivo."
        )
    return None
