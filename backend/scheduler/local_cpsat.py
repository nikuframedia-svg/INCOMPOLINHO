"""Neighbourhood N4: local CP-SAT over a coupled group of runs (plan §5.3).

For a movable run that still starts after its own floor, the group is that
run plus the movable runs that use its eligible machines, its tool or its
setup crew inside its useful window (at most ``max_group``). A small CP-SAT
model chooses the order and machine of the group on a productive-time axis:

* exactly one eligible machine per run (optional intervals);
* no overlap per machine and per physical tool, including the fixed work of
  every other run;
* the setup crew of the machine group as a cumulative resource;
* nothing (setup included) before the material release or replanning floor.

It is solved lexicographically, most urgent run first, each production
start bounded by the value already found. The model abstracts calendars,
operators and retained mounts, so it only proposes an order and assignment:
the existing allocator materialises it against every real constraint and the
improvement evaluator decides on the complete plan. ``FEASIBLE`` or a time
limit is never reported as optimality.
"""

from __future__ import annotations

import math
from collections.abc import Iterator

from backend.config.types import FactoryConfig
from backend.planning_control import planning_checkpoint, solve_cpsat
from backend.scheduler.alternative_repair import (
    _eligible_machines,
    _extended_holidays,
    _neighbourhood_calendar,
    _replace_lots,
    _resolve_runs,
    _retained_setup_successors,
    _schedule_run_earliest,
    _sorted_segments,
)
from backend.scheduler.improvement import Proposal, SkippedProposal, production_windows
from backend.scheduler.jit_policy import earliest_allowed_start
from backend.scheduler.policy import anticipation_better
from backend.scheduler.priority import lot_priority_key, run_priority_key
from backend.scheduler.resources import clone_run_for_machine
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.scheduler.validation import validate_plan
from backend.types import EngineData

MAX_GROUP = 6
SOLVE_SECONDS = 0.25


class _Axis:
    """Absolute plan minutes <-> productive minutes (workdays, shift span)."""

    def __init__(self, config: FactoryConfig, holidays: set[int], first: int, last: int):
        self.open = int(config.shift_a_start)
        self.close = int(config.shift_b_end)
        self.capacity = self.close - self.open
        self.rank: dict[int, int] = {}
        rank = 0
        for day in range(first, last + 1):
            self.rank[day] = rank
            if day not in holidays:
                rank += 1
        self.holidays = holidays

    def to_productive(self, absolute: float) -> int:
        day, minute = divmod(int(absolute), 1440)
        if day not in self.rank:
            day = min(max(day, min(self.rank)), max(self.rank))
        base = self.rank[day] * self.capacity
        if day in self.holidays:
            return base
        return base + min(max(minute - self.open, 0), self.capacity)


def _with_retained_successors(group, ordered, run_map, movable, max_group):
    """A run whose zero setup relies on a member's mount must move with it."""
    members = list(group)
    for run_id in list(members):
        for successor in _retained_setup_successors(run_id, ordered, run_map):
            if successor.id in movable and successor.id not in members:
                members.append(successor.id)
    return tuple(sorted(members)) if len(members) <= max_group else None


def _group_for(target: ToolRun, movable, segments_by_run, eligible, floor_abs, max_group):
    machines = set(eligible[target.id])
    end = max(s.day_idx * 1440 + s.end_min for s in segments_by_run[target.id])
    neighbours = []
    for run_id, run_segments in segments_by_run.items():
        if run_id == target.id or run_id not in movable:
            continue
        overlap = [
            s for s in run_segments
            if (s.machine_id in machines or s.tool_id == target.tool_id)
            and s.day_idx * 1440 + s.end_min > floor_abs and s.day_idx * 1440 + s.start_min < end
        ]
        if overlap:
            neighbours.append((min(s.day_idx * 1440 + s.start_min for s in overlap), run_id))
    neighbours.sort()
    return tuple(sorted({target.id, *(run_id for _start, run_id in neighbours[: max_group - 1])}))


def local_cpsat_proposals(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    not_before_abs: int | None = None,
    max_group: int = MAX_GROUP,
    solve_seconds: float = SOLVE_SECONDS,
) -> Iterator[Proposal | SkippedProposal]:
    from ortools.sat.python import cp_model

    ordered = _sorted_segments(segments)
    run_map = _resolve_runs(ordered, lots, None)
    if not run_map:
        return
    data = _neighbourhood_calendar(ordered, run_map, data, config)
    protected = set(getattr(data, "preserved_lot_proofs", None) or {})
    movable = {rid: run for rid, run in run_map.items()
               if not any(lot.id in protected for lot in run.lots)}
    holidays = _extended_holidays(data, -20, data.n_days + 400)
    windows = production_windows(ordered)
    segments_by_run: dict[str, list[Segment]] = {}
    for segment in ordered:
        segments_by_run.setdefault(segment.run_id, []).append(segment)
    last_day = max(s.day_idx for s in ordered) + 60
    axis = _Axis(config, holidays, min(-20, min(s.day_idx for s in ordered)), last_day)
    eligible = {rid: _eligible_machines(run, data, config, ordered) for rid, run in movable.items()}
    group_of = {machine.id: machine.group for machine in data.machines}
    group_of.update(config.machine_groups)

    def floor_abs(run: ToolRun) -> int:
        release = min(max(0, earliest_allowed_start(lot, holidays)) for lot in run.lots)
        return max(release * 1440 + axis.open, int(not_before_abs or 0))

    targets = sorted(
        (run for rid, run in movable.items() if eligible[rid]
         and min(windows[lot.id][0] for lot in run.lots if lot.id in windows) > floor_abs(run)),
        key=run_priority_key,
    )
    seen: set[tuple[str, ...]] = set()
    for target in targets:
        group = _with_retained_successors(
            _group_for(target, movable, segments_by_run, eligible, floor_abs(target), max_group),
            ordered, run_map, movable, max_group,
        )
        if group is None or len(group) < 2 or group in seen or any(
            not eligible[rid] for rid in group
        ):
            continue
        seen.add(group)
        planning_checkpoint()
        plan = _solve_group(group, movable, eligible, ordered, data, config, axis,
                            floor_abs, group_of, solve_seconds, cp_model)
        if plan is None:
            continue
        member_lots = sorted((lot for rid in group for lot in movable[rid].lots),
                             key=lot_priority_key)
        before = tuple(windows.get(lot.id, (math.inf, math.inf)) for lot in member_lots)
        fixed = [s for s in ordered if s.run_id not in group]
        created: list[Segment] = []
        rebound: list[Lot] = []
        for run_id, machine_id in plan:
            placed = _schedule_run_earliest(
                movable[run_id], machine_id, [*fixed, *created], data, config,
                not_before_abs=not_before_abs,
            )
            if placed is None:
                created = []
                break
            created.extend(placed[1])
            rebound.extend(placed[0].lots)
        if not created:
            continue
        after_windows = production_windows(created)
        after = tuple(after_windows.get(lot.id, (math.inf, math.inf)) for lot in member_lots)
        if not anticipation_better(after, before):
            continue
        subject = {
            "key": "cpsat:" + "|".join(f"{rid}>{m}" for rid, m in plan),
            "kind": "local_cpsat",
            "assignments": [list(item) for item in plan],
        }
        candidate_segments = _sorted_segments([*fixed, *created])
        candidate_lots = _replace_lots(lots, rebound)
        violations = validate_plan(candidate_segments, data, config, lots=candidate_lots)
        if violations:
            yield SkippedProposal(subject, "physical", tuple(sorted(
                {str(item.get("kind", "physical")) for item in violations})))
            continue
        yield Proposal(candidate_segments, candidate_lots, subject=subject)


def _solve_group(group, movable, eligible, ordered, data, config, axis, floor_abs, group_of,
                 solve_seconds, cp_model):
    """Return [(run_id, machine)] in start order, or None."""

    model = cp_model.CpModel()
    fixed = [s for s in ordered if s.run_id not in group]
    horizon = axis.to_productive(max(s.day_idx * 1440 + s.end_min for s in ordered)) + sum(
        int(movable[rid].total_min) + 1 for rid in group) + axis.capacity * 2
    machine_intervals: dict[str, list] = {}
    tool_intervals: dict[str, list] = {}
    crew: dict[str, tuple[list, list]] = {}

    def fixed_interval(start, end, name):
        start, end = axis.to_productive(start), axis.to_productive(end)
        return model.new_fixed_size_interval_var(start, max(0, end - start), name) if end > start \
            else None

    group_tools = {movable[rid].tool_id for rid in group}
    group_machines = {m for rid in group for m in eligible[rid]}
    for index, s in enumerate(fixed):
        start, end = s.day_idx * 1440 + s.start_min, s.day_idx * 1440 + s.end_min
        if s.machine_id in group_machines:
            interval = fixed_interval(start, end, f"fm{index}")
            if interval is not None:
                machine_intervals.setdefault(s.machine_id, []).append(interval)
        if s.tool_id in group_tools:
            interval = fixed_interval(start, end, f"ft{index}")
            if interval is not None:
                tool_intervals.setdefault(s.tool_id, []).append(interval)
        if s.setup_min > 0:
            interval = fixed_interval(start, start + s.setup_min, f"fc{index}")
            if interval is not None:
                intervals, demands = crew.setdefault(group_of.get(s.machine_id, ""), ([], []))
                intervals.append(interval)
                demands.append(1)

    starts, production_starts, choices = {}, {}, {}
    for rid in group:
        run = movable[rid]
        start = model.new_int_var(axis.to_productive(floor_abs(run)), horizon, f"s_{rid}")
        options = []
        setup_terms = []
        for m in eligible[rid]:
            rebound = clone_run_for_machine(run, m, data, config)
            setup = int(math.ceil(rebound.setup_min))
            duration = int(math.ceil(rebound.setup_min + rebound.total_prod_min))
            present = model.new_bool_var(f"b_{rid}_{m}")
            end = model.new_int_var(0, horizon + duration, f"e_{rid}_{m}")
            interval = model.new_optional_interval_var(start, duration, end, present,
                                                       f"i_{rid}_{m}")
            machine_intervals.setdefault(m, []).append(interval)
            tool_intervals.setdefault(run.tool_id, []).append(interval)
            if setup > 0:
                setup_end = model.new_int_var(0, horizon + setup, f"se_{rid}_{m}")
                setup_interval = model.new_optional_interval_var(
                    start, setup, setup_end, present, f"c_{rid}_{m}")
                intervals, demands = crew.setdefault(group_of.get(m, ""), ([], []))
                intervals.append(setup_interval)
                demands.append(1)
            options.append((m, present))
            setup_terms.append(setup * present)
        model.add_exactly_one(present for _m, present in options)
        production = model.new_int_var(0, horizon * 2, f"p_{rid}")
        model.add(production == start + sum(setup_terms))
        starts[rid], production_starts[rid], choices[rid] = start, production, options
    for intervals in machine_intervals.values():
        model.add_no_overlap(intervals)
    for intervals in tool_intervals.values():
        model.add_no_overlap(intervals)
    for crew_group, (intervals, demands) in crew.items():
        capacity = int((config.setup_crews_by_group or {}).get(crew_group, config.setup_crews) or 1)
        model.add_cumulative(intervals, demands, capacity)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    values = solver_values = None
    for rid in sorted(group, key=lambda item: run_priority_key(movable[item])):
        model.minimize(production_starts[rid])
        if values is not None:
            for other, value in values.items():
                model.add_hint(starts[other], value)
        solver.parameters.max_time_in_seconds = solve_seconds
        status = solve_cpsat(solver, model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None if values is None else _order(values, choices, solver_values)
        found = solver.value(production_starts[rid])
        model.add(production_starts[rid] <= found)
        values = {other: solver.value(starts[other]) for other in group}
        solver_values = {other: next(m for m, present in choices[other]
                                     if solver.boolean_value(present)) for other in group}
        model.clear_hints()
    return _order(values, choices, solver_values)


def _order(values, choices, machines):
    return [(rid, machines[rid]) for rid in sorted(values, key=lambda item: (values[item], item))]
