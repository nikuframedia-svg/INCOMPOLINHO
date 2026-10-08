"""Fixed JIT policy helpers shared by scheduling, scoring and gates."""

from __future__ import annotations

from datetime import date, timedelta

from backend.config.types import JIT_MAX_ANTICIPATION_WORKDAYS
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.types import EngineData


def calendar_holidays(data: EngineData, start_day: int, end_day: int) -> set[int]:
    """Return authoritative holidays, extrapolating weekends outside the ISOP.

    Negative indices are real calendar days before the first visible column;
    treating them all as working days would incorrectly shrink a five-workday
    window that crosses a weekend.
    """

    holidays = set(data.holidays or [])
    if not data.workdays:
        return holidays
    try:
        first = date.fromisoformat(str(data.workdays[0])[:10])
    except ValueError:
        return holidays
    extra_workdays = set(getattr(data, "calendar_extra_workdays", []) or [])
    for day in range(start_day, end_day + 1):
        if 0 <= day < data.n_days:
            continue
        if day not in extra_workdays and (first + timedelta(days=day)).weekday() >= 5:
            holidays.add(day)
    return holidays


def expedition_day(lot: Lot) -> int:
    """Return the immutable customer-delivery commitment."""

    if lot.customer_delivery_day is not None:
        return int(lot.customer_delivery_day)
    if lot.delivery_day is not None:
        return int(lot.delivery_day)
    if lot.original_edd is not None:
        return int(lot.original_edd)
    return int(lot.edd)


def planning_deadline_day(lot: Lot) -> int:
    """Return the optional internal planning target."""

    if lot.internal_target_day is not None:
        return int(lot.internal_target_day)
    if lot.internal_deadline is not None:
        return int(lot.internal_deadline)
    return int(lot.edd)


def is_subcontracted_lot(lot: Lot) -> bool:
    return bool(
        lot.is_subcontracted
        or lot.subcontract_company_id
        or lot.subcontract_lead_time_days
        or lot.subcontract_buffer_days
    )


def production_due_day(lot: Lot, holidays: set[int] | None = None) -> int:
    """Latest controllable completion day for normal or subcontracted output."""

    if lot.production_due_day is not None:
        return int(lot.production_due_day)
    if is_subcontracted_lot(lot):
        return subtract_workdays(
            expedition_day(lot),
            int(lot.subcontract_lead_time_days or 0)
            + int(lot.subcontract_buffer_days or 0),
            holidays or set(),
        )
    return expedition_day(lot)


def subcontract_dispatch_day(lot: Lot, holidays: set[int] | None = None) -> int | None:
    if lot.subcontract_dispatch_day is not None:
        return int(lot.subcontract_dispatch_day)
    if not is_subcontracted_lot(lot):
        return None
    return production_due_day(lot, holidays)


def material_reference_day(lot: Lot, holidays: set[int] | None = None) -> int:
    if lot.material_reference_day is not None:
        return int(lot.material_reference_day)
    dispatch = subcontract_dispatch_day(lot, holidays)
    return dispatch if dispatch is not None else expedition_day(lot)


def material_reference_kind(lot: Lot) -> str:
    if lot.material_reference_kind in {"customer_delivery", "subcontract_dispatch", "mixed"}:
        return lot.material_reference_kind
    return "subcontract_dispatch" if is_subcontracted_lot(lot) else "customer_delivery"


def lot_output_milestones(lot: Lot) -> list[dict[str, object]]:
    """Return per-output milestones, including a safe legacy projection."""

    if lot.output_milestones:
        return [dict(item) for item in lot.output_milestones]

    raw_outputs = lot.twin_outputs or [(lot.op_id, lot.sku, lot.qty)]
    subcontracted = is_subcontracted_lot(lot)
    return [
        {
            "op_id": op_id,
            "sku": sku,
            "qty": int(qty),
            "is_subcontracted": subcontracted,
            "subcontract_company_id": lot.subcontract_company_id,
            "subcontract_lead_time_days": int(lot.subcontract_lead_time_days or 0),
            "subcontract_buffer_days": int(lot.subcontract_buffer_days or 0),
            "customer_delivery_day": expedition_day(lot),
            "latest_subcontract_dispatch_day": (
                production_due_day(lot) if subcontracted else None
            ),
            "subcontract_dispatch_day": (
                production_due_day(lot) if subcontracted else None
            ),
            "production_due_day": production_due_day(lot),
            "internal_target_day": planning_deadline_day(lot),
            "material_reference_day": material_reference_day(lot),
            "material_reference_kind": material_reference_kind(lot),
            "material_release_day": lot.material_release_day,
        }
        for op_id, sku, qty in raw_outputs
        if int(qty) > 0
    ]


def lot_demand_output_milestones(lot: Lot) -> list[dict[str, object]]:
    """Return outputs tied to real demand, excluding synthetic twin stock."""

    return [
        output
        for output in lot_output_milestones(lot)
        if not bool(output.get("is_coproduced_surplus"))
    ]


def customer_factory_due_day(lot: Lot, holidays: set[int]) -> int:
    """Latest factory completion compatible with every customer commitment.

    Planned subcontract buffers deliberately make ``production_due_day``
    earlier than this boundary. Keeping both dates lets best-effort scheduling
    protect customer service before deciding which planning buffer to consume.
    """

    deadlines: list[int] = []
    has_explicit_outputs = bool(lot.output_milestones)
    for output in lot_demand_output_milestones(lot):
        customer_day = int(output.get("customer_delivery_day", expedition_day(lot)))
        if not bool(output.get("is_subcontracted")):
            deadlines.append(customer_day)
            continue

        latest_dispatch = output.get("latest_subcontract_dispatch_day")
        if latest_dispatch is None or not has_explicit_outputs:
            latest_dispatch = subtract_workdays(
                customer_day,
                int(output.get("subcontract_lead_time_days", 0) or 0),
                holidays,
            )
            while int(latest_dispatch) in holidays:
                latest_dispatch = int(latest_dispatch) - 1
        deadlines.append(int(latest_dispatch))

    return min(deadlines, default=expedition_day(lot))


def lot_material_release_day(
    lot: Lot,
    holidays: set[int],
    max_anticipation_workdays: int = JIT_MAX_ANTICIPATION_WORKDAYS,
) -> int:
    if lot.material_release_day is not None:
        return int(lot.material_release_day)
    return subtract_workdays(
        material_reference_day(lot, holidays),
        max_anticipation_workdays,
        holidays,
    )


def subtract_workdays(day_idx: int, days: int, holidays: set[int]) -> int:
    """Subtract workdays without clamping at the visible horizon.

    Negative indices represent real buffer dates before the first ISOP column.
    """

    current = int(day_idx)
    remaining = max(0, int(days))
    while remaining:
        current -= 1
        if current not in holidays:
            remaining -= 1
    return current


def add_workdays(day_idx: int, days: int, holidays: set[int]) -> int:
    """Add working days without assuming the visible horizon is the calendar."""

    current = int(day_idx)
    remaining = max(0, int(days))
    while remaining:
        current += 1
        if current not in holidays:
            remaining -= 1
    return current


def workdays_between(start_day: int, end_day: int, holidays: set[int]) -> int:
    """Count working days after ``start_day`` through ``end_day``."""

    if start_day >= end_day:
        return 0
    return sum(1 for day in range(start_day + 1, end_day + 1) if day not in holidays)


def earliest_allowed_start(
    lot: Lot,
    holidays: set[int],
    max_anticipation_workdays: int = JIT_MAX_ANTICIPATION_WORKDAYS,
) -> int:
    """Earliest productive start allowed for a lot."""

    return lot_material_release_day(lot, holidays, max_anticipation_workdays)


def productive_start_days(segments: list[Segment]) -> dict[str, int]:
    """First day containing productive minutes for every lot."""

    starts: dict[str, int] = {}
    for segment in segments:
        if segment.prod_min <= 0:
            continue
        starts[segment.lot_id] = min(
            starts.get(segment.lot_id, segment.day_idx),
            segment.day_idx,
        )
    return starts


def lot_floor_minutes(
    machine_runs: dict[str, list[ToolRun]],
    holidays: set[int],
    day_capacity_min: int,
) -> dict[str, float]:
    """Return absolute-minute productive floors for every scheduled lot."""

    return {
        lot.id: float(earliest_allowed_start(lot, holidays) * day_capacity_min)
        for runs in machine_runs.values()
        for run in runs
        for lot in run.lots
    }


def clamp_run_gates_to_window(
    machine_runs: dict[str, list[ToolRun]],
    gates: dict[str, float],
    lot_floors: dict[str, float],
) -> dict[str, float]:
    """Keep setup and production inside the material-availability window."""

    clamped = dict(gates)
    for runs in machine_runs.values():
        for run in runs:
            if not run.lots:
                continue
            first_floor = lot_floors.get(run.lots[0].id)
            if first_floor is not None:
                clamped[run.id] = max(clamped.get(run.id, first_floor), first_floor)
    return clamped


def window_violation_details(
    segments: list[Segment],
    lots: list[Lot],
    holidays: set[int],
) -> list[dict]:
    """Return deterministic lot-level violations of the fixed JIT window."""

    starts = productive_start_days(segments)
    first_segments: dict[str, Segment] = {}
    for segment in segments:
        if segment.prod_min <= 0:
            continue
        previous = first_segments.get(segment.lot_id)
        if previous is None or (segment.day_idx, segment.start_min) < (
            previous.day_idx,
            previous.start_min,
        ):
            first_segments[segment.lot_id] = segment

    lots_by_id = {lot.id: lot for lot in lots}
    campaign_lot_ids: dict[str, set[str]] = {}
    for lot_id, segment in first_segments.items():
        if lot_id not in lots_by_id:
            continue
        campaign_lot_ids.setdefault(segment.run_id, set()).add(lot_id)
    campaign_stats: dict[str, tuple[int, int]] = {}
    for run_id, lot_ids in campaign_lot_ids.items():
        deliveries = [
            material_reference_day(lots_by_id[lot_id], holidays) for lot_id in lot_ids
        ]
        span = (
            workdays_between(min(deliveries), max(deliveries), holidays)
            if deliveries
            else 0
        )
        campaign_stats[run_id] = (len(lot_ids), span)

    details: list[dict] = []
    for lot in lots:
        start_day = starts.get(lot.id)
        if start_day is None:
            continue
        delivery_day = expedition_day(lot)
        reference_day = material_reference_day(lot, holidays)
        floor_day = earliest_allowed_start(lot, holidays)
        if start_day >= floor_day:
            continue
        anticipation = workdays_between(start_day, reference_day, holidays)
        first = first_segments.get(lot.id)
        run_id = first.run_id if first is not None else ""
        campaign_count, campaign_span = campaign_stats.get(run_id, (1, 0))
        if start_day in holidays:
            reason_code = "non_workday_start"
            reason = (
                "Comecou num dia em que nao devia existir producao e ainda "
                "antes da data permitida."
            )
        elif (
            campaign_count > 1
            and campaign_span > JIT_MAX_ANTICIPATION_WORKDAYS
        ):
            reason_code = "campaign_span"
            reason = (
                f"Foi produzido juntamente com outros {campaign_count - 1} "
                "lotes para evitar outro setup. Como esses lotes saem em "
                "datas muito diferentes, este comecou cedo demais."
            )
        elif lot.is_twin:
            reason_code = "twin_sequence"
            reason = (
                "Foi antecipado juntamente com o artigo gemeo para aproveitar "
                "a mesma producao."
            )
        else:
            reason_code = "early_sequence"
            reason = (
                "O planeamento colocou esta producao antes da primeira data "
                "permitida."
            )
        excess = max(
            0,
            anticipation - JIT_MAX_ANTICIPATION_WORKDAYS,
        )
        details.append(
            {
                "lot_id": lot.id,
                "run_id": run_id,
                "op_id": lot.op_id,
                "sku": first.sku if first is not None else "",
                "machine_id": first.machine_id if first is not None else lot.machine_id,
                "tool_id": lot.tool_id,
                "qty": lot.qty,
                "is_twin": lot.is_twin,
                "delivery_day": delivery_day,
                "customer_delivery_day": delivery_day,
                "material_reference_day": reference_day,
                "material_reference_kind": material_reference_kind(lot),
                "production_due_day": production_due_day(lot, holidays),
                "subcontract_dispatch_day": subcontract_dispatch_day(lot, holidays),
                "start_day": start_day,
                "earliest_allowed_start_day": floor_day,
                "anticipation_workdays": anticipation,
                "allowed_anticipation_workdays": (
                    JIT_MAX_ANTICIPATION_WORKDAYS
                ),
                "excess_workdays": excess,
                "increment_workdays": excess,
                "reason_code": reason_code,
                "reason": reason,
                "campaign_lot_count": campaign_count,
                "campaign_span_workdays": campaign_span,
            }
        )
    return sorted(
        details,
        key=lambda item: (
            -item["excess_workdays"],
            item["material_reference_day"],
            item["lot_id"],
        ),
    )
