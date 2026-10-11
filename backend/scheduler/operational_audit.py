"""Operational sequencing audit for a material-release production plan.

Physical validation answers whether a plan can run.  This module answers the
separate business question: whether the final sequence still contains an
obvious earlier slot or lets a less urgent lot interrupt an urgent campaign.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.config.types import FactoryConfig
from backend.scheduler.gap_filling import PartialGapOpportunity, find_gap_opportunities
from backend.scheduler.jit_policy import calendar_holidays, earliest_allowed_start
from backend.scheduler.material_quantities import factory_readiness, output_release_day
from backend.scheduler.policy import measured_outputs
from backend.scheduler.priority import lot_priority_key, output_priority_key
from backend.scheduler.priority_normalization import _build_priority_rotation_candidates
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData

# Work budget for the one slow part of the audit: proving, by validated
# counterfactual rotations judged with the improvement loop's own contract,
# which priority-order anomalies are avoidable.  It is a count of anomalies to
# classify, not a wall-clock cap, so the same plan always gets the same status
# whatever the machine load.  A plan with more anomalies still gets its 32
# most urgent movable anomalies classified (proven findings first), keeps
# every cheap metric exact and reports the rest as pending ("por avaliar"),
# never as a pass.  The cheap metrics (gaps, campaign interruptions, tool
# inversions and the anomaly count itself) are always computed in full.
# 32 (was 16) covers the 14-20 anomalies the loop leaves on the real cases
# (review b3r2 #3); the audit time is measured in the B3/B4 notes (< 2 s).
PRIORITY_CLASSIFICATION_MAX_ANOMALIES = 32
_UNSET: Any = object()


def build_operational_audit(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig | None = None,
    *,
    gap_opportunities: list[PartialGapOpportunity] | None = None,
    classification_budget: int | None = _UNSET,
) -> dict[str, Any]:
    """Audit the final sequence; ``status`` says whether every metric is proven.

    ``status == "not_evaluated"`` means the cheap metrics are exact but the
    avoidable priority anomalies exceed the classification work budget.  That
    is never a pass: the gate reports the audit as pending ("por avaliar").
    By default only per-delivery plans are bounded (their anomaly count is
    large); pass ``classification_budget=None`` for an unbounded audit.
    """

    from backend.scheduler.quantity_dispatch import has_quantity_releases

    quantity_plan = has_quantity_releases(lots)
    budget = (
        (PRIORITY_CLASSIFICATION_MAX_ANOMALIES if quantity_plan else None)
        if classification_budget is _UNSET
        else classification_budget
    )
    if not quantity_plan:
        return _build_operational_audit(
            segments, lots, data, config,
            gap_opportunities=gap_opportunities,
            classification_budget=budget,
        )
    import copy

    from backend.planning_control import execution_cache
    from backend.plans.serialize import value_fingerprint

    cache = execution_cache("quantity_operational_audit")
    key = value_fingerprint((segments, lots, data, config, gap_opportunities, budget))
    if key in cache:
        return copy.deepcopy(cache[key])
    result = _build_operational_audit(
        segments, lots, data, config,
        gap_opportunities=gap_opportunities,
        classification_budget=budget,
    )
    if len(cache) >= 4:
        cache.pop(next(iter(cache)))
    cache[key] = copy.deepcopy(result)
    return result


# ── Priority-order anomalies, per delivery (B4.4) ─────────────────────────
#
# A run is ranked by the most urgent delivery it actually makes, with that
# delivery's own material release, the unit the builder places (a portion,
# ``quantity_dispatch._portion_lot``).  Ranking a run by its whole lot (first
# delivery, first release) reported every later delivery run of a lot as
# "urgent work blocked" by whatever ran before it, although its material was
# not yet released: 86% of the 1800-4700 anomalies of the real plans.
# Lots measured as a whole (``policy.measured_outputs`` is ``None``: legacy,
# twin v1, at most one delivery per side) keep exactly the lot view, so a plan
# without per-delivery lots gets the anomalies of
# ``priority_normalization.find_priority_order_anomalies`` unchanged.


# A run whose pieces are all surplus (economic or co-produced stock) makes no
# delivery (``policy._delivery_windows``): it ranks after every delivery, so
# placed before released urgent work it is reported as the blocking run, and
# it is never itself "urgent work blocked".  Its output is ``"surplus"`` and
# its rupture day ``None`` in the anomaly detail.
_SURPLUS = "surplus"
_NO_DAY = 2**62
_SURPLUS_KEY = (_NO_DAY, _NO_DAY, 0, _NO_DAY, _NO_DAY, _NO_DAY, 0)


def _run_units(
    segments: list[Segment],
    lots_by_id: dict[str, Lot],
    holidays: set[int],
) -> dict[tuple[str, str], list[tuple[tuple, int, Lot, int | str | None]]]:
    """(machine, run) -> [(priority key, release floor, lot, output index)].

    A lot measured as a whole is one unit (index ``None``). A lot measured
    per delivery gives one unit per demand delivery the run makes pieces of,
    pieces assigned first-in-first-out per side exactly as
    ``material_quantities.delivery_readiness``. The pieces of a surplus
    output belong to no delivery, as in ``policy._delivery_windows``: a run
    that makes only surplus gets one unit ranked after every delivery
    (index ``"surplus"``, see ``_SURPLUS_KEY``); a run that also makes a
    delivery is ranked and released by its deliveries alone.
    """

    measured = {
        lot_id: lot for lot_id, lot in lots_by_id.items()
        if measured_outputs(lot) is not None
    }
    runs: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, segment in enumerate(segments):
        if segment.prod_min > 0 and segment.lot_id in lots_by_id:
            runs[(segment.machine_id, segment.run_id)].append(index)
    served: dict[int, set[tuple[str, int]]] = defaultdict(set)
    surplus: dict[int, set[tuple[str, int]]] = defaultdict(set)
    if measured:
        records = factory_readiness(
            list(measured.values()),
            [segment for segment in segments if segment.lot_id in measured],
            missing_day=0,
        )
        # Indexes of ``factory_readiness`` are into the filtered list.
        positions = [
            index for index, segment in enumerate(segments) if segment.lot_id in measured
        ]
        for record in records:
            target = served if record.is_demand else surplus
            for piece in record.slices:
                if piece.qty > 0:
                    target[positions[piece.segment_index]].add((record.lot_id, record.index))

    units: dict[tuple[str, str], list[tuple[tuple, int, Lot, int | str | None]]] = {}
    for key, indexes in runs.items():
        found: dict[tuple[str, int | None], tuple[tuple, int, Lot, int | str | None]] = {}
        surplus_only: dict[str, tuple[tuple, int, Lot, int | str | None]] = {}
        for index in indexes:
            lot = lots_by_id[segments[index].lot_id]
            if lot.id in measured:
                outputs = served.get(index)
                if not outputs and surplus.get(index):
                    if lot.id not in surplus_only:
                        surplus_only[lot.id] = (
                            (*_SURPLUS_KEY, str(lot.id), -1),
                            min(
                                _output_floor(lot, _milestone(lot, position), holidays)
                                for _lot_id, position in surplus[index]
                            ),
                            lot, _SURPLUS,
                        )
                    continue
            else:
                outputs = None
            if not outputs:
                if (lot.id, None) not in found:
                    found[(lot.id, None)] = (
                        output_priority_key(lot), earliest_allowed_start(lot, holidays),
                        lot, None,
                    )
                continue
            for lot_id, position in outputs:
                if (lot_id, position) in found:
                    continue
                output = (lot.output_milestones or [])[position]
                found[(lot_id, position)] = (
                    output_priority_key(lot, position),
                    _output_floor(lot, output, holidays),
                    lot, position,
                )
        units[key] = list(found.values()) or list(surplus_only.values())
    return units


def _milestone(lot: Lot, position: int) -> dict:
    """Output milestone at ``position``; ``{}`` for undeclared production."""

    outputs = lot.output_milestones or []
    return outputs[position] if 0 <= position < len(outputs) else {}


def _output_floor(lot: Lot, output: dict, holidays: set[int]) -> int:
    """Earliest productive start of one delivery: its own material release."""

    try:
        return output_release_day(output)
    except (KeyError, TypeError, ValueError):
        return earliest_allowed_start(lot, holidays)


def find_output_priority_anomalies(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
) -> list[dict[str, Any]]:
    """Less urgent run before a more urgent one that could have gone first.

    Same pairs and fields as ``find_priority_order_anomalies``, with each run
    ranked by its most urgent delivery and released by the earliest release
    among the deliveries it makes (see ``_run_units``). ``urgent_output`` and
    ``blocking_output`` name the deciding delivery (its position in the lot's
    milestones, ``None`` for a lot ranked as a whole).
    """

    lots_by_id = {lot.id: lot for lot in lots}
    holidays = calendar_holidays(
        data,
        min((segment.day_idx for segment in segments), default=0) - 7,
        data.n_days + 7,
    )
    by_run: dict[tuple[str, str], list[Segment]] = defaultdict(list)
    for segment in segments:
        if segment.prod_min > 0:
            by_run[(segment.machine_id, segment.run_id)].append(segment)
    units = _run_units(segments, lots_by_id, holidays)
    timelines: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (machine_id, run_id), run_segments in by_run.items():
        run_units = units.get((machine_id, run_id))
        if not run_units:
            continue
        key, _floor, lot, output = min(run_units, key=lambda unit: unit[0])
        timelines[machine_id].append(
            {
                "run_id": run_id,
                "key": key,
                "lot": lot,
                "output": output,
                "start": min(_position(segment) for segment in run_segments),
                "floor": min(unit[1] for unit in run_units),
            }
        )

    detail: list[dict[str, Any]] = []
    for machine_id, runs in timelines.items():
        ordered = sorted(runs, key=lambda run: (run["start"], run["run_id"]))
        for index, earlier in enumerate(ordered):
            for later in ordered[index + 1 :]:
                # Dates and explicit business priority only: quantity and id
                # are tie-breakers, never a commercial inversion.
                if later["key"][:5] >= earlier["key"][:5]:
                    continue
                if later["floor"] > earlier["floor"]:
                    continue
                detail.append(
                    {
                        "machine_id": machine_id,
                        "urgent_run_id": later["run_id"],
                        "urgent_lot_id": later["lot"].id,
                        "urgent_output": later["output"],
                        "blocking_run_id": earlier["run_id"],
                        "blocking_lot_id": earlier["lot"].id,
                        "blocking_output": earlier["output"],
                        "urgent_rupture_day": later["key"][0],
                        "blocking_rupture_day": _rupture_day(earlier),
                        "urgent_release_day": later["floor"],
                        "blocking_release_day": earlier["floor"],
                        "blocking_reason": None,
                        "blocking_reasons": [],
                        "verification_status": "counterfactual_required",
                    }
                )
    return sorted(
        detail,
        key=lambda item: (
            item["urgent_rupture_day"],
            item["machine_id"],
            item["urgent_lot_id"],
            item["blocking_lot_id"],
        ),
    )


def _rupture_day(run: dict[str, Any]) -> int | None:
    return None if run["output"] == _SURPLUS else run["key"][0]


def classify_priority_order_anomalies(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    anomalies: list[dict[str, Any]] | None = None,
    max_classifications: int | None = None,
) -> list[dict[str, Any]]:
    """Prove whether each per-delivery anomaly is movable or blocked.

    An anomaly is avoidable (``permutable``) only when a rotation of the runs
    is a move the improvement loop itself would accept (AGENTS §1, see
    ``_loop_verdict``) and leaves fewer anomalies. Only the first
    ``max_classifications`` of ``anomalies`` (default: every anomaly of the
    plan) are classified; the rest are returned ``not_evaluated`` with
    reason ``audit_budget``, never as a pass (AGENTS §6).
    """

    every = find_output_priority_anomalies(segments, lots, data)
    details = every if anomalies is None else anomalies
    before_count = len(every)
    limit = len(details) if max_classifications is None else max(0, int(max_classifications))
    contract = _LoopContract(segments, lots, data, config) if details[:limit] else None
    classified: list[dict[str, Any]] = []
    for index, detail in enumerate(details):
        if index >= limit:
            classified.append({**detail, **_PENDING})
            continue
        status = "counterfactual_unavailable"
        reasons: list[str] = []
        candidates = _build_priority_rotation_candidates(segments, lots, data, config, detail)
        for candidate in candidates or []:
            status, reasons = contract.verdict(candidate)
            if status is not None:
                continue
            if len(find_output_priority_anomalies(candidate, lots, data)) < before_count:
                status, reasons = "permutable", []
                break
            status = "counterfactual_required"
            reasons = ["counterfactual_did_not_reduce_priority_anomalies"]
        classified.append(
            {
                **detail,
                "verification_status": status,
                "blocking_reason": reasons[0] if reasons else None,
                "blocking_reasons": reasons,
            }
        )
    return classified


class _LoopContract:
    """The improvement loop's acceptance rule, applied to one rotation.

    The same functions ``improvement.improve_plan`` accepts a move with, in
    the order of AGENTS §1: physics and quantity conservation (the checks of
    ``_physically_valid``) with protected rows and manual anchors unchanged;
    no individual order loses quantity or gains lateness
    (``no_loss_verdict``); then the plan must be better under
    the canonical comparator (``improvement_better``: delivery, then the
    per-delivery anticipation with the policy tolerance, then setups). An
    aggregate delivery figure never decides on its own. The current plan is
    evaluated once and every rotation is validated once.
    """

    def __init__(self, segments, lots, data, config) -> None:
        from backend.scheduler import improvement
        from backend.scheduler.policy import anticipation_order

        self._improvement = improvement
        self._segments, self._lots, self._data, self._config = segments, lots, data, config
        self._order = anticipation_order(lots)
        # Every rotation keeps exactly these lots, so the loop's check that
        # production obligations are unchanged always holds here; only the
        # protected rows and the manual anchors are checked per rotation.
        preserved = set(getattr(data, "preserved_lot_proofs", None) or {})
        self._preserved_rows = improvement._lot_rows(segments, preserved)
        self._violated_anchors = improvement._anchor_violation_lots(segments, data, config)
        self._current = improvement._evaluate(
            segments, lots, data, config, segments, self._order,
        )

    def verdict(self, candidate: list[Segment]) -> tuple[str | None, list[str]]:
        """``(None, [])`` when the loop would accept ``candidate``."""

        from backend.scheduler.validation import coverage_metrics, validate_plan

        improvement = self._improvement
        # The checks of ``improvement._physically_valid``; a rotation is a new
        # plan by construction, so it skips the memo key (B4.2).
        violations = validate_plan(
            candidate, self._data, self._config, lots=self._lots, memo=False,
        )
        kinds = sorted({str(item.get("kind", "physical")) for item in violations})
        coverage = coverage_metrics(candidate, self._lots)
        if any(int(coverage.get(key, 0) or 0) for key in improvement._COVERAGE_KEYS):
            kinds.append("quantity_conservation")
        if improvement._lot_rows(candidate, set(self._preserved_rows)) != self._preserved_rows:
            kinds.append("preserved_lot_moved")
        if (
            improvement._anchor_violation_lots(candidate, self._data, self._config)
            - self._violated_anchors
        ):
            kinds.append("plan_anchor")
        if kinds:
            return "resource_blocked", kinds
        evaluated = improvement._evaluate(
            candidate, self._lots, self._data, self._config, self._segments,
            self._order, violations,
        )
        loss = improvement.no_loss_verdict(evaluated.facts, self._current.facts)
        if not loss.admissible:
            return "delivery_blocked", list(loss.reasons)
        if improvement.improvement_better(evaluated.key, self._current.key):
            return None, []
        if evaluated.key[0] != self._current.key[0]:  # delivery ranks first
            return "delivery_blocked", ["blocked_by_delivery_objective"]
        return "counterfactual_required", ["counterfactual_not_earlier"]


_PENDING = {
    "verification_status": "not_evaluated",
    "blocking_reason": "audit_budget",
    "blocking_reasons": ["audit_budget"],
}


def _classified_priority_anomalies(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    budget: int | None,
    *,
    preserved_lot_ids: set[str],
    anchored_lot_ids: set[str],
) -> tuple[list[dict[str, Any]], bool]:
    """Return (anomalies, every anomaly explained or classified).

    Pairs with a protected lot are explained first (history and manual
    positions are never moved by a recalculation), so the work budget is
    spent only on pairs a recalculation could change. Over budget, the
    ``budget`` most urgent movable pairs are classified (proven findings
    first) and the rest stay ``not_evaluated``: the audit stays pending
    ("por avaliar", AGENTS §6), never a pass. The split depends only on the
    plan, never on time; an outer deadline or a cancellation still stops a
    classification through the checkpoints inside it.
    """

    frozen_lot_ids = preserved_lot_ids | anchored_lot_ids
    anomalies = find_output_priority_anomalies(segments, lots, data)
    movable: list[dict[str, Any]] = []
    protected: dict[int, dict[str, Any]] = {}
    for position, item in enumerate(anomalies):
        pair = {item.get("urgent_lot_id"), item.get("blocking_lot_id")}
        if not pair & frozen_lot_ids:
            movable.append(item)
            continue
        # Anchored lots also carry a preservation proof in a protected
        # replan; the explicit manual position is the reason to report.
        historical = bool(pair & (preserved_lot_ids - anchored_lot_ids))
        reason = "historical_lot_locked" if historical else "manual_anchor"
        protected[position] = {
            **item,
            "verification_status": "historical_locked" if historical else "manual_locked",
            "blocking_reason": reason,
            "blocking_reasons": [reason],
        }
    if budget is None:
        # Unbounded audit: every anomaly is classified, then explained.
        checked = classify_priority_order_anomalies(segments, lots, data, config)
        return [protected.get(position, item) for position, item in enumerate(checked)], True
    limit = max(0, int(budget))
    complete = len(movable) <= limit
    if not movable:
        checked = []
    elif limit == 0 and not complete:
        checked = [{**item, **_PENDING} for item in movable]
    else:
        checked = classify_priority_order_anomalies(
            segments, lots, data, config,
            anomalies=movable,
            max_classifications=None if complete else limit,
        )
    merged = iter(checked)
    return [
        protected[position] if position in protected else next(merged)
        for position in range(len(anomalies))
    ], complete


def _build_operational_audit(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig | None = None,
    *,
    gap_opportunities: list[PartialGapOpportunity] | None = None,
    classification_budget: int | None = None,
) -> dict[str, Any]:
    """Return stable metrics and evidence for final-plan sequencing quality."""

    anchored_lot_ids = {
        str(anchor.lot_id) for anchor in getattr(data, "plan_anchors", None) or []
    }
    preserved_lot_ids = set(getattr(data, "preserved_lot_proofs", None) or {})
    frozen_lot_ids = preserved_lot_ids | anchored_lot_ids
    all_left_shift = _left_shift_detail(
        segments,
        lots,
        data,
        config or FactoryConfig(),
        gap_opportunities=gap_opportunities,
    )
    # A gap in front of a protected lot is explained, not actionable: history
    # and manual positions are never moved by a recalculation (plan §6.4).
    left_shift_detail = []
    protected_left_shift_detail = []
    for item in all_left_shift:
        lot_id = item.get("lot_id")
        # Anchored lots also carry a preservation proof in a protected
        # replan; the explicit manual position is the reason to report.
        reason = (
            "manual_anchor" if lot_id in anchored_lot_ids
            else "historical_lot_locked" if lot_id in preserved_lot_ids
            else None
        )
        if reason is None:
            left_shift_detail.append(item)
        else:
            protected_left_shift_detail.append({**item, "protection": reason})
    interruption_detail = _lower_priority_campaign_interruptions(segments, lots)
    priority_detail, classified = _classified_priority_anomalies(
        segments,
        lots,
        data,
        config or FactoryConfig(),
        classification_budget,
        preserved_lot_ids=preserved_lot_ids,
        anchored_lot_ids=anchored_lot_ids,
    )
    tool_priority_detail = released_tool_priority_inversion_detail(
        segments,
        lots,
        data,
        config or FactoryConfig(),
        frozen_lot_ids=frozen_lot_ids,
    )
    # Only a validated rotation that reduces the anomaly count proves the
    # current order avoidable. A neutral counterfactual remains useful audit
    # evidence, but must not block an otherwise executable plan.
    avoidable_priority = sum(
        item["verification_status"] == "permutable" for item in priority_detail
    )
    pending_priority = sum(
        item["verification_status"] == "not_evaluated" for item in priority_detail
    )
    status: dict[str, Any] = (
        {"status": "evaluated"}
        if classified
        else {
            "status": "not_evaluated",
            "stop_reason": "audit_budget",
            "unevaluated_metrics": ["avoidable_priority_order_anomalies"],
            # The avoidable count is then a lower bound: only the most
            # urgent anomalies, up to the work budget, were classified.
            "unevaluated_priority_order_anomalies": pending_priority,
        }
    )
    return {
        **status,
        "left_shift_opportunities": len(left_shift_detail),
        "lower_priority_campaign_interruptions": len(interruption_detail),
        "priority_order_anomalies": len(priority_detail),
        "avoidable_priority_order_anomalies": avoidable_priority,
        "released_tool_priority_inversions": len(tool_priority_detail),
        "left_shift_detail": left_shift_detail,
        "protected_left_shift_detail": protected_left_shift_detail,
        "campaign_interruption_detail": interruption_detail,
        "priority_order_detail": priority_detail,
        "released_tool_priority_detail": tool_priority_detail,
    }


def released_tool_priority_inversion_detail(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    frozen_lot_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Find released urgent runs placed after later work on one physical tool."""

    frozen = frozen_lot_ids or set()
    lots_by_id = {lot.id: lot for lot in lots}
    holidays = calendar_holidays(
        data,
        min((segment.day_idx for segment in segments), default=0) - 14,
        max(data.n_days, max((segment.day_idx for segment in segments), default=0)) + 30,
    )
    by_run: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        if segment.end_min > segment.start_min:
            by_run[segment.run_id].append(segment)

    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run_id, run_segments in by_run.items():
        run_lots = [
            lots_by_id[lot_id]
            for lot_id in dict.fromkeys(segment.lot_id for segment in run_segments)
            if lot_id in lots_by_id
        ]
        if not run_lots or any(lot.id in frozen for lot in run_lots):
            continue
        urgent = min(run_lots, key=lot_priority_key)
        by_tool[run_segments[0].tool_id].append(
            {
                "run_id": run_id,
                "lot": urgent,
                "start": min(_position(segment) for segment in run_segments),
                "end": max((segment.day_idx, segment.end_min) for segment in run_segments),
                "release": min(earliest_allowed_start(lot, holidays) for lot in run_lots),
                "machines": sorted({segment.machine_id for segment in run_segments}),
            }
        )

    detail: list[dict[str, Any]] = []
    for tool_id, runs in by_tool.items():
        timeline = sorted(runs, key=lambda run: (run["start"], run["run_id"]))
        for index, blocking in enumerate(timeline):
            for urgent in timeline[index + 1 :]:
                if lot_priority_key(urgent["lot"])[:5] >= lot_priority_key(blocking["lot"])[:5]:
                    continue
                if urgent["release"] > blocking["release"]:
                    continue
                detail.append(
                    {
                        "tool_id": tool_id,
                        "urgent_run_id": urgent["run_id"],
                        "urgent_lot_id": urgent["lot"].id,
                        "urgent_due_day": lot_priority_key(urgent["lot"])[0],
                        "urgent_release_day": urgent["release"],
                        "urgent_machines": urgent["machines"],
                        "blocking_run_id": blocking["run_id"],
                        "blocking_lot_id": blocking["lot"].id,
                        "blocking_due_day": lot_priority_key(blocking["lot"])[0],
                        "blocking_release_day": blocking["release"],
                        "blocking_machines": blocking["machines"],
                    }
                )
    return sorted(
        detail,
        key=lambda item: (
            item["urgent_due_day"],
            item["tool_id"],
            item["urgent_run_id"],
            item["blocking_run_id"],
        ),
    )


def _left_shift_detail(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    gap_opportunities: list[PartialGapOpportunity] | None = None,
) -> list[dict[str, Any]]:
    opportunities = (
        find_gap_opportunities(segments, lots, data, config)
        if gap_opportunities is None
        else gap_opportunities
    )
    canonical = [
        (
            opportunity,
            "partial_opening_gap"
            if opportunity.movable_setup_min > 0
            else "partial_internal_gap",
        )
        for opportunity in actionable_gap_opportunities(
            segments,
            lots,
            data,
            config,
            gap_opportunities=opportunities,
        )
    ]
    canonical.sort(
        key=lambda item: (
            item[0].gap_day,
            item[0].gap_start_min,
            item[0].source_day,
            item[0].source_start_min,
            item[0].machine_id,
            item[0].lot_id,
        )
    )
    detail = [
        {
            **opportunity.to_dict(),
            "current_day": opportunity.source_day,
            "current_start_min": opportunity.source_start_min,
            "evidence": evidence,
        }
        for opportunity, evidence in canonical
    ]
    return detail


def actionable_gap_opportunities(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    gap_opportunities: list[PartialGapOpportunity] | None = None,
) -> list[PartialGapOpportunity]:
    """Every left-shift gap is actionable.

    Setup families describe physical compatibility; they never reserve the
    final shift. A gap left before a campaign tail is therefore reported like
    any other until the improvement contract fills it or explains why not.
    """

    if gap_opportunities is not None:
        return list(gap_opportunities)
    return find_gap_opportunities(segments, lots, data, config)


def _lower_priority_campaign_interruptions(
    segments: list[Segment],
    lots: list[Lot],
) -> list[dict[str, Any]]:
    """Less urgent work placed inside one physical run (one mounted campaign).

    The campaign is the run, not the lot: with per-delivery material windows a
    lot is produced in several runs, and work between two of them is the
    material window doing its job, not an interruption.  Portions of one lot
    keep one campaign identity, so a blocker is reported once per lot pair.
    """

    lots_by_id = {lot.id: lot for lot in lots}
    productive = [
        segment
        for segment in segments
        if segment.prod_min > 0 and segment.end_min > segment.start_min
    ]
    by_machine_run: dict[tuple[str, str], list[Segment]] = defaultdict(list)
    by_machine: dict[str, list[Segment]] = defaultdict(list)
    for segment in productive:
        by_machine_run[(segment.machine_id, segment.run_id)].append(segment)
        by_machine[segment.machine_id].append(segment)

    detail: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for (machine_id, run_id), campaign in by_machine_run.items():
        if len(campaign) < 2:
            continue
        ordered = sorted(campaign, key=_position)
        for previous, following in zip(ordered, ordered[1:]):
            protected = lots_by_id.get(following.lot_id)
            if protected is None:
                continue
            blockers = [
                segment
                for segment in by_machine[machine_id]
                if segment.run_id != run_id
                and segment.lot_id != following.lot_id
                and _position(previous) < _position(segment) < _position(following)
            ]
            for blocker in blockers:
                blocking_lot = lots_by_id.get(blocker.lot_id)
                if blocking_lot is None:
                    continue
                if lot_priority_key(blocking_lot)[:-1] <= lot_priority_key(protected)[:-1]:
                    continue
                key = (machine_id, protected.id, blocker.lot_id)
                if key in seen:
                    continue
                seen.add(key)
                detail.append(
                    {
                        "machine_id": machine_id,
                        "run_id": run_id,
                        "urgent_lot_id": protected.id,
                        "blocking_lot_id": blocker.lot_id,
                        "gap_start_day": previous.day_idx,
                        "gap_end_day": following.day_idx,
                        "blocking_day": blocker.day_idx,
                    }
                )
    return sorted(
        detail,
        key=lambda item: (
            item["blocking_day"],
            item["machine_id"],
            item["urgent_lot_id"],
        ),
    )


def _position(segment: Segment) -> tuple[int, int]:
    return segment.day_idx, segment.start_min
