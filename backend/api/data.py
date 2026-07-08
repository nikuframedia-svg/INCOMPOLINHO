"""Data REST API — direct endpoints for the frontend.

22 endpoints as thin wrappers over CopilotState.
All analytics are pre-computed in state._refresh_analytics().
"""

from __future__ import annotations

import copy
import json
import logging
import tempfile
from dataclasses import asdict
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from backend.config.loader import validate_config
from backend.config.planning import (
    clean_sku_subcontracts,
    normalize_sku_planning_rule,
    normalize_subcontract_company,
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data", tags=["data"])


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


def _validate_mutations(raw_mutations: list[BaseModel], require_non_empty: bool = False):
    if require_non_empty and not raw_mutations:
        raise HTTPException(400, "Pelo menos uma mutação é obrigatória.")

    from backend.simulator.mutations import valid_mutation_types
    from backend.simulator.simulator import Mutation

    allowed = valid_mutation_types()
    mutations = []
    for item in raw_mutations:
        if item.type not in allowed:
            raise HTTPException(400, f"Mutação desconhecida: {item.type}")
        mutations.append(Mutation(type=item.type, params=item.params))
    return mutations


def _mutation_dicts(mutations) -> list[dict]:
    return [{"type": m.type, "params": dict(m.params)} for m in mutations]


def _mutation_models(mutations: list[dict]):
    from backend.simulator.simulator import Mutation

    return [Mutation(type=m["type"], params=m.get("params", {})) for m in mutations]


def _mutation_key(mutation: dict) -> str:
    return json.dumps(
        {"type": mutation["type"], "params": mutation.get("params", {})},
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
            "message": "Plano não aplicável: hard gates ou OTD/OTD-D falharam.",
            "gate_report": report,
        },
    )


def _ensure_result_applicable(result) -> None:
    report = _result_gate_report(result)
    if report is not None and report.get("status") != "applicable":
        raise _gate_exception(report)


def _schedule_result_from_simulation(sim):
    from backend.scheduler.types import ScheduleResult

    return ScheduleResult(
        segments=sim.segments,
        lots=sim.lots,
        score=sim.score,
        time_ms=sim.time_ms,
        warnings=[],
        operator_alerts=[],
        audit_trail=None,
        journal=None,
        gate_report=getattr(sim, "gate_report", None),
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
    )


def _compute_schedule(config):
    """Recalculate the schedule with the given config without mutating state.

    Uses trust-loop `mode="normal"` (baseline JIT/VNS + local CP-SAT gates).
    If there are active what-if mutations (machine down, rush
    order, ...) they are re-applied on top so a config change (e.g. a preset)
    does not silently discard the simulation.
    """
    if state.engine_data is None:
        return None, None

    if state.active_mutations:
        from backend.cpo import optimize
        from backend.simulator.simulator import Mutation, simulate

        baseline = optimize(state.engine_data, mode="normal", audit=True, config=config)

        mutations = [
            Mutation(type=m["type"], params=m.get("params", {})) for m in state.active_mutations
        ]
        sim = simulate(state.engine_data, baseline.score, mutations, config=config)
        return _schedule_result_from_simulation(sim), baseline

    from backend.cpo import optimize

    return optimize(state.engine_data, mode="normal", audit=True, config=config), None


def _recompute(config):
    """Recalculate, validate and update state atomically."""

    if state.engine_data is None:
        state.config = config
        return None

    result, baseline = _compute_schedule(config)
    state.config = config
    state.update_schedule(result)
    if baseline is not None:
        state.saved_schedule = baseline
    return result


def _recompute_transactional(config):
    """Recalculate with rollback if the candidate plan is invalid."""
    engine_snapshot = copy.deepcopy(state.engine_data)
    config_snapshot = copy.deepcopy(state.config)
    saved_snapshot = copy.deepcopy(state.saved_schedule)
    saved_mutations_snapshot = copy.deepcopy(state.saved_mutations)
    mutations_snapshot = copy.deepcopy(state.active_mutations)
    segments_snapshot = copy.deepcopy(state.segments)
    lots_snapshot = copy.deepcopy(state.lots)
    score_snapshot = copy.deepcopy(state.score)
    warnings_snapshot = copy.deepcopy(state.warnings)
    journal_snapshot = copy.deepcopy(state.journal_entries)
    operator_alerts_snapshot = copy.deepcopy(state.operator_alerts)
    gate_report_snapshot = copy.deepcopy(state.gate_report)
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
        result = _recompute(config)
        _ensure_result_applicable(result)
        return result
    except Exception:
        state.engine_data = engine_snapshot
        state.config = config_snapshot
        state.saved_schedule = saved_snapshot
        state.saved_mutations = saved_mutations_snapshot
        state.active_mutations = mutations_snapshot
        state.segments = segments_snapshot
        state.lots = lots_snapshot
        state.score = score_snapshot
        state.warnings = warnings_snapshot
        state.journal_entries = journal_snapshot
        state.operator_alerts = operator_alerts_snapshot
        state.gate_report = gate_report_snapshot
        for key, value in analytics_snapshot.items():
            setattr(state, key, value)
        raise


def _compute_schedule_for_preview(engine_data, config):
    """Compute schedule on a detached EngineData copy."""
    from backend.cpo import optimize

    if state.active_mutations:
        from backend.simulator.simulator import Mutation, simulate

        baseline = optimize(engine_data, mode="normal", audit=True, config=config)
        mutations = [
            Mutation(type=m["type"], params=m.get("params", {})) for m in state.active_mutations
        ]
        sim = simulate(engine_data, baseline.score, mutations, config=config)
        return _schedule_result_from_simulation(sim), baseline

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
    warnings = [
        lot.economic_warning
        for lot in lots
        if getattr(lot, "economic_warning", None)
    ]
    return {
        "lots": len(lots),
        "segments": len(segments),
        "qty": sum(lot.qty for lot in lots),
        "prod_min": round(sum(lot.prod_min for lot in lots), 1),
        "setups": sum(1 for seg in segments if seg.setup_min > 0),
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


# ═══════════════════════════════════════════════════════════════════════════
# CORE (5)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/today")
async def get_today():
    """Return today's day_idx based on workdays calendar."""
    _require_data()
    import datetime as _dt

    today = _dt.date.today().isoformat()
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
    return state.score


@router.get("/segments")
async def get_segments():
    _require_data()
    return [asdict(s) for s in state.segments]


@router.get("/lots")
async def get_lots():
    _require_data()
    return [asdict(lot) for lot in state.lots]


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
    return asdict(state.expedition)


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
    return asdict(state.risk_result)


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

    wf = forecast_workforce(state.segments, state.engine_data, state.config, window)
    return asdict(wf)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG / MASTER DATA (3)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/config")
async def get_config():
    _require_config()
    c = state.config
    return {
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
        "machines": {mid: {"group": m.group, "active": m.active} for mid, m in c.machines.items()},
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
        # Tunables
        "oee_default": c.oee_default,
        "subcontract_skus": c.subcontract_skus,
        "sku_planning_rules": c.sku_planning_rules,
        "subcontract_companies": c.subcontract_companies,
        "sku_subcontracts": c.sku_subcontracts,
        "setup_crews": c.setup_crews,
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
    return [
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
            "subcontract_company_id": op.subcontract_company_id,
            "subcontract_lead_time_days": op.subcontract_lead_time_days,
            "subcontract_buffer_days": op.subcontract_buffer_days,
            "stock": op.stk,
            "oee": op.oee,
            "backlog": op.backlog,
            "operators": op.operators,
            "demand": op.d,
        }
        for op in state.engine_data.ops
    ]


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
async def update_sku_planning(sku: str, body: dict):
    """Apply SKU planning rule and recalculate the active schedule."""
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

    from backend.config.loader import save_config

    old_score = dict(state.score) if state.score else {}
    try:
        result = _recompute_transactional(candidate)
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    state.config = candidate
    save_config(candidate)

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
async def reset_sku_planning(sku: str):
    """Remove SKU planning overrides and return to ISOP values."""
    _require_data()
    _require_config()
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

    from backend.config.loader import save_config

    old_score = dict(state.score) if state.score else {}
    try:
        result = _recompute_transactional(candidate)
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    state.config = candidate
    save_config(candidate)

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
        "companies": state.config.subcontract_companies,
        "sku_subcontracts": state.config.sku_subcontracts,
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
async def update_subcontracts(body: dict):
    """Apply subcontract companies/SKU rules and recalculate schedule."""
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

    from backend.config.loader import save_config

    old_score = dict(state.score) if state.score else {}
    try:
        result = _recompute_transactional(candidate)
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    state.config = candidate
    save_config(candidate)

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
async def update_config(updates: dict):
    """Update tunable config parameters and recalculate schedule."""
    _require_config()

    tunables = [
        "oee_default",
        "jit_enabled",
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
        "setup_crews",
        "weight_earliness",
        "weight_setups",
        "weight_balance",
        "eco_lot_mode",
    ]
    current = state.config
    candidate = copy.deepcopy(current)
    updates_to_apply = []
    for key in tunables:
        if key in updates:
            try:
                new_val = _coerce_tunable_value(key, getattr(candidate, key), updates[key])
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            updates_to_apply.append((key, new_val))

    if not updates_to_apply:
        return {"status": "ok", "changed": [], "score": state.score}

    changed = []
    for key, new_val in updates_to_apply:
        setattr(candidate, key, new_val)
        changed.append(key)

    errors = validate_config(candidate)
    if errors:
        raise HTTPException(400, {"message": "Configuração inválida", "errors": errors})

    from backend.config.loader import save_config

    try:
        _recompute_transactional(candidate)
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    state.config = candidate
    save_config(candidate)

    return {
        "status": "ok",
        "changed": changed,
        "score": state.score,
        "gate_report": state.gate_report,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ACTIONS (3)
# ═══════════════════════════════════════════════════════════════════════════


class MutationInput(BaseModel):
    type: str
    params: dict = {}


class SimulateRequest(BaseModel):
    mutations: list[MutationInput]


@router.post("/simulate")
async def simulate_scenario(request: SimulateRequest):
    _require_data()
    from backend.simulator.simulator import simulate

    mutations = _validate_mutations(request.mutations, require_non_empty=True)
    scenario_mutations = _compose_active_mutations(mutations)
    try:
        result = simulate(
            state.engine_data,
            state.score,
            _mutation_models(scenario_mutations),
            config=state.config,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    return {
        "score_baseline": state.score,
        "score_scenario": result.score,
        "delta": asdict(result.delta),
        "time_ms": result.time_ms,
        "summary": result.summary,
        "segments": [asdict(s) for s in result.segments],
        "lots": [asdict(lot) for lot in result.lots],
        "gate_report": _result_gate_report(result),
    }


@router.post("/simulate-apply")
async def simulate_and_apply(request: SimulateRequest):
    """Run simulation and apply result as active schedule. Saves snapshot for revert."""
    _require_data()
    from backend.simulator.simulator import simulate

    old_score = dict(state.score) if state.score else {}
    old_n = len(state.segments)

    mutations = _validate_mutations(request.mutations, require_non_empty=True)
    combined_mutations = _compose_active_mutations(mutations)
    try:
        result = simulate(
            state.engine_data,
            old_score,
            _mutation_models(combined_mutations),
            config=state.config,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    _ensure_result_applicable(result)
    state.save_current()
    state.update_schedule(_schedule_result_from_simulation(result))

    # Persist mutations so a later recompute (e.g. preset) keeps them applied
    state.active_mutations = combined_mutations

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
    }


@router.post("/revert")
async def revert_simulation():
    """Revert to schedule saved before simulate-apply."""
    _require_data()
    if not state.saved_schedule:
        raise HTTPException(400, "Nada para reverter.")
    state.update_schedule(state.saved_schedule)
    state.saved_schedule = None
    state.active_mutations = copy.deepcopy(state.saved_mutations or [])
    state.saved_mutations = None
    return {"status": "reverted", "score": state.score}


@router.get("/can-revert")
async def can_revert():
    """Check if there is a saved schedule to revert to."""
    return {"can_revert": state.saved_schedule is not None}


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
    qty: int
    deadline: int


@router.post("/ctp")
async def check_ctp(request: CTPRequest):
    _require_data()
    if request.qty <= 0:
        raise HTTPException(400, "A quantidade deve ser maior que zero.")
    if request.deadline < 0 or request.deadline >= state.engine_data.n_days:
        raise HTTPException(400, "Deadline fora do horizonte do ISOP.")

    from backend.analytics.ctp import compute_ctp
    from backend.config.planning import effective_internal_deadline_for_op

    op = next((o for o in state.engine_data.ops if o.sku == request.sku), None)
    effective_deadline = (
        effective_internal_deadline_for_op(op, request.deadline)
        if op is not None
        else request.deadline
    )

    result = compute_ctp(
        request.sku,
        request.qty,
        effective_deadline,
        state.segments,
        state.engine_data,
        config=state.config,
    )
    return {
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
        "effective_deadline": effective_deadline,
    }


@router.post("/ctp-apply")
async def apply_ctp(request: CTPRequest):
    """Apply CTP as a rush order: add demand + reschedule."""
    _require_data()
    if request.qty <= 0:
        raise HTTPException(400, "A quantidade deve ser maior que zero.")
    if request.deadline < 0 or request.deadline >= state.engine_data.n_days:
        raise HTTPException(400, "Deadline fora do horizonte do ISOP.")

    from backend.analytics.ctp import compute_ctp
    from backend.config.planning import effective_internal_deadline_for_op
    from backend.simulator.simulator import simulate

    old_score = dict(state.score) if state.score else {}
    old_n = len(state.segments)

    op = next((o for o in state.engine_data.ops if o.sku == request.sku), None)
    if op is None:
        raise HTTPException(404, f"SKU {request.sku} não encontrado.")

    effective_deadline = effective_internal_deadline_for_op(op, request.deadline)
    before_ctp = compute_ctp(
        request.sku,
        request.qty,
        effective_deadline,
        state.segments,
        state.engine_data,
        config=state.config,
    )
    if not before_ctp.feasible:
        raise HTTPException(400, before_ctp.reason or "CTP não é viável.")

    rush_params = {
        "sku": request.sku,
        "qty": str(request.qty),
        "deadline_day": str(request.deadline),
    }
    new_mutation = {"type": "rush_order", "params": rush_params}
    combined_mutations = copy.deepcopy(state.active_mutations) + [new_mutation]
    try:
        result = simulate(
            state.engine_data,
            old_score,
            _mutation_models(combined_mutations),
            config=state.config,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    _ensure_result_applicable(result)
    state.save_current()
    state.update_schedule(_schedule_result_from_simulation(result))

    # Persist mutation so a later recompute (e.g. preset) keeps it applied
    state.active_mutations = combined_mutations
    after_ctp = compute_ctp(
        request.sku,
        request.qty,
        effective_deadline,
        state.segments,
        state.engine_data,
        config=state.config,
    )

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
        "promise": {
            "requested_deadline": request.deadline,
            "effective_deadline": effective_deadline,
            "promised_machine": before_ctp.machine,
            "promised_latest_day": before_ctp.latest_day,
            "promised_end_day": before_ctp.earliest_end_day,
            "post_apply_feasible_for_same_request": after_ctp.feasible,
            "post_apply_machine": after_ctp.machine,
            "post_apply_latest_day": after_ctp.latest_day,
            "post_apply_end_day": after_ctp.earliest_end_day,
            "post_apply_reason": after_ctp.reason,
        },
    }


@router.post("/recalculate")
async def recalculate():
    _require_data()

    old_score = dict(state.score) if state.score else {}
    try:
        result = _recompute_transactional(state.config)
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
    }


# ═══════════════════════════════════════════════════════════════════════════
# UPLOAD (1)
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/load")
async def load_isop_upload(
    file: UploadFile,
    config_path: str = "config/factory.yaml",
    master_path: str = "config/incompol.yaml",
):
    """Load ISOP from uploaded file (multipart/form-data)."""
    from backend.config.loader import load_config
    from backend.config.planning import apply_effective_planning_config
    from backend.cpo import optimize
    from backend.dqa import compute_trust_index
    from backend.parser.isop_reader import read_isop
    from backend.transform.transform import transform

    # Save uploaded file to temp
    suffix = Path(file.filename or "upload.xlsx").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        config = load_config(config_path)
        with open(master_path) as f:
            master = yaml.safe_load(f)

        rows, workdays, has_twin = read_isop(tmp_path)
        engine_data = transform(rows, workdays, has_twin, master)
        apply_effective_planning_config(engine_data, config)
        result = optimize(
            engine_data,
            mode="normal",
            audit=True,
            config=config,
        )

        state.clear_runtime_for_new_dataset()
        state.default_config = copy.deepcopy(config)
        state.engine_data = engine_data
        state.config = config
        state.update_schedule(result)
        state._load_rules()

        # DQA trust index
        trust = compute_trust_index(engine_data, config)
        state.trust_index = trust

        # Journal summary
        journal_summary = None
        if result.journal:
            journal_summary = {
                "total": len(result.journal),
                "warnings": len(
                    [e for e in result.journal if e.get("severity") in ("warn", "error")]
                ),
            }

        learning_info = {
            "optimized": True,
            "mode": "normal",
            "time_ms": result.time_ms,
        }
        state.learning_info = learning_info
        dataset = state.set_dataset_info(
            file.filename or "upload.xlsx",
            result,
            trust,
            len(engine_data.ops),
        )

        return {
            "status": "ok",
            "n_ops": len(engine_data.ops),
            "n_segments": len(result.segments),
            "score": result.score,
            "time_ms": result.time_ms,
            "trust_index": {"score": trust.score, "gate": trust.gate},
            "journal_summary": journal_summary,
            "learning": learning_info,
            "dataset": dataset,
            "gate_report": _result_gate_report(result),
        }
    finally:
        Path(tmp_path).unlink(missing_ok=True)


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
async def edit_machine(mid: str, body: dict):
    """Toggle machine active/inactive or change group."""
    _require_data()
    body["id"] = mid
    return _exec_result(exec_editar_maquina(body))


@router.put("/tools/{tid}")
async def edit_tool(tid: str, body: dict):
    """Edit tool setup_hours or alt machine."""
    _require_data()
    body["id"] = tid
    return _exec_result(exec_editar_ferramenta(body))


@router.put("/operators")
async def update_operators(body: dict):
    """Batch update operator counts. Body: { "Grandes A": 6, ... }"""
    _require_config()
    _require_data()

    from backend.config.loader import save_config

    old_score = dict(state.score) if state.score else {}
    changed = []
    candidate = copy.deepcopy(state.config)
    for key, count in body.items():
        try:
            parsed_count = int(count)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"Operadores inválidos para {key}: {count!r}") from exc
        if parsed_count < 0:
            raise HTTPException(400, f"Operadores inválidos para {key}: deve ser >= 0")

        if key in candidate.operators:
            candidate.operators[key] = parsed_count
            changed.append(key)
        else:
            # Try tuple key format: "Grandes A" → ("Grandes", "A")
            parts = key.split()
            if len(parts) == 2:
                tkey = (parts[0], parts[1])
                if tkey in candidate.operators:
                    candidate.operators[tkey] = parsed_count
                    changed.append(key)

    if not changed:
        return {"status": "ok", "score": state.score, "score_anterior": old_score}

    try:
        result = _recompute_transactional(candidate)
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc
    state.config = candidate
    save_config(candidate)

    return {
        "status": "ok",
        "changed": changed,
        "score": result.score,
        "score_anterior": old_score,
        "gate_report": _result_gate_report(result),
    }


@router.post("/holidays")
async def add_holiday(body: dict):
    """Add a holiday. Body: { "data": "2026-05-01" }"""
    _require_data()
    date = body.get("data", "")
    if not date:
        raise HTTPException(400, "Campo 'data' obrigatório.")
    return _exec_result(exec_adicionar_feriado({"data": date}))


@router.delete("/holidays/{date}")
async def remove_holiday(date: str):
    """Remove a holiday by ISO date."""
    _require_data()
    return _exec_result(exec_remover_feriado({"data": date}))


@router.post("/twins")
async def add_twin(body: dict):
    """Add a twin pair. Body: { "tool_id": "...", "sku_a": "...", "sku_b": "..." }"""
    _require_data()
    for field in ("tool_id", "sku_a", "sku_b"):
        if field not in body:
            raise HTTPException(400, f"Campo '{field}' obrigatório.")
    return _exec_result(exec_adicionar_twin(body))


@router.delete("/twins/{tool_id}")
async def remove_twin(tool_id: str):
    """Remove a twin pair by tool_id."""
    _require_data()
    return _exec_result(exec_remover_twin({"tool_id": tool_id}))


@router.post("/presets/{name}")
async def apply_preset_endpoint(name: str):
    """Apply a named config preset (urgente, equilibrado, min_setups, max_otd).

    Each preset is PURE: it starts from the pristine `default_config` snapshot
    captured at ISOP load and applies only its own overrides on top. Presets
    therefore never accumulate each other's parameters, and `equilibrado` ({})
    correctly resets everything back to the factory defaults.

    Any active what-if simulation is preserved — `_recompute` re-applies the
    stored mutations after rescheduling.
    """
    _require_config()
    from backend.config.loader import save_config
    from backend.config.presets import apply_preset, get_preset

    try:
        get_preset(name)  # validate name early
    except KeyError as e:
        raise HTTPException(400, str(e))

    # Baseline: pristine config from load (fallback to current if missing)
    base = state.default_config if state.default_config is not None else state.config
    new_config = apply_preset(copy.deepcopy(base), name)
    if hasattr(state.config, "subcontract_skus"):
        new_config.subcontract_skus = list(state.config.subcontract_skus)
    if hasattr(state.config, "sku_planning_rules"):
        new_config.sku_planning_rules = copy.deepcopy(state.config.sku_planning_rules)
    if hasattr(state.config, "subcontract_companies"):
        new_config.subcontract_companies = copy.deepcopy(state.config.subcontract_companies)
    if hasattr(state.config, "sku_subcontracts"):
        new_config.sku_subcontracts = copy.deepcopy(state.config.sku_subcontracts)

    old_score = dict(state.score) if state.score else {}
    try:
        _recompute_transactional(new_config)
    except (KeyError, TypeError, ValueError) as exc:
        raise _plan_validation_error(exc) from exc

    state.config = new_config
    save_config(new_config)

    return {
        "status": "ok",
        "preset": name,
        "changed": list(get_preset(name).keys()),
        "score": state.score,
        "score_previous": old_score,
        "simulation_active": bool(state.active_mutations),
        "gate_report": state.gate_report,
    }
