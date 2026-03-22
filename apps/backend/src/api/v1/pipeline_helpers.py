"""Pipeline helpers — cache, KPI computation, copilot state, analytics runners, response models.

Extracted from pipeline.py to keep route handlers lean.
"""

from __future__ import annotations

import hashlib
import json as _json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from pydantic import BaseModel, Field

from ...core.logging import get_logger
from ...domain.copilot.state import copilot_state
from ...domain.scheduling.analysis.cap_analysis import cap_analysis
from ...domain.scheduling.analysis.coverage_audit import audit_coverage
from ...domain.scheduling.analysis.gen_decisions import gen_decisions
from ...domain.scheduling.analysis.late_delivery_analysis import analyze_late_deliveries
from ...domain.scheduling.analysis.quick_validate import quick_validate
from ...domain.scheduling.analysis.score_schedule import score_schedule
from ...domain.scheduling.analysis.validate_schedule import validate_schedule
from ...domain.scheduling.analysis.workforce_forecast import compute_workforce_forecast
from ...domain.scheduling.mrp.mrp_actions import compute_action_messages
from ...domain.scheduling.mrp.mrp_coverage_sku import compute_coverage_matrix_sku
from ...domain.scheduling.mrp.mrp_engine import compute_mrp
from ...domain.scheduling.mrp.mrp_rop import compute_coverage_matrix, compute_rop, compute_rop_sku
from ...domain.scheduling.mrp.mrp_sku_view import compute_mrp_sku_view
from ...domain.scheduling.types import Block, DecisionEntry, FeasibilityReport
from ...domain.solver.bridge import engine_data_to_solver_request, solver_result_to_blocks
from ...domain.solver.post_solve import build_decisions, build_feasibility_report
from ...domain.solver.router_logic import SolverRouter

logger = get_logger(__name__)


# ── Response models ───────────────────────────────────────────


class PipelineKPIs(BaseModel):
    total_blocks: int = 0
    production_blocks: int = 0
    infeasible_blocks: int = 0
    total_qty: int = 0
    total_production_min: int = 0
    otd_pct: float = 100.0
    machines_used: int = 0
    n_ops: int = 0


class PipelineResponse(BaseModel):
    """Full pipeline output — everything the frontend needs."""

    blocks: list[Block] = Field(default_factory=list)
    kpis: PipelineKPIs = Field(default_factory=PipelineKPIs)
    decisions: list[DecisionEntry] = Field(default_factory=list)
    feasibility_report: FeasibilityReport | None = None
    auto_moves: list[dict] = Field(default_factory=list)
    auto_advances: list[dict] = Field(default_factory=list)
    solve_time_s: float = 0.0
    solver_used: str = "cpsat"
    n_blocks: int = 0
    n_ops: int = 0
    parse_meta: dict | None = None
    parse_warnings: list[str] = Field(default_factory=list)
    nikufra_data: dict | None = None

    model_config = {"arbitrary_types_allowed": True}


class FullScheduleResponse(PipelineResponse):
    """Extended response — includes engine_data, score, validation, coverage, cap, MRP + extensions."""

    engine_data: dict | None = None
    score: dict | None = None
    validation: dict | None = None
    coverage: dict | None = None
    cap: dict[str, list] | None = None
    mrp: dict | None = None
    late_deliveries: dict | None = None
    mrp_sku_view: dict | None = None
    mrp_rop: dict | None = None
    mrp_rop_sku: dict | None = None
    mrp_actions: dict | None = None
    mrp_coverage_sku: dict | None = None
    mrp_coverage_matrix: dict | None = None
    quick_validate: dict | None = None
    gen_decisions: list | None = None
    workforce_forecast: dict | None = None
    journal_summary: dict | None = None


# ── Per-request solver factory (thread safety) ───────────────


def _get_solver() -> SolverRouter:
    """Create a fresh SolverRouter per request for thread safety."""
    return SolverRouter()


# ── In-memory cache with TTL + LRU eviction (PERF-01) ────────
_CACHE_MAX_SIZE = 5
_CACHE_TTL_S = 300  # 5 minutes


class _CacheEntry:
    __slots__ = ("data", "ts")

    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.ts = time.monotonic()

    def is_expired(self) -> bool:
        return (time.monotonic() - self.ts) > _CACHE_TTL_S


_schedule_cache: dict[str, _CacheEntry] = {}


def cache_get(key: str) -> dict[str, Any] | None:
    entry = _schedule_cache.get(key)
    if entry is None:
        return None
    if entry.is_expired():
        del _schedule_cache[key]
        return None
    # Move to end for LRU
    _schedule_cache.pop(key)
    _schedule_cache[key] = entry
    return entry.data


def cache_set(key: str, data: dict[str, Any]) -> None:
    # Evict expired entries first
    expired = [k for k, v in _schedule_cache.items() if v.is_expired()]
    for k in expired:
        del _schedule_cache[k]
    # Evict oldest if at capacity
    while len(_schedule_cache) >= _CACHE_MAX_SIZE:
        oldest = next(iter(_schedule_cache))
        del _schedule_cache[oldest]
    _schedule_cache[key] = _CacheEntry(data)


def cache_key(nikufra_data: dict, settings: dict) -> str:
    raw = _json.dumps(nikufra_data, sort_keys=True, default=str) + _json.dumps(
        settings, sort_keys=True, default=str
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


# ── KPI computation ──────────────────────────────────────────


def compute_kpis(blocks: list[Block], n_ops: int) -> PipelineKPIs:
    prod_blocks = [b for b in blocks if getattr(b, "type", "ok") != "infeasible"]
    infeasible = [b for b in blocks if getattr(b, "type", "ok") == "infeasible"]
    machines_used: set[str] = set()
    total_qty = 0
    total_prod_min = 0
    for b in prod_blocks:
        machines_used.add(b.machine_id)
        total_qty += b.qty
        total_prod_min += b.prod_min

    total = len(blocks)
    otd_pct = round((1 - len(infeasible) / max(total, 1)) * 100, 1) if total > 0 else 100.0

    return PipelineKPIs(
        total_blocks=total,
        production_blocks=len(prod_blocks),
        infeasible_blocks=len(infeasible),
        total_qty=total_qty,
        total_production_min=total_prod_min,
        otd_pct=otd_pct,
        machines_used=len(machines_used),
        n_ops=n_ops,
    )


# ── Copilot state helpers ────────────────────────────────────


def populate_copilot_isop(nikufra_data: dict[str, Any]) -> None:
    """Populate copilot_state.isop_data from parsed NikufraData."""
    operations = nikufra_data.get("operations", [])
    skus: dict[str, Any] = {}
    for op in operations:
        sku = op.get("sku", "")
        if not sku:
            continue
        orders = []
        dates = nikufra_data.get("dates", [])
        for i, v in enumerate(op.get("d", [])):
            if v is not None and v < 0:
                orders.append(
                    {
                        "date": dates[i] if i < len(dates) else f"D{i}",
                        "qty": abs(v),
                    }
                )
        skus[sku] = {
            "sku": sku,
            "designation": op.get("nm", sku),
            "machine": op.get("m", ""),
            "tool": op.get("t", ""),
            "pieces_per_hour": op.get("pH", 0),
            "stock": 0,
            "atraso": op.get("atr", 0),
            "twin_ref": op.get("twin"),
            "clients": [op.get("cl")] if op.get("cl") else [],
            "orders": orders,
        }
    copilot_state.isop_data = {"skus": skus}


def populate_copilot_state(
    blocks: list,
    decisions: list,
    feasibility: Any,
    kpis: Any,
    engine_data: Any,
    solver_used: str,
    solve_time: float,
    nikufra_data: dict[str, Any] | None = None,
) -> None:
    if nikufra_data is not None:
        copilot_state.nikufra_data = nikufra_data
    copilot_state.update_from_schedule_result(
        {
            "blocks": blocks,
            "decisions": decisions,
            "feasibility_report": feasibility,
            "auto_moves": [],
            "kpis": kpis.model_dump() if hasattr(kpis, "model_dump") else kpis.dict(),
            "engine_data": (
                engine_data.model_dump()
                if hasattr(engine_data, "model_dump")
                else engine_data.dict()
            ),
            "solver_used": solver_used,
            "solve_time_s": round(solve_time, 3),
        }
    )


# ── CP-SAT runner ────────────────────────────────────────────


def run_cpsat(engine_data: Any, settings_dict: dict) -> dict[str, Any]:
    """Run CP-SAT solver on engine data. Returns blocks, decisions, feasibility, solve_time."""
    solver_request = engine_data_to_solver_request(engine_data, settings_dict)
    solver_result = _get_solver().solve(solver_request)
    blocks = solver_result_to_blocks(solver_result, engine_data)
    feasibility = build_feasibility_report(solver_result, len(engine_data.ops))
    decisions = build_decisions(solver_result)

    return {
        "blocks": blocks,
        "decisions": decisions,
        "feasibility_report": feasibility,
        "solver_used": solver_result.solver_used,
        "solve_time_s": solver_result.solve_time_s,
        "status": solver_result.status,
    }


# ── Serialization helper ─────────────────────────────────────


def to_dict(obj: Any) -> Any:
    """Convert dataclass/pydantic to dict for JSON serialization."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(obj)
    return obj


# ── Analytics runner ─────────────────────────────────────────


def run_analytics(
    blocks: list[Block],
    engine_data: Any,
) -> dict[str, Any]:
    """Run all analytics on a schedule result.

    Uses ThreadPoolExecutor to run independent analytics in parallel.
    Group A: no dependencies — run in parallel.
    Group B: depends on MRP result — run in parallel after MRP completes.
    """
    results: dict[str, Any] = {}

    def _safe(key: str, fn, *args, **kwargs):
        """Run fn, return (key, result) or log warning on failure."""
        try:
            val = fn(*args, **kwargs)
            if key == "gen_decisions":
                return key, [to_dict(d) for d in val]
            return key, to_dict(val) if not isinstance(val, (dict, list)) else val
        except Exception as e:
            logger.warning("schedule.full.%s.error", key, error=str(e))
            return key, None

    # ── Group A: independent analytics (parallel) ──
    group_a_tasks = [
        (
            "score",
            score_schedule,
            [],
            {
                "blocks": blocks,
                "ops": engine_data.ops,
                "machines": engine_data.machines,
                "n_days": engine_data.n_days,
            },
        ),
        (
            "validation",
            validate_schedule,
            [],
            {
                "blocks": blocks,
                "machines": engine_data.machines,
                "tool_map": engine_data.tool_map,
                "ops": engine_data.ops,
                "third_shift": engine_data.third_shift,
                "n_days": engine_data.n_days,
            },
        ),
        (
            "coverage",
            audit_coverage,
            [],
            {
                "blocks": blocks,
                "ops": engine_data.ops,
                "tool_map": engine_data.tool_map,
                "twin_groups": engine_data.twin_groups,
            },
        ),
        (
            "cap",
            cap_analysis,
            [],
            {
                "blocks": blocks,
                "machines": engine_data.machines,
            },
        ),
        (
            "late_deliveries",
            analyze_late_deliveries,
            [],
            {
                "blocks": blocks,
                "ops": engine_data.ops,
                "dates": engine_data.dates,
            },
        ),
        (
            "quick_validate",
            quick_validate,
            [],
            {
                "blocks": blocks,
                "machines": engine_data.machines,
                "tool_map": engine_data.tool_map,
            },
        ),
        (
            "gen_decisions",
            gen_decisions,
            [],
            {
                "ops": engine_data.ops,
                "m_st": engine_data.m_st,
                "t_st": engine_data.t_st,
                "moves": [],
                "blocks": blocks,
                "machines": engine_data.machines,
                "tool_map": engine_data.tool_map,
                "focus_ids": engine_data.focus_ids,
                "tools": engine_data.tools,
            },
        ),
    ]

    if engine_data.workforce_config is not None:
        group_a_tasks.append(
            (
                "workforce_forecast",
                compute_workforce_forecast,
                [],
                {
                    "blocks": blocks,
                    "workforce_config": engine_data.workforce_config,
                    "workdays": engine_data.workdays,
                    "dates": engine_data.dates,
                    "tool_map": engine_data.tool_map,
                    "third_shift": engine_data.third_shift,
                },
            )
        )

    # MRP runs in Group A but we need the result for Group B
    mrp_result = None
    try:
        mrp_result = compute_mrp(engine_data)
        results["mrp"] = to_dict(mrp_result)
    except Exception as e:
        logger.warning("schedule.full.mrp.error", error=str(e))

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(_safe, key, fn, *args, **kwargs): key
            for key, fn, args, kwargs in group_a_tasks
        }
        for future in as_completed(futures):
            key, val = future.result()
            if val is not None:
                results[key] = val

    # ── Group B: depends on MRP result (parallel) ──
    if mrp_result is not None:
        group_b_tasks = [
            ("mrp_sku_view", compute_mrp_sku_view, [mrp_result], {}),
            ("mrp_rop", compute_rop, [mrp_result, engine_data], {}),
            ("mrp_rop_sku", compute_rop_sku, [mrp_result, engine_data], {}),
            ("mrp_actions", compute_action_messages, [mrp_result, engine_data], {}),
            ("mrp_coverage_sku", compute_coverage_matrix_sku, [mrp_result, engine_data], {}),
            ("mrp_coverage_matrix", compute_coverage_matrix, [mrp_result, engine_data], {}),
        ]

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(_safe, key, fn, *args, **kwargs): key
                for key, fn, args, kwargs in group_b_tasks
            }
            for future in as_completed(futures):
                key, val = future.result()
                if val is not None:
                    results[key] = val

    return results
