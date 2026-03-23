"""Pipeline API — POST /v1/pipeline/run

Unified endpoint: ISOP XLSX upload → parse → transform → CP-SAT solve → response.
One call replaces the entire frontend scheduling pipeline.
CP-SAT is the ONLY solver — no heuristic fallback.
"""

from __future__ import annotations

import io
import time
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from ...core.logging import get_logger
from ...domain.guardian import InputValidator, Journal, JournalStep, OutputGuardian
from ...domain.nikufra.isop_parser import parse_isop_file
from ...domain.nikufra.utils import nikufra_to_plan_state as _nikufra_to_plan_state
from ...domain.scheduling.transform import transform_plan_state
from .pipeline_helpers import (
    FullScheduleResponse,
    PipelineResponse,
    cache_get,
    cache_key,
    cache_set,
    compute_kpis,
    populate_copilot_isop,
    populate_copilot_state,
    run_analytics,
    run_cpsat,
    run_greedy,
    set_last_schedule,
)

logger = get_logger(__name__)

pipeline_router = APIRouter(prefix="/pipeline", tags=["pipeline"])


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

    populate_copilot_isop(nikufra_data)
    plan_state = _nikufra_to_plan_state(nikufra_data)

    try:
        engine_data = transform_plan_state(
            plan_state,
            demand_semantics=demand_semantics,
            order_based=order_based,
        )
    except Exception as e:
        logger.error("pipeline.schedule.transform.error", error=str(e))
        return PipelineResponse(
            nikufra_data=nikufra_data,
            parse_warnings=[f"Erro na transformação: {e}"],
        )

    solver_pref = settings_dict.get("solver", "greedy")
    run_solver = run_greedy if solver_pref == "greedy" else run_cpsat

    try:
        solve_result = run_solver(engine_data, settings_dict)
    except Exception as e:
        logger.error("pipeline.schedule.error", error=str(e))
        return PipelineResponse(
            nikufra_data=nikufra_data,
            parse_warnings=[f"Erro no scheduling: {e}"],
        )

    total_elapsed = time.perf_counter() - t0
    blocks = solve_result["blocks"]
    decisions = solve_result["decisions"]
    feasibility = solve_result["feasibility_report"]
    solver_used = solve_result["solver_used"]
    kpis = compute_kpis(blocks, len(engine_data.ops))

    # Store last schedule for stock projection / CTP endpoints
    set_last_schedule(engine_data, blocks)

    populate_copilot_state(
        blocks,
        decisions,
        feasibility,
        kpis,
        engine_data,
        solver_used,
        total_elapsed,
        nikufra_data=nikufra_data,
    )

    logger.info(
        "pipeline.schedule.done",
        n_blocks=len(blocks),
        n_ops=len(engine_data.ops),
        solver=solver_used,
        total_s=round(total_elapsed, 3),
    )

    return PipelineResponse(
        blocks=blocks,
        kpis=kpis,
        decisions=decisions,
        feasibility_report=feasibility,
        solve_time_s=round(total_elapsed, 3),
        solver_used=solver_used,
        n_blocks=len(blocks),
        n_ops=len(engine_data.ops),
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

    populate_copilot_isop(nikufra_data)

    # Transform
    plan_state = _nikufra_to_plan_state(nikufra_data)
    t_transform = time.perf_counter()

    try:
        engine_data = transform_plan_state(
            plan_state,
            demand_semantics=demand_semantics,
            order_based=order_based,
        )
    except Exception as e:
        logger.error("pipeline.transform.error", error=str(e))
        return PipelineResponse(
            nikufra_data=nikufra_data,
            parse_meta=parse_meta,
            parse_warnings=warnings + [f"Erro na transformação: {e}"],
        )

    transform_elapsed = time.perf_counter() - t_transform
    warnings.append(
        f"Transform: {len(engine_data.ops)} ops, {engine_data.n_days} days "
        f"in {transform_elapsed:.3f}s."
    )

    # Solve (greedy default, CP-SAT fallback)
    t_schedule = time.perf_counter()
    solver_pref = settings_dict.get("solver", "greedy")
    run_solver = run_greedy if solver_pref == "greedy" else run_cpsat

    try:
        solve_result = run_solver(engine_data, settings_dict)
    except Exception as e:
        logger.error("pipeline.schedule.error", error=str(e))
        return PipelineResponse(
            nikufra_data=nikufra_data,
            parse_meta=parse_meta,
            parse_warnings=warnings + [f"Erro no scheduling: {e}"],
        )

    schedule_elapsed = time.perf_counter() - t_schedule
    total_elapsed = time.perf_counter() - t0

    blocks = solve_result["blocks"]
    decisions = solve_result["decisions"]
    feasibility = solve_result["feasibility_report"]
    solver_used = solve_result["solver_used"]
    kpis = compute_kpis(blocks, len(engine_data.ops))

    warnings.append(
        f"{solver_used}: {len(blocks)} blocks in {schedule_elapsed:.3f}s ({solve_result['status']}). "
        f"Total pipeline: {total_elapsed:.3f}s."
    )

    populate_copilot_state(
        blocks,
        decisions,
        feasibility,
        kpis,
        engine_data,
        solver_used,
        total_elapsed,
        nikufra_data=nikufra_data,
    )

    logger.info(
        "pipeline.run.done",
        n_blocks=len(blocks),
        n_ops=len(engine_data.ops),
        solver=solver_used,
        otd_pct=kpis.otd_pct,
        total_s=round(total_elapsed, 3),
    )

    return PipelineResponse(
        blocks=blocks,
        kpis=kpis,
        decisions=decisions,
        feasibility_report=feasibility,
        solve_time_s=round(total_elapsed, 3),
        solver_used=solver_used,
        n_blocks=len(blocks),
        n_ops=len(engine_data.ops),
        parse_meta=parse_meta,
        parse_warnings=warnings,
        nikufra_data=nikufra_data,
    )


# ── Full schedule endpoint ────────────────────────────────────


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
    ck = cache_key(nikufra_data, settings_dict)
    cached = cache_get(ck)
    if cached is not None:
        logger.info("schedule.full.cache_hit", key=ck)
        return FullScheduleResponse(**cached)

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

    populate_copilot_isop(nikufra_data)
    plan_state = _nikufra_to_plan_state(nikufra_data)

    journal.step(JournalStep.TRANSFORM, "Transforming plan state")

    try:
        engine_data = transform_plan_state(
            plan_state,
            demand_semantics=demand_semantics,
            order_based=order_based,
        )
    except Exception as e:
        logger.error("schedule.full.transform.error", error=str(e))
        journal.error(JournalStep.TRANSFORM, f"Transform failed: {e}")
        return FullScheduleResponse(
            nikufra_data=nikufra_data,
            parse_warnings=[f"Erro na transformação: {e}"],
            journal_summary=journal.summary(),
        )

    journal.info(
        JournalStep.TRANSFORM, f"Transformed {len(engine_data.ops)} ops, {engine_data.n_days} days"
    )
    solver_pref = settings_dict.get("solver", "greedy")
    run_solver = run_greedy if solver_pref == "greedy" else run_cpsat
    journal.step(JournalStep.SOLVE, f"Running {solver_pref} solver")

    try:
        solve_result = run_solver(engine_data, settings_dict)
    except Exception as e:
        logger.error("schedule.full.schedule.error", error=str(e))
        journal.error(JournalStep.SOLVE, f"Solver failed: {e}")
        return FullScheduleResponse(
            nikufra_data=nikufra_data,
            parse_warnings=[f"Erro no scheduling: {e}"],
            journal_summary=journal.summary(),
        )

    blocks = solve_result["blocks"]
    decisions = solve_result["decisions"]
    feasibility = solve_result["feasibility_report"]
    solver_used = solve_result["solver_used"]

    journal.info(
        JournalStep.SOLVE,
        f"{solver_used}: {len(blocks)} blocks",
        metadata={"solve_time_s": solve_result.get("solve_time_s", 0)},
    )

    # ── Guardian: Output Validation ──
    workdays = getattr(engine_data, "workdays", None)
    output_violations = output_guardian.validate(blocks, workdays=workdays)
    if output_violations:
        for v in output_violations[:5]:
            warnings.append(f"Output: {v.violation_type} — {v.detail}")

    kpis = compute_kpis(blocks, len(engine_data.ops))

    # Store last schedule for stock projection / CTP endpoints
    set_last_schedule(engine_data, blocks)

    # Run all analytics
    journal.step(JournalStep.ANALYTICS, "Running analytics")
    analytics = run_analytics(blocks, engine_data)
    journal.info(JournalStep.ANALYTICS, f"Computed {len(analytics)} analytics")

    total_elapsed = time.perf_counter() - t0

    populate_copilot_state(
        blocks,
        decisions,
        feasibility,
        kpis,
        engine_data,
        solver_used,
        total_elapsed,
        nikufra_data=nikufra_data,
    )

    logger.info(
        "schedule.full.done",
        n_blocks=len(blocks),
        n_ops=len(engine_data.ops),
        solver=solver_used,
        total_s=round(total_elapsed, 3),
        analytics_keys=list(analytics.keys()),
    )

    # Serialize engine_data with camelCase aliases for frontend consumption
    engine_data_dict = engine_data.model_dump(by_alias=True)

    # Cache store
    response_dict = dict(
        blocks=blocks,
        kpis=kpis,
        decisions=decisions,
        feasibility_report=feasibility,
        solve_time_s=round(total_elapsed, 3),
        solver_used=solver_used,
        n_blocks=len(blocks),
        n_ops=len(engine_data.ops),
        parse_warnings=warnings,
        nikufra_data=nikufra_data,
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
    cache_set(ck, response_dict)

    return FullScheduleResponse(**response_dict)
