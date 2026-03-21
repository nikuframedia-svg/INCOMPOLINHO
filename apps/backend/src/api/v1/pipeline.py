"""Pipeline API — POST /v1/pipeline/run

Unified endpoint: ISOP XLSX upload → parse → transform → CP-SAT solve → response.
One call replaces the entire frontend scheduling pipeline.
CP-SAT is the ONLY solver — no heuristic fallback.
"""

from __future__ import annotations

import hashlib
import io
import json as _json
import time
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from ...core.logging import get_logger
from ...domain.copilot.state import copilot_state
from ...domain.guardian import InputValidator, Journal, JournalStep, OutputGuardian
from ...domain.nikufra.isop_parser import parse_isop_file
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
from ...domain.scheduling.overflow.overflow_helpers import cap_analysis
from ...domain.scheduling.transform import transform_plan_state
from ...domain.scheduling.types import Block, DecisionEntry, FeasibilityReport
from ...domain.solver.bridge import engine_data_to_solver_request, solver_result_to_blocks
from ...domain.solver.post_solve import build_decisions, build_feasibility_report
from ...domain.solver.router_logic import SolverRouter

logger = get_logger(__name__)

# ── Shared solver instance ────────────────────────────────────
_solver_router = SolverRouter()

# ── In-memory cache (PERF-01) ─────────────────────────────────
_schedule_cache: dict[str, dict[str, Any]] = {}
_CACHE_MAX_SIZE = 5


def _cache_key(nikufra_data: dict, settings: dict) -> str:
    raw = _json.dumps(nikufra_data, sort_keys=True, default=str) + _json.dumps(
        settings, sort_keys=True, default=str
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


pipeline_router = APIRouter(prefix="/pipeline", tags=["pipeline"])


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

# ── Shared helpers ────────────────────────────────────────────


def _compute_kpis(blocks: list[Block], n_ops: int) -> PipelineKPIs:
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


def _nikufra_to_plan_state(nikufra_data: dict[str, Any]) -> dict[str, Any]:
    """Convert parsed NikufraData into the dict format transform_plan_state expects."""
    operations = nikufra_data.get("operations", [])
    tools = nikufra_data.get("tools", [])

    tool_lookup: dict[str, dict[str, Any]] = {}
    for t in tools:
        tool_lookup[t["id"]] = t

    enriched_ops: list[dict[str, Any]] = []
    for op in operations:
        tool_info = tool_lookup.get(op.get("t", ""), {})
        enriched: dict[str, Any] = {
            "id": op.get("id", ""),
            "m": op.get("m", ""),
            "t": op.get("t", ""),
            "sku": op.get("sku", ""),
            "nm": op.get("nm", ""),
            "pH": op.get("pH", 100),
            "atr": op.get("atr", 0),
            "d": op.get("d", []),
            "op": op.get("op", 1),
            "sH": op.get("s", tool_info.get("s", 0.75)),
            "alt": tool_info.get("alt", "-"),
            "eco": tool_info.get("lt", 0),
            "twin": op.get("twin"),
            "cl": op.get("cl"),
            "clNm": op.get("clNm"),
            "pa": op.get("pa"),
            "ltDays": op.get("ltDays"),
        }
        enriched_ops.append(enriched)

    return {
        "operations": enriched_ops,
        "dates": nikufra_data.get("dates", []),
        "dnames": nikufra_data.get("days_label", []),
    }


def _populate_copilot_isop(nikufra_data: dict[str, Any]) -> None:
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


def _run_cpsat(engine_data: Any, settings_dict: dict) -> dict[str, Any]:
    """Run CP-SAT solver on engine data. Returns blocks, decisions, feasibility, solve_time."""
    solver_request = engine_data_to_solver_request(engine_data, settings_dict)
    solver_result = _solver_router.solve(solver_request)
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


def _populate_copilot_state(
    blocks: list, decisions: list, feasibility: Any,
    kpis: Any, engine_data: Any, solver_used: str, solve_time: float,
) -> None:
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


# ── Endpoints ─────────────────────────────────────────────────


class PipelineScheduleRequest(BaseModel):
    """JSON-based pipeline request — accepts pre-parsed NikufraData."""

    nikufra_data: dict[str, Any]
    settings: dict[str, Any] = Field(default_factory=dict)


@pipeline_router.post("/schedule", response_model=PipelineResponse)
async def schedule_from_data(request: PipelineScheduleRequest) -> PipelineResponse:
    """Schedule from pre-parsed NikufraData JSON (no file upload needed).

    Frontend sends its already-parsed NikufraData + settings.
    Backend does: transform → CP-SAT solve → return everything.
    """
    t0 = time.perf_counter()
    nikufra_data = request.nikufra_data
    settings_dict = request.settings
    order_based = settings_dict.get("orderBased", True)
    demand_semantics = settings_dict.get("demandSemantics", "raw_np")

    _populate_copilot_isop(nikufra_data)
    plan_state = _nikufra_to_plan_state(nikufra_data)

    try:
        engine_data = transform_plan_state(
            plan_state, demand_semantics=demand_semantics, order_based=order_based,
        )
    except Exception as e:
        logger.error("pipeline.schedule.transform.error", error=str(e))
        return PipelineResponse(
            nikufra_data=nikufra_data,
            parse_warnings=[f"Erro na transformação: {e}"],
        )

    try:
        cpsat_result = _run_cpsat(engine_data, settings_dict)
    except Exception as e:
        logger.error("pipeline.schedule.error", error=str(e))
        return PipelineResponse(
            nikufra_data=nikufra_data,
            parse_warnings=[f"Erro no scheduling: {e}"],
        )

    total_elapsed = time.perf_counter() - t0
    blocks = cpsat_result["blocks"]
    decisions = cpsat_result["decisions"]
    feasibility = cpsat_result["feasibility_report"]
    solver_used = cpsat_result["solver_used"]
    kpis = _compute_kpis(blocks, len(engine_data.ops))

    _populate_copilot_state(blocks, decisions, feasibility, kpis, engine_data, solver_used, total_elapsed)

    logger.info(
        "pipeline.schedule.done",
        n_blocks=len(blocks), n_ops=len(engine_data.ops),
        solver=solver_used, total_s=round(total_elapsed, 3),
    )

    return PipelineResponse(
        blocks=blocks, kpis=kpis, decisions=decisions,
        feasibility_report=feasibility,
        solve_time_s=round(total_elapsed, 3),
        solver_used=solver_used,
        n_blocks=len(blocks), n_ops=len(engine_data.ops),
        nikufra_data=nikufra_data,
    )


@pipeline_router.post("/run", response_model=PipelineResponse)
async def run_pipeline(
    isop_file: UploadFile = File(..., description="ISOP XLSX file"),
    settings: str = Form(default="{}", description="JSON settings string"),
) -> PipelineResponse:
    """Unified pipeline: ISOP XLSX → parse → transform → CP-SAT solve → response."""
    import json

    t0 = time.perf_counter()

    try:
        settings_dict = json.loads(settings) if settings else {}
    except json.JSONDecodeError:
        settings_dict = {}

    order_based = settings_dict.get("orderBased", True)
    demand_semantics = settings_dict.get("demandSemantics", "raw_np")

    xlsx_bytes = await isop_file.read()
    if not xlsx_bytes:
        return PipelineResponse(parse_warnings=["Ficheiro ISOP vazio."])

    # Parse ISOP
    t_parse = time.perf_counter()
    parse_result = parse_isop_file(io.BytesIO(xlsx_bytes))
    parse_elapsed = time.perf_counter() - t_parse

    if not parse_result.success:
        return PipelineResponse(parse_warnings=parse_result.errors)

    nikufra_data = parse_result.data
    parse_meta = parse_result.meta
    warnings = parse_meta.get("warnings", []) if parse_meta else []
    warnings.append(f"ISOP parsed in {parse_elapsed:.3f}s.")

    logger.info(
        "pipeline.parse.done",
        rows=parse_meta.get("rows", 0) if parse_meta else 0,
        skus=parse_meta.get("skus", 0) if parse_meta else 0,
        elapsed_s=round(parse_elapsed, 3),
    )

    _populate_copilot_isop(nikufra_data)

    # Transform
    plan_state = _nikufra_to_plan_state(nikufra_data)
    t_transform = time.perf_counter()

    try:
        engine_data = transform_plan_state(
            plan_state, demand_semantics=demand_semantics, order_based=order_based,
        )
    except Exception as e:
        logger.error("pipeline.transform.error", error=str(e))
        return PipelineResponse(
            nikufra_data=nikufra_data, parse_meta=parse_meta,
            parse_warnings=warnings + [f"Erro na transformação: {e}"],
        )

    transform_elapsed = time.perf_counter() - t_transform
    warnings.append(
        f"Transform: {len(engine_data.ops)} ops, {engine_data.n_days} days "
        f"in {transform_elapsed:.3f}s."
    )

    # CP-SAT Solve
    t_schedule = time.perf_counter()

    try:
        cpsat_result = _run_cpsat(engine_data, settings_dict)
    except Exception as e:
        logger.error("pipeline.schedule.error", error=str(e))
        return PipelineResponse(
            nikufra_data=nikufra_data, parse_meta=parse_meta,
            parse_warnings=warnings + [f"Erro no scheduling: {e}"],
        )

    schedule_elapsed = time.perf_counter() - t_schedule
    total_elapsed = time.perf_counter() - t0

    blocks = cpsat_result["blocks"]
    decisions = cpsat_result["decisions"]
    feasibility = cpsat_result["feasibility_report"]
    solver_used = cpsat_result["solver_used"]
    kpis = _compute_kpis(blocks, len(engine_data.ops))

    warnings.append(
        f"CP-SAT: {len(blocks)} blocks in {schedule_elapsed:.3f}s ({cpsat_result['status']}). "
        f"Total pipeline: {total_elapsed:.3f}s."
    )

    _populate_copilot_state(blocks, decisions, feasibility, kpis, engine_data, solver_used, total_elapsed)

    logger.info(
        "pipeline.run.done",
        n_blocks=len(blocks), n_ops=len(engine_data.ops),
        solver=solver_used, otd_pct=kpis.otd_pct,
        total_s=round(total_elapsed, 3),
    )

    return PipelineResponse(
        blocks=blocks, kpis=kpis, decisions=decisions,
        feasibility_report=feasibility,
        solve_time_s=round(total_elapsed, 3),
        solver_used=solver_used,
        n_blocks=len(blocks), n_ops=len(engine_data.ops),
        parse_meta=parse_meta, parse_warnings=warnings,
        nikufra_data=nikufra_data,
    )


# ── Full schedule endpoint ────────────────────────────────────


def _to_dict(obj: Any) -> Any:
    """Convert dataclass/pydantic to dict for JSON serialization."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(obj)
    return obj


def _run_analytics(
    blocks: list[Block],
    engine_data: Any,
) -> dict[str, Any]:
    """Run all analytics on a schedule result."""
    results: dict[str, Any] = {}

    try:
        results["score"] = _to_dict(score_schedule(
            blocks=blocks, ops=engine_data.ops,
            machines=engine_data.machines, n_days=engine_data.n_days,
        ))
    except Exception as e:
        logger.warning("schedule.full.score.error", error=str(e))

    try:
        results["validation"] = _to_dict(validate_schedule(
            blocks=blocks, machines=engine_data.machines,
            tool_map=engine_data.tool_map, ops=engine_data.ops,
            third_shift=engine_data.third_shift, n_days=engine_data.n_days,
        ))
    except Exception as e:
        logger.warning("schedule.full.validate.error", error=str(e))

    try:
        results["coverage"] = _to_dict(audit_coverage(
            blocks=blocks, ops=engine_data.ops,
            tool_map=engine_data.tool_map, twin_groups=engine_data.twin_groups,
        ))
    except Exception as e:
        logger.warning("schedule.full.coverage.error", error=str(e))

    try:
        results["cap"] = cap_analysis(blocks=blocks, machines=engine_data.machines)
    except Exception as e:
        logger.warning("schedule.full.cap.error", error=str(e))

    mrp_result = None
    try:
        mrp_result = compute_mrp(engine_data)
        results["mrp"] = _to_dict(mrp_result)
    except Exception as e:
        logger.warning("schedule.full.mrp.error", error=str(e))

    try:
        results["late_deliveries"] = _to_dict(analyze_late_deliveries(
            blocks=blocks, ops=engine_data.ops, dates=engine_data.dates,
        ))
    except Exception as e:
        logger.warning("schedule.full.late_deliveries.error", error=str(e))

    if mrp_result is not None:
        try:
            results["mrp_sku_view"] = _to_dict(compute_mrp_sku_view(mrp_result))
        except Exception as e:
            logger.warning("schedule.full.mrp_sku_view.error", error=str(e))

        try:
            results["mrp_rop"] = _to_dict(compute_rop(mrp_result, engine_data))
        except Exception as e:
            logger.warning("schedule.full.mrp_rop.error", error=str(e))

        try:
            results["mrp_rop_sku"] = _to_dict(compute_rop_sku(mrp_result, engine_data))
        except Exception as e:
            logger.warning("schedule.full.mrp_rop_sku.error", error=str(e))

        try:
            results["mrp_actions"] = _to_dict(compute_action_messages(mrp_result, engine_data))
        except Exception as e:
            logger.warning("schedule.full.mrp_actions.error", error=str(e))

        try:
            results["mrp_coverage_sku"] = _to_dict(
                compute_coverage_matrix_sku(mrp_result, engine_data)
            )
        except Exception as e:
            logger.warning("schedule.full.mrp_coverage_sku.error", error=str(e))

        try:
            results["mrp_coverage_matrix"] = _to_dict(
                compute_coverage_matrix(mrp_result, engine_data)
            )
        except Exception as e:
            logger.warning("schedule.full.mrp_coverage_matrix.error", error=str(e))

    try:
        results["quick_validate"] = _to_dict(quick_validate(
            blocks=blocks, machines=engine_data.machines,
            tool_map=engine_data.tool_map,
        ))
    except Exception as e:
        logger.warning("schedule.full.quick_validate.error", error=str(e))

    try:
        decisions_list = gen_decisions(
            ops=engine_data.ops, m_st=engine_data.m_st, t_st=engine_data.t_st,
            moves=[], blocks=blocks, machines=engine_data.machines,
            tool_map=engine_data.tool_map, focus_ids=engine_data.focus_ids,
            tools=engine_data.tools,
        )
        results["gen_decisions"] = [_to_dict(d) for d in decisions_list]
    except Exception as e:
        logger.warning("schedule.full.gen_decisions.error", error=str(e))

    if engine_data.workforce_config is not None:
        try:
            results["workforce_forecast"] = _to_dict(compute_workforce_forecast(
                blocks=blocks, workforce_config=engine_data.workforce_config,
                workdays=engine_data.workdays, dates=engine_data.dates,
                tool_map=engine_data.tool_map, third_shift=engine_data.third_shift,
            ))
        except Exception as e:
            logger.warning("schedule.full.workforce_forecast.error", error=str(e))

    return results


@pipeline_router.post("/schedule/full", response_model=FullScheduleResponse)
async def schedule_full(request: PipelineScheduleRequest) -> FullScheduleResponse:
    """Full schedule: transform → CP-SAT solve → score → validate → coverage → cap → MRP.

    Single endpoint that returns everything the frontend needs.
    No client-side computation required.
    """
    t0 = time.perf_counter()
    nikufra_data = request.nikufra_data
    settings_dict = request.settings

    # Cache check
    ck = _cache_key(nikufra_data, settings_dict)
    if ck in _schedule_cache:
        logger.info("schedule.full.cache_hit", key=ck)
        return FullScheduleResponse(**_schedule_cache[ck])

    # ── Guardian: Journal + Input Validation ──
    journal = Journal()
    input_validator = InputValidator(journal)
    output_guardian = OutputGuardian(journal)

    journal.step(JournalStep.PARSE, "Pipeline started")

    try:
        validated = input_validator.validate(nikufra_data)
    except Exception as e:
        journal.error(JournalStep.VALIDATE_INPUT, f"Input validation failed: {e}")
        return FullScheduleResponse(
            nikufra_data=nikufra_data,
            parse_warnings=[f"Erro na validação: {e}"],
            journal_summary=journal.summary(),
        )

    order_based = settings_dict.get("orderBased", True)
    demand_semantics = settings_dict.get("demandSemantics", "raw_np")
    warnings: list[str] = []

    _populate_copilot_isop(nikufra_data)
    plan_state = _nikufra_to_plan_state(nikufra_data)

    journal.step(JournalStep.TRANSFORM, "Transforming plan state")

    try:
        engine_data = transform_plan_state(
            plan_state, demand_semantics=demand_semantics, order_based=order_based,
        )
    except Exception as e:
        logger.error("schedule.full.transform.error", error=str(e))
        journal.error(JournalStep.TRANSFORM, f"Transform failed: {e}")
        return FullScheduleResponse(
            nikufra_data=nikufra_data,
            parse_warnings=[f"Erro na transformação: {e}"],
            journal_summary=journal.summary(),
        )

    journal.info(JournalStep.TRANSFORM, f"Transformed {len(engine_data.ops)} ops, {engine_data.n_days} days")
    journal.step(JournalStep.SOLVE, "Running CP-SAT solver")

    try:
        cpsat_result = _run_cpsat(engine_data, settings_dict)
    except Exception as e:
        logger.error("schedule.full.schedule.error", error=str(e))
        journal.error(JournalStep.SOLVE, f"Solver failed: {e}")
        return FullScheduleResponse(
            nikufra_data=nikufra_data,
            parse_warnings=[f"Erro no scheduling: {e}"],
            journal_summary=journal.summary(),
        )

    blocks = cpsat_result["blocks"]
    decisions = cpsat_result["decisions"]
    feasibility = cpsat_result["feasibility_report"]
    solver_used = cpsat_result["solver_used"]

    journal.info(JournalStep.SOLVE, f"CP-SAT: {len(blocks)} blocks ({solver_used})",
                 metadata={"solve_time_s": cpsat_result.get("solve_time_s", 0)})

    # ── Guardian: Output Validation ──
    workdays = getattr(engine_data, "workdays", None)
    output_violations = output_guardian.validate(blocks, workdays=workdays)
    if output_violations:
        for v in output_violations[:5]:
            warnings.append(f"Output: {v.violation_type} — {v.detail}")

    kpis = _compute_kpis(blocks, len(engine_data.ops))

    # Run all analytics
    journal.step(JournalStep.ANALYTICS, "Running analytics")
    analytics = _run_analytics(blocks, engine_data)
    journal.info(JournalStep.ANALYTICS, f"Computed {len(analytics)} analytics")

    total_elapsed = time.perf_counter() - t0

    _populate_copilot_state(blocks, decisions, feasibility, kpis, engine_data, solver_used, total_elapsed)

    logger.info(
        "schedule.full.done",
        n_blocks=len(blocks), n_ops=len(engine_data.ops),
        solver=solver_used, total_s=round(total_elapsed, 3),
        analytics_keys=list(analytics.keys()),
    )

    # Serialize engine_data with camelCase aliases for frontend consumption
    engine_data_dict = engine_data.model_dump(by_alias=True)

    # Cache store
    response_dict = dict(
        blocks=blocks, kpis=kpis, decisions=decisions,
        feasibility_report=feasibility,
        solve_time_s=round(total_elapsed, 3),
        solver_used=solver_used,
        n_blocks=len(blocks), n_ops=len(engine_data.ops),
        parse_warnings=warnings, nikufra_data=nikufra_data,
        engine_data=engine_data_dict,
        score=analytics.get("score"),
        validation=analytics.get("validation"),
        coverage=analytics.get("coverage"),
        cap=analytics.get("cap"),
        mrp=analytics.get("mrp"),
        late_deliveries=analytics.get("late_deliveries"),
        mrp_sku_view=analytics.get("mrp_sku_view"),
        mrp_rop=analytics.get("mrp_rop"),
        mrp_rop_sku=analytics.get("mrp_rop_sku"),
        mrp_actions=analytics.get("mrp_actions"),
        mrp_coverage_sku=analytics.get("mrp_coverage_sku"),
        mrp_coverage_matrix=analytics.get("mrp_coverage_matrix"),
        quick_validate=analytics.get("quick_validate"),
        gen_decisions=analytics.get("gen_decisions"),
        workforce_forecast=analytics.get("workforce_forecast"),
        journal_summary=journal.summary(),
    )
    if len(_schedule_cache) >= _CACHE_MAX_SIZE:
        oldest = next(iter(_schedule_cache))
        del _schedule_cache[oldest]
    _schedule_cache[ck] = response_dict

    return FullScheduleResponse(**response_dict)
