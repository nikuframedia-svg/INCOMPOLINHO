"""Proposals that keep a tool on one machine (plan-melhoria §2.3, §5.3).

The constructor chooses a machine for every run independently and has no
setup or transfer cost, so a mould can bounce between machines (A → B → A)
for no physical reason. For every such transfer this generator proposes an
alternative that keeps the tool on its prior machine. The proposal may retain
only the incoming run when moving the whole subsequent block is too broad.
The evaluator applies the common delivery, setup and transfer objective;
protected (started or anchored) lots are never moved.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, replace

from backend.planning_control import execution_cache
from backend.plans.serialize import MODEL_VERSION, planning_input_fingerprints, value_fingerprint
from backend.scheduler.alternative_repair import (
    MAX_COORDINATED_GROUP_SIZE,
    _eligible_machines,
    _replace_lots,
    _resolve_runs,
    _schedule_run_earliest,
    _sorted_segments,
)
from backend.scheduler.improvement import (
    Proposal,
    SkippedProposal,
    physical_setups,
    tool_transfers,
)
from backend.scheduler.priority import run_priority_key
from backend.scheduler.protection import protected_lot_ids
from backend.scheduler.resources import clone_run_for_machine
from backend.scheduler.setup_identity import retained_setup_at, segment_setup_identity
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.types import EngineData

SCOPE = "tool_transfers"
TRANSFER_SEARCH_VERSION = 2
_BEAM_WIDTH = 4
_MAX_HOPS = 24
_LOCAL_BEAM_WIDTH = 32
_LOCAL_LOOKAHEAD_DAYS = 14


@dataclass(frozen=True, slots=True)
class TransferHop:
    """One block of a tool's use on a machine other than its neighbour's."""

    key: str
    tool_id: str
    kind: str  # "ping_pong" (A|B|A) or "split" (A|B)
    from_machine: str  # machine of the block today
    to_machine: str  # machine where the tool already is
    lot_ids: tuple[str, ...]
    run_ids: tuple[str, ...]
    day_idx: int
    start_abs: int
    end_abs: int
    duration_ratio: float
    transfers_removed: int
    protected: bool

    def subject(self) -> dict[str, object]:
        return {
            "key": self.key, "tool_id": self.tool_id, "kind": self.kind,
            "from_machine": self.from_machine, "to_machine": self.to_machine,
            "lot_ids": list(self.lot_ids[:6]), "day_idx": self.day_idx,
            "duration_ratio": round(self.duration_ratio, 2),
        }


@dataclass(frozen=True, slots=True)
class RetainedMounting:
    first: Segment
    predecessor_run_id: str


def _active(segment: Segment) -> bool:
    return segment.end_min > segment.start_min and (
        segment.prod_min > 0 or segment.setup_min > 0
    )


def _abs(segment: Segment) -> tuple[int, int]:
    return (
        int(segment.day_idx) * 1440 + int(segment.start_min),
        int(segment.day_idx) * 1440 + int(segment.end_min),
    )


def _blocks(segments: list[Segment]) -> dict[str, list[list[Segment]]]:
    """Consecutive uses of each tool on the same machine."""

    by_tool: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        if _active(segment):
            by_tool[segment.tool_id].append(segment)
    blocks: dict[str, list[list[Segment]]] = {}
    for tool_id, uses in by_tool.items():
        uses.sort(key=lambda s: (s.day_idx, s.start_min, s.end_min, s.machine_id))
        grouped: list[list[Segment]] = []
        for use in uses:
            if grouped and grouped[-1][-1].machine_id == use.machine_id:
                grouped[-1].append(use)
            else:
                grouped.append([use])
        if len(grouped) > 1:
            blocks[tool_id] = grouped
    return blocks


def _duration_ratio(runs: list[ToolRun], machine_id: str, data, config) -> float:
    current = sum(run.total_prod_min for run in runs)
    if current <= 0:
        return 1.0
    moved = sum(
        clone_run_for_machine(run, machine_id, data, config).total_prod_min for run in runs
    )
    return moved / current


def enumerate_transfer_hops(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config,
) -> list[TransferHop]:
    """Every transfer, ranked: same-speed ping-pong first, then shortest."""

    protected = protected_lot_ids(data)
    run_map = _resolve_runs(segments, lots, None)
    hops: list[TransferHop] = []
    for tool_id, blocks in sorted(_blocks(segments).items()):
        for index, block in enumerate(blocks):
            before = blocks[index - 1] if index > 0 else None
            after = blocks[index + 1] if index + 1 < len(blocks) else None
            targets: list[tuple[str, str, int]] = []
            if before and after and before[0].machine_id == after[0].machine_id:
                targets.append((before[0].machine_id, "ping_pong", 2))
            else:
                for neighbour in (before, after):
                    if neighbour is not None:
                        targets.append((neighbour[0].machine_id, "split", 1))
            run_ids = tuple(sorted({s.run_id for s in block}))
            lot_ids = tuple(sorted({s.lot_id for s in block}))
            runs = [run_map[run_id] for run_id in run_ids if run_id in run_map]
            start_abs = min(_abs(s)[0] for s in block)
            end_abs = max(_abs(s)[1] for s in block)
            for to_machine, kind, removed in dict.fromkeys(targets):
                hops.append(TransferHop(
                    key=f"{tool_id}:{','.join(lot_ids)}:{block[0].machine_id}->{to_machine}",
                    tool_id=tool_id, kind=kind,
                    from_machine=block[0].machine_id, to_machine=to_machine,
                    lot_ids=lot_ids, run_ids=run_ids,
                    day_idx=min(s.day_idx for s in block),
                    start_abs=start_abs, end_abs=end_abs,
                    duration_ratio=_duration_ratio(runs, to_machine, data, config),
                    transfers_removed=removed,
                    protected=bool(set(lot_ids) & protected),
                ))

    def rank(hop: TransferHop) -> tuple[object, ...]:
        ratio = hop.duration_ratio
        speed = 0 if abs(ratio - 1.0) <= 0.02 else 1 if ratio < 1.0 else 2
        return (hop.protected, -hop.transfers_removed, speed, hop.end_abs - hop.start_abs,
                hop.tool_id, hop.lot_ids, hop.to_machine)

    return sorted(hops, key=rank)


def _displaced_runs(
    hop: TransferHop,
    segments: list[Segment],
    run_map: dict[str, ToolRun],
    protected: set[str],
) -> tuple[list[str], bool]:
    """Unprotected runs of other tools occupying the target window."""

    duration = int((hop.end_abs - hop.start_abs) * max(1.0, hop.duration_ratio))
    window = (hop.start_abs, hop.start_abs + duration)
    overlapping: dict[str, int] = {}
    for segment in segments:
        if segment.machine_id != hop.to_machine or segment.tool_id == hop.tool_id:
            continue
        start, end = _abs(segment)
        if start < window[1] and window[0] < end and segment.run_id in run_map:
            overlapping[segment.run_id] = min(overlapping.get(segment.run_id, start), start)
    ordered = sorted(overlapping.items(), key=lambda item: (item[1], item[0]))
    displaced = [
        run_id for run_id, _start in ordered
        if not {lot.id for lot in run_map[run_id].lots} & protected
    ]
    room = max(0, MAX_COORDINATED_GROUP_SIZE - len(hop.run_ids))
    return displaced[:room], len(displaced) > room


def _first_run_stay_hop(
    hop: TransferHop,
    segments: list[Segment],
    run_map: dict[str, ToolRun],
    protected: set[str],
    data: EngineData,
    config,
) -> TransferHop | None:
    """Keep just the incoming run when moving the entire later block is too broad."""

    if len(hop.run_ids) < 2:
        return None
    first_id = min(
        hop.run_ids,
        key=lambda run_id: min(
            _abs(segment)[0] for segment in segments if segment.run_id == run_id
        ),
    )
    run = run_map.get(first_id)
    if run is None or {lot.id for lot in run.lots} & protected:
        return None
    first_segments = [segment for segment in segments if segment.run_id == first_id]
    if not any(segment.setup_min > 0 for segment in first_segments):
        return None
    start = min(_abs(segment)[0] for segment in first_segments)
    previous = max(
        (
            segment for segment in segments
            if segment.tool_id == hop.tool_id and _abs(segment)[1] <= start
        ),
        key=lambda segment: _abs(segment)[1],
        default=None,
    )
    if previous is None or previous.machine_id != hop.to_machine:
        return None
    if hop.to_machine not in _eligible_machines(run, data, config, segments):
        return None
    return TransferHop(
        key=f"{hop.key}|first_run:{first_id}",
        tool_id=hop.tool_id,
        kind="local_stay",
        from_machine=hop.from_machine,
        to_machine=hop.to_machine,
        lot_ids=tuple(sorted(lot.id for lot in run.lots)),
        run_ids=(first_id,),
        day_idx=min(segment.day_idx for segment in first_segments),
        start_abs=start,
        end_abs=max(_abs(segment)[1] for segment in first_segments),
        duration_ratio=_duration_ratio([run], hop.to_machine, data, config),
        transfers_removed=0,
        protected=False,
    )


def _local_displaced_runs(
    hop: TransferHop,
    segments: list[Segment],
    run_map: dict[str, ToolRun],
    protected: set[str],
    data: EngineData,
    config,
) -> tuple[list[str], str | None]:
    """Probe the incoming run, then release only runs it actually intersects."""

    run = run_map[hop.run_ids[0]]
    by_run: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        by_run[segment.run_id].append(segment)
    cutoff = hop.start_abs + _LOCAL_LOOKAHEAD_DAYS * 1440
    potential = {
        run_id for run_id, items in by_run.items()
        if run_id != run.id
        and all(segment.machine_id == hop.to_machine for segment in items)
        and items[0].tool_id != hop.tool_id
        and max(_abs(segment)[1] for segment in items) > hop.start_abs
        and min(_abs(segment)[0] for segment in items) < cutoff
        and run_id in run_map
        and not ({lot.id for lot in run_map[run_id].lots} & protected)
    }
    probe_fixed = [
        segment for segment in segments
        if segment.run_id != run.id and segment.run_id not in potential
    ]
    probe = _schedule_run_earliest(
        run, hop.to_machine, probe_fixed, data, config,
        not_before_abs=hop.start_abs,
    )
    if probe is None:
        return [], "unschedulable"
    created = probe[1]
    start = min(_abs(segment)[0] for segment in created)
    end = max(_abs(segment)[1] for segment in created)
    if end > cutoff:
        return [], "scope_limited"
    displaced = sorted(
        (
            run_id for run_id in potential
            if any(
                _abs(segment)[0] < end and start < _abs(segment)[1]
                for segment in by_run[run_id]
            )
        ),
        key=lambda run_id: (
            min(_abs(segment)[0] for segment in by_run[run_id]), run_id
        ),
    )
    if len(displaced) + 1 > MAX_COORDINATED_GROUP_SIZE:
        return [], "group_too_large"
    return displaced, None


def _rebuild(
    hop: TransferHop,
    displaced: list[str],
    segments: list[Segment],
    lots: list[Lot],
    run_map: dict[str, ToolRun],
    data: EngineData,
    config,
    *,
    not_before_by_run: dict[str, int] | None = None,
    beam_width: int = _BEAM_WIDTH,
    search_limits: set[str] | None = None,
    retained_origins: dict[str, RetainedMounting] | None = None,
) -> list[tuple[list[Segment], list[Lot], tuple[tuple[str, str], ...]]]:
    """Rebuild the block and the mounting dependencies it removes or inserts."""

    from backend.planning_control import planning_checkpoint

    protected = protected_lot_ids(data)
    origins = (retained_origins if retained_origins is not None
               else _retained_origins(segments, run_map))
    successors: dict[str, list[str]] = defaultdict(list)
    for run_id, mounting in origins.items():
        successors[mounting.predecessor_run_id].append(run_id)
    block_runs = sorted((run_map[run_id] for run_id in hop.run_ids), key=run_priority_key)

    def close(group: set[str], *, include_predecessors: bool = False) -> set[str] | None:
        pending = sorted(group)
        while pending:
            planning_checkpoint()
            run_id = pending.pop(0)
            relatives = list(successors.get(run_id, []))
            if include_predecessors and run_id in origins:
                relatives.append(origins[run_id].predecessor_run_id)
            for relative_id in relatives:
                relative = run_map.get(relative_id)
                if relative is None or {lot.id for lot in relative.lots} & protected:
                    continue
                if relative_id not in group:
                    group.add(relative_id)
                    pending.append(relative_id)
            if len(group) > MAX_COORDINATED_GROUP_SIZE:
                if search_limits is not None:
                    search_limits.add("setup_dependency_group_size")
                return None
        return group

    initial = close(set(hop.run_ids) | set(displaced))
    if initial is None:
        return []
    pending_groups = [initial]
    visited: set[frozenset[str]] = set()
    result = []
    while pending_groups:
        planning_checkpoint()
        group = pending_groups.pop(0)
        key = frozenset(group)
        if key in visited:
            continue
        visited.add(key)
        fixed = [segment for segment in segments if segment.run_id not in group]
        other_runs = sorted(
            (run_map[run_id] for run_id in group - set(hop.run_ids)),
            key=run_priority_key,
        )
        states: list[tuple[list[Segment], list[Lot], tuple, tuple]] = [(fixed, lots, (), ())]
        for run in [*block_runs, *other_runs]:
            planning_checkpoint()
            if run.id in hop.run_ids:
                options = [hop.to_machine]
            else:
                eligible = _eligible_machines(run, data, config, segments)
                options = [m for m in dict.fromkeys((hop.from_machine, hop.to_machine, *eligible))
                           if m in eligible]
            next_states = []
            for state_segments, state_lots, assignments, completion in states:
                for machine_id in options:
                    planning_checkpoint()
                    scheduled = _schedule_run_earliest(
                        run, machine_id, state_segments, data, config,
                        not_before_abs=(not_before_by_run or {}).get(run.id),
                    )
                    if scheduled is None:
                        continue
                    rebound, created = scheduled
                    finish = max(_abs(segment)[1] for segment in created)
                    next_states.append((
                        _sorted_segments([*state_segments, *created]),
                        _replace_lots(state_lots, rebound.lots),
                        (*assignments, (run.id, machine_id)),
                        (*completion, finish),
                    ))
            if len(next_states) > beam_width and search_limits is not None:
                search_limits.add("beam_width")
            states = sorted(next_states, key=lambda state: (state[3], state[2]))[:beam_width]
            if not states:
                break
        for state_segments, state_lots, assignments, _ in states:
            # Inserting the rebuilt campaign can also replace the mounting of
            # a fixed successor whose predecessor was not in the original group.
            dependencies = set()
            for run_id, mounting in origins.items():
                planning_checkpoint()
                if (run_id in group or run_id not in run_map
                        or {lot.id for lot in run_map[run_id].lots} & protected):
                    continue
                first = mounting.first
                if not retained_setup_at(
                    state_segments, first.machine_id, segment_setup_identity(first),
                    first.day_idx, first.start_min, ignore_run_id=run_id,
                ):
                    dependencies.add(run_id)
            if not dependencies:
                result.append((state_segments, state_lots, assignments))
            else:
                extended = close(group | dependencies, include_predecessors=True)
                if extended is not None and frozenset(extended) not in visited:
                    pending_groups.append(extended)
    return result


def _retained_origins(
    segments: list[Segment], run_map: dict[str, ToolRun],
) -> dict[str, RetainedMounting]:
    """Setup-free run starts whose mounting is proved in the source plan."""

    from backend.planning_control import planning_checkpoint

    seen = set()
    previous_by_machine: dict[str, Segment] = {}
    result = {}
    for first in _sorted_segments(segment for segment in segments if _active(segment)):
        planning_checkpoint()
        run_id = first.run_id
        previous = previous_by_machine.get(first.machine_id)
        previous_by_machine[first.machine_id] = first
        if run_id in seen:
            continue
        seen.add(run_id)
        run = run_map.get(run_id)
        if (previous is not None and run is not None and run.setup_min > 0
                and first.setup_min <= 0 and retained_setup_at(
            segments, first.machine_id, segment_setup_identity(first),
            first.day_idx, first.start_min, ignore_run_id=run_id,
        )):
            result[run_id] = RetainedMounting(first, previous.run_id)
    return result


def _local_stay_proposals(
    hop: TransferHop,
    segments: list[Segment],
    lots: list[Lot],
    run_map: dict[str, ToolRun],
    protected: set[str],
    data: EngineData,
    config,
    current_setups,
    *,
    retained_origins: dict[str, RetainedMounting] | None = None,
) -> Iterator[Proposal | SkippedProposal]:
    """Compare retaining one run without forcing all later uses onto that machine."""

    from backend.scheduler.scheduler import _remove_redundant_retained_tool_setups

    subject = hop.subject()
    displaced, reason = _local_displaced_runs(
        hop, segments, run_map, protected, data, config,
    )
    if reason is not None:
        yield SkippedProposal(subject, reason,
                              scope_limited=reason in {"scope_limited", "group_too_large"})
        return
    subject["displaced"] = [
        {"run_id": run_id, "tool_id": run_map[run_id].tool_id}
        for run_id in displaced
    ]
    group = set(hop.run_ids) | set(displaced)
    first_start = {
        run_id: min(_abs(segment)[0] for segment in segments if segment.run_id == run_id)
        for run_id in group
    }
    limits: set[str] = set()
    states = _rebuild(
        hop, displaced, segments, lots, run_map, data, config,
        not_before_by_run=first_start, beam_width=_LOCAL_BEAM_WIDTH,
        search_limits=limits, retained_origins=retained_origins,
    )
    if not states:
        yield SkippedProposal(subject, "scope_limited" if limits else "unschedulable",
                              tuple(sorted(limits)), scope_limited=bool(limits))
        return
    yielded = 0
    for state_segments, state_lots, assignments in states:
        candidate = _remove_redundant_retained_tool_setups(
            [replace(segment) for segment in state_segments],
            protected_lot_ids=protected,
        )
        setups = physical_setups(candidate)
        if setups.count > current_setups.count or setups.minutes > current_setups.minutes:
            continue
        if (setups.count, setups.minutes) >= (
            current_setups.count, current_setups.minutes
        ):
            continue
        yield Proposal(
            _sorted_segments(candidate), copy.copy(state_lots),
            subject={**subject, "assignments": dict(assignments)},
        )
        yielded += 1
    if limits:
        yield SkippedProposal(subject, "scope_limited", tuple(sorted(limits)), scope_limited=True)
    elif not yielded:
        yield SkippedProposal(subject, "no_admissible_setup_saving")


def consolidation_proposals(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config,
) -> Iterator[Proposal | SkippedProposal]:
    """Lazily propose "keep the tool on one machine" for each ranked transfer."""

    from backend.scheduler.scheduler import _remove_redundant_retained_tool_setups

    protected = protected_lot_ids(data)
    run_map = _resolve_runs(segments, lots, None)
    # A third machine can release shared operators or setup crews. Until the
    # complete dependency closure is known, any state change invalidates skips.
    cache = execution_cache("transfer_consolidation")
    context = value_fingerprint({
        "plan": sorted(value_fingerprint(replace(s, left_shift_blockers=[])) for s in segments),
        "lots": lots,
        "inputs": planning_input_fingerprints(data, config), "model": MODEL_VERSION,
        "scope": [TRANSFER_SEARCH_VERSION, MAX_COORDINATED_GROUP_SIZE, _MAX_HOPS, _BEAM_WIDTH,
                  _LOCAL_BEAM_WIDTH, _LOCAL_LOOKAHEAD_DAYS],
    })
    if cache.get("context") != context:
        cache.clear()
        cache["context"] = context
    screened = cache.setdefault("screened", {})
    origins = cache.get("retained_origins")
    if origins is None:
        origins = _retained_origins(segments, run_map)
        cache["retained_origins"] = origins
    current_transfers = tool_transfers(segments)
    current_setups = physical_setups(segments)
    hops = enumerate_transfer_hops(segments, lots, data, config)
    for hop in hops[:_MAX_HOPS]:
        local = _first_run_stay_hop(
            hop, segments, run_map, protected, data, config,
        )
        if local is not None:
            yield from _local_stay_proposals(
                local, segments, lots, run_map, protected, data, config,
                current_setups,
                retained_origins=origins,
            )
        subject = hop.subject()
        if hop.protected:
            yield SkippedProposal(subject, "protected", ("envolve lote iniciado ou ancorado",))
            continue
        block_runs = [run_map.get(run_id) for run_id in hop.run_ids]
        if any(run is None for run in block_runs) or any(
            segment.run_id in hop.run_ids and segment.machine_id != hop.from_machine
            for segment in segments
        ):
            yield SkippedProposal(subject, "split_run")
            continue
        if any(
            hop.to_machine not in _eligible_machines(run, data, config, segments)
            for run in block_runs
        ):
            yield SkippedProposal(subject, "not_eligible")
            continue
        if len(hop.run_ids) > MAX_COORDINATED_GROUP_SIZE:
            yield SkippedProposal(
                subject, "group_too_large",
                (f"{len(hop.run_ids)} campanhas; limite {MAX_COORDINATED_GROUP_SIZE}",),
                scope_limited=True,
            )
            continue
        memo_key = hop.key
        if memo_key in screened:
            reason, details, limited = screened[memo_key]
            yield SkippedProposal(subject, reason, (*details, "reutilizado: recursos inalterados"),
                                  scope_limited=limited)
            continue
        displaced, truncated = _displaced_runs(hop, segments, run_map, protected)
        subject["displaced"] = [
            {"run_id": run_id, "tool_id": run_map[run_id].tool_id} for run_id in displaced[:3]
        ]
        subject["group_truncated"] = truncated
        limits: set[str] = set()
        states = _rebuild(hop, displaced, segments, lots, run_map, data, config,
                          search_limits=limits, retained_origins=origins)
        limited = truncated or bool(limits)
        if not states:
            reason = "scope_limited" if limited else "unschedulable"
            details = tuple(sorted(limits))
            screened[memo_key] = (reason, details, limited)
            yield SkippedProposal(subject, reason, details, scope_limited=limited)
            continue
        yielded = 0
        dominant = "no_transfer_reduction"
        dominant_details: tuple[str, ...] = ()
        for state_segments, state_lots, assignments in states:
            # A campaign may finish later while all promised quantities stay
            # on time. Only the complete-plan evaluator can prove a loss.
            # Beam states share segment objects; the cleanup mutates in place.
            candidate = _remove_redundant_retained_tool_setups(
                [replace(segment) for segment in state_segments],
                protected_lot_ids=protected,
            )
            setups = physical_setups(candidate)
            if setups.count > current_setups.count or setups.minutes > current_setups.minutes:
                dominant = "would_add_setups"
                continue
            if (
                tool_transfers(candidate) >= current_transfers
                and (setups.count, setups.minutes)
                >= (current_setups.count, current_setups.minutes)
            ):
                continue
            yield Proposal(
                _sorted_segments(candidate),
                copy.copy(state_lots),
                subject={**subject, "assignments": dict(assignments)},
            )
            yielded += 1
        if limited:
            yield SkippedProposal(
                subject, "scope_limited", tuple(sorted(limits)), scope_limited=True,
            )
        if not yielded:
            reason = "scope_limited" if limited else dominant
            screened[memo_key] = (reason, (*dominant_details, *sorted(limits)), limited)
            if not limited:
                yield SkippedProposal(subject, reason, dominant_details)
    if len(hops) > _MAX_HOPS:
        yield SkippedProposal(
            {"key": "transfer_search_limit", "omitted": len(hops) - _MAX_HOPS},
            "scope_limited", (f"{len(hops)-_MAX_HOPS} hipóteses por analisar",),
            scope_limited=True,
        )


# ── Explanations of the transfers that remain (plan §6.4) ────────────────

_MAX_EXPLAINED = 20
_REASON_TEXT = {
    "protected": "envolve lote já iniciado ou posição fixada à mão",
    "unschedulable": "não foi encontrada alocação válida na {to} no âmbito verificado",
    "scope_limited": "comparação incompleta: atingido o limite de pesquisa",
    "group_too_large": "comparação incompleta: excede o grupo de seis campanhas",
    "not_eligible": "a referência não pode ser feita na {to}",
    "split_run": "a campanha já está repartida por máquinas",
    "no_transfer_reduction": "juntar na {to} não reduz as mudanças de ferramenta",
    "would_add_setups": "manter na {to} exigiria mais setups",
    "no_strict_gain": "manter na {to} não traz ganho",
    "physical": "manter na {to} violaria uma restrição física",
    "not_evaluated": "não avaliada neste cálculo ({stop})",
    "not_reevaluated": "avaliada num estado anterior do plano; não reavaliada",
}


def _speed_text(hop: TransferHop) -> str:
    ratio = hop.duration_ratio
    if ratio > 1.02:
        return f"na {hop.to_machine} a produção demora {ratio:.1f}× mais".replace(".", ",")
    if ratio < 0.98:
        return f"na {hop.to_machine} a produção demora {ratio:.1f}× o tempo".replace(".", ",")
    return ""


def _summary(hop: TransferHop, reason: str, details: list[str], stop: str) -> str:
    if reason == "contract":
        text = f"manter na {hop.to_machine} violaria o contrato sem perdas"
        if details:
            text += f": {details[0]}"
    elif reason == "would_delay":
        text = f"manter na {hop.to_machine} atrasaria: {details[0]}" if details else (
            f"manter na {hop.to_machine} atrasaria uma encomenda"
        )
    else:
        text = _REASON_TEXT.get(reason, reason).format(to=hop.to_machine, stop=stop)
    speed = _speed_text(hop)
    return f"{text} ({speed})" if speed and reason not in {"protected"} else text


def explain_remaining_transfers(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config,
    report: dict | None,
) -> dict[str, object]:
    """Why each tool transfer of the final plan is still there.

    A verdict is reused only when it was given on the final plan state;
    otherwise the transfer is marked as not (re)evaluated — an explanation of
    an earlier state is never shown as current (plan §5.6).
    """

    report = report or {}
    log = report.get("proposal_log") or {}
    final_signature = report.get("final_signature")
    stop = str(report.get("stop_reason") or "fora do âmbito")
    hops = enumerate_transfer_hops(segments, lots, data, config)
    items = []
    seen_blocks: set[tuple[str, tuple[str, ...]]] = set()
    for hop in hops:
        block = (hop.tool_id, hop.lot_ids)
        if block in seen_blocks:
            continue
        seen_blocks.add(block)
        entry = log.get(hop.key)
        if hop.protected:
            reason, details = "protected", []
        elif entry is None:
            reason, details = "not_evaluated", []
        elif entry.get("on_signature") != final_signature:
            reason, details = "not_reevaluated", []
        else:
            reason, details = str(entry.get("reason") or entry.get("outcome")), list(
                entry.get("details") or []
            )
        items.append({
            "key": hop.key, "tool_id": hop.tool_id, "kind": hop.kind,
            "from_machine": hop.from_machine, "to_machine": hop.to_machine,
            "day_idx": hop.day_idx, "lot_ids": list(hop.lot_ids[:6]),
            "duration_ratio": round(hop.duration_ratio, 2),
            "reason": reason, "details": details[:3],
            "summary": _summary(hop, reason, details, stop),
        })
    return {
        "remaining": tool_transfers(segments),
        "items": items[:_MAX_EXPLAINED],
        "omitted": max(0, len(items) - _MAX_EXPLAINED),
    }
