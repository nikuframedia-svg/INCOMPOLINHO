"""Global material-release JIT constructor.

The legacy dispatcher reserves each machine independently and repairs shared
resources afterwards.  That architecture can push work beyond the visible
horizon and silently lose lots.  This module builds one CP-SAT model for every
run, machine, tool, setup crew and operator group, then materialises the chosen
solution into the existing Segment contract.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.config.shifts import (
    clock_to_productive_offset,
    merge_clock_intervals,
    ordered_shifts,
)
from backend.config.types import JIT_MAX_ANTICIPATION_WORKDAYS, FactoryConfig
from backend.planning_control import (
    current_planning_control,
    planning_checkpoint,
    remaining_time,
    solve_cpsat,
)
from backend.scheduler.jit_policy import (
    calendar_holidays,
    customer_factory_due_day,
    earliest_allowed_start,
    expedition_day,
    material_reference_day,
    production_due_day,
    subtract_workdays,
)
from backend.scheduler.operators import (
    effective_operator_capacity,
    operator_free_windows,
)
from backend.scheduler.priority import (
    lot_delivery_qty,
    lot_priority_key,
    run_priority_key,
)
from backend.scheduler.resources import clone_run_for_machine
from backend.scheduler.setup_identity import SetupIdentity, lot_setup_identity, retained_setup_at
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.types import EngineData

try:
    from ortools.sat.python import cp_model

    HAS_ORTOOLS = True
except ImportError:  # pragma: no cover - production dependency, defensive fallback
    cp_model = None
    HAS_ORTOOLS = False


@dataclass(slots=True)
class GlobalJITResult:
    segments: list[Segment]
    lots: list[Lot]
    machine_runs: dict[str, list[ToolRun]]
    run_gates: dict[str, float]
    solver_status: str
    feasibility: dict[str, Any]
    warnings: list[str]
    candidate_found: bool = True


@dataclass(slots=True)
class _Option:
    run: ToolRun
    machine_id: str
    presence: Any
    start: Any
    end: Any
    duration: int
    setup: int
    lot_offsets: list[tuple[Lot, int, int]]


@dataclass(slots=True)
class _Artifacts:
    model: Any
    config: FactoryConfig
    options_by_run: dict[str, list[_Option]]
    origin_abs: int
    horizon_abs: int
    strict: bool
    day_cap: int
    shift_start: int
    working_days: list[int]
    day_to_slot: dict[int, int]
    objectives: list[Any]


def solve_global_jit(
    runs: list[ToolRun],
    data: EngineData,
    config: FactoryConfig,
    baseline_segments: list[Segment] | None = None,
    time_limit_s: float | None = None,
    *,
    horizon_end_day: int | None = None,
) -> GlobalJITResult | None:
    """Solve the industrial best-effort problem and return a complete candidate.

    A strict delivery model is attempted first.  If it is proven infeasible or
    times out without a solution, a complete diagnostic model allows lateness.
    Material release is a hard floor in both models.  Once a lot is released,
    the solver pulls it as early as physical resources and higher-priority
    requirements allow; it does not use the five-day window as a reason to
    delay production.
    """

    planning_checkpoint()
    if not HAS_ORTOOLS or not runs:
        return None

    parent_deadline = getattr(config, "_optimization_deadline", None)
    limit = _effective_time_limit(
        runs,
        time_limit_s or getattr(config, "global_jit_time_limit_s", 8.0),
        # A parent optimizer already allocates the available wall-clock budget
        # between the baseline and shadow candidates. Adaptive standalone
        # sizing must not silently override that allocation.
        allow_adaptive=parent_deadline is None and current_planning_control() is None,
    )
    limit = remaining_time(limit)
    deadline = time.monotonic() + limit
    report_reserve = min(0.5, max(0.01, limit * 0.10))
    solve_deadline = deadline - report_reserve
    priority_reserve = min(12.0, max(4.0, limit * 0.34)) if len(runs) >= 50 else 0.0
    constructor_deadline = solve_deadline - priority_reserve
    strict_artifacts = _build_model(
        runs, data, config, strict=True, horizon_end_day=horizon_end_day,
    )
    planning_checkpoint()
    strict_solver, strict_status = _solve(
        strict_artifacts,
        min(constructor_deadline, time.monotonic() + min(limit * 0.25, 2.0)),
        baseline_segments,
    )
    strict_name = _status_name(strict_status)

    chosen_artifacts = strict_artifacts
    chosen_solver = strict_solver
    chosen_status = strict_status
    solver_status = (
        "strict_feasible"
        if strict_status == cp_model.OPTIMAL
        else "timeout_with_candidate"
        if strict_status == cp_model.FEASIBLE
        else "no_candidate"
    )
    warnings: list[str] = []

    if (
        strict_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        and time.monotonic() < constructor_deadline
    ):
        diagnostic_artifacts = _build_model(
            runs, data, config, strict=False, horizon_end_day=horizon_end_day,
        )
        diagnostic_solver, diagnostic_status = _solve(
            diagnostic_artifacts,
            constructor_deadline,
            baseline_segments,
        )
        if diagnostic_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            chosen_artifacts = diagnostic_artifacts
            chosen_solver = diagnostic_solver
            chosen_status = diagnostic_status
            solver_status = (
                "strict_infeasible_best_effort"
                if strict_status == cp_model.INFEASIBLE
                else "timeout_with_candidate"
            )
        if strict_status == cp_model.INFEASIBLE:
            warnings.append(
                "JIT global: as entregas nao cabem nas condicoes atuais; "
                "foi produzido o melhor plano completo encontrado"
            )
        else:
            warnings.append(
                "JIT global: verificacao de entregas inconclusiva no tempo disponivel; "
                "o resultado conserva o estado da pesquisa"
            )

    if chosen_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        planning_checkpoint()
        fallback = _calendar_preemptive_fallback(
            runs, data, config, horizon_end_day=horizon_end_day,
        )
        planning_checkpoint()
        if fallback is not None:
            segments, lots, machine_runs, run_gates, calendar_preemptions = fallback
            strict_feasible = _strict_delivery_feasible(segments, lots, data)
            solver_status = (
                "strict_feasible"
                if strict_feasible
                else "strict_infeasible_best_effort"
                if strict_status == cp_model.INFEASIBLE
                else "timeout_with_candidate"
            )
            feasibility = _build_feasibility_report(
                runs,
                data,
                config,
                solver_status=solver_status,
                strict_status=strict_name,
                deadline=deadline,
            )
            feasibility.update(
                strict_feasible=strict_feasible,
                calendar_preemptions=calendar_preemptions,
                calendar_preemptive_fallback=True,
            )
            return GlobalJITResult(
                segments=segments,
                lots=lots,
                machine_runs=machine_runs,
                run_gates=run_gates,
                solver_status=solver_status,
                feasibility=feasibility,
                warnings=[
                    *warnings,
                    "Calendario: candidato completo reconstruido com producao "
                    "nos intervalos legais de recursos",
                ],
            )
        feasibility = _build_feasibility_report(
            runs,
            data,
            config,
            solver_status=solver_status,
            strict_status=strict_name,
            deadline=deadline,
        )
        return GlobalJITResult(
            segments=[],
            lots=[lot for run in runs for lot in run.lots],
            machine_runs={},
            run_gates={},
            solver_status=solver_status,
            feasibility=feasibility,
            warnings=warnings + ["JIT global: nenhum candidato executavel encontrado"],
            candidate_found=False,
        )

    chosen_solver, unresolved_priority = _refine_priority_inversions(
        chosen_artifacts,
        chosen_solver,
        solve_deadline,
        known_holidays=_extended_holidays(data, -20, data.n_days + 100),
    )
    if unresolved_priority:
        warnings.append(
            f"Prioridade operacional: {unresolved_priority} inversao(oes) exigem revisao manual"
        )

    machine_runs, selected = _extract_selection(chosen_artifacts, chosen_solver)
    segments = _materialise(
        selected,
        chosen_solver,
        chosen_artifacts.origin_abs,
        chosen_artifacts.working_days,
        config,
    )
    lots = [
        lot for machine in sorted(machine_runs) for run in machine_runs[machine] for lot in run.lots
    ]
    segments, calendar_preemptions = _preempt_exact_calendar_gaps(
        segments,
        lots,
        data,
        config,
    )
    if calendar_preemptions:
        warnings.append(
            "Calendario: producao repartida em torno de "
            f"{calendar_preemptions} indisponibilidade(s) parcial(is)"
        )
        if _strict_delivery_feasible(segments, lots, data):
            solver_status = "strict_feasible"
            warnings = [
                warning
                for warning in warnings
                if not warning.startswith("JIT global: as entregas nao cabem")
            ]
    run_gates = {
        option.run.id: _materialised_run_gate(
            option,
            segments,
            chosen_solver,
            chosen_artifacts,
            config,
        )
        for option in selected
    }
    feasibility = _build_feasibility_report(
        runs,
        data,
        config,
        solver_status=solver_status,
        strict_status=strict_name,
        deadline=deadline,
    )
    if strict_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        feasibility["strict_feasible"] = True
    if calendar_preemptions:
        feasibility["calendar_preemptions"] = calendar_preemptions
    return GlobalJITResult(
        segments=segments,
        lots=lots,
        machine_runs=machine_runs,
        run_gates=run_gates,
        solver_status=solver_status,
        feasibility=feasibility,
        warnings=warnings,
    )


def _effective_time_limit(
    runs: list[ToolRun],
    requested_limit_s: float,
    *,
    allow_adaptive: bool = True,
) -> float:
    """Keep large ISOPs on the complete global-constructor path.

    A sub-second budget is useful for small interactive fixtures, but on a
    real ISOP it can expire before the diagnostic model finds its first
    complete candidate.  The legacy fallback is intentionally lightweight and
    is not a substitute for a globally resource-feasible plan.  Give only
    large run sets enough time to return a complete candidate; small requests
    retain their configured responsive budget.
    """

    requested = max(0.05, float(requested_limit_s))
    if allow_adaptive and len(runs) >= 50:
        # Real ISOPs need materially more search than tiny fixtures.  Scale the
        # budget with the number of independently sequenced runs, capped so an
        # interactive recalculation remains bounded. The second-stage priority
        # refinement needs its own search budget after delivery optimisation.
        adaptive = min(36.0, max(8.0, len(runs) / 7.5))
        return max(adaptive, requested)
    return requested


def _build_model(
    runs: list[ToolRun],
    data: EngineData,
    config: FactoryConfig,
    *,
    strict: bool,
    horizon_end_day: int | None = None,
) -> _Artifacts:
    day_cap = config.day_capacity_min
    total_prod = sum(run.total_min for run in runs)
    load_by_primary_machine: dict[str, float] = {}
    for run in runs:
        load_by_primary_machine[run.machine_id] = (
            load_by_primary_machine.get(run.machine_id, 0.0) + run.total_min
        )
    bottleneck_workdays = math.ceil(
        max(load_by_primary_machine.values(), default=total_prod) / max(1, day_cap)
    )
    # A diagnostic plan must have enough room to schedule every lot even when
    # one primary machine/tool carries far more than the factory average.
    diagnostic_extra = max(
        15,
        bottleneck_workdays + len(set(data.holidays)) + 10,
    )
    known_holidays = _extended_holidays(
        data,
        -20,
        data.n_days + diagnostic_extra + 10,
    )
    max_day = (
        max(
            max(expedition_day(lot), production_due_day(lot, known_holidays))
            for run in runs
            for lot in run.lots
        )
        + 1
        if strict
        else data.n_days + diagnostic_extra
    )
    if horizon_end_day is not None:
        max_day = min(max_day, horizon_end_day)
    # Day 0 is reality.  Negative auto-buffer days are no longer schedulable.
    from backend.transform.calendars import calendar_window

    data = calendar_window(data, config, max_day)
    first_day = 0
    working_days = [day for day in range(first_day, max_day + 1) if day not in known_holidays]
    day_to_slot = {day: slot for slot, day in enumerate(working_days)}
    origin_abs = 0
    horizon_abs = len(working_days) * day_cap
    horizon = max(1, horizon_abs)

    model = cp_model.CpModel()
    options_by_run: dict[str, list[_Option]] = {}
    machine_intervals: dict[str, list[Any]] = {machine.id: [] for machine in data.machines}
    tool_intervals: dict[str, list[Any]] = {}
    crew_intervals: dict[str, list[Any]] = {}
    operator_intervals: dict[str, list[Any]] = {}
    operator_demands: dict[str, list[int]] = {}
    release_lag_terms: list[tuple[Lot, Any, int]] = []
    late_vars: list[Any] = []
    late_bools: list[Any] = []
    late_entries: list[tuple[Lot, Any]] = []
    late_qty_terms: list[Any] = []
    customer_late_vars: list[Any] = []
    customer_late_bools: list[Any] = []
    customer_late_entries: list[tuple[Lot, Any]] = []
    customer_late_qty_terms: list[Any] = []
    customer_due_differs = False
    ops_by_id = {op.id: op for op in data.ops}
    machine_group = {
        machine.id: config.machine_groups.get(machine.id, machine.group)
        for machine in data.machines
    }
    active_machines = {
        machine_id
        for machine_id in machine_intervals
        if config.machines.get(machine_id) is None or config.machines[machine_id].active
    }

    for run_idx, original in enumerate(sorted(runs, key=run_priority_key)):
        planning_checkpoint()
        candidates = [original.machine_id]
        if original.alt_machine_id and original.alt_machine_id in active_machines:
            candidates.append(original.alt_machine_id)
        candidates = list(
            dict.fromkeys(machine for machine in candidates if machine in active_machines)
        )
        options: list[_Option] = []
        for opt_idx, machine_id in enumerate(candidates):
            planning_checkpoint()
            run = clone_run_for_machine(original, machine_id, data, config)
            setup = max(0, math.ceil(run.setup_min))
            lot_offsets: list[tuple[Lot, int, int]] = []
            offset = setup
            for lot in sorted(run.lots, key=lot_priority_key):
                duration = max(1, math.ceil(lot.prod_min))
                lot_offsets.append((lot, offset, duration))
                offset += duration
            duration = max(1, offset)
            presence = model.new_bool_var(f"run_{run_idx}_{opt_idx}_on_{machine_id}")
            minimum_productive_run = 1 if setup and lot_offsets else 0
            allowed = _allowed_setup_starts(
                working_days,
                horizon_abs - duration,
                setup,
                day_cap,
                [shift.duration_min for shift in ordered_shifts(config)],
                set(data.machine_blocked_days.get(machine_id, set())),
                minimum_productive_run=minimum_productive_run,
            )
            if not allowed:
                model.add(presence == 0)
                start = model.new_int_var(0, 0, f"start_{run_idx}_{opt_idx}")
            else:
                start = model.new_int_var_from_domain(
                    cp_model.Domain.from_intervals(allowed),
                    f"start_{run_idx}_{opt_idx}",
                )
            end = model.new_int_var(0, horizon, f"end_{run_idx}_{opt_idx}")
            model.add(end == start + duration)
            interval = model.new_optional_interval_var(
                start,
                duration,
                end,
                presence,
                f"iv_{run_idx}_{opt_idx}",
            )
            machine_intervals[machine_id].append(interval)
            tool_intervals.setdefault(run.tool_id, []).append(interval)

            if setup:
                setup_end = model.new_int_var(0, horizon, f"setup_end_{run_idx}_{opt_idx}")
                model.add(setup_end == start + setup)
                group = machine_group.get(machine_id, "Grandes")
                crew_intervals.setdefault(group, []).append(
                    model.new_optional_interval_var(
                        start,
                        setup,
                        setup_end,
                        presence,
                        f"setup_{run_idx}_{opt_idx}",
                    )
                )

            # Setup belongs to the first produced lot. Its material release is
            # therefore the setup floor; later lots keep their individual
            # production floors while the mounted tool remains available.
            run_floor_abs = (
                _start_coord(
                    earliest_allowed_start(lot_offsets[0][0], known_holidays),
                    working_days,
                    day_cap,
                )
                if lot_offsets
                else 0
            )
            model.add(start >= run_floor_abs).only_enforce_if(presence)

            group = machine_group.get(machine_id, "Grandes")
            for lot_idx, (lot, lot_offset, lot_duration) in enumerate(lot_offsets):
                prod_start = model.new_int_var(0, horizon, f"prod_s_{run_idx}_{opt_idx}_{lot_idx}")
                prod_end = model.new_int_var(0, horizon, f"prod_e_{run_idx}_{opt_idx}_{lot_idx}")
                model.add(prod_start == start + lot_offset)
                model.add(prod_end == prod_start + lot_duration)
                prod_iv = model.new_optional_interval_var(
                    prod_start,
                    lot_duration,
                    prod_end,
                    presence,
                    f"prod_{run_idx}_{opt_idx}_{lot_idx}",
                )
                operator_intervals.setdefault(group, []).append(prod_iv)
                operator_demands.setdefault(group, []).append(_operator_demand(lot, ops_by_id))

                floor_abs = _start_coord(
                    earliest_allowed_start(lot, known_holidays),
                    working_days,
                    day_cap,
                )
                # The five workdays model material availability.  Production
                # cannot begin before this release floor, even if a tighter
                # delivery target would otherwise tempt the optimiser to make
                # an unexplainable early exception.
                model.add(prod_start >= floor_abs).only_enforce_if(presence)
                release_lag = model.new_int_var(
                    0,
                    horizon,
                    f"release_lag_{run_idx}_{opt_idx}_{lot_idx}",
                )
                model.add(release_lag == prod_start - floor_abs).only_enforce_if(presence)
                model.add(release_lag == 0).only_enforce_if(presence.negated())
                release_lag_terms.append((lot, release_lag, lot_duration))
                reserve = max(0, min(5, int(config.robustness_reserve_workdays)))
                # Manufacturing must finish by the controllable boundary:
                # customer delivery for an internal output, supplier dispatch
                # for a subcontracted output. Customer OTD remains a separate
                # downstream KPI that includes the external lead time.
                delivery_due_day = subtract_workdays(
                    production_due_day(lot, known_holidays),
                    reserve,
                    known_holidays,
                )
                due_abs = _due_end_coord(delivery_due_day, working_days, day_cap)
                if strict:
                    model.add(prod_end <= due_abs).only_enforce_if(presence)
                else:
                    late = model.new_int_var(0, horizon, f"late_{run_idx}_{opt_idx}_{lot_idx}")
                    model.add(late >= prod_end - due_abs).only_enforce_if(presence)
                    model.add(late == 0).only_enforce_if(presence.negated())
                    late_vars.append(late)
                    late_bool = model.new_bool_var(f"late_order_{run_idx}_{opt_idx}_{lot_idx}")
                    model.add(late == 0).only_enforce_if(late_bool.negated())
                    model.add(late >= 1).only_enforce_if(late_bool)
                    model.add_implication(late_bool, presence)
                    late_bools.append(late_bool)
                    late_entries.append((lot, late_bool))
                    late_qty_terms.append(late_bool * max(1, lot_delivery_qty(lot)))

                    customer_due_abs = _due_end_coord(
                        customer_factory_due_day(lot, known_holidays),
                        working_days,
                        day_cap,
                    )
                    if customer_due_abs == due_abs:
                        customer_late = late
                        customer_late_bool = late_bool
                    else:
                        customer_due_differs = True
                        customer_late = model.new_int_var(
                            0,
                            horizon,
                            f"customer_late_{run_idx}_{opt_idx}_{lot_idx}",
                        )
                        model.add(customer_late >= prod_end - customer_due_abs).only_enforce_if(
                            presence
                        )
                        model.add(customer_late == 0).only_enforce_if(presence.negated())
                        customer_late_bool = model.new_bool_var(
                            f"customer_late_order_{run_idx}_{opt_idx}_{lot_idx}"
                        )
                        model.add(customer_late == 0).only_enforce_if(customer_late_bool.negated())
                        model.add(customer_late >= 1).only_enforce_if(customer_late_bool)
                        model.add_implication(customer_late_bool, presence)
                    customer_late_vars.append(customer_late)
                    customer_late_bools.append(customer_late_bool)
                    customer_late_entries.append((lot, customer_late_bool))
                    customer_late_qty_terms.append(
                        customer_late_bool * max(1, lot_delivery_qty(lot))
                    )

            options.append(
                _Option(
                    run=run,
                    machine_id=machine_id,
                    presence=presence,
                    start=start,
                    end=end,
                    duration=duration,
                    setup=setup,
                    lot_offsets=lot_offsets,
                )
            )
        model.add_exactly_one(option.presence for option in options)
        options_by_run[original.id] = options

    _add_released_tool_priority_constraints(
        model,
        options_by_run,
        data,
        known_holidays,
    )

    _apply_plan_anchors(
        model,
        options_by_run,
        data,
        config,
        working_days,
        day_cap,
    )

    for machine_id, intervals in machine_intervals.items():
        planning_checkpoint()
        blocked_days = set(data.machine_blocked_days.get(machine_id, set()))
        for slot, day in enumerate(working_days):
            if day not in blocked_days:
                continue
            start = slot * day_cap
            if 0 <= start and start + day_cap <= horizon:
                intervals.append(
                    model.new_interval_var(
                        start,
                        day_cap,
                        start + day_cap,
                        f"blocked_machine_{machine_id}_{day}",
                    )
                )
        model.add_no_overlap(intervals)
    for tool_id, intervals in tool_intervals.items():
        planning_checkpoint()
        blocked_days = set(data.tool_blocked_days.get(tool_id, set()))
        for slot, day in enumerate(working_days):
            if day not in blocked_days:
                continue
            start = slot * day_cap
            if 0 <= start and start + day_cap <= horizon:
                intervals.append(
                    model.new_interval_var(
                        start,
                        day_cap,
                        start + day_cap,
                        f"blocked_tool_{tool_id}_{day}",
                    )
                )
        model.add_no_overlap(intervals)
    _add_exact_resource_blocks(
        model,
        machine_intervals,
        data.machine_blocked_intervals,
        data.machine_blocked_days,
        working_days,
        day_cap,
        config,
        horizon,
        prefix="machine",
    )
    _add_exact_resource_blocks(
        model,
        tool_intervals,
        data.tool_blocked_intervals,
        data.tool_blocked_days,
        working_days,
        day_cap,
        config,
        horizon,
        prefix="tool",
    )
    # Exact blocks were appended after the first no-overlap calls above.
    for intervals in machine_intervals.values():
        model.add_no_overlap(intervals)
    for intervals in tool_intervals.values():
        model.add_no_overlap(intervals)
    for group, intervals in crew_intervals.items():
        for block in data.setup_crew_reservations:
            if block["group"] == group:
                fixed = _fixed_block_interval(
                    model, block, working_days, day_cap, config, horizon,
                    f"frozen_crew_{block['id']}",
                )
                if fixed is not None:
                    intervals.append(fixed)
        model.add_cumulative(
            intervals,
            [1] * len(intervals),
            max(1, int(config.setup_crews_by_group.get(group, 1))),
        )

    # Operator capacity is a physical cumulative resource.  Fixed intervals
    # consume the unavailable portion of each shift, allowing daily absences.
    for group, intervals in operator_intervals.items():
        planning_checkpoint()
        demands = operator_demands[group]
        max_cap = max(
            [config.operators.get((group, shift.id), 0) for shift in ordered_shifts(config)] or [0]
        )
        for slot, day in enumerate(working_days):
            shift_offset = 0
            for shift in ordered_shifts(config):
                shift_duration = shift.duration_min
                effective = effective_operator_capacity(data, config, day, group, shift.id)
                unavailable = max(0, max_cap - effective)
                if unavailable:
                    start = slot * day_cap + shift_offset
                    end = start + shift_duration
                    if start >= 0 and end <= horizon:
                        fixed = model.new_interval_var(
                            start,
                            shift_duration,
                            end,
                            f"op_cap_{group}_{day}_{shift.id}",
                        )
                        intervals.append(fixed)
                        demands.append(unavailable)
                shift_offset += shift_duration
        for block in data.operator_blocked_intervals:
            if str(block.get("group", "")) != group:
                continue
            fixed = _fixed_block_interval(
                model,
                block,
                working_days,
                day_cap,
                config,
                horizon,
                f"operator_{group}_{block.get('id', '')}",
            )
            if fixed is not None:
                intervals.append(fixed)
                demands.append(max(0, int(block.get("count", 1))))
        model.add_cumulative(intervals, demands, max_cap)

    # Rank every lot once using the business priority key.  The previous
    # quadratic weight ignored processing duration, so weighted-shortest-job
    # behaviour could put a short d10 order before a longer d8 order.  A
    # duration-scaled rank makes an adjacent exchange improve the objective if
    # and only if the more urgent released lot goes first.  The rank is global
    # because alternative-machine assignments must remain comparable.
    unique_lots = {lot.id: lot for lot, _release_lag, _duration in release_lag_terms}
    ordered_lots = sorted(unique_lots.values(), key=lot_priority_key)
    priority_rank = {lot.id: len(ordered_lots) - index for index, lot in enumerate(ordered_lots)}
    ordered_customer_lots = sorted(
        unique_lots.values(),
        key=lambda lot: (
            customer_factory_due_day(lot, known_holidays),
            *lot_priority_key(lot)[1:],
        ),
    )
    customer_priority_rank = {
        lot.id: len(ordered_customer_lots) - index
        for index, lot in enumerate(ordered_customer_lots)
    }

    def _release_priority_weight(lot: Lot, duration: int = 1) -> int:
        return max(1, priority_rank.get(lot.id, 1)) * max(1, int(duration))

    release_total = sum(
        release_lag * _release_priority_weight(lot, duration)
        for lot, release_lag, duration in release_lag_terms
    )
    if strict:
        objectives = [release_total]
    else:
        max_late = model.new_int_var(0, horizon, "max_lateness")
        model.add_max_equality(max_late, late_vars)
        late_count = sum(late_bools)
        explicit_priority_late_count = sum(
            late_bool * max(0, int(lot.planning_priority or 0)) for lot, late_bool in late_entries
        )
        priority_late_count = sum(
            late_bool * _release_priority_weight(lot) for lot, late_bool in late_entries
        )
        late_qty = sum(late_qty_terms)
        objectives = []
        if customer_due_differs:
            customer_max_late = model.new_int_var(0, horizon, "customer_max_lateness")
            model.add_max_equality(customer_max_late, customer_late_vars)
            customer_explicit_priority_late_count = sum(
                late_bool * max(0, int(lot.planning_priority or 0))
                for lot, late_bool in customer_late_entries
            )
            customer_priority_late_count = sum(
                late_bool
                * max(1, customer_priority_rank.get(lot.id, 1))
                * max(1, int(lot.prod_min))
                for lot, late_bool in customer_late_entries
            )
            if any(int(lot.planning_priority or 0) > 0 for lot, _late in customer_late_entries):
                objectives.append(customer_explicit_priority_late_count)
            objectives.extend(
                [
                    sum(customer_late_bools),
                    customer_priority_late_count,
                    sum(customer_late_qty_terms),
                    customer_max_late,
                    sum(customer_late_vars),
                ]
            )
        # A planner can mark a reference as a customer priority.  That signal
        # must be resolved before aggregate OTD; otherwise two small, ordinary
        # references can displace one explicitly critical order.  With no
        # configured priority this stage is omitted and OTD count remains the
        # primary best-effort objective.
        if any(int(lot.planning_priority or 0) > 0 for lot, _late in late_entries):
            objectives.append(explicit_priority_late_count)
        objectives.extend(
            [
                late_count,
                priority_late_count,
                late_qty,
                max_late,
                sum(late_vars),
                release_total,
            ]
        )

    return _Artifacts(
        model=model,
        config=config,
        options_by_run=options_by_run,
        origin_abs=origin_abs,
        horizon_abs=horizon_abs,
        strict=strict,
        day_cap=day_cap,
        shift_start=config.shift_a_start,
        working_days=working_days,
        day_to_slot=day_to_slot,
        objectives=objectives,
    )


def _add_released_tool_priority_constraints(
    model: Any,
    options_by_run: dict[str, list[_Option]],
    data: EngineData,
    known_holidays: set[int],
) -> None:
    """Keep a released physical tool in commercial priority order.

    Aggregate OTD can otherwise sacrifice one already-late order indefinitely
    to keep several later orders on time. A tool is unary, so when the more
    urgent run is released no useful capacity is gained by letting a later run
    reserve that tool first. Anchored shop-floor reality remains immutable.
    """

    anchored_lots = {str(anchor.lot_id) for anchor in data.plan_anchors}
    by_tool: dict[str, list[ToolRun]] = {}
    for options in options_by_run.values():
        if not options:
            continue
        run = options[0].run
        if any(lot.id in anchored_lots for lot in run.lots):
            continue
        by_tool.setdefault(run.tool_id, []).append(run)

    for runs in by_tool.values():
        ordered = sorted(runs, key=run_priority_key)
        release = {
            run.id: min(
                (earliest_allowed_start(lot, known_holidays) for lot in run.lots),
                default=0,
            )
            for run in ordered
        }
        # Chain consecutive due-date classes. Runs inside one class remain
        # free so the solver can minimise the number of late orders; every run
        # in an earlier class must finish before the next released class. This
        # avoids the former quadratic all-pairs model without imposing an
        # arbitrary order on equal customer commitments.
        classes: list[list[ToolRun]] = []
        for run in ordered:
            if not classes or run_priority_key(classes[-1][0])[:2] != run_priority_key(run)[:2]:
                classes.append([])
            classes[-1].append(run)
        for urgent_class, later_class in zip(classes, classes[1:]):
            for urgent in urgent_class:
                for later in later_class:
                    if release[urgent.id] > release[later.id]:
                        continue
                    for urgent_option in options_by_run[urgent.id]:
                        for later_option in options_by_run[later.id]:
                            model.add(
                                urgent_option.end <= later_option.start
                            ).only_enforce_if(
                                [urgent_option.presence, later_option.presence]
                            )


def _solve(
    artifacts: _Artifacts,
    deadline: float,
    baseline_segments: list[Segment] | None,
) -> tuple[Any, int]:
    _add_hints(artifacts, baseline_segments or [])
    objectives = artifacts.objectives or [0]
    chosen_solver = None
    chosen_status = cp_model.UNKNOWN
    solver = cp_model.CpSolver()
    status = cp_model.UNKNOWN
    # Reserve time for every lexicographic stage.  Previously the first stage
    # could consume the complete deadline and the solver would return without
    # ever considering rupture priority or ASAP.  Earlier stages still receive
    # more time, while ``<= incumbent`` keeps them non-regressing during all
    # later stages.
    if len(objectives) == 1:
        stage_weights = [1]
    else:
        # Delivery stages remain dominant; weighted ASAP is the final stage.
        stage_weights = [4] * (len(objectives) - 1) + [2]
    for index, objective in enumerate(objectives):
        planning_checkpoint()
        remaining = deadline - time.monotonic()
        if remaining <= 0.01:
            break
        artifacts.model.minimize(objective)
        solver = cp_model.CpSolver()
        remaining_weight = max(1, sum(stage_weights[index:]))
        stage_budget = remaining * stage_weights[index] / remaining_weight
        solver.parameters.max_time_in_seconds = max(
            0.001,
            min(remaining - 0.005, stage_budget),
        )
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 42
        status = solve_cpsat(solver, artifacts.model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break
        chosen_solver = solver
        chosen_status = status
        # Never allow a later priority to worsen an earlier one. With a
        # time-limited FEASIBLE phase this also permits a later solve to improve
        # the earlier value, because the constraint is <= rather than ==.
        if index < len(objectives) - 1:
            artifacts.model.add(objective <= int(round(solver.value(objective))))
    if chosen_solver is None:
        return solver, status
    return chosen_solver, chosen_status


def _refine_priority_inversions(
    artifacts: _Artifacts,
    incumbent: Any,
    deadline: float,
    *,
    known_holidays: set[int],
) -> tuple[Any, int]:
    """Repair incumbent order without regressing established delivery goals.

    ``_solve`` has already bounded every delivery objective. This refinement
    fixes the chosen machine assignment and creates order choices for the
    inversions observed in each incumbent. Repeating discovery after a solve
    catches new inversions exposed by earlier corrections. Unlike hard global
    precedences, the soft choices can retain the few inversions genuinely
    required by resource and delivery constraints. Weighted ASAP resolves the
    remaining free time.
    """

    current = incumbent
    # The delivery solve has already selected a physically valid machine for
    # every run.  Keep those assignments fixed while repairing order: allowing
    # the refinement to reopen every alternative machine made this small
    # sequencing problem as hard as the original APS solve and frequently
    # exhausted its reserved time without changing the incumbent.
    for options in artifacts.options_by_run.values():
        selected = next(
            (option for option in options if incumbent.value(option.presence)),
            None,
        )
        if selected is None:
            continue
        for option in options:
            artifacts.model.add(option.presence == int(option is selected))

    inversion_choices: list[Any] = []
    represented_pairs: set[tuple[str, str]] = set()
    best_current = current
    best_unresolved = len(
        _priority_inversion_pairs(
            artifacts,
            current,
            known_holidays=known_holidays,
        )
    )
    # Correcting one incumbent order can expose a different inversion elsewhere
    # on the same machine or tool. Re-discover pairs after each accepted solve
    # instead of treating the first incumbent as the complete problem.
    max_refinement_rounds = 4
    for refinement_round in range(max_refinement_rounds):
        planning_checkpoint()
        pairs = _priority_inversion_pairs(
            artifacts,
            current,
            known_holidays=known_holidays,
        )
        if not pairs:
            best_current = current
            best_unresolved = 0
            break
        new_pairs = [
            pair for pair in pairs if (pair[0].run.id, pair[1].run.id) not in represented_pairs
        ]
        # Every represented pair was already optimized in the preceding
        # solve. Re-solving the same objective from scratch only consumes the
        # budget reserved for the final ASAP tie-breaker.
        if not new_pairs and refinement_round > 0:
            break
        for urgent, later in new_pairs:
            pair_key = (urgent.run.id, later.run.id)
            represented_pairs.add(pair_key)
            urgent_first = artifacts.model.new_bool_var(
                f"repair_priority_{len(represented_pairs)}_{urgent.run.id}_{later.run.id}"
            )
            artifacts.model.add(urgent.end <= later.start).only_enforce_if(urgent_first)
            artifacts.model.add(later.end <= urgent.start).only_enforce_if(urgent_first.negated())
            inversion_choices.append(urgent_first.negated())

        remaining = deadline - time.monotonic() - 0.01
        if remaining <= 0.05:
            break
        # The former ``remaining / (rounds_left + 1)`` allocation gave the
        # only useful inversion solve roughly one second on a real ISOP, then
        # exited because all incumbent pairs were already represented. Spend
        # most of the available budget on the business ordering itself while
        # retaining a bounded tail for weighted ASAP.
        rounds_left = max_refinement_rounds - refinement_round
        reserve_for_asap = min(2.0, max(0.05, remaining * 0.20))
        priority_budget = max(
            0.001,
            (remaining - reserve_for_asap) / max(1, min(2, rounds_left)),
        )
        artifacts.model.minimize(sum(inversion_choices))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = priority_budget
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 42
        status = solve_cpsat(solver, artifacts.model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break
        current = solver
        best_inversions = int(round(solver.value(sum(inversion_choices))))
        artifacts.model.add(sum(inversion_choices) <= best_inversions)
        unresolved = len(
            _priority_inversion_pairs(
                artifacts,
                current,
                known_holidays=known_holidays,
            )
        )
        if unresolved < best_unresolved:
            best_current = current
            best_unresolved = unresolved

    if not inversion_choices:
        return current, 0

    if deadline - time.monotonic() > 0.05:
        artifacts.model.minimize(artifacts.objectives[-1])
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(
            0.001,
            deadline - time.monotonic() - 0.01,
        )
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 42
        status = solve_cpsat(solver, artifacts.model)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            current = solver
            unresolved = len(
                _priority_inversion_pairs(
                    artifacts,
                    current,
                    known_holidays=known_holidays,
                )
            )
            if unresolved <= best_unresolved:
                best_current = current
                best_unresolved = unresolved

    return best_current, best_unresolved


def _priority_inversion_pairs(
    artifacts: _Artifacts,
    solver: Any,
    *,
    known_holidays: set[int],
) -> list[tuple[_Option, _Option]]:
    """Return incumbent resource orders that contradict business urgency."""

    selected: list[_Option] = []
    for options in artifacts.options_by_run.values():
        chosen = next(
            (option for option in options if solver.value(option.presence)),
            None,
        )
        if chosen is not None:
            selected.append(chosen)

    timelines: list[list[_Option]] = []
    by_machine: dict[str, list[_Option]] = {}
    by_tool: dict[str, list[_Option]] = {}
    for option in selected:
        by_machine.setdefault(option.machine_id, []).append(option)
        by_tool.setdefault(option.run.tool_id, []).append(option)
    timelines.extend(by_machine.values())
    timelines.extend(values for values in by_tool.values() if len(values) > 1)

    pairs: dict[tuple[str, str], tuple[_Option, _Option]] = {}
    for timeline in timelines:
        planning_checkpoint()
        ordered = sorted(timeline, key=lambda option: solver.value(option.start))
        for earlier_index, earlier in enumerate(ordered):
            for later in ordered[earlier_index + 1 :]:
                earlier_priority = run_priority_key(earlier.run)[:2]
                later_priority = run_priority_key(later.run)[:2]
                if later_priority >= earlier_priority:
                    continue
                urgent_floor = min(
                    earliest_allowed_start(lot, known_holidays) for lot in later.run.lots
                )
                blocker_floor = min(
                    earliest_allowed_start(lot, known_holidays) for lot in earlier.run.lots
                )
                if urgent_floor > blocker_floor:
                    continue
                pairs[(later.run.id, earlier.run.id)] = (later, earlier)
    return list(pairs.values())


def _clock_to_coord(
    day_idx: int,
    minute: int,
    working_days: list[int],
    day_cap: int,
    config: FactoryConfig,
) -> int | None:
    try:
        slot = working_days.index(day_idx)
    except ValueError:
        return None
    offset = max(0, min(day_cap, clock_to_productive_offset(config, minute)))
    return slot * day_cap + offset


def _fixed_block_interval(
    model: Any,
    block: dict,
    working_days: list[int],
    day_cap: int,
    config: FactoryConfig,
    horizon: int,
    name: str,
) -> Any | None:
    day_idx = int(block.get("start_day", -1))
    shifts = ordered_shifts(config)
    # The integer model must cover the whole physical reservation, not release
    # a crew early when a protected setup ends between clock minutes.
    start_min = max(int(shifts[0].start_min), math.floor(block.get("start_min", 0)))
    end_min = min(int(shifts[-1].end_min), math.ceil(block.get("end_min", 1440)))
    if end_min <= start_min:
        return None
    start = _clock_to_coord(day_idx, start_min, working_days, day_cap, config)
    end = _clock_to_coord(day_idx, end_min, working_days, day_cap, config)
    if start is None or end is None or end <= start or end > horizon:
        return None
    return model.new_interval_var(start, end - start, end, name)


def _add_exact_resource_blocks(
    model: Any,
    target: dict[str, list[Any]],
    blocks: dict[str, list[dict]],
    full_day_blocks: dict[str, set[int]],
    working_days: list[int],
    day_cap: int,
    config: FactoryConfig,
    horizon: int,
    *,
    prefix: str,
) -> None:
    for resource, entries in blocks.items():
        planning_checkpoint()
        intervals = target.setdefault(resource, [])
        coordinate_blocks: list[tuple[int, int]] = []
        for block in entries:
            # Full-day calendar entries already exist in the compact
            # ``*_blocked_days`` resource. Adding the projected interval too
            # would create two overlapping fixed intervals and make the whole
            # CP-SAT model infeasible.
            block_day = int(block.get("start_day", -1))
            candidate_blocks = [block]
            if block.get("open_end"):
                shifts = ordered_shifts(config)
                candidate_blocks = [
                    {
                        **block,
                        "start_day": day,
                        "start_min": (
                            int(block.get("start_min", shifts[0].start_min))
                            if day == block_day
                            else int(shifts[0].start_min)
                        ),
                        "end_min": int(shifts[-1].end_min),
                    }
                    for day in working_days
                    if day >= block_day
                ]
            for candidate in candidate_blocks:
                day_idx = int(candidate.get("start_day", -1))
                if day_idx in full_day_blocks.get(resource, set()):
                    continue
                start = _clock_to_coord(
                    day_idx,
                    int(candidate.get("start_min", 0)),
                    working_days,
                    day_cap,
                    config,
                )
                end = _clock_to_coord(
                    day_idx,
                    int(candidate.get("end_min", 1440)),
                    working_days,
                    day_cap,
                    config,
                )
                if start is not None and end is not None and start < end <= horizon:
                    coordinate_blocks.append((start, end))
        for idx, (start, end) in enumerate(merge_clock_intervals(coordinate_blocks)):
            intervals.append(
                model.new_interval_var(
                    start,
                    end - start,
                    end,
                    f"blocked_{prefix}_{resource}_{idx}",
                )
            )


def _apply_plan_anchors(
    model: Any,
    options_by_run: dict[str, list[_Option]],
    data: EngineData,
    config: FactoryConfig,
    working_days: list[int],
    day_cap: int,
) -> None:
    if not data.plan_anchors:
        return
    day_by_date = {str(day)[:10]: idx for idx, day in enumerate(data.workdays)}
    timezone = ZoneInfo(config.timezone)
    for anchor in data.plan_anchors:
        try:
            start_at = datetime.fromisoformat(anchor.start_at)
        except ValueError:
            continue
        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone)
        start_at = start_at.astimezone(timezone)
        day_idx = day_by_date.get(start_at.date().isoformat())
        if day_idx is None:
            continue
        target = _clock_to_coord(
            day_idx,
            start_at.hour * 60 + start_at.minute,
            working_days,
            day_cap,
            config,
        )
        if target is None:
            continue
        for options in options_by_run.values():
            if not any(
                lot.id == anchor.lot_id
                for option in options
                for lot, _offset, _duration in option.lot_offsets
            ):
                continue
            for option in options:
                matching = option.machine_id == anchor.machine_id
                lot_entry = next(
                    (item for item in option.lot_offsets if item[0].id == anchor.lot_id),
                    None,
                )
                if not matching or lot_entry is None:
                    model.add(option.presence == 0)
                    continue
                _lot, offset, _duration = lot_entry
                model.add(option.presence == 1)
                model.add(option.start == target - offset)
            break


def _add_hints(
    artifacts: _Artifacts,
    segments: list[Segment],
) -> None:
    by_run: dict[str, list[Segment]] = {}
    for segment in segments:
        by_run.setdefault(segment.run_id, []).append(segment)
    for run_id, options in artifacts.options_by_run.items():
        previous = by_run.get(run_id, [])
        previous_machine = previous[0].machine_id if previous else None
        previous_start = None
        if previous:
            first = min(previous, key=lambda segment: (segment.day_idx, segment.start_min))
            slot = artifacts.day_to_slot.get(first.day_idx)
            if slot is not None:
                previous_start = slot * artifacts.day_cap + clock_to_productive_offset(
                    artifacts.config,
                    first.start_min,
                )
        for option in options:
            selected = int(option.machine_id == previous_machine)
            artifacts.model.add_hint(option.presence, selected)
            if selected and previous_start is not None:
                try:
                    artifacts.model.add_hint(option.start, max(0, int(previous_start)))
                except ValueError:
                    pass


def _extract_selection(
    artifacts: _Artifacts,
    solver: Any,
) -> tuple[dict[str, list[ToolRun]], list[_Option]]:
    machine_runs: dict[str, list[tuple[int, ToolRun]]] = {}
    selected: list[_Option] = []
    for options in artifacts.options_by_run.values():
        option = next(
            (candidate for candidate in options if solver.value(candidate.presence)),
            None,
        )
        if option is None:
            continue
        selected.append(option)
        start_abs = solver.value(option.start) + artifacts.origin_abs
        machine_runs.setdefault(option.machine_id, []).append((start_abs, option.run))
    return {
        machine: [run for _start, run in sorted(entries, key=lambda item: item[0])]
        for machine, entries in machine_runs.items()
    }, selected


def _materialise(
    selected: list[_Option],
    solver: Any,
    origin_abs: int,
    working_days: list[int],
    config: FactoryConfig,
) -> list[Segment]:
    segments: list[Segment] = []
    for option in selected:
        start_coord = int(solver.value(option.start)) + origin_abs
        planning_checkpoint()
        segments.extend(
            _materialise_option(
                option,
                start_coord,
                config,
                working_days=working_days,
            )
        )
    return sorted(
        segments,
        key=lambda segment: (segment.day_idx, segment.start_min, segment.machine_id),
    )


def _preempt_exact_calendar_gaps(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
) -> tuple[list[Segment], int]:
    """Use legal productive prefixes on both sides of exact resource stops."""

    if not any(data.machine_blocked_intervals.values()) and not any(
        data.tool_blocked_intervals.values()
    ):
        return segments, 0

    from backend.scheduler.gap_filling import find_gap_opportunities
    from backend.scheduler.scheduler import _apply_gap_move_batch
    from backend.scheduler.scoring import compute_score

    current = list(segments)
    applied = 0
    max_moves = max(16, min(2048, len(current) * 4))
    while applied < max_moves:
        planning_checkpoint()
        opportunities = find_gap_opportunities(
            current,
            lots,
            data,
            config,
            allow_setup_free_opening=True,
        )
        if not opportunities:
            break
        # Reuse one search snapshot for independent moves. The batch helper
        # validates the full trial and splits conflicting batches recursively.
        before_score = compute_score(
            current, lots, data, config=config, include_operational_audit=False,
        )
        current, accepted, _score = _apply_gap_move_batch(
            current, opportunities[:max_moves - applied], lots, data, config,
            before_score,
        )
        if not accepted:
            break
        applied += accepted
    return current, applied


def _calendar_preemptive_fallback(
    runs: list[ToolRun],
    data: EngineData,
    config: FactoryConfig,
    *,
    horizon_end_day: int | None = None,
) -> (
    tuple[
        list[Segment],
        list[Lot],
        dict[str, list[ToolRun]],
        dict[str, float],
        int,
    ]
    | None
):
    """Build a complete candidate when the contiguous solver finds none.

    CP-SAT models every ToolRun as one interval. That is efficient for the
    normal case, while a recurring partial stop can make a physically feasible
    run look impossible when the run is longer than every uninterrupted gap.
    It also handles solver timeouts without resource stops; the legacy
    dispatcher can truncate production at the original demand horizon.
    This deterministic fallback is used only after both CP models fail. It
    keeps each selected machine/tool campaign reserved until completion and
    emits work only into real resource and operator-capacity windows.
    """

    active_machines = {
        machine.id
        for machine in data.machines
        if config.machines.get(machine.id) is None or config.machines[machine.id].active
    }
    if not active_machines:
        return None

    day_cap = max(1, config.day_capacity_min)
    total_minutes = sum(max(1, math.ceil(run.total_min)) for run in runs)
    bottleneck_days = math.ceil(total_minutes / day_cap)
    due_days = [
        production_due_day(lot, _extended_holidays(data, -20, data.n_days + 400))
        for run in runs
        for lot in run.lots
    ]
    projected_days = [
        int(block.get("start_day", -1))
        for entries in (
            *data.machine_blocked_intervals.values(),
            *data.tool_blocked_intervals.values(),
        )
        for block in entries
    ]
    horizon_day = max(
        data.n_days + bottleneck_days + 30,
        max(due_days, default=0) + bottleneck_days + 30,
        max(projected_days, default=0) + bottleneck_days + 2,
    )
    if horizon_end_day is not None:
        horizon_day = min(horizon_day, horizon_end_day)
    holidays = _extended_holidays(data, -20, horizon_day + 2)
    ops_by_id = {op.id: op for op in data.ops}
    segments: list[Segment] = []
    machine_cursor: dict[str, int] = {}
    tool_cursor: dict[str, int] = {}
    selected_runs: list[tuple[ToolRun, list[Segment], int]] = []
    calendar_preemptions = 0

    for original in sorted(runs, key=run_priority_key):
        planning_checkpoint()
        candidates = [original.machine_id]
        if original.alt_machine_id:
            candidates.append(original.alt_machine_id)
        candidates = [
            machine_id for machine_id in dict.fromkeys(candidates) if machine_id in active_machines
        ]
        best: tuple[int, int, ToolRun, list[Segment], int] | None = None
        for preference, machine_id in enumerate(candidates):
            planning_checkpoint()
            candidate = clone_run_for_machine(original, machine_id, data, config)
            start_after = max(
                machine_cursor.get(machine_id, 0),
                tool_cursor.get(candidate.tool_id, 0),
            )
            scheduled = _schedule_preemptive_run(
                candidate,
                machine_id,
                segments,
                data,
                config,
                ops_by_id,
                holidays,
                start_after,
                horizon_day,
            )
            if scheduled is None:
                continue
            candidate_segments, finish_abs, preemptions = scheduled
            ranking = (finish_abs, preference)
            if best is None or ranking < best[:2]:
                best = (
                    finish_abs,
                    preference,
                    candidate,
                    candidate_segments,
                    preemptions,
                )
        if best is None:
            return None

        finish_abs, _preference, chosen, created, preemptions = best
        segments.extend(created)
        machine_cursor[chosen.machine_id] = finish_abs
        tool_cursor[chosen.tool_id] = finish_abs
        selected_runs.append((chosen, created, finish_abs))
        calendar_preemptions += preemptions

    segments.sort(key=lambda item: (item.day_idx, item.start_min, item.machine_id))
    machine_runs: dict[str, list[ToolRun]] = {}
    run_gates: dict[str, float] = {}
    for run, created, _finish in selected_runs:
        machine_runs.setdefault(run.machine_id, []).append(run)
        first = min(created, key=lambda item: (item.day_idx, item.start_min))
        run_gates[run.id] = float(
            first.day_idx * day_cap + clock_to_productive_offset(config, int(first.start_min))
        )
    machine_runs = {
        machine_id: sorted(
            machine_selected,
            key=lambda run: run_gates.get(run.id, 0.0),
        )
        for machine_id, machine_selected in machine_runs.items()
    }
    lots = [
        lot
        for machine_id in sorted(machine_runs)
        for run in machine_runs[machine_id]
        for lot in run.lots
    ]

    from backend.scheduler.validation import PlanValidationError, assert_plan_valid

    try:
        assert_plan_valid(segments, data, config, lots=lots)
    except PlanValidationError:
        return None
    return segments, lots, machine_runs, run_gates, calendar_preemptions


def _schedule_preemptive_run(
    run: ToolRun,
    machine_id: str,
    existing: list[Segment],
    data: EngineData,
    config: FactoryConfig,
    ops_by_id: dict[str, Any],
    holidays: set[int],
    start_after: int,
    horizon_day: int,
) -> tuple[list[Segment], int, int] | None:
    """Place one non-interleaved run into exact productive calendar slices."""

    lots = sorted(run.lots, key=lot_priority_key)
    if not lots:
        return None
    first_lot = lots[0]
    setup = max(0, math.ceil(run.setup_min))
    first_demand = _operator_demand(first_lot, ops_by_id)
    first_floor = max(0, earliest_allowed_start(first_lot, holidays))
    floor_abs = first_floor * 1440 + int(ordered_shifts(config)[0].start_min)
    setup_slot = _find_preemptive_setup_slot(
        existing,
        data,
        config,
        machine_id,
        run.tool_id,
        first_demand,
        setup,
        max(start_after, floor_abs),
        horizon_day,
        holidays,
        setup_identity=lot_setup_identity(first_lot),
        ignore_run_id=run.id,
    )
    if setup_slot is None:
        return None
    setup_day, setup_start, production_start = setup_slot
    setup = production_start - setup_start
    cursor_abs = setup_day * 1440 + production_start
    created: list[Segment] = []
    all_chunks: list[tuple[int, int, int]] = []

    for lot_index, lot in enumerate(lots):
        planning_checkpoint()
        duration = max(1, math.ceil(lot.prod_min))
        demand = _operator_demand(lot, ops_by_id)
        lot_floor = max(0, earliest_allowed_start(lot, holidays))
        lot_floor_abs = lot_floor * 1440 + int(ordered_shifts(config)[0].start_min)
        cursor_abs = max(cursor_abs, lot_floor_abs)
        chunks = _allocate_preemptive_production(
            [*existing, *created],
            data,
            config,
            machine_id,
            run.tool_id,
            demand,
            duration,
            cursor_abs,
            horizon_day,
            holidays,
            require_exact_start=lot_index == 0,
        )
        if chunks is None:
            return None
        lot_segments = _materialise_preemptive_lot(
            run,
            lot,
            machine_id,
            chunks,
            setup_start=setup_start if lot_index == 0 else None,
            setup_min=setup if lot_index == 0 else 0,
            first_in_run=lot_index == 0,
        )
        created.extend(lot_segments)
        all_chunks.extend((day, start, end) for day, _shift, start, end in chunks)
        last_day, _last_shift, _last_start, last_end = chunks[-1]
        cursor_abs = last_day * 1440 + last_end

    preemptions = _count_calendar_preemptions(
        all_chunks,
        data,
        machine_id,
        run.tool_id,
    )
    return created, cursor_abs, preemptions


def _find_preemptive_setup_slot(
    segments: list[Segment],
    data: EngineData,
    config: FactoryConfig,
    machine_id: str,
    tool_id: str,
    operator_demand: int,
    setup_min: int,
    start_after: int,
    horizon_day: int,
    holidays: set[int],
    *,
    setup_identity: SetupIdentity | None = None,
    ignore_run_id: str | None = None,
) -> tuple[int, int, int] | None:
    """Find setup immediately followed by at least one productive minute."""
    from backend.scheduler.resources import reserved_setup_segments

    group = config.machine_groups.get(machine_id, "Grandes")
    setup_segments = [*segments, *reserved_setup_segments(data)]
    for day, shift_id, window_start, window_end in _preemptive_resource_windows(
        data,
        config,
        machine_id,
        tool_id,
        start_after,
        horizon_day,
        holidays,
    ):
        operator_windows = _preemptive_operator_windows(
            segments,
            data,
            config,
            day,
            shift_id,
            group,
            operator_demand,
            window_start,
            window_end,
        )
        for operator_start, operator_end in operator_windows:
            planning_checkpoint()
            # Retention is a physical proof, not a visual cleanup after booking
            # nominal setup time and displacing the following production.
            if setup_identity is not None and retained_setup_at(
                segments, machine_id, setup_identity, day, operator_start,
                ignore_run_id=ignore_run_id,
            ):
                return day, operator_start, operator_start
            candidate_starts = {
                window_start,
                max(window_start, operator_start - setup_min),
            }
            for segment in setup_segments:
                if (
                    segment.day_idx == day
                    and segment.setup_min > 0
                    and config.machine_groups.get(segment.machine_id, "Grandes") == group
                ):
                    candidate_starts.add(int(math.ceil(segment.start_min + segment.setup_min)))
            for setup_start in sorted(candidate_starts):
                production_start = setup_start + setup_min
                if setup_start < window_start or production_start + 1 > window_end:
                    continue
                if not operator_start <= production_start < operator_end:
                    continue
                if production_start + 1 > operator_end:
                    continue
                if not _preemptive_setup_capacity_available(
                    segments,
                    config,
                    machine_id,
                    day,
                    setup_start,
                    production_start,
                    data,
                ):
                    continue
                return day, setup_start, production_start
    return None


def _allocate_preemptive_production(
    segments: list[Segment],
    data: EngineData,
    config: FactoryConfig,
    machine_id: str,
    tool_id: str,
    operator_demand: int,
    duration: int,
    start_after: int,
    horizon_day: int,
    holidays: set[int],
    *,
    require_exact_start: bool,
) -> list[tuple[int, str, int, int]] | None:
    group = config.machine_groups.get(machine_id, "Grandes")
    remaining = duration
    chunks: list[tuple[int, str, int, int]] = []
    for day, shift_id, window_start, window_end in _preemptive_resource_windows(
        data,
        config,
        machine_id,
        tool_id,
        start_after,
        horizon_day,
        holidays,
    ):
        for available_start, available_end in _preemptive_operator_windows(
            segments,
            data,
            config,
            day,
            shift_id,
            group,
            operator_demand,
            window_start,
            window_end,
        ):
            start = max(available_start, start_after - day * 1440)
            if start >= available_end:
                continue
            if require_exact_start and not chunks and day * 1440 + start != start_after:
                return None
            block = min(remaining, available_end - start)
            if block <= 0:
                continue
            chunks.append((day, shift_id, start, start + block))
            remaining -= block
            if remaining <= 0:
                return chunks
    return None


def _preemptive_resource_windows(
    data: EngineData,
    config: FactoryConfig,
    machine_id: str,
    tool_id: str,
    start_after: int,
    horizon_day: int,
    holidays: set[int],
):
    """Yield exact machine/tool windows in deterministic wall-clock order."""
    from backend.transform.calendars import calendar_window

    data = calendar_window(data, config, horizon_day, from_day=max(0, start_after // 1440))

    first_day = max(0, start_after // 1440)
    machine_days = data.machine_blocked_days.get(machine_id, set())
    tool_days = data.tool_blocked_days.get(tool_id, set())
    entries = [
        *data.machine_blocked_intervals.get(machine_id, []),
        *data.tool_blocked_intervals.get(tool_id, []),
    ]
    open_origins = [int(block.get("start_day", -1)) for block in entries if block.get("open_end")]
    open_origin = min(open_origins) if open_origins else None
    for day in range(first_day, horizon_day + 1):
        planning_checkpoint()
        if (
            day in holidays
            or day in machine_days
            or day in tool_days
            or open_origin is not None
            and day > open_origin
        ):
            continue
        day_blocks = [
            (int(block.get("start_min", 0)), int(block.get("end_min", 1440)))
            for block in entries
            if int(block.get("start_day", -1)) == day
        ]
        for shift in ordered_shifts(config):
            cursor = max(
                int(shift.start_min),
                start_after - day * 1440 if day == first_day else int(shift.start_min),
            )
            shift_end = int(shift.end_min)
            for block_start, block_end in merge_clock_intervals(day_blocks):
                block_start = max(int(shift.start_min), block_start)
                block_end = min(shift_end, block_end)
                if block_end <= cursor or block_start >= shift_end:
                    continue
                if block_start > cursor:
                    yield day, shift.id, cursor, block_start
                cursor = max(cursor, block_end)
            if cursor < shift_end:
                yield day, shift.id, cursor, shift_end


def _preemptive_operator_windows(
    segments: list[Segment],
    data: EngineData,
    config: FactoryConfig,
    day: int,
    shift_id: str,
    group: str,
    required: int,
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    """Return slices where concurrent production plus absences fit headcount."""
    return operator_free_windows(
        segments, data, config, day=day, shift=shift_id, group=group,
        required=required, start=start, end=end,
    )


def _preemptive_setup_capacity_available(
    segments: list[Segment],
    config: FactoryConfig,
    machine_id: str,
    day: int,
    start: int,
    end: int,
    data: EngineData | None = None,
) -> bool:
    if end <= start:
        return True
    group = config.machine_groups.get(machine_id, "Grandes")
    capacity = max(1, int(config.setup_crews_by_group.get(group, 1)))
    overlaps: list[tuple[float, float]] = []
    boundaries = {start, end}
    from backend.scheduler.resources import reserved_setup_segments

    for segment in [*segments, *reserved_setup_segments(data)]:
        if (
            segment.day_idx != day
            or segment.setup_min <= 0
            or config.machine_groups.get(segment.machine_id, "Grandes") != group
        ):
            continue
        other_start = int(segment.start_min)
        other_end = segment.production_start_min
        if start < other_end and other_start < end:
            overlaps.append((other_start, other_end))
            boundaries.update((max(start, other_start), min(end, other_end)))
    for left, right in zip(sorted(boundaries), sorted(boundaries)[1:]):
        if right <= left:
            continue
        occupied = sum(
            left < other_end and other_start < right for other_start, other_end in overlaps
        )
        if occupied >= capacity:
            return False
    return True


def _materialise_preemptive_lot(
    run: ToolRun,
    lot: Lot,
    machine_id: str,
    chunks: list[tuple[int, str, int, int]],
    *,
    setup_start: int | None,
    setup_min: int,
    first_in_run: bool,
) -> list[Segment]:
    duration = sum(end - start for _day, _shift, start, end in chunks)
    allocated_qty = 0
    allocated_twin = [0 for _ in (lot.twin_outputs or [])]
    consumed = 0
    result: list[Segment] = []
    run_qty = sum(run_lot.qty for run_lot in run.lots)
    for index, (day, shift_id, production_start, end) in enumerate(chunks):
        block = end - production_start
        consumed += block
        last = index == len(chunks) - 1
        target_qty = lot.qty if last else round(lot.qty * consumed / max(1, duration))
        qty = max(0, target_qty - allocated_qty)
        allocated_qty += qty
        twin_outputs = None
        if lot.twin_outputs is not None:
            twin_outputs = []
            for output_index, (op_id, sku, total_qty) in enumerate(lot.twin_outputs):
                target = total_qty if last else round(total_qty * consumed / max(1, duration))
                output_qty = max(0, target - allocated_twin[output_index])
                allocated_twin[output_index] += output_qty
                twin_outputs.append((op_id, sku, output_qty))
        segment_setup = setup_min if first_in_run and index == 0 else 0
        start = setup_start if segment_setup and setup_start is not None else production_start
        result.append(
            Segment(
                lot_id=lot.id,
                run_id=run.id,
                machine_id=machine_id,
                tool_id=run.tool_id,
                day_idx=day,
                start_min=int(start),
                end_min=int(end),
                shift=shift_id,
                qty=qty,
                prod_min=float(block),
                setup_min=float(segment_setup),
                is_continuation=not (first_in_run and index == 0),
                edd=lot.edd,
                sku=lot.sku or (lot.twin_outputs[0][1] if lot.twin_outputs else ""),
                setup_family=lot.setup_family,
                twin_outputs=twin_outputs,
                lot_qty=lot.qty,
                run_qty=run_qty,
                run_setup_min=run.setup_min,
                run_lot_count=len(run.lots),
                original_edd=lot.original_edd,
                internal_deadline=lot.internal_deadline,
                delivery_day=lot.delivery_day,
                customer_delivery_day=lot.customer_delivery_day,
                latest_subcontract_dispatch_day=lot.latest_subcontract_dispatch_day,
                subcontract_dispatch_day=lot.subcontract_dispatch_day,
                production_due_day=lot.production_due_day,
                internal_target_day=lot.internal_target_day,
                material_reference_day=lot.material_reference_day,
                material_reference_kind=lot.material_reference_kind,
                eco_lot_isop=lot.eco_lot_isop,
                eco_lot_effective=lot.eco_lot_effective,
                start_buffer_days=lot.start_buffer_days,
                finish_buffer_days=lot.finish_buffer_days,
                target_start_day=lot.target_start_day,
                min_campaign_qty=lot.min_campaign_qty,
                min_campaign_prod_min=lot.min_campaign_prod_min,
                max_group_gap_days=lot.max_group_gap_days,
                planning_priority=lot.planning_priority,
                material_release_day=lot.material_release_day,
                output_milestones=(
                    [dict(item) for item in lot.output_milestones]
                    if lot.output_milestones is not None
                    else None
                ),
                planning_source=lot.planning_source,
                economic_warning=lot.economic_warning,
                is_subcontracted=lot.is_subcontracted,
                subcontract_company_id=lot.subcontract_company_id,
                subcontract_lead_time_days=lot.subcontract_lead_time_days,
                subcontract_buffer_days=lot.subcontract_buffer_days,
            )
        )
    return result


def _count_calendar_preemptions(
    chunks: list[tuple[int, int, int]],
    data: EngineData,
    machine_id: str,
    tool_id: str,
) -> int:
    ordered = sorted(chunks)
    exact = [
        *data.machine_blocked_intervals.get(machine_id, []),
        *data.tool_blocked_intervals.get(tool_id, []),
    ]
    count = 0
    for previous, following in zip(ordered, ordered[1:]):
        previous_day, _previous_start, previous_end = previous
        following_day, following_start, _following_end = following
        if any(
            previous_day <= int(block.get("start_day", -1)) <= following_day
            and (
                int(block.get("start_day", -1)) != previous_day
                or int(block.get("end_min", 1440)) > previous_end
            )
            and (
                int(block.get("start_day", -1)) != following_day
                or int(block.get("start_min", 0)) < following_start
            )
            for block in exact
        ):
            count += 1
    return count


def _strict_delivery_feasible(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
) -> bool:
    holidays = _extended_holidays(data, -20, data.n_days + 100)
    completion: dict[str, int] = {}
    for segment in segments:
        if segment.prod_min <= 0:
            continue
        completion[segment.lot_id] = max(
            completion.get(segment.lot_id, segment.day_idx),
            segment.day_idx,
        )
    return all(
        lot.id in completion and completion[lot.id] <= production_due_day(lot, holidays)
        for lot in lots
    )


def _materialised_run_gate(
    option: _Option,
    segments: list[Segment],
    solver: Any,
    artifacts: _Artifacts,
    config: FactoryConfig,
) -> float:
    materialised = [segment for segment in segments if segment.run_id == option.run.id]
    if materialised:
        first = min(materialised, key=lambda item: (item.day_idx, item.start_min))
        coordinate = _clock_to_coord(
            first.day_idx,
            int(first.start_min),
            artifacts.working_days,
            artifacts.day_cap,
            config,
        )
        if coordinate is not None:
            return float(_coord_to_abs(coordinate, artifacts.working_days, artifacts.day_cap))
    return float(
        _coord_to_abs(
            int(solver.value(option.start)),
            artifacts.working_days,
            artifacts.day_cap,
        )
    )


def _materialise_option(
    option: _Option,
    start_abs: int,
    config: FactoryConfig,
    working_days: list[int] | None = None,
) -> list[Segment]:
    """Convert one contiguous CP-SAT run into exact, quantity-conserving blocks."""

    day_cap = config.day_capacity_min
    segments: list[Segment] = []
    setup_start = start_abs
    prod_cursor = start_abs + option.setup
    setup_attached = False

    for lot_idx, (lot, _offset, duration) in enumerate(option.lot_offsets):
        planning_checkpoint()
        chunks: list[tuple[int, int, int, str]] = []
        remaining = duration
        cursor = prod_cursor
        while remaining > 0:
            planning_checkpoint()
            slot = math.floor(cursor / day_cap)
            day = working_days[slot] if working_days is not None else slot
            offset = cursor - slot * day_cap
            shift, _clock, shift_end_offset = _shift_at_offset(config, offset)
            available = max(1, shift_end_offset - offset)
            block = min(remaining, available)
            chunks.append((day, int(offset), int(block), shift))
            cursor += block
            remaining -= block

        allocated_qty = 0
        allocated_twin = [0 for _ in (lot.twin_outputs or [])]
        consumed = 0
        for chunk_idx, (day, offset, block, shift) in enumerate(chunks):
            consumed += block
            target_qty = (
                lot.qty if chunk_idx == len(chunks) - 1 else round(lot.qty * consumed / duration)
            )
            block_qty = max(0, target_qty - allocated_qty)
            allocated_qty += block_qty
            twin_out = None
            if lot.twin_outputs is not None:
                twin_out = []
                for output_idx, (op_id, sku, total_qty) in enumerate(lot.twin_outputs):
                    target = (
                        total_qty
                        if chunk_idx == len(chunks) - 1
                        else round(total_qty * consumed / duration)
                    )
                    qty = max(0, target - allocated_twin[output_idx])
                    allocated_twin[output_idx] += qty
                    twin_out.append((op_id, sku, qty))

            seg_setup = 0
            _shift_id, clock_start, _boundary = _shift_at_offset(config, offset)
            if not setup_attached and lot_idx == 0 and option.setup:
                setup_slot = math.floor(setup_start / day_cap)
                setup_day = working_days[setup_slot] if working_days is not None else setup_slot
                setup_offset = setup_start - setup_slot * day_cap
                setup_shift, setup_clock, _setup_boundary = _shift_at_offset(
                    config,
                    setup_offset,
                )
                if setup_day == day and setup_shift == shift:
                    seg_setup = option.setup
                    clock_start = setup_clock
                    setup_attached = True
            _end_shift, clock_end, _end_boundary = _shift_at_offset(
                config,
                min(day_cap - 1, offset + block - 1),
            )
            clock_end += 1
            sku = lot.sku or (lot.twin_outputs[0][1] if lot.twin_outputs else "")
            segments.append(
                Segment(
                    lot_id=lot.id,
                    run_id=option.run.id,
                    machine_id=option.machine_id,
                    tool_id=option.run.tool_id,
                    day_idx=day,
                    start_min=int(clock_start),
                    end_min=int(clock_end),
                    shift=shift,
                    qty=block_qty,
                    prod_min=float(block),
                    setup_min=float(seg_setup),
                    is_continuation=chunk_idx > 0,
                    edd=lot.edd,
                    sku=sku,
                    setup_family=lot.setup_family,
                    twin_outputs=twin_out,
                    lot_qty=lot.qty,
                    run_qty=sum(run_lot.qty for run_lot in option.run.lots),
                    run_setup_min=option.run.setup_min,
                    run_lot_count=len(option.run.lots),
                    original_edd=lot.original_edd,
                    internal_deadline=lot.internal_deadline,
                    delivery_day=lot.delivery_day,
                    customer_delivery_day=lot.customer_delivery_day,
                    latest_subcontract_dispatch_day=lot.latest_subcontract_dispatch_day,
                    subcontract_dispatch_day=lot.subcontract_dispatch_day,
                    production_due_day=lot.production_due_day,
                    internal_target_day=lot.internal_target_day,
                    material_reference_day=lot.material_reference_day,
                    material_reference_kind=lot.material_reference_kind,
                    eco_lot_isop=lot.eco_lot_isop,
                    eco_lot_effective=lot.eco_lot_effective,
                    start_buffer_days=lot.start_buffer_days,
                    finish_buffer_days=lot.finish_buffer_days,
                    target_start_day=lot.target_start_day,
                    min_campaign_qty=lot.min_campaign_qty,
                    min_campaign_prod_min=lot.min_campaign_prod_min,
                    max_group_gap_days=lot.max_group_gap_days,
                    planning_priority=lot.planning_priority,
                    material_release_day=lot.material_release_day,
                    output_milestones=(
                        [dict(item) for item in lot.output_milestones]
                        if lot.output_milestones is not None
                        else None
                    ),
                    planning_source=lot.planning_source,
                    economic_warning=lot.economic_warning,
                    is_subcontracted=lot.is_subcontracted,
                    subcontract_company_id=lot.subcontract_company_id,
                    subcontract_lead_time_days=lot.subcontract_lead_time_days,
                    subcontract_buffer_days=lot.subcontract_buffer_days,
                )
            )
        prod_cursor += duration

    if option.setup and not setup_attached and option.lot_offsets:
        lot = option.lot_offsets[0][0]
        slot = math.floor(setup_start / day_cap)
        day = working_days[slot] if working_days is not None else slot
        offset = setup_start - slot * day_cap
        shift, clock_start, _boundary = _shift_at_offset(config, offset)
        segments.insert(
            0,
            Segment(
                lot_id=lot.id,
                run_id=option.run.id,
                machine_id=option.machine_id,
                tool_id=option.run.tool_id,
                day_idx=day,
                start_min=int(clock_start),
                end_min=int(clock_start + option.setup),
                shift=shift,
                qty=0,
                prod_min=0.0,
                setup_min=float(option.setup),
                edd=lot.edd,
                sku=lot.sku or (lot.twin_outputs[0][1] if lot.twin_outputs else ""),
                setup_family=lot.setup_family,
                twin_outputs=(
                    [(op_id, sku, 0) for op_id, sku, _qty in lot.twin_outputs]
                    if lot.twin_outputs is not None
                    else None
                ),
                original_edd=lot.original_edd,
                internal_deadline=lot.internal_deadline,
                delivery_day=lot.delivery_day,
                customer_delivery_day=lot.customer_delivery_day,
                latest_subcontract_dispatch_day=lot.latest_subcontract_dispatch_day,
                subcontract_dispatch_day=lot.subcontract_dispatch_day,
                production_due_day=lot.production_due_day,
                internal_target_day=lot.internal_target_day,
                material_reference_day=lot.material_reference_day,
                material_reference_kind=lot.material_reference_kind,
                planning_priority=lot.planning_priority,
                material_release_day=lot.material_release_day,
                output_milestones=(
                    [dict(item) for item in lot.output_milestones]
                    if lot.output_milestones is not None
                    else None
                ),
                planning_source=lot.planning_source,
                economic_warning=lot.economic_warning,
                is_subcontracted=lot.is_subcontracted,
                subcontract_company_id=lot.subcontract_company_id,
                subcontract_lead_time_days=lot.subcontract_lead_time_days,
                subcontract_buffer_days=lot.subcontract_buffer_days,
            ),
        )
    return segments


def materialise_fixed_run(
    run: ToolRun,
    machine_id: str,
    start_coord: int,
    working_days: list[int],
    config: FactoryConfig,
) -> list[Segment]:
    """Materialise one fixed run with the constructor's canonical semantics.

    Final-plan repairs use this small public entry point instead of duplicating
    shift splitting, setup placement and exact quantity allocation. Coordinates
    are expressed in productive factory minutes over ``working_days``.
    """

    setup = max(0, math.ceil(run.setup_min))
    lot_offsets: list[tuple[Lot, int, int]] = []
    offset = setup
    for lot in run.lots:
        duration = max(1, math.ceil(lot.prod_min))
        lot_offsets.append((lot, offset, duration))
        offset += duration
    option = _Option(
        run=run,
        machine_id=machine_id,
        presence=None,
        start=None,
        end=None,
        duration=max(1, offset),
        setup=setup,
        lot_offsets=lot_offsets,
    )
    return _materialise_option(
        option,
        int(start_coord),
        config,
        working_days=working_days,
    )


def _allowed_setup_starts(
    working_days: list[int],
    latest_abs: int,
    setup: int,
    day_cap: int,
    shift_durations: list[int],
    holidays: set[int],
    *,
    minimum_productive_run: int = 0,
) -> list[list[int]]:
    intervals: list[list[int]] = []
    for slot, day in enumerate(working_days):
        if day in holidays:
            continue
        offset = 0
        for duration in shift_durations:
            lo_abs = slot * day_cap + offset
            # Setup and the first meaningful production tranche are one
            # industrial commitment.  Production may continue in following
            # shifts, but a token minute may not be used to park a prepared
            # mould over an idle period.
            productive_start = max(0, int(minimum_productive_run))
            hi_abs = min(
                latest_abs,
                lo_abs + duration - setup - productive_start,
            )
            if hi_abs >= lo_abs:
                intervals.append([lo_abs, hi_abs])
            # It is also physically valid to finish the setup exactly at a
            # shift boundary and start production at the next factory minute.
            # In compressed work-time that can be the following shift or the
            # next workday.  This is the only setup-only placement allowed and
            # keeps the machine committed to the prepared tool throughout the
            # intervening closed period.
            boundary_start = lo_abs + duration - setup
            if setup > 0 and boundary_start >= lo_abs and boundary_start <= latest_abs:
                intervals.append([boundary_start, boundary_start])
            offset += duration
    # CP-SAT domains may receive adjacent/duplicate intervals.  Normalise them
    # so the optional boundary point does not create an invalid domain.
    merged: list[list[int]] = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return merged


def _shift_at_offset(config: FactoryConfig, offset: int) -> tuple[str, int, int]:
    cumulative = 0
    shifts = ordered_shifts(config)
    for shift in shifts:
        boundary = cumulative + shift.duration_min
        if offset < boundary:
            return shift.id, shift.start_min + (offset - cumulative), boundary
        cumulative = boundary
    last = shifts[-1]
    return last.id, last.end_min, cumulative


def _start_coord(day: int, working_days: list[int], day_cap: int) -> int:
    """First compressed working minute on or after an actual day index."""

    for slot, actual_day in enumerate(working_days):
        if actual_day >= day:
            return slot * day_cap
    return len(working_days) * day_cap


def _due_end_coord(day: int, working_days: list[int], day_cap: int) -> int:
    """End of the last working day not later than the production due day."""

    last_slot: int | None = None
    for slot, actual_day in enumerate(working_days):
        if actual_day > day:
            break
        last_slot = slot
    if last_slot is None:
        return 0
    return (last_slot + 1) * day_cap


def _coord_to_abs(coord: int, working_days: list[int], day_cap: int) -> int:
    slot = min(max(0, coord // day_cap), max(0, len(working_days) - 1))
    offset = coord - slot * day_cap
    return working_days[slot] * day_cap + offset


def _operator_demand(lot: Lot, ops_by_id: dict[str, Any]) -> int:
    if lot.twin_outputs:
        return max(
            [
                int(getattr(ops_by_id.get(op_id), "operators", 1) or 1)
                for op_id, _sku, _qty in lot.twin_outputs
            ]
            or [1]
        )
    return max(1, int(getattr(ops_by_id.get(lot.op_id), "operators", 1) or 1))


def _extended_holidays(data: EngineData, start_day: int, end_day: int) -> set[int]:
    return calendar_holidays(data, start_day, end_day)


def _build_feasibility_report(
    runs: list[ToolRun],
    data: EngineData,
    config: FactoryConfig,
    *,
    solver_status: str,
    strict_status: str,
    deadline: float | None = None,
) -> dict[str, Any]:
    lots = [lot for run in runs for lot in run.lots]
    lower_bound = _minimum_window_lower_bound(
        lots,
        data,
        config,
        deadline=deadline,
    )
    constraints = _binding_capacity_constraints(
        lots,
        data,
        config,
        deadline=deadline,
    )
    interventions: list[dict[str, Any]] = []
    for constraint in constraints[:10]:
        interventions.append(
            {
                "type": "overtime",
                "resource_type": constraint["resource_type"],
                "resource_id": constraint["resource_id"],
                "from_day": constraint["from_day"],
                "to_day": constraint["to_day"],
                "required_minutes": constraint["deficit_min"],
                "automatic": False,
            }
        )
        if constraint.get("affected_qty", 0):
            interventions.append(
                {
                    "type": "subcontract",
                    "resource_type": constraint["resource_type"],
                    "resource_id": constraint["resource_id"],
                    "from_day": constraint["from_day"],
                    "to_day": constraint["to_day"],
                    "required_qty_upper_bound": constraint["affected_qty"],
                    "automatic": False,
                }
            )
    return {
        "solver_status": solver_status,
        "strict_solver_status": strict_status,
        "strict_feasible": solver_status in {"strict_feasible", "timeout_with_candidate"}
        and strict_status in {"OPTIMAL", "FEASIBLE"},
        "jit_window_workdays": JIT_MAX_ANTICIPATION_WORKDAYS,
        "minimum_required_window_workdays_lower_bound": lower_bound,
        "binding_constraints": constraints,
        "interventions": interventions,
    }


def _minimum_window_lower_bound(
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    max_width: int = 12,
    *,
    deadline: float | None = None,
) -> int | None:
    """Return a proven lower bound from a production-only relaxation."""

    if not HAS_ORTOOLS or not lots:
        return None
    machines = {
        machine.id
        for machine in data.machines
        if config.machines.get(machine.id) is None or config.machines[machine.id].active
    }
    day_cap = config.day_capacity_min
    customer_days = sorted({expedition_day(lot) for lot in lots})
    rough_min = min(customer_days) - max_width * 2 - 30
    rough_max = max(customer_days) + 30
    rough_holidays = _extended_holidays(data, rough_min, rough_max)
    reference_days = sorted({material_reference_day(lot, rough_holidays) for lot in lots})
    production_due_days = sorted({production_due_day(lot, rough_holidays) for lot in lots})
    # Preserve real gaps by mapping every workday in the relevant calendar.
    min_day = min(reference_days) - max_width * 2 - 5
    max_day = max(max(customer_days), max(production_due_days)) + 1
    holidays = _extended_holidays(data, min_day, max_day)
    workdays = [day for day in range(min_day, max_day + 1) if day not in holidays]
    work_rank = {day: idx for idx, day in enumerate(workdays)}

    lower_bound = JIT_MAX_ANTICIPATION_WORKDAYS
    for width in range(JIT_MAX_ANTICIPATION_WORKDAYS, max_width + 1):
        planning_checkpoint()
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0.005:
            break
        model = cp_model.CpModel()
        machine_intervals: dict[str, list[Any]] = {machine: [] for machine in machines}
        horizon = max(1, len(workdays) * day_cap)
        for idx, lot in enumerate(lots):
            candidates = [lot.machine_id]
            if lot.alt_machine_id:
                candidates.append(lot.alt_machine_id)
            candidates = [machine for machine in dict.fromkeys(candidates) if machine in machines]
            presences = []
            reference = material_reference_day(lot, holidays)
            due_day = production_due_day(lot, holidays)
            due_rank = work_rank.get(due_day)
            if due_rank is None:
                prior = [day for day in workdays if day <= due_day]
                due_rank = work_rank[prior[-1]] if prior else 0
            reference_rank = work_rank.get(reference)
            if reference_rank is None:
                prior = [day for day in workdays if day <= reference]
                reference_rank = work_rank[prior[-1]] if prior else 0
            floor_rank = max(0, reference_rank - width)
            duration = max(1, math.ceil(lot.prod_min))
            for opt, machine in enumerate(candidates):
                presence = model.new_bool_var(f"p_{idx}_{opt}")
                if floor_rank > due_rank:
                    model.add(presence == 0)
                    start = model.new_int_var(0, 0, f"s_{idx}_{opt}")
                else:
                    start = model.new_int_var(
                        floor_rank * day_cap,
                        (due_rank + 1) * day_cap,
                        f"s_{idx}_{opt}",
                    )
                end = model.new_int_var(0, horizon, f"e_{idx}_{opt}")
                model.add(end == start + duration)
                model.add(end <= (due_rank + 1) * day_cap).only_enforce_if(presence)
                machine_intervals[machine].append(
                    model.new_optional_interval_var(
                        start,
                        duration,
                        end,
                        presence,
                        f"iv_{idx}_{opt}",
                    )
                )
                presences.append(presence)
            model.add_exactly_one(presences)
        for intervals in machine_intervals.values():
            model.add_no_overlap(intervals)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = min(
            0.5,
            max(0.001, remaining - 0.002) if remaining is not None else 0.5,
        )
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 42
        status = solve_cpsat(solver, model)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return lower_bound
        if status == cp_model.INFEASIBLE:
            lower_bound = width + 1
        else:
            return lower_bound if lower_bound > JIT_MAX_ANTICIPATION_WORKDAYS else None
    return lower_bound


def _binding_capacity_constraints(
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    holidays = _extended_holidays(data, -20, data.n_days + 5)
    resources: dict[tuple[str, str], list[Lot]] = {}
    for lot in lots:
        resources.setdefault(("tool", lot.tool_id), []).append(lot)
        if not lot.alt_machine_id:
            resources.setdefault(("machine", lot.machine_id), []).append(lot)

    constraints: list[dict[str, Any]] = []
    for (resource_type, resource_id), resource_lots in resources.items():
        planning_checkpoint()
        if deadline is not None and time.monotonic() >= deadline:
            break
        boundary_days = sorted(
            {
                day
                for lot in resource_lots
                for day in (
                    earliest_allowed_start(lot, holidays),
                    production_due_day(lot, holidays),
                )
            }
        )
        for start in boundary_days:
            planning_checkpoint()
            if deadline is not None and time.monotonic() >= deadline:
                break
            for end in boundary_days:
                if deadline is not None and time.monotonic() >= deadline:
                    break
                if end < start:
                    continue
                enclosed = [
                    lot
                    for lot in resource_lots
                    if earliest_allowed_start(lot, holidays) >= start
                    and production_due_day(lot, holidays) <= end
                ]
                if not enclosed:
                    continue
                demand = sum(lot.prod_min for lot in enclosed)
                workdays = sum(1 for day in range(start, end + 1) if day not in holidays)
                capacity = workdays * config.day_capacity_min
                deficit = demand - capacity
                if deficit <= 0.5:
                    continue
                constraints.append(
                    {
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "from_day": start,
                        "to_day": end,
                        "demand_min": round(demand, 1),
                        "capacity_min": round(capacity, 1),
                        "deficit_min": round(deficit, 1),
                        "affected_lots": [lot.id for lot in enclosed[:20]],
                        "affected_ops": sorted({lot.op_id for lot in enclosed})[:20],
                        "affected_qty": sum(lot_delivery_qty(lot) for lot in enclosed),
                    }
                )
    constraints.sort(key=lambda item: (-item["deficit_min"], item["resource_id"]))
    return constraints[:25]


def _status_name(status: int) -> str:
    mapping = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    return mapping.get(status, "UNKNOWN")
