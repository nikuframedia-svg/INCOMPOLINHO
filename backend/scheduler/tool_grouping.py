"""Phase 2 — Tool Grouping: Spec 02 v6 §4.

Groups Lots by physical setup identity and machine into ToolRuns.
1 setup covers all lots in the same adjusted reference group. Lots are sequential.

Fix 1: Lots within each ToolRun are ALWAYS sorted by EDD.

Splits runs on two criteria:
  1. EDD gap > MAX_EDD_GAP between consecutive lots
  2. Cumulative production time > MAX_RUN_DAYS * DAY_CAP
"""

from __future__ import annotations

from collections import defaultdict

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP, MAX_EDD_GAP, MAX_RUN_DAYS
from backend.scheduler.jit_policy import earliest_allowed_start
from backend.scheduler.priority import lot_priority_key
from backend.scheduler.setup_identity import SetupIdentity, lot_setup_identity
from backend.scheduler.types import Lot, ToolRun


def create_tool_runs(
    lots: list[Lot],
    max_edd_gap: int = MAX_EDD_GAP,
    audit_logger: object | None = None,
    config: FactoryConfig | None = None,
    release_holidays: set[int] | None = None,
) -> list[ToolRun]:
    """Group lots by setup identity and machine into ToolRuns, with splitting."""
    day_cap = config.day_capacity_min if config else DAY_CAP

    groups: dict[tuple[SetupIdentity, str], list[Lot]] = defaultdict(list)

    for lot in lots:
        key = (lot_setup_identity(lot), lot.machine_id)
        groups[key].append(lot)

    runs: list[ToolRun] = []
    next_run_index: dict[tuple[str, str], int] = defaultdict(int)
    for (setup_identity, machine), group_lots in sorted(groups.items()):
        tool = setup_identity[0]
        group_lots.sort(key=lot_priority_key)
        gap = config.max_edd_gap if config else max_edd_gap
        max_run = config.max_run_days if config else MAX_RUN_DAYS
        span = config.max_edd_span if config else 20
        sub_runs = _split_by_edd_gap(
            group_lots,
            gap,
            max_run,
            day_cap=day_cap,
            max_span=span,
            release_holidays=release_holidays,
        )

        for sub_lots in sub_runs:
            idx = next_run_index[(tool, machine)]
            next_run_index[(tool, machine)] += 1
            setup = max(lot.setup_min for lot in sub_lots)
            total_prod = sum(lot.prod_min for lot in sub_lots)

            runs.append(
                ToolRun(
                    id=f"run_{tool}_{machine}_{idx}",
                    tool_id=tool,
                    machine_id=machine,
                    alt_machine_id=sub_lots[0].alt_machine_id,
                    lots=sub_lots,
                    setup_min=setup,
                    total_prod_min=total_prod,
                    total_min=setup + total_prod,
                    edd=sub_lots[0].edd,
                    target_start_day=_run_target_start(sub_lots),
                    production_due_day=min(
                        (
                            lot.production_due_day
                            if lot.production_due_day is not None
                            else lot.edd
                            for lot in sub_lots
                        ),
                        default=sub_lots[0].edd,
                    ),
                )
            )

    before_count = len(runs)
    runs = _split_infeasible_runs(runs, day_cap=day_cap)
    if config and config.forced_run_splits:
        runs = _split_forced_runs(runs, config.forced_run_splits)

    # Log infeasibility splits
    if audit_logger and len(runs) > before_count:
        for run in runs:
            if run.id.endswith("_early"):
                original_id = run.id.removesuffix("_early")
                late = next((r for r in runs if r.id == f"{original_id}_late"), None)
                audit_logger.log_split(
                    original_id,
                    "infeasible",
                    len(run.lots),
                    len(late.lots) if late else 0,
                    total_min=run.total_min + (late.total_min if late else 0),
                    capacity=(run.edd + 1) * day_cap,
                )

    return runs


def _split_forced_runs(
    runs: list[ToolRun],
    split_positions_by_run_id: dict[str, list[int]],
) -> list[ToolRun]:
    """Apply explicit CPO/LNS split positions to selected runs.

    Positions are lot indexes in the run's EDD-sorted lot list. Invalid,
    duplicate, or degenerate positions are ignored.
    """

    if not split_positions_by_run_id:
        return runs

    out: list[ToolRun] = []
    for run in runs:
        positions = _normalise_split_positions(
            split_positions_by_run_id.get(run.id, []),
            len(run.lots),
        )
        if not positions:
            out.append(run)
            continue

        last = 0
        for idx, pos in enumerate([*positions, len(run.lots)]):
            sub_lots = run.lots[last:pos]
            last = pos
            if sub_lots:
                out.append(_make_run(run, sub_lots, f"{run.id}_lns{idx}"))

    return out


def _normalise_split_positions(raw_positions: object, lot_count: int) -> list[int]:
    if lot_count <= 1:
        return []
    if isinstance(raw_positions, str | bytes):
        candidates = [raw_positions]
    else:
        try:
            candidates = list(raw_positions)  # type: ignore[arg-type]
        except TypeError:
            candidates = [raw_positions]

    positions: set[int] = set()
    for raw in candidates:
        try:
            pos = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 < pos < lot_count:
            positions.add(pos)
    return sorted(positions)


def _split_by_edd_gap(
    lots: list[Lot],
    max_gap: int,
    max_run_days: int = MAX_RUN_DAYS,
    day_cap: int = DAY_CAP,
    max_span: int = 20,
    release_holidays: set[int] | None = None,
) -> list[list[Lot]]:
    """Split sorted lots by release floor, EDD gap, span, and duration.

    A ToolRun is non-preemptive and contains no deliberate idle time. Lots
    whose simulated material-release floors differ therefore cannot share a
    run: the later lot would delay already-released production. This was the
    structural source of apparently unexplained four-day starts and empty
    machine time inside the five-workday window.
    """
    if not lots:
        return []
    if len(lots) <= 1:
        return [lots]

    max_prod = max_run_days * day_cap
    sub_runs: list[list[Lot]] = [[lots[0]]]
    cum_prod = lots[0].prod_min

    for lot in lots[1:]:
        previous = sub_runs[-1][-1]
        prev_edd = sub_runs[-1][-1].edd
        first_edd = sub_runs[-1][0].edd
        gap = lot.edd - prev_edd
        span = lot.edd - first_edd
        duration_split = cum_prod + lot.prod_min > max_prod
        release_split = bool(
            release_holidays is not None
            and max(0, earliest_allowed_start(lot, release_holidays))
            != max(0, earliest_allowed_start(previous, release_holidays))
        )

        if release_split or gap > max_gap or duration_split or span > max_span:
            sub_runs.append([lot])
            cum_prod = lot.prod_min
        else:
            sub_runs[-1].append(lot)
            cum_prod += lot.prod_min

    return sub_runs


def _make_run(original: ToolRun, lots: list[Lot], run_id: str) -> ToolRun:
    """Create a new ToolRun from a subset of lots."""
    setup = max(lot.setup_min for lot in lots)
    total_prod = sum(lot.prod_min for lot in lots)
    return ToolRun(
        id=run_id,
        tool_id=original.tool_id,
        machine_id=original.machine_id,
        alt_machine_id=original.alt_machine_id,
        lots=lots,
        setup_min=setup,
        total_prod_min=total_prod,
        total_min=setup + total_prod,
        edd=lots[0].edd,
        target_start_day=_run_target_start(lots),
        production_due_day=min(
            (
                lot.production_due_day
                if lot.production_due_day is not None
                else lot.edd
                for lot in lots
            ),
            default=lots[0].edd,
        ),
    )


def _run_target_start(lots: list[Lot]) -> int | None:
    targets = [lot.target_start_day for lot in lots if lot.target_start_day is not None]
    return min(targets) if targets else None


def _split_infeasible_runs(runs: list[ToolRun], day_cap: int = DAY_CAP) -> list[ToolRun]:
    """Split runs where total_min exceeds capacity available by their EDD.

    If a run needs more time than (edd+1)*day_cap, the early-EDD lots are
    separated into their own run so they can potentially be routed to an
    alt machine or scheduled earlier.
    """
    result: list[ToolRun] = []
    for run in runs:
        capacity_by_edd = (run.edd + 1) * day_cap
        if run.total_min <= capacity_by_edd or len(run.lots) <= 1:
            result.append(run)
            continue

        early_lots: list[Lot] = []
        late_lots: list[Lot] = []
        cum = 0.0
        for lot in run.lots:  # already EDD-sorted
            if lot.edd <= run.edd and cum + lot.prod_min + run.setup_min <= capacity_by_edd:
                early_lots.append(lot)
                cum += lot.prod_min
            else:
                late_lots.append(lot)

        if early_lots and late_lots:
            result.append(_make_run(run, early_lots, f"{run.id}_early"))
            result.append(_make_run(run, late_lots, f"{run.id}_late"))
        else:
            result.append(run)

    return result
