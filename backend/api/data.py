"""Data REST API — direct endpoints for the frontend.

22 endpoints as thin wrappers over CopilotState.
All analytics are pre-computed in state._refresh_analytics().
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import asdict
from datetime import date as dt_date
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.api.locks import plan_mutation_lock
from backend.api.plan_reads import PlanReadRoute
from backend.config.loader import validate_config
from backend.config.planning import (
    clean_sku_subcontracts,
    normalize_sku_planning_rule,
    normalize_subcontract_company,
)
from backend.config.shifts import (
    clear_legacy_common_machine_capacity_overrides,
    normalize_shift_updates,
)
from backend.config.types import ShiftConfig
from backend.config.unavailability import (
    UnavailabilityConflict,
    add_unavailability_entry,
    remove_unavailability_entry,
)
from backend.copilot.executors_master import (
    exec_adicionar_feriado,
    exec_adicionar_twin,
    exec_editar_ferramenta,
    exec_editar_maquina,
    exec_remover_feriado,
    exec_remover_twin,
)
from backend.copilot.state import state
from backend.plans.transactions import plan_writer
from backend.validation import ApprovalInput, IntegerInput, finite_float, strict_bool, strict_int

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data", tags=["data"], route_class=PlanReadRoute)


def _require_data():
    """Raise 503 if no ISOP data loaded."""
    if state.engine_data is None:
        raise HTTPException(503, "Sem dados carregados. Carrega um ISOP primeiro.")


def _require_config():
    if state.config is None:
        raise HTTPException(503, "Configuração não carregada.")


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "sim", "on"}:
            return True
        if normalized in {"false", "0", "no", "nao", "não", "off"}:
            return False
    raise ValueError(f"valor booleano inválido: {value!r}")


def _coerce_tunable_value(key: str, current_value, new_value):
    if isinstance(current_value, bool):
        return _coerce_bool(new_value)
    try:
        coerced = type(current_value)(new_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key}: valor inválido {new_value!r}") from exc
    if key == "eco_lot_mode" and coerced not in {"hard", "soft"}:
        raise ValueError("eco_lot_mode deve ser 'hard' ou 'soft'")
    return coerced


def _normalize_shift_updates(raw_shifts) -> list[ShiftConfig]:
    try:
        return normalize_shift_updates(raw_shifts)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _validate_mutations(raw_mutations: list[BaseModel], require_non_empty: bool = False):
    if require_non_empty and not raw_mutations:
        raise HTTPException(400, "Pelo menos uma mutação é obrigatória.")

    from backend.simulator.mutations import (
        apply_mutation,
        normalize_mutation_params,
        valid_mutation_types,
    )
    from backend.simulator.simulator import Mutation

    allowed = valid_mutation_types()
    mutations = []
    seen = {_mutation_key(item) for item in state.active_mutations}
    validation_data = copy.deepcopy(state.engine_data)
    validation_config = copy.deepcopy(state.config)
    for item in raw_mutations:
        if item.type not in allowed:
            raise HTTPException(400, f"Mutação desconhecida: {item.type}")
        try:
            params = normalize_mutation_params(item.type, item.params)
            key = _mutation_key({"type": item.type, "params": params})
            if key not in seen:
                apply_mutation(validation_data, item.type, params, validation_config)
            seen.add(key)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        mutations.append(Mutation(type=item.type, params=params))
    return mutations


def _mutation_dicts(mutations) -> list[dict]:
    return [{"type": m.type, "params": dict(m.params)} for m in mutations]


def _mutation_models(mutations: list[dict]):
    from backend.simulator.simulator import Mutation

    return [Mutation(type=m["type"], params=m.get("params", {})) for m in mutations]


def _mutation_key(mutation: dict) -> str:
    from backend.simulator.mutations import normalize_mutation_params

    return json.dumps(
        {
            "type": mutation["type"],
            "params": normalize_mutation_params(mutation["type"], mutation.get("params", {})),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _dedupe_mutations(mutations: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for mutation in mutations:
        item = {
            "type": mutation["type"],
            "params": dict(mutation.get("params", {})),
        }
        key = _mutation_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _compose_active_mutations(pending) -> list[dict]:
    return _dedupe_mutations(copy.deepcopy(state.active_mutations) + _mutation_dicts(pending))


def _pending_mutations(pending) -> list[dict]:
    """Return only mutations not already materialized in the active state."""

    active_keys = {_mutation_key(item) for item in state.active_mutations}
    return [
        item
        for item in _dedupe_mutations(_mutation_dicts(pending))
        if _mutation_key(item) not in active_keys
    ]


def _plan_validation_error(exc):
    from backend.scheduler.validation import PlanValidationError

    if isinstance(exc, PlanValidationError):
        return HTTPException(
            400,
            {
                "message": str(exc),
                "violations": exc.violations,
            },
        )
    return HTTPException(400, str(exc))


def _result_gate_report(result) -> dict | None:
    return getattr(result, "gate_report", None) if result is not None else None


def _gate_exception(report: dict) -> HTTPException:
    return HTTPException(
        409,
        {
            "message": (
                "Plano não aplicável por conflito físico ou inconsistência de quantidades."
            ),
            "gate_report": report,
        },
    )


def _approval_args(body: dict | None) -> dict:
    payload = body or {}
    return {
        "approve_exceptions": strict_bool(
            payload.get(
                "approve_exceptions",
                payload.get("confirm_delivery_risk", False),
            )
        ),
        "approval_reason": str(payload.get("approval_reason", payload.get("reason", ""))),
        "approval_author": str(payload.get("approval_author", payload.get("author", ""))),
    }


def _require_expected_revision(body: dict | None) -> int:
    if body is None or "expected_revision" not in body:
        raise HTTPException(400, "expected_revision é obrigatório.")
    try:
        expected = strict_int(body["expected_revision"], "expected_revision")
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "expected_revision deve ser um inteiro.") from exc
    if expected != state.plan_revision:
        raise HTTPException(
            409,
            {
                "message": "Revisão obsoleta: o plano mudou entretanto.",
                "current_revision": state.plan_revision,
            },
        )
    return expected


def _ensure_result_applicable(result, body: dict | None = None) -> dict | None:
    from backend.scheduler.gates import authorize_application

    report = _result_gate_report(result)
    if report is None:
        return None
    try:
        return authorize_application(report, **_approval_args(body))
    except ValueError as exc:
        error = _gate_exception(report)
        error.detail["message"] = str(exc)
        raise error from exc


def _require_recompute_preview(body: dict | None) -> None:
    from backend.plans.context import api_write_context

    if api_write_context() is not None and (
        (body or {}).get("candidate_id") or _approval_args(body)["approve_exceptions"]
    ):
        raise HTTPException(409, {
            "code": "preview_required",
            "message": "Calcula uma nova pre-visualizacao antes de aprovar este recalculo.",
        })


def _authorize_recomputed_candidate(result, body: dict | None, *, action="recompute"):
    from backend.plans.context import api_write_context
    from backend.scheduler.gates import physically_valid

    try:
        return _ensure_result_applicable(result, body)
    except HTTPException as exc:
        context = api_write_context()
        report = _result_gate_report(result) or {}
        if (
            context is None or report.get("apply_decision") != "approval_required"
            or not physically_valid(report)
        ):
            raise
        # Finish the detached response: generated IDs and diagnostics belong
        # to the exact candidate that the writer will offer for confirmation.
        context.approval_required = exc
        context.approval_action = action
        return None


def _schedule_result_from_simulation(sim):
    from backend.scheduler.types import ScheduleResult

    return ScheduleResult(
        segments=sim.segments,
        lots=sim.lots,
        score=sim.score,
        time_ms=sim.time_ms,
        warnings=list(getattr(sim, "warnings", [])),
        operator_alerts=list(getattr(sim, "operator_alerts", [])),
        audit_trail=None,
        journal=None,
        gate_report=getattr(sim, "gate_report", None),
        improvement_report=copy.deepcopy(getattr(sim, "improvement_report", None)),
        solver_status=(getattr(sim, "gate_report", None) or {}).get("solver_status"),
        feasibility=(getattr(sim, "gate_report", None) or {}).get("feasibility"),
    )


def _schedule_result_from_state():
    from backend.scheduler.types import ScheduleResult

    return ScheduleResult(
        segments=state.segments,
        lots=state.lots,
        score=state.score,
        time_ms=0.0,
        warnings=state.warnings,
        operator_alerts=state.operator_alerts or [],
        audit_trail=None,
        journal=state.journal_entries,
        gate_report=state.gate_report,
        improvement_report=copy.deepcopy(state.improvement_report),
    )


_SIMULATION_TRANSACTION_FIELDS = (
    "engine_data",
    "config",
    "segments",
    "lots",
    "score",
    "warnings",
    "gate_report",
    "improvement_report",
    "solver_status",
    "feasibility",
    "plan_revision",
    "approvals",
    "journal_entries",
    "operator_alerts",
    "active_mutations",
    "manual_edits",
    "saved_schedule",
    "saved_mutations",
    "saved_manual_edits",
    "saved_engine_data",
    "saved_config",
    "saved_plan_revision",
    "dataset_info",
    "stock_projections",
    "expedition",
    "risk_result",
    "late_deliveries",
    "coverage",
    "order_tracking",
    "stress_map",
)


def _simulation_state_snapshot() -> dict[str, object]:
    return {field: copy.deepcopy(getattr(state, field)) for field in _SIMULATION_TRANSACTION_FIELDS}


def _restore_simulation_state(snapshot: dict[str, object]) -> None:
    for field, value in snapshot.items():
        setattr(state, field, value)


def _compute_schedule(config):
    """Recalculate the schedule with the given config without mutating state.

    Uses trust-loop `mode="normal"` (baseline JIT/VNS + local CP-SAT gates).
    If there are active what-if mutations (machine down, rush
    order, ...) they are re-applied on top so a config change (e.g. a preset)
    does not silently discard the simulation.
    """
    if state.engine_data is None:
        return None, None

    # Calendar config is persisted separately from the uploaded ISOP.  Rebuild
    # its effective day-index representation before every transactional
    # recompute so additions and removals take effect immediately.
    from backend.config.planning import synchronize_active_twin_groups
    from backend.transform.calendars import apply_calendars

    synchronize_active_twin_groups(state.engine_data, config.twins)
    apply_calendars(state.engine_data, config)

    if state.active_mutations:
        from backend.simulator.mutations import reapply_calendar_mutations

        reapply_calendar_mutations(state.engine_data, state.active_mutations, config)
    from backend.plans.context import recalculation_from_start
    from backend.plans.frozen import optimize_preserving_started_lots

    return optimize_preserving_started_lots(
        state.engine_data,
        config,
        _schedule_result_from_state(),
        audit=True,
        **({"recalculate_from_start": True} if recalculation_from_start() else {}),
    ), None


def _compact_active_schedule(config):
    """Budget the whole preview, including the final analytics."""
    from backend.cpo.optimizer import MODE_CONFIG
    from backend.planning_control import planning_scope

    with planning_scope(timeout_s=float(MODE_CONFIG["normal"]["time_budget_s"])):
        return _compact_active_schedule_bounded(config)


def _compact_active_schedule_bounded(config):
    """Recompact existing lots in the scope selected by the server-side writer."""

    if state.engine_data is None:
        state.config = config
        return None
    from backend.config.planning import synchronize_active_twin_groups
    from backend.plans.context import recalculation_from_start
    from backend.plans.frozen import compact_preserving_started_lots
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.gates import build_gate_report
    from backend.transform.calendars import apply_calendars

    synchronize_active_twin_groups(state.engine_data, config.twins)
    apply_calendars(state.engine_data, config)
    if state.active_mutations:
        from backend.simulator.mutations import reapply_calendar_mutations

        reapply_calendar_mutations(state.engine_data, state.active_mutations, config)
    result = compact_preserving_started_lots(
        state.engine_data,
        config,
        _schedule_result_from_state(),
        **({"recalculate_from_start": True} if recalculation_from_start() else {}),
    )
    validation_data = result_validation_data(state.engine_data, result)
    result.gate_report = build_gate_report(
        result.segments,
        result.lots,
        result.score,
        validation_data,
        config,
    )
    from backend.scheduler.improvement import improvement_gate_summary

    # Same informational summary as the full recalculation: what the no-loss
    # improvement did and why each remaining tool transfer stays.
    result.gate_report["improvement"] = improvement_gate_summary(
        result.improvement_report, result.segments, result.lots, validation_data, config,
    )
    state.config = config
    state.manual_edits = []
    state.update_schedule(result)
    return result


def _recompute(config):
    """Recalculate, validate and update state atomically."""

    if state.engine_data is None:
        state.config = config
        return None

    result, baseline = _compute_schedule(config)
    state.config = config
    state.manual_edits = []
    state.update_schedule(result)
    if baseline is not None:
        state.saved_schedule = baseline
    return result


def _recalculation_needs_rebuild(config) -> bool:
    """Whether "Recalcular" from D0 must rebuild lots instead of compacting.

    Recalculation from the start drops the date-derived protection, so lots
    planned under an older configuration (e.g. before an OEE change) are
    checked against the current one. Compaction only moves segments and
    cannot fix their durations, so it would fail; the full optimizer rebuilds
    them (reproduced on the frozen revision 87 after an OEE change).
    """
    from backend.plans.context import recalculation_from_start
    from backend.scheduler.canonical import source_contract_violations

    if state.engine_data is None or not recalculation_from_start():
        return False
    detached = copy.copy(state.engine_data)
    detached.preserved_lot_proofs = {}
    return bool(source_contract_violations(state.segments, state.lots, detached, config))


def _recompute_transactional(
    config,
    approval_body: dict | None = None,
    *,
    persist_config: bool = False,
):
    """Recalculate with rollback if the candidate plan is invalid."""
    from backend.plans.context import is_staging
    from backend.plans.transactions import run_sync_mutation

    if not is_staging():
        return run_sync_mutation(
            state,
            lambda: _recompute_transactional(
                copy.deepcopy(config),
                approval_body,
                persist_config=persist_config,
            ),
        )
    _require_recompute_preview(approval_body)
    engine_snapshot = copy.deepcopy(state.engine_data)
    config_snapshot = copy.deepcopy(state.config)
    saved_snapshot = copy.deepcopy(state.saved_schedule)
    saved_mutations_snapshot = copy.deepcopy(state.saved_mutations)
    saved_manual_edits_snapshot = copy.deepcopy(state.saved_manual_edits)
    mutations_snapshot = copy.deepcopy(state.active_mutations)
    manual_edits_snapshot = copy.deepcopy(state.manual_edits)
    segments_snapshot = copy.deepcopy(state.segments)
    lots_snapshot = copy.deepcopy(state.lots)
    score_snapshot = copy.deepcopy(state.score)
    warnings_snapshot = copy.deepcopy(state.warnings)
    journal_snapshot = copy.deepcopy(state.journal_entries)
    operator_alerts_snapshot = copy.deepcopy(state.operator_alerts)
    gate_report_snapshot = copy.deepcopy(state.gate_report)
    improvement_snapshot = copy.deepcopy(state.improvement_report)
    revision_snapshot = state.plan_revision
    approvals_snapshot = copy.deepcopy(state.approvals)
    analytics_snapshot = {
        "stock_projections": copy.deepcopy(state.stock_projections),
        "expedition": copy.deepcopy(state.expedition),
        "risk_result": copy.deepcopy(state.risk_result),
        "late_deliveries": copy.deepcopy(state.late_deliveries),
        "coverage": copy.deepcopy(state.coverage),
        "order_tracking": copy.deepcopy(state.order_tracking),
        "stress_map": copy.deepcopy(state.stress_map),
    }
    try:
        if (approval_body or {}).get("compact_active_plan", False) and not (
            _recalculation_needs_rebuild(config)
        ):
            result = _compact_active_schedule(config)
        else:
            result = _recompute(config)
        # Keep this assignment inside the rollback boundary even when tests or
        # integrations provide a detached recompute implementation.
        state.config = config
        approval = _authorize_recomputed_candidate(result, approval_body)
        if approval is not None:
            state.approvals.append({**approval, "action": "recompute"})
        if persist_config:
            from backend.config.loader import save_config

            save_config(config)
        if state.dataset_info is not None:
            try:
                state.persist_current_plan(
                    name="Replaneamento automático",
                    source="auto",
                    note="Configuração ou dados mestre alterados",
                    is_auto=True,
                )
            except Exception:
                logger.exception("Failed to persist automatic plan snapshot")
                raise
        return result
    except Exception:
        state.engine_data = engine_snapshot
        state.config = config_snapshot
        state.saved_schedule = saved_snapshot
        state.saved_mutations = saved_mutations_snapshot
        state.saved_manual_edits = saved_manual_edits_snapshot
        state.active_mutations = mutations_snapshot
        state.manual_edits = manual_edits_snapshot
        state.segments = segments_snapshot
        state.lots = lots_snapshot
        state.score = score_snapshot
        state.warnings = warnings_snapshot
        state.journal_entries = journal_snapshot
        state.operator_alerts = operator_alerts_snapshot
        state.gate_report = gate_report_snapshot
        state.improvement_report = improvement_snapshot
        state.plan_revision = revision_snapshot
        state.approvals = approvals_snapshot
        for key, value in analytics_snapshot.items():
            setattr(state, key, value)
        raise


def _apply_config_candidate(
    candidate,
    approval_body: dict | None = None,
) -> tuple[object | None, dict]:
    """Validate, recompute and persist a detached config candidate."""
    errors = validate_config(candidate, state.engine_data)
    if errors:
        raise HTTPException(400, {"message": "Configuração inválida", "errors": errors})

    old_score = dict(state.score) if state.score else {}
    try:
        result = _recompute_transactional(
            candidate,
            approval_body,
            persist_config=True,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    return result, old_score


def _resolved_unavailability() -> dict:
    """Serialize persistent calendar ranges with their effective day indices."""
    if state.engine_data is None or state.config is None:
        return {"machines": [], "tools": []}
    from backend.transform.calendars import _range_day_indices

    workday_index = {str(day): idx for idx, day in enumerate(state.engine_data.workdays)}

    def resolve(entries: list[dict]) -> list[dict]:
        return [
            {
                "id": str(entry.get("id", "")),
                "resource": str(entry.get("resource", "")),
                "days": sorted(
                    _range_day_indices(
                        entry,
                        workday_index,
                        state.config.timezone,
                    )
                ),
            }
            for entry in entries
        ]

    return {
        "machines": resolve(state.config.machine_unavailability),
        "tools": resolve(state.config.tool_unavailability),
    }


def _calendar_response(result, old_score: dict, **extra) -> dict:
    return {
        "status": "ok",
        "plan_revision": state.plan_revision,
        **extra,
        "score": result.score if result is not None else state.score,
        "score_previous": old_score,
        "resolved": _resolved_unavailability(),
        "gate_report": _result_gate_report(result) or state.gate_report,
    }


def _compute_schedule_for_preview(engine_data, config):
    """Compute schedule on a detached EngineData copy."""
    from backend.cpo import optimize
    from backend.simulator.mutations import reapply_calendar_mutations
    from backend.transform.calendars import apply_calendars

    apply_calendars(engine_data, config)
    if state.active_mutations:
        reapply_calendar_mutations(engine_data, state.active_mutations, config)

    return optimize(engine_data, mode="normal", audit=True, config=config), None


def _score_delta(before: dict, after: dict) -> dict:
    return {
        "otd": round(after.get("otd", 0) - before.get("otd", 0), 3),
        "otd_d": round(after.get("otd_d", 0) - before.get("otd_d", 0), 3),
        "setups": after.get("setups", 0) - before.get("setups", 0),
        "tardy_count": after.get("tardy_count", 0) - before.get("tardy_count", 0),
        "earliness_avg_days": round(
            after.get("earliness_avg_days", 0) - before.get("earliness_avg_days", 0),
            3,
        ),
        "planning_penalty": round(
            after.get("planning_penalty", 0) - before.get("planning_penalty", 0),
            3,
        ),
        "subcontract_dispatch_misses": int(after.get("subcontract_dispatch_misses", 0) or 0)
        - int(before.get("subcontract_dispatch_misses", 0) or 0),
        "subcontract_dispatch_late_workdays": int(
            after.get("subcontract_dispatch_late_workdays", 0) or 0
        )
        - int(before.get("subcontract_dispatch_late_workdays", 0) or 0),
    }


def _lot_matches_sku(lot, sku: str, op_sku_by_id: dict[str, str]) -> bool:
    if op_sku_by_id.get(lot.op_id) == sku:
        return True
    return any(out_sku == sku for _op_id, out_sku, _qty in (lot.twin_outputs or []))


def _segment_matches_sku(seg, sku: str) -> bool:
    if seg.sku == sku:
        return True
    return any(out_sku == sku for _op_id, out_sku, _qty in (seg.twin_outputs or []))


def _sku_impact(result, engine_data, sku: str) -> dict:
    op_sku_by_id = {op.id: op.sku for op in engine_data.ops}
    lots = [lot for lot in result.lots if _lot_matches_sku(lot, sku, op_sku_by_id)]
    segments = [seg for seg in result.segments if _segment_matches_sku(seg, sku)]
    warnings = [lot.economic_warning for lot in lots if getattr(lot, "economic_warning", None)]
    return {
        "lots": len(lots),
        "segments": len(segments),
        "qty": sum(lot.qty for lot in lots),
        "prod_min": round(sum(lot.prod_min for lot in lots), 1),
        "setups": len({seg.run_id for seg in segments if seg.setup_min > 0}),
        "warnings": warnings,
    }


def _planning_rule_response(sku: str, config) -> dict:
    return dict(config.sku_planning_rules.get(sku, {}))


def _validate_subcontract_rules(companies: list[dict], sku_subcontracts: dict[str, dict]) -> None:
    company_ids = {str(company.get("id")) for company in companies if company.get("id")}
    for sku, rule in sku_subcontracts.items():
        if not rule.get("enabled", True):
            continue
        company_id = str(rule.get("company_id") or "").strip()
        if not company_id:
            raise HTTPException(
                400,
                f"{sku}: escolhe uma empresa antes de ativar a subcontratação.",
            )
        if company_id not in company_ids:
            raise HTTPException(
                400,
                f"{sku}: empresa de subcontratação desconhecida: {company_id}.",
            )


def _nominal_calendar_days(workdays: int) -> int:
    full_weeks, remainder = divmod(max(0, int(workdays)), 5)
    return full_weeks * 7 + remainder


def _subcontract_companies_response(companies: list[dict]) -> list[dict]:
    response = []
    for company in companies:
        item = normalize_subcontract_company(company)
        nominal = _nominal_calendar_days(int(item.get("lead_time_workdays", 0) or 0))
        if int(item.get("lead_time_days", 0) or 0) < nominal:
            item["lead_time_days"] = nominal
        response.append(item)
    return response


def _sku_subcontracts_response(rules: dict[str, dict]) -> dict[str, dict]:
    response = clean_sku_subcontracts(rules)
    for rule in response.values():
        nominal = _nominal_calendar_days(int(rule.get("lead_time_workdays", 0) or 0))
        if int(rule.get("lead_time_days", 0) or 0) < nominal:
            rule["lead_time_days"] = nominal
    return response


# ═══════════════════════════════════════════════════════════════════════════
# CORE (5)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/today")
async def get_today():
    """Return today's day_idx based on workdays calendar."""
    _require_data()
    timezone = state.config.timezone if state.config is not None else "Europe/Lisbon"
    today = datetime.now(ZoneInfo(timezone)).date().isoformat()
    workdays = state.engine_data.workdays
    for i, d in enumerate(workdays):
        if d >= today:
            return {"today_idx": i, "date": d}
    return {"today_idx": len(workdays) - 1, "date": workdays[-1] if workdays else ""}


@router.get("/workdays")
async def get_workdays():
    """Return workdays list (day_idx → ISO date mapping)."""
    _require_data()
    return state.engine_data.workdays


@router.get("/score")
async def get_score():
    _require_data()
    return {**state.score, "plan_revision": state.plan_revision}


@router.get("/gate-report")
async def get_gate_report():
    _require_data()
    return {**(state.gate_report or {}), "plan_revision": state.plan_revision}


@router.get("/segments")
async def get_segments():
    _require_data()
    return [asdict(s) for s in state.segments]


@router.get("/lots")
async def get_lots():
    _require_data()
    return [asdict(lot) for lot in state.lots]


@router.get("/plan-view")
async def get_plan_view():
    """Return one revision-consistent snapshot for the main frontend views."""

    _require_data()
    _require_config()
    from backend.plans.context import stage_state
    from backend.plans.explanations import plan_view_explanations
    from backend.plans.transactions import clone_state

    async with plan_mutation_lock:
        baseline = clone_state(state)
    with stage_state(state, baseline):
        revision = baseline.plan_revision
        segments, placement_reasons = await run_in_threadpool(
            plan_view_explanations,
            state.segments,
            state.lots,
            state.engine_data,
            state.config,
        )
        return {
            "plan_revision": revision,
            "dataset_id": str((state.dataset_info or {}).get("id", "")),
            "dataset": copy.deepcopy(state.dataset_info),
            "active_mutations": copy.deepcopy(state.active_mutations),
            "manual_edits": copy.deepcopy(state.manual_edits),
            "can_revert": (await can_revert())["can_revert"],
            "learning": await get_learning(),
            "score": await get_score(),
            "gate_report": await get_gate_report(),
            "improvement_report": copy.deepcopy(state.improvement_report),
            "segments": segments,
            "placement_reasons": placement_reasons,
            "lots": await get_lots(),
            "config": await get_config(),
            "capacity": await get_capacity("day"),
            "workdays": await get_workdays(),
            "blocked_days": await get_blocked_days(),
        }


@router.get("/trust")
async def get_trust():
    if state.trust_index is None:
        raise HTTPException(503, "Trust index não calculado.")
    t = state.trust_index
    return {
        "score": t.score,
        "gate": t.gate,
        "n_ops": t.n_ops,
        "n_issues": t.n_issues,
        "dimensions": [
            {"name": d.name, "score": d.score, "details": d.details} for d in t.dimensions
        ],
    }


@router.get("/journal")
async def get_journal():
    return state.journal_entries or []


@router.get("/learning")
async def get_learning():
    """Return learning optimization info (or null if not optimized)."""
    return state.learning_info


# ═══════════════════════════════════════════════════════════════════════════
# ANALYTICS (8)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/stock")
async def get_stock_summary():
    """Stock grid data — all SKUs with daily stock values."""
    _require_data()
    if not state.stock_projections:
        return []

    # Build op_id → (machine, tool) lookup from engine_data
    op_info: dict[str, tuple[str, str]] = {}
    if state.engine_data:
        for op in state.engine_data.ops:
            op_info[op.id] = (op.m, op.t)

    # Detect non-workdays (weekends + holidays)
    holidays = set(state.engine_data.holidays) if state.engine_data else set()

    def _is_workday(date_str, day_idx):
        if day_idx in holidays:
            return False
        # ISO date "YYYY-MM-DD" → weekday (5=Sat, 6=Sun)
        import datetime as _dt

        try:
            dt = _dt.date.fromisoformat(date_str.split("T")[0])
            return dt.weekday() < 5
        except (ValueError, AttributeError):
            return True

    return [
        {
            "op_id": p.op_id,
            "sku": p.sku,
            "client": p.client,
            "machine": op_info.get(p.op_id, ("", ""))[0],
            "tool": op_info.get(p.op_id, ("", ""))[1],
            "initial_stock": p.initial_stock,
            "stockout_day": p.stockout_day,
            "coverage_days": p.coverage_days,
            "total_demand": p.total_demand,
            "total_produced": p.total_produced,
            "subcontract_company_id": getattr(p, "subcontract_company_id", None),
            "internal_deadline_min": getattr(p, "internal_deadline_min", None),
            "days": [
                {
                    "day": d.day_idx,
                    "date": d.date,
                    "stock": d.stock,
                    "demand": d.demand,
                    "produced": d.produced,
                    "workday": True if d.is_buffer else _is_workday(d.date, d.day_idx),
                    "is_buffer": d.is_buffer,
                }
                for d in p.days
            ],
        }
        for p in state.stock_projections
    ]


@router.get("/stock/{sku}")
async def get_stock_detail(sku: str):
    """Full stock projection for a single SKU (with daily data)."""
    _require_data()
    if not state.stock_projections:
        raise HTTPException(404, f"SKU {sku} não encontrado.")
    proj = next((p for p in state.stock_projections if p.sku == sku), None)
    if not proj:
        raise HTTPException(404, f"SKU {sku} não encontrado.")
    return asdict(proj)


@router.get("/expedition")
async def get_expedition():
    _require_data()
    if state.expedition is None:
        raise HTTPException(503, "Expedição não calculada.")
    from backend.analytics.expedition import at_risk_in_window
    from backend.calendar import current_factory_day

    result = asdict(state.expedition)
    result["at_risk_count"] = at_risk_in_window(
        state.expedition.days, current_factory_day(state.engine_data, state.config)
    )
    return result


@router.get("/orders")
async def get_orders():
    _require_data()
    if not state.order_tracking:
        return []
    return [asdict(co) for co in state.order_tracking]


@router.get("/coverage")
async def get_coverage():
    _require_data()
    if state.coverage is None:
        raise HTTPException(503, "Cobertura não calculada.")
    return asdict(state.coverage)


@router.get("/risk")
async def get_risk():
    _require_data()
    if state.risk_result is None:
        raise HTTPException(503, "Risco não calculado.")
    from backend.risk.plan_identity import planning_anchor_day
    from backend.risk.slack_analytics import select_top_risks

    payload = asdict(state.risk_result)
    # The 7-day window follows today at request time, not the day the risk
    # result was computed (a plan computed yesterday must not show yesterday's
    # window).
    today_idx = planning_anchor_day(state.engine_data, state.config)
    payload["top_risks"] = [
        asdict(risk) for risk in select_top_risks(state.risk_result.lot_risks, today_idx)
    ]
    return payload


@router.get("/stress")
async def get_stress():
    _require_data()
    from backend.scheduler.stress import (
        compute_stress_map,
        stress_recommendations,
        stress_summary,
    )

    smap = state.stress_map or compute_stress_map(
        state.segments,
        state.lots,
        state.engine_data.n_days,
        n_holidays=len(getattr(state.engine_data, "holidays", []) or []),
    )
    summary = stress_summary(smap)
    recs = stress_recommendations(smap, state.lots, state.segments)
    return {"summary": summary, "recommendations": recs}


@router.get("/late")
async def get_late_deliveries():
    _require_data()
    if state.late_deliveries is None:
        raise HTTPException(503, "Atrasos não calculados.")
    return asdict(state.late_deliveries)


@router.get("/workforce")
async def get_workforce(window: int = 10):
    """Workforce forecast (computed on-demand, not cached)."""
    _require_data()
    _require_config()
    from backend.analytics.workforce_forecast import forecast_workforce
    from backend.calendar import current_factory_day

    wf = forecast_workforce(state.segments, state.engine_data, state.config, window,
                            start_day=current_factory_day(state.engine_data, state.config))
    return asdict(wf)


@router.get("/capacity")
async def get_capacity(granularity: str = "day"):
    _require_data()
    _require_config()
    from backend.analytics.capacity import compute_capacity

    try:
        return compute_capacity(state.segments, state.engine_data, state.config, granularity)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/blocked-days")
async def get_blocked_days():
    """Serialize effective calendar blocks for Gantt overlays."""
    _require_data()
    _require_config()
    workdays = state.engine_data.workdays
    return {
        "workdays": workdays,
        "holidays": [
            {
                "day_idx": day,
                "date": workdays[day] if 0 <= day < len(workdays) else None,
            }
            for day in sorted(set(state.engine_data.holidays or []))
        ],
        "machine_blocks": [
            {
                "machine_id": machine_id,
                "day_idx": day,
                "date": workdays[day] if 0 <= day < len(workdays) else None,
            }
            for machine_id, days in sorted(state.engine_data.machine_blocked_days.items())
            for day in sorted(days)
        ],
        "tool_blocks": [
            {
                "tool_id": tool_id,
                "day_idx": day,
                "date": workdays[day] if 0 <= day < len(workdays) else None,
            }
            for tool_id, days in sorted(state.engine_data.tool_blocked_days.items())
            for day in sorted(days)
        ],
        "machine_intervals": [
            {"machine_id": machine_id, **interval}
            for machine_id, intervals in sorted(state.engine_data.machine_blocked_intervals.items())
            for interval in intervals
        ],
        "tool_intervals": [
            {"tool_id": tool_id, **interval}
            for tool_id, intervals in sorted(state.engine_data.tool_blocked_intervals.items())
            for interval in intervals
        ],
        "operator_intervals": list(state.engine_data.operator_blocked_intervals),
        "inactive_machines": sorted(
            machine_id
            for machine_id, machine in state.config.machines.items()
            if not machine.active
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG / MASTER DATA (3)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/config")
async def get_config():
    _require_config()
    c = state.config
    return {
        "plan_revision": state.plan_revision,
        "name": c.name,
        "site": c.site,
        "timezone": c.timezone,
        "shifts": [
            {
                "id": s.id,
                "start_min": s.start_min,
                "end_min": s.end_min,
                "duration_min": s.duration_min,
                "label": s.label,
            }
            for s in c.shifts
        ],
        "day_capacity_min": c.day_capacity_min,
        "machines": {
            mid: {
                "group": m.group,
                "active": m.active,
                "day_capacity_min": m.day_capacity_min,
                "oee": m.oee,
            }
            for mid, m in c.machines.items()
        },
        "tools": {
            tid: (
                {
                    "primary": t.get("primary", ""),
                    "alt": t.get("alt"),
                    "setup_hours": t.get("setup_hours", 0.5),
                }
                if isinstance(t, dict)
                else {"primary": t.primary, "alt": t.alt, "setup_hours": t.setup_hours}
            )
            for tid, t in c.tools.items()
        },
        "twins": (
            [{"tool_id": tid, "sku_a": skus[0], "sku_b": skus[1]} for tid, skus in c.twins.items()]
            if isinstance(c.twins, dict)
            else [{"tool_id": tw.tool_id, "sku_a": tw.sku_a, "sku_b": tw.sku_b} for tw in c.twins]
        ),
        "operators": {
            f"{k[0]} {k[1]}" if isinstance(k, tuple) else str(k): v for k, v in c.operators.items()
        },
        "holidays": [str(h) for h in c.holidays],
        "extra_workdays": [str(d) for d in c.extra_workdays],
        "unavailability": {
            "machines": c.machine_unavailability,
            "tools": c.tool_unavailability,
            "operators": c.operator_unavailability,
        },
        "setup_overrides": c.setup_overrides,
        "setup_families": c.setup_families,
        # Tunables
        "earliness_policy": c.earliness_policy,
        "material_release_days": c.material_release_days,
        "early_window_enforcement": c.early_window_enforcement,
        "oee_default": c.oee_default,
        "subcontract_skus": c.subcontract_skus,
        "sku_planning_rules": c.sku_planning_rules,
        "subcontract_companies": _subcontract_companies_response(c.subcontract_companies),
        "sku_subcontracts": _sku_subcontracts_response(c.sku_subcontracts),
        "setup_crews": c.setup_crews,
        "setup_crews_by_group": c.setup_crews_by_group,
        "jit_enabled": c.jit_enabled,
        "jit_buffer_pct": c.jit_buffer_pct,
        "jit_threshold": c.jit_threshold,
        "jit_max_retries": c.jit_max_retries,
        "jit_earliness_target": c.jit_earliness_target,
        "max_run_days": c.max_run_days,
        "max_edd_gap": c.max_edd_gap,
        "max_edd_span": c.max_edd_span,
        "edd_swap_tolerance": c.edd_swap_tolerance,
        "edd_assign_threshold": c.edd_assign_threshold,
        "campaign_window": c.campaign_window,
        "urgency_threshold": c.urgency_threshold,
        "interleave_enabled": c.interleave_enabled,
        "auto_buffer": c.auto_buffer,
        "vns_enabled": c.vns_enabled,
        "vns_max_iter": c.vns_max_iter,
        "compact_enabled": c.compact_enabled,
        "weight_earliness": c.weight_earliness,
        "weight_setups": c.weight_setups,
        "weight_balance": c.weight_balance,
        "eco_lot_mode": c.eco_lot_mode,
    }


@router.get("/ops")
async def get_ops():
    _require_data()
    active_rows = []
    for op in state.engine_data.ops:
        subcontract_rule = state.config.sku_subcontracts.get(op.sku, {}) if state.config else {}
        active_rows.append(
            {
                "id": op.id,
                "sku": op.sku,
                "client": op.client,
                "designation": op.designation,
                "machine": op.m,
                "tool": op.t,
                "alt_machine": op.alt,
                "pcs_hour": op.pH,
                "setup_hours": op.sH,
                "eco_lot": op.eco_lot,
                "eco_lot_isop": op.eco_lot_isop if op.eco_lot_isop is not None else op.eco_lot,
                "eco_lot_effective": op.eco_lot_effective
                if op.eco_lot_effective is not None
                else op.eco_lot,
                "start_buffer_days": op.start_buffer_days,
                "finish_buffer_days": op.finish_buffer_days,
                "min_campaign_qty": op.min_campaign_qty,
                "min_campaign_prod_min": op.min_campaign_prod_min,
                "max_group_gap_days": op.max_group_gap_days,
                "planning_priority": op.planning_priority,
                "subcontract_company_id": op.subcontract_company_id,
                "subcontract_lead_time_days": op.subcontract_lead_time_days,
                "subcontract_lead_time_workdays": op.subcontract_lead_time_days,
                "subcontract_lead_time_calendar_days": int(
                    subcontract_rule.get("lead_time_days", 0) or 0
                ),
                "subcontract_buffer_days": op.subcontract_buffer_days,
                "stock": op.stk,
                "oee": op.oee,
                "backlog": op.backlog,
                "operators": op.operators,
                "demand": op.d,
                "active": True,
            }
        )
    active_skus = {op.sku for op in state.engine_data.ops}
    historical_skus = (
        set((state.config.sku_planning_rules if state.config else {}).keys())
        | set((state.config.sku_subcontracts if state.config else {}).keys())
        | set(state.config.subcontract_skus if state.config else [])
    ) - active_skus
    for sku in sorted(historical_skus):
        rule = (state.config.sku_planning_rules if state.config else {}).get(sku, {})
        subcontract_rule = state.config.sku_subcontracts.get(sku, {}) if state.config else {}
        active_rows.append(
            {
                "id": f"inactive::{sku}",
                "sku": sku,
                "client": "",
                "designation": "Histórico — ausente no ISOP atual",
                "machine": "",
                "tool": "",
                "alt_machine": None,
                "pcs_hour": 0,
                "setup_hours": 0,
                "eco_lot": int(rule.get("eco_lot", 0) or 0),
                "eco_lot_isop": 0,
                "eco_lot_effective": int(rule.get("eco_lot", 0) or 0),
                "start_buffer_days": int(rule.get("start_buffer_days", 0) or 0),
                "finish_buffer_days": int(rule.get("finish_buffer_days", 0) or 0),
                "min_campaign_qty": rule.get("min_campaign_qty"),
                "min_campaign_prod_min": rule.get("min_campaign_prod_min"),
                "max_group_gap_days": rule.get("max_group_gap_days"),
                "planning_priority": int(rule.get("planning_priority", 0) or 0),
                "subcontract_company_id": subcontract_rule.get("company_id"),
                "subcontract_lead_time_days": int(
                    subcontract_rule.get("lead_time_workdays", 0) or 0
                ),
                "subcontract_lead_time_workdays": int(
                    subcontract_rule.get("lead_time_workdays", 0) or 0
                ),
                "subcontract_lead_time_calendar_days": int(
                    subcontract_rule.get("lead_time_days", 0) or 0
                ),
                "subcontract_buffer_days": 0,
                "stock": 0,
                "oee": state.config.oee_default if state.config else 0,
                "backlog": 0,
                "operators": 0,
                "demand": [],
                "active": False,
            }
        )
    return active_rows


@router.get("/catalog")
async def get_catalog():
    """Canonical, explainable catalogue for every configuration screen.

    ISOP rows are the source of active references and tools. Configuration
    keeps persistent overrides and historical records between uploads.
    """
    _require_data()
    _require_config()

    op_machine_ids = {op.m for op in state.engine_data.ops}
    op_machine_ids.update(op.alt for op in state.engine_data.ops if op.alt)
    engine_machine_ids = {machine.id for machine in state.engine_data.machines}
    machine_ids = sorted(set(state.config.machines) | op_machine_ids | engine_machine_ids)
    machines = []
    for machine_id in machine_ids:
        configured = state.config.machines.get(machine_id)
        engine_machine = next(
            (machine for machine in state.engine_data.machines if machine.id == machine_id),
            None,
        )
        in_isop = machine_id in op_machine_ids
        machines.append(
            {
                "id": machine_id,
                "source": (
                    "both"
                    if configured is not None and in_isop
                    else "config"
                    if configured is not None
                    else "isop"
                ),
                "active": (
                    configured.active if configured is not None else engine_machine is not None
                ),
                "group": (
                    configured.group
                    if configured is not None
                    else getattr(engine_machine, "group", "Grandes")
                ),
                "oee": configured.oee if configured is not None else None,
            }
        )

    ops_by_tool: dict[str, list] = {}
    for op in state.engine_data.ops:
        if op.t:
            ops_by_tool.setdefault(op.t, []).append(op)

    active_tools = set(ops_by_tool)
    tool_ids = sorted(set(state.config.tools) | active_tools)
    tools = []
    for tool_id in tool_ids:
        configured = state.config.tools.get(tool_id)
        configured_dict = (
            configured
            if isinstance(configured, dict)
            else {
                "primary": getattr(configured, "primary", ""),
                "alt": getattr(configured, "alt", None),
                "setup_hours": getattr(
                    configured,
                    "setup_hours",
                    state.config.default_setup_hours,
                ),
            }
            if configured is not None
            else {}
        )
        matching_ops = ops_by_tool.get(tool_id, [])
        first_op = matching_ops[0] if matching_ops else None
        observed_machines = sorted(
            {str(op.m).strip() for op in matching_ops if str(op.m or "").strip()}
        )
        configured_primary = str(configured_dict.get("primary") or "").strip()
        if configured_primary:
            primary = configured_primary
            primary_source = "config"
        elif len(observed_machines) == 1:
            primary = observed_machines[0]
            primary_source = "isop"
        elif observed_machines:
            # A tool-level route cannot be inferred safely from inconsistent
            # ISOP rows. Expose the conflict instead of choosing the first row.
            primary = ""
            primary_source = "conflict"
        else:
            primary = ""
            primary_source = "missing"
        in_isop = tool_id in active_tools
        tools.append(
            {
                "id": tool_id,
                "source": (
                    "both"
                    if configured is not None and in_isop
                    else "config"
                    if configured is not None
                    else "isop"
                ),
                "active": in_isop,
                "primary": primary,
                "primary_source": primary_source,
                "observed_machines": observed_machines,
                "alt": configured_dict.get(
                    "alt",
                    first_op.alt if first_op else None,
                ),
                "setup_hours": float(
                    configured_dict.get(
                        "setup_hours",
                        first_op.sH if first_op is not None else state.config.default_setup_hours,
                    )
                ),
            }
        )

    active_skus = {op.sku for op in state.engine_data.ops}
    historical_skus = (
        set(state.config.sku_planning_rules)
        | set(state.config.sku_subcontracts)
        | set(state.config.subcontract_skus)
    )
    references = []
    for sku in sorted(active_skus | historical_skus):
        matching_ops = [op for op in state.engine_data.ops if op.sku == sku]
        first_op = matching_ops[0] if matching_ops else None
        references.append(
            {
                "id": sku,
                "source": "isop" if sku in active_skus else "config",
                "active": sku in active_skus,
                "client": first_op.client if first_op else "",
                "machine": first_op.m if first_op else "",
                "tool": first_op.t if first_op else "",
                "has_override": (
                    sku in state.config.sku_planning_rules or sku in state.config.sku_subcontracts
                ),
            }
        )

    return {
        "source_policy": {
            "active": "O ISOP define referências e ferramentas ativas.",
            "persistent": (
                "A configuração guarda máquinas, exceções e histórico entre carregamentos."
            ),
        },
        "machines": machines,
        "tools": tools,
        "references": references,
    }


@router.get("/skus/planning")
async def get_sku_planning_rules():
    _require_data()
    _require_config()
    return {
        "rules": state.config.sku_planning_rules,
        "subcontracts": state.config.sku_subcontracts,
        "companies": state.config.subcontract_companies,
    }


@router.post("/skus/{sku}/planning/preview")
async def preview_sku_planning(sku: str, body: dict):
    """Preview SKU planning rule impact without mutating current state."""
    _require_data()
    _require_config()
    if not any(op.sku == sku for op in state.engine_data.ops):
        raise HTTPException(404, f"SKU {sku} não encontrado.")

    try:
        rule = normalize_sku_planning_rule(sku, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    candidate = copy.deepcopy(state.config)
    if rule:
        candidate.sku_planning_rules[sku] = rule
    else:
        candidate.sku_planning_rules.pop(sku, None)

    engine_copy = copy.deepcopy(state.engine_data)
    try:
        result, _baseline = _compute_schedule_for_preview(engine_copy, candidate)
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    return {
        "status": "ok",
        "sku": sku,
        "rule": rule,
        "score_before": state.score,
        "score_after": result.score,
        "delta": _score_delta(state.score, result.score),
        "impact_before": _sku_impact(
            _schedule_result_from_state(),
            state.engine_data,
            sku,
        ),
        "impact_after": _sku_impact(result, engine_copy, sku),
        "warnings": result.warnings[:10],
        "gate_report": _result_gate_report(result),
    }


@router.put("/skus/{sku}/planning")
@plan_writer
async def update_sku_planning(sku: str, body: dict):
    """Apply SKU planning rule and recalculate the active schedule."""
    _require_data()
    _require_config()
    _require_expected_revision(body)
    if not any(op.sku == sku for op in state.engine_data.ops):
        raise HTTPException(404, f"SKU {sku} não encontrado.")

    try:
        rule = normalize_sku_planning_rule(sku, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    candidate = copy.deepcopy(state.config)
    if rule:
        candidate.sku_planning_rules[sku] = rule
    else:
        candidate.sku_planning_rules.pop(sku, None)

    result, old_score = _apply_config_candidate(candidate, body)

    return {
        "status": "ok",
        "sku": sku,
        "rule": rule,
        "score": result.score if result else state.score,
        "score_previous": old_score,
        "delta": _score_delta(old_score, state.score),
        "impact": _sku_impact(
            _schedule_result_from_state(),
            state.engine_data,
            sku,
        ),
        "gate_report": _result_gate_report(result) or state.gate_report,
    }


@router.delete("/skus/{sku}/planning")
@plan_writer
async def reset_sku_planning(sku: str, body: dict):
    """Remove SKU planning overrides and return to ISOP values."""
    _require_data()
    _require_config()
    _require_expected_revision(body)
    if sku not in state.config.sku_planning_rules:
        return {
            "status": "ok",
            "sku": sku,
            "rule": {},
            "score": state.score,
            "score_previous": state.score,
        }

    candidate = copy.deepcopy(state.config)
    candidate.sku_planning_rules.pop(sku, None)

    result, old_score = _apply_config_candidate(candidate, body)

    return {
        "status": "ok",
        "sku": sku,
        "rule": {},
        "score": result.score if result else state.score,
        "score_previous": old_score,
        "delta": _score_delta(old_score, state.score),
        "gate_report": _result_gate_report(result) or state.gate_report,
    }


@router.get("/subcontracts")
async def get_subcontracts():
    _require_config()
    return {
        "companies": _subcontract_companies_response(state.config.subcontract_companies),
        "sku_subcontracts": _sku_subcontracts_response(state.config.sku_subcontracts),
        "legacy_skus": state.config.subcontract_skus,
    }


@router.post("/subcontracts/preview")
async def preview_subcontracts(body: dict):
    """Preview subcontract company/SKU rules without mutating current state."""
    _require_data()
    _require_config()

    try:
        companies = [
            normalize_subcontract_company(c)
            for c in body.get("companies", [])
            if isinstance(c, dict)
        ]
        sku_subcontracts = clean_sku_subcontracts(body.get("sku_subcontracts", {}))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _validate_subcontract_rules(companies, sku_subcontracts)

    candidate = copy.deepcopy(state.config)
    candidate.subcontract_companies = companies
    candidate.sku_subcontracts = sku_subcontracts
    candidate.subcontract_skus = [
        sku for sku, rule in sku_subcontracts.items() if rule.get("enabled", True)
    ]

    engine_copy = copy.deepcopy(state.engine_data)
    try:
        result, _baseline = _compute_schedule_for_preview(engine_copy, candidate)
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    return {
        "status": "ok",
        "companies": companies,
        "sku_subcontracts": sku_subcontracts,
        "score_before": state.score,
        "score_after": result.score,
        "delta": _score_delta(state.score, result.score),
        "warnings": result.warnings[:10],
        "gate_report": _result_gate_report(result),
    }


@router.put("/subcontracts")
@plan_writer
async def update_subcontracts(body: dict):
    """Apply subcontract companies/SKU rules and recalculate schedule."""
    _require_data()
    _require_config()
    _require_expected_revision(body)

    try:
        companies = [
            normalize_subcontract_company(c)
            for c in body.get("companies", [])
            if isinstance(c, dict)
        ]
        sku_subcontracts = clean_sku_subcontracts(body.get("sku_subcontracts", {}))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _validate_subcontract_rules(companies, sku_subcontracts)

    candidate = copy.deepcopy(state.config)
    candidate.subcontract_companies = companies
    candidate.sku_subcontracts = sku_subcontracts
    candidate.subcontract_skus = [
        sku for sku, rule in sku_subcontracts.items() if rule.get("enabled", True)
    ]

    result, old_score = _apply_config_candidate(candidate, body)

    return {
        "status": "ok",
        "companies": companies,
        "sku_subcontracts": sku_subcontracts,
        "score": result.score if result else state.score,
        "score_previous": old_score,
        "delta": _score_delta(old_score, state.score),
        "gate_report": _result_gate_report(result) or state.gate_report,
    }


@router.get("/rules")
async def get_rules():
    return state.rules


@router.put("/config")
@plan_writer
async def update_config(updates: dict):
    """Update tunable config parameters and recalculate schedule."""
    _require_config()
    _require_expected_revision(updates)

    tunables = [
        "oee_default",
        "jit_buffer_pct",
        "jit_threshold",
        "jit_max_retries",
        "max_run_days",
        "max_edd_gap",
        "max_edd_span",
        "edd_swap_tolerance",
        "edd_assign_threshold",
        "campaign_window",
        "urgency_threshold",
        "interleave_enabled",
        "auto_buffer",
        "vns_enabled",
        "vns_max_iter",
        "compact_enabled",
        "setup_crews_by_group",
        "weight_earliness",
        "weight_setups",
        "weight_balance",
        "eco_lot_mode",
    ]
    current = state.config
    if "setup_crews" in updates:
        raise HTTPException(
            400,
            "setup_crews global foi substituído por setup_crews_by_group.",
        )
    candidate = copy.deepcopy(current)
    updates_to_apply = []
    if "shifts" in updates:
        updates_to_apply.append(("shifts", _normalize_shift_updates(updates["shifts"])))
    for key in tunables:
        if key in updates:
            try:
                new_val = _coerce_tunable_value(key, getattr(candidate, key), updates[key])
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            updates_to_apply.append((key, new_val))

    if not updates_to_apply:
        return {
            "status": "ok",
            "changed": [],
            "score": state.score,
            "score_previous": state.score,
        }

    old_score = dict(state.score) if state.score else {}
    changed = []
    for key, new_val in updates_to_apply:
        setattr(candidate, key, new_val)
        changed.append(key)
    if "shifts" in changed:
        clear_legacy_common_machine_capacity_overrides(
            candidate,
            current.day_capacity_min,
        )

    errors = validate_config(candidate, state.engine_data)
    if errors:
        raise HTTPException(400, {"message": "Configuração inválida", "errors": errors})

    try:
        _recompute_transactional(candidate, updates, persist_config=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    return {
        "status": "ok",
        "changed": changed,
        "score": state.score,
        "score_previous": old_score,
        "gate_report": state.gate_report,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ACTIONS (3)
# ═══════════════════════════════════════════════════════════════════════════


class MutationInput(BaseModel):
    type: str
    params: dict = Field(default_factory=dict)


class SimulateRequest(BaseModel):
    mutations: list[MutationInput]
    expected_revision: IntegerInput | None = None
    approve_exceptions: ApprovalInput = False
    approval_reason: str = ""
    approval_author: str = ""
    confirm_delivery_risk: ApprovalInput = False
    candidate_id: str | None = None
    request_id: str | None = None


@router.post("/simulate")
async def simulate_scenario(request: SimulateRequest):
    _require_data()
    from backend.plans.candidates import previews
    from backend.plans.context import stage_state
    from backend.plans.transactions import clone_state
    from backend.simulator.simulator import simulate

    async with plan_mutation_lock:
        baseline = clone_state(state)

    def calculate():
        with stage_state(state, baseline):
            mutations = _validate_mutations(request.mutations, require_non_empty=True)
            pending = _pending_mutations(mutations)
            result = simulate(
                baseline.engine_data,
                baseline.score,
                _mutation_models(pending),
                baseline.config,
                baseline_result=_schedule_result_from_state(),
                active_mutations=baseline.active_mutations,
            )
            return result, pending

    try:
        result, pending_mutations = await run_in_threadpool(calculate)
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    candidate = previews.put("simulation", baseline, {"mutations": pending_mutations}, result)
    return {
        **candidate.identity(),
        "score_baseline": baseline.score,
        "score_scenario": result.score,
        "improvement_report": getattr(result, "improvement_report", None),
        "delta": asdict(result.delta),
        "time_ms": result.time_ms,
        "summary": result.summary,
        "segments": [asdict(s) for s in result.segments],
        "lots": [asdict(lot) for lot in result.lots],
        "gate_report": _result_gate_report(result),
    }


@router.post("/simulate-apply")
@plan_writer
async def simulate_and_apply(request: SimulateRequest):
    async with plan_mutation_lock:
        return await run_in_threadpool(_simulate_and_apply_locked, request)


def _simulate_and_apply_locked(request: SimulateRequest):
    """Run simulation and apply result as active schedule. Saves snapshot for revert."""
    _require_data()
    request_body = request.model_dump()
    _require_expected_revision(request_body)

    old_score = dict(state.score) if state.score else {}
    old_n = len(state.segments)

    mutations = _validate_mutations(request.mutations, require_non_empty=True)
    combined_mutations = _compose_active_mutations(mutations)
    pending_mutations = _pending_mutations(mutations)
    if not pending_mutations:
        return {
            "status": "unchanged",
            "score": state.score,
            "score_previous": old_score,
            "summary": [],
            "mutations": state.active_mutations,
            "can_revert": bool(state.saved_schedule),
            "plan_revision": state.plan_revision,
        }
    from backend.plans.candidates import previews

    candidate = previews.get(
        request.candidate_id, "simulation", state, {"mutations": pending_mutations}
    )
    result = copy.deepcopy(candidate.result)

    approval = _ensure_result_applicable(result, request_body)
    runtime_snapshot = _simulation_state_snapshot()
    previous_config = copy.deepcopy(state.config)
    candidate_config = getattr(result, "mutated_config", None)
    config_persisted = False
    try:
        if candidate_config is not None:
            from backend.config.loader import save_config

            # Persistence is the commit point. A disk failure must leave both
            # the active state and the user's revert snapshot untouched.
            save_config(candidate_config)
            config_persisted = True
        state.save_current()
        if getattr(result, "mutated_data", None) is not None:
            state.engine_data = result.mutated_data
        if candidate_config is not None:
            state.config = candidate_config
        state.manual_edits = []
        state.active_mutations = combined_mutations
        if approval is not None:
            state.approvals.append({**approval, "action": "simulation_apply"})
        state.update_schedule(
            _schedule_result_from_simulation(result),
            plan_source="simulation_apply",
        )
    except Exception:
        _restore_simulation_state(runtime_snapshot)
        if config_persisted and previous_config is not None:
            try:
                from backend.config.loader import save_config

                save_config(previous_config)
            except Exception:
                logger.exception("Failed to restore config after simulation rollback")
        raise

    return {
        "status": "applied",
        "score": result.score,
        "score_previous": old_score,
        "summary": result.summary,
        "n_segments_before": old_n,
        "n_segments_after": len(result.segments),
        "improvement_report": getattr(result, "improvement_report", None),
        "time_ms": result.time_ms,
        "can_revert": True,
        "mutations": state.active_mutations,
        "gate_report": _result_gate_report(result),
        "plan_revision": state.plan_revision,
    }


@router.post("/revert")
@plan_writer
async def revert_simulation(body: dict):
    async with plan_mutation_lock:
        return await run_in_threadpool(_revert_simulation_locked, body)


def _revert_simulation_locked(body: dict):
    """Revert to schedule saved before simulate-apply."""
    _require_data()
    _require_expected_revision(body)
    if not state.saved_schedule:
        raise HTTPException(400, "Nada para reverter.")
    if (
        state.saved_plan_revision is None
        or int(state.plan_revision) != int(state.saved_plan_revision) + 1
    ):
        raise HTTPException(
            409,
            "O plano mudou depois desta alteração; a reversão foi bloqueada para "
            "não apagar trabalho posterior.",
        )
    saved_schedule = copy.deepcopy(state.saved_schedule)
    saved_engine_data = copy.deepcopy(state.saved_engine_data)
    saved_config = copy.deepcopy(state.saved_config)
    runtime_snapshot = _simulation_state_snapshot()
    current_config = copy.deepcopy(state.config)
    config_persisted = False
    try:
        if saved_config is not None:
            from backend.config.loader import save_config

            save_config(saved_config)
            config_persisted = True
        state.active_mutations = copy.deepcopy(state.saved_mutations or [])
        state.manual_edits = copy.deepcopy(state.saved_manual_edits or [])
        if saved_engine_data is not None:
            state.engine_data = saved_engine_data
        if saved_config is not None:
            state.config = saved_config
        state.update_schedule(
            saved_schedule,
            plan_source="restore",
            plan_note="Desfazer cenário",
        )
        state.saved_schedule = None
        state.saved_mutations = None
        state.saved_manual_edits = None
        state.saved_engine_data = None
        state.saved_config = None
        state.saved_plan_revision = None
    except Exception:
        _restore_simulation_state(runtime_snapshot)
        if config_persisted and current_config is not None:
            try:
                from backend.config.loader import save_config

                save_config(current_config)
            except Exception:
                logger.exception("Failed to restore config after revert rollback")
        raise
    return {
        "status": "reverted",
        "score": state.score,
        "plan_revision": state.plan_revision,
    }


@router.get("/can-revert")
async def can_revert():
    """Check if there is a saved schedule to revert to."""
    return {
        "can_revert": bool(
            state.saved_schedule is not None
            and state.saved_plan_revision is not None
            and int(state.plan_revision) == int(state.saved_plan_revision) + 1
        )
    }


@router.get("/active-mutations")
async def get_active_mutations():
    """Return the what-if mutations currently applied to the schedule.

    Lets the UI keep its simulation banner in sync — non-empty means a
    simulation is active, empty means none.
    """
    return {
        "active": bool(state.active_mutations),
        "mutations": state.active_mutations,
    }


class CTPRequest(BaseModel):
    sku: str
    qty: IntegerInput
    deadline: IntegerInput
    expected_revision: IntegerInput | None = None
    approve_exceptions: ApprovalInput = False
    approval_reason: str = ""
    approval_author: str = ""
    confirm_delivery_risk: ApprovalInput = False
    candidate_id: str | None = None
    request_id: str | None = None


def _ctp_milestone_payload(result, requested_deadline: int) -> dict[str, object]:
    """Serialize named CTP milestones while tolerating pre-v3 result objects."""

    customer_delivery_day = getattr(
        result,
        "customer_delivery_day",
        requested_deadline,
    )
    production_due_day = getattr(
        result,
        "production_due_day",
        customer_delivery_day,
    )
    subcontract_dispatch_day = getattr(
        result,
        "subcontract_dispatch_day",
        None,
    )
    material_reference_kind = getattr(
        result,
        "material_reference_kind",
        "subcontract_dispatch" if subcontract_dispatch_day is not None else "customer_delivery",
    )
    material_reference_day = getattr(
        result,
        "material_reference_day",
        subcontract_dispatch_day if subcontract_dispatch_day is not None else customer_delivery_day,
    )
    return {
        "customer_delivery_day": customer_delivery_day,
        "latest_subcontract_dispatch_day": getattr(
            result,
            "latest_subcontract_dispatch_day",
            None,
        ),
        "production_due_day": production_due_day,
        "subcontract_dispatch_day": subcontract_dispatch_day,
        "internal_target_day": getattr(
            result,
            "internal_target_day",
            production_due_day,
        ),
        "material_reference_day": material_reference_day,
        "material_release_day": getattr(result, "material_release_day", None),
        "material_reference_kind": material_reference_kind,
        "customer_delivery_date": getattr(result, "customer_delivery_date", None),
        "latest_subcontract_dispatch_date": getattr(
            result,
            "latest_subcontract_dispatch_date",
            None,
        ),
        "production_due_date": getattr(result, "production_due_date", None),
        "subcontract_dispatch_date": getattr(
            result,
            "subcontract_dispatch_date",
            None,
        ),
        "internal_target_date": getattr(result, "internal_target_date", None),
        "material_reference_date": getattr(
            result,
            "material_reference_date",
            getattr(
                result,
                "subcontract_dispatch_date",
                None,
            )
            if subcontract_dispatch_day is not None
            else getattr(result, "customer_delivery_date", None),
        ),
        "material_release_date": getattr(result, "material_release_date", None),
    }


@router.post("/ctp")
async def check_ctp(request: CTPRequest):
    _require_data()
    if request.qty <= 0:
        raise HTTPException(400, "A quantidade deve ser maior que zero.")
    if request.deadline < 0 or request.deadline >= state.engine_data.n_days:
        raise HTTPException(400, "Deadline fora do horizonte do ISOP.")

    from backend.analytics.ctp import verify_ctp
    from backend.plans.candidates import previews
    from backend.plans.context import stage_state
    from backend.plans.transactions import clone_state

    async with plan_mutation_lock:
        baseline = clone_state(state)
    request.sku = request.sku.strip()
    def calculate():
        with stage_state(state, baseline):
            return verify_ctp(
                request.sku,
                request.qty,
                request.deadline,
                _schedule_result_from_state(),
                baseline.engine_data,
                baseline.config,
                active_mutations=baseline.active_mutations,
            )

    result, simulation = await run_in_threadpool(calculate)
    candidate = previews.put(
        "ctp",
        baseline,
        {"sku": request.sku, "qty": request.qty, "deadline": request.deadline},
        result,
        simulation=simulation,
    )
    milestones = _ctp_milestone_payload(result, request.deadline)
    return {
        **candidate.identity(),
        "sku": result.sku,
        "qty_requested": result.qty_requested,
        "feasible": result.feasible,
        "latest_day": result.latest_day,
        "earliest_end_day": result.earliest_end_day,
        "machine": result.machine,
        "confidence": result.confidence,
        "slack_min": result.slack_min,
        "reason": result.reason,
        "date_start": result.date_start,
        "date_end": result.date_end,
        "required_min": result.required_min,
        "prod_days": result.prod_days,
        "delivery_deadline": request.deadline,
        "effective_deadline": milestones["production_due_day"],
        **milestones,
    }


@router.post("/ctp-apply")
@plan_writer
async def apply_ctp(request: CTPRequest):
    async with plan_mutation_lock:
        return await run_in_threadpool(_apply_ctp_locked, request)


def _apply_ctp_locked(request: CTPRequest):
    """Apply CTP as a rush order: add demand + reschedule."""
    _require_data()
    request.sku = request.sku.strip()
    request_body = request.model_dump()
    _require_expected_revision(request_body)
    if request.qty <= 0:
        raise HTTPException(400, "A quantidade deve ser maior que zero.")
    if request.deadline < 0 or request.deadline >= state.engine_data.n_days:
        raise HTTPException(400, "Deadline fora do horizonte do ISOP.")

    old_score = dict(state.score) if state.score else {}
    old_n = len(state.segments)

    op = next((o for o in state.engine_data.ops if o.sku == request.sku), None)
    if op is None:
        raise HTTPException(404, f"SKU {request.sku} não encontrado.")

    from backend.plans.candidates import previews

    candidate = previews.get(
        request.candidate_id,
        "ctp",
        state,
        {"sku": request.sku, "qty": request.qty, "deadline": request.deadline},
    )
    before_ctp = candidate.result
    rush_params = {
        "sku": request.sku.strip(),
        "qty": str(request.qty),
        "deadline_day": str(request.deadline),
    }
    new_mutation = {"type": "rush_order", "params": rush_params}
    combined_mutations = copy.deepcopy(state.active_mutations) + [new_mutation]
    try:
        with candidate.lock:
            if candidate.simulation is None:
                raise HTTPException(
                    409,
                    {
                        "code": "preview_required",
                        "message": "Verifica novamente a promessa antes de aplicar.",
                    },
                )
            result = copy.deepcopy(candidate.simulation)
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    approval = _ensure_result_applicable(result, request_body)
    if not before_ctp.feasible:
        raise HTTPException(400, before_ctp.reason or "CTP não é viável.")
    state.save_current()
    if getattr(result, "mutated_data", None) is not None:
        state.engine_data = result.mutated_data
    if getattr(result, "mutated_config", None) is not None:
        state.config = result.mutated_config
    state.manual_edits = []
    state.active_mutations = combined_mutations
    if approval is not None:
        state.approvals.append({**approval, "action": "ctp_apply"})
    state.update_schedule(
        _schedule_result_from_simulation(result),
        plan_source="simulation_apply",
        plan_note="CTP aplicado",
    )
    before_milestones = _ctp_milestone_payload(before_ctp, request.deadline)

    return {
        "status": "applied",
        "score": result.score,
        "score_previous": old_score,
        "summary": result.summary,
        "n_segments_before": old_n,
        "n_segments_after": len(result.segments),
        "time_ms": result.time_ms,
        "can_revert": True,
        "mutations": state.active_mutations,
        "gate_report": _result_gate_report(result),
        "plan_revision": state.plan_revision,
        "promise": {
            "requested_deadline": request.deadline,
            "effective_deadline": before_milestones["production_due_day"],
            "customer_delivery_day": before_milestones["customer_delivery_day"],
            "latest_subcontract_dispatch_day": before_milestones["latest_subcontract_dispatch_day"],
            "production_due_day": before_milestones["production_due_day"],
            "subcontract_dispatch_day": before_milestones["subcontract_dispatch_day"],
            "internal_target_day": before_milestones["internal_target_day"],
            "material_reference_day": before_milestones["material_reference_day"],
            "material_reference_kind": before_milestones["material_reference_kind"],
            "material_release_day": before_milestones["material_release_day"],
            "promised_machine": before_ctp.machine,
            "promised_latest_day": before_ctp.latest_day,
            "promised_end_day": before_ctp.earliest_end_day,
            "post_apply_feasible_for_same_request": None,
            "post_apply_machine": None,
            "post_apply_latest_day": None,
            "post_apply_end_day": None,
            "post_apply_reason": "Uma nova encomenda exige nova verificacao.",
        },
    }


@router.post("/recalculate")
@plan_writer(recalculate_from_start=True)
async def recalculate(body: dict):
    _require_data()

    async with plan_mutation_lock:
        _require_expected_revision(body)
        old_score = dict(state.score) if state.score else {}
        try:
            result = await run_in_threadpool(
                _recompute_transactional,
                state.config,
                body,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _plan_validation_error(exc) from exc

    return {
        "status": "ok",
        "score": state.score,
        "score_previous": old_score,
        "time_ms": result.time_ms if result else 0,
        "n_segments": len(state.segments),
        "warnings": state.warnings[:10],
        "gate_report": _result_gate_report(result) or state.gate_report,
        "plan_revision": state.plan_revision,
    }


# ═══════════════════════════════════════════════════════════════════════════
# UPLOAD (1)
# ═══════════════════════════════════════════════════════════════════════════

_MAX_ISOP_UPLOAD_BYTES = 25 * 1024 * 1024


async def _read_isop_upload(file: UploadFile) -> tuple[str, bytes]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".xlsx":
        raise HTTPException(400, "O ISOP tem de ser um ficheiro .xlsx.")
    content = await file.read(_MAX_ISOP_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(400, "O ficheiro ISOP está vazio.")
    if len(content) > _MAX_ISOP_UPLOAD_BYTES:
        raise HTTPException(413, "O ficheiro ISOP excede o limite de 25 MB.")
    return suffix, content


def _load_jobs(request: Request):
    from backend.loading.jobs import LoadJobManager

    manager = getattr(request.app.state, "load_jobs", None)
    if manager is None or manager.closed:
        manager = LoadJobManager(state)
        request.app.state.load_jobs = manager
    return manager


def _load_revision(body: dict) -> int:
    value = body.get("expected_revision")
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(400, "expected_revision deve ser um inteiro.")
    return value


def _load_call(fn, *args, **kwargs):
    from backend.loading.jobs import LoadJobError

    try:
        return {"job": fn(*args, **kwargs)}
    except LoadJobError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/load/prepare", status_code=202)
async def prepare_isop_upload(
    request: Request,
    file: UploadFile,
    request_id: str | None = Form(None),
):
    """Accept an upload; parsing happens outside the request/event loop."""
    _, content = await _read_isop_upload(file)
    return _load_call(_load_jobs(request).start, content, file.filename, request_id)


@router.post("/load/confirm", status_code=202)
async def confirm_isop_upload(request: Request, body: dict):
    """Confirm once; repeated requests refer to the same background calculation."""
    return _load_call(
        _load_jobs(request).confirm,
        str(body.get("token", "")),
        _load_revision(body),
        str(body.get("mode", "")),
    )


@router.get("/load/jobs/{job_id}")
async def get_load_job(request: Request, job_id: str):
    return _load_call(_load_jobs(request).get, job_id)


@router.post("/load/jobs/{job_id}/approve", status_code=202)
async def approve_load_job(request: Request, job_id: str, body: dict):
    reason = body.get("approval_reason")
    author = body.get("approval_author")
    if not isinstance(reason, str) or not isinstance(author, str):
        raise HTTPException(400, "A aprovação exige motivo e autor em texto.")
    return _load_call(
        _load_jobs(request).approve,
        job_id,
        _load_revision(body),
        reason=reason,
        author=author,
    )


@router.post("/load/jobs/{job_id}/cancel")
async def cancel_load_job(request: Request, job_id: str):
    return _load_call(_load_jobs(request).cancel, job_id)


@router.get("/current-state")
async def get_current_machine_state():
    _require_data()
    from backend.current_state import serialize_current_states

    return {
        "confirmed": bool(state.current_machine_states),
        "items": serialize_current_states(state.current_machine_states),
    }


@router.post("/load", status_code=202)
async def load_isop_upload(
    request: Request,
    file: UploadFile,
    assume_machines_free: bool = False,
    expected_revision: int | None = None,
    approve_exceptions: bool = False,
    approval_reason: str = "",
    approval_author: str = "",
    confirm_delivery_risk: bool = False,
    request_id: str | None = Form(None),
):
    """Compatibility entry point using the same background manager and receipts."""
    if expected_revision is None:
        raise HTTPException(400, "expected_revision é obrigatório.")
    if not assume_machines_free:
        raise HTTPException(409, "Usa /load/prepare e /load/confirm para indicar o estado atual.")
    _, content = await _read_isop_upload(file)
    return _load_call(
        _load_jobs(request).start,
        content,
        file.filename,
        request_id,
        auto_confirm=True,
        expected_revision=expected_revision,
        approval={
            "approve_exceptions": approve_exceptions or confirm_delivery_risk,
            "approval_reason": approval_reason,
            "approval_author": approval_author,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# MASTER DATA MUTATIONS (8)
# ═══════════════════════════════════════════════════════════════════════════


def _exec_result(result_json: str) -> dict:
    """Parse executor JSON result, raise HTTPException on error."""
    result = json.loads(result_json)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.put("/machines/{mid}")
@plan_writer
async def edit_machine(mid: str, body: dict):
    """Toggle machine, change group or set its OEE override."""
    from backend.config.types import OUT_OF_SCOPE_MACHINES

    if mid.upper() in OUT_OF_SCOPE_MACHINES:
        raise HTTPException(400, f"{mid.upper()} está fora do âmbito da análise.")
    _require_data()
    _require_expected_revision(body)
    if "oee" in body and body["oee"] is not None:
        try:
            body["oee"] = finite_float(body["oee"], "oee")
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "OEE deve ser um número entre 0.1 e 1.0.") from exc
        if not 0.1 <= body["oee"] <= 1.0:
            raise HTTPException(400, "OEE deve estar entre 0.1 e 1.0.")
    if "activa" in body:
        try:
            body["activa"] = _coerce_bool(body["activa"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    body["id"] = mid
    return _exec_result(exec_editar_maquina(body))


@router.post("/machines")
async def add_machine(body: dict):
    """Queue transactional machine creation for review and explicit application."""
    _require_data()
    _require_config()
    _require_expected_revision(body)
    machine_id = str(body.get("id", "")).strip().upper()
    from backend.config.types import OUT_OF_SCOPE_MACHINES

    if machine_id in OUT_OF_SCOPE_MACHINES:
        raise HTTPException(400, f"{machine_id} está fora do âmbito da análise.")
    if not machine_id:
        raise HTTPException(400, "O identificador da máquina é obrigatório.")
    group = str(body.get("group", body.get("grupo", ""))).strip()
    if not group:
        raise HTTPException(400, "O grupo da máquina é obrigatório.")
    try:
        active = _coerce_bool(body.get("active", body.get("activa", True)))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    from backend.api.replan import start_replan

    return await start_replan(
        {
            "expected_revision": body["expected_revision"],
            "reason": f"Adicionar máquina {machine_id}",
            "config_updates": {
                "machine_additions": [{"id": machine_id, "group": group, "active": active}]
            },
        }
    )


@router.put("/tools/{tid}")
@plan_writer
async def edit_tool(tid: str, body: dict):
    """Edit tool setup_hours or alt machine."""
    _require_data()
    _require_expected_revision(body)
    if "setup_hours" in body:
        try:
            body["setup_hours"] = finite_float(body["setup_hours"], "setup_hours")
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "setup_hours deve ser um número.") from exc
        if not 0 <= body["setup_hours"] <= 8:
            raise HTTPException(400, "setup_hours deve estar no intervalo [0, 8].")
    body["id"] = tid
    return _exec_result(exec_editar_ferramenta(body))


@router.post("/tools")
async def add_tool(body: dict):
    """Queue transactional tool creation for review and explicit application."""
    _require_data()
    _require_config()
    _require_expected_revision(body)
    tool_id = str(body.get("id", "")).strip().upper()
    primary = str(body.get("primary", "")).strip().upper()
    alt = str(body.get("alt", "")).strip().upper() or None
    if not tool_id or not primary:
        raise HTTPException(
            400,
            "A ferramenta e a máquina principal são obrigatórias.",
        )
    try:
        setup_hours = finite_float(
            body.get("setup_hours", state.config.default_setup_hours), "setup_hours"
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "O setup deve ser indicado em horas.") from exc
    if not 0 <= setup_hours <= 8:
        raise HTTPException(400, "O setup deve estar entre 0 e 8 horas.")
    from backend.api.replan import start_replan

    return await start_replan(
        {
            "expected_revision": body["expected_revision"],
            "reason": f"Adicionar ferramenta {tool_id}",
            "config_updates": {
                "tool_additions": [
                    {
                        "id": tool_id,
                        "primary": primary,
                        "alt": alt,
                        "setup_hours": setup_hours,
                    }
                ]
            },
        }
    )


@router.put("/operators")
@plan_writer
async def update_operators(body: dict):
    """Batch update operator counts. Body: { "Grandes A": 6, ... }"""
    _require_config()
    _require_data()
    _require_expected_revision(body)

    old_score = dict(state.score) if state.score else {}
    changed = []
    candidate = copy.deepcopy(state.config)
    for key, count in body.items():
        if key in {
            "expected_revision",
            "approve_exceptions",
            "approval_reason",
            "approval_author",
            "confirm_delivery_risk",
            "reason",
            "author",
            "candidate_id",
            "request_id",
            "dataset_id",
            "base_revision",
            "input_fingerprint",
            "candidate_fingerprint",
        }:
            continue
        try:
            parsed_count = strict_int(count, key)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"Operadores inválidos para {key}: {count!r}") from exc
        if parsed_count < 0:
            raise HTTPException(400, f"Operadores inválidos para {key}: deve ser >= 0")

        if key in candidate.operators:
            candidate.operators[key] = parsed_count
            changed.append(key)
        else:
            # Try tuple key format: "Grandes A" → ("Grandes", "A")
            parts = key.rsplit(" ", 1)
            if len(parts) == 2:
                group, shift = parts
                shift_ids = {item.id for item in candidate.shifts}
                machine_groups = set(candidate.machine_groups.values())
                if shift not in shift_ids:
                    raise HTTPException(
                        400,
                        f"Turno desconhecido para {key}: {shift}",
                    )
                if group not in machine_groups:
                    raise HTTPException(
                        400,
                        f"Grupo desconhecido para {key}: {group}",
                    )
                candidate.operators[(group, shift)] = parsed_count
                changed.append(key)

    if not changed:
        return {"status": "ok", "score": state.score, "score_anterior": old_score}

    result, old_score = _apply_config_candidate(candidate, body)

    return {
        "status": "ok",
        "changed": changed,
        "score": result.score,
        "score_anterior": old_score,
        "gate_report": _result_gate_report(result),
    }


@router.post("/holidays")
@plan_writer
async def add_holiday(body: dict):
    """Add a holiday. Body: { "data": "2026-05-01" }"""
    _require_data()
    _require_expected_revision(body)
    date = body.get("data", "")
    if not date:
        raise HTTPException(400, "Campo 'data' obrigatório.")
    return _exec_result(exec_adicionar_feriado({**body, "data": date}))


def _date_range(body: dict) -> list[str]:
    try:
        date_from = dt_date.fromisoformat(str(body.get("from", "")))
        date_to = dt_date.fromisoformat(str(body.get("to", body.get("from", ""))))
    except ValueError as exc:
        raise HTTPException(400, "Datas 'from'/'to' devem usar o formato YYYY-MM-DD.") from exc
    if date_from > date_to:
        raise HTTPException(400, "A data inicial não pode ser posterior à data final.")
    if (date_to - date_from).days > 366:
        raise HTTPException(400, "O intervalo não pode exceder 366 dias.")
    return [
        (date_from + timedelta(days=offset)).isoformat()
        for offset in range((date_to - date_from).days + 1)
    ]


@router.post("/holidays/range")
@plan_writer
async def add_holiday_range(body: dict):
    """Add a holiday/vacation date range with one transactional replan."""
    _require_data()
    _require_config()
    _require_expected_revision(body)
    dates = _date_range(body)
    candidate = copy.deepcopy(state.config)
    candidate.holidays = sorted(set(candidate.holidays) | set(dates))
    result, old_score = _apply_config_candidate(candidate, body)
    return _calendar_response(result, old_score, holidays=dates)


@router.delete("/holidays/range")
@plan_writer
async def remove_holiday_range(body: dict):
    """Remove all explicit holidays inside a date range with one replan."""
    _require_data()
    _require_config()
    _require_expected_revision(body)
    dates = set(_date_range(body))
    candidate = copy.deepcopy(state.config)
    candidate.holidays = [date for date in candidate.holidays if str(date) not in dates]
    result, old_score = _apply_config_candidate(candidate, body)
    return _calendar_response(result, old_score, holidays=sorted(dates))


@router.post("/workdays-extra")
@plan_writer
async def add_extra_workday(body: dict):
    """Open a normally closed weekend date."""
    _require_data()
    _require_config()
    _require_expected_revision(body)
    date_str = str(body.get("date", body.get("data", "")))
    try:
        parsed = dt_date.fromisoformat(date_str)
    except ValueError as exc:
        raise HTTPException(400, "A data deve usar o formato YYYY-MM-DD.") from exc
    if parsed.weekday() < 5:
        raise HTTPException(400, "Só sábados ou domingos podem ser dias extra.")
    candidate = copy.deepcopy(state.config)
    if date_str not in candidate.extra_workdays:
        candidate.extra_workdays.append(date_str)
        candidate.extra_workdays.sort()
    result, old_score = _apply_config_candidate(candidate, body)
    return _calendar_response(result, old_score, extra_workday=date_str)


@router.delete("/workdays-extra/{date}")
@plan_writer
async def remove_extra_workday(date: str, body: dict):
    _require_data()
    _require_config()
    _require_expected_revision(body)
    candidate = copy.deepcopy(state.config)
    if date not in candidate.extra_workdays:
        raise HTTPException(404, f"Dia de trabalho extra {date} não existe.")
    candidate.extra_workdays.remove(date)
    result, old_score = _apply_config_candidate(candidate, body)
    return _calendar_response(result, old_score, extra_workday=date)


@router.get("/unavailability")
async def get_unavailability():
    _require_data()
    _require_config()
    return {
        "machines": state.config.machine_unavailability,
        "tools": state.config.tool_unavailability,
        "operators": state.config.operator_unavailability,
        "resolved": _resolved_unavailability(),
    }


@router.post("/unavailability")
@plan_writer
async def add_unavailability(body: dict):
    """Persist one machine/tool/operator unavailability range."""
    _require_data()
    _require_config()
    _require_expected_revision(body)
    candidate = copy.deepcopy(state.config)
    try:
        entry = add_unavailability_entry(candidate, state.engine_data, body)
    except UnavailabilityConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    result, old_score = _apply_config_candidate(candidate, body)
    return _calendar_response(result, old_score, entry=entry)


@router.delete("/unavailability/{entry_id}")
@plan_writer
async def remove_unavailability(entry_id: str, body: dict):
    _require_data()
    _require_config()
    _require_expected_revision(body)
    candidate = copy.deepcopy(state.config)
    removed = remove_unavailability_entry(candidate, entry_id)
    if removed is None:
        raise HTTPException(404, f"Indisponibilidade {entry_id} não existe.")
    result, old_score = _apply_config_candidate(candidate, body)
    return _calendar_response(result, old_score, removed=removed)


@router.get("/setup-overrides")
async def get_setup_overrides():
    _require_config()
    return {"items": state.config.setup_overrides}


@router.put("/setup-overrides")
@plan_writer
async def replace_setup_overrides(body: dict):
    """Replace all SKU × machine setup exceptions atomically."""
    _require_data()
    _require_config()
    _require_expected_revision(body)
    raw_items = body.get("items", [])
    if not isinstance(raw_items, list):
        raise HTTPException(400, "items deve ser uma lista.")
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise HTTPException(400, "Cada override deve ser um objeto.")
        try:
            item = {
                "sku": str(raw.get("sku", "")).strip(),
                "machine": str(raw.get("machine", "")).strip(),
                "hours": float(raw.get("hours")),
            }
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "hours deve ser um número.") from exc
        if not item["sku"] or not item["machine"]:
            raise HTTPException(400, "sku e machine são obrigatórios.")
        items.append(item)
    candidate = copy.deepcopy(state.config)
    candidate.setup_overrides = items
    result, old_score = _apply_config_candidate(candidate, body)
    return _calendar_response(result, old_score, items=items)


@router.delete("/holidays/{date}")
@plan_writer
async def remove_holiday(date: str, body: dict):
    """Remove a holiday by ISO date."""
    _require_data()
    _require_expected_revision(body)
    return _exec_result(exec_remover_feriado({**body, "data": date}))


@router.post("/twins")
@plan_writer
async def add_twin(body: dict):
    """Add a twin pair. Body: { "tool_id": "...", "sku_a": "...", "sku_b": "..." }"""
    _require_data()
    _require_expected_revision(body)
    for field in ("tool_id", "sku_a", "sku_b"):
        if field not in body:
            raise HTTPException(400, f"Campo '{field}' obrigatório.")
    return _exec_result(exec_adicionar_twin(body))


@router.delete("/twins/{tool_id}")
@plan_writer
async def remove_twin(tool_id: str, body: dict):
    """Remove a twin pair by tool_id."""
    _require_data()
    _require_expected_revision(body)
    return _exec_result(exec_remover_twin({**body, "tool_id": tool_id}))


@router.post("/presets/{name}")
@plan_writer
async def apply_preset_endpoint(name: str, body: dict):
    """Apply a named config preset (urgente, equilibrado, min_setups, max_otd).

    Each preset resets only the tunables owned by the preset family against the
    load-time baseline, then applies its own overrides. Runtime factory master
    data and unrelated configuration always remain authoritative.

    Any active what-if simulation is preserved — `_recompute` re-applies the
    stored mutations after rescheduling.
    """
    _require_config()
    _require_expected_revision(body)
    from backend.config.presets import apply_preset, get_preset

    try:
        get_preset(name)  # validate name early
    except KeyError as e:
        raise HTTPException(400, str(e))

    # Reset only fields owned by presets. Factory master data and all other
    # live configuration remain authoritative.
    base = state.default_config if state.default_config is not None else state.config
    new_config = apply_preset(
        copy.deepcopy(state.config),
        name,
        baseline=base,
    )
    _result, old_score = _apply_config_candidate(new_config, body)

    return {
        "status": "ok",
        "preset": name,
        "changed": list(get_preset(name).keys()),
        "score": state.score,
        "score_previous": old_score,
        "simulation_active": bool(state.active_mutations),
        "gate_report": state.gate_report,
        "plan_revision": state.plan_revision,
    }
