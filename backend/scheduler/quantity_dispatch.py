"""Build the plan from material portions, as tool campaigns (plan of 10/10, B1a).

An economic lot that covers several deliveries is sized once (AGENTS §3).
Under the current material contract (version 3, 13/10/2026) the whole lot is
released at the ``R`` of its first delivery and is one portion: it is placed
as one production (one setup), never split. Plans of versions 1-2 released
each delivery at its own ``R`` ("Janela por entrega"); their lots still have
several portions. This builder never returns new lots: it allocates the lot
portion by portion with the shared earliest-slot allocator and keeps one
machine per lot.

- **Portions** (``material_portions``): consecutive outputs released on the
  same day; the economic surplus closes the last portion. A portion uses the
  milestones and the target start of its own deliveries. A twin cycle has one
  portion per increment of its release curve (Fase B2): each side makes the
  portion's cycles, in one execution.
- **Ready queue:** portion ``k`` of a lot is ready only after portion ``k-1``
  is placed, so the first-in-first-out assignment of pieces to deliveries
  stays valid. The most urgent ready portion (``lot_priority_key``, with the
  quantity of the customer delivery it serves among those due on its due
  day) is placed next.
- **Deliveries first** (AGENTS §1.2): a portion's delays are measured against
  the production due day of each of its deliveries. A less urgent portion due
  the same day goes first when that saves its delivery and costs no delivery
  to the lots it passes (``delivery_swap``).
- **Machine per lot:** the first portion of a lot places, as a trial, every
  portion on each eligible machine. The machine is chosen by days late, then
  the tolerant anticipation (``policy.anticipation_compare``), then setups
  (owner rule 2 of 10/10: inside the tolerance setups break ties before exact
  minutes), then exact minutes, then the primary machine. A machine change
  always moves the whole lot (rule 3); the machine stays fixed for the rest
  of the lot.
- **Campaign continuation** (rules 1-2): after a portion, the most urgent ready
  portion with the same setup identity whose material is already released
  continues on the mounted tool, without a setup and in the same physical run.
  It is vetoed when a more urgent ready lot that may use that machine would
  get a delivery later, or lose ``ANTICIPATION_TOLERANCE_MIN`` (60 min) or
  more over all its remaining portions, measured against its position before
  the chain of continuations started (small steps never add up past 60 min).
- **Retained tool:** the allocator does not insert other work into an idle gap
  on which a setup-free continuation depends, unless the insertion is worth a
  break (``_break_accepted``): the dependent campaign is placed again, with
  its setup. A break is refused when some delivery gets later (the
  dependent portions, the portions of those lots not placed yet, the inserted
  lot and its later portions). With no delivery of the inserted lot getting
  earlier it is judged by the evaluator's comparator
  (``policy.tolerant_better``) over the moved portions in priority order:
  a portion may lose 60 min or more only if a more urgent one gains as much,
  and inside the tolerance the extra setup refuses it (rule 2).
- Portions of one lot that run back to back share one run; portion boundaries
  remain segment boundaries.
- Protected work of a frozen recalculation (``protected_mounting_segments``)
  is physical evidence of the mounted tool.
- **Fallback:** if the campaign builder fails, the previous behaviour (one run
  per portion, no continuation) is tried before the recalculation fails, and
  the plan carries a plain warning (``FALLBACK_WARNING``).
"""

from __future__ import annotations

import copy
import logging
from collections import defaultdict
from dataclasses import dataclass, field, replace

from backend.config.shifts import ordered_shifts
from backend.planning_control import planning_checkpoint
from backend.scheduler.alternative_repair import _schedule_run_earliest
from backend.scheduler.lot_sizing import _aggregate_milestones
from backend.scheduler.material_quantities import (
    material_portions,
    releases_in_portions,
    whole_lot_release,
)
from backend.scheduler.policy import (
    ANTICIPATION_TOLERANCE_MIN,
    anticipation_compare,
    tolerant_better,
)
from backend.scheduler.priority import lot_priority_key
from backend.scheduler.resources import clone_run_for_machine, protected_mounting_segments
from backend.scheduler.setup_identity import (
    SetupIdentity,
    fixed_mounting_gaps,
    lot_setup_identity,
    segment_setup_identity,
)
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.scheduler.validation import assert_plan_valid

logger = logging.getLogger(__name__)

_DAY = 1440
# Retention gaps examined for one insertion (bounded work, not time).
_MAX_RETENTION_BREAKS = 3
# Less urgent portions examined for a delivery-first swap (bounded work).
_MAX_DELIVERY_SWAPS = 3
_LOT_FIELDS = (
    "edd",
    "original_edd",
    "delivery_day",
    "internal_deadline",
    "customer_delivery_day",
    "production_due_day",
    "internal_target_day",
    "material_reference_day",
    "material_release_day",
)
_KEEP = object()


def has_quantity_releases(lots):
    """Whether the lots are planned by this builder.

    Lots of the current material contract (version 3, one production per
    economic lot, AGENTS §2) always are, as are lots of versions 1-2 that
    release their material in more than one portion (twin cycles since
    Fase B2). Only older plans fall back to the previous engine.
    """

    return any(whole_lot_release(lot) or releases_in_portions(lot) for lot in lots)


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


def _abs_start(segment: Segment) -> float:
    return float(segment.day_idx * _DAY + segment.start_min)


def _is_surplus(output: dict) -> bool:
    return bool(output.get("is_coproduced_surplus") or output.get("is_economic_surplus"))


def _portion_lot(
    lot: Lot, qty: int, outputs: tuple[dict, ...], single: bool,
    release_day: int | None = None,
) -> Lot:
    """The lot restricted to one portion: its quantity, deliveries and window.

    A twin portion is ``qty`` cycles: each side makes ``qty`` pieces and the
    time is one execution (the lot minutes in proportion, never a sum).
    """

    if single:
        return copy.deepcopy(lot)
    trial = replace(lot, qty=qty, prod_min=lot.prod_min * qty / lot.qty)
    if lot.twin_outputs:
        trial.twin_outputs = [(op_id, sku, qty) for op_id, sku, _qty in lot.twin_outputs]
    for name, value in _aggregate_milestones(list(outputs)).items():
        setattr(trial, name, value)
    if release_day is not None:
        trial.material_release_day = int(release_day)
    trial.edd = int(trial.production_due_day)
    trial.original_edd = trial.delivery_day = int(trial.customer_delivery_day)
    trial.internal_deadline = int(trial.internal_target_day)
    demand_days = [
        int(output["customer_delivery_day"]) for output in outputs if not _is_surplus(output)
    ]
    if demand_days and lot.target_start_day is not None:
        trial.target_start_day = max(0, min(demand_days) - int(lot.start_buffer_days or 0))
    return trial


@dataclass
class _Portion:
    lot_id: str
    index: int
    lot: Lot
    key: tuple
    identity: SetupIdentity
    release_day: int | None


@dataclass
class _Placement:
    portion: _Portion
    machine: str
    created: list[Segment]
    start: float  # first productive minute (absolute)
    end: float  # end of the portion (absolute)
    setup: float
    # Days late of each delivery of the portion against its production due day.
    delays: tuple[int, ...] = ()

    @property
    def window(self) -> tuple[float, float]:
        return self.start, self.end

    @property
    def first(self) -> Segment:
        return min(self.created, key=lambda s: (s.day_idx, s.start_min))


@dataclass
class _MachineOption:
    """All remaining portions of one lot placed, as a trial, on one machine."""

    machine: str
    placements: list[_Placement] = field(default_factory=list)

    @property
    def windows(self) -> list[tuple[float, float]]:
        return [item.window for item in self.placements]

    @property
    def delays(self) -> tuple[int, ...]:
        return tuple(day for item in self.placements for day in item.delays)

    @property
    def late_days(self) -> int:
        return sum(self.delays)

    @property
    def setups(self) -> int:
        return sum(1 for item in self.placements if item.setup > 0)

    @property
    def setup_min(self) -> float:
        return sum(item.setup for item in self.placements)

    @property
    def first(self) -> _Placement:
        return self.placements[0]


def _portion_delays(portion: _Portion, created: list[Segment]) -> tuple[int, ...]:
    """Days late of each delivery of the portion (first-in-first-out pieces).

    Each operation (each side of a twin cycle) serves its own deliveries.
    """

    lot = portion.lot
    ordered = sorted(
        created, key=lambda segment: (segment.day_idx, segment.end_min),
    )
    made: dict[object, list[tuple[int, int]]] = defaultdict(list)
    for segment in ordered:
        for op_id, _sku, qty in segment.twin_outputs or [(lot.op_id, lot.sku, segment.qty)]:
            if int(qty) > 0:
                made[op_id].append((segment.day_idx, int(qty)))
    last_day = max((day for items in made.values() for day, _qty in items), default=None)
    needed: dict[object, int] = defaultdict(int)
    position: dict[object, int] = defaultdict(int)
    produced: dict[object, int] = defaultdict(int)
    delays: list[int] = []
    for output in lot.output_milestones or []:
        op_id = output.get("op_id") or lot.op_id
        needed[op_id] += int(output.get("qty") or 0)
        if _is_surplus(output) or output.get("production_due_day") is None:
            continue
        items = made.get(op_id, [])
        while position[op_id] < len(items) and produced[op_id] < needed[op_id]:
            produced[op_id] += items[position[op_id]][1]
            position[op_id] += 1
        if produced[op_id] >= needed[op_id] and position[op_id]:
            day = items[position[op_id] - 1][0]
        else:
            day = last_day if last_day is not None else 10**6
        delays.append(max(0, int(day) - int(output["production_due_day"])))
    return tuple(delays)


def _later_delivery(candidate: tuple[int, ...], reference: tuple[int, ...]) -> bool:
    """Does any delivery become late, or later, than in ``reference``?"""

    return any(after > before for after, before in zip(candidate, reference, strict=True))


def _delays(placements: list[_Placement]) -> tuple[int, ...]:
    return tuple(day for item in placements for day in item.delays)


def _urgency(placement: _Placement) -> tuple:
    """Rank of a portion in the anticipation vector: its priority key."""

    portion = placement.portion
    return portion.key, portion.lot_id, portion.index


def _ranked_windows(placements: list[_Placement]) -> tuple[tuple[float, float], ...]:
    return tuple(item.window for item in sorted(placements, key=_urgency))


def _setup_summary(placements) -> tuple[int, float]:
    return (
        sum(1 for item in placements if item.setup > 0),
        sum(max(0.0, item.setup) for item in placements),
    )


def _break_accepted(
    own: list[tuple[_Placement, _Placement]],
    others: list[tuple[_Placement, _Placement]],
) -> bool:
    """Owner rule 2 for a retention break, once no delivery gets later.

    ``own`` pairs (before, after) the inserted portion and the later portions
    of its lot; ``others`` the dependent portions placed again and the
    portions of those lots not placed yet. A break whose lot gets a delivery
    earlier is always accepted (deliveries first, AGENTS §1.2). Otherwise
    the break is judged by the evaluator's own comparator
    (``policy.tolerant_better``, contract v3) on every portion it moves, in
    priority order (``_Portion.key``): a portion may lose 60 min or more
    only if a more urgent one gains as much; inside the tolerance fewer
    setups decide (the break re-mounts the dependent tool), then the exact
    minutes. So the builder never keeps a break the improvement cycle would
    undo, nor refuses one it would take.
    """

    if any(
        after < before
        for old, new in own
        for after, before in zip(new.delays, old.delays, strict=True)
    ):
        return True
    pairs = sorted([*own, *others], key=lambda pair: _urgency(pair[0]))
    before = [old for old, _new in pairs]
    after = [new for _old, new in pairs]
    return tolerant_better(
        tuple(item.window for item in after), tuple(item.window for item in before),
        _setup_summary(after), _setup_summary(before),
    )


def _order_id(output: dict) -> tuple[object, object]:
    return output.get("op_id") or output.get("sku"), output.get("customer_delivery_day")


def _order_quantities(lots: list[Lot]) -> dict[tuple[object, object], int]:
    """Quantity of each customer delivery (operation, day) over every lot."""

    totals: dict[tuple[object, object], int] = defaultdict(int)
    for lot in lots:
        for output in lot.output_milestones or []:
            if not _is_surplus(output):
                totals[_order_id(output)] += int(output.get("qty") or 0)
    return dict(totals)


class _Chain:
    """State of the plan before a chain of continuations started (rule 2)."""

    def __init__(self, segments: list[Segment]) -> None:
        self.base = segments
        self._before: dict[str, _MachineOption | None] = {}

    def before(self, builder: _CampaignBuilder, lot_id: str) -> _MachineOption | None:
        if lot_id not in self._before:
            self._before[lot_id] = builder.best_outlook(lot_id, self.base)
        return self._before[lot_id]


def _machine_better(candidate: _MachineOption, best: _MachineOption, primary: str) -> bool:
    # Deliveries before anticipation and setups (AGENTS §1.2): the machine
    # that leaves fewer days late wins whatever the minutes.
    if candidate.late_days != best.late_days:
        return candidate.late_days < best.late_days
    decided = anticipation_compare(candidate.windows, best.windows)
    if decided:
        return decided < 0
    if (candidate.setups, candidate.setup_min) != (best.setups, best.setup_min):
        return (candidate.setups, candidate.setup_min) < (best.setups, best.setup_min)
    if candidate.windows != best.windows:
        return tuple(candidate.windows) < tuple(best.windows)
    return (candidate.machine != primary, candidate.machine) < (
        best.machine != primary, best.machine,
    )


class _CampaignBuilder:
    def __init__(self, lots: list[Lot], data, config, *, campaigns: bool = True) -> None:
        # ``campaigns=False`` is the previous safe behaviour, kept as the
        # fallback: one run per portion, no continuation, no retention break.
        self.campaigns = campaigns
        self.data = data
        self.config = config
        self.lots = lots
        self.originals = {lot.id: copy.deepcopy(lot) for lot in lots}
        self.order_qty = _order_quantities(lots)
        self.portions: dict[str, list[_Portion]] = {}
        for lot in lots:
            parts = material_portions(lot)
            portions = []
            for part in parts:
                trial = _portion_lot(
                    lot, part.qty, part.outputs, len(parts) == 1, part.material_release_day,
                )
                portions.append(_Portion(
                    lot.id, part.index, trial, self.portion_key(trial),
                    lot_setup_identity(trial), trial.material_release_day,
                ))
            self.portions[lot.id] = portions
        # Frozen recalculation: protected work is physical evidence on the
        # machines (mountings, tool changes), never part of this plan.
        self.fixed = protected_mounting_segments(data)
        # A started lot's rest keeps its lot id (AGENTS §2, rule 4): its new
        # runs must not reuse the run ids of its frozen part.
        self.fixed_run_ids = {segment.run_id for segment in self.fixed}
        self.active = {
            machine.id
            for machine in data.machines
            if machine.id not in config.machines or config.machines[machine.id].active
        }
        shifts = ordered_shifts(config)
        self.shift_start = int(shifts[0].start_min) if shifts else 0
        self.segments: list[Segment] = []
        self.locked: dict[str, str] = {}
        self.parents: dict[tuple[str, str], Lot] = {}
        self.cursor: dict[str, float] = {}
        self.placed: dict[tuple[str, int], _Placement] = {}
        self.next_index = {lot.id: 0 for lot in lots}

    # ── helpers ──────────────────────────────────────────────────────────

    def portion_key(self, trial: Lot) -> tuple:
        """``lot_priority_key`` with the quantity of the delivery served.

        The canonical key ranks equal due dates by the larger quantity to
        deliver (AGENTS §1.3). A portion may carry only part of a customer
        delivery (the rest is in another economic lot of the operation, and
        pieces are fungible). Ranking it by its share would put part of a
        large delivery behind a smaller delivery due the same day and make
        the large one late for nothing; the delivery's own quantity is used.
        Only the deliveries due on the key's own due day count: a larger
        delivery due later never ranks a portion among those due earlier.
        """

        key = lot_priority_key(trial)
        served = [
            self.order_qty.get(_order_id(output), 0)
            for output in trial.output_milestones or []
            if not _is_surplus(output)
            and output.get("production_due_day") is not None
            and int(output["production_due_day"]) == key[0]
        ]
        if not served:
            return key
        return (*key[:6], -max(max(served), -key[6]), *key[7:])

    def run_id(self, portion: _Portion) -> str:
        """Identifier of a new run for ``portion``, never one of frozen work."""

        base = run_id = f"quantity:{portion.lot_id}:{portion.index}"
        suffix = 1
        while run_id in self.fixed_run_ids:
            run_id = f"{base}:rest{suffix}"
            suffix += 1
        return run_id

    def ready(self) -> list[_Portion]:
        return [
            self.portions[lot_id][index]
            for lot_id, index in self.next_index.items()
            if index < len(self.portions[lot_id])
        ]

    def release_abs(self, portion: _Portion) -> float:
        if portion.release_day is None:
            return float("-inf")
        return float(portion.release_day * _DAY + self.shift_start)

    def machines(self, lot_id: str) -> list[str]:
        if lot_id in self.locked:
            return [self.locked[lot_id]]
        original = self.originals[lot_id]
        return list(dict.fromkeys(
            machine for machine in (original.machine_id, original.alt_machine_id)
            if machine in self.active
        ))

    def parent(self, lot_id: str, machine: str) -> Lot:
        key = (lot_id, machine)
        if key not in self.parents:
            original = self.originals[lot_id]
            parent = clone_run_for_machine(
                _run(original, lot_id), machine, self.data, self.config,
            ).lots[0]
            parent.machine_id = machine
            self.parents[key] = parent
        return self.parents[key]

    def place(self, portion, machine, segments, *, cursor=_KEEP, not_before=None):
        """Earliest legal placement of one portion on ``machine`` (no commit)."""

        planning_checkpoint()
        parent = self.parent(portion.lot_id, machine)
        trial = copy.copy(portion.lot)
        trial.prod_min = parent.prod_min * trial.qty / parent.qty
        trial.setup_min = parent.setup_min
        trial.machine_id = machine
        floor = self.cursor.get(portion.lot_id) if cursor is _KEEP else cursor
        bounds = [value for value in (floor, not_before) if value is not None]
        scheduled = _schedule_run_earliest(
            _run(trial, self.run_id(portion)),
            machine,
            segments,
            self.data,
            self.config,
            not_before_abs=int(max(bounds)) if bounds else None,
        )
        if scheduled is None:
            return None
        created = scheduled[1]
        productive = [s for s in created if s.prod_min > 0 and s.end_min > s.start_min]
        if not productive:
            return None
        return _Placement(
            portion,
            machine,
            created,
            min(s.day_idx * _DAY + s.start_min + max(0.0, s.setup_min) for s in productive),
            max(s.day_idx * _DAY + s.end_min for s in created),
            sum(max(0.0, s.setup_min) for s in created),
            _portion_delays(portion, created),
        )

    def outlook(self, lot_id: str, machine: str, segments) -> _MachineOption | None:
        """Every remaining portion of the lot placed in order on ``machine``."""

        trial_segments = list(segments)
        cursor = self.cursor.get(lot_id)
        option = _MachineOption(machine)
        for portion in self.portions[lot_id][self.next_index[lot_id]:]:
            placed = self.place(portion, machine, trial_segments, cursor=cursor)
            if placed is None:
                return None
            trial_segments.extend(placed.created)
            cursor = placed.end
            option.placements.append(placed)
        return option if option.placements else None

    def best_outlook(self, lot_id: str, segments) -> _MachineOption | None:
        best: _MachineOption | None = None
        primary = self.originals[lot_id].machine_id
        for machine in self.machines(lot_id):
            option = self.outlook(lot_id, machine, segments)
            if option is not None and (best is None or _machine_better(option, best, primary)):
                best = option
        return best

    def previous_on_machine(self, machine: str, segment: Segment) -> Segment | None:
        point = (segment.day_idx, segment.start_min)
        return max(
            (
                item for item in (*self.segments, *self.fixed)
                if item.machine_id == machine and item.end_min > item.start_min
                and (item.day_idx, item.end_min) <= point
            ),
            key=lambda item: (item.day_idx, item.end_min, item.start_min),
            default=None,
        )

    def retained(self, placement: _Placement) -> Segment | None:
        """The segment whose mounted tool the placement continues, if any."""

        if placement.setup > 0:
            return None
        previous = self.previous_on_machine(placement.machine, placement.first)
        if previous is None or segment_setup_identity(previous) != placement.portion.identity:
            return None
        return previous

    # ── decisions ────────────────────────────────────────────────────────

    def choose_machine(self, lot_id: str) -> tuple[str | None, _Placement | None]:
        machines = self.machines(lot_id)
        if len(machines) <= 1:
            return (machines[0] if machines else None), None
        if not self.campaigns:
            portion = self.portions[lot_id][self.next_index[lot_id]]
            options = [
                placed for machine in machines
                for placed in [self.place(portion, machine, self.segments)]
                if placed is not None
            ]
            if not options:
                return machines[0], None
            chosen = min(options, key=lambda item: (item.start, item.end, item.machine))
            return chosen.machine, chosen
        best = self.best_outlook(lot_id, self.segments)
        if best is None:
            return machines[0], None
        return best.machine, best.first

    def loses(self, portion: _Portion, placement: _Placement, chain: _Chain) -> bool:
        """Would the more urgent lot of ``portion`` lose to ``placement``?

        Measured over every remaining portion of that lot, on its best
        machine, against its outlook *before the chain of continuations
        started* (``chain.base``), so several small continuations never add
        up past the tolerance. Deliveries first: no delivery of that lot may
        become late or later; then the 60-min tolerance (rule 2).
        """

        machine = placement.machine
        if (
            machine not in self.machines(portion.lot_id)
            or self.release_abs(portion) >= placement.end
        ):
            return False
        before = chain.before(self, portion.lot_id)
        if before is None:
            return False
        # Untouched when, before the chain, its own setup already started
        # after this continuation ends (the chain only adds earlier work).
        if _abs_start(before.first.first) >= placement.end:
            return False
        after = self.best_outlook(portion.lot_id, [*self.segments, *placement.created])
        if after is None:
            return True
        if _later_delivery(after.delays, before.delays):
            return True
        # The evaluator's order: the lot's portions by priority (rule 2).
        return anticipation_compare(
            _ranked_windows(after.placements), _ranked_windows(before.placements),
        ) > 0

    def vetoed(self, candidate: _Portion, placement: _Placement, chain: _Chain) -> bool:
        return any(
            self.loses(other, placement, chain)
            for other in self.ready()
            if other.lot_id != candidate.lot_id
            and other.identity != candidate.identity
            and other.key < candidate.key
        )

    # ── commits ──────────────────────────────────────────────────────────

    def commit(self, placement: _Placement) -> None:
        portion = placement.portion
        previous = self.retained(placement) if self.campaigns else None
        run_id = (
            previous.run_id if previous is not None
            else self.run_id(portion)
        )
        parent = self.parent(portion.lot_id, placement.machine)
        productive = sum(s.prod_min for s in placement.created)
        expected = parent.prod_min * portion.lot.qty / parent.qty
        for segment in placement.created:
            segment.run_id = run_id
            # Integer clock slots can round a portion up. Preserve exact
            # productive minutes as well as pieces; the fraction stays reserved.
            if productive > 0:
                segment.prod_min *= expected / productive
            segment.lot_qty = parent.qty
            segment.output_milestones = copy.deepcopy(parent.output_milestones)
            for name in _LOT_FIELDS:
                setattr(segment, name, getattr(parent, name))
        self.segments.extend(placement.created)
        self.locked[portion.lot_id] = placement.machine
        self.cursor[portion.lot_id] = placement.end
        self.placed[(portion.lot_id, portion.index)] = placement
        self.next_index[portion.lot_id] = portion.index + 1

    def break_retention(self, placement: _Placement) -> bool:
        """Insert into a retained-tool gap only for a gain the rules accept."""

        portion = placement.portion
        machine = placement.machine
        floor = max(self.release_abs(portion), self.cursor.get(portion.lot_id, float("-inf")))
        by_first = {id(item.first): item for item in self.placed.values()}
        tried = 0
        for previous, dependent in fixed_mounting_gaps([*self.segments, *self.fixed]):
            if tried >= _MAX_RETENTION_BREAKS:
                break
            if dependent.machine_id != machine:
                continue
            if segment_setup_identity(dependent) == portion.identity:
                continue
            gap_start = previous.day_idx * _DAY + previous.end_min
            gap_end = dependent.day_idx * _DAY + dependent.start_min
            if (
                gap_end <= floor
                or max(floor, gap_start) > placement.start - ANTICIPATION_TOLERANCE_MIN
            ):
                continue
            head = by_first.get(id(dependent))
            if head is None:
                continue
            tried += 1
            if self._try_break(placement, head):
                return True
        return False

    def _try_break(self, placement: _Placement, head: _Placement) -> bool:
        run_id = head.first.run_id
        head_start = head.first.day_idx * _DAY + head.first.start_min
        tail = sorted(
            (
                item for item in self.placed.values()
                if item.machine == head.machine
                and item.first.run_id == run_id
                and item.first.day_idx * _DAY + item.first.start_min >= head_start
            ),
            key=lambda item: (item.first.day_idx, item.first.start_min),
        )
        for item in tail:
            lot_id = item.portion.lot_id
            last_placed = max(index for (owner, index) in self.placed if owner == lot_id)
            last_in_tail = max(
                other.portion.index for other in tail if other.portion.lot_id == lot_id
            )
            if last_placed != last_in_tail:
                return False  # a later portion of that lot already follows it
        removed = {id(segment) for item in tail for segment in item.created}
        base = [segment for segment in self.segments if id(segment) not in removed]
        portion = placement.portion
        inserted = self.place(portion, placement.machine, base)
        if inserted is None or _later_delivery(inserted.delays, placement.delays):
            return False
        segments = [*base, *inserted.created]
        cursors: dict[str, float | None] = {}
        for item in tail:
            lot_id = item.portion.lot_id
            if lot_id not in cursors:
                before = self.placed.get((lot_id, item.portion.index - 1))
                cursors[lot_id] = before.end if before is not None else None
        # Every placement the break changes, as (before, after) pairs.
        pairs: list[tuple[_Placement, _Placement]] = []
        replaced = []
        for item in tail:
            lot_id = item.portion.lot_id
            again = self.place(item.portion, item.machine, segments, cursor=cursors[lot_id])
            if again is None or _later_delivery(again.delays, item.delays):
                return False
            segments.extend(again.created)
            cursors[lot_id] = again.end
            replaced.append(again)
            pairs.append((item, again))
        # Deliveries first: the portions of those lots not placed yet must not
        # get later either (the tail now ends later).
        for lot_id in dict.fromkeys(item.portion.lot_id for item in tail):
            machine = self.locked[lot_id]
            kept = self._unplaced(lot_id, machine, self.segments, self.cursor.get(lot_id))
            if kept is None:
                continue
            moved = self._unplaced(lot_id, machine, segments, cursors[lot_id])
            if moved is None or _later_delivery(_delays(moved), _delays(kept)):
                return False
            pairs.extend(zip(kept, moved, strict=True))
        # The inserted lot's own later portions follow it: their deliveries
        # count as gains, and none may get later.
        own = [(placement, inserted)]
        after = portion.index + 1
        kept = self._unplaced(
            portion.lot_id, placement.machine, [*self.segments, *placement.created],
            placement.end, start=after,
        )
        if kept:
            moved = self._unplaced(
                portion.lot_id, placement.machine, segments, inserted.end, start=after,
            )
            if moved is None or _later_delivery(_delays(moved), _delays(kept)):
                return False
            own.extend(zip(kept, moved, strict=True))
        if not _break_accepted(own, pairs):
            return False
        self.segments = base
        self.commit(inserted)
        for again in replaced:
            self.commit(again)
        return True

    def _unplaced(
        self, lot_id, machine, segments, cursor, *, start: int | None = None,
    ) -> list[_Placement] | None:
        """The lot's portions not placed yet (from ``start``), placed in order."""

        trial_segments = list(segments)
        placements: list[_Placement] = []
        first = self.next_index[lot_id] if start is None else start
        for portion in self.portions[lot_id][first:]:
            placed = self.place(portion, machine, trial_segments, cursor=cursor)
            if placed is None:
                return None
            trial_segments.extend(placed.created)
            cursor = placed.end
            placements.append(placed)
        return placements

    def continue_campaign(self, head: _Placement) -> None:
        chain = head
        machine = chain.machine
        state = _Chain(list(self.segments))
        while True:
            planning_checkpoint()
            candidates = [
                portion for portion in self.ready()
                if portion.identity == chain.portion.identity
                and self.release_abs(portion) <= chain.end
                and machine in self.machines(portion.lot_id)
            ]
            placement = None
            for candidate in sorted(candidates, key=lambda item: (item.key, item.index)):
                if candidate.lot_id in self.locked:
                    placement = self.place(
                        candidate, machine, self.segments, not_before=chain.end,
                    )
                else:
                    # A lot not yet placed continues here only if this is the
                    # machine it would choose anyway (rule 3: whole lot).
                    chosen, placement = self.choose_machine(candidate.lot_id)
                    if chosen != machine:
                        placement = None
                        continue
                    if placement is None:
                        placement = self.place(candidate, machine, self.segments)
                break
            if (
                placement is None
                or placement.start < chain.end
                or self.retained(placement) is None
                or self.vetoed(placement.portion, placement, state)
                or self.delivery_swap(placement) is not None
            ):
                return
            self.commit(placement)
            chain = placement

    def delivery_swap(self, placement: _Placement) -> _Placement | None:
        """A less urgent portion that must go first to save a delivery.

        Deliveries come before anticipation (AGENTS §1.2). The priority key
        ranks portions due the same day by quantity; when the next placement
        would make such a portion late, or later, while that portion placed
        first costs no delivery (neither the placement's lot nor the ready
        portions ranked between them gets later), the smaller one goes
        first. A whole economic lot (material version 3) cannot let a later
        order in between: any order it would make late may go first, and
        the whole lot moves after it. Returns that portion's placement, or
        ``None``.
        """

        head = placement.portion
        machine = placement.machine
        due = head.lot.production_due_day
        if due is None:
            return None
        ready = self.ready()
        rivals = sorted(
            (
                portion for portion in ready
                if portion.lot_id != head.lot_id
                and portion.key > head.key
                and portion.identity != head.identity
                and portion.lot.production_due_day is not None
                and (portion.lot.production_due_day <= due or whole_lot_release(head.lot))
                and self.release_abs(portion) < placement.end
                and machine in self.machines(portion.lot_id)
            ),
            key=lambda item: (item.key, item.index),
        )
        after_head = [*self.segments, *placement.created]
        tried = 0
        for rival in rivals:
            if tried >= _MAX_DELIVERY_SWAPS:
                break
            late = self.place(rival, machine, after_head)
            if late is None or not any(late.delays):
                continue
            tried += 1
            first = self.place(rival, machine, self.segments)
            if (
                first is None
                or sum(first.delays) >= sum(late.delays)
                or _later_delivery(first.delays, late.delays)
            ):
                continue
            if rival.lot_id not in self.locked and self.choose_machine(rival.lot_id)[0] != machine:
                continue  # rule 3: the whole lot goes where it is best
            with_rival = [*self.segments, *first.created]
            if self._delivery_kept(head.lot_id, with_rival) and all(
                not _later_delivery(
                    moved.delays, kept.delays,
                )
                for other in ready
                if other.lot_id not in (head.lot_id, rival.lot_id)
                and head.key < other.key < rival.key
                and machine in self.machines(other.lot_id)
                for kept, moved in [(
                    self.place(other, machine, after_head),
                    self.place(other, machine, with_rival),
                )]
                if kept is not None and moved is not None
            ):
                return first
        return None

    def _delivery_kept(self, lot_id: str, segments) -> bool:
        before = self.best_outlook(lot_id, self.segments)
        after = self.best_outlook(lot_id, segments)
        if before is None:
            return True
        return after is not None and not _later_delivery(after.delays, before.delays)

    # ── main loop ────────────────────────────────────────────────────────

    def build(self) -> tuple[list[Segment], list[Lot]]:
        while True:
            planning_checkpoint()
            ready = self.ready()
            if not ready:
                break
            portion = min(ready, key=lambda item: (item.key, item.index))
            machine = self.locked.get(portion.lot_id)
            placement = None
            if machine is None:
                machine, placement = self.choose_machine(portion.lot_id)
            if machine is not None and placement is None:
                placement = self.place(portion, machine, self.segments)
            if placement is None:
                raise ValueError(
                    "Não foi possível alocar as quantidades libertadas do lote "
                    f"{portion.lot_id}."
                )
            if not self.campaigns:
                self.commit(placement)
                continue
            swap = self.delivery_swap(placement)
            if swap is not None:
                self.commit(swap)
                self.continue_campaign(swap)
                continue
            if not self.break_retention(placement):
                self.commit(placement)
            self.continue_campaign(self.placed[(portion.lot_id, portion.index)])

        return self.finish()

    def finish(self) -> tuple[list[Segment], list[Lot]]:
        by_run: dict[str, list[Segment]] = {}
        for segment in self.segments:
            by_run.setdefault(segment.run_id, []).append(segment)
        for run_segments in by_run.values():
            run_qty = sum(segment.qty for segment in run_segments)
            lot_count = len({segment.lot_id for segment in run_segments})
            nominal = max(segment.run_setup_min for segment in run_segments)
            for segment in run_segments:
                segment.run_qty = run_qty
                segment.run_lot_count = lot_count
                segment.run_setup_min = nominal
        result_lots = [self.parent(lot.id, self.locked[lot.id]) for lot in self.lots]
        segments = sorted(self.segments, key=lambda s: (s.day_idx, s.start_min, s.machine_id))
        return segments, result_lots


FALLBACK_WARNING = (
    "Não foi possível juntar a produção em campanhas por ferramenta. O plano "
    "monta a ferramenta uma vez por cada lote (ou parte de entrega, nos planos "
    "antigos) e pode ter mais mudanças de ferramenta (setups). As entregas e "
    "as datas do material continuam verificadas."
)


def schedule_quantity_releases(lots, data, config, *, notes: list[str] | None = None):
    """Schedule released portions as campaigns, using the shared allocator.

    Temporary portions are never returned as new lots. Each economic lot keeps
    one chosen machine, its full quantity and its original delivery identity.
    A portion that needs a new mounting starts a new physical run; one that
    continues a mounted tool joins that run without setup. ``notes`` receives
    the plain warning shown with the plan when the fallback is used.
    """

    try:
        segments, result_lots = _CampaignBuilder(lots, data, config).build()
        assert_plan_valid(segments, data, config, lots=result_lots)
        return segments, result_lots
    except ValueError as error:  # includes PlanValidationError; never a timeout
        # A builder defect must not turn into a failed recalculation while the
        # previous behaviour (one run per portion) still gives a valid plan.
        # The planner sees it with the plan, not only in the server log.
        logger.warning(
            "Campanhas por partes falharam (%s); plano por partes separadas.", error,
        )
        if notes is not None:
            notes.append(FALLBACK_WARNING)
    segments, result_lots = _CampaignBuilder(lots, data, config, campaigns=False).build()
    assert_plan_valid(segments, data, config, lots=result_lots)
    return segments, result_lots
