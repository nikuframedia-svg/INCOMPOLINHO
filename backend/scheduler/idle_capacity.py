"""Late deliveries with idle machine time before their deadline (read-only).

A plan that leaves a delivery late while an eligible machine stands idle
inside that delivery's material window is not a capacity shortage: the plan
can be improved (revision 127, 13/10/2026: PRM043 idle from 13 to 18/10 with
two late deliveries). This module only reads a plan; it never changes,
orders or blocks one. The gate report lists its cases, the screen shows a
plain notice, and a capacity-release replan uses it to decide whether to
also try the full constructor (AGENTS §6).

Deliveries are judged as everywhere else (AGENTS §1.2, §2):

* late orders come from the canonical order evaluator
  (``improvement.order_service``); the shortfall is the quantity not covered
  on the customer day. Subcontracted deliveries are judged the same way, on
  the stock shown on Entregas (Luís, 14/10/2026), with the customer day as
  their deadline;
* only for the replan job (``dispatch_targets``, never shown): a
  subcontracted delivery that leaves after its latest compatible dispatch
  ``H`` is a case too, the planner's aim of finishing it before the
  dispatch. The shortfall is what is not ready to leave by ``H``; a lot that
  goes out whole (material version 3, 13/10/2026) leaves when its last piece
  is made, so the lot has to end by ``H`` of its first delivery.

The late deliveries of one lot (both sides of a twin cycle, several orders)
are one case, listed once: the lot is a case when its late deliveries up to
some deadline can all be served by that deadline (pieces go
first-in-first-out), from ``max(planning day, material release R)`` on. Free time is
``backend.calendar.free_shift_intervals`` (the same definition as rule 4's
contiguity): shift time of factory working days, minus machine and tool
unavailabilities, the plan's segments on the machine, the tool at work on
another machine and time without enough operators of the machine's group;
pieces shorter than ``MIN_FREE_INTERVAL_MIN`` do not count. On the planning
day only the time after the current factory minute counts.

The minutes needed follow the planning rules:

* on a machine the lot already uses, the shortfall at the lot's rate, or —
  when its pieces are only available at the lot end (cycle rule; a
  subcontracted lot that goes out whole, for ``dispatch_targets``) — the
  rest of the lot not produced by the deadline;
* on an alternative machine (rule 3), the whole lot at that machine's rate:
  a lot changes machine as a whole. A lot with production on the planning
  day or before has started (rule 4) and only counts its own machine;
* plus one setup, none when the same setup is mounted on the machine just
  before the free time.

A lot is a case when the free minutes reach the minutes needed. Lots are
taken in deadline order and a case claims the minutes it needs, so two late
lots never count the same idle time.

It is a rough check, not a schedule: the setup crew, the setup-in-one-shift
rule and the moves needed to use the time are not modelled.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from backend import calendar as factory_calendar
from backend.calendar import (
    MIN_FREE_INTERVAL_MIN,
    current_factory_day,
    elapsed_minutes,
    free_shift_intervals,
)
from backend.config.types import FactoryConfig
from backend.scheduler.material_quantities import delivery_portions, output_release_day
from backend.scheduler.resources import clone_run_for_machine
from backend.scheduler.setup_identity import lot_setup_identity, segment_setup_identity
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.types import EngineData

__all__ = ["MIN_FREE_INTERVAL_MIN", "idle_capacity_notice", "late_with_idle_capacity"]
CLAIM_LOT_ID = "__idle_capacity_claim__"


@dataclass(slots=True)
class _Delivery:
    sku: str
    customer_delivery_day: int
    clients: set[str]
    order_shortfall: int


def late_with_idle_capacity(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData | None,
    config: FactoryConfig | None,
    *,
    planning_day: int | None = None,
    service=None,
    now: datetime | None = None,
    dispatch_targets: bool = False,
) -> list[dict]:
    """Late lots whose deliveries idle shift time on an eligible machine could serve.

    ``planning_day`` is the first day that can still be planned (default:
    today in the factory calendar); ``now`` replaces the factory clock (on
    the planning day only the time after it is free); ``service`` reuses an
    already computed ``order_service``. One case per lot, naming its late
    deliveries, their window and the machine with the most spare time.
    ``dispatch_targets`` also counts missed subcontract dispatches (the
    replan job's aim; never for the gate report or the screen).
    """

    if data is None or not data.ops:
        return []
    if service is None:
        from backend.scheduler.improvement import order_service

        service = order_service(segments, lots, data)
    deliveries: dict[tuple[str, int], _Delivery] = {}
    for (sku, client, due_day, order_qty, _np, _occ), item in service.items():
        if item.tardiness <= 0:
            continue
        delivery = deliveries.setdefault(
            (sku, int(due_day)), _Delivery(sku, int(due_day), set(), 0),
        )
        delivery.clients.add(str(client))
        delivery.order_shortfall += max(0, int(order_qty) - int(item.covered_qty))

    portions_by_delivery = defaultdict(list)
    for portion in delivery_portions(lots, segments, data):
        if not portion.is_demand or portion.source is None:
            continue
        key = (portion.sku, int(portion.customer_delivery_day))
        portions_by_delivery[key].append(portion)
        if dispatch_targets and _misses_dispatch(portion):
            deliveries.setdefault(key, _Delivery(key[0], key[1], set(), 0))
    if not deliveries:
        return []

    config = config or FactoryConfig()
    current = factory_calendar.factory_now(config, now=now)
    if planning_day is None:
        planning_day = current_factory_day(data, config, now=current) if data.workdays else 0
    windows = []
    for key, delivery in deliveries.items():
        window = _delivery_window(
            delivery, portions_by_delivery.get(key, []), dispatch_targets=dispatch_targets,
        )
        if window is not None:
            windows.append(window)
    candidates = _lot_windows(windows, planning_day)
    if not candidates:
        return []

    checker = _IdleTime(segments, lots, data, config, planning_day, current)
    cases = []
    for lot_windows in sorted(candidates, key=lambda items: (
        items[0]["production_due_day"], items[0]["sku"], items[0]["customer_delivery_day"],
    )):
        for window in lot_windows:
            case = checker.evaluate(window)
            if case is not None:
                cases.append(case)
                break
    return cases


def _misses_dispatch(portion) -> bool:
    dispatch = portion.latest_subcontract_dispatch_day
    return (
        portion.is_subcontracted
        and dispatch is not None
        and (not portion.complete or portion.factory_day > dispatch)
    )


def _delivery_window(delivery: _Delivery, portions, *, dispatch_targets: bool) -> dict | None:
    """Shortfall, material release and production deadline of one delivery."""

    if not portions:
        return None
    subcontracted = [
        portion for portion in portions
        if dispatch_targets and portion.is_subcontracted
        and portion.latest_subcontract_dispatch_day is not None
    ]
    if subcontracted:
        # The planner's aim: ready to leave by the latest dispatch ``H``.
        deadline = min(int(portion.latest_subcontract_dispatch_day) for portion in subcontracted)
        shortfall = sum(
            max(0, int(portion.qty) - sum(
                int(item.qty) for item in portion.slices if item.available_day <= deadline
            ))
            for portion in subcontracted
        )
        pending = [
            portion for portion in subcontracted
            if sum(int(item.qty) for item in portion.slices if item.available_day <= deadline)
            < int(portion.qty)
        ]
    else:
        # The customer day (stock rule, 14/10/2026); for in-house deliveries
        # it is their production due day.
        deadline = min(
            int(portion.customer_delivery_day if portion.is_subcontracted
                else portion.production_due_day)
            for portion in portions
        )
        shortfall = delivery.order_shortfall
        pending = [portion for portion in portions if not portion.complete] or portions
    if shortfall <= 0 or not pending:
        return None
    return {
        "sku": delivery.sku,
        "op_id": pending[0].op_id,
        "lot_id": pending[0].source.lot_id,
        "clients": sorted(delivery.clients),
        "customer_delivery_day": delivery.customer_delivery_day,
        "production_due_day": deadline,
        "material_release_day": min(
            output_release_day(portion.source.output) for portion in portions
        ),
        "shortfall_qty": int(shortfall),
        # Cycle rule, or a subcontracted lot that goes out whole (dispatch
        # targets): the pieces are only available when the lot ends.
        "lot_end_rule": any(
            bool(portion.source.cycle_rule) or (bool(subcontracted) and portion.whole_lot_dispatch)
            for portion in pending
        ),
    }


def _lot_windows(windows: list[dict], planning_day: int) -> list[list[dict]]:
    """Per lot, the windows that could recover its late deliveries, earliest first.

    The late deliveries of one lot are one case: both sides of a twin cycle
    and the orders of one deadline are served together (sides run in
    parallel: the largest side sets the quantity). The ``k``-th window
    serves every late delivery of the lot up to the ``k``-th deadline
    (pieces go first-in-first-out, so a later delivery needs the earlier
    ones made too), from the earliest of their material releases.
    """

    by_lot: dict[str, list[dict]] = defaultdict(list)
    for window in windows:
        by_lot[window["lot_id"]].append(window)
    candidates = []
    for lot_id, items in by_lot.items():
        items.sort(key=lambda item: (item["production_due_day"], item["customer_delivery_day"],
                                     item["sku"]))
        per_sku: dict[str, int] = defaultdict(int)
        served: list[dict] = []
        lot_windows = []
        for position, item in enumerate(items):
            per_sku[item["sku"]] += int(item["shortfall_qty"])
            served.append(item)
            following = items[position + 1] if position + 1 < len(items) else None
            if following is not None and (
                following["production_due_day"] == item["production_due_day"]
            ):
                continue  # one deadline is one window
            release = min(int(entry["material_release_day"]) for entry in served)
            start = max(int(planning_day), release, 0)
            deadline = int(item["production_due_day"])
            if start > deadline:
                continue
            first = served[0]
            lot_windows.append({
                "sku": first["sku"],
                "skus": list(dict.fromkeys(entry["sku"] for entry in served)),
                "op_id": first["op_id"],
                "lot_id": lot_id,
                "clients": sorted({client for entry in served for client in entry["clients"]}),
                "customer_delivery_day": int(first["customer_delivery_day"]),
                "production_due_day": deadline,
                "material_release_day": release,
                "window_start_day": start,
                "shortfall_qty": max(per_sku.values()),
                "lot_end_rule": any(entry["lot_end_rule"] for entry in served),
                "deliveries": [
                    {
                        "sku": entry["sku"],
                        "customer_delivery_day": int(entry["customer_delivery_day"]),
                        "production_due_day": int(entry["production_due_day"]),
                    }
                    for entry in served
                ],
            })
        if lot_windows:
            candidates.append(lot_windows)
    return candidates


class _IdleTime:
    """Free shift time per machine, with the minutes already claimed by cases."""

    def __init__(self, segments, lots, data, config, planning_day: int, now: datetime):
        self.data = data
        self.config = config
        self.planning_day = planning_day
        self.now = now
        self.lots = {lot.id: lot for lot in lots}
        self.ops = {op.id: op for op in data.ops}
        self.active = {
            machine.id for machine in data.machines
            if config.machines.get(machine.id) is None or config.machines[machine.id].active
        }
        self.by_day: dict[int, list[Segment]] = defaultdict(list)
        self.by_machine: dict[str, list[Segment]] = defaultdict(list)
        self.by_lot: dict[str, list[Segment]] = defaultdict(list)
        for segment in segments:
            if segment.end_min <= segment.start_min:
                continue
            self.by_day[segment.day_idx].append(segment)
            self.by_machine[segment.machine_id].append(segment)
            self.by_lot[segment.lot_id].append(segment)
        for timeline in self.by_machine.values():
            timeline.sort(key=lambda item: (item.day_idx, item.start_min, item.end_min))

    def evaluate(self, window: dict) -> dict | None:
        lot = self.lots.get(window["lot_id"])
        if lot is None or int(lot.qty) <= 0:
            return None
        own = self._own_machines(lot)
        best = None
        for machine_id in self._eligible_machines(lot, own):
            on_machine = self._on_machine(lot, machine_id)
            intervals = self._free_intervals(
                lot, machine_id, window["window_start_day"], window["production_due_day"],
            )
            if not intervals:
                continue
            whole_lot = machine_id not in own or window["lot_end_rule"]
            production = self._production_needed(
                lot, machine_id, on_machine, window, whole=machine_id not in own,
            )
            setup_min = (
                0.0 if self._mounted_before(lot, machine_id, intervals[0])
                else float(on_machine.setup_min)
            )
            needed = production + setup_min
            free = float(sum(end - start for _day, start, end in intervals))
            option = (free - needed, machine_id, free, needed, setup_min, whole_lot, intervals)
            if best is None or option[0] > best[0]:
                best = option
        if best is None or best[0] < 0:
            return None
        _margin, machine_id, free, needed, setup_min, whole_lot, intervals = best
        self._claim(lot, machine_id, intervals, needed)
        return {
            **window,
            "machine_id": machine_id,
            "free_min": round(free, 1),
            "needed_min": round(needed, 1),
            "setup_min": round(setup_min, 1),
            "whole_lot": whole_lot,
        }

    def _own_machines(self, lot: Lot) -> set[str]:
        machines = {segment.machine_id for segment in self.by_lot.get(lot.id, [])}
        return machines or {lot.machine_id}

    def _eligible_machines(self, lot: Lot, own: set[str]) -> list[str]:
        """Own machines, plus the alternatives while the lot has not started.

        A lot with production on the planning day or before has started
        (rule 4): its rest stays on its machine.
        """

        if any(segment.day_idx <= self.planning_day and segment.prod_min > 0
               for segment in self.by_lot.get(lot.id, [])):
            return sorted(own & self.active)
        op_ids = [str(op_id) for op_id, _sku, _qty in lot.twin_outputs or []] or [lot.op_id]
        options: set[str] | None = None
        for op_id in op_ids:
            op = self.ops.get(op_id)
            machines = {machine for machine in (op.m, op.alt) if machine} if op else set()
            options = machines if options is None else options & machines
        if not options:
            options = {machine for machine in (lot.machine_id, lot.alt_machine_id) if machine}
        return sorted((options | own) & self.active)

    def _on_machine(self, lot: Lot, machine_id: str) -> Lot:
        """The lot rebound to ``machine_id`` (its rate and setup there)."""

        if machine_id == lot.machine_id:
            return lot
        run = ToolRun(
            id=lot.id, tool_id=lot.tool_id, machine_id=lot.machine_id,
            alt_machine_id=lot.alt_machine_id, lots=[lot], setup_min=float(lot.setup_min),
            total_prod_min=float(lot.prod_min),
            total_min=float(lot.setup_min) + float(lot.prod_min), edd=int(lot.edd),
        )
        return clone_run_for_machine(run, machine_id, self.data, self.config).lots[0]

    def _production_needed(
        self, lot: Lot, machine_id: str, on_machine: Lot, window: dict, *, whole: bool,
    ) -> float:
        """Production minutes the free time must hold for the lot's late deliveries.

        ``whole``: the lot would change machine, so all of it moves (rule 3).
        Pieces available only at the lot end: the rest of the lot not
        produced on the machine by the deadline. Otherwise the shortfall.
        """

        if whole:
            return float(on_machine.prod_min)
        if window["lot_end_rule"]:
            done = sum(
                float(segment.prod_min) for segment in self.by_lot.get(lot.id, [])
                if segment.machine_id == machine_id
                and segment.day_idx <= window["production_due_day"]
            )
            return max(0.0, float(on_machine.prod_min) - done)
        return window["shortfall_qty"] * float(on_machine.prod_min) / int(on_machine.qty)

    def _operators(self, lot: Lot) -> int:
        op_ids = [str(op_id) for op_id, _sku, _qty in lot.twin_outputs or []] or [lot.op_id]
        return max(
            (max(1, int(getattr(self.ops.get(op_id), "operators", 1) or 1)) for op_id in op_ids),
            default=1,
        )

    def _free_intervals(self, lot: Lot, machine_id: str, first_day: int, last_day: int):
        required = self._operators(lot)
        intervals: list[tuple[int, int, int]] = []
        for day in range(max(0, first_day), last_day + 1):
            intervals.extend(
                (day, start, end)
                for start, end in free_shift_intervals(
                    machine_id, lot.tool_id, day, self.data, self.config,
                    segments=self.by_day.get(day, []), required_operators=required,
                    start_min=elapsed_minutes(day, self.data, self.config, now=self.now),
                )
            )
        return intervals

    def _mounted_before(self, lot: Lot, machine_id: str, first: tuple[int, int, int]) -> bool:
        """The lot's setup is the last one on the machine before the free time."""

        day, start, _end = first
        previous = None
        for segment in self.by_machine.get(machine_id, []):
            if (segment.day_idx, segment.end_min) > (day, start):
                break
            if segment.lot_id != CLAIM_LOT_ID:
                previous = segment
        return previous is not None and segment_setup_identity(previous) == lot_setup_identity(lot)

    def _claim(self, lot: Lot, machine_id: str, intervals, needed: float) -> None:
        """Book the first ``needed`` free minutes, so no other case counts them."""

        remaining = needed
        for day, start, end in intervals:
            if remaining <= 0:
                break
            stop = min(end, start + math.ceil(remaining))
            claim = Segment(
                CLAIM_LOT_ID, CLAIM_LOT_ID, machine_id, lot.tool_id, day, start, stop, "",
                0, float(stop - start), sku=lot.sku,
                twin_outputs=list(lot.twin_outputs) if lot.twin_outputs else None,
            )
            self.by_day[day].append(claim)
            remaining -= stop - start


def idle_capacity_notice(cases: list[dict], data: EngineData, limit: int = 3) -> str | None:
    """Plain pt-PT notice: late deliveries with enough idle time (at most ``limit`` lots).

    It says what is possible, not which button to press: «Recalcular plano»
    recalculates from the first day and is not guaranteed to use the time.
    """

    if not cases:
        return None
    workdays = list(data.workdays or [])

    def label(day: int) -> str:
        if 0 <= day < len(workdays):
            text = str(workdays[day])[:10]
            return f"{text[8:10]}/{text[5:7]}"
        return f"dia {day}"

    def joined(items: list[str]) -> str:
        return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} e {items[-1]}"

    def describe(case: dict) -> str:
        deliveries = case.get("deliveries") or [case]
        orders = list(dict.fromkeys(
            label(item["customer_delivery_day"]) for item in deliveries
        ))
        dues = f"{'entregas' if len(orders) > 1 else 'entrega'} {joined(orders)}"
        skus = list(dict.fromkeys(case.get("skus") or [case["sku"]]))
        return f"{joined(skus)} ({dues})"

    machines = {case["machine_id"] for case in cases}
    shown = cases[:limit]
    one_machine = len(machines) == 1
    items = [describe(case) if one_machine else f"{describe(case)} na {case['machine_id']}"
             for case in shown]
    if len(cases) > len(shown):
        items.append(f"mais {len(cases) - len(shown)}")
    plural = len(cases) > 1 or len(shown[0].get("skus") or [shown[0]["sku"]]) > 1
    late = "estão atrasadas" if plural else "está atrasada"
    if one_machine:
        where = f"a {next(iter(machines))} tem tempo livre suficiente"
    else:
        where = "essas máquinas têm tempo livre suficiente"
    deadline = "antes dos prazos" if len(cases) > 1 else "antes do prazo"
    title = "Possíveis melhorias" if len(cases) > 1 else "Possível melhoria"
    return f"{title}: {joined(items)} {late} e {where} {deadline}."
