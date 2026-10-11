"""Preserve what has started before the current planning day (AGENTS §2, rule 4).

A lot that has started keeps exactly the production that started: every
segment before the planning day plus the run that is mounted at that boundary
and continues without a new setup. Its later portions stay in the residual
problem and are replanned, but the lot is never re-sized: the residual
receives the rest of the same economic lot as a pre-sized lot
(``EngineData.residual_lot_remainders``) while the whole lot is credited as
committed supply, so lot sizing never sizes it a second time. The complete
plan joins both parts back into the original lot.

Frozen work never depends on movable work: a frozen segment that continues a
mounted tool without setup keeps its mount supplier frozen too (with the
earlier production of that supplier's lot).
"""

from __future__ import annotations

import copy
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.types import CommittedSupply


class NoValidCandidateError(ValueError):
    """The optimizer finished without a complete executable candidate."""



def preserved_lots_warning(started: int, freeze_day: int) -> str:
    """One wording for every path that keeps started production unchanged."""

    if started == 1:
        return (
            f"Plano anterior preservado: 1 lote iniciado antes do dia {freeze_day}; "
            "a produção já iniciada mantém-se sem alterações."
        )
    return (
        f"Plano anterior preservado: {started} lotes iniciados antes do dia {freeze_day}; "
        "a produção já iniciada mantém-se sem alterações."
    )


@dataclass
class ProtectedPlan:
    """What a replan keeps exactly as in the baseline (AGENTS §2, rule 4).

    ``segments``: every frozen segment (whole lots and the started part of
    partial lots). ``lots``: lots kept whole (all their production started,
    manual anchors, lots of an older material contract, mount suppliers).
    ``partial``: ``(original lot, remainder lot)`` of started lots whose later
    portions are replanned; the remainder is the rest of the same economic
    lot, never re-sized. ``started``: lots with production before the planning
    day, for the plan warning.
    """

    segments: list = dataclass_field(default_factory=list)
    lots: list = dataclass_field(default_factory=list)
    partial: list = dataclass_field(default_factory=list)
    anchored: set = dataclass_field(default_factory=set)
    started: set = dataclass_field(default_factory=set)

    def __bool__(self) -> bool:
        return bool(self.lots or self.partial)

def _current_planning_day(engine_data, config, *, now: datetime | None = None) -> int:
    workdays = list(getattr(engine_data, "workdays", []) or [])
    if not workdays:
        return 0
    timezone_name = str(getattr(config, "timezone", "Europe/Lisbon"))
    current = now or datetime.now(ZoneInfo(timezone_name))
    today = current.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    # Historical imports and future scenarios have no executed prefix.
    if today < str(workdays[0])[:10] or today > str(workdays[-1])[:10]:
        return 0
    for day_idx, value in enumerate(workdays):
        if str(value)[:10] >= today:
            return day_idx
    return 0


def _frozen_started_lots(baseline_result, freeze_day: int):
    if baseline_result is None or freeze_day <= 0:
        return [], []
    frozen_ids = {
        segment.lot_id
        for segment in baseline_result.segments
        if segment.day_idx < freeze_day and segment.end_min > segment.start_min
    }
    return (
        [copy.deepcopy(s) for s in baseline_result.segments if s.lot_id in frozen_ids],
        [copy.deepcopy(lot) for lot in baseline_result.lots if lot.id in frozen_ids],
    )


_HISTORICAL_SEGMENT_FIELDS = (
    "lot_id", "run_id", "machine_id", "tool_id", "day_idx", "start_min",
    "end_min", "shift", "qty", "prod_min", "setup_min", "is_continuation",
    "twin_outputs",
)
_HISTORICAL_LOT_FIELDS = (
    "id", "op_id", "tool_id", "machine_id", "qty", "prod_min",
    "setup_min", "is_twin", "twin_outputs",
)


def historical_schedule_changes(
    before: dict, after: dict, *, today: str | None = None,
) -> list[str]:
    """Started lots whose history changed (same dataset), or new past production.

    History is what happened before today: the production of a started lot
    before today and the lot itself (never re-sized). Its later portions may
    be replanned (AGENTS §2, rule 4).
    """

    before_id = str((before.get("dataset_info") or {}).get("id") or "")
    after_id = str((after.get("dataset_info") or {}).get("id") or "")
    if not before_id or before_id != after_id:
        return []
    workdays = list((before.get("engine_data") or {}).get("workdays") or [])
    if not workdays:
        return []
    timezone = str((before.get("config") or {}).get("timezone") or "Europe/Lisbon")
    current_day = today or datetime.now(ZoneInfo(timezone)).date().isoformat()
    if current_day <= str(workdays[0])[:10]:
        return []
    freeze_day = next(
        (index for index, value in enumerate(workdays) if str(value)[:10] >= current_day),
        len(workdays),
    )
    started = {
        str(segment["lot_id"])
        for segment in before.get("segments", [])
        if int(segment["day_idx"]) < freeze_day
        and float(segment["end_min"]) > float(segment["start_min"])
    }
    def lot_rows(snapshot: dict, lot_id: str):
        snapshot_days = list((snapshot.get("engine_data") or {}).get("workdays") or [])

        def calendar_date(segment):
            day = int(segment["day_idx"])
            return str(snapshot_days[day])[:10] if 0 <= day < len(snapshot_days) else None

        segments = [
            json.dumps(
                {
                    **{field: segment.get(field) for field in _HISTORICAL_SEGMENT_FIELDS},
                    "calendar_date": calendar_date(segment),
                },
                sort_keys=True, separators=(",", ":"),
            )
            for segment in snapshot.get("segments", [])
            if segment.get("lot_id") == lot_id
            and (calendar_date(segment) is None or calendar_date(segment) < current_day)
        ]
        lots = [
            json.dumps(
                {field: lot.get(field) for field in _HISTORICAL_LOT_FIELDS},
                sort_keys=True, separators=(",", ":"),
            )
            for lot in snapshot.get("lots", [])
            if lot.get("id") == lot_id
        ]
        return sorted(segments), sorted(lots)

    after_days = list((after.get("engine_data") or {}).get("workdays") or [])
    newly_past = {
        str(segment["lot_id"])
        for segment in after.get("segments", [])
        if str(segment["lot_id"]) not in started
        and 0 <= int(segment["day_idx"]) < len(after_days)
        and str(after_days[int(segment["day_idx"])])[:10] < current_day
        and float(segment["end_min"]) > float(segment["start_min"])
    }
    return sorted(
        newly_past | {
            lot_id for lot_id in started
            if lot_rows(before, lot_id) != lot_rows(after, lot_id)
        }
    )


def _honoured_anchor_lot_ids(baseline_result, engine_data, config) -> set[str]:
    """Anchored lots whose baseline placement already satisfies the anchor."""

    from backend.scheduler.validation import plan_anchor_violations

    anchors = list(getattr(engine_data, "plan_anchors", None) or [])
    if baseline_result is None or not anchors:
        return set()
    violated = {
        str(violation.get("lot_id"))
        for violation in plan_anchor_violations(baseline_result.segments, engine_data, config)
    }
    present = {segment.lot_id for segment in baseline_result.segments}
    return {
        anchor.lot_id
        for anchor in anchors
        if anchor.lot_id in present and anchor.lot_id not in violated
    }


def _protected_lots(
    baseline_result, freeze_day: int, engine_data, config, *, mount_suppliers: bool = False,
):
    """Started lots plus manually anchored lots, kept exactly as in the baseline.

    Whole lots (manual moves). ``mount_suppliers``: for a calculation that
    re-allocates the other lots, also keep whole every lot whose mounted tool
    a protected setup-free continuation needs (transitively). Improvement
    alone does not need it: it validates the complete plan.

    An anchor is a saved manual decision. The constructive solver can only
    honour it inside the CP-SAT model; when that model times out the fallback
    and the post-processing ignore it, and every candidate is rejected by the
    anchor gate. Reserving the anchored lot like confirmed history keeps the
    decision intact and lets the rest of the plan be recalculated around it.
    """

    segments, lots = _frozen_started_lots(baseline_result, freeze_day)
    anchored = _honoured_anchor_lot_ids(baseline_result, engine_data, config) - {
        lot.id for lot in lots
    }
    if anchored:
        segments = [
            *segments,
            *(copy.deepcopy(s) for s in baseline_result.segments if s.lot_id in anchored),
        ]
        lots = [
            *lots,
            *(copy.deepcopy(lot) for lot in baseline_result.lots if lot.id in anchored),
        ]
    # A protected setup-free continuation needs the lot that mounted its tool:
    # keep that supplier whole too (never leave a frozen continuation without
    # its mounting, AGENTS §4).
    if not lots or not mount_suppliers:
        return segments, lots, anchored
    protected = {lot.id for lot in lots}
    suppliers = set()
    previous = _machine_order(baseline_result.segments)
    while True:
        selected = {
            index for index, segment in enumerate(baseline_result.segments)
            if segment.lot_id in protected | suppliers
        }
        missing = {
            baseline_result.segments[supplier].lot_id
            for supplier in _mount_suppliers(baseline_result.segments, selected, previous)
        } - protected - suppliers
        if not missing:
            break
        suppliers |= missing
    if suppliers:
        segments = [
            *segments,
            *(copy.deepcopy(s) for s in baseline_result.segments if s.lot_id in suppliers),
        ]
        lots = [
            *lots,
            *(copy.deepcopy(lot) for lot in baseline_result.lots if lot.id in suppliers),
        ]
    return segments, lots, anchored


def _machine_order(segments) -> dict[int, int | None]:
    """Index of the previous productive segment on the same machine."""

    previous: dict[int, int | None] = {}
    last_by_machine: dict[str, int] = {}
    order = sorted(
        (index for index, segment in enumerate(segments) if segment.end_min > segment.start_min),
        key=lambda index: (
            segments[index].day_idx, segments[index].start_min, segments[index].end_min,
        ),
    )
    for index in order:
        machine = segments[index].machine_id
        previous[index] = last_by_machine.get(machine)
        last_by_machine[machine] = index
    return previous


def _mount_suppliers(segments, selected: set[int], previous=None) -> set[int]:
    """Unselected segments whose mounted tool a selected one continues.

    A setup-free segment relies on the preceding segment of the same machine
    when it has the same setup identity (the mounting is retained).
    """
    from backend.scheduler.setup_identity import segment_setup_identity

    previous = _machine_order(segments) if previous is None else previous
    suppliers = set()
    for index in selected:
        segment = segments[index]
        before = previous.get(index)
        if (
            before is not None and before not in selected and segment.setup_min <= 0
            and segment_setup_identity(segments[before]) == segment_setup_identity(segment)
        ):
            suppliers.add(before)
    return suppliers


def _running_continuations(segments, freeze_day: int, previous) -> list[tuple[int, list[int]]]:
    """Per machine, the run mounted at the planning-day boundary that goes on.

    Starting from the last segment before ``freeze_day`` (the boundary), the
    following segments of the same machine with the same setup identity and
    no new setup (or the rest of a setup split before the boundary) are the
    same physical run continuing. Returns ``(boundary, continuation)`` pairs.
    """
    from backend.scheduler.setup_identity import segment_setup_identity

    following: dict[int, int] = {
        before: index for index, before in previous.items() if before is not None
    }
    chains = []
    last_started: dict[str, int] = {}
    for index in previous:
        segment = segments[index]
        if segment.day_idx < freeze_day:
            current = last_started.get(segment.machine_id)
            if current is None or (
                (segment.day_idx, segment.start_min, segment.end_min)
                > (segments[current].day_idx, segments[current].start_min,
                   segments[current].end_min)
            ):
                last_started[segment.machine_id] = index
    for boundary in last_started.values():
        chain = []
        before = boundary
        index = following.get(before)
        while index is not None:
            segment, mounted = segments[index], segments[before]
            if segment_setup_identity(segment) != segment_setup_identity(mounted) or not (
                segment.setup_min <= 0 or mounted.prod_min <= 0
            ):
                break
            chain.append(index)
            before, index = index, following.get(index)
        if chain:
            chains.append((boundary, chain))
    return chains


def _blocked_continuations(segments, chains, engine_data, config) -> set[int]:
    """Continuation segments the current inputs no longer allow (e.g. an outage).

    A running run stops where the new calendar or a resource block makes it
    impossible; from there on it is replanned like any later portion.
    """
    from backend.scheduler.validation import validate_plan

    candidates = [index for _boundary, chain in chains for index in chain]
    if not candidates or engine_data is None:
        return set()
    by_key = {
        (segments[index].lot_id, segments[index].machine_id, segments[index].day_idx,
         segments[index].start_min, segments[index].end_min): index
        for index in candidates
    }
    # The boundary segments are the mounting evidence of their continuations.
    checked = [segments[index] for boundary, chain in chains for index in (boundary, *chain)]
    invalid = set()
    for violation in validate_plan(checked, engine_data, config, memo=False):
        for item in (violation, violation.get("other") or {}):
            key = (item.get("lot_id"), item.get("machine_id"), item.get("day_idx"),
                   item.get("start_min"), item.get("end_min"))
            if key in by_key:
                invalid.add(by_key[key])
    blocked = set()
    for _boundary, chain in chains:
        cut = next((position for position, index in enumerate(chain) if index in invalid), None)
        if cut is not None:
            blocked.update(chain[cut:])
    return blocked


def _protected_plan(baseline_result, freeze_day: int, engine_data, config) -> ProtectedPlan:
    """Frozen segments and lots of a replan under AGENTS §2, rule 4.

    Frozen: every segment before ``freeze_day``, the run mounted at that
    boundary while it continues without a new setup (unless the current
    inputs block it), manually anchored lots, and — closed under these two
    rules until nothing changes — the earlier production of each touched lot
    (a frozen part is always a prefix of its lot) and the mount supplier of
    every frozen setup-free continuation. A touched lot whose rest cannot be
    replanned on its own (older material contract, anchored, nothing left)
    is kept whole.
    """
    from backend.scheduler.lot_sizing import QUANTITY_MATERIAL_VERSION
    from backend.scheduler.material_quantities import lot_material_version

    if baseline_result is None:
        return ProtectedPlan()
    segments = list(baseline_result.segments)
    lots_by_id = {lot.id: lot for lot in baseline_result.lots}
    anchored = _honoured_anchor_lot_ids(baseline_result, engine_data, config)
    previous = _machine_order(segments)
    started_ids = set()
    selected: set[int] = set()
    if freeze_day > 0:
        for index, segment in enumerate(segments):
            if segment.day_idx < freeze_day and segment.end_min > segment.start_min:
                selected.add(index)
                started_ids.add(segment.lot_id)
        chains = _running_continuations(segments, freeze_day, previous)
        blocked = _blocked_continuations(segments, chains, engine_data, config)
        selected.update(
            index for _boundary, chain in chains for index in chain if index not in blocked
        )
    selected.update(
        index for index, segment in enumerate(segments) if segment.lot_id in anchored
    )
    if not selected:
        return ProtectedPlan(anchored=set())
    by_lot: dict[str, list[int]] = {}
    for index, segment in enumerate(segments):
        by_lot.setdefault(segment.lot_id, []).append(index)
    for indexes in by_lot.values():
        indexes.sort(key=lambda index: (
            segments[index].day_idx, segments[index].start_min, segments[index].end_min,
        ))

    def keeps_whole(lot_id: str) -> bool:
        lot = lots_by_id.get(lot_id)
        if lot is None or lot_id in anchored:
            return True
        if lot_material_version(lot) < QUANTITY_MATERIAL_VERSION:
            return True
        frozen_qty = sum(int(segments[index].qty) for index in by_lot[lot_id] if index in selected)
        return frozen_qty >= int(lot.qty)

    while True:
        before = len(selected)
        for lot_id in {segments[index].lot_id for index in selected}:
            indexes = by_lot[lot_id]
            if keeps_whole(lot_id):
                selected.update(indexes)
                continue
            last = max(position for position, index in enumerate(indexes) if index in selected)
            selected.update(indexes[: last + 1])
        selected |= _mount_suppliers(segments, selected, previous)
        if len(selected) == before:
            break

    touched = {segments[index].lot_id for index in selected}
    whole = {lot_id for lot_id in touched if set(by_lot[lot_id]) <= selected}
    frozen_segments = [
        copy.deepcopy(segment) for index, segment in enumerate(segments) if index in selected
    ]
    frozen_lots = [copy.deepcopy(lots_by_id[lot_id]) for lot_id in sorted(whole)
                   if lot_id in lots_by_id]
    partial = []
    for lot_id in sorted(touched - whole):
        lot = lots_by_id[lot_id]
        started = [segments[index] for index in by_lot[lot_id] if index in selected]
        partial.append((copy.deepcopy(lot), _remainder_lot(lot, started, engine_data, config)))
    return ProtectedPlan(
        segments=frozen_segments, lots=frozen_lots, partial=partial,
        anchored=anchored - started_ids, started=started_ids,
    )


def _trim_outputs(outputs: list[dict], made: dict[str, int]) -> list[dict]:
    """Outputs left after the pieces already made, first in, first out per side."""

    left = dict(made)
    remaining = []
    for output in outputs:
        side = str(output.get("op_id"))
        qty = int(output.get("qty", 0))
        used = min(qty, left.get(side, 0))
        left[side] = left.get(side, 0) - used
        if qty - used > 0:
            remaining.append({**copy.deepcopy(output), "qty": qty - used})
    return remaining


def _remainder_lot(lot, started_segments, engine_data, config):
    """The rest of a started economic lot, as one pre-sized lot (never re-sized).

    Same identity, operation, tool and machine (a started lot never changes
    machine, rule 3); its quantity and deliveries are what the started part
    did not make, first in, first out (the readiness rule). Durations follow
    the source contract for that quantity on that machine.
    """
    from backend.config.types import FactoryConfig
    from backend.scheduler.lot_sizing import _aggregate_milestones
    from backend.scheduler.resources import (
        build_setup_override_map,
        effective_oee,
        resolve_setup_hours,
    )

    config = config or FactoryConfig()
    rest = copy.deepcopy(lot)
    made_cycles = sum(int(segment.qty) for segment in started_segments)
    rest.qty = int(lot.qty) - made_cycles
    machine = next(
        (s.machine_id for s in started_segments if s.prod_min > 0), lot.machine_id,
    )
    rest.machine_id, rest.alt_machine_id = machine, None
    if lot.twin_outputs:
        made = {str(op_id): 0 for op_id, _sku, _qty in lot.twin_outputs}
        for segment in started_segments:
            for op_id, _sku, qty in segment.twin_outputs or []:
                made[str(op_id)] = made.get(str(op_id), 0) + int(qty)
        rest.twin_outputs = [
            (op_id, sku, int(qty) - made.get(str(op_id), 0))
            for op_id, sku, qty in lot.twin_outputs
        ]
    else:
        made = {str(lot.op_id): made_cycles}
    if lot.output_milestones:
        outputs = _trim_outputs(list(lot.output_milestones), made)
        for name, value in _aggregate_milestones(outputs).items():
            setattr(rest, name, value)
        rest.edd = int(rest.production_due_day)
        rest.original_edd = rest.delivery_day = int(rest.customer_delivery_day)
        rest.internal_deadline = int(rest.internal_target_day)
        demand_days = [
            int(output["customer_delivery_day"]) for output in outputs
            if not (output.get("is_economic_surplus") or output.get("is_coproduced_surplus"))
        ]
        if demand_days and lot.target_start_day is not None:
            rest.target_start_day = max(0, min(demand_days) - int(lot.start_buffer_days or 0))
    ops = {op.id: op for op in getattr(engine_data, "ops", None) or []}
    overrides = build_setup_override_map(config)
    times, setups = [], []
    for op_id, _sku, qty in rest.twin_outputs or [(rest.op_id, rest.sku, rest.qty)]:
        op = ops.get(op_id)
        if op is None:
            continue
        oee = effective_oee(op, machine, config)
        times.append(qty / (op.pH * oee) * 60.0 if op.pH > 0 and oee > 0 else 0.0)
        setups.append(resolve_setup_hours(op.sku, machine, op.sH, config, overrides) * 60)
    if times:
        rest.prod_min = max([config.min_prod_min, *times])
        rest.setup_min = max(setups, default=0.0)
    else:
        rest.prod_min = lot.prod_min * rest.qty / lot.qty if lot.qty else 0.0
    return rest


def _install_frozen_reservations(
    engine_data, frozen_segments, frozen_lots, freeze_day: int, config=None, partial=(),
) -> dict:
    """Temporarily reserve frozen output and all future resource occupancy.

    ``partial``: ``(original, remainder)`` of started lots whose rest is
    replanned. The whole original lot is credited (lot sizing must not size
    it again) and the remainder is handed to lot sizing as a pre-sized lot.
    """
    from backend.scheduler.operators import segment_operator_demand

    snapshot = {
        field: copy.deepcopy(getattr(engine_data, field))
        for field in (
            "holidays", "machine_blocked_intervals", "tool_blocked_intervals",
            "operator_blocked_intervals", "committed_supplies",
            "machine_blocked_days", "tool_blocked_days",
            "setup_crew_reservations", "plan_anchors", "protected_mounting_segments",
            "residual_lot_remainders",
        )
    }
    # Protected lots are spliced back unchanged; the residual problem must
    # not be asked to place them again.
    protected_ids = {lot.id for lot in frozen_lots}
    engine_data.protected_mounting_segments.extend(asdict(s) for s in frozen_segments)
    engine_data.residual_lot_remainders.extend(asdict(rest) for _lot, rest in partial)
    engine_data.plan_anchors = [
        anchor for anchor in engine_data.plan_anchors if anchor.lot_id not in protected_ids
    ]
    # Reserve elapsed capacity without changing the industrial calendar used
    # to derive material and subcontracting dates.
    elapsed = set(range(freeze_day))
    machines = {m.id for m in engine_data.machines}
    tools = {op.t for op in engine_data.ops}
    if config is not None:
        machines.update(config.machine_groups)
    for machine in machines:
        engine_data.machine_blocked_days.setdefault(machine, set()).update(elapsed)
    for tool in tools:
        engine_data.tool_blocked_days.setdefault(tool, set()).update(elapsed)
    groups = {machine.id: machine.group for machine in engine_data.machines}
    if config is not None:
        groups.update(config.machine_groups)
    shifts = (
        [(s.id, s.start_min, s.end_min) for s in config.shifts]
        if config is not None else [("A", 420, 930), ("B", 930, 1440)]
    )
    from backend.scheduler.setup_identity import segment_setup_identity

    # A protected continuation without setup requires its adjustment to remain
    # mounted. Inserting another tool in that gap would change the frozen lot.
    previous_by_machine = {}
    for segment in sorted(frozen_segments, key=lambda s: (s.day_idx, s.start_min, s.end_min)):
        previous = previous_by_machine.get(segment.machine_id)
        previous_by_machine[segment.machine_id] = segment
        if (previous is None or segment.day_idx < freeze_day or segment.setup_min > 0
                or segment_setup_identity(previous) != segment_setup_identity(segment)):
            continue
        start_day, start_min = max((freeze_day, 0), (previous.day_idx, previous.end_min))
        if (start_day, start_min) >= (segment.day_idx, segment.start_min):
            continue
        block = {
            "id": f"frozen-mounted-{segment.machine_id}-{segment.day_idx}-{segment.start_min}",
            "start_day": start_day, "start_min": int(start_min),
            "end_day": segment.day_idx, "end_min": int(segment.start_min),
            "category": "Plano passado", "reason": "Continuação sem reinstalação",
        }
        for day in range(start_day, segment.day_idx + 1):
            daily = {**block, "start_day": day, "end_day": day,
                     "start_min": int(start_min) if day == start_day else 0,
                     "end_min": int(segment.start_min) if day == segment.day_idx else 1440}
            if daily["end_min"] > daily["start_min"]:
                engine_data.machine_blocked_intervals.setdefault(segment.machine_id, []).append(
                    copy.deepcopy(daily)
                )
                engine_data.tool_blocked_intervals.setdefault(segment.tool_id, []).append(
                    copy.deepcopy(daily)
                )
    for index, segment in enumerate(frozen_segments):
        if segment.day_idx < freeze_day or segment.end_min <= segment.start_min:
            continue
        block = {
            "id": f"frozen-prefix-{index}",
            "start_day": int(segment.day_idx), "start_min": int(segment.start_min),
            "end_day": int(segment.day_idx), "end_min": int(segment.end_min),
            "category": "Plano passado",
            "reason": "Lote iniciado antes do dia atual",
        }
        engine_data.machine_blocked_intervals.setdefault(segment.machine_id, []).append(
            copy.deepcopy(block)
        )
        engine_data.tool_blocked_intervals.setdefault(segment.tool_id, []).append(
            copy.deepcopy(block)
        )
        if segment.setup_min > 0:
            engine_data.setup_crew_reservations.append({
                **block, "machine_id": segment.machine_id, "tool_id": segment.tool_id,
                "group": groups.get(segment.machine_id, "Grandes"),
                "end_min": min(segment.end_min, segment.start_min + segment.setup_min),
            })
        if segment.prod_min <= 0:
            continue
        production_start = segment.production_start_min
        for shift_id, shift_start, shift_end in shifts:
            start = max(production_start, shift_start)
            end = min(int(segment.end_min), shift_end)
            if start < end:
                engine_data.operator_blocked_intervals.append({
                    **block,
                    "id": f"frozen-operator-{index}-{shift_id}",
                    "group": groups.get(segment.machine_id, "Grandes"),
                    "shift": shift_id,
                    "start_min": start, "end_min": end,
                    "count": segment_operator_demand(segment, engine_data),
                })

    first_by_lot = {}
    for segment in sorted(
        frozen_segments, key=lambda item: (item.day_idx, item.start_min, item.end_min),
    ):
        first_by_lot.setdefault(segment.lot_id, segment)
    available_at = (
        f"{str(engine_data.workdays[0])[:10]}T00:00:00" if engine_data.workdays else ""
    )
    for lot in [*frozen_lots, *(original for original, _rest in partial)]:
        segment = first_by_lot.get(lot.id)
        if segment is None:
            continue
        for op_id, sku, qty in lot.twin_outputs or [(lot.op_id, lot.sku, lot.qty)]:
            engine_data.committed_supplies.append(CommittedSupply(
                op_id=str(op_id), sku=str(sku), qty=int(qty),
                available_at=available_at, available_day=0,
                machine_id=segment.machine_id, tool_id=segment.tool_id,
            ))
    return snapshot


def _restore_frozen_reservations(engine_data, snapshot: dict) -> None:
    for field, value in snapshot.items():
        setattr(engine_data, field, value)


def _splice_frozen_started_lots(result, frozen_segments, frozen_lots, partial=()):
    """Join the residual plan with the frozen work into the complete plan.

    A partial lot's residual segments rejoin its original lot: the remainder
    record is replaced by the original economic lot and the segments carry
    the lot's own metadata, as the builder writes it.
    """
    from backend.scheduler.canonical import preserved_lot_proofs
    from backend.scheduler.quantity_dispatch import _LOT_FIELDS

    frozen_ids = {lot.id for lot in frozen_lots}
    originals = {original.id: original for original, _rest in partial}
    if not frozen_ids and not originals:
        return result
    # Run identifiers are deterministic within one optimizer execution. A
    # residual plan can therefore reuse an identifier already present in the
    # historical prefix for a later, independent campaign. Keep those
    # campaigns distinct before joining them; otherwise setup validation
    # associates the future production with the historical setup.
    frozen_run_ids = {segment.run_id for segment in frozen_segments}
    residual_run_ids = {
        segment.run_id
        for segment in result.segments
        if segment.lot_id not in frozen_ids
    }
    used_run_ids = frozen_run_ids | residual_run_ids
    replacements: dict[str, str] = {}
    for run_id in sorted(frozen_run_ids & residual_run_ids):
        suffix = 1
        candidate = f"{run_id}__replanned_{suffix}"
        while candidate in used_run_ids:
            suffix += 1
            candidate = f"{run_id}__replanned_{suffix}"
        replacements[run_id] = candidate
        used_run_ids.add(candidate)
    if replacements:
        for segment in result.segments:
            if segment.lot_id not in frozen_ids and segment.run_id in replacements:
                segment.run_id = replacements[segment.run_id]
    def rejoined(segment):
        original = originals.get(segment.lot_id)
        if original is None:
            return segment
        segment = copy.copy(segment)
        segment.lot_qty = original.qty
        segment.output_milestones = copy.deepcopy(original.output_milestones)
        for name in _LOT_FIELDS:
            setattr(segment, name, getattr(original, name))
        return segment

    result.segments = [rejoined(s) for s in result.segments if s.lot_id not in frozen_ids]
    result.segments.extend(copy.deepcopy(frozen_segments))
    result.segments.sort(key=lambda s: (
        s.day_idx, s.start_min, s.machine_id, s.tool_id, s.lot_id,
    ))
    result.lots = [
        copy.deepcopy(originals[lot.id]) if lot.id in originals else lot
        for lot in result.lots if lot.id not in frozen_ids
    ]
    result.lots.extend(copy.deepcopy(frozen_lots))
    result.preserved_lot_proofs = preserved_lot_proofs(
        [s for s in frozen_segments if s.lot_id in frozen_ids], frozen_lots,
    )
    return result


def _residual_of(result, protected: ProtectedPlan):
    """The residual part of a complete plan: what a replan may still move."""
    from backend.scheduler.improvement import _segment_physical_row

    whole = {lot.id for lot in protected.lots}
    rests = {rest.id: rest for _original, rest in protected.partial}
    frozen_rows = Counter(
        _segment_physical_row(s) for s in protected.segments if s.lot_id in rests
    )
    segments = []
    for segment in result.segments:
        if segment.lot_id in whole:
            continue
        row = _segment_physical_row(segment) if segment.lot_id in rests else None
        if row is not None and frozen_rows[row] > 0:
            frozen_rows[row] -= 1
            continue
        segments.append(segment)
    lots = [rests.get(lot.id, lot) for lot in result.lots if lot.id not in whole]
    return segments, lots


def _recalculation_context(engine_data, config, baseline_result, recalculate_from_start):
    if not recalculate_from_start:
        return engine_data, baseline_result, _current_planning_day(engine_data, config)
    # Date-derived proofs belong to the old protected plan, not to observed
    # execution. Clear them only on detached inputs; keep anchors/observations.
    data, baseline = copy.deepcopy((engine_data, baseline_result))
    data.preserved_lot_proofs = {}
    baseline.preserved_lot_proofs = {}
    baseline.warnings = [
        warning for warning in baseline.warnings
        if not warning.startswith("Plano anterior preservado:")
    ]
    return data, baseline, 0


def compact_preserving_started_lots(
    engine_data, config, baseline_result, *, recalculate_from_start=False,
):
    """Recompact a valid active plan after capacity is released."""
    from backend.planning_control import planning_scope

    with planning_scope(timeout_s=60.0):
        return _compact_preserving_started_lots(
            engine_data, config, baseline_result, recalculate_from_start=recalculate_from_start,
        )


def _compact_preserving_started_lots(
    engine_data, config, baseline_result, *, recalculate_from_start=False,
):
    from backend.planning_control import improvement_time_budget
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.operators import compute_operator_alerts
    from backend.scheduler.scoring import compute_score
    from backend.scheduler.validation import assert_plan_valid

    started_at = time.perf_counter()
    engine_data, baseline_result, freeze_day = _recalculation_context(
        engine_data, config, baseline_result, recalculate_from_start,
    )
    result = copy.deepcopy(baseline_result)
    protected = _protected_plan(result, freeze_day, engine_data, config)
    result, improvement = improve_preserving_protected_lots(
        result, engine_data, copy.deepcopy(engine_data), config,
        protected.segments, protected.lots, freeze_day,
        time_budget_s=improvement_time_budget(60.0), partial=protected.partial,
    )
    result.improvement_report = improvement
    engine_data = result_validation_data(engine_data, result)
    result.score = compute_score(
        result.segments,
        result.lots,
        engine_data,
        config=config,
    )
    result.operator_alerts = compute_operator_alerts(
        result.segments,
        engine_data,
        config=config,
    )
    assert_plan_valid(result.segments, engine_data, config, lots=result.lots)
    result.time_ms = round((time.perf_counter() - started_at) * 1000, 1)
    result.warnings = [
        *_without_protection_warnings(result.warnings),
        "Capacidade libertada: o plano ativo foi novamente compactado.",
    ]
    result.warnings.extend(_protection_warnings(protected, freeze_day))
    return result


def _without_protection_warnings(warnings) -> list[str]:
    """Drop protection notes of an earlier calculation (they are restated)."""

    return [
        warning for warning in warnings
        if not warning.startswith(("Plano anterior preservado:", "Posições manuais preservadas:"))
    ]


def _protection_warnings(protected: ProtectedPlan, freeze_day: int) -> list[str]:
    warnings = []
    if protected.started:
        warnings.append(preserved_lots_warning(len(protected.started), freeze_day))
    if protected.anchored:
        warnings.append(_anchor_warning(protected.anchored))
    return warnings


def _anchor_warning(anchored: set[str]) -> str:
    return (
        f"Posições manuais preservadas: {len(anchored)} lote(s) ancorado(s) "
        "mantido(s) sem alterações."
    )


def improve_preserving_protected_lots(
    result, engine_data, original_data, config, protected_segments, protected_lots,
    freeze_day: int, *, time_budget_s: float, partial=(),
):
    """Run the no-loss improvement cycle on the residual plan only.

    Frozen work (``protected_segments``: whole protected lots and the started
    part of ``partial`` lots) stays reserved exactly as in the complete
    candidate; the rest of a partial lot is residual work. The improved
    residual is spliced back and the merged plan is re-validated on the
    original inputs; on any failure the complete candidate is kept unchanged.
    Returns ``(result, report)``.
    """
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.gates import build_gate_report
    from backend.scheduler.improvement import improve_plan
    from backend.scheduler.operators import compute_operator_alerts
    from backend.scheduler.scoring import compute_score
    from backend.scheduler.validation import validate_plan

    frozen_run_ids = {segment.run_id for segment in protected_segments}

    def evaluation_plan(segments, lots):
        # Consumers read the complete plan exactly as they read an unprotected
        # candidate (never mutating it), so no deep copy is needed (B4.3).
        # Nothing protected: the residual already is the complete plan.
        if not protected_lots and not partial:
            return segments, lots, result_validation_data(original_data, result)
        # The splice only rewrites ``run_id`` of residual segments whose run
        # id collides with a protected run: copy just those, so the
        # candidate itself is never changed.
        complete = copy.copy(result)
        complete.segments = [
            copy.copy(segment) if segment.run_id in frozen_run_ids else segment
            for segment in segments
        ]
        complete.lots = list(lots)
        complete = _splice_frozen_started_lots(
            complete, protected_segments, protected_lots, partial,
        )
        return complete.segments, complete.lots, result_validation_data(original_data, complete)

    residual_segments, residual_lots = _residual_of(
        result, ProtectedPlan(list(protected_segments), list(protected_lots), list(partial)),
    )
    snapshot = _install_frozen_reservations(
        engine_data, protected_segments, protected_lots, freeze_day, config, partial,
    )
    try:
        segments, lots, report = improve_plan(
            residual_segments, residual_lots, engine_data, config,
            time_budget_s=time_budget_s, evaluation_plan=evaluation_plan,
        )
    finally:
        _restore_frozen_reservations(engine_data, snapshot)
    if not report.get("moves_accepted"):
        return result, report

    def reject_merged(reason):
        from backend.scheduler.improvement import physical_signature

        return result, {
            **report, "status": "partial", "stop_reason": reason,
            "rolled_back_moves": int(report.get("rolled_back_moves", 0)) + report["moves_accepted"],
            "moves_accepted": 0, "accepted_by_scope": {},
            "proposal_log": {key: entry for key, entry in report.get("proposal_log", {}).items()
                             if entry.get("outcome") != "accepted"},
            "final": report.get("reference"),
            "final_signature": physical_signature(result.segments, result.lots),
        }

    improved = copy.copy(result)
    improved.segments, improved.lots = segments, lots
    if protected_lots or partial:
        improved = _splice_frozen_started_lots(
            improved, protected_segments, protected_lots, partial,
        )
    view = result_validation_data(original_data, improved)
    if validate_plan(improved.segments, view, config, lots=improved.lots):
        return reject_merged("merged_validation_failed")
    from backend.scheduler.improvement import contract_verdict

    if not contract_verdict(
        improved.segments, result.segments, view,
        candidate_lots=improved.lots, reference_lots=result.lots,
    ).admissible:
        return reject_merged("merged_contract_failed")
    improved.score = compute_score(improved.segments, improved.lots, view, config=config)
    improved.operator_alerts = compute_operator_alerts(improved.segments, view, config=config)
    improved.gate_report = build_gate_report(
        improved.segments, improved.lots, improved.score, view, config,
    )
    if not (improved.gate_report.get("physical_gate_passed")
            and improved.gate_report.get("coverage_gate_passed")):
        return reject_merged("merged_gate_failed")
    return improved, report


def optimize_preserving_started_lots(
    engine_data, config, baseline_result, *, mode="normal", audit=False, cancel_event=None,
    optimizer=None, recalculate_from_start=False,
):
    """Optimize a detached input, preserving the production that has started.

    Only what started is frozen (AGENTS §2, rule 4, ``_protected_plan``); the
    rest of a started lot is replanned as the same, pre-sized lot.
    Temporary reservations are always removed. The optimizer and final merged
    validation share one budget and propagate PlanningCancelled/PlanningTimeout.
    """
    from backend.cpo import optimize
    from backend.cpo.optimizer import (
        MODE_CONFIG,
        _strip_score_policy,
    )
    from backend.planning_control import (
        PlanningTimeout,
        candidate_observer,
        closing_reserve,
        improvement_time_budget,
        planning_checkpoint,
        planning_scope,
        remaining_time,
    )
    from backend.plans.serialize import schedule_fingerprint
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.gates import build_gate_report
    from backend.scheduler.operators import compute_operator_alerts
    from backend.scheduler.scoring import compute_score
    from backend.scheduler.validation import assert_plan_valid

    if mode not in MODE_CONFIG:
        raise ValueError(f"Unknown mode: {mode}. Use: {list(MODE_CONFIG)}")
    with planning_scope(
        timeout_s=float(MODE_CONFIG[mode].get("time_budget_s", 60.0)),
        cancel_event=cancel_event,
    ):
        engine_data, baseline_result, freeze_day = _recalculation_context(
            engine_data, config, baseline_result, recalculate_from_start,
        )
        protected = _protected_plan(baseline_result, freeze_day, engine_data, config)
        segments, lots, partial = protected.segments, protected.lots, protected.partial
        original_data = copy.deepcopy(engine_data)
        complete = None
        complete_fingerprint = None

        def retain(candidate):
            nonlocal complete, complete_fingerprint
            fingerprint = schedule_fingerprint(candidate.segments, candidate.lots)
            if fingerprint == complete_fingerprint:
                for field in ("solver_status", "feasibility", "time_ms", "journal"):
                    setattr(complete, field, copy.deepcopy(getattr(candidate, field)))
                complete.warnings = list(dict.fromkeys([*complete.warnings, *candidate.warnings]))
                if not protected:
                    complete.score = copy.deepcopy(candidate.score)
                if "solver_trace" in (candidate.gate_report or {}):
                    complete.gate_report["solver_trace"] = copy.deepcopy(
                        candidate.gate_report["solver_trace"],
                    )
                return
            merged = copy.deepcopy(candidate)
            if recalculate_from_start:
                merged.preserved_lot_proofs = {}
            if protected:
                merged = _splice_frozen_started_lots(merged, segments, lots, partial)
                view = result_validation_data(original_data, merged)
                merged.score = compute_score(merged.segments, merged.lots, view, config=config)
                merged.operator_alerts = compute_operator_alerts(
                    merged.segments, view, config=config
                )
                for warning in _protection_warnings(protected, freeze_day):
                    if warning not in merged.warnings:
                        merged.warnings.append(warning)
            else:
                view = original_data
            assert_plan_valid(merged.segments, view, config, lots=merged.lots)
            merged.gate_report = build_gate_report(
                merged.segments, merged.lots, merged.score, view, config,
            )
            if not (merged.gate_report.get("physical_gate_passed")
                    and merged.gate_report.get("coverage_gate_passed")):
                return
            planning_checkpoint()
            complete, complete_fingerprint = merged, fingerprint

        snapshot = _install_frozen_reservations(
            engine_data, segments, lots, freeze_day, config, partial,
        )
        try:
            planning_checkpoint()
            remaining = remaining_time()
            reserve = closing_reserve(float(MODE_CONFIG[mode].get("time_budget_s", 60.0)))
            with candidate_observer(retain):
                try:
                    # The improvement cycle runs once below, on the residual
                    # plan with protected lots reserved; defer it here.
                    defer = {"improve": False} if optimizer in (None, optimize) else {}
                    if defer and mode != "quick":
                        defer["reserve_improvement"] = True
                    with planning_scope(timeout_s=max(0.0, remaining - reserve)):
                        result = (optimizer or optimize)(
                            engine_data,
                            mode=mode,
                            audit=audit,
                            config=config,
                            cancel_event=cancel_event,
                            **defer,
                        )
                    retain(result)
                except PlanningTimeout:
                    planning_checkpoint()
                    if complete is None:
                        raise
                    complete.warnings.append(
                        "Tempo de melhoria esgotado; conservado o candidato completo validado."
                    )
        finally:
            _restore_frozen_reservations(engine_data, snapshot)
        planning_checkpoint()
        if complete is None:
            raise NoValidCandidateError(
                "O cálculo não produziu um candidato completo fisicamente válido."
            )
        result = complete
        solver_trace = copy.deepcopy((result.gate_report or {}).get("solver_trace"))
        # Improvement phase (plan §5): only on a complete validated candidate,
        # inside the same deadline, keeping a closing margin.
        budget = improvement_time_budget(float(MODE_CONFIG[mode]["time_budget_s"]))
        if mode == "quick":
            budget = min(10.0, budget)
        verified = dict(getattr(result, "improvement_report", None) or {})
        if budget > 0:
            result, report = improve_preserving_protected_lots(
                result, engine_data, original_data, config, segments, lots, freeze_day,
                time_budget_s=budget, partial=partial,
            )
        else:
            report = {"status": "not_evaluated", "stop_reason": "no_time_left"}
        # Search verifications of the pre-improvement state no longer apply
        # to a changed plan; keep them only when nothing was accepted.
        result.improvement_report = {
            **({"verified": verified["verified"]}
               if verified.get("verified") and not report.get("moves_accepted") else {}),
            **report,
        }
        planning_checkpoint()
        engine_data = result_validation_data(engine_data, result)
        result.gate_report = build_gate_report(
            result.segments, result.lots, result.score, engine_data, config,
        )
        if result.solver_status is not None:
            result.gate_report["solver_status"] = result.solver_status
        result.gate_report["feasibility"] = result.feasibility
        if solver_trace is not None:
            result.gate_report["solver_trace"] = solver_trace
        from backend.scheduler.improvement import improvement_gate_summary

        # Informational: explains the merged plan (history included) and
        # never changes the apply decision.
        result.gate_report["improvement"] = improvement_gate_summary(
            result.improvement_report, result.segments, result.lots, engine_data, config,
        )
        _strip_score_policy(result)
        planning_checkpoint()
        return result
