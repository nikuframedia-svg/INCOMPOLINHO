# CP-SAT Constraint Builders — Incompol factory constraints
# SetupCrew, ToolTimeline, CalcoTimeline, OperatorPool (advisory), Twin co-production

from __future__ import annotations

import logging
from collections import defaultdict

from ortools.sat.python import cp_model

from .schemas import SolverRequest, TwinPairInput

logger = logging.getLogger(__name__)


def add_setup_crew_constraint(
    model: cp_model.CpModel,
    setup_intervals: list[cp_model.IntervalVar],
) -> None:
    """SetupCrew: max 1 setup simultaneous across entire factory."""
    if len(setup_intervals) > 1:
        model.AddNoOverlap(setup_intervals)


def build_tool_intervals(
    op_tool_map: dict[str, str],
    op_full_intervals: dict[str, cp_model.IntervalVar],
    op_machine_map: dict[str, str],
) -> dict[str, list[cp_model.IntervalVar]]:
    """Group intervals by tool_id for tools used on 2+ different machines."""
    tool_machines: dict[str, set[str]] = defaultdict(set)
    tool_intervals: dict[str, list[cp_model.IntervalVar]] = defaultdict(list)

    for op_id, tool_id in op_tool_map.items():
        if op_id not in op_full_intervals:
            continue  # Twin ops have no individual interval
        machine_id = op_machine_map[op_id]
        tool_machines[tool_id].add(machine_id)
        tool_intervals[tool_id].append(op_full_intervals[op_id])

    # Only return tools that span 2+ machines (cross-machine constraint)
    return {
        tid: intervals for tid, intervals in tool_intervals.items() if len(tool_machines[tid]) > 1
    }


def apply_tool_timeline(
    model: cp_model.CpModel,
    op_tool_map: dict[str, str],
    op_full_intervals: dict[str, cp_model.IntervalVar],
    op_machine_map: dict[str, str],
) -> None:
    """Apply ToolTimeline NoOverlap for tools on multiple machines."""
    groups = build_tool_intervals(op_tool_map, op_full_intervals, op_machine_map)
    for _tool_id, intervals in groups.items():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)


def build_calco_intervals(
    op_calco_map: dict[str, str | None],
    op_full_intervals: dict[str, cp_model.IntervalVar],
) -> dict[str, list[cp_model.IntervalVar]]:
    """Group intervals by calco_code (ignoring None)."""
    calco_intervals: dict[str, list[cp_model.IntervalVar]] = defaultdict(list)

    for op_id, calco_code in op_calco_map.items():
        if calco_code is not None and op_id in op_full_intervals:
            calco_intervals[calco_code].append(op_full_intervals[op_id])

    return {cid: ivs for cid, ivs in calco_intervals.items() if len(ivs) > 1}


def apply_calco_timeline(
    model: cp_model.CpModel,
    op_calco_map: dict[str, str | None],
    op_full_intervals: dict[str, cp_model.IntervalVar],
) -> None:
    """CalcoTimeline: calço on 1 machine at a time (no same-machine exception)."""
    groups = build_calco_intervals(op_calco_map, op_full_intervals)
    for _calco_code, intervals in groups.items():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)


def analyse_operator_pool(
    schedule: list[dict],
    request: SolverRequest,
) -> list[dict]:
    """Post-solve advisory: detect operator pool overloads per shift window.

    Returns list of warning dicts (never blocks the schedule).
    """
    shifts = request.shifts
    if not shifts.operators_by_machine_shift:
        return []

    # Build op lookup for operators count
    op_operators: dict[str, int] = {}
    for job in request.jobs:
        for op in job.operations:
            op_operators[op.id] = op.operators

    warnings = []
    # Check each shift window
    for machine_id, shift_caps in shifts.operators_by_machine_shift.items():
        for shift_name, capacity in shift_caps.items():
            # Determine shift time window (within each day)
            if shift_name == "X":
                window_start = shifts.shift_x_start
                window_end = shifts.shift_change
            elif shift_name == "Y":
                window_start = shifts.shift_change
                window_end = shifts.shift_y_end
            else:
                continue

            # Sum operators in this window for this machine
            for entry in schedule:
                if entry["machine_id"] != machine_id:
                    continue
                # Check overlap with shift window (modulo day)
                op_start_in_day = entry["start_min"] % 1440
                op_end_in_day = entry["end_min"] % 1440
                if op_end_in_day <= op_start_in_day:
                    op_end_in_day = 1440  # wraps midnight

                if op_start_in_day < window_end and op_end_in_day > window_start:
                    ops_needed = op_operators.get(entry["op_id"], 1)
                    if ops_needed > capacity:
                        warnings.append(
                            {
                                "type": "OPERATOR_CAPACITY_WARNING",
                                "machine_id": machine_id,
                                "shift": shift_name,
                                "op_id": entry["op_id"],
                                "operators_needed": ops_needed,
                                "capacity": capacity,
                            }
                        )

    return warnings


def build_twin_merged_intervals(
    model: cp_model.CpModel,
    twin_pairs: list[TwinPairInput],
    op_vars: dict[str, tuple],
    horizon: int,
) -> tuple[dict[str, cp_model.IntervalVar], list[str]]:
    """Build merged intervals for twin pairs.

    For each twin pair:
    - Both ops share the same start time
    - Machine interval = max(dur_a, dur_b) + setup (shared)
    - Returns merged_interval per pair (to replace individuals in machine NoOverlap)

    op_vars: op_id → (start_var, end_var, setup_iv, prod_iv, full_iv, job, op)

    Returns: (dict of pair_key → merged_interval_var, list of warning strings)
    Also modifies model with start equality constraints.
    """
    merged = {}
    warnings: list[str] = []
    for pair in twin_pairs:
        if pair.op_id_a not in op_vars or pair.op_id_b not in op_vars:
            missing = []
            if pair.op_id_a not in op_vars:
                missing.append(pair.op_id_a)
            if pair.op_id_b not in op_vars:
                missing.append(pair.op_id_b)
            msg = (
                f"Twin pair ({pair.op_id_a}, {pair.op_id_b}) skipped: "
                f"op(s) {missing} not found in op_vars"
            )
            logger.warning(msg)
            warnings.append(msg)
            continue

        start_a, end_a, _, _, _, _, op_a = op_vars[pair.op_id_a]
        start_b, end_b, _, _, _, _, op_b = op_vars[pair.op_id_b]

        # Both must start at same time
        model.Add(start_a == start_b)

        # Merged duration = max(dur_a, dur_b) + max(setup_a, setup_b) (one setup shared)
        dur_a = op_a.duration_min
        dur_b = op_b.duration_min
        setup = max(op_a.setup_min, op_b.setup_min)
        merged_duration = max(dur_a, dur_b) + setup

        pair_key = f"twin_{pair.op_id_a}_{pair.op_id_b}"
        merged_start = start_a  # shared start
        merged_end = model.NewIntVar(0, horizon, f"twin_end_{pair_key}")
        model.Add(merged_end == merged_start + merged_duration)

        # Constrain each twin op's end_var to the merged end
        # (so tardiness is computed from the shared end time)
        model.Add(end_a == merged_end)
        model.Add(end_b == merged_end)

        merged_iv = model.NewIntervalVar(
            merged_start, merged_duration, merged_end, f"twin_iv_{pair_key}"
        )
        merged[pair_key] = (merged_iv, pair.machine_id, pair)

    return merged, warnings
