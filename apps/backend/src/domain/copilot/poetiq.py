"""Poetiq cycle — Generate → Verify → Critique → Refine.

Iterative improvement loop for copilot responses that involve
scheduling decisions. Uses the solver to verify plan viability.

Flow:
  1. Generate initial response (GPT-4o)
  2. Verify against solver (CP-SAT via /v1/solver/schedule)
  3. If viable + OTD >= 99%: return
  4. Critique: build specific feedback on what failed
  5. Refine: generate improved response with critique context
  6. Repeat until max_iter or success
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PoetiqResult:
    """Result of a Poetiq cycle."""

    response: str
    viable: bool
    otd_pct: float = 0.0
    iterations: int = 1
    critiques: list[str] = field(default_factory=list)
    solver_result: dict[str, Any] | None = None


@dataclass
class PoetiqConfig:
    """Configuration for the Poetiq cycle."""

    max_iterations: int = 5
    otd_threshold: float = 0.99
    solver_timeout_s: int = 30
    model: str = "gpt-4o"


def build_critique(solver_result: dict[str, Any], config: PoetiqConfig) -> str:
    """Build specific critique from solver verification result."""
    issues = []

    status = solver_result.get("solver_status", "unknown")
    if status != "optimal":
        issues.append(f"Solver status: {status} (esperado: optimal)")

    kpis = solver_result.get("kpis", {})
    otd = kpis.get("otd_pct", 0)
    if otd < config.otd_threshold * 100:
        issues.append(f"OTD = {otd}% (mínimo: {config.otd_threshold * 100}%)")

    overflow = kpis.get("overflow_count", 0)
    if overflow > 0:
        issues.append(f"{overflow} operações em overflow — capacidade insuficiente")

    violations = kpis.get("constraint_violations", 0)
    if violations > 0:
        issues.append(f"{violations} violações de constraints")

    infeasible = kpis.get("infeasible_count", 0)
    if infeasible > 0:
        issues.append(f"{infeasible} operações infeasible")

    tardiness = kpis.get("total_tardiness_days", 0)
    if tardiness > 0:
        issues.append(f"Tardiness total: {tardiness} dias")

    if not issues:
        return "Plano parece viável mas OTD ainda abaixo do threshold."

    return "PROBLEMAS ENCONTRADOS:\n" + "\n".join(f"- {i}" for i in issues)


def _is_success(solver_result: dict[str, Any], config: PoetiqConfig) -> bool:
    """Check if solver result meets success criteria."""
    kpis = solver_result.get("kpis", {})
    otd = kpis.get("otd_pct", 0) / 100.0
    status = solver_result.get("solver_status", "unknown")
    return status in ("optimal", "feasible") and otd >= config.otd_threshold


async def poetiq_cycle(
    problem: str,
    generate_fn: Any,
    verify_fn: Any,
    config: PoetiqConfig | None = None,
) -> PoetiqResult:
    """Execute the Poetiq cycle: Generate → Verify → Critique → Refine.

    Args:
        problem: The user's scheduling problem/question.
        generate_fn: async fn(problem, history) -> str — generates a response.
        verify_fn: async fn(response) -> dict — verifies via solver, returns solver result.
        config: Poetiq configuration.

    Returns:
        PoetiqResult with final response and metadata.
    """
    if config is None:
        config = PoetiqConfig()

    history: list[dict[str, str]] = []
    critiques: list[str] = []
    last_response = ""
    last_solver_result: dict[str, Any] = {}

    for iteration in range(1, config.max_iterations + 1):
        logger.info("Poetiq iteration %d/%d", iteration, config.max_iterations)

        # Generate
        response = await generate_fn(problem, history)
        last_response = response

        # Verify
        try:
            solver_result = await verify_fn(response)
            last_solver_result = solver_result
        except Exception as e:
            logger.warning("Solver verification failed: %s", e)
            solver_result = {"solver_status": "error", "kpis": {}}
            last_solver_result = solver_result

        # Check success
        if _is_success(solver_result, config):
            logger.info("Poetiq success at iteration %d", iteration)
            return PoetiqResult(
                response=response,
                viable=True,
                otd_pct=solver_result.get("kpis", {}).get("otd_pct", 0),
                iterations=iteration,
                critiques=critiques,
                solver_result=solver_result,
            )

        # Critique
        critique = build_critique(solver_result, config)
        critiques.append(critique)
        logger.info("Critique: %s", critique)

        # Add to history for refinement
        history.append({"role": "assistant", "content": response})
        history.append(
            {
                "role": "user",
                "content": (
                    f"A tua resposta não produziu um plano viável. "
                    f"Iteração {iteration}/{config.max_iterations}.\n\n{critique}\n\n"
                    f"Corrige a tua proposta considerando estes problemas."
                ),
            }
        )

    # Max iterations reached — return best effort
    logger.warning("Poetiq max iterations (%d) reached", config.max_iterations)
    return PoetiqResult(
        response=last_response,
        viable=False,
        otd_pct=last_solver_result.get("kpis", {}).get("otd_pct", 0),
        iterations=config.max_iterations,
        critiques=critiques,
        solver_result=last_solver_result,
    )


def format_poetiq_response(result: PoetiqResult) -> str:
    """Format a Poetiq result for display to the user."""
    parts = [result.response]

    if result.iterations > 1:
        parts.append(
            f"\n\n---\n_Verificado em {result.iterations} iterações. "
            f"OTD: {result.otd_pct:.1f}%. "
            f"{'Plano viável.' if result.viable else 'Plano não atingiu 100% OTD.'}_"
        )

    return "\n".join(parts)
