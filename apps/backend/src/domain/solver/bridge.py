"""Bridge — EngineData ↔ SolverRequest / SolverResult ↔ Block[].

Converts the scheduling domain model (EngineData) into the CP-SAT solver
input (SolverRequest) and maps solver output back to production blocks.
"""

from __future__ import annotations

import math
from typing import Any

from ..scheduling.constants import DAY_CAP, DEFAULT_OEE
from ..scheduling.types import Block, EngineData, EOp, ETool, TwinOutput
from .schemas import (
    ConstraintConfigInput,
    JobInput,
    MachineInput,
    OperationInput,
    ScheduledOp,
    SolverConfig,
    SolverRequest,
    SolverResult,
    TwinPairInput,
)

# ── Shift boundaries within a day (minutes from day start) ──
SHIFT_LEN = 510  # Each shift is 510 min (8.5h)


# ── EngineData → SolverRequest ──────────────────────────────────


def engine_data_to_solver_request(
    engine_data: EngineData,
    settings: dict[str, Any] | None = None,
) -> SolverRequest:
    """Convert EngineData to a SolverRequest for the CP-SAT solver.

    Each EOp.d[i] > 0 becomes a separate JobInput (one order = one job).
    Twin pairs from engine_data.twin_groups are mapped to TwinPairInput.
    """
    settings = settings or {}
    oee = settings.get("oee", DEFAULT_OEE)

    # Build workday index mapping: calendar day → workday rank
    # workdays is list[bool], True = workday
    workday_ranks = _build_workday_ranks(engine_data.workdays)
    workday_indices = [i for i, wd in enumerate(engine_data.workdays) if wd]
    n_workdays = len(workday_indices)

    # Pre-start offset (synthetic days before ISOP start)
    pre_start = engine_data.pre_start_days or 0

    jobs: list[JobInput] = []
    # Track op_id → list of (day_idx, job_id) for twin matching
    op_day_jobs: dict[str, list[tuple[int, str]]] = {}

    for op in engine_data.ops:
        tool = engine_data.tool_map.get(op.t)
        if tool is None:
            continue

        pH = tool.pH or op.pH or 100
        setup_min = max(1, round(tool.sH * 60))
        operators = tool.op or 1
        calco_code = tool.calco
        eco_lot = tool.lt or 0

        day_jobs: list[tuple[int, str]] = []

        for day_idx, qty in enumerate(op.d):
            if qty <= 0:
                continue

            # Apply eco lot rounding (only inflate, never deflate)
            effective_qty = qty
            if eco_lot > 0:
                effective_qty = math.ceil(qty / eco_lot) * eco_lot

            # Duration from quantity, pH, OEE
            duration_min = max(1, math.ceil((effective_qty / (pH * oee)) * 60))

            # Map calendar day to workday rank for due date
            cal_day = day_idx + pre_start
            if cal_day < len(workday_ranks):
                wk_rank = workday_ranks[cal_day]
            else:
                wk_rank = max(0, n_workdays - 1)

            # Due date = end of that workday (in solver minutes)
            due_date_min = (wk_rank + 1) * DAY_CAP

            job_id = f"{op.id}_d{day_idx}"
            jobs.append(
                JobInput(
                    id=job_id,
                    sku=op.sku,
                    due_date_min=due_date_min,
                    weight=1.0,
                    operations=[
                        OperationInput(
                            id=job_id,
                            machine_id=op.m,
                            tool_id=op.t,
                            duration_min=duration_min,
                            setup_min=setup_min,
                            operators=operators,
                            calco_code=calco_code,
                        )
                    ],
                )
            )
            day_jobs.append((day_idx, job_id))

        if day_jobs:
            op_day_jobs[op.id] = day_jobs

    # Build machines
    machines = [MachineInput(id=m.id) for m in engine_data.machines]

    # Build twin pairs from twin_groups
    twin_pairs = _build_twin_pairs(engine_data, op_day_jobs)

    # Build setup matrix (tool-based: same tool = 0 setup, different = default)
    setup_matrix = _build_setup_matrix(engine_data)

    # Solver config
    config = SolverConfig(
        time_limit_s=settings.get("timeLimitS", 60),
        objective=settings.get("objective", "weighted_tardiness"),
        num_workers=settings.get("numWorkers", 4),
        use_circuit=settings.get("useCircuit", True),
        objective_mode=settings.get("objectiveMode", "single"),
        warm_start=settings.get("warmStart", True),
    )

    return SolverRequest(
        jobs=jobs,
        machines=machines,
        setup_matrix=setup_matrix,
        config=config,
        twin_pairs=twin_pairs,
        constraints=ConstraintConfigInput(
            setup_crew=settings.get("setupCrew", True),
            tool_timeline=settings.get("toolTimeline", True),
            calco_timeline=settings.get("calcoTimeline", True),
            operator_pool=settings.get("operatorPool", False),
        ),
        workdays=list(range(n_workdays)),
    )


def _build_workday_to_calendar(workdays: list[bool]) -> list[int]:
    """Map workday rank → calendar day index.

    Returns a list where index = workday rank, value = calendar day index.
    E.g. if calendar is [True, True, False, False, True], returns [0, 1, 4].
    """
    return [i for i, wd in enumerate(workdays) if wd]


def _build_workday_ranks(workdays: list[bool]) -> list[int]:
    """Map calendar day index → workday rank (0-based).

    Non-workdays get the rank of the previous workday (or 0).
    """
    ranks: list[int] = []
    rank = -1
    for wd in workdays:
        if wd:
            rank += 1
        ranks.append(max(rank, 0))
    return ranks


def _build_twin_pairs(
    engine_data: EngineData,
    op_day_jobs: dict[str, list[tuple[int, str]]],
) -> list[TwinPairInput]:
    """Build TwinPairInput list from twin_groups.

    Matches jobs by day index: twin op1 day 5 ↔ twin op2 day 5.
    If one twin has a day the other doesn't, skip that day.
    """
    pairs: list[TwinPairInput] = []

    for tg in engine_data.twin_groups:
        jobs_a = {d: jid for d, jid in op_day_jobs.get(tg.op_id1, [])}
        jobs_b = {d: jid for d, jid in op_day_jobs.get(tg.op_id2, [])}

        # Match by shared demand days
        for day_idx in sorted(set(jobs_a.keys()) & set(jobs_b.keys())):
            pairs.append(
                TwinPairInput(
                    op_id_a=jobs_a[day_idx],
                    op_id_b=jobs_b[day_idx],
                    machine_id=tg.machine,
                    tool_id=tg.tool,
                )
            )

    return pairs


def _build_setup_matrix(engine_data: EngineData) -> dict[str, dict[str, int]]:
    """Build tool-to-tool setup matrix.

    Same tool → 0 setup. Different tools → default setup (45 min).
    """
    tool_ids = list(engine_data.tool_map.keys())
    if not tool_ids:
        return {}

    matrix: dict[str, dict[str, int]] = {}
    for t1 in tool_ids:
        row: dict[str, int] = {}
        for t2 in tool_ids:
            row[t2] = 0 if t1 == t2 else 45
        matrix[t1] = row
    return matrix


# ── SolverResult → Block[] ───────────────────────────────────────


def solver_result_to_blocks(
    result: SolverResult,
    engine_data: EngineData,
) -> list[Block]:
    """Convert SolverResult.schedule → list[Block] for the frontend.

    Maps each ScheduledOp back to its original EOp for metadata.
    Solver operates in workday-indexed time — we reverse-map back to calendar indices.
    """
    if not result.schedule:
        return []

    # Build workday rank → calendar day index reverse mapping
    workday_to_calendar = _build_workday_to_calendar(engine_data.workdays)

    # Build lookups
    op_lookup = {op.id: op for op in engine_data.ops}
    tool_lookup = engine_data.tool_map

    # Parse job_id pattern: "{op_id}_d{day_idx}"
    # Also build twin partner lookup for co-production output
    twin_partner: dict[str, str] = {}
    for sop in result.schedule:
        if sop.twin_partner_op_id:
            twin_partner[sop.op_id] = sop.twin_partner_op_id

    blocks: list[Block] = []

    for sop in result.schedule:
        # Parse original op_id and day_idx from job_id
        orig_op_id, day_idx = _parse_job_id(sop.job_id)
        eop = op_lookup.get(orig_op_id)
        tool = tool_lookup.get(sop.tool_id)

        if eop is None:
            continue

        # Get demand qty for this day
        qty = eop.d[day_idx] if day_idx < len(eop.d) else 0

        # Compute day and shift from solver time
        # Solver time is workday-indexed — reverse-map to calendar day
        workday_rank = sop.start_min // DAY_CAP
        if workday_to_calendar and workday_rank < len(workday_to_calendar):
            block_day_idx = workday_to_calendar[workday_rank]
        else:
            block_day_idx = workday_rank  # fallback: no weekends in calendar
        start_in_day = sop.start_min % DAY_CAP
        shift = "X" if start_in_day < SHIFT_LEN else "Y"

        # Build twin outputs if this is a twin production
        outputs = None
        if sop.is_twin_production and sop.twin_partner_op_id:
            partner_op_id, partner_day = _parse_job_id(sop.twin_partner_op_id)
            partner_eop = op_lookup.get(partner_op_id)
            if partner_eop:
                partner_qty = (
                    partner_eop.d[partner_day] if partner_day < len(partner_eop.d) else 0
                )
                outputs = [
                    TwinOutput(op_id=orig_op_id, sku=eop.sku, qty=qty),
                    TwinOutput(op_id=partner_op_id, sku=partner_eop.sku, qty=partner_qty),
                ]

        # EDD day: convert due_date_min back to calendar day
        edd_day = day_idx

        block = Block(
            op_id=orig_op_id,
            tool_id=sop.tool_id,
            sku=eop.sku,
            nm=eop.nm,
            machine_id=sop.machine_id,
            orig_m=eop.m,
            day_idx=block_day_idx,
            edd_day=edd_day,
            qty=qty,
            prod_min=sop.end_min - sop.start_min - sop.setup_min,
            setup_min=sop.setup_min,
            operators=tool.op if tool else 1,
            start_min=sop.start_min,
            end_min=sop.end_min,
            setup_s=sop.start_min,
            setup_e=sop.start_min + sop.setup_min,
            type="ok",
            shift=shift,
            blocked=sop.is_tardy,
            has_alt=_has_alt(tool),
            alt_m=tool.alt if tool and tool.alt != "-" else None,
            mp=tool.mp if tool else None,
            stk=eop.stk or 0,
            lt=tool.lt if tool else 0,
            atr=eop.atr,
            is_twin_production=sop.is_twin_production,
            co_production_group_id=(
                f"twin_{sop.op_id}_{sop.twin_partner_op_id}" if sop.is_twin_production else None
            ),
            outputs=outputs,
        )
        blocks.append(block)

    # Sort by machine, then start time
    blocks.sort(key=lambda b: (b.machine_id, b.start_min))
    return blocks


def _parse_job_id(job_id: str) -> tuple[str, int]:
    """Parse job_id format '{op_id}_d{day_idx}' → (op_id, day_idx)."""
    parts = job_id.rsplit("_d", 1)
    if len(parts) == 2:
        try:
            return parts[0], int(parts[1])
        except ValueError:
            pass
    return job_id, 0


def _has_alt(tool: ETool | None) -> bool:
    """Check if tool has a valid alternative machine."""
    if tool is None:
        return False
    return tool.alt is not None and tool.alt != "-" and tool.alt != ""
