# CP-SAT Solver — OR-Tools wrapper
# Conforme CLAUDE.md Camada 3: CP-SAT server-side (OR-Tools, 5-60s)
# <50 jobs: solução óptima. 50-200: time limit 30-60s. >200: fallback Camada 1.
#
# Supports two modes:
#   use_circuit=True  (default): AddCircuit per machine, sequence-dependent setups
#   use_circuit=False (legacy):  Fixed setup per op, NoOverlap per machine

from __future__ import annotations

import time
from collections import defaultdict

from ortools.sat.python import cp_model

from .cpsat_constraints import (
    add_setup_crew_constraint,
    analyse_operator_pool,
    apply_calco_timeline,
    apply_tool_timeline,
    build_twin_merged_intervals,
)
from .schemas import ScheduledOp, SolverRequest, SolverResult
from .setup_sequencing import add_machine_circuit
from .warm_start import add_edd_hints, pick_best_heuristic


class CpsatSolver:
    """
    Wrapper para o solver CP-SAT do OR-Tools.

    Suporta 3 objectivos: makespan, tardiness, weighted_tardiness.
    Constraints: precedência, NoOverlap máquina, SetupCrew, ToolTimeline,
    CalcoTimeline, OperatorPool (advisory), Twin co-production.

    When use_circuit=True (default), uses AddCircuit for sequence-dependent
    setup times. Same tool consecutive → zero setup.
    """

    def solve(self, request: SolverRequest) -> SolverResult:
        start_time = time.monotonic()
        model = cp_model.CpModel()

        all_ops = []
        for job in request.jobs:
            for op in job.operations:
                all_ops.append((job, op))

        n_ops = len(all_ops)

        if n_ops == 0:
            return SolverResult(
                schedule=[],
                makespan_min=0,
                total_tardiness_min=0,
                weighted_tardiness=0.0,
                solver_used="cpsat",
                solve_time_s=0.0,
                status="optimal",
                objective_value=0.0,
                n_ops=0,
            )

        # 1. Calculate horizon (rounded up to DAY_CAP multiple for day constraints)
        DAY_CAP = 1020
        if request.workdays:
            # Workday-aware: horizon = number of workdays × DAY_CAP
            # Due dates are already in workday-indexed time from the bridge
            n_workdays = len(request.workdays)
            horizon = n_workdays * DAY_CAP
            # Ensure horizon covers all due dates
            max_due = max(j.due_date_min for j in request.jobs)
            if max_due >= horizon:
                horizon = ((max_due + DAY_CAP) // DAY_CAP) * DAY_CAP
        else:
            horizon = sum(op.duration_min + op.setup_min for _, op in all_ops)
            horizon = max(horizon, max(j.due_date_min for j in request.jobs) + 1)
            horizon = ((horizon + DAY_CAP - 1) // DAY_CAP) * DAY_CAP

        use_circuit = request.config.use_circuit

        # Build twin set for quick lookup
        twin_op_ids = set()
        for pair in request.twin_pairs:
            twin_op_ids.add(pair.op_id_a)
            twin_op_ids.add(pair.op_id_b)

        # 2. Create variables per op
        # op_vars: op_id → (start, end, setup_iv, prod_iv, full_iv, job, op)
        op_vars: dict[str, tuple] = {}
        machine_intervals: dict[str, list[cp_model.IntervalVar]] = defaultdict(list)
        setup_intervals: list[cp_model.IntervalVar] = []
        op_tool_map: dict[str, str] = {}
        op_calco_map: dict[str, str | None] = {}
        op_machine_map: dict[str, str] = {}
        op_full_intervals: dict[str, cp_model.IntervalVar] = {}

        # Track per-machine non-twin ops for circuit building
        machine_jobs: dict[str, list[dict]] = defaultdict(list)
        prod_durations: dict[str, int] = {}

        for job, op in all_ops:
            suffix = f"_{op.id}"
            is_twin = op.id in twin_op_ids

            start_var = model.NewIntVar(0, horizon, f"start{suffix}")
            end_var = model.NewIntVar(0, horizon, f"end{suffix}")

            if use_circuit:
                # Circuit mode: no fixed setup/prod split.
                # start/end are free; circuit constraints handle sequencing + setup.
                setup_iv = None
                prod_iv = None
                full_iv = None

                if not is_twin:
                    # Track for circuit building
                    machine_jobs[op.machine_id].append(
                        {
                            "job_id": op.id,
                            "tool": op.tool_id,
                            "setup_default": op.setup_min,
                        }
                    )
                    prod_durations[op.id] = op.duration_min

                    # Create full interval for tool/calco timeline constraints.
                    # Size is variable (depends on circuit sequence), so use
                    # wide range: [duration_min, duration_min + max_possible_setup].
                    max_setup = max(op.setup_min, 90)  # at least 90 to cover defaults
                    size_var = model.NewIntVar(
                        op.duration_min, op.duration_min + max_setup, f"sz{suffix}"
                    )
                    full_iv = model.NewIntervalVar(
                        start_var, size_var, end_var, f"interval{suffix}"
                    )
                    op_full_intervals[op.id] = full_iv
            else:
                # Legacy mode: fixed setup per op
                if is_twin:
                    setup_iv = None
                    prod_iv = None
                    full_iv = None
                elif op.setup_min > 0:
                    total_duration = op.duration_min + op.setup_min
                    setup_end = model.NewIntVar(0, horizon, f"setup_end{suffix}")
                    setup_iv = model.NewIntervalVar(
                        start_var, op.setup_min, setup_end, f"setup_iv{suffix}"
                    )
                    prod_iv = model.NewIntervalVar(
                        setup_end, op.duration_min, end_var, f"prod_iv{suffix}"
                    )
                    setup_intervals.append(setup_iv)
                    full_iv = model.NewIntervalVar(
                        start_var, total_duration, end_var, f"interval{suffix}"
                    )
                    machine_intervals[op.machine_id].append(full_iv)
                else:
                    total_duration = op.duration_min
                    setup_iv = None
                    prod_iv = model.NewIntervalVar(
                        start_var, op.duration_min, end_var, f"prod_iv{suffix}"
                    )
                    full_iv = model.NewIntervalVar(
                        start_var, total_duration, end_var, f"interval{suffix}"
                    )
                    machine_intervals[op.machine_id].append(full_iv)

            op_vars[op.id] = (start_var, end_var, setup_iv, prod_iv, full_iv, job, op)
            op_tool_map[op.id] = op.tool_id
            op_calco_map[op.id] = op.calco_code
            op_machine_map[op.id] = op.machine_id

        # 3. Twin co-production: merged intervals
        twin_merged, twin_warnings = build_twin_merged_intervals(
            model, request.twin_pairs, op_vars, horizon
        )
        for _pair_key, (merged_iv, machine_id, pair) in twin_merged.items():
            machine_intervals[machine_id].append(merged_iv)
            op_full_intervals[pair.op_id_a] = merged_iv

        # 4. Precedence constraints (within each job)
        for job in request.jobs:
            for i in range(len(job.operations) - 1):
                op_curr = job.operations[i]
                op_next = job.operations[i + 1]
                _, end_curr, _, _, _, _, _ = op_vars[op_curr.id]
                start_next, _, _, _, _, _, _ = op_vars[op_next.id]
                model.Add(end_curr <= start_next)

        # 5. Machine sequencing
        all_setup_arcs: list[tuple] = []  # (arc_lit, setup_dur, machine_id)
        if use_circuit:
            # Circuit mode: AddCircuit per machine handles sequencing + setup
            circuit_setup_intervals: list[cp_model.IntervalVar] = []
            start_vars_map = {oid: op_vars[oid][0] for oid in op_vars}
            end_vars_map = {oid: op_vars[oid][1] for oid in op_vars}

            for mid, jobs_list in machine_jobs.items():
                arcs, sivs = add_machine_circuit(
                    model=model,
                    machine_id=mid,
                    jobs=jobs_list,
                    start_vars=start_vars_map,
                    end_vars=end_vars_map,
                    prod_durations=prod_durations,
                    setup_matrix=request.setup_matrix,
                    default_setup=45,
                    horizon=horizon,
                )
                circuit_setup_intervals.extend(sivs)
                all_setup_arcs.extend(arcs)

            # SetupCrew on circuit-derived setup intervals
            constraints = request.constraints
            if constraints.setup_crew and circuit_setup_intervals:
                add_setup_crew_constraint(model, circuit_setup_intervals)
        else:
            # Legacy mode: NoOverlap per machine
            for machine_id, intervals in machine_intervals.items():
                if len(intervals) > 1:
                    model.AddNoOverlap(intervals)

            # SetupCrew on legacy fixed setup intervals
            constraints = request.constraints
            if constraints.setup_crew and setup_intervals:
                add_setup_crew_constraint(model, setup_intervals)

        # 6. Factory constraints (shared between modes)
        constraints = request.constraints

        if constraints.tool_timeline:
            apply_tool_timeline(model, op_tool_map, op_full_intervals, op_machine_map)

        if constraints.calco_timeline:
            apply_calco_timeline(model, op_calco_map, op_full_intervals)

        # 6b. Day capacity + shift boundary constraints
        self._add_day_shift_constraints(model, op_vars, twin_op_ids, horizon)

        # 7. Objective (with changeover penalty from circuit arcs)
        self._add_objective(model, request, op_vars, horizon, all_setup_arcs)

        # 7b. Warm-start with EDD heuristic
        if request.config.warm_start:
            heuristic_schedule = pick_best_heuristic(request)
            add_edd_hints(model, heuristic_schedule, op_vars)

        # 8. Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = request.config.time_limit_s
        solver.parameters.num_workers = request.config.num_workers

        status = solver.Solve(model)

        solve_time = time.monotonic() - start_time

        # 9. Map status
        status_map = {
            cp_model.OPTIMAL: "optimal",
            cp_model.FEASIBLE: "feasible",
            cp_model.INFEASIBLE: "infeasible",
            cp_model.MODEL_INVALID: "infeasible",
            cp_model.UNKNOWN: "timeout",
        }
        status_str = status_map.get(status, "timeout")

        # 10. Extract solution
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            result = self._extract_solution(solver, op_vars, request, solve_time, status_str, n_ops)
            if constraints.operator_pool:
                schedule_dicts = [
                    {
                        "op_id": s.op_id,
                        "machine_id": s.machine_id,
                        "start_min": s.start_min,
                        "end_min": s.end_min,
                    }
                    for s in result.schedule
                ]
                result.operator_warnings = analyse_operator_pool(schedule_dicts, request)
            return result
        else:
            return SolverResult(
                schedule=[],
                makespan_min=0,
                total_tardiness_min=0,
                weighted_tardiness=0.0,
                solver_used="cpsat",
                solve_time_s=round(solve_time, 3),
                status=status_str,
                objective_value=0.0,
                n_ops=n_ops,
            )

    def _add_objective(self, model, request, op_vars, horizon, setup_arcs=None):
        """Add objective function to the model.

        Objective structure (tardiness/weighted_tardiness modes):
          Minimize(1000 × Σ(tardiness) + 1 × Σ(earliness) + changeover)

        Earliness = max(0, due_date - end_var) penalises producing too early (JIT).
        Weight 1000:1 ensures tardiness always dominates — JIT never causes delays.
        Changeover is a tiebreaker (+1 per tool change arc in circuit mode).
        """
        objective = request.config.objective

        # Changeover penalty: sum of active arcs that represent tool changes
        has_changeover = False
        changeover_penalty = 0
        if setup_arcs:
            arc_lits = [arc_lit for (arc_lit, _, _) in setup_arcs if arc_lit is not None]
            if arc_lits:
                changeover_penalty = sum(arc_lits)
                has_changeover = True

        # JIT earliness penalty: push production closer to deadline
        earliness_vars = []
        for job in request.jobs:
            last_op = job.operations[-1]
            _, end_var, _, _, _, _, _ = op_vars[last_op.id]
            early = model.NewIntVar(0, horizon, f"early_{job.id}")
            model.Add(early >= job.due_date_min - end_var)
            model.Add(early >= 0)
            earliness_vars.append(early)
        earliness_term = sum(earliness_vars) if earliness_vars else 0

        if objective == "makespan":
            makespan_var = model.NewIntVar(0, horizon, "makespan")
            for op_id, (_, end_var, _, _, _, _, _) in op_vars.items():
                model.Add(makespan_var >= end_var)
            if has_changeover:
                model.Minimize(1000 * makespan_var + changeover_penalty)
            else:
                model.Minimize(makespan_var)

        elif objective == "tardiness":
            tardiness_vars = []
            for job in request.jobs:
                last_op = job.operations[-1]
                _, end_var, _, _, _, _, _ = op_vars[last_op.id]
                tardy = model.NewIntVar(0, horizon, f"tardy_{job.id}")
                model.Add(tardy >= end_var - job.due_date_min)
                model.Add(tardy >= 0)
                tardiness_vars.append(tardy)
            obj = 1000 * sum(tardiness_vars) + earliness_term
            if has_changeover:
                obj = obj + changeover_penalty
            model.Minimize(obj)

        else:  # weighted_tardiness
            weighted_tardy_terms = []
            for job in request.jobs:
                last_op = job.operations[-1]
                _, end_var, _, _, _, _, _ = op_vars[last_op.id]
                tardy = model.NewIntVar(0, horizon, f"tardy_{job.id}")
                model.Add(tardy >= end_var - job.due_date_min)
                model.Add(tardy >= 0)
                scaled_weight = int(job.weight * 100)
                weighted_tardy = model.NewIntVar(0, horizon * scaled_weight, f"wtardy_{job.id}")
                model.Add(weighted_tardy == tardy * scaled_weight)
                weighted_tardy_terms.append(weighted_tardy)
            obj = 1000 * sum(weighted_tardy_terms) + earliness_term
            if has_changeover:
                obj = obj + changeover_penalty
            model.Minimize(obj)

    def _add_day_shift_constraints(self, model, op_vars, twin_op_ids, horizon):
        """Day capacity + shift boundary constraints.

        Short ops (<=DAY_CAP): must fit within a single day.
        Short ops (<=SHIFT_LEN): must fit within one shift (X or Y).
        Large ops (>DAY_CAP): allowed to span days (no day boundary constraint).

        Uses decomposition: start_var = day_var × DAY_CAP + start_in_day.
        """
        DAY_CAP = 1020
        SHIFT_LEN = 510
        n_days = horizon // DAY_CAP

        for op_id, (start_var, end_var, _, _, _, job, op) in op_vars.items():
            suffix = f"_{op_id}"

            # Max possible size (production + setup)
            max_size = op.duration_min + max(op.setup_min, 90)

            # Only apply day/shift constraints if op can fit within a day
            if max_size <= DAY_CAP:
                # Day decomposition: start = day × 1020 + offset
                day_var = model.NewIntVar(0, n_days, f"day{suffix}")
                start_in_day = model.NewIntVar(0, DAY_CAP - 1, f"sid{suffix}")
                model.Add(start_var == day_var * DAY_CAP + start_in_day)

                size_var = model.NewIntVar(0, DAY_CAP, f"dsz{suffix}")
                model.Add(size_var == end_var - start_var)

                # ── DAY BOUNDARY: op must not cross into next day ──
                model.Add(start_in_day + size_var <= DAY_CAP)

                # ── SHIFT BOUNDARY: short ops must fit in one shift ──
                if op.duration_min <= SHIFT_LEN:
                    fits = model.NewBoolVar(f"fits{suffix}")
                    model.Add(size_var <= SHIFT_LEN).OnlyEnforceIf(fits)
                    model.Add(size_var > SHIFT_LEN).OnlyEnforceIf(fits.Not())

                    in_x = model.NewBoolVar(f"inx{suffix}")
                    model.Add(start_in_day + size_var <= SHIFT_LEN).OnlyEnforceIf([fits, in_x])
                    model.Add(start_in_day >= SHIFT_LEN).OnlyEnforceIf([fits, in_x.Not()])
            # Large ops (>DAY_CAP): no day/shift boundary — they span multiple days.
            # The NoOverlap/Circuit constraint still prevents machine conflicts.

    def _extract_solution(
        self, solver, op_vars, request, solve_time, status_str, n_ops
    ) -> SolverResult:
        """Extract solution from solved model."""
        schedule = []
        job_due_dates = {j.id: j.due_date_min for j in request.jobs}
        job_weights = {j.id: j.weight for j in request.jobs}

        op_to_job = {}
        for job in request.jobs:
            for op in job.operations:
                op_to_job[op.id] = job.id

        twin_lookup: dict[str, str] = {}
        for pair in request.twin_pairs:
            twin_lookup[pair.op_id_a] = pair.op_id_b
            twin_lookup[pair.op_id_b] = pair.op_id_a

        makespan = 0
        total_tardiness = 0
        weighted_tardiness = 0.0

        for op_id, (start_var, end_var, _, _, _, job, op) in op_vars.items():
            start_val = solver.Value(start_var)
            end_val = solver.Value(end_var)
            job_id = op_to_job[op_id]
            due_date = job_due_dates[job_id]

            makespan = max(makespan, end_val)

            is_last_op = op_id == job.operations[-1].id
            tardiness = max(0, end_val - due_date) if is_last_op else 0

            if is_last_op:
                total_tardiness += tardiness
                weighted_tardiness += job_weights[job_id] * tardiness

            # In circuit mode, actual setup is determined by sequence.
            # Report setup_min from the original op spec (for reference).
            DAY_CAP_LOCAL = 1020
            start_in_day = start_val % DAY_CAP_LOCAL
            op_shift = "X" if start_in_day < 510 else "Y"

            schedule.append(
                ScheduledOp(
                    op_id=op_id,
                    job_id=job_id,
                    machine_id=op.machine_id,
                    tool_id=op.tool_id,
                    start_min=start_val,
                    end_min=end_val,
                    setup_min=op.setup_min,
                    is_tardy=tardiness > 0 if is_last_op else False,
                    tardiness_min=tardiness,
                    is_twin_production=op_id in twin_lookup,
                    twin_partner_op_id=twin_lookup.get(op_id),
                    shift=op_shift,
                )
            )

        schedule.sort(key=lambda s: (s.machine_id, s.start_min))

        return SolverResult(
            schedule=schedule,
            makespan_min=makespan,
            total_tardiness_min=total_tardiness,
            weighted_tardiness=round(weighted_tardiness, 2),
            solver_used="cpsat",
            solve_time_s=round(solve_time, 3),
            status=status_str,
            objective_value=float(solver.ObjectiveValue()),
            n_ops=n_ops,
        )
