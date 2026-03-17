"""Pipeline API — POST /v1/pipeline/run

Unified endpoint: ISOP XLSX upload → parse → transform → schedule → response.
One call replaces the entire frontend scheduling pipeline.
"""

from __future__ import annotations

import io
import time
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from ...core.logging import get_logger
from ...domain.copilot.state import copilot_state
from ...domain.nikufra.isop_parser import parse_isop_file
from ...domain.scheduling.overflow.auto_route_overflow import auto_route_overflow
from ...domain.scheduling.transform import transform_plan_state
from ...domain.scheduling.types import Block, DecisionEntry, FeasibilityReport

logger = get_logger(__name__)

pipeline_router = APIRouter(prefix="/pipeline", tags=["pipeline"])


# ── Response models ──────────────────────────────────────────────


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
    solver_used: str = "atcs_python"
    n_blocks: int = 0
    n_ops: int = 0
    # Parser metadata
    parse_meta: dict | None = None
    parse_warnings: list[str] = Field(default_factory=list)
    # NikufraData for frontend state
    nikufra_data: dict | None = None

    model_config = {"arbitrary_types_allowed": True}


# ── KPI computation ──────────────────────────────────────────────


def _compute_kpis(blocks: list[Block], n_ops: int) -> PipelineKPIs:
    prod_blocks = [b for b in blocks if getattr(b, "block_type", None) != "infeasible"]
    infeasible = [b for b in blocks if getattr(b, "block_type", None) == "infeasible"]
    machines_used: set = set()
    total_qty = 0
    total_prod_min = 0
    for b in prod_blocks:
        machines_used.add(getattr(b, "machine_id", ""))
        total_qty += getattr(b, "qty", 0)
        total_prod_min += getattr(b, "production_minutes", 0)

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


# ── NikufraData → PlanState-like dict for transform ─────────────


def _nikufra_to_plan_state(nikufra_data: dict[str, Any]) -> dict[str, Any]:
    """Convert parsed NikufraData into the dict format transform_plan_state expects."""
    operations = nikufra_data.get("operations", [])
    tools = nikufra_data.get("tools", [])

    # Build tool lookup for setup/alt enrichment
    tool_lookup: dict[str, dict[str, Any]] = {}
    for t in tools:
        tool_lookup[t["id"]] = t

    # Enrich operations with tool-level fields for transform
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


# ── Populate copilot ISOP data ──────────────────────────────────


def _populate_copilot_isop(nikufra_data: dict[str, Any]) -> None:
    """Populate copilot_state.isop_data from parsed NikufraData."""
    operations = nikufra_data.get("operations", [])
    skus: dict[str, Any] = {}
    for op in operations:
        sku = op.get("sku", "")
        if not sku:
            continue
        # Collect demand days as orders
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


# ── Main endpoint ────────────────────────────────────────────────


class PipelineScheduleRequest(BaseModel):
    """JSON-based pipeline request — accepts pre-parsed NikufraData."""

    nikufra_data: dict[str, Any]
    settings: dict[str, Any] = Field(default_factory=dict)


@pipeline_router.post("/schedule", response_model=PipelineResponse)
async def schedule_from_data(request: PipelineScheduleRequest) -> PipelineResponse:
    """Schedule from pre-parsed NikufraData JSON (no file upload needed).

    Frontend sends its already-parsed NikufraData + settings.
    Backend does: transform → schedule → return everything.
    """
    t0 = time.perf_counter()
    nikufra_data = request.nikufra_data
    settings_dict = request.settings

    rule = settings_dict.get("dispatchRule", "EDD")
    third_shift = settings_dict.get("thirdShift", False)
    max_tier = settings_dict.get("maxTier", 4)
    order_based = settings_dict.get("orderBased", True)
    demand_semantics = settings_dict.get("demandSemantics", "raw_np")

    warnings: list[str] = []

    # Populate copilot ISOP data
    _populate_copilot_isop(nikufra_data)

    # Transform NikufraData → EngineData
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

    # Schedule
    try:
        result = auto_route_overflow(
            ops=engine_data.ops,
            m_st=engine_data.m_st,
            t_st=engine_data.t_st,
            user_moves=[],
            machines=engine_data.machines,
            tool_map=engine_data.tool_map,
            workdays=engine_data.workdays,
            n_days=engine_data.n_days,
            workforce_config=engine_data.workforce_config,
            rule=rule,
            third_shift=third_shift or engine_data.third_shift,
            twin_validation_report=engine_data.twin_validation_report,
            order_based=engine_data.order_based,
            max_tier=max_tier,
        )
    except Exception as e:
        logger.error("pipeline.schedule.error", error=str(e))
        return PipelineResponse(
            nikufra_data=nikufra_data,
            parse_warnings=[f"Erro no scheduling: {e}"],
        )

    total_elapsed = time.perf_counter() - t0
    blocks = result.get("blocks", [])
    decisions = result.get("decisions", [])
    feasibility = result.get("feasibility_report")
    auto_moves = result.get("auto_moves", [])
    auto_advances = result.get("auto_advances", [])

    moves_dicts = [m.dict() if hasattr(m, "dict") else m for m in auto_moves]
    advances_dicts = [a.dict() if hasattr(a, "dict") else a for a in auto_advances]
    kpis = _compute_kpis(blocks, len(engine_data.ops))

    # Populate copilot state
    copilot_state.update_from_schedule_result(
        {
            "blocks": blocks,
            "decisions": decisions,
            "feasibility_report": feasibility,
            "auto_moves": auto_moves,
            "kpis": kpis.model_dump() if hasattr(kpis, "model_dump") else kpis.dict(),
            "engine_data": (
                engine_data.model_dump()
                if hasattr(engine_data, "model_dump")
                else engine_data.dict()
            ),
            "solver_used": "atcs_python",
            "solve_time_s": round(total_elapsed, 3),
        }
    )

    logger.info(
        "pipeline.schedule.done",
        n_blocks=len(blocks),
        n_ops=len(engine_data.ops),
        total_s=round(total_elapsed, 3),
    )

    return PipelineResponse(
        blocks=blocks,
        kpis=kpis,
        decisions=decisions,
        feasibility_report=feasibility,
        auto_moves=moves_dicts,
        auto_advances=advances_dicts,
        solve_time_s=round(total_elapsed, 3),
        solver_used="atcs_python",
        n_blocks=len(blocks),
        n_ops=len(engine_data.ops),
        parse_warnings=warnings,
        nikufra_data=nikufra_data,
    )


@pipeline_router.post("/run", response_model=PipelineResponse)
async def run_pipeline(
    isop_file: UploadFile = File(..., description="ISOP XLSX file"),
    settings: str = Form(default="{}", description="JSON settings string"),
) -> PipelineResponse:
    """Unified pipeline: ISOP XLSX → parse → transform → schedule → response.

    Accepts:
        - isop_file: ISOP XLSX upload
        - settings: JSON string with scheduling settings (rule, third_shift, etc.)

    Returns full PipelineResponse with blocks, KPIs, decisions, and NikufraData.
    """
    import json

    t0 = time.perf_counter()

    # ── 1. Parse settings ──
    try:
        settings_dict = json.loads(settings) if settings else {}
    except json.JSONDecodeError:
        settings_dict = {}

    rule = settings_dict.get("dispatchRule", "EDD")
    third_shift = settings_dict.get("thirdShift", False)
    max_tier = settings_dict.get("maxTier", 4)
    order_based = settings_dict.get("orderBased", True)
    demand_semantics = settings_dict.get("demandSemantics", "raw_np")

    # ── 2. Read XLSX bytes ──
    xlsx_bytes = await isop_file.read()
    if not xlsx_bytes:
        return PipelineResponse(
            parse_warnings=["Ficheiro ISOP vazio."],
        )

    # ── 3. Parse ISOP → NikufraData ──
    t_parse = time.perf_counter()
    parse_result = parse_isop_file(io.BytesIO(xlsx_bytes))
    parse_elapsed = time.perf_counter() - t_parse

    if not parse_result.success:
        return PipelineResponse(
            parse_warnings=parse_result.errors,
        )

    nikufra_data = parse_result.data
    parse_meta = parse_result.meta
    warnings = parse_meta.get("warnings", []) if parse_meta else []
    warnings.append(f"ISOP parsed in {parse_elapsed:.3f}s.")

    logger.info(
        "pipeline.parse.done",
        rows=parse_meta.get("rows", 0) if parse_meta else 0,
        skus=parse_meta.get("skus", 0) if parse_meta else 0,
        dates=parse_meta.get("dates", 0) if parse_meta else 0,
        elapsed_s=round(parse_elapsed, 3),
    )

    # ── 4. Populate copilot ISOP data ──
    _populate_copilot_isop(nikufra_data)

    # ── 5. Transform NikufraData → EngineData ──
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

    # ── 6. Schedule (auto_route_overflow) ──
    t_schedule = time.perf_counter()

    try:
        result = auto_route_overflow(
            ops=engine_data.ops,
            m_st=engine_data.m_st,
            t_st=engine_data.t_st,
            user_moves=[],
            machines=engine_data.machines,
            tool_map=engine_data.tool_map,
            workdays=engine_data.workdays,
            n_days=engine_data.n_days,
            workforce_config=engine_data.workforce_config,
            rule=rule,
            third_shift=third_shift or engine_data.third_shift,
            twin_validation_report=engine_data.twin_validation_report,
            order_based=engine_data.order_based,
            max_tier=max_tier,
        )
    except Exception as e:
        logger.error("pipeline.schedule.error", error=str(e))
        return PipelineResponse(
            nikufra_data=nikufra_data,
            parse_meta=parse_meta,
            parse_warnings=warnings + [f"Erro no scheduling: {e}"],
        )

    schedule_elapsed = time.perf_counter() - t_schedule
    total_elapsed = time.perf_counter() - t0

    blocks = result.get("blocks", [])
    decisions = result.get("decisions", [])
    feasibility = result.get("feasibility_report")
    auto_moves = result.get("auto_moves", [])
    auto_advances = result.get("auto_advances", [])

    moves_dicts = [m.dict() if hasattr(m, "dict") else m for m in auto_moves]
    advances_dicts = [a.dict() if hasattr(a, "dict") else a for a in auto_advances]

    kpis = _compute_kpis(blocks, len(engine_data.ops))

    warnings.append(
        f"Schedule: {len(blocks)} blocks in {schedule_elapsed:.3f}s. "
        f"Total pipeline: {total_elapsed:.3f}s."
    )

    # ── 7. Populate copilot state ──
    copilot_state.update_from_schedule_result(
        {
            "blocks": blocks,
            "decisions": decisions,
            "feasibility_report": feasibility,
            "auto_moves": auto_moves,
            "kpis": kpis.model_dump() if hasattr(kpis, "model_dump") else kpis.dict(),
            "engine_data": (
                engine_data.model_dump()
                if hasattr(engine_data, "model_dump")
                else engine_data.dict()
            ),
            "solver_used": "atcs_python",
            "solve_time_s": round(total_elapsed, 3),
        }
    )

    logger.info(
        "pipeline.run.done",
        n_blocks=len(blocks),
        n_ops=len(engine_data.ops),
        otd_pct=kpis.otd_pct,
        total_s=round(total_elapsed, 3),
    )

    return PipelineResponse(
        blocks=blocks,
        kpis=kpis,
        decisions=decisions,
        feasibility_report=feasibility,
        auto_moves=moves_dicts,
        auto_advances=advances_dicts,
        solve_time_s=round(total_elapsed, 3),
        solver_used="atcs_python",
        n_blocks=len(blocks),
        n_ops=len(engine_data.ops),
        parse_meta=parse_meta,
        parse_warnings=warnings,
        nikufra_data=nikufra_data,
    )
