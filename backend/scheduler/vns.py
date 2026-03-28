"""Phase 4b — VNS Post-Processing: Variable Neighborhood Search.

Runs AFTER JIT dispatch to polish the schedule by exploring local moves.
Zero risk: if no improvement found, returns original schedule unchanged.

Three neighborhoods:
  N1 — Swap adjacent runs on same machine (creates tool adjacency → -1 setup)
  N2 — Relocate run to different position on same machine (3-opt style)
  N3 — Move run to alt machine (cross-machine rebalance)
"""

from __future__ import annotations

import copy
import logging
from collections import defaultdict

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.dispatch import per_machine_dispatch
from backend.scheduler.jit import _backward_stack_gates, _max_gate
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.types import EngineData

logger = logging.getLogger(__name__)


def _is_better(new: dict, old: dict, config: FactoryConfig) -> bool:
    """Check if new score is strictly better than old, respecting hard constraints."""
    # HARD — never violate
    if new["tardy_count"] > old["tardy_count"]:
        return False
    if new["otd_d"] < old["otd_d"]:
        return False
    target = config.jit_earliness_target if config else 5.5
    earliness_ceiling = max(old["earliness_avg_days"], target)
    if new["earliness_avg_days"] > earliness_ceiling:
        return False

    # Fewer tardy is always better
    if new["tardy_count"] < old["tardy_count"]:
        return True

    # SOFT — weighted composite: tradeoff setups vs earliness
    w_setups = config.weight_setups if config else 0.30
    w_earliness = config.weight_earliness if config else 0.40
    old_cost = old["setups"] * w_setups + old["earliness_avg_days"] * w_earliness
    new_cost = new["setups"] * w_setups + new["earliness_avg_days"] * w_earliness
    if new_cost < old_cost - 0.01:  # small epsilon to avoid float noise
        return True
    return False


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
    for m_id, m_runs in machine_runs.items():
        m_segs, m_lots, _ = per_machine_dispatch(
            {m_id: m_runs}, engine_data, lst_gate=gates, config=config,
        )
        all_segs.extend(m_segs)
        all_lots.extend(m_lots)
    score = compute_score(all_segs, all_lots, engine_data, config=config)
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
            affected_runs, holiday_set, engine_data.n_days, config=config,
        )
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
            # Only swap if EDD difference is within tolerance
            if abs(runs[i].edd - runs[j].edd) > tolerance:
                continue

            # Check if swap creates a tool adjacency that didn't exist before
            would_create_adjacency = False

            # After swap: runs[j] at position i, runs[i] at position j
            # Check if runs[j] matches tool at position i-1
            if i > 0 and runs[j].tool_id == runs[i - 1].tool_id:
                would_create_adjacency = True
            # Check if runs[i] matches tool at position j+1
            if j < len(runs) - 1 and runs[i].tool_id == runs[j + 1].tool_id:
                would_create_adjacency = True
            # Check if the swap itself creates adjacency (same tool)
            if runs[i].tool_id == runs[j].tool_id:
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
        tool_positions: dict[str, list[int]] = defaultdict(list)
        for idx, run in enumerate(runs):
            tool_positions[run.tool_id].append(idx)

        for tool_id, positions in tool_positions.items():
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
                r.tool_id == run.tool_id and abs(r.edd - run.edd) <= tolerance
                for r in alt_runs
            )
            if has_adjacency:
                yield ("cross_machine", m_id, idx, alt)


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
    )


def _apply_move(
    move: tuple,
    machine_runs: dict[str, list[ToolRun]],
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
        # Insert in EDD order on destination machine
        dst_runs = new_runs[dst_m]
        insert_pos = len(dst_runs)
        for i, r in enumerate(dst_runs):
            if r.edd > run.edd:
                insert_pos = i
                break
        dst_runs.insert(insert_pos, run)
        return new_runs, {src_m, dst_m}

    elif move_type == "split":
        _, m_id, idx, mid_edd = move
        original = new_runs[m_id][idx]
        early_lots = [l for l in original.lots if l.edd <= mid_edd]
        late_lots = [l for l in original.lots if l.edd > mid_edd]
        if not early_lots or not late_lots:
            return machine_runs, set()  # degenerate split, skip
        early_run = _make_split_run(original, early_lots, "e")
        late_run = _make_split_run(original, late_lots, "l")
        new_runs[m_id][idx:idx + 1] = [early_run, late_run]
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
    """VNS post-processing: explore neighborhoods to reduce setups/earliness.

    Returns (segments, lots, score, warnings).
    """
    max_iter = config.vns_max_iter if config else 50
    generators = [_generate_n1_moves, _generate_n2_moves, _generate_n3_moves]
    neighborhood_names = ["N1_swap", "N2_relocate", "N3_cross_machine"]

    current_runs = _deep_copy_runs(machine_runs)
    current_gates = dict(gates)
    improvements: list[str] = []
    total_evals = 0

    initial_setups = best_score["setups"]
    initial_earliness = best_score["earliness_avg_days"]

    k = 0  # neighbourhood index
    while k < len(generators) and total_evals < max_iter:
        improved = False

        for move in generators[k](current_runs, config):
            total_evals += 1
            if total_evals >= max_iter:
                break

            candidate_runs, affected = _apply_move(move, current_runs)
            candidate_gates = _recompute_machine_gates(
                candidate_runs, current_gates, affected, engine_data, config,
            )
            cand_segs, cand_lots, cand_score = _dispatch_and_score(
                candidate_runs, candidate_gates, engine_data, config,
            )

            if _is_better(cand_score, best_score, config):
                current_runs = candidate_runs
                current_gates = candidate_gates
                best_segs = cand_segs
                best_lots = cand_lots
                best_score = cand_score
                improvements.append(
                    f"{neighborhood_names[k]}: setups={cand_score['setups']}, "
                    f"earliness={cand_score['earliness_avg_days']:.1f}d"
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
        warnings.append(
            f"VNS: {initial_setups}→{best_score['setups']} setups, "
            f"{initial_earliness:.1f}→{best_score['earliness_avg_days']:.1f}d earliness "
            f"({len(improvements)} improvements, {total_evals} evals)"
        )
        for imp in improvements:
            logger.info("VNS improvement: %s", imp)
    else:
        warnings.append(f"VNS: no improvement found ({total_evals} evals)")
        logger.info("VNS: no improvement found after %d evaluations", total_evals)

    return best_segs, best_lots, best_score, warnings
