"""Machine-aware repair for late complete runs and delivery inversions.

The canonical left-shift normalizer deliberately preserves machine assignment.
That makes it safe and predictable, but it cannot recover an urgent run left on
an unavailable alternative machine by a time-limited global solve. It can also
leave a late run behind commercially later work on the same machine when moving
the run alone has no sufficiently large opening. This module adds both missing,
validation-gated neighbourhoods: rebuild one complete run against every eligible
calendar, or reflow it together with a bounded prefix or suffix of its
lower-urgency blockers. Only a strict delivery improvement is accepted.
"""

from __future__ import annotations

import copy
import math
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from backend.config.shifts import ordered_shifts
from backend.config.types import FactoryConfig
from backend.planning_control import execution_cache, planning_checkpoint
from backend.plans.serialize import MODEL_VERSION, value_fingerprint
from backend.scheduler.global_jit import _extended_holidays, _schedule_preemptive_run
from backend.scheduler.improvement import (
    Proposal,
    SkippedProposal,
    contract_verdict,
    tradeoff_proposal,
)
from backend.scheduler.jit_policy import (
    earliest_allowed_start,
    expedition_day,
    production_due_day,
)
from backend.scheduler.policy import anticipation_better
from backend.scheduler.priority import (
    delivery_improves,
    delivery_is_complete,
    delivery_not_worse,
    delivery_priority_key,
    lot_priority_key,
    lot_rupture_day,
    run_priority_key,
)
from backend.scheduler.protection import protected_lot_ids
from backend.scheduler.resources import clone_run_for_machine
from backend.scheduler.scoring import compute_score
from backend.scheduler.setup_identity import segment_setup_identity
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.scheduler.validation import PlanValidationError, assert_plan_valid, validate_plan
from backend.types import EngineData


@dataclass(slots=True)
class AlternativeRepairResult:
    segments: list[Segment]
    lots: list[Lot]
    moves: list[dict[str, Any]] = field(default_factory=list)
    evaluated: int = 0
    before_score: dict[str, Any] = field(default_factory=dict)
    after_score: dict[str, Any] = field(default_factory=dict)
    # Delivery repairs that add setups or hurt an individual order are
    # proposals for a human decision, never applied (no-loss contract).
    tradeoffs: list[dict[str, Any]] = field(default_factory=list)


_MAX_TRADEOFFS = 20
# Largest group of runs rebuilt together (plan-melhoria §5.3: "limite atual de
# seis campanhas"). Reaching it means limited scope, not global impossibility.
MAX_COORDINATED_GROUP_SIZE = 6
PLACEMENT_CACHE_LIMIT = 512


class _PlacementSearch:
    """Reuse identical allocations and permutation prefixes in this execution.

    Fixed work on *any* machine matters: shared operators, setup crews and a
    remotely mounted tool can invalidate an opening. A completed earliest
    allocation depends on that work only through its final day; work on later
    days cannot change the preceding search. Failed searches retain all work.
    """

    def __init__(self, data: EngineData, config: FactoryConfig, segments=(), runs=()):
        self.data, self.config = data, config
        self.context = value_fingerprint({"data": data, "config": config, "model": MODEL_VERSION})
        cache = execution_cache("run_placement")
        self.entries = cache.setdefault("entries", OrderedDict())
        self.stats = cache.setdefault("stats", {"hits": 0, "misses": 0})
        # Only the immutable neighbourhood reference is indexed. Holding all
        # temporary permutation prefixes here would make memory grow with work.
        self.segment_keys = {id(segment): value_fingerprint(segment) for segment in segments}
        self.run_keys = {id(run): value_fingerprint(run) for run in runs}
        self.horizons = {}

    def _segment_key(self, segment: Segment) -> str:
        cached = self.segment_keys.get(id(segment))
        return cached if cached is not None else value_fingerprint(segment)

    def place(self, run, machine_id, fixed, *, not_before_abs=None):
        planning_checkpoint()
        run_key = self.run_keys.get(id(run))
        if run_key is None:
            run_key = value_fingerprint(run)
        key = (self.context, run_key, machine_id, not_before_abs)
        if key in self.entries:
            placed, through_day, dependencies = self.entries[key]
            current = tuple(self._segment_key(segment) for segment in fixed
                            if through_day is None or segment.day_idx <= through_day)
            horizon_key = (run_key, max((segment.day_idx for segment in fixed), default=0))
            if (current == dependencies and through_day is not None
                    and horizon_key not in self.horizons):
                self.horizons[horizon_key] = _repair_horizon(run, fixed, self.data, self.config)
            if current == dependencies and (
                through_day is None or self.horizons[horizon_key] >= through_day
            ):
                self.stats["hits"] += 1
                self.entries.move_to_end(key)
                return copy.deepcopy(placed)
        self.stats["misses"] += 1
        placed = _schedule_run_earliest(
            run, machine_id, fixed, self.data, self.config, not_before_abs=not_before_abs,
        )
        planning_checkpoint()
        through_day = max(segment.day_idx for segment in placed[1]) if placed else None
        dependencies = tuple(self._segment_key(segment) for segment in fixed
                             if through_day is None or segment.day_idx <= through_day)
        self.entries[key] = (copy.deepcopy(placed), through_day, dependencies)
        while len(self.entries) > PLACEMENT_CACHE_LIMIT:
            self.entries.popitem(last=False)
        return placed


def _admissible_or_record(
    result: AlternativeRepairResult,
    candidate_segments: list[Segment],
    candidate_lots: list[Lot],
    reference_segments: list[Segment],
    reference_lots: list[Lot],
    candidate_score: dict[str, Any],
    reference_score: dict[str, Any],
    data: EngineData,
    **details: Any,
) -> bool:
    verdict = contract_verdict(
        candidate_segments, reference_segments, data,
        candidate_lots=candidate_lots, reference_lots=reference_lots,
        candidate_score=candidate_score, reference_score=reference_score,
    )
    if verdict.admissible:
        return True
    if len(result.tradeoffs) < _MAX_TRADEOFFS and not any(
        item.get("details") == details for item in result.tradeoffs
    ):
        result.tradeoffs.append(
            tradeoff_proposal("alternative_machine", verdict, details=details)
        )
    return False


@dataclass(slots=True)
class _BeamState:
    segments: list[Segment]
    lots: list[Lot]
    assignments: tuple[tuple[str, str], ...]
    completion_key: tuple[tuple[int, int, int], ...]
    tool_cursor: tuple[tuple[str, int], ...] = ()


def repair_alternative_machine_delivery(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    runs: list[ToolRun] | None = None,
    max_single_moves: int = 12,
    max_coordinated_moves: int = 4,
    max_group_size: int = MAX_COORDINATED_GROUP_SIZE,
    beam_width: int = 64,
) -> AlternativeRepairResult:
    """Return the best validated plan found by machine-aware run insertion.

    The single-run neighbourhood is searched to a fixed point.  If delivery is
    still incomplete, a bounded coordinated neighbourhood removes an urgent
    run together with the runs occupying its useful machine window, then
    rebuilds them in business-priority order.  For groups up to six runs and
    two machines each, the default beam retains the complete assignment space.
    """

    current_segments = _sorted_segments(copy.deepcopy(segments))
    current_lots = copy.deepcopy(lots)
    before_score = compute_score(
        current_segments,
        current_lots,
        data,
        config=config,
        include_operational_audit=False,
    )
    result = AlternativeRepairResult(
        segments=current_segments,
        lots=current_lots,
        before_score=dict(before_score),
        after_score=dict(before_score),
    )
    if not current_segments:
        return result

    run_map = _resolve_runs(current_segments, current_lots, runs)
    if not run_map:
        return result
    before_score["released_tool_priority_inversions"] = _tool_priority_inversion_count(
        current_segments,
        run_map,
        data,
    )
    result.before_score = dict(before_score)
    result.after_score = dict(before_score)
    if _repair_complete(before_score):
        return result

    current_score = before_score
    for _move in range(max(0, max_single_moves)):
        best: tuple[
            tuple[float, ...],
            str,
            str,
            list[Segment],
            list[Lot],
            dict[str, Any],
        ] | None = None
        repair_targets = _delivery_risk_run_ids(current_segments, run_map, data)
        repair_targets.update(
            _inverted_urgent_run_ids(current_segments, run_map, data)
        )
        candidate_runs = _non_dominated_tool_targets(
            (run_map[run_id] for run_id in repair_targets),
            data,
        )
        for run in sorted(
            candidate_runs,
            key=run_priority_key,
        ):
            machines = _eligible_machines(run, data, config, current_segments)
            if not machines:
                continue
            fixed = [segment for segment in current_segments if segment.run_id != run.id]
            for machine_id in machines:
                scheduled = _schedule_run_earliest(
                    run,
                    machine_id,
                    fixed,
                    data,
                    config,
                )
                result.evaluated += 1
                if scheduled is None:
                    continue
                rebound_run, created = scheduled
                candidate_segments = _sorted_segments([*fixed, *created])
                candidate_lots = _replace_lots(current_lots, rebound_run.lots)
                candidate_score = _validated_score(
                    candidate_segments,
                    candidate_lots,
                    data,
                    config,
                )
                if candidate_score is None or not delivery_improves(
                    candidate_score, current_score
                ):
                    continue
                if not _admissible_or_record(
                    result, candidate_segments, candidate_lots,
                    current_segments, current_lots, candidate_score, current_score, data,
                    run_id=str(run.id), to_machine=str(machine_id),
                ):
                    continue
                candidate_key = delivery_priority_key(candidate_score)
                tie = (candidate_key, str(run.id), str(machine_id))
                if best is None or tie < best[:3]:
                    best = (
                        candidate_key,
                        str(run.id),
                        str(machine_id),
                        candidate_segments,
                        candidate_lots,
                        candidate_score,
                    )
        if best is None:
            break

        _key, run_id, machine_id, current_segments, current_lots, current_score = best
        previous_machines = sorted(
            {
                segment.machine_id
                for segment in result.segments
                if segment.run_id == run_id
            }
        )
        result.moves.append(
            {
                "kind": "single_run",
                "run_id": run_id,
                "from_machines": previous_machines,
                "to_machine": machine_id,
            }
        )
        result.segments = current_segments
        result.lots = current_lots
        run_map = _resolve_runs(current_segments, current_lots, runs)
        if _repair_complete(current_score):
            break

    for _coordinated_move in range(max(0, max_coordinated_moves)):
        if _repair_complete(current_score):
            break
        coordinated = _best_coordinated_repair(
            current_segments,
            current_lots,
            current_score,
            run_map,
            data,
            config,
            max_group_size=max_group_size,
            beam_width=beam_width,
        )
        result.evaluated += coordinated[0]
        if coordinated[1] is None:
            break
        group, candidate_segments, candidate_lots, candidate_score, assignments = (
            coordinated[1]
        )
        if not _admissible_or_record(
            result, candidate_segments, candidate_lots,
            current_segments, current_lots, candidate_score, current_score, data,
            run_ids=list(group), assignments=dict(assignments),
        ):
            # The best coordinated rebuild is a trade-off; the bounded search
            # does not claim that no admissible coordinated move exists.
            break
        current_segments, current_lots, current_score = (
            candidate_segments, candidate_lots, candidate_score,
        )
        result.moves.append(
            {
                "kind": "coordinated_runs",
                "run_ids": list(group),
                "assignments": dict(assignments),
            }
        )
        result.segments = current_segments
        result.lots = current_lots
        run_map = _resolve_runs(current_segments, current_lots, runs)

    result.after_score = dict(current_score)
    return result


def anticipation_proposals(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    not_before_abs: int | None = None,
) -> Iterator[Proposal | SkippedProposal]:
    """Neighbourhood N1: reinsert one movable run on each eligible machine.

    Unlike ``repair_alternative_machine_delivery`` this does not require a
    delivery gain: a run already on time is still proposed when its lots start
    producing earlier (plan §5.2). All other runs stay fixed. Runs are tried in
    commercial priority order and a placement is proposed only if the run's
    own anticipation vector improves; the improvement evaluator decides with
    the complete plan. ``not_before_abs`` is the replanning boundary.
    """

    from backend.scheduler.improvement import production_windows

    ordered = _sorted_segments(segments)
    run_map = _resolve_runs(ordered, lots, None)
    data = _neighbourhood_calendar(ordered, run_map, data, config)
    search = _PlacementSearch(data, config, ordered, run_map.values())
    protected = protected_lot_ids(data)
    windows = production_windows(ordered)
    for run in sorted(run_map.values(), key=run_priority_key):
        if any(lot.id in protected for lot in run.lots):
            continue
        run_lots = sorted(run.lots, key=lot_priority_key)
        before = tuple(windows.get(lot.id, (math.inf, math.inf)) for lot in run_lots)
        fixed = [segment for segment in ordered if segment.run_id != run.id]
        placements = []
        for machine_id in _eligible_machines(run, data, config, ordered):
            planning_checkpoint()
            scheduled = search.place(
                run, machine_id, fixed, not_before_abs=not_before_abs,
            )
            if scheduled is None:
                continue
            placed = production_windows(scheduled[1])
            after = tuple(placed.get(lot.id, (math.inf, math.inf)) for lot in run_lots)
            if anticipation_better(after, before):
                placements.append((after, str(machine_id), scheduled))
        # The evaluator accepts the first strict gain: offer the best machine first.
        for after, machine_id, (rebound_run, created) in sorted(
            placements, key=lambda item: item[:2],
        ):
            subject = {
                "key": f"anticipate:{run.id}:{machine_id}",
                "kind": "alternative_anticipation",
                "run_id": str(run.id),
                "to_machine": str(machine_id),
                "start_gain_min": round(before[0][0] - after[0][0], 1),
            }
            candidate_segments = _sorted_segments([*fixed, *created])
            candidate_lots = _replace_lots(lots, rebound_run.lots)
            violations = validate_plan(candidate_segments, data, config, lots=candidate_lots)
            if violations:
                yield SkippedProposal(
                    subject, "physical",
                    tuple(sorted({str(item.get("kind", "physical")) for item in violations})),
                )
                continue
            yield Proposal(candidate_segments, candidate_lots, subject=subject)


def group_reinsertion_proposals(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    size: int,
    not_before_abs: int | None = None,
) -> Iterator[Proposal | SkippedProposal]:
    """Neighbourhoods N2/N3: reinsert ``size`` consecutive users of a resource.

    Consecutive means adjacent in the use of one machine, one physical tool
    or the setup crew of one machine group.

    Every order of the group and every eligible machine of each run are
    tried with all other runs fixed. This covers what one-run reinsertion
    cannot: swapping campaigns, or freeing the opening one run needs by
    relocating its neighbours (plan §5.2). Only groups where a run still
    starts after its own floor (material release or replanning boundary) can
    gain and are tried, most urgent group first. A proposal requires the
    group's anticipation vector to improve; the improvement evaluator decides
    on the complete plan.
    """

    from itertools import permutations

    from backend.scheduler.improvement import production_windows

    shifts = ordered_shifts(config)
    if not shifts or size < 2:
        return
    ordered = _sorted_segments(segments)
    run_map = _resolve_runs(ordered, lots, None)
    data = _neighbourhood_calendar(ordered, run_map, data, config)
    search = _PlacementSearch(data, config, ordered, run_map.values())
    protected = protected_lot_ids(data)
    windows = production_windows(ordered)
    holidays = _extended_holidays(data, -20, data.n_days + 400)

    def has_slack(run: ToolRun) -> bool:
        floor = max(
            min(max(0, earliest_allowed_start(lot, holidays)) for lot in run.lots) * 1440
            + int(shifts[0].start_min),
            int(not_before_abs or 0),
        )
        starts = [windows[lot.id][0] for lot in run.lots if lot.id in windows]
        return bool(starts) and min(starts) > floor

    movable = {
        run_id: run for run_id, run in run_map.items()
        if not any(lot.id in protected for lot in run.lots)
    }
    eligible = {run_id: _eligible_machines(run, data, config, ordered)
                for run_id, run in movable.items()}
    # Runs are coupled through every shared resource: consecutive uses of a
    # machine, of a physical tool, and of the setup crew of a machine group.
    machine_group = {machine.id: machine.group for machine in data.machines}
    machine_group.update(config.machine_groups)
    sequences: dict[tuple[str, str], list[str]] = {}

    def follow(resource: tuple[str, str], run_id: str) -> None:
        sequence = sequences.setdefault(resource, [])
        if not sequence or sequence[-1] != run_id:
            sequence.append(run_id)

    for segment in ordered:
        if segment.run_id not in movable:
            continue
        follow(("machine", segment.machine_id), segment.run_id)
        follow(("tool", segment.tool_id), segment.run_id)
        if segment.setup_min > 0:
            follow(("crew", machine_group.get(segment.machine_id, "")), segment.run_id)
    slack = {run_id: has_slack(run) for run_id, run in movable.items()}
    groups = {
        tuple(sorted(group))
        for sequence in sequences.values()
        for group in zip(*(sequence[offset:] for offset in range(size)), strict=False)
        if len(set(group)) == size and any(slack[run_id] for run_id in group)
    }

    def group_lots(group: tuple[str, ...]) -> list[Lot]:
        return sorted((lot for run_id in group for lot in movable[run_id].lots),
                      key=lot_priority_key)

    def chains(order, fixed, created, rebound, assignments):
        if not order:
            yield created, rebound, assignments
            return
        run = movable[order[0]]
        for machine_id in eligible[run.id]:
            planning_checkpoint()
            placed = search.place(
                run, machine_id, [*fixed, *created],
                not_before_abs=not_before_abs,
            )
            if placed is not None:
                yield from chains(
                    order[1:], fixed, [*created, *placed[1]], [*rebound, *placed[0].lots],
                    (*assignments, (run.id, str(machine_id))),
                )

    for group in sorted(groups, key=lambda item: (lot_priority_key(group_lots(item)[0]), item)):
        member_lots = group_lots(group)
        before = tuple(windows.get(lot.id, (math.inf, math.inf)) for lot in member_lots)
        fixed = [segment for segment in ordered if segment.run_id not in group]
        placements = []
        for order in permutations(group):
            for created, rebound, assignments in chains(list(order), fixed, [], [], ()):
                placed = production_windows(created)
                after = tuple(placed.get(lot.id, (math.inf, math.inf)) for lot in member_lots)
                if anticipation_better(after, before):
                    placements.append((after, assignments, created, rebound))
        for _after, assignments, created, rebound_lots in sorted(
            placements, key=lambda item: item[:2],
        ):
            subject = {
                "key": "group:" + "|".join(f"{run}>{machine}" for run, machine in assignments),
                "kind": "group_reinsertion",
                "assignments": [list(item) for item in assignments],
            }
            candidate_segments = _sorted_segments([*fixed, *created])
            candidate_lots = _replace_lots(lots, rebound_lots)
            violations = validate_plan(candidate_segments, data, config, lots=candidate_lots)
            if violations:
                yield SkippedProposal(
                    subject, "physical",
                    tuple(sorted({str(item.get("kind", "physical")) for item in violations})),
                )
                continue
            yield Proposal(candidate_segments, candidate_lots, subject=subject)


def _non_dominated_tool_targets(
    runs: Iterable[ToolRun],
    data: EngineData,
) -> list[ToolRun]:
    """Do not repair a later run ahead of a released urgent run on its tool."""

    holidays = _extended_holidays(data, -20, data.n_days + 400)
    selected: list[ToolRun] = []
    by_tool: dict[str, list[ToolRun]] = {}
    for run in runs:
        by_tool.setdefault(run.tool_id, []).append(run)
    for tool_runs in by_tool.values():
        ordered = sorted(tool_runs, key=run_priority_key)
        floors = {
            run.id: min(
                (earliest_allowed_start(lot, holidays) for lot in run.lots),
                default=0,
            )
            for run in ordered
        }
        for index, run in enumerate(ordered):
            if any(floors[urgent.id] <= floors[run.id] for urgent in ordered[:index]):
                continue
            selected.append(run)
    return selected


def _resolve_runs(
    segments: list[Segment],
    lots: list[Lot],
    source_runs: list[ToolRun] | None,
) -> dict[str, ToolRun]:
    lots_by_id = {lot.id: lot for lot in lots}
    source_by_id = {run.id: run for run in source_runs or []}
    segments_by_run: dict[str, list[Segment]] = {}
    for segment in segments:
        segments_by_run.setdefault(segment.run_id, []).append(segment)

    resolved: dict[str, ToolRun] = {}
    for run_id, run_segments in segments_by_run.items():
        ordered_lot_ids = list(
            dict.fromkeys(
                segment.lot_id
                for segment in _sorted_segments(run_segments)
                if segment.lot_id in lots_by_id
            )
        )
        source = source_by_id.get(run_id)
        if source is not None:
            source_order = [lot.id for lot in source.lots if lot.id in ordered_lot_ids]
            ordered_lot_ids = [
                *source_order,
                *(lot_id for lot_id in ordered_lot_ids if lot_id not in source_order),
            ]
        run_lots = [lots_by_id[lot_id] for lot_id in ordered_lot_ids]
        if not run_lots:
            continue
        if source is not None:
            run = copy.copy(source)
            run.lots = run_lots
        else:
            first = min(run_segments, key=lambda segment: (segment.day_idx, segment.start_min))
            setup_min = max(
                [float(first.run_setup_min or 0.0), float(run_lots[0].setup_min or 0.0)]
                + [float(segment.setup_min or 0.0) for segment in run_segments]
            )
            run = ToolRun(
                id=run_id,
                tool_id=first.tool_id,
                machine_id=run_lots[0].machine_id,
                alt_machine_id=run_lots[0].alt_machine_id,
                lots=run_lots,
                setup_min=setup_min,
                total_prod_min=sum(float(lot.prod_min) for lot in run_lots),
                total_min=setup_min + sum(float(lot.prod_min) for lot in run_lots),
                edd=min(int(lot.edd) for lot in run_lots),
            )
        run.setup_min = max(0.0, float(run.setup_min))
        run.total_prod_min = sum(max(0.0, float(lot.prod_min)) for lot in run_lots)
        run.total_min = run.setup_min + run.total_prod_min
        resolved[run_id] = run
    return resolved


def _eligible_machines(
    run: ToolRun,
    data: EngineData,
    config: FactoryConfig,
    segments: list[Segment],
) -> list[str]:
    known = {machine.id for machine in data.machines}
    active = {
        machine_id
        for machine_id in known
        if config.machines.get(machine_id) is None
        or config.machines[machine_id].active
    }
    ops_by_id = {op.id: op for op in data.ops}
    lot_options: list[set[str]] = []
    for lot in run.lots:
        op_ids = [lot.op_id]
        if lot.twin_outputs:
            op_ids = [str(op_id) for op_id, _sku, _qty in lot.twin_outputs]
        options = {
            machine_id
            for op_id in op_ids
            for op in [ops_by_id.get(op_id)]
            if op is not None
            for machine_id in (op.m, op.alt)
            if machine_id
        }
        if not options:
            options = {
                machine_id
                for machine_id in (lot.machine_id, lot.alt_machine_id)
                if machine_id
            }
        if options:
            lot_options.append(options)

    shared = set.intersection(*lot_options) if lot_options else set()
    if not shared:
        shared = set().union(*lot_options) if lot_options else set()
    current = {
        segment.machine_id for segment in segments if segment.run_id == run.id
    }
    preferred = [
        *sorted(current),
        run.machine_id,
        run.alt_machine_id,
        *sorted(shared),
    ]
    return [
        machine_id
        for machine_id in dict.fromkeys(preferred)
        if machine_id and machine_id in shared and machine_id in active
    ]


def _schedule_run_earliest(
    run: ToolRun,
    machine_id: str,
    fixed_segments: list[Segment],
    data: EngineData,
    config: FactoryConfig,
    *,
    not_before_abs: int | None = None,
) -> tuple[ToolRun, list[Segment]] | None:
    candidate = clone_run_for_machine(run, machine_id, data, config)
    candidate.machine_id = machine_id
    ops_by_id = {op.id: op for op in data.ops}
    horizon_day = _repair_horizon(candidate, fixed_segments, data, config)
    # Project the factory calendar once, before adding the plan bookings: the
    # allocator asks for windows thousands of times and an unprojected
    # horizon would re-merge every booking on each request.
    data = _projected_calendar(data, config, horizon_day + 2)
    holidays = _extended_holidays(data, -20, horizon_day + 2)
    calendar_data = _with_plan_resource_blocks(data, fixed_segments)
    first_shift = ordered_shifts(config)[0] if ordered_shifts(config) else None
    if first_shift is None:
        return None
    first_lot = min(candidate.lots, key=lot_priority_key)
    start_after = max(
        max(0, earliest_allowed_start(first_lot, holidays)) * 1440
        + int(first_shift.start_min),
        int(not_before_abs or 0),
    )

    # Dynamic plan bookings are represented as calendar blocks while finding
    # slices.  If a tentative run straddles such a booking, restart after it so
    # a campaign is never interleaved with another run.
    for _attempt in range(len(fixed_segments) + 2):
        scheduled = _schedule_preemptive_run(
            candidate,
            machine_id,
            fixed_segments,
            calendar_data,
            config,
            ops_by_id,
            holidays,
            start_after,
            horizon_day,
        )
        if scheduled is None:
            return None
        created, _finish_abs, _preemptions = scheduled
        campaign_start = min(
            segment.day_idx * 1440 + int(segment.start_min) for segment in created
        )
        campaign_end = max(
            segment.day_idx * 1440 + int(segment.end_min) for segment in created
        )
        interruptions = sorted(
            (
                segment.day_idx * 1440 + int(segment.start_min),
                segment.day_idx * 1440 + int(segment.end_min),
            )
            for segment in fixed_segments
            if (segment.machine_id == machine_id or segment.tool_id == candidate.tool_id)
            and campaign_start
            < segment.day_idx * 1440 + int(segment.end_min)
            and segment.day_idx * 1440 + int(segment.start_min) < campaign_end
        )
        if not interruptions:
            return candidate, created
        next_start = interruptions[0][1]
        if next_start <= start_after:
            next_start = start_after + 1
        start_after = next_start
    return None


def _projected_calendar(data: EngineData, config: FactoryConfig, through_day: int) -> EngineData:
    from backend.transform.calendars import calendar_window

    return calendar_window(data, config, through_day)


def _neighbourhood_calendar(
    segments: list[Segment],
    run_map: dict[str, ToolRun],
    data: EngineData,
    config: FactoryConfig,
) -> EngineData:
    """One calendar projection covering every run a neighbourhood may place."""

    horizon = max(
        (_repair_horizon(run, segments, data, config) for run in run_map.values()),
        default=0,
    )
    return _projected_calendar(data, config, horizon + 2)


def _with_plan_resource_blocks(
    data: EngineData,
    segments: Iterable[Segment],
) -> EngineData:
    cloned = copy.copy(data)
    cloned.machine_blocked_intervals = {
        resource: [dict(block) for block in blocks]
        for resource, blocks in data.machine_blocked_intervals.items()
    }
    cloned.tool_blocked_intervals = {
        resource: [dict(block) for block in blocks]
        for resource, blocks in data.tool_blocked_intervals.items()
    }
    for segment in segments:
        block = {
            "id": f"plan:{segment.run_id}:{segment.lot_id}",
            "start_day": int(segment.day_idx),
            "start_min": int(segment.start_min),
            "end_day": int(segment.day_idx),
            "end_min": int(segment.end_min),
        }
        cloned.machine_blocked_intervals.setdefault(segment.machine_id, []).append(block)
        cloned.tool_blocked_intervals.setdefault(segment.tool_id, []).append(block)
    return cloned


def _repair_horizon(
    run: ToolRun,
    fixed_segments: list[Segment],
    data: EngineData,
    config: FactoryConfig,
) -> int:
    holidays = _extended_holidays(data, -20, data.n_days + 400)
    latest_due = max((production_due_day(lot, holidays) for lot in run.lots), default=0)
    latest_segment = max((segment.day_idx for segment in fixed_segments), default=0)
    blocked_days = [
        int(block.get("start_day", 0))
        for blocks in (
            *data.machine_blocked_intervals.values(),
            *data.tool_blocked_intervals.values(),
        )
        for block in blocks
    ]
    blocked_days.extend(
        day
        for days in (*data.machine_blocked_days.values(), *data.tool_blocked_days.values())
        for day in days
    )
    duration_days = math.ceil(max(1.0, run.total_min) / max(1, config.day_capacity_min))
    return max(
        data.n_days + duration_days + 30,
        latest_due + duration_days + 30,
        latest_segment + duration_days + 30,
        max(blocked_days, default=0) + duration_days + 2,
    )


def _validated_score(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
) -> dict[str, Any] | None:
    try:
        assert_plan_valid(segments, data, config, lots=lots)
    except (PlanValidationError, TypeError, ValueError):
        return None
    score = compute_score(
        segments,
        lots,
        data,
        config=config,
        include_operational_audit=False,
    )
    score["released_tool_priority_inversions"] = _tool_priority_inversion_count(
        segments,
        _resolve_runs(segments, lots, None),
        data,
    )
    return score


def _repair_complete(score: dict[str, Any]) -> bool:
    return delivery_is_complete(score) and int(
        score.get("released_tool_priority_inversions", 0) or 0
    ) == 0


def _replace_lots(current: list[Lot], replacements: Iterable[Lot]) -> list[Lot]:
    by_id = {lot.id: lot for lot in replacements}
    return [by_id.get(lot.id, lot) for lot in current]


def _best_coordinated_repair(
    segments: list[Segment],
    lots: list[Lot],
    score: dict[str, Any],
    run_map: dict[str, ToolRun],
    data: EngineData,
    config: FactoryConfig,
    *,
    max_group_size: int,
    beam_width: int,
) -> tuple[
    int,
    tuple[
        tuple[str, ...],
        list[Segment],
        list[Lot],
        dict[str, Any],
        tuple[tuple[str, str], ...],
    ]
    | None,
]:
    evaluated = 0
    best = None
    best_key = delivery_priority_key(score)
    before_tool_inversions = _tool_priority_inversion_count(
        segments,
        run_map,
        data,
    )
    best_selection_key: tuple[Any, ...] = (
        before_tool_inversions,
        best_key,
    )
    for group in _coordinated_groups(
        segments,
        lots,
        run_map,
        data,
        config,
        max_group_size=max_group_size,
    ):
        fixed = [segment for segment in segments if segment.run_id not in group]
        ordered_runs = sorted((run_map[run_id] for run_id in group), key=run_priority_key)
        states = [
            _BeamState(
                segments=fixed,
                lots=lots,
                assignments=(),
                completion_key=(),
                tool_cursor=(),
            )
        ]
        for run in ordered_runs:
            next_states: list[_BeamState] = []
            for state in states:
                tool_cursor = dict(state.tool_cursor)
                for machine_id in _eligible_machines(run, data, config, segments):
                    scheduled = _schedule_run_earliest(
                        run,
                        machine_id,
                        state.segments,
                        data,
                        config,
                        not_before_abs=tool_cursor.get(run.tool_id),
                    )
                    evaluated += 1
                    if scheduled is None:
                        continue
                    rebound_run, created = scheduled
                    completion = max(segment.day_idx for segment in created)
                    due = min(
                        production_due_day(lot, _extended_holidays(data, -20, data.n_days + 400))
                        for lot in rebound_run.lots
                    )
                    next_tool_cursor = dict(tool_cursor)
                    next_tool_cursor[run.tool_id] = max(
                        segment.day_idx * 1440 + int(segment.end_min)
                        for segment in created
                    )
                    next_states.append(
                        _BeamState(
                            segments=_sorted_segments([*state.segments, *created]),
                            lots=_replace_lots(state.lots, rebound_run.lots),
                            assignments=(*state.assignments, (run.id, machine_id)),
                            completion_key=(
                                *state.completion_key,
                                (int(completion > due), max(0, completion - due), completion),
                            ),
                            tool_cursor=tuple(sorted(next_tool_cursor.items())),
                        )
                    )
            states = sorted(
                next_states,
                key=lambda state: (state.completion_key, state.assignments),
            )[: max(1, beam_width)]
            if not states:
                break

        for state in states:
            candidate_score = _validated_score(
                state.segments,
                state.lots,
                data,
                config,
            )
            if candidate_score is None or not delivery_not_worse(candidate_score, score):
                continue
            key = delivery_priority_key(candidate_score)
            tool_inversions = _tool_priority_inversion_count(
                state.segments,
                run_map,
                data,
            )
            if tool_inversions >= before_tool_inversions and key >= best_key:
                continue
            selection_key = (tool_inversions, key)
            if selection_key >= best_selection_key:
                continue
            best_key = key
            best_selection_key = selection_key
            best = (
                group,
                state.segments,
                state.lots,
                candidate_score,
                state.assignments,
            )
    return evaluated, best


def _tool_priority_inversion_count(
    segments: list[Segment],
    run_map: dict[str, ToolRun],
    data: EngineData,
) -> int:
    """Count released lower-priority runs placed first on one physical tool."""

    holidays = _extended_holidays(data, -20, data.n_days + 400)
    starts: dict[str, tuple[int, int]] = {}
    for segment in segments:
        position = (int(segment.day_idx), int(segment.start_min))
        starts[segment.run_id] = min(starts.get(segment.run_id, position), position)
    by_tool: dict[str, list[ToolRun]] = {}
    for run_id in starts:
        run = run_map.get(run_id)
        if run is not None:
            by_tool.setdefault(run.tool_id, []).append(run)
    count = 0
    for runs in by_tool.values():
        timeline = sorted(runs, key=lambda run: (starts[run.id], run.id))
        floors = {
            run.id: min(
                (earliest_allowed_start(lot, holidays) for lot in run.lots),
                default=0,
            )
            for run in timeline
        }
        for earlier_index, earlier in enumerate(timeline):
            for later in timeline[earlier_index + 1 :]:
                if run_priority_key(later)[:5] >= run_priority_key(earlier)[:5]:
                    continue
                if floors[later.id] > floors[earlier.id]:
                    continue
                count += 1
    return count


def _inverted_urgent_run_ids(
    segments: list[Segment],
    run_map: dict[str, ToolRun],
    data: EngineData,
) -> set[str]:
    """Return urgent runs currently placed after released later work."""

    holidays = _extended_holidays(data, -20, data.n_days + 400)
    starts: dict[str, tuple[int, int]] = {}
    for segment in segments:
        position = (int(segment.day_idx), int(segment.start_min))
        starts[segment.run_id] = min(starts.get(segment.run_id, position), position)
    by_tool: dict[str, list[ToolRun]] = {}
    for run_id in starts:
        run = run_map.get(run_id)
        if run is not None:
            by_tool.setdefault(run.tool_id, []).append(run)
    urgent_ids: set[str] = set()
    for runs in by_tool.values():
        timeline = sorted(runs, key=lambda run: (starts[run.id], run.id))
        floors = {
            run.id: min(
                (earliest_allowed_start(lot, holidays) for lot in run.lots),
                default=0,
            )
            for run in timeline
        }
        for earlier_index, blocking in enumerate(timeline):
            for urgent in timeline[earlier_index + 1 :]:
                if run_priority_key(urgent)[:5] >= run_priority_key(blocking)[:5]:
                    continue
                if floors[urgent.id] <= floors[blocking.id]:
                    urgent_ids.add(urgent.id)
    return urgent_ids


def _coordinated_groups(
    segments: list[Segment],
    lots: list[Lot],
    run_map: dict[str, ToolRun],
    data: EngineData,
    config: FactoryConfig,
    *,
    max_group_size: int,
) -> list[tuple[str, ...]]:
    holidays = _extended_holidays(data, -20, data.n_days + 400)
    late_runs = _delivery_risk_run_ids(segments, run_map, data)
    late_runs.update(_inverted_urgent_run_ids(segments, run_map, data))
    segments_by_run: dict[str, list[Segment]] = {}
    for segment in segments:
        segments_by_run.setdefault(segment.run_id, []).append(segment)
    targets = [
        run
        for run in sorted(run_map.values(), key=run_priority_key)
        if run.id in late_runs and _eligible_machines(run, data, config, segments)
    ]
    def append_group(selected: list[ToolRun]) -> None:
        group = tuple(run.id for run in sorted(selected, key=run_priority_key))
        if len(group) < 2 or group in seen:
            return
        seen.add(group)
        groups.append(group)

    groups: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for target in targets[:16]:
        machines = set(_eligible_machines(target, data, config, segments))
        floor = min(
            max(0, earliest_allowed_start(lot, holidays)) for lot in target.lots
        )
        due = max(production_due_day(lot, holidays) for lot in target.lots)

        # Rebuild the complete movable tail of an inverted physical-tool
        # sequence. A bounded blocker neighbourhood is insufficient when an
        # urgent run has a setup-free successor: moving only the urgent run
        # invalidates that retained setup, so the greedy repair moves the
        # successor first and recreates the inversion. One physical tool gives
        # this group a deterministic total order, keeping the beam bounded even
        # when the chain is larger than the generic coordinated neighbourhood.
        target_priority = run_priority_key(target)
        tool_timeline = sorted(
            (
                run
                for run in run_map.values()
                if run.tool_id == target.tool_id
                and run_priority_key(run) >= target_priority
            ),
            key=run_priority_key,
        )
        target_start = min(
            (
                segment.day_idx * 1440 + int(segment.start_min)
                for segment in segments_by_run.get(target.id, [])
            ),
            default=0,
        )
        has_tool_inversion = any(
            run.id != target.id
            and run_priority_key(run) > target_priority
            and min(
                (
                    segment.day_idx * 1440 + int(segment.start_min)
                    for segment in segments_by_run.get(run.id, [])
                ),
                default=target_start,
            ) < target_start
            for run in tool_timeline
        )
        if has_tool_inversion:
            append_group(tool_timeline)

        retained_chain = _retained_setup_successors(
            target.id,
            segments,
            run_map,
        )
        if retained_chain:
            append_group([target, *retained_chain])

        # Preserve the original alternative-machine neighbourhood. Its blockers
        # are bounded to the useful pre-due window; an unbounded same-tool clause
        # used to pull unrelated future campaigns into this group.
        if len(machines) > 1:
            alternative_blockers = {
                segment.run_id
                for segment in segments
                if segment.run_id != target.id
                and segment.run_id in run_map
                and floor <= segment.day_idx <= due
                and (segment.tool_id == target.tool_id or segment.machine_id in machines)
            }
            ordered = sorted(
                (run_map[run_id] for run_id in alternative_blockers),
                key=run_priority_key,
            )
            append_group([target, *ordered[: max(0, max_group_size - 1)]])

        target_segments = segments_by_run.get(target.id, [])
        if not target_segments:
            continue
        target_start = min(
            segment.day_idx * 1440 + int(segment.start_min)
            for segment in target_segments
        )
        commercial_priority = run_priority_key(target)[:7]

        # A long late campaign may have no single contiguous opening because
        # several later orders occupy the useful window. Search incremental
        # chronological prefixes and suffixes of exactly those inversions. A
        # suffix matters when the earlier blockers should stay on time and only
        # the final campaign(s) must move to expose an idle window. Keeping equal
        # or earlier commercial milestones fixed avoids manufacturing new
        # material or delivery failures merely to make the urgent run look earlier.
        for machine_id in sorted(machines):
            inversion_blockers: list[ToolRun] = []
            for run_id, run_segments in segments_by_run.items():
                if run_id == target.id or run_id not in run_map:
                    continue
                blocker = run_map[run_id]
                if run_priority_key(blocker)[:7] <= commercial_priority:
                    continue
                if not any(
                    segment.machine_id == machine_id or segment.tool_id == target.tool_id
                    for segment in run_segments
                ):
                    continue
                blocker_start = min(
                    segment.day_idx * 1440 + int(segment.start_min)
                    for segment in run_segments
                )
                if blocker_start >= target_start:
                    continue
                # Work already under way before the target's due day remains a
                # fixed predecessor. The reflow begins with genuinely later
                # orders that consume capacity on or after that checkpoint.
                if min(segment.day_idx for segment in run_segments) < due:
                    continue
                inversion_blockers.append(blocker)

            inversion_blockers.sort(
                key=lambda blocker: (
                    min(
                        segment.day_idx * 1440 + int(segment.start_min)
                        for segment in segments_by_run[blocker.id]
                    ),
                    run_priority_key(blocker),
                )
            )
            blocker_limit = min(
                len(inversion_blockers),
                max(0, max_group_size - 1),
            )
            for count in range(1, blocker_limit + 1):
                append_group([target, *inversion_blockers[:count]])

            tail = inversion_blockers[-blocker_limit:] if blocker_limit else []
            for count in range(1, len(tail) + 1):
                append_group([target, *tail[-count:]])
    return groups


def _retained_setup_successors(
    run_id: str,
    segments: list[Segment],
    run_map: dict[str, ToolRun],
) -> list[ToolRun]:
    """Return consecutive runs whose zero setup depends on ``run_id``."""

    own = [segment for segment in segments if segment.run_id == run_id]
    if not own:
        return []
    machine_ids = {segment.machine_id for segment in own}
    if len(machine_ids) != 1:
        return []
    machine_id = next(iter(machine_ids))
    by_run: dict[str, list[Segment]] = {}
    for segment in segments:
        if segment.machine_id == machine_id:
            by_run.setdefault(segment.run_id, []).append(segment)
    ordered_ids = sorted(
        by_run,
        key=lambda candidate: min(
            (segment.day_idx, segment.start_min) for segment in by_run[candidate]
        ),
    )
    try:
        index = ordered_ids.index(run_id)
    except ValueError:
        return []
    previous = max(
        by_run[run_id],
        key=lambda segment: (segment.day_idx, segment.end_min),
    )
    result: list[ToolRun] = []
    for candidate_id in ordered_ids[index + 1 :]:
        candidate_segments = by_run[candidate_id]
        first = min(
            candidate_segments,
            key=lambda segment: (segment.day_idx, segment.start_min),
        )
        if (
            float(first.setup_min) > 0
            or segment_setup_identity(first) != segment_setup_identity(previous)
        ):
            break
        candidate = run_map.get(candidate_id)
        if candidate is None:
            break
        result.append(candidate)
        previous = max(
            candidate_segments,
            key=lambda segment: (segment.day_idx, segment.end_min),
        )
    return result


def _delivery_risk_run_ids(
    segments: list[Segment],
    run_map: dict[str, ToolRun],
    data: EngineData,
) -> set[str]:
    """Runs completing after a delivery, stock-rupture or dispatch checkpoint."""

    holidays = _extended_holidays(data, -20, data.n_days + 400)
    completion_by_lot: dict[str, int] = {}
    for segment in segments:
        completion_by_lot[segment.lot_id] = max(
            completion_by_lot.get(segment.lot_id, segment.day_idx),
            segment.day_idx,
        )
    result: set[str] = set()
    for run_id, run in run_map.items():
        for lot in run.lots:
            checkpoints = [expedition_day(lot), lot_rupture_day(lot)]
            if lot.is_subcontracted:
                checkpoints.append(production_due_day(lot, holidays))
            if completion_by_lot.get(lot.id, data.n_days) > min(checkpoints):
                result.add(run_id)
                break
    return result


def _sorted_segments(segments: Iterable[Segment]) -> list[Segment]:
    return sorted(
        segments,
        key=lambda segment: (
            segment.day_idx,
            segment.start_min,
            segment.machine_id,
            segment.run_id,
            segment.lot_id,
        ),
    )
