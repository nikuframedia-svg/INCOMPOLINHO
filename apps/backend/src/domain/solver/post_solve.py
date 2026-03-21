"""Post-solve analysis — generate FeasibilityReport + DecisionEntry from SolverResult.

Bridges the gap between CP-SAT solver output and the pipeline response contract.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from ..scheduling.types import (
    DecisionEntry,
    FeasibilityReport,
    InfeasibilityEntry,
)
from .schemas import SolverResult


def build_feasibility_report(result: SolverResult, n_ops: int) -> FeasibilityReport:
    """Build FeasibilityReport from SolverResult status."""
    if result.status in ("optimal", "feasible"):
        tardy_ops = [s for s in result.schedule if s.is_tardy]
        infeasible_entries = [
            InfeasibilityEntry(
                op_id=s.op_id,
                tool_id=s.tool_id,
                machine_id=s.machine_id,
                reason="DEADLINE_VIOLATION",
                detail=f"Tardy by {s.tardiness_min} min",
            )
            for s in tardy_ops
        ]
        by_reason: dict[str, int] = {}
        for e in infeasible_entries:
            by_reason[e.reason] = by_reason.get(e.reason, 0) + 1

        feasible_ops = n_ops - len(tardy_ops)
        score = feasible_ops / max(n_ops, 1)

        return FeasibilityReport(
            total_ops=n_ops,
            feasible_ops=feasible_ops,
            infeasible_ops=len(tardy_ops),
            entries=infeasible_entries,
            by_reason=by_reason,
            feasibility_score=round(score, 4),
            deadline_feasible=len(tardy_ops) == 0,
        )

    elif result.status == "infeasible":
        return FeasibilityReport(
            total_ops=n_ops,
            feasible_ops=0,
            infeasible_ops=n_ops,
            entries=[],
            by_reason={"CAPACITY_OVERFLOW": 1},
            feasibility_score=0.0,
            remediations=[
                {
                    "type": "OVERTIME",
                    "detail": "CP-SAT found no feasible solution. Consider overtime or relaxing constraints.",
                }
            ],
            deadline_feasible=False,
        )

    else:  # timeout
        return FeasibilityReport(
            total_ops=n_ops,
            feasible_ops=0,
            infeasible_ops=0,
            entries=[],
            by_reason={},
            feasibility_score=0.5,
            remediations=[
                {
                    "type": "OVERTIME",
                    "detail": f"Solver timed out after {result.solve_time_s:.1f}s. Increase time limit.",
                }
            ],
            deadline_feasible=False,
        )


def build_decisions(result: SolverResult) -> list[DecisionEntry]:
    """Generate DecisionEntry list from SolverResult."""
    decisions: list[DecisionEntry] = []
    now = time.time()

    # Decision for solver status
    decisions.append(
        DecisionEntry(
            id=_uid(),
            timestamp=now,
            type="SCORING_DECISION",
            detail=(
                f"CP-SAT solver: status={result.status}, "
                f"objective={result.objective_value:.1f}, "
                f"tardiness={result.total_tardiness_min}min, "
                f"solve_time={result.solve_time_s:.2f}s"
            ),
            metadata={
                "solver": result.solver_used,
                "status": result.status,
                "objective_value": result.objective_value,
                "makespan_min": result.makespan_min,
                "total_tardiness_min": result.total_tardiness_min,
                "weighted_tardiness": result.weighted_tardiness,
                "n_ops": result.n_ops,
            },
        )
    )

    # Decision per tardy operation
    for sop in result.schedule:
        if sop.is_tardy and sop.tardiness_min > 0:
            decisions.append(
                DecisionEntry(
                    id=_uid(),
                    timestamp=now,
                    type="DEADLINE_CONSTRAINT",
                    op_id=sop.op_id,
                    tool_id=sop.tool_id,
                    machine_id=sop.machine_id,
                    detail=f"Tardy by {sop.tardiness_min} min (CP-SAT optimal)",
                    metadata={
                        "tardiness_min": sop.tardiness_min,
                        "start_min": sop.start_min,
                        "end_min": sop.end_min,
                    },
                    reversible=False,
                )
            )

    # Decision per twin co-production
    seen_twins: set[str] = set()
    for sop in result.schedule:
        if sop.is_twin_production and sop.twin_partner_op_id:
            pair_key = "|".join(sorted([sop.op_id, sop.twin_partner_op_id]))
            if pair_key in seen_twins:
                continue
            seen_twins.add(pair_key)
            decisions.append(
                DecisionEntry(
                    id=_uid(),
                    timestamp=now,
                    type="TWIN_VALIDATION_ANOMALY",
                    op_id=sop.op_id,
                    machine_id=sop.machine_id,
                    detail=f"Twin co-production: {sop.op_id} + {sop.twin_partner_op_id}",
                    metadata={
                        "partner_op_id": sop.twin_partner_op_id,
                        "start_min": sop.start_min,
                    },
                )
            )

    # Operator warnings
    for warn in result.operator_warnings:
        decisions.append(
            DecisionEntry(
                id=_uid(),
                timestamp=now,
                type="OPERATOR_CAPACITY_WARNING",
                op_id=warn.get("op_id"),
                machine_id=warn.get("machine_id"),
                detail=(
                    f"Shift {warn.get('shift')}: needs {warn.get('operators_needed')} "
                    f"operators, capacity {warn.get('capacity')}"
                ),
                metadata=warn,
            )
        )

    return decisions


def _uid() -> str:
    return str(uuid.uuid4())[:12]
