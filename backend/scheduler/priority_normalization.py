"""Deterministic audit and repair of machine-run priority inversions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any

from backend.calendar import is_factory_workday
from backend.config.shifts import clock_to_productive_offset, productive_offset_to_clock
from backend.config.types import FactoryConfig
from backend.planning_control import planning_checkpoint
from backend.scheduler.gap_filling import _proportional_prefix
from backend.scheduler.improvement import contract_verdict
from backend.scheduler.jit_policy import calendar_holidays, earliest_allowed_start
from backend.scheduler.priority import (
    delivery_not_worse,
    lot_priority_key,
)
from backend.scheduler.protection import protected_lot_ids as planning_protected_lot_ids
from backend.scheduler.setup_identity import run_setup_identity, segment_setup_identity
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.scheduler.validation import (
    PlanValidationError,
    assert_plan_valid,
    coverage_metrics,
    validate_plan,
)
from backend.types import EngineData


def _position(segment: Segment) -> tuple[int, int]:
    return int(segment.day_idx), int(segment.start_min)


def _end_position(segment: Segment) -> tuple[int, int]:
    return int(segment.day_idx), int(segment.end_min)


def repair_same_reference_interruptions(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Finish earlier lots within an unchanged same-reference production span.

    Reuse only occupied production slots. Setups, idle time and other tools
    stay fixed; validation and independent delivery guards decide acceptance.
    """
    from backend.scheduler.scoring import compute_score

    protected = planning_protected_lot_ids(data, protected_lot_ids)
    lots_by_id = {lot.id: lot for lot in lots}
    holidays = calendar_holidays(data, -14, max(data.n_days, max(
        (segment.day_idx for segment in segments), default=0
    )) + 30)
    by_machine: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        if segment.end_min > segment.start_min:
            by_machine[segment.machine_id].append(segment)

    blocks: list[list[Segment]] = []
    for timeline in by_machine.values():
        planning_checkpoint()
        block: list[Segment] = []
        previous_op = None
        for segment in sorted(timeline, key=_position):
            lot = lots_by_id.get(segment.lot_id)
            op = (lot.op_id, lot.tool_id, lot.sku) if lot is not None else None
            if (op != previous_op or segment.setup_min > 0 or segment.prod_min <= 0
                    or segment.lot_id in protected):
                if block:
                    blocks.append(block)
                block = []
            # Keep any setup-bearing segment intact, including its production.
            if (op is not None and segment.setup_min == 0 and segment.prod_min > 0
                    and segment.lot_id not in protected):
                block.append(segment)
            previous_op = op
        if block:
            blocks.append(block)

    current = list(segments)
    for block in blocks:
        planning_checkpoint()
        if len({segment.lot_id for segment in block}) < 2:
            continue
        ordered = sorted(
            block, key=lambda s: (lot_priority_key(lots_by_id[s.lot_id]), _position(s))
        )
        if ordered == block or any(
            abs(segment.end_min - segment.start_min - segment.prod_min) > 1e-6
            or not float(segment.start_min).is_integer()
            or not float(segment.end_min).is_integer()
            for segment in block
        ):
            continue
        replacement: list[Segment] = []
        source_index = 0
        consumed = 0
        for slot in block:
            cursor = int(slot.start_min)
            while cursor < slot.end_min:
                planning_checkpoint()
                source = ordered[source_index]
                duration = int(source.end_min - source.start_min)
                take = min(int(slot.end_min) - cursor, duration - consumed)

                def portion(quantity: int) -> int:
                    return (
                        _proportional_prefix(quantity, consumed + take, duration)
                        - _proportional_prefix(quantity, consumed, duration)
                    )

                replacement.append(replace(
                    source,
                    day_idx=slot.day_idx,
                    start_min=cursor,
                    end_min=cursor + take,
                    shift=slot.shift,
                    prod_min=float(take),
                    qty=portion(source.qty),
                    twin_outputs=(
                        [(op_id, sku, portion(qty)) for op_id, sku, qty in source.twin_outputs]
                        if source.twin_outputs is not None else None
                    ),
                    is_continuation=True,
                    left_shift_blockers=[],
                ))
                cursor += take
                consumed += take
                if consumed == duration:
                    source_index += 1
                    consumed = 0
        if any(
            segment.day_idx < earliest_allowed_start(lots_by_id[segment.lot_id], holidays)
            for segment in replacement
        ):
            continue
        original_ids = {id(segment) for segment in block}
        candidate = [s for s in current if id(s) not in original_ids] + replacement
        candidate.sort(key=lambda s: (s.day_idx, s.start_min, s.machine_id))
        seen_runs: set[tuple[str, str]] = set()
        replacement_ids = {id(segment) for segment in replacement}
        for segment in candidate:
            key = (segment.machine_id, segment.run_id)
            if id(segment) in replacement_ids:
                segment.is_continuation = key in seen_runs
            seen_runs.add(key)
        try:
            assert_plan_valid(candidate, data, config, lots=lots)
        except PlanValidationError:
            continue
        before = compute_score(current, lots, data, config=config, include_operational_audit=False)
        after = compute_score(candidate, lots, data, config=config, include_operational_audit=False)
        if not delivery_not_worse(after, before) or any(
            after[key] < before[key] for key in ("otd", "otd_d")
        ):
            continue
        if after.get("operator_capacity_violations", 0) > before.get(
            "operator_capacity_violations", 0
        ):
            continue
        if not contract_verdict(
            candidate, current, data, candidate_lots=lots,
            candidate_score=after, reference_score=before,
        ).admissible:
            continue
        current = candidate
    return sorted(current, key=lambda s: (s.day_idx, s.start_min, s.machine_id))


def find_priority_order_anomalies(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
) -> list[dict[str, Any]]:
    """Return suspicious lower-urgency-before-higher-urgency run pairs."""

    lots_by_id = {lot.id: lot for lot in lots}
    holidays = calendar_holidays(
        data,
        min((segment.day_idx for segment in segments), default=0) - 7,
        data.n_days + 7,
    )
    by_machine_run: dict[tuple[str, str], list[Segment]] = defaultdict(list)
    for segment in segments:
        if segment.prod_min > 0:
            by_machine_run[(segment.machine_id, segment.run_id)].append(segment)

    timelines: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (machine_id, run_id), run_segments in by_machine_run.items():
        run_lots = {
            segment.lot_id: lots_by_id[segment.lot_id]
            for segment in run_segments
            if segment.lot_id in lots_by_id
        }
        if not run_lots:
            continue
        urgent_lot = min(run_lots.values(), key=lot_priority_key)
        timelines[machine_id].append(
            {
                "run_id": run_id,
                "lot": urgent_lot,
                "lot_ids": set(run_lots),
                "start": min(_position(segment) for segment in run_segments),
                "end": max(_end_position(segment) for segment in run_segments),
                "floor": min(
                    earliest_allowed_start(lot, holidays)
                    for lot in run_lots.values()
                ),
            }
        )

    detail: list[dict[str, Any]] = []
    for machine_id, runs in timelines.items():
        ordered = sorted(runs, key=lambda run: (run["start"], run["run_id"]))
        for index, earlier in enumerate(ordered):
            for later in ordered[index + 1 :]:
                earlier_lot = earlier["lot"]
                later_lot = later["lot"]
                # Compare dates and explicit business priority. Quantity and
                # lot id remain useful scheduler tie-breakers, but must not
                # manufacture a commercial inversion when every date ties.
                if lot_priority_key(later_lot)[:5] >= lot_priority_key(earlier_lot)[:5]:
                    continue
                if later["floor"] > earlier["floor"]:
                    continue
                detail.append(
                    {
                        "machine_id": machine_id,
                        "urgent_run_id": later["run_id"],
                        "urgent_lot_id": later_lot.id,
                        "blocking_run_id": earlier["run_id"],
                        "blocking_lot_id": earlier_lot.id,
                        "urgent_rupture_day": lot_priority_key(later_lot)[0],
                        "blocking_rupture_day": lot_priority_key(earlier_lot)[0],
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


def _twin_totals(segments: list[Segment]) -> list[tuple[str, str, int]] | None:
    order: list[tuple[str, str]] = []
    totals: dict[tuple[str, str], int] = {}
    seen_twin = False
    for segment in segments:
        if segment.twin_outputs is None:
            continue
        seen_twin = True
        for op_id, sku, qty in segment.twin_outputs:
            key = (op_id, sku)
            if key not in totals:
                order.append(key)
                totals[key] = 0
            totals[key] += int(qty)
    if not seen_twin:
        return None
    return [(op_id, sku, totals[(op_id, sku)]) for op_id, sku in order]


def _rebuild_run(
    run_id: str,
    run_segments: list[Segment],
    lots_by_id: dict[str, Lot],
    machine_id: str,
) -> ToolRun | None:
    productive = [segment for segment in run_segments if segment.prod_min > 0]
    if not productive:
        return None
    by_lot: dict[str, list[Segment]] = defaultdict(list)
    for segment in productive:
        by_lot[segment.lot_id].append(segment)
    ordered_lot_ids = sorted(
        by_lot,
        key=lambda lot_id: (
            min(_position(segment) for segment in by_lot[lot_id]),
            lot_id,
        ),
    )
    run_lots: list[Lot] = []
    for lot_id in ordered_lot_ids:
        original = lots_by_id.get(lot_id)
        if original is None:
            return None
        lot_segments = by_lot[lot_id]
        run_lots.append(
            replace(
                original,
                machine_id=machine_id,
                qty=sum(int(segment.qty) for segment in lot_segments),
                prod_min=sum(float(segment.prod_min) for segment in lot_segments),
                twin_outputs=_twin_totals(lot_segments),
            )
        )
    observed_setup_min = sum(float(segment.setup_min) for segment in run_segments)
    required_setup_min = max(
        (
            float(segment.run_setup_min or 0.0)
            for segment in run_segments
        ),
        default=0.0,
    )
    required_setup_min = max(
        required_setup_min,
        *(float(lot.setup_min or 0.0) for lot in run_lots),
    )
    setup_min = max(observed_setup_min, required_setup_min)
    total_prod = sum(float(lot.prod_min) for lot in run_lots)
    return ToolRun(
        id=run_id,
        tool_id=productive[0].tool_id,
        machine_id=machine_id,
        alt_machine_id=None,
        lots=run_lots,
        setup_min=setup_min,
        total_prod_min=total_prod,
        total_min=setup_min + total_prod,
        edd=min((lot.edd for lot in run_lots), default=0),
        target_start_day=min(
            (
                lot.target_start_day
                for lot in run_lots
                if lot.target_start_day is not None
            ),
            default=None,
        ),
        production_due_day=min(
            (
                lot.production_due_day
                if lot.production_due_day is not None
                else lot.edd
                for lot in run_lots
            ),
            default=0,
        ),
    )


def _working_days(data: EngineData, config: FactoryConfig) -> list[int]:
    return [
        day_idx
        for day_idx in range(max(0, int(data.n_days)))
        if is_factory_workday(day_idx, data, config)
    ]


def _clock_to_coord(
    day_idx: int,
    minute: int,
    working_days: list[int],
    config: FactoryConfig,
) -> int | None:
    try:
        slot = working_days.index(int(day_idx))
    except ValueError:
        return None
    return slot * int(config.day_capacity_min) + clock_to_productive_offset(
        config,
        minute,
    )


def _restore_exact_production(
    segments: list[Segment],
    runs: list[ToolRun],
) -> None:
    exact = {lot.id: float(lot.prod_min) for run in runs for lot in run.lots}
    for lot_id, expected in exact.items():
        lot_segments = sorted(
            (
                segment
                for segment in segments
                if segment.lot_id == lot_id and segment.prod_min > 0
            ),
            key=_position,
        )
        if not lot_segments:
            continue
        delta = expected - sum(float(segment.prod_min) for segment in lot_segments)
        if abs(delta) > 1e-9:
            lot_segments[-1].prod_min = max(
                0.0,
                float(lot_segments[-1].prod_min) + delta,
            )


def _retained_campaign_cursor(
    ordered_run_ids: list[str],
    first_index: int,
    all_by_run: dict[str, list[Segment]],
    working_days: list[int],
    config: FactoryConfig,
) -> int | None:
    """Return the end of a retained setup immediately before the blocker.

    A setup-free run can be the deferred tail of the preceding campaign.  In
    that case an urgent run may start when the preceding lot finishes, then
    pay one setup to resume the deferred tail.  Other idle gaps are not used:
    this keeps the extra-setup move tied to a proven retained adjustment.
    """

    if first_index <= 0:
        return None
    blocking_segments = all_by_run[ordered_run_ids[first_index]]
    if any(float(segment.setup_min) > 0 for segment in blocking_segments):
        return None
    blocking_productive = sorted(
        (segment for segment in blocking_segments if segment.prod_min > 0),
        key=_position,
    )
    preceding_productive = sorted(
        (
            segment
            for segment in all_by_run[ordered_run_ids[first_index - 1]]
            if segment.prod_min > 0
        ),
        key=_position,
    )
    if not blocking_productive or not preceding_productive:
        return None
    if segment_setup_identity(preceding_productive[-1]) != segment_setup_identity(
        blocking_productive[0]
    ):
        return None
    preceding_end = max(preceding_productive, key=_end_position)
    return _clock_to_coord(
        preceding_end.day_idx,
        preceding_end.end_min,
        working_days,
        config,
    )


def _build_priority_rotation_candidates(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    anomaly: dict[str, Any],
    *,
    protected_lot_ids: set[str] | None = None,
) -> list[list[Segment]]:
    """Build conservative rotations, earliest retained-campaign slot first."""
    from backend.scheduler.alternative_repair import _with_plan_resource_blocks
    from backend.scheduler.global_jit import _schedule_preemptive_run

    machine_id = str(anomaly["machine_id"])
    blocking_run_id = str(anomaly["blocking_run_id"])
    urgent_run_id = str(anomaly["urgent_run_id"])
    machine_segments = [
        segment
        for segment in segments
        if segment.machine_id == machine_id and segment.end_min > segment.start_min
    ]
    productive_by_run: dict[str, list[Segment]] = defaultdict(list)
    all_by_run: dict[str, list[Segment]] = defaultdict(list)
    for segment in machine_segments:
        all_by_run[segment.run_id].append(segment)
        if segment.prod_min > 0:
            productive_by_run[segment.run_id].append(segment)
    ordered_run_ids = sorted(
        productive_by_run,
        key=lambda run_id: (
            min(_position(segment) for segment in productive_by_run[run_id]),
            run_id,
        ),
    )
    try:
        first_index = ordered_run_ids.index(blocking_run_id)
        urgent_index = ordered_run_ids.index(urgent_run_id)
    except ValueError:
        return []
    if urgent_index <= first_index:
        return []

    # A setup-free continuation belongs to the mounted adjustment, even when
    # it has another run ID. Moving only its predecessor strands it behind the
    # blocker and creates an unmodelled reinstallation.
    campaign_end = urgent_index + 1
    urgent_identity = segment_setup_identity(productive_by_run[urgent_run_id][0])
    for run_id in ordered_run_ids[campaign_end:]:
        planning_checkpoint()
        if (any(segment.setup_min > 0 for segment in all_by_run[run_id])
                or any(segment_setup_identity(segment) != urgent_identity
                       for segment in productive_by_run[run_id])):
            break
        campaign_end += 1
    selected_ids = ordered_run_ids[first_index:campaign_end]
    urgent_campaign = ordered_run_ids[urgent_index:campaign_end]
    rotation_order = [
        *urgent_campaign,
        *ordered_run_ids[first_index:urgent_index],
    ]
    selected_segments = [
        segment for run_id in selected_ids for segment in all_by_run[run_id]
    ]
    if not selected_segments:
        return []
    protected = planning_protected_lot_ids(data, protected_lot_ids)
    if any(segment.lot_id in protected for segment in selected_segments):
        return []

    working_days = _working_days(data, config)
    earliest = min(selected_segments, key=_position)
    cursor = _clock_to_coord(
        earliest.day_idx,
        earliest.start_min,
        working_days,
        config,
    )
    if cursor is None:
        return []

    retained_cursor = _retained_campaign_cursor(
        ordered_run_ids,
        first_index,
        all_by_run,
        working_days,
        config,
    )
    cursors = [cursor]
    if retained_cursor is not None and retained_cursor < cursor:
        cursors.insert(0, retained_cursor)

    lots_by_id = {lot.id: lot for lot in lots}
    rebuilt_runs: list[ToolRun] = []
    for run_id in rotation_order:
        planning_checkpoint()
        rebuilt = _rebuild_run(run_id, all_by_run[run_id], lots_by_id, machine_id)
        if rebuilt is None:
            return []
        if rebuilt_runs and run_setup_identity(rebuilt_runs[-1]) == run_setup_identity(rebuilt):
            rebuilt.setup_min = 0.0
            rebuilt.total_min = rebuilt.total_prod_min
        rebuilt_runs.append(rebuilt)

    candidates: list[list[Segment]] = []
    selected_set = set(selected_ids)
    fixed = [
        replace(segment) for segment in segments
        if not (segment.machine_id == machine_id and segment.run_id in selected_set)
    ]
    horizon = max(data.n_days, max((s.day_idx + 1 for s in segments), default=0)) - 1
    holidays = calendar_holidays(data, -14, horizon + 30)
    ops_by_id = {op.id: op for op in data.ops}
    for start_cursor in cursors:
        replacement: list[Segment] = []
        slot, offset = divmod(start_cursor, int(config.day_capacity_min))
        if slot >= len(working_days):
            continue
        candidate_cursor = working_days[slot] * 1440 + productive_offset_to_clock(config, offset)
        for run in rebuilt_runs:
            planning_checkpoint()
            occupied = [*fixed, *replacement]
            calendar_data = _with_plan_resource_blocks(data, occupied)
            scheduled = _schedule_preemptive_run(
                run, machine_id, occupied, calendar_data, config, ops_by_id,
                holidays, candidate_cursor, horizon,
            )
            if scheduled is None:
                replacement = []
                break
            created, candidate_cursor, _preemptions = scheduled
            replacement.extend(created)
        if not replacement:
            continue
        _restore_exact_production(replacement, rebuilt_runs)
        candidate = [*fixed, *replacement]
        candidates.append(
            sorted(candidate, key=lambda item: (*_position(item), item.machine_id))
        )
    return candidates


def build_priority_rotation_candidate(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    anomaly: dict[str, Any],
) -> list[Segment] | None:
    """Return the earliest conservative rotation for one priority anomaly."""

    candidates = _build_priority_rotation_candidates(
        segments,
        lots,
        data,
        config,
        anomaly,
    )
    return candidates[0] if candidates else None


def _score(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
) -> dict[str, Any]:
    from backend.scheduler.scoring import compute_score

    return compute_score(
        segments,
        lots,
        data,
        config=config,
        include_operational_audit=False,
    )


def _metric(score: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(score.get(key, default) or 0.0)
    except (TypeError, ValueError):
        return default


def _candidate_rejection(
    before_segments: list[Segment],
    candidate: list[Segment] | None,
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    before_score: dict[str, Any] | None = None,
) -> tuple[str | None, list[str], dict[str, Any] | None, dict[str, Any]]:
    before_score = before_score or _score(before_segments, lots, data, config)
    if candidate is None:
        return "counterfactual_unavailable", [], None, before_score

    violations = validate_plan(candidate, data, config, lots=lots)
    coverage = coverage_metrics(candidate, lots)
    coverage_invalid = any(
        int(coverage.get(key, 0) or 0) > 0
        for key in (
            "missing_lots",
            "missing_qty",
            "unexpected_lots",
            "overproduced_qty",
            "duplicate_twin_output_qty",
            "twin_output_mismatches",
        )
    )
    if violations or coverage_invalid:
        reasons = sorted(
            {
                str(violation.get("kind", "physical_conflict"))
                for violation in violations
            }
        )
        if coverage_invalid:
            reasons.append("quantity_conservation")
        return "resource_blocked", reasons, None, before_score

    after_score = _score(candidate, lots, data, config)
    if not delivery_not_worse(after_score, before_score):
        reason = (
            "blocked_by_delivery_objective"
            f"|otd_before={before_score.get('otd')}"
            f"|otd_after={after_score.get('otd')}"
            f"|otd_d_before={before_score.get('otd_d')}"
            f"|otd_d_after={after_score.get('otd_d')}"
            f"|tardy_before={before_score.get('tardy_count')}"
            f"|tardy_after={after_score.get('tardy_count')}"
        )
        return "delivery_blocked", [reason], after_score, before_score
    if any(
        _metric(after_score, key, 100.0) < _metric(before_score, key, 100.0)
        for key in ("otd", "otd_d")
    ):
        return (
            "delivery_blocked",
            ["otd_or_otd_d_would_decrease"],
            after_score,
            before_score,
        )
    if after_score.get("early_window_violations", 0) > before_score.get(
        "early_window_violations", 0
    ):
        return (
            "material_blocked",
            ["setup_or_production_before_material"],
            after_score,
            before_score,
        )
    verdict = contract_verdict(
        candidate, before_segments, data,
        candidate_lots=lots, candidate_score=after_score, reference_score=before_score,
    )
    if not verdict.admissible:
        # Per-order losses only: an extra setup is a tie-break, not a veto
        # (AGENTS.md §1.5).
        return "delivery_blocked", list(verdict.reasons), after_score, before_score
    # This function evaluates a candidate that exists specifically to correct
    # an EDD/rupture inversion. The caller still requires fewer priority
    # anomalies, so a neutral reshuffle cannot pass merely because it is
    # physically possible.
    return None, [], after_score, before_score


def classify_priority_order_anomalies(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
) -> list[dict[str, Any]]:
    """Prove whether each suspicious pair is movable or legitimately blocked."""

    details = find_priority_order_anomalies(segments, lots, data)
    before_count = len(details)
    before_score = _score(segments, lots, data, config)
    classified: list[dict[str, Any]] = []
    for detail in details:
        candidates = _build_priority_rotation_candidates(
            segments,
            lots,
            data,
            config,
            detail,
        )
        status = "counterfactual_unavailable"
        reasons: list[str] = []
        for candidate in candidates or [None]:
            candidate_status, candidate_reasons, _after_score, _before_score = (
                _candidate_rejection(
                    segments,
                    candidate,
                    lots,
                    data,
                    config,
                    before_score=before_score,
                )
            )
            status = candidate_status
            reasons = candidate_reasons
            if candidate_status is not None or candidate is None:
                continue
            after_count = len(find_priority_order_anomalies(candidate, lots, data))
            if after_count < before_count:
                status = "permutable"
                reasons = []
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


def repair_priority_inversions(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig,
    *,
    max_moves: int | None = None,
    max_evaluations: int | None = None,
    prioritize_late: bool = True,
    protected_lot_ids: set[str] | None = None,
) -> list[Segment]:
    """Apply every delivery-safe priority rotation until reaching a fixed point."""

    current = sorted(
        (replace(segment) for segment in segments),
        key=lambda item: (*_position(item), item.machine_id),
    )
    limit = max_moves if max_moves is not None else max(1, len(current) * 2)
    # Full-plan counterfactuals rebuild and validate several complete runs.
    # Prioritise genuinely late work and keep the production path bounded; the
    # audit path still reports every remaining anomaly for review.
    evaluations_remaining = (
        max_evaluations
        if max_evaluations is not None
        else 32 if len(current) > 200 else None
    )
    frozen_lot_ids = planning_protected_lot_ids(data, protected_lot_ids)

    def actionable_anomalies(plan: list[Segment]) -> list[dict[str, Any]]:
        return [
            anomaly
            for anomaly in find_priority_order_anomalies(plan, lots, data)
            if anomaly.get("urgent_lot_id") not in frozen_lot_ids
            and anomaly.get("blocking_lot_id") not in frozen_lot_ids
        ]

    for _move in range(limit):
        planning_checkpoint()
        anomalies = actionable_anomalies(current)
        if not anomalies:
            break
        if prioritize_late:
            lots_by_id = {lot.id: lot for lot in lots}
            completion = {
                lot_id: max(
                    (segment.day_idx for segment in current if segment.lot_id == lot_id),
                    default=-1,
                )
                for lot_id in {segment.lot_id for segment in current}
            }

            def lateness(item: dict[str, Any]) -> int:
                lot = lots_by_id.get(str(item["urgent_lot_id"]))
                if lot is None:
                    return 0
                due = lot.production_due_day if lot.production_due_day is not None else lot.edd
                return int(completion.get(lot.id, due)) - int(due)

            anomalies.sort(
                key=lambda item: (
                    lateness(item) <= 0,
                    -lateness(item),
                    item["urgent_rupture_day"],
                    item["machine_id"],
                    item["urgent_lot_id"],
                )
            )
        before_score = _score(current, lots, data, config)
        accepted = False
        for anomaly in anomalies:
            candidates = _build_priority_rotation_candidates(
                current,
                lots,
                data,
                config,
                anomaly,
                protected_lot_ids=frozen_lot_ids,
            )
            for candidate in candidates:
                if evaluations_remaining is not None:
                    if evaluations_remaining <= 0:
                        return current
                    evaluations_remaining -= 1
                status, _reasons, _after_score, _before_score = _candidate_rejection(
                    current,
                    candidate,
                    lots,
                    data,
                    config,
                    before_score=before_score,
                )
                if status is not None:
                    continue
                if len(actionable_anomalies(candidate)) >= len(anomalies):
                    continue
                current = candidate
                accepted = True
                break
            if accepted:
                break
        if not accepted:
            break
    return current
