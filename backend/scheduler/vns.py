"""Phase 4b — VNS Post-Processing: Variable Neighborhood Search.

Runs AFTER JIT dispatch to polish the schedule by exploring local moves.
Zero risk: if no improvement found, returns original schedule unchanged.

Neighborhoods:
  N1 — Swap adjacent runs on same machine (creates tool adjacency → -1 setup)
  N2 — Relocate run to different position on same machine (3-opt style)
  N3 — Relocate a whole same-tool block on the same machine
  N4 — Move run to alt machine (cross-machine rebalance)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from backend.config.types import FactoryConfig
from backend.scheduler.dispatch import per_machine_dispatch
from backend.scheduler.gates import HARD_GATE_KEYS
from backend.scheduler.jit import _backward_stack_gates
from backend.scheduler.jit_policy import (
    clamp_run_gates_to_window,
    lot_floor_minutes,
)
from backend.scheduler.priority import delivery_priority_key
from backend.scheduler.resources import clone_run_for_machine
from backend.scheduler.scoring import compute_score
from backend.scheduler.setup_identity import SetupIdentity, run_setup_identity
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.types import EngineData

logger = logging.getLogger(__name__)


def _is_better(new: dict, old: dict, config: FactoryConfig) -> bool:
    """Check if new score is strictly better than old, respecting hard constraints."""
    # HARD — never accept physical or delivery regression for a VNS improvement.
    if _hard_violation_count(new) > 0:
        return False
    if _hard_violation_count(new) > _hard_violation_count(old):
        return False
    new_delivery = delivery_priority_key(new)
    old_delivery = delivery_priority_key(old)
    if new_delivery > old_delivery:
        return False
    if new_delivery < old_delivery:
        return True

    # Once delivery and the material-release floor are preserved, keep work as
    # early as possible. A larger gap to the latest legal start means that the
    # candidate starts earlier inside the five-workday material window.
    new_latest_start_gap = float(new.get("latest_start_gap_avg_min", 0.0) or 0.0)
    old_latest_start_gap = float(old.get("latest_start_gap_avg_min", 0.0) or 0.0)
    if new_latest_start_gap > old_latest_start_gap:
        return True
    if new_latest_start_gap < old_latest_start_gap:
        return False

    # With the same production timing, reducing setups is beneficial. It must
    # never be used as a reason to delay a legal production run.
    if int(new.get("setups", 0) or 0) > int(old.get("setups", 0) or 0):
        return False
    if "setup_time_min" in new and "setup_time_min" in old:
        if float(new.get("setup_time_min", 0.0) or 0.0) > float(
            old.get("setup_time_min", 0.0) or 0.0
        ):
            return False

    # Materials-window guard: a VNS move must never worsen window compliance.
    if int(new.get("early_window_violations", 0) or 0) > int(
        old.get("early_window_violations", 0) or 0
    ):
        return False

    if int(new.get("setups", 0) or 0) < int(old.get("setups", 0) or 0):
        return True
    if "setup_time_min" in new and "setup_time_min" in old:
        if float(new.get("setup_time_min", 0.0) or 0.0) < float(
            old.get("setup_time_min", 0.0) or 0.0
        ):
            return True
    if float(new.get("planning_penalty", 0.0) or 0.0) < float(
        old.get("planning_penalty", 0.0) or 0.0
    ):
        return True
    return False


def _hard_violation_count(score: dict) -> int:
    # VNS scores are computed before the scheduler's final single-crew
    # serialization pass. Setup-crew overlaps are therefore repairable
    # intermediate conflicts here; all other physical gates are blocking.
    repairable_pre_serialization = {"setup_crew_overlaps"}
    explicit = sum(
        int(score.get(key, 0) or 0)
        for key in HARD_GATE_KEYS
        if key not in repairable_pre_serialization
    )
    aggregate = int(score.get("hard_violations", 0) or 0) - int(
        score.get("setup_crew_overlaps", 0) or 0
    )
    return max(aggregate, explicit) + int(score.get("early_window_violations", 0) or 0)


def _deep_copy_runs(machine_runs: dict[str, list[ToolRun]]) -> dict[str, list[ToolRun]]:
    """Deep copy machine_runs to avoid mutating the original."""
    return {m_id: list(runs) for m_id, runs in machine_runs.items()}


def _dispatch_and_score(
    machine_runs: dict[str, list[ToolRun]],
    gates: dict[str, float],
    engine_data: EngineData,
    config: FactoryConfig,
) -> tuple[list[Segment], list[Lot], dict]:
    """Re-dispatch all machines and compute score.

    Per-machine dispatch for gate independence; crew serialized in post-processing.
    """
    all_segs: list[Segment] = []
    all_lots: list[Lot] = []
    holiday_set = set(getattr(engine_data, "holidays", []) or [])
    floors = lot_floor_minutes(machine_runs, holiday_set, config.day_capacity_min)
    gates = clamp_run_gates_to_window(machine_runs, gates, floors)
    for m_id, m_runs in machine_runs.items():
        m_segs, m_lots, _ = per_machine_dispatch(
            {m_id: m_runs},
            engine_data,
            lst_gate=gates,
            config=config,
            lot_floors=floors,
        )
        all_segs.extend(m_segs)
        all_lots.extend(m_lots)
    # The canonical scheduler audits legal gaps once on the settled plan.
    # Repeating that O(n²) explainability scan for every VNS neighbour changes
    # no VNS decision and made real recalculations exceed their time budget.
    score = compute_score(
        all_segs,
        all_lots,
        engine_data,
        config=config,
        include_operational_audit=False,
    )
    return all_segs, all_lots, score


def _recompute_machine_gates(
    machine_runs: dict[str, list[ToolRun]],
    old_gates: dict[str, float],
    affected_machines: set[str],
    engine_data: EngineData,
    config: FactoryConfig,
) -> dict[str, float]:
    """Recompute gates for affected machines, keep others unchanged."""
    holiday_set = set(getattr(engine_data, "holidays", []))
    new_gates = dict(old_gates)

    # Only recompute affected machines
    affected_runs = {m_id: runs for m_id, runs in machine_runs.items() if m_id in affected_machines}
    if affected_runs:
        recomputed = _backward_stack_gates(
            affected_runs,
            holiday_set,
            engine_data.n_days,
            config=config,
        )
        floors = lot_floor_minutes(affected_runs, holiday_set, config.day_capacity_min)
        recomputed = clamp_run_gates_to_window(affected_runs, recomputed, floors)
        new_gates.update(recomputed)

    return new_gates


# ─── Neighborhood generators ──────────────────────────────────────────


def _generate_n1_moves(machine_runs: dict[str, list[ToolRun]], config: FactoryConfig):
    """N1: Swap adjacent runs on same machine if it creates a tool adjacency.

    Yields (machine_id, i, j) tuples where i and j are adjacent positions.
    Only yields swaps that would create a same-tool adjacency (potential setup saving).
    """
    tolerance = config.edd_swap_tolerance * 2  # wider tolerance for VNS

    for m_id, runs in machine_runs.items():
        for i in range(len(runs) - 1):
            j = i + 1
            # Only swap if operational due-date difference is within tolerance
            if abs(runs[i].edd - runs[j].edd) > tolerance:
                continue

            # Check if swap creates a tool adjacency that didn't exist before
            would_create_adjacency = False

            # After swap: runs[j] at position i, runs[i] at position j
            # Check if runs[j] matches tool at position i-1
            if i > 0 and run_setup_identity(runs[j]) == run_setup_identity(runs[i - 1]):
                would_create_adjacency = True
            # Check if runs[i] matches tool at position j+1
            if (
                j < len(runs) - 1
                and run_setup_identity(runs[i]) == run_setup_identity(runs[j + 1])
            ):
                would_create_adjacency = True
            # Check if the swap itself creates adjacency (same tool)
            if run_setup_identity(runs[i]) == run_setup_identity(runs[j]):
                continue  # already adjacent same tool, no benefit

            if would_create_adjacency:
                yield ("swap", m_id, i, j)


def _generate_n2_moves(machine_runs: dict[str, list[ToolRun]], config: FactoryConfig):
    """N2: Relocate run to create tool adjacency (3-opt style).

    For each run, check if moving it next to a same-tool run would save a setup.
    """
    tolerance = config.edd_swap_tolerance * 2

    for m_id, runs in machine_runs.items():
        # Build tool → positions index
        tool_positions: dict[SetupIdentity, list[int]] = defaultdict(list)
        for idx, run in enumerate(runs):
            tool_positions[run_setup_identity(run)].append(idx)

        for _setup_identity, positions in tool_positions.items():
            if len(positions) < 2:
                continue

            # For each pair of positions with same tool, try relocating to be adjacent
            for pi in range(len(positions)):
                for pj in range(pi + 1, len(positions)):
                    src = positions[pj]  # move later run
                    dst = positions[pi] + 1  # place right after earlier run

                    if src == dst or src == dst - 1:
                        continue  # already adjacent

                    # EDD tolerance check
                    if abs(runs[src].edd - runs[positions[pi]].edd) > tolerance:
                        continue

                    yield ("relocate", m_id, src, dst)


def _generate_n3_moves(machine_runs: dict[str, list[ToolRun]], config: FactoryConfig):
    """N3: Move run to alt machine.

    For each run with alt_machine_id, try moving it to the alt machine
    if it would create a tool adjacency there.
    """
    tolerance = config.edd_swap_tolerance * 2

    for m_id, runs in machine_runs.items():
        for idx, run in enumerate(runs):
            alt = run.alt_machine_id
            if alt is None or alt not in machine_runs:
                continue

            # Check if alt machine has a same-tool run within EDD tolerance
            alt_runs = machine_runs[alt]
            has_adjacency = any(
                run_setup_identity(r) == run_setup_identity(run)
                and abs(r.edd - run.edd) <= tolerance
                for r in alt_runs
            )
            if has_adjacency:
                yield ("cross_machine", m_id, idx, alt)


def _generate_n4_block_moves(machine_runs: dict[str, list[ToolRun]], config: FactoryConfig):
    """N4: Move a whole same-tool block next to an earlier same-tool block.

    Single-run relocate can fail on patterns like A-X-A-A: moving only one A
    leaves the later A stranded, so the setup count does not improve. A block
    move keeps existing campaigns intact and lets the trust gates decide whether
    the earlier placement is still executable.
    """

    tolerance = config.edd_swap_tolerance * 2
    for m_id, runs in machine_runs.items():
        blocks = _same_tool_blocks(runs)
        if len(blocks) < 3:
            continue

        for anchor_idx, anchor in enumerate(blocks):
            for src in blocks[anchor_idx + 2 :]:
                if src["setup_identity"] != anchor["setup_identity"]:
                    continue
                if int(src["edd_min"]) - int(anchor["edd_max"]) > tolerance:
                    continue
                yield (
                    "block_relocate",
                    m_id,
                    int(src["start"]),
                    int(src["end"]),
                    int(anchor["end"]),
                )


def _same_tool_blocks(runs: list[ToolRun]) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    start = 0
    while start < len(runs):
        end = start + 1
        setup_identity = run_setup_identity(runs[start])
        while end < len(runs) and run_setup_identity(runs[end]) == setup_identity:
            end += 1

        edds = [run.edd for run in runs[start:end]]
        blocks.append(
            {
                "start": start,
                "end": end,
                "setup_identity": setup_identity,
                "edd_min": min(edds),
                "edd_max": max(edds),
            }
        )
        start = end
    return blocks


def _generate_n4_split_moves(machine_runs: dict[str, list[ToolRun]], config: FactoryConfig):
    """N4: Split high-earliness multi-lot runs into two runs.

    For runs where lot EDD span > threshold, split at the midpoint.
    Cost: +1 setup. Benefit: later lots get their own gate closer to their EDD.
    """
    split_threshold = 15  # only split runs with EDD span > 15 days

    for m_id, runs in machine_runs.items():
        for idx, run in enumerate(runs):
            if len(run.lots) < 2:
                continue
            # Lots are EDD-sorted within each run
            span = run.lots[-1].edd - run.lots[0].edd
            if span <= split_threshold:
                continue
            mid_edd = (run.lots[0].edd + run.lots[-1].edd) // 2
            yield ("split", m_id, idx, mid_edd)


def _make_split_run(original: ToolRun, lots: list[Lot], suffix: str) -> ToolRun:
    """Create a new ToolRun from a subset of lots (for N4 split)."""
    setup = lots[0].setup_min
    total_prod = sum(lot.prod_min for lot in lots)
    return ToolRun(
        id=f"{original.id}_{suffix}",
        tool_id=original.tool_id,
        machine_id=original.machine_id,
        alt_machine_id=original.alt_machine_id,
        lots=lots,
        setup_min=setup,
        total_prod_min=total_prod,
        total_min=setup + total_prod,
        edd=lots[0].edd,
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


def _apply_move(
    move: tuple,
    machine_runs: dict[str, list[ToolRun]],
    engine_data: EngineData | None = None,
    config: FactoryConfig | None = None,
) -> tuple[dict[str, list[ToolRun]], set[str]]:
    """Apply a VNS move, returning new machine_runs and set of affected machine IDs."""
    new_runs = _deep_copy_runs(machine_runs)
    move_type = move[0]

    if move_type == "swap":
        _, m_id, i, j = move
        new_runs[m_id][i], new_runs[m_id][j] = new_runs[m_id][j], new_runs[m_id][i]
        return new_runs, {m_id}

    elif move_type == "relocate":
        _, m_id, src, dst = move
        runs = new_runs[m_id]
        run = runs.pop(src)
        # Adjust dst if src was before dst
        if src < dst:
            dst -= 1
        runs.insert(dst, run)
        return new_runs, {m_id}

    elif move_type == "cross_machine":
        _, src_m, idx, dst_m = move
        run = new_runs[src_m].pop(idx)
        if engine_data is not None:
            # Run objects are shared across candidates (shallow copies) — a
            # cross-machine move must clone before rebinding setup/OEE to the
            # destination machine, never mutate the shared original.
            run = clone_run_for_machine(run, dst_m, engine_data, config)
        # Insert in EDD order on destination machine. Positional insertion next
        # to a matching tool can degrade the post-crew-serialization frontier.
        dst_runs = new_runs[dst_m]
        insert_pos = len(dst_runs)
        for i, r in enumerate(dst_runs):
            if r.edd > run.edd:
                insert_pos = i
                break
        dst_runs.insert(insert_pos, run)
        return new_runs, {src_m, dst_m}

    elif move_type == "block_relocate":
        _, m_id, src_start, src_end, dst = move
        runs = new_runs[m_id]
        if src_start < 0 or src_end > len(runs) or src_start >= src_end:
            return machine_runs, set()
        if dst >= src_start and dst <= src_end:
            return machine_runs, set()
        block = runs[src_start:src_end]
        del runs[src_start:src_end]
        if src_start < dst:
            dst -= len(block)
        dst = max(0, min(dst, len(runs)))
        runs[dst:dst] = block
        return new_runs, {m_id}

    elif move_type == "split":
        _, m_id, idx, mid_edd = move
        original = new_runs[m_id][idx]
        early_lots = [lot for lot in original.lots if lot.edd <= mid_edd]
        late_lots = [lot for lot in original.lots if lot.edd > mid_edd]
        if not early_lots or not late_lots:
            return machine_runs, set()  # degenerate split, skip
        early_run = _make_split_run(original, early_lots, "e")
        late_run = _make_split_run(original, late_lots, "l")
        new_runs[m_id][idx : idx + 1] = [early_run, late_run]
        return new_runs, {m_id}

    return machine_runs, set()


# ─── Main VNS ─────────────────────────────────────────────────────────


def vns_polish(
    machine_runs: dict[str, list[ToolRun]],
    gates: dict[str, float],
    engine_data: EngineData,
    config: FactoryConfig,
    best_segs: list[Segment],
    best_lots: list[Lot],
    best_score: dict,
) -> tuple[list[Segment], list[Lot], dict, list[str]]:
    """VNS post-processing: explore neighborhoods to improve timing/setups.

    Returns (segments, lots, score, warnings).
    """
    max_iter = config.vns_max_iter if config else 50
    deadline = getattr(config, "_optimization_deadline", None)
    generators = [_generate_n1_moves, _generate_n2_moves]
    neighborhood_names = ["N1_swap", "N2_relocate"]
    if getattr(config, "vns_block_moves_enabled", False):
        generators.append(_generate_n4_block_moves)
        neighborhood_names.append("N3_block_relocate")
    generators.append(_generate_n3_moves)
    neighborhood_names.append(
        "N4_cross_machine"
        if getattr(config, "vns_block_moves_enabled", False)
        else "N3_cross_machine"
    )

    current_runs = _deep_copy_runs(machine_runs)
    current_gates = dict(gates)
    improvements: list[str] = []
    total_evals = 0

    initial_setups = best_score["setups"]
    initial_latest_start_gap = float(best_score.get("latest_start_gap_avg_min", 0.0) or 0.0)

    k = 0  # neighbourhood index
    while (
        k < len(generators)
        and total_evals < max_iter
        and (deadline is None or time.perf_counter() < float(deadline))
    ):
        improved = False

        for move in generators[k](current_runs, config):
            if deadline is not None and time.perf_counter() >= float(deadline):
                break
            total_evals += 1
            if total_evals >= max_iter:
                break

            candidate_runs, affected = _apply_move(move, current_runs, engine_data, config)
            candidate_gates = _recompute_machine_gates(
                candidate_runs,
                current_gates,
                affected,
                engine_data,
                config,
            )
            cand_segs, cand_lots, cand_score = _dispatch_and_score(
                candidate_runs,
                candidate_gates,
                engine_data,
                config,
            )

            if _is_better(cand_score, best_score, config):
                current_runs = candidate_runs
                current_gates = candidate_gates
                best_segs = cand_segs
                best_lots = cand_lots
                best_score = cand_score
                improvements.append(
                    f"{neighborhood_names[k]}: setups={cand_score['setups']}, "
                    "latest-start gap="
                    f"{float(cand_score.get('latest_start_gap_avg_min', 0.0) or 0.0):.0f}min"
                )
                improved = True
                break  # restart from N1

        if improved:
            k = 0  # restart from first neighbourhood
        else:
            k += 1  # try next neighbourhood

    # Build summary warnings
    warnings: list[str] = []
    if improvements:
        final_latest_start_gap = float(
            best_score.get("latest_start_gap_avg_min", 0.0) or 0.0
        )
        warnings.append(
            f"VNS: {initial_setups}→{best_score['setups']} setups, "
            f"{initial_latest_start_gap:.0f}→{final_latest_start_gap:.0f}min "
            "de margem até ao último início legal "
            f"({len(improvements)} improvements, {total_evals} evals)"
        )
        for imp in improvements:
            logger.info("VNS improvement: %s", imp)
    else:
        warnings.append(f"VNS: no improvement found ({total_evals} evals)")
        logger.info("VNS: no improvement found after %d evaluations", total_evals)

    return best_segs, best_lots, best_score, warnings
