"""Preserve whole lots started before the current planning day."""

from __future__ import annotations

import copy
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.types import CommittedSupply


class NoValidCandidateError(ValueError):
    """The optimizer finished without a complete executable candidate."""


def _current_planning_day(engine_data, config, *, now: datetime | None = None) -> int:
    workdays = list(getattr(engine_data, "workdays", []) or [])
    if not workdays:
        return 0
    timezone_name = str(getattr(config, "timezone", "Europe/Lisbon"))
    current = now or datetime.now(ZoneInfo(timezone_name))
    today = current.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    # Historical imports and future scenarios have no executed prefix.
    if today < str(workdays[0])[:10] or today > str(workdays[-1])[:10]:
        return 0
    for day_idx, value in enumerate(workdays):
        if str(value)[:10] >= today:
            return day_idx
    return 0


def _frozen_started_lots(baseline_result, freeze_day: int):
    if baseline_result is None or freeze_day <= 0:
        return [], []
    frozen_ids = {
        segment.lot_id
        for segment in baseline_result.segments
        if segment.day_idx < freeze_day and segment.end_min > segment.start_min
    }
    return (
        [copy.deepcopy(s) for s in baseline_result.segments if s.lot_id in frozen_ids],
        [copy.deepcopy(lot) for lot in baseline_result.lots if lot.id in frozen_ids],
    )


_HISTORICAL_SEGMENT_FIELDS = (
    "lot_id", "run_id", "machine_id", "tool_id", "day_idx", "start_min",
    "end_min", "shift", "qty", "prod_min", "setup_min", "is_continuation",
    "twin_outputs",
)
_HISTORICAL_LOT_FIELDS = (
    "id", "op_id", "tool_id", "machine_id", "qty", "prod_min",
    "setup_min", "is_twin", "twin_outputs",
)


def historical_schedule_changes(
    before: dict, after: dict, *, today: str | None = None,
) -> list[str]:
    """Detect changed whole lots that had started before today in this dataset."""

    before_id = str((before.get("dataset_info") or {}).get("id") or "")
    after_id = str((after.get("dataset_info") or {}).get("id") or "")
    if not before_id or before_id != after_id:
        return []
    workdays = list((before.get("engine_data") or {}).get("workdays") or [])
    if not workdays:
        return []
    timezone = str((before.get("config") or {}).get("timezone") or "Europe/Lisbon")
    current_day = today or datetime.now(ZoneInfo(timezone)).date().isoformat()
    if current_day <= str(workdays[0])[:10]:
        return []
    freeze_day = next(
        (index for index, value in enumerate(workdays) if str(value)[:10] >= current_day),
        len(workdays),
    )
    started = {
        str(segment["lot_id"])
        for segment in before.get("segments", [])
        if int(segment["day_idx"]) < freeze_day
        and float(segment["end_min"]) > float(segment["start_min"])
    }
    def lot_rows(snapshot: dict, lot_id: str):
        snapshot_days = list((snapshot.get("engine_data") or {}).get("workdays") or [])
        segments = [
            json.dumps(
                {
                    **{field: segment.get(field) for field in _HISTORICAL_SEGMENT_FIELDS},
                    "calendar_date": (
                        str(snapshot_days[int(segment["day_idx"])])[:10]
                        if 0 <= int(segment["day_idx"]) < len(snapshot_days) else None
                    ),
                },
                sort_keys=True, separators=(",", ":"),
            )
            for segment in snapshot.get("segments", [])
            if segment.get("lot_id") == lot_id
        ]
        lots = [
            json.dumps(
                {field: lot.get(field) for field in _HISTORICAL_LOT_FIELDS},
                sort_keys=True, separators=(",", ":"),
            )
            for lot in snapshot.get("lots", [])
            if lot.get("id") == lot_id
        ]
        return sorted(segments), sorted(lots)

    after_days = list((after.get("engine_data") or {}).get("workdays") or [])
    newly_past = {
        str(segment["lot_id"])
        for segment in after.get("segments", [])
        if str(segment["lot_id"]) not in started
        and 0 <= int(segment["day_idx"]) < len(after_days)
        and str(after_days[int(segment["day_idx"])])[:10] < current_day
        and float(segment["end_min"]) > float(segment["start_min"])
    }
    return sorted(
        newly_past | {
            lot_id for lot_id in started
            if lot_rows(before, lot_id) != lot_rows(after, lot_id)
        }
    )


def _honoured_anchor_lot_ids(baseline_result, engine_data, config) -> set[str]:
    """Anchored lots whose baseline placement already satisfies the anchor."""

    from backend.scheduler.validation import plan_anchor_violations

    anchors = list(getattr(engine_data, "plan_anchors", None) or [])
    if baseline_result is None or not anchors:
        return set()
    violated = {
        str(violation.get("lot_id"))
        for violation in plan_anchor_violations(baseline_result.segments, engine_data, config)
    }
    present = {segment.lot_id for segment in baseline_result.segments}
    return {
        anchor.lot_id
        for anchor in anchors
        if anchor.lot_id in present and anchor.lot_id not in violated
    }


def _protected_lots(baseline_result, freeze_day: int, engine_data, config):
    """Started lots plus manually anchored lots, kept exactly as in the baseline.

    An anchor is a saved manual decision. The constructive solver can only
    honour it inside the CP-SAT model; when that model times out the fallback
    and the post-processing ignore it, and every candidate is rejected by the
    anchor gate. Reserving the anchored lot like confirmed history keeps the
    decision intact and lets the rest of the plan be recalculated around it.
    """

    segments, lots = _frozen_started_lots(baseline_result, freeze_day)
    anchored = _honoured_anchor_lot_ids(baseline_result, engine_data, config) - {
        lot.id for lot in lots
    }
    if anchored:
        segments = [
            *segments,
            *(copy.deepcopy(s) for s in baseline_result.segments if s.lot_id in anchored),
        ]
        lots = [
            *lots,
            *(copy.deepcopy(lot) for lot in baseline_result.lots if lot.id in anchored),
        ]
    return segments, lots, anchored


def _install_frozen_reservations(
    engine_data, frozen_segments, frozen_lots, freeze_day: int, config=None,
) -> dict:
    """Temporarily reserve whole-lot output and all future resource occupancy."""
    from backend.scheduler.operators import segment_operator_demand

    snapshot = {
        field: copy.deepcopy(getattr(engine_data, field))
        for field in (
            "holidays", "machine_blocked_intervals", "tool_blocked_intervals",
            "operator_blocked_intervals", "committed_supplies",
            "machine_blocked_days", "tool_blocked_days",
            "setup_crew_reservations", "plan_anchors",
        )
    }
    # Protected lots are spliced back unchanged; the residual problem must
    # not be asked to place them again.
    protected_ids = {lot.id for lot in frozen_lots}
    engine_data.plan_anchors = [
        anchor for anchor in engine_data.plan_anchors if anchor.lot_id not in protected_ids
    ]
    # Reserve elapsed capacity without changing the industrial calendar used
    # to derive material and subcontracting dates.
    elapsed = set(range(freeze_day))
    machines = {m.id for m in engine_data.machines}
    tools = {op.t for op in engine_data.ops}
    if config is not None:
        machines.update(config.machine_groups)
    for machine in machines:
        engine_data.machine_blocked_days.setdefault(machine, set()).update(elapsed)
    for tool in tools:
        engine_data.tool_blocked_days.setdefault(tool, set()).update(elapsed)
    groups = {machine.id: machine.group for machine in engine_data.machines}
    if config is not None:
        groups.update(config.machine_groups)
    shifts = (
        [(s.id, s.start_min, s.end_min) for s in config.shifts]
        if config is not None else [("A", 420, 930), ("B", 930, 1440)]
    )
    from backend.scheduler.setup_identity import segment_setup_identity

    # A protected continuation without setup requires its adjustment to remain
    # mounted. Inserting another tool in that gap would change the frozen lot.
    previous_by_machine = {}
    for segment in sorted(frozen_segments, key=lambda s: (s.day_idx, s.start_min, s.end_min)):
        previous = previous_by_machine.get(segment.machine_id)
        previous_by_machine[segment.machine_id] = segment
        if (previous is None or segment.day_idx < freeze_day or segment.setup_min > 0
                or segment_setup_identity(previous) != segment_setup_identity(segment)):
            continue
        start_day, start_min = max((freeze_day, 0), (previous.day_idx, previous.end_min))
        if (start_day, start_min) >= (segment.day_idx, segment.start_min):
            continue
        block = {
            "id": f"frozen-mounted-{segment.machine_id}-{segment.day_idx}-{segment.start_min}",
            "start_day": start_day, "start_min": int(start_min),
            "end_day": segment.day_idx, "end_min": int(segment.start_min),
            "category": "Plano passado", "reason": "Continuação sem reinstalação",
        }
        for day in range(start_day, segment.day_idx + 1):
            daily = {**block, "start_day": day, "end_day": day,
                     "start_min": int(start_min) if day == start_day else 0,
                     "end_min": int(segment.start_min) if day == segment.day_idx else 1440}
            if daily["end_min"] > daily["start_min"]:
                engine_data.machine_blocked_intervals.setdefault(segment.machine_id, []).append(
                    copy.deepcopy(daily)
                )
                engine_data.tool_blocked_intervals.setdefault(segment.tool_id, []).append(
                    copy.deepcopy(daily)
                )
    for index, segment in enumerate(frozen_segments):
        if segment.day_idx < freeze_day or segment.end_min <= segment.start_min:
            continue
        block = {
            "id": f"frozen-prefix-{index}",
            "start_day": int(segment.day_idx), "start_min": int(segment.start_min),
            "end_day": int(segment.day_idx), "end_min": int(segment.end_min),
            "category": "Plano passado",
            "reason": "Lote iniciado antes do dia atual",
        }
        engine_data.machine_blocked_intervals.setdefault(segment.machine_id, []).append(
            copy.deepcopy(block)
        )
        engine_data.tool_blocked_intervals.setdefault(segment.tool_id, []).append(
            copy.deepcopy(block)
        )
        if segment.setup_min > 0:
            engine_data.setup_crew_reservations.append({
                **block, "machine_id": segment.machine_id, "tool_id": segment.tool_id,
                "group": groups.get(segment.machine_id, "Grandes"),
                "end_min": min(segment.end_min, segment.start_min + segment.setup_min),
            })
        if segment.prod_min <= 0:
            continue
        production_start = segment.production_start_min
        for shift_id, shift_start, shift_end in shifts:
            start = max(production_start, shift_start)
            end = min(int(segment.end_min), shift_end)
            if start < end:
                engine_data.operator_blocked_intervals.append({
                    **block,
                    "id": f"frozen-operator-{index}-{shift_id}",
                    "group": groups.get(segment.machine_id, "Grandes"),
                    "shift": shift_id,
                    "start_min": start, "end_min": end,
                    "count": segment_operator_demand(segment, engine_data),
                })

    first_by_lot = {}
    for segment in sorted(
        frozen_segments, key=lambda item: (item.day_idx, item.start_min, item.end_min),
    ):
        first_by_lot.setdefault(segment.lot_id, segment)
    available_at = (
        f"{str(engine_data.workdays[0])[:10]}T00:00:00" if engine_data.workdays else ""
    )
    for lot in frozen_lots:
        segment = first_by_lot.get(lot.id)
        if segment is None:
            continue
        for op_id, sku, qty in lot.twin_outputs or [(lot.op_id, lot.sku, lot.qty)]:
            engine_data.committed_supplies.append(CommittedSupply(
                op_id=str(op_id), sku=str(sku), qty=int(qty),
                available_at=available_at, available_day=0,
                machine_id=segment.machine_id, tool_id=segment.tool_id,
            ))
    return snapshot


def _restore_frozen_reservations(engine_data, snapshot: dict) -> None:
    for field, value in snapshot.items():
        setattr(engine_data, field, value)


def _splice_frozen_started_lots(result, frozen_segments, frozen_lots):
    from backend.scheduler.canonical import preserved_lot_proofs

    frozen_ids = {lot.id for lot in frozen_lots}
    if not frozen_ids:
        return result
    # Run identifiers are deterministic within one optimizer execution. A
    # residual plan can therefore reuse an identifier already present in the
    # historical prefix for a later, independent campaign. Keep those
    # campaigns distinct before joining them; otherwise setup validation
    # associates the future production with the historical setup.
    frozen_run_ids = {segment.run_id for segment in frozen_segments}
    residual_run_ids = {
        segment.run_id
        for segment in result.segments
        if segment.lot_id not in frozen_ids
    }
    used_run_ids = frozen_run_ids | residual_run_ids
    replacements: dict[str, str] = {}
    for run_id in sorted(frozen_run_ids & residual_run_ids):
        suffix = 1
        candidate = f"{run_id}__replanned_{suffix}"
        while candidate in used_run_ids:
            suffix += 1
            candidate = f"{run_id}__replanned_{suffix}"
        replacements[run_id] = candidate
        used_run_ids.add(candidate)
    if replacements:
        for segment in result.segments:
            if segment.lot_id not in frozen_ids and segment.run_id in replacements:
                segment.run_id = replacements[segment.run_id]
    result.segments = [s for s in result.segments if s.lot_id not in frozen_ids]
    result.segments.extend(copy.deepcopy(frozen_segments))
    result.segments.sort(key=lambda s: (
        s.day_idx, s.start_min, s.machine_id, s.tool_id, s.lot_id,
    ))
    result.lots = [lot for lot in result.lots if lot.id not in frozen_ids]
    result.lots.extend(copy.deepcopy(frozen_lots))
    result.preserved_lot_proofs = preserved_lot_proofs(frozen_segments, frozen_lots)
    return result


def _recalculation_context(engine_data, config, baseline_result, recalculate_from_start):
    if not recalculate_from_start:
        return engine_data, baseline_result, _current_planning_day(engine_data, config)
    # Date-derived proofs belong to the old protected plan, not to observed
    # execution. Clear them only on detached inputs; keep anchors/observations.
    data, baseline = copy.deepcopy((engine_data, baseline_result))
    data.preserved_lot_proofs = {}
    baseline.preserved_lot_proofs = {}
    baseline.warnings = [
        warning for warning in baseline.warnings
        if not warning.startswith("Plano anterior preservado:")
    ]
    return data, baseline, 0


def compact_preserving_started_lots(
    engine_data, config, baseline_result, *, recalculate_from_start=False,
):
    """Recompact a valid active plan after capacity is released."""
    from backend.planning_control import planning_scope

    with planning_scope(timeout_s=60.0):
        return _compact_preserving_started_lots(
            engine_data, config, baseline_result, recalculate_from_start=recalculate_from_start,
        )


def _compact_preserving_started_lots(
    engine_data, config, baseline_result, *, recalculate_from_start=False,
):
    from backend.planning_control import improvement_time_budget
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.operators import compute_operator_alerts
    from backend.scheduler.scoring import compute_score
    from backend.scheduler.validation import assert_plan_valid

    started_at = time.perf_counter()
    engine_data, baseline_result, freeze_day = _recalculation_context(
        engine_data, config, baseline_result, recalculate_from_start,
    )
    result = copy.deepcopy(baseline_result)
    frozen_segments, frozen_lots, anchored = _protected_lots(
        result, freeze_day, engine_data, config,
    )
    result, improvement = improve_preserving_protected_lots(
        result, engine_data, copy.deepcopy(engine_data), config,
        frozen_segments, frozen_lots, freeze_day,
        time_budget_s=improvement_time_budget(60.0),
    )
    result.improvement_report = improvement
    engine_data = result_validation_data(engine_data, result)
    result.score = compute_score(
        result.segments,
        result.lots,
        engine_data,
        config=config,
    )
    result.operator_alerts = compute_operator_alerts(
        result.segments,
        engine_data,
        config=config,
    )
    assert_plan_valid(result.segments, engine_data, config, lots=result.lots)
    result.time_ms = round((time.perf_counter() - started_at) * 1000, 1)
    result.warnings = [
        *list(result.warnings),
        "Capacidade libertada: o plano ativo foi novamente compactado.",
    ]
    started = len(frozen_lots) - len(anchored)
    if started:
        result.warnings.append(
            f"Plano anterior preservado: {started} lote(s) iniciado(s) "
            f"antes do dia {freeze_day} mantidos sem alterações."
        )
    if anchored:
        result.warnings.append(_anchor_warning(anchored))
    return result


def _anchor_warning(anchored: set[str]) -> str:
    return (
        f"Posições manuais preservadas: {len(anchored)} lote(s) ancorado(s) "
        "mantido(s) sem alterações."
    )


def improve_preserving_protected_lots(
    result, engine_data, original_data, config, protected_segments, protected_lots,
    freeze_day: int, *, time_budget_s: float,
):
    """Run the no-loss improvement cycle on the residual plan only.

    Started and anchored lots stay reserved exactly as in the complete
    candidate. The improved residual is spliced back and the merged plan is
    re-validated on the original inputs; on any failure the complete candidate
    is kept unchanged. Returns ``(result, report)``.
    """
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.gates import build_gate_report
    from backend.scheduler.improvement import improve_plan
    from backend.scheduler.operators import compute_operator_alerts
    from backend.scheduler.scoring import compute_score
    from backend.scheduler.validation import validate_plan

    def evaluation_plan(segments, lots):
        complete = copy.copy(result)
        complete.segments, complete.lots = copy.deepcopy(segments), copy.deepcopy(lots)
        complete = _splice_frozen_started_lots(complete, protected_segments, protected_lots)
        return complete.segments, complete.lots, result_validation_data(original_data, complete)

    protected_ids = {lot.id for lot in protected_lots}
    residual_segments = [s for s in result.segments if s.lot_id not in protected_ids]
    residual_lots = [lot for lot in result.lots if lot.id not in protected_ids]
    snapshot = _install_frozen_reservations(
        engine_data, protected_segments, protected_lots, freeze_day, config,
    )
    try:
        segments, lots, report = improve_plan(
            residual_segments, residual_lots, engine_data, config,
            time_budget_s=time_budget_s, evaluation_plan=evaluation_plan,
        )
    finally:
        _restore_frozen_reservations(engine_data, snapshot)
    if not report.get("moves_accepted"):
        return result, report

    def reject_merged(reason):
        from backend.scheduler.improvement import physical_signature

        return result, {
            **report, "status": "partial", "stop_reason": reason,
            "rolled_back_moves": int(report.get("rolled_back_moves", 0)) + report["moves_accepted"],
            "moves_accepted": 0, "accepted_by_scope": {},
            "proposal_log": {key: entry for key, entry in report.get("proposal_log", {}).items()
                             if entry.get("outcome") != "accepted"},
            "final": report.get("reference"),
            "final_signature": physical_signature(result.segments, result.lots),
        }

    improved = copy.copy(result)
    improved.segments, improved.lots = segments, lots
    if protected_lots:
        improved = _splice_frozen_started_lots(improved, protected_segments, protected_lots)
    view = result_validation_data(original_data, improved)
    if validate_plan(improved.segments, view, config, lots=improved.lots):
        return reject_merged("merged_validation_failed")
    from backend.scheduler.improvement import contract_verdict

    if not contract_verdict(
        improved.segments, result.segments, view,
        candidate_lots=improved.lots, reference_lots=result.lots,
    ).admissible:
        return reject_merged("merged_contract_failed")
    improved.score = compute_score(improved.segments, improved.lots, view, config=config)
    improved.operator_alerts = compute_operator_alerts(improved.segments, view, config=config)
    improved.gate_report = build_gate_report(
        improved.segments, improved.lots, improved.score, view, config,
    )
    if not (improved.gate_report.get("physical_gate_passed")
            and improved.gate_report.get("coverage_gate_passed")):
        return reject_merged("merged_gate_failed")
    return improved, report


def optimize_preserving_started_lots(
    engine_data, config, baseline_result, *, mode="normal", audit=False, cancel_event=None,
    optimizer=None, recalculate_from_start=False,
):
    """Optimize a detached input, preserving every segment of already-started lots.

    Temporary reservations are always removed. The optimizer and final merged
    validation share one budget and propagate PlanningCancelled/PlanningTimeout.
    """
    from backend.cpo import optimize
    from backend.cpo.optimizer import (
        MODE_CONFIG,
        _strip_score_policy,
    )
    from backend.planning_control import (
        PlanningTimeout,
        candidate_observer,
        closing_reserve,
        improvement_time_budget,
        planning_checkpoint,
        planning_scope,
        remaining_time,
    )
    from backend.plans.serialize import schedule_fingerprint
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.gates import build_gate_report
    from backend.scheduler.operators import compute_operator_alerts
    from backend.scheduler.scoring import compute_score
    from backend.scheduler.validation import assert_plan_valid

    if mode not in MODE_CONFIG:
        raise ValueError(f"Unknown mode: {mode}. Use: {list(MODE_CONFIG)}")
    with planning_scope(
        timeout_s=float(MODE_CONFIG[mode].get("time_budget_s", 60.0)),
        cancel_event=cancel_event,
    ):
        engine_data, baseline_result, freeze_day = _recalculation_context(
            engine_data, config, baseline_result, recalculate_from_start,
        )
        segments, lots, anchored = _protected_lots(
            baseline_result, freeze_day, engine_data, config,
        )
        original_data = copy.deepcopy(engine_data)
        complete = None
        complete_fingerprint = None

        def retain(candidate):
            nonlocal complete, complete_fingerprint
            fingerprint = schedule_fingerprint(candidate.segments, candidate.lots)
            if fingerprint == complete_fingerprint:
                for field in ("solver_status", "feasibility", "time_ms", "journal"):
                    setattr(complete, field, copy.deepcopy(getattr(candidate, field)))
                complete.warnings = list(dict.fromkeys([*complete.warnings, *candidate.warnings]))
                if not lots:
                    complete.score = copy.deepcopy(candidate.score)
                if "solver_trace" in (candidate.gate_report or {}):
                    complete.gate_report["solver_trace"] = copy.deepcopy(
                        candidate.gate_report["solver_trace"],
                    )
                return
            merged = copy.deepcopy(candidate)
            if recalculate_from_start:
                merged.preserved_lot_proofs = {}
            if lots:
                merged = _splice_frozen_started_lots(merged, segments, lots)
                view = result_validation_data(original_data, merged)
                merged.score = compute_score(merged.segments, merged.lots, view, config=config)
                merged.operator_alerts = compute_operator_alerts(
                    merged.segments, view, config=config
                )
                started = len(lots) - len(anchored)
                warnings = [
                    *(
                        [f"Plano anterior preservado: {started} lote(s) iniciado(s) "
                         f"antes do dia {freeze_day} mantidos sem alterações."]
                        if started else []
                    ),
                    *([_anchor_warning(anchored)] if anchored else []),
                ]
                for warning in warnings:
                    if warning not in merged.warnings:
                        merged.warnings.append(warning)
            else:
                view = original_data
            assert_plan_valid(merged.segments, view, config, lots=merged.lots)
            merged.gate_report = build_gate_report(
                merged.segments, merged.lots, merged.score, view, config,
            )
            if not (merged.gate_report.get("physical_gate_passed")
                    and merged.gate_report.get("coverage_gate_passed")):
                return
            planning_checkpoint()
            complete, complete_fingerprint = merged, fingerprint

        snapshot = _install_frozen_reservations(engine_data, segments, lots, freeze_day, config)
        try:
            planning_checkpoint()
            remaining = remaining_time()
            reserve = closing_reserve(float(MODE_CONFIG[mode].get("time_budget_s", 60.0)))
            with candidate_observer(retain):
                try:
                    # The improvement cycle runs once below, on the residual
                    # plan with protected lots reserved; defer it here.
                    defer = {"improve": False} if optimizer in (None, optimize) else {}
                    if defer and mode != "quick":
                        defer["reserve_improvement"] = True
                    with planning_scope(timeout_s=max(0.0, remaining - reserve)):
                        result = (optimizer or optimize)(
                            engine_data,
                            mode=mode,
                            audit=audit,
                            config=config,
                            cancel_event=cancel_event,
                            **defer,
                        )
                    retain(result)
                except PlanningTimeout:
                    planning_checkpoint()
                    if complete is None:
                        raise
                    complete.warnings.append(
                        "Tempo de melhoria esgotado; conservado o candidato completo validado."
                    )
        finally:
            _restore_frozen_reservations(engine_data, snapshot)
        planning_checkpoint()
        if complete is None:
            raise NoValidCandidateError(
                "O cálculo não produziu um candidato completo fisicamente válido."
            )
        result = complete
        solver_trace = copy.deepcopy((result.gate_report or {}).get("solver_trace"))
        # Improvement phase (plan §5): only on a complete validated candidate,
        # inside the same deadline, keeping a closing margin.
        budget = improvement_time_budget(float(MODE_CONFIG[mode]["time_budget_s"]))
        if mode == "quick":
            budget = min(10.0, budget)
        verified = dict(getattr(result, "improvement_report", None) or {})
        if budget > 0:
            result, report = improve_preserving_protected_lots(
                result, engine_data, original_data, config, segments, lots, freeze_day,
                time_budget_s=budget,
            )
        else:
            report = {"status": "not_evaluated", "stop_reason": "no_time_left"}
        # Search verifications of the pre-improvement state no longer apply
        # to a changed plan; keep them only when nothing was accepted.
        result.improvement_report = {
            **({"verified": verified["verified"]}
               if verified.get("verified") and not report.get("moves_accepted") else {}),
            **report,
        }
        planning_checkpoint()
        engine_data = result_validation_data(engine_data, result)
        result.gate_report = build_gate_report(
            result.segments, result.lots, result.score, engine_data, config,
        )
        if result.solver_status is not None:
            result.gate_report["solver_status"] = result.solver_status
        result.gate_report["feasibility"] = result.feasibility
        if solver_trace is not None:
            result.gate_report["solver_trace"] = solver_trace
        from backend.scheduler.improvement import improvement_gate_summary

        # Informational: explains the merged plan (history included) and
        # never changes the apply decision.
        result.gate_report["improvement"] = improvement_gate_summary(
            result.improvement_report, result.segments, result.lots, engine_data, config,
        )
        _strip_score_policy(result)
        planning_checkpoint()
        return result
