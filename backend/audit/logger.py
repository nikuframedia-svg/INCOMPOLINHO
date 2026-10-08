"""Audit Logger — Spec 07 §2.

Constraint-waterfall recorder. Injected into dispatch/jit/tool_grouping.
Each decision is recorded with WHY.
"""

from __future__ import annotations

import time
from collections import defaultdict

from .templates import render_decision
from .types import Alternative, AuditTrail, DecisionRecord


class AuditLogger:
    """Records scheduler decisions with constraint waterfall."""

    def __init__(self) -> None:
        self.decisions: list[DecisionRecord] = []
        self._t0 = time.perf_counter()

    def _elapsed(self) -> float:
        return (time.perf_counter() - self._t0) * 1000

    def _next_id(self) -> str:
        return f"D{len(self.decisions):04d}"

    def log_assign(
        self,
        run_id: str,
        tool_id: str,
        chosen: str,
        candidates: list[tuple[str, float]],  # (machine_id, load)
        rule: str,
    ) -> None:
        """Record machine assignment decision."""
        alts = []
        chosen_load = 0.0
        for machine_id, load in candidates:
            if machine_id == chosen:
                chosen_load = load
            else:
                alts.append(
                    Alternative(
                        value=machine_id,
                        score=load,
                        rejected_by="LOAD_BALANCE",
                        reason=f"Carga {load:.0f}min",
                    )
                )

        binding = "ONLY_OPTION" if not alts else "LOAD_BALANCE"

        record = DecisionRecord(
            id=self._next_id(),
            phase="assign",
            subject_id=run_id,
            subject_type="run",
            action="assign_machine",
            chosen=chosen,
            rule=rule,
            binding_constraint=binding,
            alternatives=alts,
            state_snapshot={
                "chosen_load": chosen_load,
                "alt_load": alts[0].score if alts else 0.0,
                "tool_id": tool_id,
                "edd": 0,
            },
            explanation_pt="",
            timestamp_ms=self._elapsed(),
        )
        record.explanation_pt = render_decision(record)
        self.decisions.append(record)

    def log_sequence(
        self,
        machine_id: str,
        rule: str,
        n_moves: int,
    ) -> None:
        """Record a sequencing decision (campaign, interleave, 2-opt)."""
        if n_moves == 0:
            return

        record = DecisionRecord(
            id=self._next_id(),
            phase="sequence",
            subject_id=machine_id,
            subject_type="run",
            action="set_sequence",
            chosen=f"{n_moves} moves",
            rule=rule,
            binding_constraint=rule,
            alternatives=[],
            state_snapshot={"machine_id": machine_id, "n_moves": n_moves},
            explanation_pt="",
            timestamp_ms=self._elapsed(),
        )
        record.explanation_pt = render_decision(record)
        self.decisions.append(record)

    def log_gate(
        self,
        run_id: str,
        gate_abs: float,
        max_gate_abs: float,
        edd: int,
        rule: str = "gate_jit",
        machine_id: str = "",
        attempt: int = 0,
        config=None,
    ) -> None:
        """Record material-release gate placement."""
        if config:
            day_cap = config.day_capacity_min
        else:
            from backend.scheduler.constants import DAY_CAP

            day_cap = DAY_CAP

        gate_day = gate_abs / day_cap if day_cap > 0 else 0
        max_gate_day = max_gate_abs / day_cap if day_cap > 0 else 0

        record = DecisionRecord(
            id=self._next_id(),
            phase="jit",
            subject_id=run_id,
            subject_type="run",
            action="set_gate",
            chosen=f"dia {gate_day:.0f}",
            rule=rule,
            binding_constraint="JIT_BACKWARD",
            alternatives=[],
            state_snapshot={
                "gate_day": gate_day,
                "max_gate_day": max_gate_day,
                "edd": edd,
                "machine_id": machine_id,
                "attempt": attempt,
            },
            explanation_pt="",
            timestamp_ms=self._elapsed(),
        )
        record.explanation_pt = render_decision(record)
        self.decisions.append(record)

    def log_split(
        self,
        original_id: str,
        reason: str,
        early_lots: int,
        late_lots: int,
        total_min: float = 0,
        capacity: float = 0,
    ) -> None:
        """Record tool-run split decision."""
        rule = "split_infeasible" if reason == "infeasible" else "split_edd_gap"

        record = DecisionRecord(
            id=self._next_id(),
            phase="tool_grouping",
            subject_id=original_id,
            subject_type="run",
            action="split_run",
            chosen=f"early={early_lots}, late={late_lots}",
            rule=rule,
            binding_constraint="CAPACITY",
            alternatives=[],
            state_snapshot={
                "original_id": original_id,
                "early_lots": early_lots,
                "late_lots": late_lots,
                "total_min": total_min,
                "capacity": capacity,
                "max_gap": 10,
            },
            explanation_pt="",
            timestamp_ms=self._elapsed(),
        )
        record.explanation_pt = render_decision(record)
        self.decisions.append(record)

    def get_trail(self, schedule_id: str = "") -> AuditTrail:
        """Build the final AuditTrail."""
        phases: dict[str, int] = defaultdict(int)
        for d in self.decisions:
            phases[d.phase] += 1

        return AuditTrail(
            schedule_id=schedule_id or str(int(time.time())),
            decisions=self.decisions,
            total_decisions=len(self.decisions),
            phases=dict(phases),
        )
