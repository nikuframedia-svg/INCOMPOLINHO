# ATCS Heuristic Fallback — for >200 operations
# Conforme CLAUDE.md Camada 1: ATCS client-side (<10ms)
# Priority(j) = (w/p) · exp(-slack/(k1·p̄)) · exp(-setup/(k2·s̄))

import math
import time
from collections import defaultdict

from .schemas import ScheduledOp, SolverRequest, SolverResult


class HeuristicFallback:
    """
    ATCS (Apparent Tardiness Cost with Setups) heuristic.
    Used as fallback when problem is too large for CP-SAT (>200 ops).
    """

    def solve(self, request: SolverRequest) -> SolverResult:
        start_time = time.monotonic()

        if not request.jobs:
            return SolverResult(
                schedule=[],
                makespan_min=0,
                total_tardiness_min=0,
                weighted_tardiness=0.0,
                solver_used="heuristic",
                solve_time_s=0.0,
                status="optimal",
                objective_value=0.0,
                n_ops=0,
            )

        # Flatten all ops with job context
        ops_with_context = []
        for job in request.jobs:
            for i, op in enumerate(job.operations):
                ops_with_context.append(
                    {
                        "op": op,
                        "job": job,
                        "op_idx": i,
                        "is_last": i == len(job.operations) - 1,
                    }
                )

        n_ops = len(ops_with_context)

        # Calculate average processing time and setup time
        durations = [oc["op"].duration_min for oc in ops_with_context]
        setups = [oc["op"].setup_min for oc in ops_with_context]
        p_bar = sum(durations) / len(durations) if durations else 1
        s_bar = sum(setups) / len(setups) if setups else 1
        s_bar = max(s_bar, 1)  # Avoid division by zero

        # ATCS parameters (k1=0.5, k2=0.5 as defaults)
        k1, k2 = 0.5, 0.5

        # Group ops by machine
        machine_ops = defaultdict(list)
        for oc in ops_with_context:
            machine_ops[oc["op"].machine_id].append(oc)

        # Track job completion times (for precedence)
        job_ready = defaultdict(int)  # job_id → earliest available time for next op
        schedule = []

        # Machine current time and last tool
        machine_time = {m.id: 0 for m in request.machines}
        machine_last_tool = {m.id: None for m in request.machines}

        # Process each machine independently
        for machine_id, m_ops in machine_ops.items():
            if machine_id not in machine_time:
                machine_time[machine_id] = 0
                machine_last_tool[machine_id] = None

            remaining = list(m_ops)

            while remaining:
                current_time = machine_time[machine_id]

                # Filter ops whose predecessors are done
                ready = []
                for oc in remaining:
                    job_id = oc["job"].id
                    op_idx = oc["op_idx"]
                    if op_idx == 0 or job_ready.get(f"{job_id}_{op_idx - 1}", 0) <= current_time:
                        ready.append(oc)

                if not ready:
                    # Advance time to earliest predecessor completion
                    min_ready = float("inf")
                    for oc in remaining:
                        job_id = oc["job"].id
                        op_idx = oc["op_idx"]
                        if op_idx > 0:
                            pred_key = f"{job_id}_{op_idx - 1}"
                            min_ready = min(min_ready, job_ready.get(pred_key, 0))
                    machine_time[machine_id] = (
                        int(min_ready) if min_ready < float("inf") else current_time + 1
                    )
                    continue

                # Calculate ATCS priority for each ready op
                best_op = None
                best_priority = -float("inf")

                for oc in ready:
                    op = oc["op"]
                    job = oc["job"]
                    p = max(op.duration_min, 1)
                    w = job.weight
                    d = job.due_date_min

                    # Slack
                    slack = max(d - current_time - p, 0)

                    # Setup penalty
                    last_tool = machine_last_tool.get(machine_id)
                    setup = op.setup_min if last_tool != op.tool_id else 0

                    # ATCS formula
                    wp = w / p
                    slack_term = math.exp(-max(slack, 0) / (k1 * p_bar)) if p_bar > 0 else 1
                    setup_term = math.exp(-setup / (k2 * s_bar)) if s_bar > 0 else 1

                    priority = wp * slack_term * setup_term

                    if priority > best_priority:
                        best_priority = priority
                        best_op = oc

                if best_op is None:
                    break

                # Schedule the best op
                op = best_op["op"]
                job = best_op["job"]
                op_idx = best_op["op_idx"]

                # Consider job readiness (predecessor must be done)
                earliest = machine_time[machine_id]
                if op_idx > 0:
                    pred_key = f"{job.id}_{op_idx - 1}"
                    earliest = max(earliest, job_ready.get(pred_key, 0))

                # Setup time
                last_tool = machine_last_tool.get(machine_id)
                setup_time = op.setup_min if last_tool != op.tool_id else 0

                start = earliest + setup_time
                end = start + op.duration_min

                # Tardiness (only for last op of job)
                tardiness = max(0, end - job.due_date_min) if best_op["is_last"] else 0

                schedule.append(
                    ScheduledOp(
                        op_id=op.id,
                        job_id=job.id,
                        machine_id=machine_id,
                        tool_id=op.tool_id,
                        start_min=start,
                        end_min=end,
                        setup_min=setup_time,
                        is_tardy=tardiness > 0,
                        tardiness_min=tardiness,
                    )
                )

                # Update state
                machine_time[machine_id] = end
                machine_last_tool[machine_id] = op.tool_id
                job_ready[f"{job.id}_{op_idx}"] = end
                remaining.remove(best_op)

        # Calculate KPIs
        makespan = max((s.end_min for s in schedule), default=0)
        total_tardiness = sum(s.tardiness_min for s in schedule)
        weighted_tardiness = sum(
            next(j.weight for j in request.jobs if j.id == s.job_id) * s.tardiness_min
            for s in schedule
            if s.tardiness_min > 0
        )

        solve_time = time.monotonic() - start_time

        # Sort by machine + start
        schedule.sort(key=lambda s: (s.machine_id, s.start_min))

        return SolverResult(
            schedule=schedule,
            makespan_min=makespan,
            total_tardiness_min=total_tardiness,
            weighted_tardiness=round(weighted_tardiness, 2),
            solver_used="heuristic",
            solve_time_s=round(solve_time, 3),
            status="feasible",
            objective_value=float(weighted_tardiness),
            n_ops=n_ops,
        )
