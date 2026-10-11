"""Canonical planning policy: how "earlier" is measured (AGENTS.md §1).

One place for the anticipation measure shared by the improvement evaluator,
the CPO ranks, the local neighbourhoods, the builder and the explanations.
Transfers and plan disturbance rank after it, in
``improvement.improvement_key``. Bump ``POLICY_VERSION`` with any change.

Per delivery (policy v3, Fase B3): an economic lot that covers several
deliveries releases each one on its own ``R`` (AGENTS §2, "Janela por
entrega"), so "earlier" is measured per (lot, output): the production
start and finish of the pieces of each delivery, assigned first in first
out by cumulative quantity (``output_windows``). Elements are ranked by the
commercial priority of the delivery (``priority.output_priority_key``). A
lot with at most one delivery per operation (side) is one element, exactly
as before: its window is the whole lot and it ranks by ``lot_priority_key``.
The economic surplus and co-produced stock are never elements of their own
and never move a delivery's window: each delivery finishes when its own
pieces are made, its readiness (``material_quantities.delivery_readiness``).

Tolerance (decision of 05/10/2026): a difference smaller than
``ANTICIPATION_TOLERANCE_MIN`` does not decide between elements. One may
only start or finish that much later when a more urgent one gains at least
as much. The tolerant comparison is not transitive: callers compare against
both the current and the reference plan.

Setups inside the tolerance (decision of 10/10/2026): when no element moves
by the tolerance or more, fewer setups and then fewer setup minutes decide
*before* the exact minutes (``tolerant_tiebreak``). A mounted tool therefore
keeps running even when a more urgent lot wants the machine, as long as that
lot loses less than ``ANTICIPATION_TOLERANCE_MIN``. Exact minutes still break
the remaining ties, so small gains are taken when nothing larger is at stake.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from backend.scheduler.material_quantities import lot_material_version
from backend.scheduler.priority import output_priority_key
from backend.scheduler.types import Lot, Segment

POLICY_VERSION = "per-output-earliest-lexicographic-tolerant-setups-v3"
ANTICIPATION_TOLERANCE_MIN = 60.0
_MISSING = math.inf
_DAY = 1440.0

# Per element, in commercial priority order: (element id, production start,
# production finish) in absolute plan minutes. The element id is the lot id
# for a lot measured as a whole and ``"<lot id>#<output position>"`` for one
# delivery of a lot measured per output. Missing production ranks last.
type AnticipationKey = tuple[tuple[str, float, float], ...]


def production_windows(segments: Iterable[Segment]) -> dict[str, tuple[float, float]]:
    """First productive minute and end of production per lot, absolute minutes.

    Setup minutes are excluded from the start: a lot "starts" when it starts
    producing. Duration enters only through the finish, so a slower machine
    cannot win merely by having fewer productive minutes.
    """

    windows: dict[str, tuple[float, float]] = {}
    for segment in segments:
        if segment.prod_min <= 0:
            continue
        base = float(segment.day_idx) * _DAY
        start = base + float(segment.start_min) + max(0.0, float(segment.setup_min))
        end = base + float(segment.end_min)
        before = windows.get(segment.lot_id)
        windows[segment.lot_id] = (
            (start, end) if before is None else (min(before[0], start), max(before[1], end))
        )
    return windows


def _is_surplus(output: dict) -> bool:
    return bool(output.get("is_coproduced_surplus") or output.get("is_economic_surplus"))


def _output_op(lot: Lot, output: dict) -> str:
    return str(output.get("op_id") or lot.op_id)


def measured_outputs(lot: Lot) -> list[int] | None:
    """Positions of the deliveries measured on their own, or ``None``.

    ``None`` (the lot is one element, as in policy v2) for lots without
    per-delivery material (legacy, or twin cycles of material version 1,
    which release the whole cycle at once) and for lots with at most one
    delivery per operation. Otherwise every demand output of every side,
    in lot order; surplus and co-produced stock are left out.
    """

    outputs = lot.output_milestones or []
    if len(outputs) < 2:
        return None
    version = lot_material_version(lot)
    if not version or (lot.is_twin and version < 2):
        return None
    demand = [index for index, output in enumerate(outputs) if not _is_surplus(output)]
    per_op: dict[str, int] = defaultdict(int)
    for index in demand:
        per_op[_output_op(lot, outputs[index])] += 1
    if not per_op or max(per_op.values()) < 2:
        return None
    return demand


def element_id(lot: Lot, index: int | None) -> str:
    return str(lot.id) if index is None else f"{lot.id}#{index}"


@dataclass(frozen=True, slots=True)
class AnticipationOrder:
    """Elements of the anticipation vector in commercial priority order.

    Depends only on the lots (never on the plan), so it is computed once
    per scenario and reused for every candidate (``anticipation_key``).
    ``elements`` holds (element id, lot id); ``measured`` the output
    positions of each lot measured per delivery.
    """

    elements: tuple[tuple[str, str], ...]
    measured: dict[str, tuple[int, ...]]


def _delivery_quantities(lots: Iterable[Lot]) -> dict[tuple[str, object], int]:
    """Quantity of each customer delivery (operation, customer day), all lots."""

    totals: dict[tuple[str, object], int] = defaultdict(int)
    for lot in lots:
        for output in lot.output_milestones or []:
            if not _is_surplus(output):
                totals[(_output_op(lot, output), output.get("customer_delivery_day"))] += int(
                    output.get("qty") or 0
                )
    return totals


def anticipation_order(lots: Iterable[Lot]) -> AnticipationOrder:
    """The canonical order of the anticipation elements of ``lots``.

    A delivery ranks with the quantity of the customer delivery it serves
    over every lot of the operation (pieces are fungible), as the builder
    ranks a portion (AGENTS §2, "Prioridade de uma parte").
    """

    lots = list(lots)
    quantities: dict[tuple[str, object], int] | None = None
    ranked: list[tuple[tuple, str, str]] = []
    measured: dict[str, tuple[int, ...]] = {}
    for lot in lots:
        positions = measured_outputs(lot)
        if positions is None:
            ranked.append((output_priority_key(lot), element_id(lot, None), lot.id))
            continue
        if quantities is None:
            quantities = _delivery_quantities(lots)
        measured[lot.id] = tuple(positions)
        outputs = lot.output_milestones or []
        for index in positions:
            output = outputs[index]
            delivery = quantities.get(
                (_output_op(lot, output), output.get("customer_delivery_day")), 0,
            )
            key = output_priority_key(
                lot, index, delivery_qty=max(delivery, int(output.get("qty") or 0)),
            )
            ranked.append((key, element_id(lot, index), lot.id))
    ranked.sort(key=lambda item: item[0])
    return AnticipationOrder(
        tuple((element, lot_id) for _key, element, lot_id in ranked), measured,
    )


def _segment_quantities(lot: Lot, segment: Segment) -> list[tuple[str, int]]:
    if segment.twin_outputs:
        return [(str(op_id), int(qty)) for op_id, _sku, qty in segment.twin_outputs]
    return [(str(lot.op_id), int(segment.qty))]


def _delivery_windows(
    lot: Lot, positions: Iterable[int], items: list[tuple[int, Segment]],
) -> dict[str, tuple[float, float]]:
    """Window of each measured delivery of one lot, first in first out.

    Pieces of each side are assigned to that side's deliveries in lot order
    by absolute end time (then segment order), the rule of
    ``material_quantities.delivery_readiness``. A delivery starts at the
    first productive minute of the first segment making its pieces and
    finishes at the end of the segment making its last piece, so its finish
    is its readiness. The pieces of a surplus output (economic or
    co-produced) belong to no delivery: making them later delays nothing.
    As in ``delivery_readiness``, a side without a surplus output gives its
    remaining pieces to its last delivery. A delivery not fully produced
    finishes never (``inf``).
    """

    outputs = lot.output_milestones or []
    sides_with_surplus = {
        _output_op(lot, output) for output in outputs if _is_surplus(output)
    }
    produced: dict[str, list[list[float]]] = defaultdict(list)
    for _index, segment in sorted(
        items, key=lambda item: (item[1].day_idx * _DAY + item[1].end_min, item[0]),
    ):
        base = float(segment.day_idx) * _DAY
        start = base + float(segment.start_min) + max(0.0, float(segment.setup_min))
        end = base + float(segment.end_min)
        for op_id, qty in _segment_quantities(lot, segment):
            if qty > 0:
                produced[op_id].append([float(qty), start, end])
    by_op: dict[str, list[int]] = defaultdict(list)
    for index in positions:
        by_op[_output_op(lot, outputs[index])].append(index)
    windows: dict[str, tuple[float, float]] = {}
    for op_id, indexes in by_op.items():
        queue = produced.get(op_id, [])
        cursor = 0
        left = queue[0][0] if queue else 0.0
        for rank, index in enumerate(indexes):
            need = float(max(0, int(outputs[index].get("qty") or 0)))
            last = rank == len(indexes) - 1 and op_id not in sides_with_surplus
            start = finish = _MISSING
            taken = 0.0
            while cursor < len(queue) and (taken < need or last):
                amount = left if last else min(left, need - taken)
                if amount > 0:
                    _qty, piece_start, piece_end = queue[cursor]
                    start = min(start, piece_start)
                    finish = piece_end if finish == _MISSING else max(finish, piece_end)
                    taken += amount
                    left -= amount
                if left <= 0:
                    cursor += 1
                    left = queue[cursor][0] if cursor < len(queue) else 0.0
            windows[element_id(lot, index)] = (
                start, finish if taken >= need and need > 0 else _MISSING,
            )
    return windows


def output_windows(
    segments: Iterable[Segment],
    lots: Iterable[Lot],
    *,
    order: AnticipationOrder | None = None,
) -> dict[str, tuple[float, float]]:
    """Production window of every anticipation element, by element id.

    Lots measured per delivery (``measured_outputs``) get one window per
    demand output (``_delivery_windows``); every other lot keeps its whole
    production window (``production_windows``) under its own id.
    """

    lots = list(lots)
    measured = (
        order.measured if order is not None
        else {
            lot.id: tuple(positions) for lot in lots
            if (positions := measured_outputs(lot)) is not None
        }
    )
    plain: list[Segment] = []
    per_lot: dict[str, list[tuple[int, Segment]]] = defaultdict(list)
    for index, segment in enumerate(segments):
        if segment.lot_id in measured:
            if segment.prod_min > 0:
                per_lot[segment.lot_id].append((index, segment))
        else:
            plain.append(segment)
    windows = production_windows(plain)
    for lot in lots:
        positions = measured.get(lot.id)
        if positions is not None:
            windows.update(_delivery_windows(lot, positions, per_lot.get(lot.id, [])))
    return windows


def anticipation_key(
    segments: Iterable[Segment],
    lots: Iterable[Lot],
    *,
    order: AnticipationOrder | None = None,
    lot_ids: Collection[str] | None = None,
) -> AnticipationKey:
    """Lexicographic anticipation vector, smaller is earlier.

    Elements (lots, or deliveries of lots measured per output) are ordered
    by the canonical commercial priority, so advancing a less urgent
    delivery never compensates delaying a more urgent one. The material
    release ``R`` of an element is the same in every candidate of one
    scenario, so comparing ``S`` and ``F`` is comparing ``S-R`` and ``F-R``.
    Only meaningful between candidates with the same lots.

    ``order`` (``anticipation_order(lots)``) may be passed to reuse it;
    ``lot_ids`` restricts the vector to those lots' elements, in the same
    global order (pre-checks of a local move compare only what it touches).
    """

    lots = list(lots)
    order = order if order is not None else anticipation_order(lots)
    if lot_ids is not None:
        wanted = set(lot_ids)
        segments = [segment for segment in segments if segment.lot_id in wanted]
        lots = [lot for lot in lots if lot.id in wanted]
        elements = [item for item in order.elements if item[1] in wanted]
    else:
        elements = list(order.elements)
    windows = output_windows(segments, lots, order=order)
    return tuple(
        (element, *windows.get(element, (_MISSING, _MISSING))) for element, _lot in elements
    )


def anticipation_compare(
    candidate, reference, tolerance: float = ANTICIPATION_TOLERANCE_MIN,
) -> int:
    """-1 if ``candidate`` is earlier, 1 if later, 0 if no difference reaches
    ``tolerance``. Elements end with (start, finish); both vectors list the
    same lots in the same order."""

    for left, right in zip(candidate, reference, strict=True):
        for a, b in ((left[-2], right[-2]), (left[-1], right[-1])):
            if a == b:
                continue
            if math.isinf(a) or math.isinf(b) or abs(a - b) >= tolerance:
                return -1 if a < b else 1
    return 0


def anticipation_better(
    candidate, reference, tolerance: float = ANTICIPATION_TOLERANCE_MIN,
) -> bool:
    """Tolerant comparison first, exact lexicographic minutes as tie-break.

    Ignores setups, so it is only for plans with the same setups; every
    decision between plans uses ``tolerant_better`` (contract v3).
    """

    decided = anticipation_compare(candidate, reference, tolerance)
    if decided:
        return decided < 0
    return tuple(item[-2:] for item in candidate) < tuple(item[-2:] for item in reference)


def anticipation_exact(key) -> tuple[tuple[float, float], ...]:
    """The exact (start, finish) minutes of an anticipation vector."""

    return tuple(item[-2:] for item in key)


def tolerant_tiebreak(anticipation, setups: tuple[float, ...]) -> tuple[object, ...]:
    """Order among plans the tolerant comparison does not separate (v3).

    ``setups`` is (count, minutes): a setup saved outranks any gain smaller
    than the tolerance; exact minutes decide only between equal setups.
    """

    return (*setups, anticipation_exact(anticipation))


def tolerant_better(
    candidate_anticipation,
    reference_anticipation,
    candidate_setups: tuple[float, ...],
    reference_setups: tuple[float, ...],
    candidate_rest: tuple[object, ...] = (),
    reference_rest: tuple[object, ...] = (),
) -> bool:
    """The one canonical preference after physics and delivery (contract v3).

    1. anticipation with the tolerance (a lot may lose ``tolerance`` or more
       only if a more urgent lot gains as much);
    2. inside the tolerance, fewer setups, then fewer setup minutes
       (``setups`` is (count, minutes));
    3. then the exact anticipation minutes;
    4. then ``rest`` (transfers, disturbance or caller proxies).

    Anticipation vectors may hold (lot, start, finish) or (start, finish)
    items; both sides must list the same lots in the same order. The
    improvement evaluator, the CPO ranks and every pre-check before
    validation use this function, so they never disagree.
    """

    decided = anticipation_compare(candidate_anticipation, reference_anticipation)
    if decided:
        return decided < 0
    return (
        *tolerant_tiebreak(candidate_anticipation, candidate_setups), *candidate_rest,
    ) < (
        *tolerant_tiebreak(reference_anticipation, reference_setups), *reference_rest,
    )
