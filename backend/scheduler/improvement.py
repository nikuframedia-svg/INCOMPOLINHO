"""Automatic no-loss improvement contract and coordinator.

Generators propose complete candidate plans; this module decides whether a
candidate may replace the current one without a human decision. Admissibility
is strict: no customer order may lose on-time quantity or gain tardiness and
no subcontract dispatch milestone may slip. Candidates that trade one of these
for an aggregate gain are kept as trade-offs, never applied silently.

Among admissible candidates one canonical order decides (AGENTS.md §1):
delivery, then real anticipation (production start and finish of every lot,
in commercial priority order), then physical setups, setup minutes,
transfers and plan disturbance. Extra setups are a tie-break, never a veto:
an anticipation that adds a setup while preserving every order is accepted
(decision of 02/10/2026).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace

from backend.scheduler.jit_policy import lot_output_milestones
from backend.scheduler.policy import (  # noqa: F401  (re-exported)
    AnticipationKey,
    anticipation_better,
    anticipation_compare,
    anticipation_key,
    production_windows,
)
from backend.scheduler.priority import delivery_priority_key
from backend.scheduler.setup_identity import segment_setup_identity
from backend.scheduler.types import Lot, Segment
from backend.types import ClientDemandEntry, EngineData

# 2: anticipation vector ranks before setups; extra setups no longer veto.
CONTRACT_VERSION = 2
PROTECTED_CONTEXT_VERSION = 5

# Same precision as ``scoring.setup_time_min``. Both the phase reference and
# the last accepted candidate are checked, so rounding cannot drift upwards
# across iterations.
SETUP_MINUTES_DECIMALS = 1

_MISSING = math.inf

type OrderKey = tuple[str, str, int, int, int, int]


@dataclass(frozen=True, slots=True)
class OrderService:
    """Service level of one demand entry under chronological allocation."""

    covered_qty: int
    factory_covered_qty: int
    tardiness: float
    factory_tardiness: float


@dataclass(frozen=True, slots=True)
class SetupSummary:
    count: int
    minutes: float


@dataclass(slots=True)
class PlanFacts:
    """Everything the contract needs, computed once per materialised plan."""

    orders: dict[OrderKey, OrderService]
    subcontract_lateness: dict[tuple[str, str], float]
    setups: SetupSummary
    score: Mapping[str, object]
    signature: str
    anticipation: AnticipationKey = ()


@dataclass(slots=True)
class ContractVerdict:
    admissible: bool
    reasons: list[str] = field(default_factory=list)


# ── Order service ────────────────────────────────────────────────────────


def _canonical_demand_entries(data: EngineData) -> dict[str, list[ClientDemandEntry]]:
    """Client demand, falling back to canonical op demand for SKUs without it."""

    demands = {sku: list(entries) for sku, entries in data.client_demands.items()}
    for op in data.ops:
        if op.sku in data.client_demands:
            continue
        for day_idx, qty in enumerate(op.d):
            if int(qty) > 0:
                demands.setdefault(op.sku, []).append(
                    ClientDemandEntry(
                        client=str(op.client or ""),
                        sku=op.sku,
                        day_idx=day_idx,
                        date="",
                        order_qty=int(qty),
                        np_value=-int(qty),
                    )
                )
    return demands


def order_service(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
) -> dict[OrderKey, OrderService]:
    """Per-order service keyed by a stable identity, duplicates kept apart.

    Reuses ``compute_order_readiness`` (stock, production, twins and committed
    supplies). Identical entries receive an occurrence index in their stable
    allocation order instead of being merged.
    """

    from backend.analytics.order_tracking import compute_order_readiness

    detached = copy.copy(data)
    detached.client_demands = _canonical_demand_entries(data)
    readiness = compute_order_readiness(segments, lots, detached)
    result: dict[OrderKey, OrderService] = {}
    for sku in sorted(readiness):
        seen: Counter[tuple[str, str, int, int, int]] = Counter()
        for allocation in readiness[sku]:
            entry = allocation.entry
            base = (sku, entry.client, entry.day_idx, entry.order_qty, entry.np_value)
            occurrence = seen[base]
            seen[base] += 1
            result[(*base, occurrence)] = OrderService(
                covered_qty=int(allocation.covered_qty),
                factory_covered_qty=int(allocation.factory_covered_qty),
                tardiness=_lateness(allocation.ready_day, entry.day_idx),
                factory_tardiness=_lateness(allocation.factory_ready_day, entry.day_idx),
            )
    return result


def _lateness(ready_day: int | None, due_day: int) -> float:
    if ready_day is None:
        return _MISSING
    return float(max(0, ready_day - due_day))


def subcontract_lateness(
    segments: list[Segment],
    lots: list[Lot],
) -> dict[tuple[str, str], float]:
    """Days each subcontracted output finishes after its latest dispatch day."""

    finish: dict[tuple[str, str], int] = {}
    produced: dict[tuple[str, str], int] = defaultdict(int)
    for segment in segments:
        outputs = segment.twin_outputs or [("", segment.sku, segment.qty)]
        for op_id, _sku, qty in outputs:
            if int(qty) <= 0:
                continue
            key = (segment.lot_id, op_id)
            produced[key] += int(qty)
            finish[key] = max(finish.get(key, segment.day_idx), segment.day_idx)
    result = {}
    for lot in lots:
        for output in lot_output_milestones(lot):
            due = output.get("latest_subcontract_dispatch_day")
            if not output.get("is_subcontracted") or due is None:
                continue
            op_id = str(output.get("op_id") or "")
            key = (lot.id, op_id if lot.twin_outputs else "")
            if produced.get(key, 0) < int(output.get("qty", 0) or 0):
                result[(lot.id, op_id)] = _MISSING
            else:
                result[(lot.id, op_id)] = float(max(0, finish[key] - int(due)))
    return result


# ── Anticipation (AGENTS.md §1.3, plan §4.2) ─────────────────────────────


# ── Physical setups and signature ────────────────────────────────────────


def _machine_timelines(segments: Iterable[Segment]) -> dict[str, list[Segment]]:
    by_machine: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        by_machine[segment.machine_id].append(segment)
    for timeline in by_machine.values():
        timeline.sort(key=lambda s: (s.day_idx, s.start_min, s.end_min, s.lot_id))
    return by_machine


def physical_setups(segments: Iterable[Segment]) -> SetupSummary:
    """Count physical setups; fragments split by a shift boundary count once.

    A setup-bearing block continues the previous one when both belong to the
    same run and identity on the same machine and the previous block had not
    started producing yet. A reinstallation after use on another machine is a
    new setup block and therefore counts.
    """

    count = 0
    minutes = 0.0
    for timeline in _machine_timelines(segments).values():
        previous: Segment | None = None
        for segment in timeline:
            if segment.setup_min > 0:
                minutes += float(segment.setup_min)
                fragment = (
                    previous is not None
                    and previous.setup_min > 0
                    and previous.prod_min <= 0
                    and previous.run_id == segment.run_id
                    and segment_setup_identity(previous) == segment_setup_identity(segment)
                )
                if not fragment:
                    count += 1
            previous = segment
    return SetupSummary(count=count, minutes=round(minutes, SETUP_MINUTES_DECIMALS))


def tool_transfers(segments: Iterable[Segment]) -> int:
    """Times a tool changes machine along its chronological use."""

    by_tool: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        if segment.prod_min > 0 or segment.setup_min > 0:
            by_tool[segment.tool_id].append(segment)
    transfers = 0
    for uses in by_tool.values():
        uses.sort(key=lambda s: (s.day_idx, s.start_min, s.end_min, s.machine_id))
        transfers += sum(
            1 for before, after in zip(uses, uses[1:], strict=False)
            if before.machine_id != after.machine_id
        )
    return transfers


def _segment_physical_row(segment: Segment) -> tuple[object, ...]:
    return (
        segment.lot_id,
        segment.machine_id,
        segment.tool_id,
        int(segment.day_idx),
        int(segment.start_min),
        int(segment.end_min),
        int(segment.qty),
        round(float(segment.prod_min), 3),
        round(float(segment.setup_min), 3),
        tuple(sorted((str(o), str(s), int(q)) for o, s, q in segment.twin_outputs or [])),
    )


def physical_signature(segments: Iterable[Segment], lots: Iterable[Lot]) -> str:
    """Deduplication signature: times, resources, quantities and outputs only.

    Unlike the full fingerprint it ignores warnings, explanations and any
    metadata that does not change what the factory physically does.
    """

    payload = {
        "segments": sorted(_segment_physical_row(s) for s in segments),
        "lots": sorted(
            (
                lot.id,
                lot.machine_id,
                int(lot.qty),
                tuple(sorted((str(o), str(s), int(q)) for o, s, q in lot.twin_outputs or [])),
            )
            for lot in lots
        ),
    }
    encoded = json.dumps(payload, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def plan_facts(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    score: Mapping[str, object],
) -> PlanFacts:
    return PlanFacts(
        orders=order_service(segments, lots, data),
        subcontract_lateness=subcontract_lateness(segments, lots),
        setups=physical_setups(segments),
        score=score,
        signature=physical_signature(segments, lots),
        anticipation=anticipation_key(segments, lots),
    )


# ── Contract ─────────────────────────────────────────────────────────────


def no_loss_verdict(candidate: PlanFacts, reference: PlanFacts) -> ContractVerdict:
    """Apply the automatic-acceptance contract of candidate against reference.

    Aggregate indicators never compensate an individual regression. Setup
    count and minutes are preferences ranked by ``improvement_key``, not
    admissibility: physical setup validity is checked by plan validation.
    """

    reasons: list[str] = []
    for key, before in reference.orders.items():
        after = candidate.orders.get(key)
        label = f"{key[0]}/{key[1] or '-'} dia {key[2]}"
        if after is None:
            reasons.append(f"encomenda {label} desapareceu da alocacao")
            continue
        if after.covered_qty < before.covered_qty:
            reasons.append(f"encomenda {label}: quantidade no prazo diminui")
        if after.tardiness > before.tardiness:
            reasons.append(f"encomenda {label}: atraso aumenta")
        if after.factory_covered_qty < before.factory_covered_qty:
            reasons.append(f"encomenda {label}: cobertura de fabrica diminui")
        if after.factory_tardiness > before.factory_tardiness:
            reasons.append(f"encomenda {label}: atraso de fabrica aumenta")
    for key, before in reference.subcontract_lateness.items():
        if candidate.subcontract_lateness.get(key, _MISSING) > before:
            reasons.append(f"expedicao para subcontratacao do lote {key[0]} atrasa")
    return ContractVerdict(admissible=not reasons, reasons=reasons)


def improvement_key(
    facts: PlanFacts,
    *,
    transfers: int,
    changed_lots: int,
    displacement_min: float,
) -> tuple[object, ...]:
    """Canonical lexicographic order among admissible candidates (smaller wins).

    Delivery, then anticipation, then setups/minutes, transfers and plan
    disturbance. Compare keys only between plans with the same lots.
    """

    return (
        delivery_priority_key(facts.score),
        facts.anticipation,
        facts.setups.count,
        facts.setups.minutes,
        transfers,
        changed_lots,
        round(displacement_min, 3),
    )


def improvement_better(candidate_key: tuple, reference_key: tuple) -> bool:
    """Canonical preference between two ``improvement_key`` values.

    Delivery first; then anticipation with the policy tolerance (a lot may
    lose an hour or more only if a more urgent lot gains as much); then the
    exact key (exact minutes, setups, transfers, disturbance).
    """

    if candidate_key[0] != reference_key[0]:
        return candidate_key[0] < reference_key[0]
    decided = anticipation_compare(candidate_key[1], reference_key[1])
    if decided:
        return decided < 0
    return candidate_key < reference_key


def regresses_reference(candidate_key: tuple, reference_key: tuple) -> bool:
    """Guard of a chain of tolerant improvements against its starting plan:
    with the same delivery, no lot may drift an hour or more later unless a
    more urgent lot gained as much."""

    return candidate_key[0] == reference_key[0] and anticipation_compare(
        candidate_key[1], reference_key[1],
    ) > 0


def lot_changes(
    segments: Iterable[Segment],
    reference: Iterable[Segment],
) -> tuple[int, float]:
    """Lots whose physical rows differ, and summed start displacement (min)."""

    def by_lot(items: Iterable[Segment]) -> dict[str, list[tuple[object, ...]]]:
        grouped: dict[str, list[tuple[object, ...]]] = defaultdict(list)
        for segment in items:
            grouped[segment.lot_id].append(_segment_physical_row(segment))
        return {lot_id: sorted(rows) for lot_id, rows in grouped.items()}

    def start(rows: list[tuple[object, ...]]) -> float:
        _lot, _m, _t, day, start_min, *_ = rows[0]
        return float(day) * 1440.0 + float(start_min)

    current, before = by_lot(segments), by_lot(reference)
    changed = 0
    displacement = 0.0
    for lot_id in sorted(set(current) | set(before)):
        if current.get(lot_id) == before.get(lot_id):
            continue
        changed += 1
        if lot_id in current and lot_id in before:
            displacement += abs(start(current[lot_id]) - start(before[lot_id]))
    return changed, displacement


# ── Generator helpers ────────────────────────────────────────────────────

_MAX_TRADEOFF_REASONS = 5


def contract_verdict(
    candidate: list[Segment],
    reference: list[Segment],
    data: EngineData,
    *,
    candidate_lots: list[Lot],
    reference_lots: list[Lot] | None = None,
    candidate_score: Mapping[str, object] | None = None,
    reference_score: Mapping[str, object] | None = None,
) -> ContractVerdict:
    """No-loss verdict of one generator step against the plan it started from."""

    return no_loss_verdict(
        plan_facts(candidate, candidate_lots, data, candidate_score or {}),
        plan_facts(
            reference,
            reference_lots if reference_lots is not None else candidate_lots,
            data,
            reference_score or {},
        ),
    )


def tradeoff_proposal(kind: str, verdict: ContractVerdict, **details: object) -> dict[str, object]:
    """Bounded, descriptive summary of a physically valid move not applied.

    It records impact only; applying it requires the existing preview and
    confirmation path.
    """

    return {
        "kind": kind,
        "applied": False,
        "reasons": list(verdict.reasons[:_MAX_TRADEOFF_REASONS]),
        "reason_count": len(verdict.reasons),
        **details,
    }


# ── Verified search scopes ───────────────────────────────────────────────


def record_verified(
    report: dict | None,
    scope: str,
    segments: Iterable[Segment],
    lots: Iterable[Lot],
) -> dict:
    """Bind a completed search scope to the exact physical state it verified.

    Replaces inferring "already repaired" from warning text: a later change to
    the plan changes the signature and the scope must be searched again.
    """

    updated = dict(report or {})
    verified = dict(updated.get("verified") or {})
    verified[scope] = physical_signature(segments, lots)
    updated["verified"] = verified
    return updated


def is_verified(
    report: Mapping[str, object] | None,
    scope: str,
    segments: Iterable[Segment],
    lots: Iterable[Lot],
) -> bool:
    verified = (report or {}).get("verified") or {}
    signature = verified.get(scope) if isinstance(verified, Mapping) else None
    return bool(signature) and signature == physical_signature(segments, lots)


# ── Single improvement cycle (plan §5) ───────────────────────────────────

MAX_IMPROVEMENT_ROUNDS = 64
# Generic generators are capped per call. Finite reinsertion neighbourhoods
# exhaust their hypotheses subject to the shared deadline/evaluation budget.
MAX_PROPOSALS_PER_CALL = 12
MAX_SKIPPED_PER_CALL = 64
_MAX_PROPOSAL_LOG = 200
_MAX_REPORTED_TRADEOFFS = 10
_COVERAGE_KEYS = (
    "missing_lots", "missing_qty", "unexpected_lots", "overproduced_qty",
    "duplicate_twin_output_qty", "twin_output_mismatches",
)
_SUMMARY_KEYS = (
    "otd", "otd_d", "tardy_count", "total_tardiness", "setups", "setup_time_min",
    "production_time_cost", "left_shift_opportunities",
)


@dataclass(slots=True)
class Proposal:
    """What a generator suggests: a complete plan plus described trade-offs.

    ``subject`` identifies what the proposal tries to change (e.g. one tool
    transfer) so the evaluator's verdict can later explain the final plan.
    """

    segments: list[Segment]
    lots: list[Lot]
    tradeoffs: list[dict[str, object]] = field(default_factory=list)
    subject: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class SkippedProposal:
    """A hypothesis the generator could not turn into a candidate plan."""

    subject: dict[str, object]
    reason: str
    details: tuple[str, ...] = ()
    scope_limited: bool = False


class _ProposalLimitReached(Exception):
    """The declared scope contains hypotheses that were not exhausted."""


@dataclass(frozen=True, slots=True)
class Generator:
    name: str
    propose: object  # Callable[[list[Segment], list[Lot]], Proposal]
    # None is reserved for finite enumerations; the shared deadline still applies.
    proposal_limit: int | None = MAX_PROPOSALS_PER_CALL


@dataclass(slots=True)
class _Evaluated:
    segments: list[Segment]
    lots: list[Lot]
    facts: PlanFacts
    key: tuple[object, ...]
    transfers: int


def default_generators(data: EngineData, config, *, evaluation_plan=None) -> list[Generator]:
    """Existing routines, local changes first (plan §5.3)."""

    def earliest_legal(segments, lots):
        from backend.scheduler.scheduler import normalize_earliest_legal_plan

        if evaluation_plan is not None:
            complete_segments, complete_lots, complete_data = evaluation_plan(segments, lots)
            residual_ids = {lot.id for lot in lots}
            protected_ids = {lot.id for lot in complete_lots} - residual_ids
            # The complete inputs have no elapsed-day reservations; without
            # the replanning floor the compaction would move residual work
            # into the past and the whole proposal would be invalid.
            normalized = normalize_earliest_legal_plan(
                complete_segments,
                _with_replanning_floor(complete_lots, residual_ids, complete_data, floor_day),
                complete_data, config,
                annotate=False, protected_lot_ids=protected_ids,
            )
            if _lot_rows(normalized, protected_ids) != _lot_rows(complete_segments, protected_ids):
                return Proposal(segments, lots)
            return Proposal([item for item in normalized if item.lot_id in residual_ids], lots)
        return Proposal(
            normalize_earliest_legal_plan(segments, lots, data, config, annotate=False),
            lots,
        )

    def priority_inversions(segments, lots):
        from backend.scheduler.priority_normalization import repair_priority_inversions

        return allocate_in_complete_context(
            lambda complete_segments, complete_lots, complete_data: Proposal(
                repair_priority_inversions(complete_segments, complete_lots, complete_data, config),
                complete_lots,
            ), segments, lots,
        )

    def campaign_tail(segments, lots):
        from backend.scheduler.campaign_tail import repair_short_runs_after_merged_campaigns

        def propose(complete_segments, complete_lots, complete_data):
            result = repair_short_runs_after_merged_campaigns(
                complete_segments, complete_lots, complete_data, config,
            )
            return Proposal(result.segments, complete_lots, list(result.tradeoffs))

        return allocate_in_complete_context(propose, segments, lots)

    # Replanning boundary: the elapsed days blocked on every machine by the
    # protected-context reservations (none outside a frozen replan).
    blocked_everywhere = set.intersection(*(
        set(data.machine_blocked_days.get(machine.id, ())) for machine in data.machines
    )) if data.machines else set()
    floor_day = next(day for day in range(len(blocked_everywhere) + 1)
                     if day not in blocked_everywhere)

    def alternative_anticipation(segments, lots):
        from backend.scheduler.alternative_repair import anticipation_proposals

        return allocate_in_complete_context(
            lambda complete_segments, complete_lots, complete_data: anticipation_proposals(
                complete_segments, complete_lots, complete_data, config,
                not_before_abs=floor_day * 1440 if floor_day else None,
            ), segments, lots,
        )

    def group_reinsertion(size):
        def propose(segments, lots):
            from backend.scheduler.alternative_repair import group_reinsertion_proposals

            return allocate_in_complete_context(
                lambda complete_segments, complete_lots, complete_data:
                group_reinsertion_proposals(
                    complete_segments, complete_lots, complete_data, config, size=size,
                    not_before_abs=floor_day * 1440 if floor_day else None,
                ), segments, lots,
            )

        return propose

    def local_cpsat(segments, lots):
        from backend.scheduler.local_cpsat import local_cpsat_proposals

        return allocate_in_complete_context(
            lambda complete_segments, complete_lots, complete_data: local_cpsat_proposals(
                complete_segments, complete_lots, complete_data, config,
                not_before_abs=floor_day * 1440 if floor_day else None,
            ), segments, lots,
        )

    def alternative_machine(segments, lots):
        from backend.scheduler.alternative_repair import repair_alternative_machine_delivery

        def propose(complete_segments, complete_lots, complete_data):
            result = repair_alternative_machine_delivery(
                complete_segments, complete_lots, complete_data, config,
            )
            return Proposal(result.segments, result.lots, list(result.tradeoffs))

        return allocate_in_complete_context(propose, segments, lots)

    def shift_exchange(segments, lots):
        from backend.scheduler.shift_exchange import repair_shift_capacity_exchange

        def propose(complete_segments, complete_lots, complete_data):
            tradeoffs: list[dict[str, object]] = []
            exchanged = repair_shift_capacity_exchange(
                complete_segments, complete_lots, complete_data, config, tradeoffs=tradeoffs,
            )
            return Proposal(exchanged, complete_lots, tradeoffs)

        return allocate_in_complete_context(propose, segments, lots)

    def keep_tools_on_machine(segments, lots):
        from backend.scheduler.transfer_consolidation import consolidation_proposals

        return allocate_in_complete_context(
            lambda complete_segments, complete_lots, complete_data: consolidation_proposals(
                complete_segments, complete_lots, complete_data, config,
            ), segments, lots,
        )

    def allocate_in_complete_context(propose, segments, lots):
        """See retained mounts without freeing or moving protected production."""
        if evaluation_plan is None:
            produced = propose(segments, lots, data)
            yield from [produced] if isinstance(produced, Proposal) else produced
            return
        from backend.scheduler.canonical import preserved_lot_proofs

        complete_segments, complete_lots, complete_data = evaluation_plan(segments, lots)
        residual_ids = {lot.id for lot in lots}
        protected_ids = {lot.id for lot in complete_lots} - residual_ids
        protected_rows = _lot_rows(complete_segments, protected_ids)
        protected_lots = {lot.id: copy.deepcopy(lot) for lot in complete_lots
                          if lot.id in protected_ids}
        complete_data = copy.copy(complete_data)
        complete_data.preserved_lot_proofs = {
            **(complete_data.preserved_lot_proofs or {}),
            **preserved_lot_proofs(
                [item for item in complete_segments if item.lot_id in protected_ids],
                list(protected_lots.values()),
            ),
        }
        # The complete inputs have actual protected segments, not residual
        # reservations; allocating against both would consume capacity twice.
        produced = propose(complete_segments, complete_lots, complete_data)
        for proposal in [produced] if isinstance(produced, Proposal) else produced:
            if isinstance(proposal, SkippedProposal):
                yield proposal
            elif (
                _lot_rows(proposal.segments, protected_ids) != protected_rows
                or {lot.id: lot for lot in proposal.lots if lot.id in protected_ids}
                != protected_lots
            ):
                yield SkippedProposal(proposal.subject or {}, "protected_context_changed")
            else:
                yield replace(
                    proposal,
                    segments=[item for item in proposal.segments
                              if item.lot_id not in protected_ids],
                    lots=[lot for lot in proposal.lots if lot.id not in protected_ids],
                )

    # Local changes first, group moves last (§5.3). The first generator is
    # also the closing compaction pass (see ``improve_plan``). N0-N3:
    # same-machine compaction, then reinsertion of one, two and three
    # consecutive runs on every eligible machine; setup/transfer-focused
    # neighbourhoods follow.
    return [
        Generator("earliest_legal", earliest_legal),
        Generator("alternative_anticipation", alternative_anticipation, proposal_limit=None),
        Generator("pair_reinsertion", group_reinsertion(2), proposal_limit=None),
        Generator("triple_reinsertion", group_reinsertion(3), proposal_limit=None),
        Generator("local_cpsat", local_cpsat, proposal_limit=None),
        Generator("priority_inversions", priority_inversions),
        Generator("campaign_tail", campaign_tail),
        Generator("shift_exchange", shift_exchange),
        Generator("tool_transfers", keep_tools_on_machine),
        Generator("alternative_machine", alternative_machine),
    ]


def _with_replanning_floor(lots, movable_ids, data, floor_day: int):
    """Copies of the movable lots whose material floor is at least the
    replanning day. Used only to steer an allocator; the returned plan is
    validated against the original lots (a later start is always legal)."""

    if not floor_day:
        return lots
    from backend.scheduler.jit_policy import calendar_holidays, earliest_allowed_start

    holidays = calendar_holidays(data, -14, data.n_days + 30)
    return [
        replace(lot, material_release_day=max(earliest_allowed_start(lot, holidays), floor_day))
        if lot.id in movable_ids and earliest_allowed_start(lot, holidays) < floor_day
        else lot
        for lot in lots
    ]


def _score_plan(segments, lots, data, config) -> dict:
    from backend.scheduler.scoring import compute_score

    return compute_score(segments, lots, data, config=config, include_operational_audit=False)


@dataclass(frozen=True, slots=True)
class _Protection:
    """Protected lots of the phase reference, frozen before any proposal."""

    preserved_rows: dict[str, tuple[tuple[object, ...], ...]]
    violated_anchor_lots: frozenset[str]
    production_obligations: dict[str, tuple]


def _lot_rows(segments: Iterable[Segment], lot_ids: set[str]) -> dict[str, tuple]:
    rows: dict[str, list[tuple[object, ...]]] = defaultdict(list)
    for segment in segments:
        if segment.lot_id in lot_ids:
            rows[segment.lot_id].append(_segment_physical_row(segment))
    return {lot_id: tuple(sorted(items)) for lot_id, items in rows.items()}


def _anchor_violation_lots(segments, data, config) -> frozenset[str]:
    from backend.scheduler.validation import plan_anchor_violations

    return frozenset(
        str(violation.get("lot_id"))
        for violation in plan_anchor_violations(segments, data, config)
    )


def _protection(segments, lots, data, config) -> _Protection:
    from backend.scheduler.canonical import production_lot_obligations

    preserved = set(getattr(data, "preserved_lot_proofs", None) or {})
    return _Protection(
        preserved_rows=_lot_rows(segments, preserved),
        violated_anchor_lots=_anchor_violation_lots(segments, data, config),
        production_obligations=production_lot_obligations(lots),
    )


def _physically_valid(segments, lots, data, config, protection=None) -> list[str]:
    from backend.scheduler.canonical import production_lot_obligations
    from backend.scheduler.validation import coverage_metrics, validate_plan

    kinds = sorted({str(v.get("kind", "physical")) for v in validate_plan(
        segments, data, config, lots=lots,
    )})
    coverage = coverage_metrics(segments, lots)
    if any(int(coverage.get(key, 0) or 0) for key in _COVERAGE_KEYS):
        kinds.append("quantity_conservation")
    if protection is not None:
        if (
            len(lots) != len(protection.production_obligations)
            or production_lot_obligations(lots) != protection.production_obligations
        ):
            kinds.append("production_obligations_changed")
        # validate_plan does not check manual anchors, and a preserved lot
        # whose proof no longer matches is re-validated as an ordinary lot.
        # An improvement must leave both exactly as the reference had them.
        if _lot_rows(segments, set(protection.preserved_rows)) != protection.preserved_rows:
            kinds.append("preserved_lot_moved")
        if _anchor_violation_lots(segments, data, config) - protection.violated_anchor_lots:
            kinds.append("plan_anchor")
    return kinds


def _evaluate(segments, lots, data, config, reference_segments) -> _Evaluated:
    score = _score_plan(segments, lots, data, config)
    facts = plan_facts(segments, lots, data, score)
    changed, displacement = lot_changes(segments, reference_segments)
    transfers = tool_transfers(segments)
    key = improvement_key(
        facts,
        transfers=transfers,
        changed_lots=changed,
        displacement_min=displacement,
    )
    return _Evaluated(segments, lots, facts, key, transfers)


def _summary(evaluated: _Evaluated) -> dict[str, object]:
    return {key: evaluated.facts.score.get(key) for key in _SUMMARY_KEYS} | {
        "physical_setups": evaluated.facts.setups.count,
        "physical_setup_minutes": evaluated.facts.setups.minutes,
        "tool_transfers": evaluated.transfers,
    }


def _working_copy(evaluated: _Evaluated) -> tuple[list[Segment], list[Lot]]:
    """Per-object copies: a generator may mutate or replace segments and lots
    freely without touching the current candidate, at a fraction of the cost
    of a deep copy of the whole plan."""

    segments = []
    for segment in evaluated.segments:
        clone = copy.copy(segment)
        clone.left_shift_blockers = list(segment.left_shift_blockers)
        if segment.twin_outputs is not None:
            clone.twin_outputs = list(segment.twin_outputs)
        if segment.output_milestones is not None:
            clone.output_milestones = copy.deepcopy(segment.output_milestones)
        segments.append(clone)
    return segments, copy.deepcopy(evaluated.lots)


def _proposals(produced) -> Iterable:
    """A generator returns one Proposal or an iterable of proposals/skips."""

    if isinstance(produced, (Proposal, SkippedProposal)):
        return (produced,)
    return produced


def _bounded_proposals(
    produced, *, limit: int | None = MAX_PROPOSALS_PER_CALL,
) -> Iterable[Proposal | SkippedProposal]:
    """Keep generic calls bounded; finite searches use the coordinator's budget."""

    candidates = 0
    skipped = 0
    for proposal in _proposals(produced):
        if isinstance(proposal, SkippedProposal):
            if limit is not None and skipped >= MAX_SKIPPED_PER_CALL:
                raise _ProposalLimitReached
            skipped += 1
        else:
            if limit is not None and candidates >= limit:
                raise _ProposalLimitReached
            candidates += 1
        yield proposal


def improve_plan(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config,
    *,
    generators: list[Generator] | None = None,
    time_budget_s: float | None = None,
    max_rounds: int = MAX_IMPROVEMENT_ROUNDS,
    max_evaluations: int | None = None,
    evaluation_plan: Callable[
        [list[Segment], list[Lot]], tuple[list[Segment], list[Lot], EngineData]
    ] | None = None,
) -> tuple[list[Segment], list[Lot], dict[str, object]]:
    """Incorporate every admissible no-loss improvement found in scope.

    Generators only propose. One evaluator materialises, validates physics and
    conservation, applies the per-order contract against both the phase
    reference and the last accepted candidate, and accepts only a strict gain
    in the canonical order of ``improvement_key``. After each acceptance the search
    restarts (consequences propagate); visited physical states are skipped, so
    the cycle cannot oscillate. Rejected attempts never touch the current
    candidate. ``completed`` means completed within the declared scope, never
    a proof of global optimality.

    ``max_evaluations`` bounds the number of evaluated candidates (a budget
    that does not depend on machine load); ``time_budget_s`` stays a safety cap.
    Each outcome for a proposal with a ``subject`` is logged against the plan
    state it was judged on, so explanations are never reused for another state.
    ``evaluation_plan`` joins protected production for the no-loss comparison;
    allocation generators still allocate only their residual resource problem.
    Canonical compaction sees the complete physical sequence, with the joined
    lots protected, so retained mounting is not lost at the residual boundary.
    """

    import time
    from contextlib import nullcontext

    from backend.planning_control import (
        PlanningTimeout,
        execution_cache,
        planning_checkpoint,
        planning_scope,
        remaining_time,
    )

    started = time.monotonic()
    generators = (generators if generators is not None else default_generators(
        data, config, evaluation_plan=evaluation_plan,
    ))
    report: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "status": "not_evaluated",
        "stop_reason": None,
        "scopes": [generator.name for generator in generators],
        "candidates_evaluated": 0,
        "moves_accepted": 0,
        "accepted_by_scope": {},
        "duplicates_skipped": 0,
        "evaluations_by_scope": {},
        "skipped_by_scope": {},
        "limited_by_scope": {},
        "rejections": {},
        "proposal_log": {},
        "tradeoffs": {"count": 0, "items": []},
        "duration_ms": 0.0,
    }

    def out_of_time() -> bool:
        if time_budget_s is not None and time.monotonic() - started >= time_budget_s:
            return True
        left = remaining_time()
        return left is not None and left <= 0

    def reject(reason: str) -> None:
        rejections = report["rejections"]
        rejections[reason] = rejections.get(reason, 0) + 1

    def count(bucket: str, scope: str) -> None:
        counts = report[bucket]
        counts[scope] = counts.get(scope, 0) + 1

    def note(scope, subject, outcome, reason="", details=()) -> None:
        key = str((subject or {}).get("key") or "")
        log = report["proposal_log"]
        if not key or (key not in log and len(log) >= _MAX_PROPOSAL_LOG):
            return
        log[key] = {
            "scope": scope,
            "outcome": outcome,
            "reason": reason,
            "details": [str(item) for item in list(details)[:3]],
            "on_signature": current.facts.signature,
        }

    def keep_tradeoffs(items: list[dict[str, object]]) -> None:
        tradeoffs = report["tradeoffs"]
        for item in items:
            tradeoffs["count"] += 1
            if len(tradeoffs["items"]) < _MAX_REPORTED_TRADEOFFS:
                tradeoffs["items"].append(item)

    if not segments:
        report["status"] = "completed"
        report["stop_reason"] = "nothing_to_improve"
        return segments, lots, report
    if _physically_valid(segments, lots, data, config):
        # Improvement compares against a complete valid candidate only.
        report["stop_reason"] = "reference_invalid"
        return segments, lots, report

    protection = _protection(segments, lots, data, config)
    reference_segments = copy.deepcopy(segments)
    reference_lots = copy.deepcopy(lots)

    def materialize(candidate_segments, candidate_lots):
        if evaluation_plan is None:
            return candidate_segments, candidate_lots, data
        return evaluation_plan(candidate_segments, candidate_lots)

    full_reference, full_reference_lots, reference_data = materialize(
        reference_segments, reference_lots,
    )

    def evaluate(candidate_segments, candidate_lots, complete_plan):
        full_segments, full_lots, full_data = complete_plan
        evaluated = _evaluate(full_segments, full_lots, full_data, config, full_reference)
        # Generators allocate only the residual; facts and ranking use the
        # actual complete plan, not the D0 supplies used to reserve demand.
        evaluated.segments, evaluated.lots = candidate_segments, candidate_lots
        return evaluated

    reference = evaluate(reference_segments, reference_lots,
                         (full_reference, full_reference_lots, reference_data))
    current = reference
    visited = {reference.facts.signature}
    report["reference"] = _summary(reference)
    stop_reason = "no_admissible_improvement"
    evaluations = 0

    def budget_scope(limit_s: float | None):
        """Child deadline, checked inside generators: a long generator call is
        interrupted instead of overrunning the phase budget."""

        if limit_s is None:
            return nullcontext()
        return planning_scope(timeout_s=max(0.0, limit_s - (time.monotonic() - started)))

    def consider(scope: str, proposal) -> bool:
        """Evaluate one proposal; True when it became the current candidate."""

        nonlocal current, evaluations
        if isinstance(proposal, SkippedProposal):
            count("skipped_by_scope", scope)
            note(scope, proposal.subject, "skipped", proposal.reason, proposal.details)
            return False
        keep_tradeoffs(proposal.tradeoffs)
        complete_plan = materialize(proposal.segments, proposal.lots)
        signature = physical_signature(complete_plan[0], complete_plan[1])
        if signature in visited:
            report["duplicates_skipped"] += 1
            return False
        visited.add(signature)
        evaluations += 1
        report["candidates_evaluated"] += 1
        count("evaluations_by_scope", scope)
        physical = _physically_valid(
            proposal.segments, proposal.lots, data, config, protection,
        )
        if physical:
            reject(f"{scope}:physical")
            note(scope, proposal.subject, "rejected", "physical", physical)
            return False
        candidate = evaluate(proposal.segments, proposal.lots, complete_plan)
        losses = list(dict.fromkeys([
            *no_loss_verdict(candidate.facts, current.facts).reasons,
            *no_loss_verdict(candidate.facts, reference.facts).reasons,
        ]))
        if losses:
            reject(f"{scope}:contract")
            note(scope, proposal.subject, "rejected", "contract", losses)
            keep_tradeoffs([tradeoff_proposal(scope, ContractVerdict(False, losses))])
            return False
        if not improvement_better(candidate.key, current.key) or regresses_reference(
            candidate.key, reference.key,
        ):
            reject(f"{scope}:no_strict_gain")
            note(scope, proposal.subject, "rejected", "no_strict_gain")
            return False
        note(scope, proposal.subject, "accepted")
        current = candidate
        report["moves_accepted"] += 1
        count("accepted_by_scope", scope)
        return True

    # The first generator is the compaction (earliest legal start). Every
    # other accepted move is immediately followed by it, so the candidate
    # handed back never keeps time released by a group move unused. If the
    # budget ends before that compaction, the last settled candidate is
    # returned instead of a partially verified one (§5.6, §9.3).
    compacting = generators[0] if generators else None
    settled = {"candidate": current, "moves": 0, "accepted_by_scope": {}, "proposal_log": {}}

    def settle() -> None:
        settled["candidate"] = current
        settled["moves"] = report["moves_accepted"]
        settled["accepted_by_scope"] = dict(report["accepted_by_scope"])
        settled["proposal_log"] = copy.deepcopy(report["proposal_log"])

    def compact() -> None:
        produced = compacting.propose(*_working_copy(current))
        limited = False
        try:
            for proposal in _bounded_proposals(produced, limit=compacting.proposal_limit):
                if isinstance(proposal, SkippedProposal) and proposal.scope_limited:
                    limited = True
                if consider(compacting.name, proposal):
                    break
        except _ProposalLimitReached:
            count("limited_by_scope", compacting.name)
            raise
        if limited:
            count("limited_by_scope", compacting.name)
            raise _ProposalLimitReached
        settle()

    def search() -> str:
        """Rounds of generators until none finds an admissible improvement.

        After an acceptance the next round starts with the generator that
        just succeeded (its consequences are explored first, e.g. the next
        transfer), then every other generator in order (§5.5). A round only
        ends the search when all generators failed on the current plan.
        """

        start = 0
        for _round in range(max_rounds):
            accepted = False
            limited = False
            order = [*generators[start:], *generators[:start]]
            for position, generator in enumerate(order):
                planning_checkpoint()
                if out_of_time():
                    return "budget"
                produced = generator.propose(*_working_copy(current))
                scope_limited = False
                try:
                    for proposal in _bounded_proposals(produced, limit=generator.proposal_limit):
                        planning_checkpoint()
                        if out_of_time():
                            return "budget"
                        if max_evaluations is not None and evaluations >= max_evaluations:
                            return "evaluation_limit"
                        if isinstance(proposal, SkippedProposal) and proposal.scope_limited:
                            scope_limited = True
                        if consider(generator.name, proposal):
                            accepted = True
                            break
                except _ProposalLimitReached:
                    scope_limited = True
                if scope_limited:
                    count("limited_by_scope", generator.name)
                    limited = True
                if accepted:
                    if generator is compacting:
                        settle()
                    else:
                        compact()
                    start = (start + position) % len(generators)
                    break
            if not accepted:
                return "search_limit" if limited else "no_admissible_improvement"
        return "search_limit"

    try:
        with budget_scope(time_budget_s):
            try:
                stop_reason = search()
            finally:
                cache = execution_cache("run_placement")
                report["allocation_cache"] = {
                    **cache.get("stats", {}), "entries": len(cache.get("entries", {})),
                }
    except PlanningTimeout:
        stop_reason = "budget"
    except _ProposalLimitReached:
        stop_reason = "search_limit"
    if current is not settled["candidate"]:
        report["rolled_back_moves"] = report["moves_accepted"] - settled["moves"]
        report["moves_accepted"] = settled["moves"]
        report["accepted_by_scope"] = settled["accepted_by_scope"]
        report["proposal_log"] = settled["proposal_log"]
        current = settled["candidate"]

    report["stop_reason"] = stop_reason
    report["status"] = "completed" if stop_reason == "no_admissible_improvement" else "partial"
    report["final"] = _summary(current)
    report["final_signature"] = current.facts.signature
    report["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
    return current.segments, current.lots, report


def improvement_gate_summary(
    report: Mapping[str, object] | None,
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config,
) -> dict[str, object]:
    """Compact, informational view of the improvement phase for gate_report.

    It never changes the apply decision (plan §7.2).
    """

    from backend.scheduler.transfer_consolidation import explain_remaining_transfers

    report = _report_for_schedule(report, segments, lots) or {}
    return {
        "contract_version": report.get("contract_version", CONTRACT_VERSION),
        "status": report.get("status", "not_evaluated"),
        "stop_reason": report.get("stop_reason"),
        "moves_accepted": report.get("moves_accepted", 0),
        "accepted_by_scope": dict(report.get("accepted_by_scope") or {}),
        "rolled_back_moves": report.get("rolled_back_moves", 0),
        "reference": report.get("reference"),
        "final": report.get("final"),
        "tool_transfers": explain_remaining_transfers(segments, lots, data, config, report),
    }


def _report_for_schedule(report, segments, lots):
    if report and report.get("final_signature") and (
        report["final_signature"] != physical_signature(segments, lots)
    ):
        return {"status": "not_evaluated", "stop_reason": "candidate_changed"}
    return report


def attach_improvement_summary(result, data, config) -> None:
    """Reattach current evidence after rebuilding gates; never run a search."""
    from backend.scheduler.canonical import result_validation_data

    result.improvement_report = _report_for_schedule(
        result.improvement_report, result.segments, result.lots,
    )
    if result.gate_report is not None:
        result.gate_report["improvement"] = improvement_gate_summary(
            result.improvement_report, result.segments, result.lots,
            result_validation_data(data, result), config,
        )
