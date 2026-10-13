"""Quantity limits released by material, independent of machine duration."""

from collections import defaultdict
from dataclasses import dataclass, field, replace

from backend.scheduler.types import Lot, Segment


def output_release_day(output: dict) -> int:
    """Material release ``R`` of one lot output.

    The two outputs paired in one twin cycle share ``R_ciclo = min(R)``
    (``cycle_material_release_day``); every other output keeps its own ``R``.
    """

    shared = output.get("cycle_material_release_day")
    return int(shared if shared is not None else output["material_release_day"])


def lot_material_version(lot: Lot) -> int:
    """Material contract version recorded on the lot's outputs (0: none)."""

    return max(
        (
            int(output.get("quantity_material_version") or 0)
            for output in lot.output_milestones or []
        ),
        default=0,
    )


def whole_lot_release(lot: Lot) -> bool:
    """Economic lot = one production (material version 3, AGENTS §2).

    The whole lot is released at the lot ``R`` (its first delivery's, or
    ``R_ciclo`` of a twin cycle): one portion, one release day.
    """

    return lot_material_version(lot) >= 3


def twin_per_delivery(lot: Lot) -> bool:
    """A twin cycle under the per-delivery contract (material version 2)."""

    return bool(lot.is_twin) and lot_material_version(lot) == 2


def _twin_curve(lot: Lot, day: int) -> int:
    """Cycles released by ``day``: the larger of the two sides' released outputs.

    Every cycle makes one piece of each side, so a side's released quantity
    allows as many cycles; the other side's pieces are co-produced. A side
    whose output is only co-produced stock (no delivery of its own in the
    cycle) never drives the release: the cycle follows the other side.
    """

    by_side: dict[str, int] = defaultdict(int)
    for output in lot.output_milestones or []:
        if output.get("is_coproduced_surplus"):
            continue
        if output_release_day(output) <= day:
            by_side[str(output.get("op_id"))] += int(output["qty"])
    return min(int(lot.qty), max(by_side.values(), default=0))


def released_quantity(lot: Lot, day: int) -> int:
    if whole_lot_release(lot):
        return lot.qty if day >= (lot.material_release_day or 0) else 0
    if lot.is_twin and twin_per_delivery(lot):
        return _twin_curve(lot, day)
    # Legacy twin cycles (version 1) share material from their controlling output.
    if lot.is_twin or not lot.output_milestones:
        return lot.qty if day >= (lot.material_release_day or 0) else 0
    return min(
        lot.qty,
        sum(
            int(output["qty"])
            for output in lot.output_milestones
            if int(output["material_release_day"]) <= day
        ),
    )


def _driving_outputs(lot: Lot) -> list[dict]:
    """Outputs whose release can free production of the lot.

    Co-produced stock of a per-delivery twin cycle never drives the release.
    """

    outputs = list(lot.output_milestones or [])
    if twin_per_delivery(lot):
        return [output for output in outputs if not output.get("is_coproduced_surplus")]
    return outputs


def next_release_day(lot: Lot, day: int) -> int | None:
    if whole_lot_release(lot):
        release = int(lot.material_release_day or 0)
        return release if release > day else None
    days = [
        output_release_day(output)
        for output in _driving_outputs(lot)
        if output_release_day(output) > day
    ]
    return min(days) if days else None


@dataclass(frozen=True, slots=True)
class MaterialPortion:
    """Quantity of one economic lot released by material on the same day.

    ``outputs`` are the lot outputs (delivery records, in lot order) that the
    portion serves; their quantities add up to ``qty``. The economic surplus
    is released with the last delivery it follows, so it closes the last
    portion. Portions are a construction view: the lot is sized once and is
    never split into new lots (AGENTS §2-§3).
    """

    index: int
    qty: int
    material_release_day: int | None
    outputs: tuple[dict, ...] = field(compare=False)


def releases_in_portions(lot: Lot) -> bool:
    """Whether the lot's material is released in more than one portion.

    Twin cycles under the per-delivery contract count (their release curve,
    AGENTS §2). Such a lot needs a quantity-aware allocator: a single release
    floor would release pieces that are not yet available.
    """

    return len(lot.output_milestones or []) > 1 and len(material_portions(lot)) > 1


def material_portions(lot: Lot) -> list[MaterialPortion]:
    """Group consecutive outputs released on the same day.

    Lots with a single output, lots of material version 3 (released whole)
    and legacy twin cycles stay one portion; the
    surplus joins the last portion whatever its own record says. A twin cycle
    under the per-delivery contract has one portion per increment of its
    release curve (:func:`_twin_portions`).
    """

    outputs = list(lot.output_milestones or [])
    if twin_per_delivery(lot):
        return _twin_portions(lot)
    if lot.is_twin or len(outputs) <= 1 or whole_lot_release(lot):
        return [MaterialPortion(0, int(lot.qty), lot.material_release_day, tuple(outputs))]
    groups: list[tuple[object, list[dict]]] = []
    for output in outputs:
        release = output.get("material_release_day")
        if groups and (_is_surplus(output) or groups[-1][0] == release):
            groups[-1][1].append(output)
        else:
            groups.append((release, [output]))
    portions: list[MaterialPortion] = []
    assigned = 0
    for index, (release, members) in enumerate(groups):
        last = index == len(groups) - 1
        qty = int(lot.qty) - assigned if last else sum(int(item["qty"]) for item in members)
        assigned += qty
        portions.append(MaterialPortion(
            index, qty, int(release) if release is not None else None, tuple(members),
        ))
    return portions


def _twin_portions(lot: Lot) -> list[MaterialPortion]:
    """One portion per increment of a twin cycle's release curve.

    The portion released on day ``d`` holds ``curve(d) - curve(previous)``
    cycles. Its outputs are the slices of each side's deliveries (in side
    order, first-in-first-out) that those cycles make, with their quantities
    in pieces of that side; the side that is not driving the release gets
    co-produced pieces for its later deliveries.
    """

    outputs = list(lot.output_milestones or [])
    days = sorted({output_release_day(output) for output in _driving_outputs(lot)})
    by_side: dict[str, list[dict]] = defaultdict(list)
    for output in outputs:
        by_side[str(output.get("op_id"))].append(output)
    portions: list[MaterialPortion] = []
    previous = 0
    for position, day in enumerate(days):
        last = position == len(days) - 1
        current = int(lot.qty) if last else _twin_curve(lot, day)
        if current <= previous:
            continue
        members: list[dict] = []
        for side_outputs in by_side.values():
            start = 0
            for output in side_outputs:
                end = start + int(output["qty"])
                overlap = min(end, current) - max(start, previous)
                if overlap > 0:
                    members.append({**output, "qty": overlap})
                start = end
        portions.append(MaterialPortion(len(portions), current - previous, day, tuple(members)))
        previous = current
    if not portions:
        return [MaterialPortion(0, int(lot.qty), lot.material_release_day, tuple(outputs))]
    return portions


def output_completion_days(lot: Lot, segments: list[Segment], missing_day: int):
    """Factory day of each demand portion of one lot, not the lot end.

    Compatibility view of :func:`factory_readiness` (factory days only).
    """

    lot_segments = [segment for segment in segments if segment.lot_id == lot.id]
    return [
        (record.output, record.factory_day)
        for record in factory_readiness([lot], lot_segments, missing_day=missing_day)
        if record.is_demand
    ]


# ── Delivery readiness: the single evaluator of "when is each delivery ready"
#
# Every view (score, stock, orders, expedition, risks, late report,
# subcontracting, repair and optimiser heuristics) reads the readiness of an
# output from here. A delivery is ready when its own quantity exists, never
# when the whole economic lot ends; a subcontracted portion leaves when its
# own pieces are finished and is back after the subcontractor's lead time,
# counted in working days of the factory calendar (``data`` is required).
#
# Two readings, one allocation rule (FIFO in absolute time):
#
# - per lot (``delivery_readiness``): each lot's production serves that lot's
#   outputs. Lot metrics read it: ``tardy_count``/OTD ("Lotes no prazo"), the
#   late-lot report, production-due misses, repair and optimiser heuristics.
# - per delivery (``delivery_portions``): pieces of a SKU are fungible, so the
#   production of every lot of an operation serves its deliveries in due
#   order. Deliveries are judged per order (AGENTS §1.2): orders, OTD-D,
#   stock, subcontract dispatch, the gate's ``delivery_risk`` and the
#   improvement no-loss check read this one.
#
# Both agree whenever each lot is produced in due order. They differ when a
# later lot is produced before an earlier one: the earlier lot is "late" while
# no order is (the later lot's pieces serve it).
#
# Twin cycles are per delivery since Fase B2 (material version 2): each side's
# production serves that side's deliveries first-in-first-out, like any lot.
# Legacy lots without quantity material and twin cycles of version 1 keep the
# cycle rule: every output of the cycle completes with the lot
# (``cycle_rule``). Views may differ for them: lateness and subcontract
# readiness use the lot end, while stock, OTD-D and order coverage credit an
# in-house piece on the day it is produced.

_DAY_MINUTES = 1440


@dataclass(frozen=True, slots=True)
class OutputSlice:
    """Part of one segment's production assigned to one lot output."""

    segment_index: int
    day_idx: int
    end_min: int
    qty: int

    @property
    def abs_end(self) -> int:
        return self.day_idx * _DAY_MINUTES + self.end_min


@dataclass(frozen=True, slots=True)
class OutputReadiness:
    """When one output (delivery portion) of a lot is ready, from that lot alone.

    ``factory_day`` is the day its last piece is produced (``missing_day``
    when the plan does not produce it); ``customer_ready_day`` adds the
    subcontract lead time in working days for subcontracted outputs. It is
    ``None`` only in :func:`factory_readiness`, which has no calendar.
    """

    lot_id: str
    index: int
    op_id: str
    sku: str
    qty: int
    produced_qty: int
    is_demand: bool
    is_subcontracted: bool
    lead_workdays: int
    customer_delivery_day: int
    production_due_day: int
    internal_target_day: int | None
    subcontract_dispatch_day: int | None
    latest_subcontract_dispatch_day: int | None
    factory_day: int
    customer_ready_day: int | None
    complete: bool
    cycle_rule: bool
    slices: tuple[OutputSlice, ...]
    output: dict = field(compare=False, repr=False)

    @property
    def customer_delay(self) -> int:
        if self.customer_ready_day is None:
            raise ValueError("Readiness without the factory calendar has no customer day.")
        return self.customer_ready_day - self.customer_delivery_day

    @property
    def production_delay(self) -> int:
        return self.factory_day - self.production_due_day

    @property
    def planned_dispatch_day(self) -> int:
        """Planned subcontract dispatch (falls back to the production due day)."""

        if self.subcontract_dispatch_day is not None:
            return self.subcontract_dispatch_day
        return self.production_due_day


@dataclass(frozen=True, slots=True)
class PortionSlice:
    """Pieces of one segment that serve one delivery portion of an operation."""

    lot_id: str
    segment_index: int
    day_idx: int
    end_min: int
    available_day: int  # factory availability: ``day_idx``, or the lot end (cycle rule)
    qty: int


@dataclass(frozen=True, slots=True)
class DeliveryPortion:
    """One delivery of an operation, served first-in-first-out by all its lots.

    ``source`` is the lot output (milestones: due days, dispatch, company)
    the portion stands for; ``None`` for production beyond every delivery
    (economic surplus, stock).
    """

    op_id: str
    sku: str
    rank: int
    qty: int
    produced_qty: int
    is_demand: bool
    is_subcontracted: bool
    lead_workdays: int
    customer_delivery_day: int
    production_due_day: int
    subcontract_dispatch_day: int | None
    latest_subcontract_dispatch_day: int | None
    factory_day: int
    customer_ready_day: int
    complete: bool
    slices: tuple[PortionSlice, ...]
    source: OutputReadiness | None = field(default=None, compare=False, repr=False)

    @property
    def planned_dispatch_day(self) -> int | None:
        if self.source is None:
            return None
        if self.subcontract_dispatch_day is not None:
            return self.subcontract_dispatch_day
        return self.production_due_day

    @property
    def lot_ids(self) -> list[str]:
        return list(dict.fromkeys(item.lot_id for item in self.slices))

    @property
    def completing_lot_id(self) -> str | None:
        """Lot whose pieces complete the portion (latest available slice)."""

        if not self.slices:
            return self.source.lot_id if self.source is not None else None
        last = max(self.slices, key=lambda item: (item.available_day,
                                                  item.day_idx * _DAY_MINUTES + item.end_min,
                                                  item.segment_index))
        return last.lot_id

    def credits(self, *, customer: bool = True) -> list[tuple[int, int]]:
        """(day, qty) when this portion's pieces become available.

        Factory availability follows each produced piece. Customer
        availability is the same for in-house outputs; a subcontracted
        portion returns as a whole, ``lead`` working days after it leaves.
        """

        if not customer or not self.is_subcontracted:
            return [(item.day_idx, item.qty) for item in self.slices]
        if not self.produced_qty:
            return []
        return [(self.customer_ready_day, self.produced_qty)]


def readiness_holidays(lots, segments, data) -> set[int]:
    """Factory holidays covering the plan, its history and every return trip."""

    from backend.scheduler.jit_policy import calendar_holidays, lot_output_milestones

    if data is None:
        raise ValueError("Delivery readiness needs the factory calendar (EngineData).")
    first_day = min(
        [
            0,
            *(segment.day_idx for segment in segments),
            *(lot.material_release_day for lot in lots if lot.material_release_day is not None),
        ]
    )
    max_lead = max(
        (
            int(output.get("subcontract_lead_time_days", 0) or 0)
            for lot in lots
            for output in lot_output_milestones(lot)
        ),
        default=0,
    )
    return calendar_holidays(data, first_day - 14, data.n_days + max_lead * 2 + 14)


def _is_surplus(output: dict) -> bool:
    return bool(output.get("is_coproduced_surplus") or output.get("is_economic_surplus"))


def _segment_output_quantities(lot: Lot, segment: Segment) -> list[tuple[str, str, int]]:
    if segment.twin_outputs:
        return [(str(op), str(sku), int(qty)) for op, sku, qty in segment.twin_outputs]
    return [(lot.op_id, segment.sku or lot.sku, int(segment.qty))]


def delivery_readiness(
    lots: list[Lot],
    segments: list[Segment],
    data,
    *,
    missing_day: int | None = None,
    extra_lead: dict[str, int] | None = None,
) -> list[OutputReadiness]:
    """Readiness of every lot output, in lot order then output order.

    Production of each lot is assigned to its outputs first-in-first-out by
    absolute end time (``day * 1440 + end_min``, then segment order) and per
    operation (each side of a twin cycle is its own operation). Legacy lots
    without quantity material and twin cycles of version 1 keep the cycle
    rule: every output completes with the lot.
    ``data`` (required) supplies the factory calendar for subcontract lead
    times and the default ``missing_day`` (the horizon end). ``extra_lead``
    adds working days to a lot's subcontract return (robustness scenarios).
    """

    holidays = readiness_holidays(lots, segments, data)
    if missing_day is None:
        missing_day = int(data.n_days)
    return _readiness(lots, segments, holidays, missing_day, extra_lead or {})


def factory_readiness(
    lots: list[Lot],
    segments: list[Segment],
    *,
    missing_day: int,
) -> list[OutputReadiness]:
    """Factory side of :func:`delivery_readiness` for callers without a calendar.

    Only ``factory_day``, ``slices`` and the output milestones are meaningful;
    ``customer_ready_day`` is ``None`` so that no caller can read a customer
    day counted on calendar days by mistake.
    """

    return _readiness(lots, segments, None, missing_day, {})


def _readiness(
    lots: list[Lot],
    segments: list[Segment],
    holidays: set[int] | None,
    missing_day: int,
    extra_lead: dict[str, int],
) -> list[OutputReadiness]:
    from backend.scheduler.jit_policy import (
        add_workdays,
        expedition_day,
        lot_output_milestones,
        production_due_day,
    )

    by_lot: dict[str, list[tuple[int, Segment]]] = defaultdict(list)
    for index, segment in enumerate(segments):
        by_lot[segment.lot_id].append((index, segment))

    records: list[OutputReadiness] = []
    for lot in lots:
        ordered = sorted(
            by_lot.get(lot.id, []),
            key=lambda item: (item[1].day_idx * _DAY_MINUTES + item[1].end_min, item[0]),
        )
        outputs = lot_output_milestones(lot)
        version = max(
            (int(output.get("quantity_material_version") or 0) for output in outputs),
            default=0,
        )
        cycle_rule = version == 0 or (lot.is_twin and version < 2)
        lot_completion = max(
            (segment.day_idx for _, segment in ordered if segment.qty > 0),
            default=None,
        )
        # Outputs of each operation, demand first (surplus closes the lot).
        indexed = list(enumerate(outputs))
        by_op: dict[str, list[tuple[int, dict]]] = defaultdict(list)
        for position, output in sorted(indexed, key=lambda item: (_is_surplus(item[1]), item[0])):
            by_op[str(output.get("op_id", lot.op_id))].append((position, output))
        produced: dict[str, list[OutputSlice]] = defaultdict(list)
        sku_by_op: dict[str, str] = {}
        for index, segment in ordered:
            for op_id, sku, qty in _segment_output_quantities(lot, segment):
                if qty > 0:
                    produced[op_id].append(
                        OutputSlice(index, segment.day_idx, segment.end_min, qty)
                    )
                    sku_by_op.setdefault(op_id, sku)
        for op_id in produced:
            if op_id not in by_op:
                # Production without a declared output stays visible as stock.
                synthetic = {"op_id": op_id, "sku": sku_by_op[op_id], "qty": 0,
                             "is_economic_surplus": True}
                by_op[op_id].append((len(outputs) + len(by_op), synthetic))

        lot_records: list[OutputReadiness] = []
        for op_id, op_outputs in by_op.items():
            queue = list(produced.get(op_id, []))
            cursor = 0
            remaining_in_slice = queue[0].qty if queue else 0
            for rank, (position, output) in enumerate(op_outputs):
                need = max(0, int(output.get("qty", 0) or 0))
                last = rank == len(op_outputs) - 1
                slices: list[OutputSlice] = []
                taken = 0
                while cursor < len(queue) and (taken < need or last):
                    source = queue[cursor]
                    amount = remaining_in_slice if last else min(remaining_in_slice, need - taken)
                    if amount > 0:
                        slices.append(OutputSlice(
                            source.segment_index, source.day_idx, source.end_min, amount,
                        ))
                        taken += amount
                        remaining_in_slice -= amount
                    if remaining_in_slice == 0:
                        cursor += 1
                        remaining_in_slice = queue[cursor].qty if cursor < len(queue) else 0
                complete = taken >= need
                if cycle_rule:
                    factory_day = lot_completion if lot_completion is not None else missing_day
                elif complete:
                    factory_day = max(
                        (item.day_idx for item in slices),
                        default=lot_completion if lot_completion is not None else missing_day,
                    )
                else:
                    factory_day = missing_day
                subcontracted = bool(output.get("is_subcontracted"))
                lead = int(output.get("subcontract_lead_time_days", 0) or 0)
                if holidays is None:
                    ready = None
                elif subcontracted:
                    ready = add_workdays(
                        factory_day, lead + int(extra_lead.get(lot.id, 0)), holidays
                    )
                else:
                    ready = factory_day
                dispatch = output.get("subcontract_dispatch_day")
                latest = output.get("latest_subcontract_dispatch_day")
                target = output.get("internal_target_day")
                lot_records.append(OutputReadiness(
                    lot_id=lot.id,
                    index=position,
                    op_id=op_id,
                    sku=str(output.get("sku", lot.sku) or sku_by_op.get(op_id, "")),
                    qty=need,
                    produced_qty=taken,
                    is_demand=not _is_surplus(output),
                    is_subcontracted=subcontracted,
                    lead_workdays=lead,
                    customer_delivery_day=int(
                        output.get("customer_delivery_day", expedition_day(lot))
                    ),
                    production_due_day=int(
                        output.get("production_due_day", production_due_day(lot, holidays))
                    ),
                    internal_target_day=int(target) if target is not None else None,
                    subcontract_dispatch_day=int(dispatch) if dispatch is not None else None,
                    latest_subcontract_dispatch_day=int(latest) if latest is not None else None,
                    factory_day=int(factory_day),
                    customer_ready_day=int(ready) if ready is not None else None,
                    complete=complete,
                    cycle_rule=cycle_rule,
                    slices=tuple(slices),
                    output=output,
                ))
        lot_records.sort(key=lambda record: record.index)
        records.extend(lot_records)
    return records


def delivery_portions(
    lots: list[Lot],
    segments: list[Segment],
    data,
    *,
    records: list[OutputReadiness] | None = None,
    missing_day: int | None = None,
) -> list[DeliveryPortion]:
    """Readiness of every delivery of every operation, across all its lots.

    Pieces of a SKU are fungible: the production of all lots of an operation
    serves its demand outputs in due order (customer day, production due
    day, lot order), first-in-first-out by availability then absolute time.
    A subcontracted delivery leaves when its own pieces are complete and is
    back ``lead`` working days later. Production beyond every delivery forms
    one surplus portion per operation and lot. Same calendar and ``missing_day`` as
    :func:`delivery_readiness`; ``records`` reuses an already computed one.
    """

    from backend.scheduler.jit_policy import add_workdays

    holidays = readiness_holidays(lots, segments, data)
    if missing_day is None:
        missing_day = int(data.n_days)
    if records is None:
        records = _readiness(lots, segments, holidays, missing_day, {})

    lot_order = {lot.id: position for position, lot in enumerate(lots)}
    by_op: dict[str, list[OutputReadiness]] = defaultdict(list)
    for record in records:
        by_op[record.op_id].append(record)

    portions: list[DeliveryPortion] = []
    for op_id, op_records in by_op.items():
        events = sorted(
            (
                PortionSlice(
                    record.lot_id,
                    item.segment_index,
                    item.day_idx,
                    item.end_min,
                    record.factory_day if record.cycle_rule else item.day_idx,
                    item.qty,
                )
                for record in op_records
                for item in record.slices
            ),
            key=lambda item: (item.available_day, item.day_idx * _DAY_MINUTES + item.end_min,
                              item.segment_index),
        )
        demand = sorted(
            (record for record in op_records if record.is_demand),
            key=lambda record: (record.customer_delivery_day, record.production_due_day,
                                lot_order.get(record.lot_id, len(lot_order)), record.index),
        )
        subcontracted_op = any(record.is_subcontracted for record in op_records)
        lead_op = max((record.lead_workdays for record in op_records), default=0)
        sku = next((record.sku for record in op_records if record.sku), "")
        cursor = 0
        left = events[0].qty if events else 0

        def take(need: int | None) -> list[PortionSlice]:
            nonlocal cursor, left
            taken: list[PortionSlice] = []
            got = 0
            while cursor < len(events) and (need is None or got < need):
                event = events[cursor]
                amount = left if need is None else min(left, need - got)
                if amount > 0:
                    taken.append(replace(event, qty=amount))
                    got += amount
                    left -= amount
                if left == 0:
                    cursor += 1
                    left = events[cursor].qty if cursor < len(events) else 0
            return taken

        for rank, record in enumerate(demand):
            slices = take(record.qty)
            produced_qty = sum(item.qty for item in slices)
            complete = produced_qty >= record.qty
            if record.cycle_rule:
                # Cycle rule (twins, legacy lots): ready with the pieces it
                # takes, each at its lot's end, as in ``delivery_readiness``.
                factory_day = max(
                    (item.available_day for item in slices), default=record.factory_day
                )
            elif not complete:
                factory_day = missing_day
            elif slices:
                factory_day = max(item.available_day for item in slices)
            else:
                factory_day = record.factory_day
            ready = (
                add_workdays(factory_day, record.lead_workdays, holidays)
                if record.is_subcontracted
                else factory_day
            )
            portions.append(DeliveryPortion(
                op_id=op_id,
                sku=record.sku or sku,
                rank=rank,
                qty=record.qty,
                produced_qty=produced_qty,
                is_demand=True,
                is_subcontracted=record.is_subcontracted,
                lead_workdays=record.lead_workdays,
                customer_delivery_day=record.customer_delivery_day,
                production_due_day=record.production_due_day,
                subcontract_dispatch_day=record.subcontract_dispatch_day,
                latest_subcontract_dispatch_day=record.latest_subcontract_dispatch_day,
                factory_day=int(factory_day),
                customer_ready_day=int(ready),
                complete=complete,
                slices=tuple(slices),
                source=record,
            ))
        # Production beyond every delivery (economic or co-produced surplus):
        # one portion per lot, so a subcontracted surplus returns with its own
        # lot's pieces and never waits for a later lot.
        rest_by_lot: dict[str, list[PortionSlice]] = defaultdict(list)
        for item in take(None):
            rest_by_lot[item.lot_id].append(item)
        for offset, rest in enumerate(rest_by_lot.values()):
            factory_day = max(item.available_day for item in rest)
            ready = (
                add_workdays(factory_day, lead_op, holidays) if subcontracted_op else factory_day
            )
            portions.append(DeliveryPortion(
                op_id=op_id,
                sku=sku,
                rank=len(demand) + offset,
                qty=0,
                produced_qty=sum(item.qty for item in rest),
                is_demand=False,
                is_subcontracted=subcontracted_op,
                lead_workdays=lead_op,
                customer_delivery_day=factory_day,
                production_due_day=factory_day,
                subcontract_dispatch_day=None,
                latest_subcontract_dispatch_day=None,
                factory_day=int(factory_day),
                customer_ready_day=int(ready),
                complete=True,
                slices=tuple(rest),
            ))
    return portions


def readiness_by_lot(records: list[OutputReadiness]) -> dict[str, list[OutputReadiness]]:
    grouped: dict[str, list[OutputReadiness]] = defaultdict(list)
    for record in records:
        grouped[record.lot_id].append(record)
    return grouped


def production_by_op(
    portions: list[DeliveryPortion],
    *,
    customer: bool = True,
) -> dict[str, dict[int, int]]:
    """Quantity available per (op_id, day) from the delivery portions."""

    result: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for portion in portions:
        for day, qty in portion.credits(customer=customer):
            result[portion.op_id][day] += qty
    return result


def lot_customer_delays(records: list[OutputReadiness]) -> dict[str, int]:
    """Worst customer delay (days) over the demand outputs of each lot."""

    delays: dict[str, int] = {}
    for record in records:
        if record.is_demand:
            delays[record.lot_id] = max(delays.get(record.lot_id, record.customer_delay),
                                        record.customer_delay)
    return delays


def lot_production_delays(records: list[OutputReadiness]) -> dict[str, int]:
    """Worst factory delay (days) against each demand output's production due day."""

    delays: dict[str, int] = {}
    for record in records:
        if record.is_demand:
            delays[record.lot_id] = max(delays.get(record.lot_id, record.production_delay),
                                        record.production_delay)
    return delays


def segment_production_delays(
    records: list[OutputReadiness],
    segments: list[Segment],
) -> list[int | None]:
    """Worst factory delay of the demand outputs each segment produces for.

    ``None`` for segments that feed no demand output (setup-only blocks,
    economic surplus).
    """

    result: list[int | None] = [None] * len(segments)
    for record in records:
        if not record.is_demand:
            continue
        for item in record.slices:
            current = result[item.segment_index]
            delay = record.production_delay
            result[item.segment_index] = delay if current is None else max(current, delay)
    return result
