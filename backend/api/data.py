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
                    "workday": _is_workday(d.date, d.day_idx),
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
    changed = []
    for key in tunables:
        if key in updates:
            old_val = getattr(c, key)
            new_val = type(old_val)(updates[key])
            setattr(c, key, new_val)
            changed.append(key)

    if not changed:
        return {"status": "ok", "changed": [], "score": state.score}

    from backend.config.loader import save_config
    save_config(c)

    # Recalculate if data is loaded
    if state.engine_data:
        from backend.scheduler.scheduler import schedule_all

        result = schedule_all(state.engine_data, audit=True, config=c)
        state.update_schedule(result)

    return {"status": "ok", "changed": changed, "score": state.score}


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
    result = simulate(state.engine_data, state.score, mutations, config=state.config)

    return {
        "score_baseline": state.score,
        "score_scenario": result.score,
        "delta": asdict(result.delta),
        "time_ms": result.time_ms,
        "summary": result.summary,
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
        "machine": result.machine,
        "confidence": result.confidence,
        "slack_min": result.slack_min,
        "reason": result.reason,
    }


@router.post("/recalculate")
async def recalculate():
    _require_data()
    from backend.scheduler.scheduler import schedule_all

    old_score = dict(state.score) if state.score else {}
    result = schedule_all(state.engine_data, audit=True, config=state.config)
    state.update_schedule(result)

    return {
        "status": "ok",
        "score": result.score,
        "score_previous": old_score,
        "time_ms": result.time_ms,
        "n_segments": len(result.segments),
        "warnings": result.warnings[:10],
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
    from backend.dqa import compute_trust_index
    from backend.learning.smart import smart_schedule
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
        result = smart_schedule(
            engine_data,
            learn=True,
            label=file.filename or "upload",
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

        learning_info = None
        if result.study:
            learning_info = {
                "optimized": True,
                "n_trials": result.study.n_trials,
                "confidence": result.study.confidence,
                "improvement": result.study.improvement,
                "total_time_ms": result.study.total_time_ms,
                "best_params": result.study.best_params.to_dict(),
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
    from backend.scheduler.scheduler import schedule_all

    old_score = dict(state.score) if state.score else {}
    changed = []
    for key, count in body.items():
        if key in state.config.operators:
            state.config.operators[key] = int(count)
            changed.append(key)
        else:
            # Try tuple key format: "Grandes A" → ("Grandes", "A")
            parts = key.split()
            if len(parts) == 2:
                tkey = (parts[0], parts[1])
                if tkey in state.config.operators:
                    state.config.operators[tkey] = int(count)
                    changed.append(key)

    if not changed:
        return {"status": "ok", "score": state.score, "score_anterior": old_score}

    save_config(state.config)
    result = schedule_all(state.engine_data, audit=True, config=state.config)
    state.update_schedule(result)

    return {"status": "ok", "changed": changed, "score": result.score, "score_anterior": old_score}


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
    """Apply a named config preset (urgente, equilibrado, min_setups, max_otd)."""
    _require_config()
    from backend.config.presets import get_preset

    try:
        overrides = get_preset(name)
    except KeyError as e:
        raise HTTPException(400, str(e))

    # Reuse existing update_config logic
    return await update_config(overrides)
