# Optimal Pipeline — CP-SAT → Recovery → Monte Carlo (OPT-02)
# Unified endpoint that orchestrates the full solver pipeline.

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...domain.copilot.state import copilot_state
from ...domain.solver.montecarlo import monte_carlo_otd
from ...domain.solver.recovery import cascading_recovery
from ...domain.solver.router_logic import SolverRouter
from ...domain.solver.schemas import SolverRequest, SolverResult

logger = logging.getLogger(__name__)

optimal_router = APIRouter(prefix="/optimal", tags=["optimal"])


def _get_solver() -> SolverRouter:
    """Create a fresh SolverRouter per request for thread safety."""
    return SolverRouter()


# ── FINAL-04: Factory rules ──
RULES_PATH = Path(__file__).resolve().parents[3] / "data" / "rules" / "incompol_rules.yaml"


def _load_factory_rules() -> list[dict]:
    """Load factory rules from YAML. Falls back to empty list on error."""
    try:
        if RULES_PATH.exists():
            with open(RULES_PATH) as f:
                data = yaml.safe_load(f)
            return data.get("rules", []) if data else []
    except Exception as e:
        logger.warning("Failed to load factory rules: %s", e)
    return []


def _apply_factory_rules(request: SolverRequest) -> list[dict]:
    """Apply factory rules to solver request. Returns list of rule application decisions."""
    rules = _load_factory_rules()
    # Also include copilot in-memory rules
    if hasattr(copilot_state, "_rules") and copilot_state._rules:
        rules.extend(copilot_state._rules)

    applied: list[dict] = []
    for rule in rules:
        if not rule.get("active", True):
            continue

        if rule.get("type") == "material_affinity":
            target_skus = set(rule.get("skus", []))
            target_machine = rule.get("machine")
            if not target_skus or not target_machine:
                continue

            for job in request.jobs:
                # Check if any SKU part matches (handles "SKU1+SKU2" twin merged names)
                sku_parts = job.sku.split("+")
                if any(s in target_skus for s in sku_parts):
                    old_machine = job.operations[0].machine_id if job.operations else "?"
                    if old_machine != target_machine:
                        for op in job.operations:
                            op.machine_id = target_machine
                        applied.append(
                            {
                                "type": "RULE_APPLIED",
                                "op_id": job.operations[0].id if job.operations else job.id,
                                "machine_id": target_machine,
                                "detail": (
                                    f"Regra '{rule.get('name', rule['id'])}': "
                                    f"{job.sku} movido {old_machine} → {target_machine}"
                                ),
                            }
                        )
    return applied


class OptimalRequest(BaseModel):
    """Request for the optimal pipeline."""

    solver_request: SolverRequest
    frozen_ops: list[str] = Field(default_factory=list)
    alt_machines: dict[str, list[str]] | None = None
    run_monte_carlo: bool = Field(True, description="Run robustness analysis after solving")
    n_scenarios: int = Field(200, ge=10, le=5000)


class OptimalResult(BaseModel):
    """Result from the optimal pipeline: solver + recovery + robustness."""

    solver_result: SolverResult
    recovery_used: bool = False
    recovery_level: int = 0
    robustness: dict | None = None


@optimal_router.post("/solve", response_model=OptimalResult)
async def optimal_solve(request: OptimalRequest):
    """
    Pipeline óptimo unificado:
    0. Aplicar regras de fábrica (FINAL-04)
    1. CP-SAT solve (via router — routes by problem size)
    2. Se tardiness > 0 → cascading_recovery (4 níveis)
    3. Se feasible → monte_carlo_otd (200 cenários)

    Retorna SolverResult + robustness info.
    """
    # Step 0: Apply factory rules (FINAL-04)
    rule_decisions = _apply_factory_rules(request.solver_request)

    # Step 1: CP-SAT solve
    logger.info("Optimal pipeline: solving %d jobs", len(request.solver_request.jobs))
    result = _get_solver().solve(request.solver_request)
    recovery_used = False
    recovery_level = 0

    # Step 2: Recovery if tardiness > 0
    if result.total_tardiness_min > 0 and result.status in ("optimal", "feasible", "timeout"):
        logger.info(
            "Tardiness %d min — triggering cascading recovery",
            result.total_tardiness_min,
        )
        recovered = cascading_recovery(
            request=request.solver_request,
            frozen_ops=request.frozen_ops or None,
            alt_machines=request.alt_machines,
        )
        if recovered.weighted_tardiness < result.weighted_tardiness:
            result = recovered
            recovery_used = True
            recovery_level = int(recovered.phase_values.get("recovery_level", 0))
            logger.info("Recovery improved result (level %d)", recovery_level)

    # Step 3: Monte Carlo robustness (only if feasible solution found)
    robustness = None
    if request.run_monte_carlo and result.status in ("optimal", "feasible"):
        logger.info("Running Monte Carlo robustness (%d scenarios)", request.n_scenarios)
        robustness = monte_carlo_otd(
            request=request.solver_request,
            n_scenarios=request.n_scenarios,
        )
        logger.info("Robustness: P(OTD=100%%)=%.1f%%", robustness.get("p_otd_100", 0))

    # FINAL-06: Generate enriched decision trail from solver result
    decisions = rule_decisions + _generate_decisions(result, request.solver_request)
    copilot_state.decisions = decisions

    # OPT-05: Wire copilot state with solver result + robustness
    copilot_state.solver_result = {
        "status": result.status,
        "tardiness": result.total_tardiness_min,
        "solver_used": result.solver_used,
        "solve_time_s": result.solve_time_s,
        "recovery_used": recovery_used,
        "recovery_level": recovery_level,
        "robustness": robustness,
    }

    return OptimalResult(
        solver_result=result,
        recovery_used=recovery_used,
        recovery_level=recovery_level,
        robustness=robustness,
    )


def _generate_decisions(result: SolverResult, request: SolverRequest) -> list[dict]:
    """Generate enriched decision trail from CP-SAT schedule (FINAL-06)."""
    DAY_CAP = 1020
    SHIFT_LEN = 510

    job_map = {j.id: j for j in request.jobs}

    # Build workday mapping for calendar day display
    workdays = request.workdays
    has_workdays = len(workdays) > 0

    decisions: list[dict] = []

    for sop in result.schedule:
        job = job_map.get(sop.job_id)
        if not job:
            continue

        solver_day = sop.start_min // DAY_CAP
        # Map solver day to calendar day if workdays provided
        cal_day = (
            workdays[solver_day] if has_workdays and solver_day < len(workdays) else solver_day
        )
        shift = "X" if (sop.start_min % DAY_CAP) < SHIFT_LEN else "Y"
        tardiness = sop.tardiness_min

        decisions.append(
            {
                "type": "PRODUCTION_START",
                "op_id": sop.op_id,
                "machine_id": sop.machine_id,
                "day_idx": cal_day,
                "shift": shift,
                "detail": f"{job.sku} → {sop.machine_id} dia {cal_day} turno {shift}",
            }
        )

        # FINAL-06: JIT buffer info
        deadline_day = job.due_date_min // DAY_CAP
        end_day = (sop.end_min - 1) // DAY_CAP if sop.end_min > 0 else solver_day
        buffer_days = deadline_day - end_day
        if buffer_days > 0:
            decisions.append(
                {
                    "type": "JIT_BUFFER",
                    "op_id": sop.op_id,
                    "machine_id": sop.machine_id,
                    "day_idx": cal_day,
                    "detail": f"Produzido {buffer_days} dia(s) útil(eis) antes da deadline",
                }
            )

        if tardiness > 0:
            decisions.append(
                {
                    "type": "TARDINESS",
                    "op_id": sop.op_id,
                    "machine_id": sop.machine_id,
                    "day_idx": cal_day,
                    "shift": shift,
                    "detail": (
                        f"{job.sku} atrasado {tardiness} min "
                        f"(deadline={job.due_date_min}, end={sop.end_min})"
                    ),
                }
            )

        if sop.setup_min > 0:
            decisions.append(
                {
                    "type": "SETUP",
                    "op_id": sop.op_id,
                    "machine_id": sop.machine_id,
                    "day_idx": cal_day,
                    "shift": shift,
                    "detail": f"Setup {sop.setup_min}min para {sop.tool_id} em {sop.machine_id}",
                }
            )

        # FINAL-06: Twin co-production info
        if sop.is_twin_production and sop.twin_partner_op_id:
            decisions.append(
                {
                    "type": "TWIN_CO_PRODUCTION",
                    "op_id": sop.op_id,
                    "machine_id": sop.machine_id,
                    "day_idx": cal_day,
                    "detail": (
                        f"Co-produção gémea: {sop.op_id} + {sop.twin_partner_op_id} "
                        f"em {sop.machine_id} (ferramenta partilhada, setup 1×)"
                    ),
                }
            )

    return decisions
