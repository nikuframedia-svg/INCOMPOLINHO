"""Phase 2 — Tool Grouping: Spec 02 v6 §4.

Groups Lots by (tool_id, machine_id) into ToolRuns.
1 setup covers all lots in the group. Lots produced sequentially.

Fix 1: Lots within each ToolRun are ALWAYS sorted by EDD.

Splits runs on two criteria:
  1. EDD gap > MAX_EDD_GAP between consecutive lots
  2. Cumulative production time > MAX_RUN_DAYS * DAY_CAP
"""

from __future__ import annotations

from collections import defaultdict

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP, MAX_EDD_GAP, MAX_RUN_DAYS
from backend.scheduler.types import Lot, ToolRun


def create_tool_runs(
    lots: list[Lot],
    max_edd_gap: int = MAX_EDD_GAP,
    audit_logger: object | None = None,
    config: FactoryConfig | None = None,
) -> list[ToolRun]:
    """Group lots by (tool_id, machine_id) into ToolRuns, with splitting."""
    day_cap = config.day_capacity_min if config else DAY_CAP

    groups: dict[tuple[str, str], list[Lot]] = defaultdict(list)

    for lot in lots:
        key = (lot.tool_id, lot.machine_id)
        groups[key].append(lot)

    runs: list[ToolRun] = []
    for (tool, machine), group_lots in groups.items():
        group_lots.sort(key=lambda x: x.edd)  # Fix 1: always EDD sorted
        gap = config.max_edd_gap if config else max_edd_gap
        max_run = config.max_run_days if config else MAX_RUN_DAYS
        span = config.max_edd_span if config else 20
        sub_runs = _split_by_edd_gap(group_lots, gap, max_run, day_cap=day_cap, max_span=span)

        for idx, sub_lots in enumerate(sub_runs):
            setup = sub_lots[0].setup_min
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
) -> list[list[Lot]]:
    """Split sorted lots by EDD gap, span, and max cumulative production time.

    Splits on three criteria:
      1. EDD gap > max_gap between consecutive lots
      2. EDD span > max_span from first lot in group to current lot
      3. Cumulative production time > max_run_days * day_cap
    """
    if not lots:
        return []
    if len(lots) <= 1:
        return [lots]

    max_prod = max_run_days * day_cap
    sub_runs: list[list[Lot]] = [[lots[0]]]
    cum_prod = lots[0].prod_min

    for lot in lots[1:]:
        prev_edd = sub_runs[-1][-1].edd
        first_edd = sub_runs[-1][0].edd
        gap = lot.edd - prev_edd
        span = lot.edd - first_edd
        duration_split = cum_prod + lot.prod_min > max_prod

        if gap > max_gap or duration_split or span > max_span:
            sub_runs.append([lot])
            cum_prod = lot.prod_min
        else:
            sub_runs[-1].append(lot)
            cum_prod += lot.prod_min

    return sub_runs


def _make_run(original: ToolRun, lots: list[Lot], run_id: str) -> ToolRun:
    """Create a new ToolRun from a subset of lots."""
    setup = lots[0].setup_min
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
