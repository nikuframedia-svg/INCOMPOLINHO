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

from backend.copilot.state import state
from backend.copilot.executors_master import (
    exec_editar_maquina,
    exec_editar_ferramenta,
    exec_adicionar_feriado,
    exec_remover_feriado,
    exec_adicionar_twin,
    exec_remover_twin,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data", tags=["data"])


def _require_data():
    """Raise 503 if no ISOP data loaded."""
    if state.engine_data is None:
        raise HTTPException(503, "Sem dados carregados. Carrega um ISOP primeiro.")


def _require_config():
    if state.config is None:
        raise HTTPException(503, "Configuração não carregada.")


def _compute_schedule_for_config(config):
    """Build a schedule for a config without mutating global state.

    Always uses GA-backed `mode="normal"` (NOT "quick" — quick is greedy-only
    and drops OTD), in BOTH branches. If there are active what-if mutations
    (machine down, rush order, ...) they are re-applied on top — via
    `simulate(..., mode="normal")` — so a config change (e.g. a preset) does
    not silently discard the simulation nor downgrade its quality.
    """
    if state.active_mutations:
        from backend.scheduler.types import ScheduleResult
        from backend.simulator.simulator import Mutation, simulate

        mutations = [
            Mutation(type=m["type"], params=m.get("params", {}))
            for m in state.active_mutations
        ]
        sim = simulate(state.engine_data, state.score, mutations, config=config, mode="normal")
        return ScheduleResult(
            segments=sim.segments,
            lots=sim.lots,
            score=sim.score,
            time_ms=sim.time_ms,
            warnings=[],
            operator_alerts=[],
            audit_trail=None,
            journal=None,
        ), list(sim.summary)

    from backend.cpo import optimize

    return optimize(state.engine_data, mode="normal", audit=True, config=config), []


def _commit_recompute(result, simulation_summary: list[str] | None = None) -> None:
    """Commit a prevalidated schedule to global state."""
    state.update_schedule(result)
    if state.active_mutations:
        state.active_simulation_summary = list(simulation_summary or [])
    elif not state.active_mutations:
        state.active_simulation_summary = []


def _validate_candidate_result(result, simulation_summary: list[str] | None = None) -> dict:
    physical_violations = _physical_violations(result.score)
    plan_violations = _plan_violations(result.score)
    return {
        "status": "invalid" if plan_violations else "ok",
        "score": result.score,
        "summary": list(simulation_summary or []),
        "hard_gate_violations": physical_violations,
        "plan_violations": plan_violations,
    }


def _recompute(config) -> dict:
    """Recalculate and commit only if the candidate plan is valid."""
    if state.engine_data is None:
        return {"status": "skipped", "score": state.score}

    result, simulation_summary = _compute_schedule_for_config(config)
    validation = _validate_candidate_result(result, simulation_summary)
    if validation["status"] == "invalid":
        return validation

    _commit_recompute(result, simulation_summary)
    return validation | {"score": state.score}


PHYSICAL_HARD_GATES = (
    "tool_conflicts",
    "machine_overlaps",
    "day_cap_violations",
    "ghost_segments",
    "blocked_machine_segments",
    "blocked_tool_segments",
    "setup_sequence_violations",
    "run_lot_order_violations",
)


def _physical_violations(score: dict | None) -> dict[str, int]:
    """Return non-zero hard gate counters from a schedule score."""
    if not score:
        return {"empty_result": 1}
    return {
        key: int(score.get(key, 0) or 0)
        for key in PHYSICAL_HARD_GATES
        if int(score.get(key, 0) or 0) > 0
    }


def _kpi_violations(score: dict | None) -> dict[str, float | int]:
    """Return delivery KPI violations that must not be applied to the Gantt."""
    if not score:
        return {"empty_result": 1}

    violations: dict[str, float | int] = {}
    otd = float(score.get("otd", 0.0) or 0.0)
    otd_d = float(score.get("otd_d", 0.0) or 0.0)
    tardy_count = int(score.get("tardy_count", 0) or 0)
    otd_d_failures = int(score.get("otd_d_failures", 0) or 0)

    if otd < 99.999:
        violations["otd_below_100"] = round(otd, 3)
    if otd_d < 99.999:
        violations["otd_d_below_100"] = round(otd_d, 3)
    if tardy_count > 0:
        violations["tardy_count"] = tardy_count
    if otd_d_failures > 0:
        violations["otd_d_failures"] = otd_d_failures

    return violations


def _plan_violations(score: dict | None) -> dict[str, float | int]:
    """Return all violations that make a user-visible plan invalid."""
    return {**_physical_violations(score), **_kpi_violations(score)}


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
            {"name": d.name, "score": d.score, "details": d.details}
            for d in t.dimensions
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
        compute_stress_map, stress_summary, stress_recommendations,
    )
    smap = state.stress_map or compute_stress_map(
        state.segments, state.lots, state.engine_data.n_days,
        n_holidays=len(getattr(state.engine_data, 'holidays', []) or []),
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
        "machines": {
            mid: {"group": m.group, "active": m.active}
            for mid, m in c.machines.items()
        },
        "tools": {
            tid: (
                {"primary": t.get("primary", ""), "alt": t.get("alt"), "setup_hours": t.get("setup_hours", 0.5)}
                if isinstance(t, dict) else
                {"primary": t.primary, "alt": t.alt, "setup_hours": t.setup_hours}
            )
            for tid, t in c.tools.items()
        },
        "twins": (
            [{"tool_id": tid, "sku_a": skus[0], "sku_b": skus[1]} for tid, skus in c.twins.items()]
            if isinstance(c.twins, dict) else
            [{"tool_id": tw.tool_id, "sku_a": tw.sku_a, "sku_b": tw.sku_b} for tw in c.twins]
        ),
        "operators": {f"{k[0]} {k[1]}" if isinstance(k, tuple) else str(k): v for k, v in c.operators.items()},
        "holidays": [str(h) for h in c.holidays],
        # Tunables
        "oee_default": c.oee_default,
        "jit_enabled": c.jit_enabled,
        "jit_buffer_pct": c.jit_buffer_pct,
        "jit_threshold": c.jit_threshold,
        "max_run_days": c.max_run_days,
        "max_edd_gap": c.max_edd_gap,
        "edd_swap_tolerance": c.edd_swap_tolerance,
        "campaign_window": c.campaign_window,
        "urgency_threshold": c.urgency_threshold,
        "interleave_enabled": c.interleave_enabled,
        "weight_earliness": c.weight_earliness,
        "weight_setups": c.weight_setups,
        "weight_balance": c.weight_balance,
        "eco_lot_mode": c.eco_lot_mode,
        "subcontract_skus": dict(c.subcontract_skus),
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
            "stock": op.stk,
            "oee": op.oee,
            "backlog": op.backlog,
            "operators": op.operators,
            "demand": op.d,
        }
        for op in state.engine_data.ops
    ]


@router.get("/rules")
async def get_rules():
    return state.rules


@router.put("/config")
async def update_config(updates: dict):
    """Update tunable config parameters and recalculate schedule."""
    _require_config()

    tunables = [
        "oee_default", "jit_enabled", "jit_buffer_pct", "jit_threshold",
        "max_run_days", "max_edd_gap", "edd_swap_tolerance", "campaign_window",
        "urgency_threshold", "interleave_enabled", "weight_earliness",
        "weight_setups", "weight_balance", "eco_lot_mode",
    ]
    c = state.config
    candidate = copy.deepcopy(c)
    changed = []
    for key in tunables:
        if key in updates:
            old_val = getattr(candidate, key)
            new_val = type(old_val)(updates[key])
            if new_val != old_val:
                changed.append(key)

    if not changed:
        return {"status": "ok", "changed": [], "score": state.score}

    for key in changed:
        old_val = getattr(candidate, key)
        setattr(candidate, key, type(old_val)(updates[key]))

    candidate_result = None
    candidate_summary: list[str] = []
    if state.engine_data is not None:
        candidate_result, candidate_summary = _compute_schedule_for_config(candidate)
        validation = _validate_candidate_result(candidate_result, candidate_summary)
        if validation["status"] == "invalid":
            return {
                "status": "invalid",
                "changed": changed,
                "score": state.score,
                "score_candidate": candidate_result.score,
                "summary": validation["summary"],
                "hard_gate_violations": validation["hard_gate_violations"],
                "plan_violations": validation["plan_violations"],
            }

    state.save_current(kind="config")
    state.config = candidate

    from backend.config.loader import save_config
    save_config(candidate)

    if candidate_result is not None:
        _commit_recompute(candidate_result, candidate_summary)

    return {"status": "ok", "changed": changed, "score": state.score}


class SubcontractRequest(BaseModel):
    sku: str
    enabled: bool
    lead_days: int | None = None


def _resolve_subcontract_sku(identifier: str) -> tuple[str, str | None]:
    """Resolve user-facing subcontract identifiers to the real SKU key.

    Operators often refer to rows by the ISOP/op prefix (e.g. HAN002), while
    the scheduler stores subcontract lead times by SKU. Accept both exact SKU
    and unique op_id/prefix matches, then persist the canonical SKU.
    """
    _require_data()
    token = identifier.strip()
    if not token:
        raise HTTPException(400, "Campo 'sku' obrigatório.")

    for op in state.engine_data.ops:
        if op.sku == token:
            return op.sku, None

    matches = {
        op.sku for op in state.engine_data.ops
        if op.id == token or op.id.startswith(f"{token}_")
    }
    if len(matches) == 1:
        return next(iter(matches)), token
    if len(matches) > 1:
        raise HTTPException(
            400,
            f"Identificador {token} é ambíguo; usa o SKU exacto.",
        )
    raise HTTPException(404, f"SKU {token} não encontrado.")


@router.put("/subcontract")
async def update_subcontract(request: SubcontractRequest):
    """Enable/disable subcontract lead time for a SKU and recalculate."""
    _require_config()
    _require_data()

    sku, alias = _resolve_subcontract_sku(request.sku)

    lead_days = 5 if request.lead_days is None else int(request.lead_days)
    if lead_days < 0:
        raise HTTPException(400, "lead_days deve ser >= 0.")

    current = dict(state.config.subcontract_skus)
    if request.enabled:
        current[sku] = lead_days
    else:
        current.pop(sku, None)

    if current == state.config.subcontract_skus:
        return {
            "status": "ok",
            "sku": sku,
            "alias": alias,
            "enabled": request.enabled,
            "lead_days": current.get(sku),
            "score": state.score,
            "score_anterior": state.score,
        }

    old_score = dict(state.score) if state.score else {}
    candidate = copy.deepcopy(state.config)
    candidate.subcontract_skus = current

    candidate_result, candidate_summary = _compute_schedule_for_config(candidate)
    validation = _validate_candidate_result(candidate_result, candidate_summary)
    if validation["status"] == "invalid":
        return {
            "status": "invalid",
            "sku": sku,
            "alias": alias,
            "enabled": request.enabled,
            "lead_days": current.get(sku),
            "score": state.score,
            "score_candidate": candidate_result.score,
            "score_anterior": old_score,
            "summary": validation["summary"],
            "hard_gate_violations": validation["hard_gate_violations"],
            "plan_violations": validation["plan_violations"],
            "can_revert": bool(state.config_snapshot or state.simulation_snapshot),
        }

    state.save_current(kind="config")
    state.config = candidate

    from backend.config.loader import save_config
    save_config(state.config)
    _commit_recompute(candidate_result, candidate_summary)

    return {
        "status": "ok",
        "sku": sku,
        "alias": alias,
        "enabled": request.enabled,
        "lead_days": current.get(sku),
        "score": state.score,
        "score_anterior": old_score,
        "can_revert": True,
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
    from backend.simulator.simulator import Mutation, simulate

    mutations = [Mutation(type=m.type, params=m.params) for m in request.mutations]
    result = simulate(state.engine_data, state.score, mutations, config=state.config, mode="normal")
    physical_violations = _physical_violations(result.score)
    plan_violations = _plan_violations(result.score)

    return {
        "status": "invalid" if plan_violations else "ok",
        "score_baseline": state.score,
        "score_scenario": result.score,
        "delta": asdict(result.delta),
        "time_ms": result.time_ms,
        "summary": result.summary,
        "hard_gate_violations": physical_violations,
        "plan_violations": plan_violations,
    }


@router.post("/simulate-apply")
async def simulate_and_apply(request: SimulateRequest):
    """Run simulation and apply result as active schedule. Saves snapshot for revert."""
    _require_data()
    from backend.simulator.simulator import Mutation, simulate

    old_score = dict(state.score) if state.score else {}
    old_n = len(state.segments)

    mutations = [Mutation(type=m.type, params=m.params) for m in request.mutations]
    result = simulate(state.engine_data, old_score, mutations, config=state.config, mode="normal")
    physical_violations = _physical_violations(result.score)
    plan_violations = _plan_violations(result.score)
    if plan_violations:
        return {
            "status": "invalid",
            "score": result.score,
            "score_previous": old_score,
            "summary": result.summary,
            "hard_gate_violations": physical_violations,
            "plan_violations": plan_violations,
            "n_segments_before": old_n,
            "n_segments_after": len(result.segments),
            "time_ms": result.time_ms,
            "can_revert": bool(state.simulation_snapshot or state.config_snapshot),
        }

    from backend.scheduler.types import ScheduleResult
    schedule_result = ScheduleResult(
        segments=result.segments,
        lots=result.lots,
        score=result.score,
        time_ms=result.time_ms,
        warnings=[],
        operator_alerts=[],
        audit_trail=None,
        journal=None,
    )
    state.save_current(kind="simulation")
    state.update_schedule(schedule_result)

    # Persist mutations so a later recompute (e.g. preset) keeps them applied
    state.active_mutations = [
        {"type": m.type, "params": m.params} for m in request.mutations
    ]
    state.active_simulation_summary = list(result.summary)

    return {
        "status": "applied",
        "score": result.score,
        "score_previous": old_score,
        "summary": result.summary,
        "hard_gate_violations": {},
        "plan_violations": {},
        "n_segments_before": old_n,
        "n_segments_after": len(result.segments),
        "time_ms": result.time_ms,
        "can_revert": True,
    }


@router.post("/revert-simulation")
async def revert_simulation():
    """Revert the active simulation snapshot without changing config."""
    _require_data()
    if not state.simulation_snapshot and not state.saved_schedule:
        raise HTTPException(400, "Nada para reverter.")
    try:
        kind = state.restore_saved("simulation")
    except ValueError as e:
        raise HTTPException(400, str(e))
    if state.config is not None:
        recompute = _recompute(state.config)
        if recompute.get("status") == "invalid":
            return {"status": "invalid", "kind": kind, **recompute}
    return {"status": "reverted", "kind": kind, "score": state.score}


@router.post("/revert-config")
async def revert_config():
    """Revert the last config/master-data change without clearing simulations."""
    _require_data()
    if not state.config_snapshot:
        raise HTTPException(400, "Nada para reverter.")
    try:
        kind = state.restore_saved("config")
    except ValueError as e:
        raise HTTPException(400, str(e))
    if state.config is not None:
        from backend.config.loader import save_config
        save_config(state.config)
    return {"status": "reverted", "kind": kind, "score": state.score}


@router.post("/clear-simulation")
async def clear_simulation():
    """Clear active what-if mutations and recompute current config."""
    _require_data()
    old_active_mutations = copy.deepcopy(state.active_mutations)
    old_summary = copy.deepcopy(state.active_simulation_summary)
    old_snapshot = state.simulation_snapshot
    state.active_mutations = []
    state.active_simulation_summary = []
    state.simulation_snapshot = None
    if state.config is not None:
        recompute = _recompute(state.config)
        if recompute.get("status") == "invalid":
            state.active_mutations = old_active_mutations
            state.active_simulation_summary = old_summary
            state.simulation_snapshot = old_snapshot
            return {"status": "invalid", "kind": "simulation", **recompute}
    return {"status": "cleared", "kind": "simulation", "score": state.score}


@router.post("/revert")
async def revert_legacy():
    """Backward-compatible alias; prefer explicit revert endpoints."""
    _require_data()
    kind = state.saved_snapshot.kind if state.saved_snapshot else None
    if kind == "config":
        return await revert_config()
    return await revert_simulation()


@router.get("/can-revert")
async def can_revert():
    """Check if there is a saved schedule to revert to."""
    kind = state.saved_snapshot.kind if state.saved_snapshot else None
    if kind is None and state.simulation_snapshot is not None:
        kind = "simulation"
    if kind is None and state.config_snapshot is not None:
        kind = "config"
    if kind is None and state.saved_schedule is not None:
        kind = "simulation"
    return {
        "can_revert": bool(state.simulation_snapshot or state.config_snapshot or state.saved_snapshot or state.saved_schedule),
        "kind": kind,
        "can_revert_simulation": state.simulation_snapshot is not None,
        "can_revert_config": state.config_snapshot is not None,
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
        "summary": state.active_simulation_summary,
    }


class CTPRequest(BaseModel):
    sku: str
    qty: int
    deadline: int


@router.post("/ctp")
async def check_ctp(request: CTPRequest):
    _require_data()
    from backend.analytics.ctp import compute_ctp

    result = compute_ctp(
        request.sku, request.qty, request.deadline,
        state.segments, state.engine_data, config=state.config,
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
    }


@router.post("/ctp-apply")
async def apply_ctp(request: CTPRequest):
    """Apply CTP as a rush order: add demand + reschedule."""
    _require_data()
    from backend.simulator.simulator import Mutation, simulate
    from backend.scheduler.types import ScheduleResult

    old_score = dict(state.score) if state.score else {}
    old_n = len(state.segments)

    rush_params = {
        "sku": request.sku,
        "qty": str(request.qty),
        "deadline_day": str(request.deadline),
    }
    mutations = [Mutation(type="rush_order", params=rush_params)]
    result = simulate(state.engine_data, old_score, mutations, config=state.config, mode="normal")
    physical_violations = _physical_violations(result.score)
    plan_violations = _plan_violations(result.score)
    if plan_violations:
        return {
            "status": "invalid",
            "score": result.score,
            "score_previous": old_score,
            "summary": result.summary,
            "hard_gate_violations": physical_violations,
            "plan_violations": plan_violations,
            "n_segments_before": old_n,
            "n_segments_after": len(result.segments),
            "time_ms": result.time_ms,
            "can_revert": bool(state.simulation_snapshot or state.config_snapshot),
        }

    schedule_result = ScheduleResult(
        segments=result.segments,
        lots=result.lots,
        score=result.score,
        time_ms=result.time_ms,
        warnings=[],
        operator_alerts=[],
        audit_trail=None,
        journal=None,
    )
    state.save_current(kind="simulation")
    state.update_schedule(schedule_result)

    # Persist mutation so a later recompute (e.g. preset) keeps it applied
    state.active_mutations = [{"type": "rush_order", "params": rush_params}]
    state.active_simulation_summary = list(result.summary)

    return {
        "status": "applied",
        "score": result.score,
        "score_previous": old_score,
        "summary": result.summary,
        "hard_gate_violations": {},
        "plan_violations": {},
        "n_segments_before": old_n,
        "n_segments_after": len(result.segments),
        "time_ms": result.time_ms,
        "can_revert": True,
    }


@router.post("/recalculate")
async def recalculate():
    _require_data()

    old_score = dict(state.score) if state.score else {}
    recompute = _recompute(state.config)
    if recompute.get("status") == "invalid":
        return {
            "status": "invalid",
            "score": state.score,
            "score_candidate": recompute.get("score"),
            "score_previous": old_score,
            "summary": recompute.get("summary", []),
            "hard_gate_violations": recompute.get("hard_gate_violations", {}),
            "plan_violations": recompute.get("plan_violations", {}),
            "n_segments": len(state.segments),
            "warnings": state.warnings[:10],
        }

    return {
        "status": "ok",
        "score": state.score,
        "score_previous": old_score,
        "time_ms": state.score.get("time_ms", 0) if state.score else 0,
        "n_segments": len(state.segments),
        "warnings": state.warnings[:10],
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
        state.default_config = copy.deepcopy(config)
        state.active_mutations = []
        state.active_simulation_summary = []
        state.clear_revert()
        with open(master_path) as f:
            master = yaml.safe_load(f)

        rows, workdays, has_twin = read_isop(tmp_path)
        engine_data = transform(rows, workdays, has_twin, master)
        result = optimize(
            engine_data,
            mode="normal",
            audit=True,
            config=config,
        )

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
                "warnings": len([
                    e for e in result.journal
                    if e.get("severity") in ("warn", "error")
                ]),
            }

        learning_info = {
            "optimized": True,
            "mode": "normal",
            "time_ms": result.time_ms,
        }
        state.learning_info = learning_info

        return {
            "status": "ok",
            "n_ops": len(engine_data.ops),
            "n_segments": len(result.segments),
            "score": result.score,
            "time_ms": result.time_ms,
            "trust_index": {"score": trust.score, "gate": trust.gate},
            "journal_summary": journal_summary,
            "learning": learning_info,
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
    pending: list[tuple[tuple[str, str], int, str]] = []
    for key, count in body.items():
        if key in state.config.operators:
            pending.append((key, int(count), key))
        else:
            # Try tuple key format: "Grandes A" → ("Grandes", "A")
            parts = key.split()
            if len(parts) == 2:
                tkey = (parts[0], parts[1])
                if tkey in state.config.operators:
                    pending.append((tkey, int(count), key))

    for tkey, count, label in pending:
        if state.config.operators[tkey] != count:
            changed.append(label)

    if not changed:
        return {"status": "ok", "score": state.score, "score_anterior": old_score}

    candidate = copy.deepcopy(state.config)
    for tkey, count, _label in pending:
        candidate.operators[tkey] = count

    candidate_result, candidate_summary = _compute_schedule_for_config(candidate)
    validation = _validate_candidate_result(candidate_result, candidate_summary)
    if validation["status"] == "invalid":
        return {
            "status": "invalid",
            "changed": changed,
            "score": state.score,
            "score_candidate": candidate_result.score,
            "score_anterior": old_score,
            "summary": validation["summary"],
            "hard_gate_violations": validation["hard_gate_violations"],
            "plan_violations": validation["plan_violations"],
        }

    state.save_current(kind="config")
    state.config = candidate
    save_config(state.config)
    _commit_recompute(candidate_result, candidate_summary)

    return {"status": "ok", "changed": changed, "score": state.score, "score_anterior": old_score}


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

    # Start from current config and reset only preset-owned fields to defaults.
    base = state.default_config if state.default_config is not None else None
    new_config = apply_preset(state.config, name, base_config=base)

    old_score = dict(state.score) if state.score else {}
    candidate_result = None
    candidate_summary: list[str] = []
    if state.engine_data is not None:
        candidate_result, candidate_summary = _compute_schedule_for_config(new_config)
        validation = _validate_candidate_result(candidate_result, candidate_summary)
        if validation["status"] == "invalid":
            return {
                "status": "invalid",
                "preset": name,
                "changed": list(get_preset(name).keys()),
                "score": state.score,
                "score_candidate": candidate_result.score,
                "score_previous": old_score,
                "summary": validation["summary"],
                "hard_gate_violations": validation["hard_gate_violations"],
                "plan_violations": validation["plan_violations"],
                "simulation_active": bool(state.active_mutations),
            }

    state.save_current(kind="config")
    state.config = new_config
    save_config(new_config)

    if candidate_result is not None:
        _commit_recompute(candidate_result, candidate_summary)

    return {
        "status": "ok",
        "preset": name,
        "changed": list(get_preset(name).keys()),
        "score": state.score,
        "score_previous": old_score,
        "simulation_active": bool(state.active_mutations),
    }
