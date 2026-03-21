"""Output Guardian — validates solver output for physical impossibilities.

Catches scheduling bugs at solver boundary:
- Operations outside shift windows
- Weekend scheduling (non-workday)
- start >= end (zero or negative duration)
- Overlapping blocks on same machine
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .journal import Journal, JournalSeverity, JournalStep

# Shift boundaries (minutes from midnight)
SHIFT_X_START = 420   # 07:00
SHIFT_X_END = 930     # 15:30
SHIFT_Y_END = 1440    # 24:00
SHIFT_Z_END = 1860    # 31:00 (next day 07:00)


class SolverOutputError(Exception):
    """Raised when solver output contains physically impossible schedules."""

    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__(f"Solver output validation failed: {'; '.join(violations[:5])}")


@dataclass
class OutputViolation:
    """A single output validation violation."""

    block_idx: int
    op_id: str
    machine_id: str
    day_idx: int
    violation_type: str
    detail: str


class OutputGuardian:
    """Validates solver output blocks for physical impossibilities."""

    def __init__(self, journal: Journal) -> None:
        self._journal = journal

    def validate(
        self,
        blocks: list[Any],
        workdays: list[bool] | None = None,
        *,
        raise_on_error: bool = False,
    ) -> list[OutputViolation]:
        """Validate solver output blocks.

        Returns list of violations. If raise_on_error=True, raises SolverOutputError
        when any critical violations are found.
        """
        self._journal.step(JournalStep.VALIDATE_OUTPUT, "Validating solver output")

        violations: list[OutputViolation] = []

        for i, block in enumerate(blocks):
            op_id = _get(block, "opId", _get(block, "op_id", f"block_{i}"))
            machine_id = _get(block, "machineId", _get(block, "machine_id", "?"))
            day_idx = _get(block, "dayIdx", _get(block, "day_idx", 0))
            start_min = _get(block, "startMin", _get(block, "start_min", 0))
            end_min = _get(block, "endMin", _get(block, "end_min", 0))
            block_type = _get(block, "type", "ok")

            # Skip infeasible/blocked — they're not actually scheduled
            if block_type in ("infeasible", "blocked"):
                continue

            # 1. start < end
            if start_min >= end_min:
                v = OutputViolation(
                    block_idx=i, op_id=op_id, machine_id=machine_id,
                    day_idx=day_idx, violation_type="ZERO_DURATION",
                    detail=f"start={start_min} >= end={end_min}",
                )
                violations.append(v)

            # 2. Not outside max shift window
            if end_min > SHIFT_Z_END:
                v = OutputViolation(
                    block_idx=i, op_id=op_id, machine_id=machine_id,
                    day_idx=day_idx, violation_type="OUTSIDE_SHIFTS",
                    detail=f"end_min={end_min} > max shift end ({SHIFT_Z_END})",
                )
                violations.append(v)

            if start_min < SHIFT_X_START:
                v = OutputViolation(
                    block_idx=i, op_id=op_id, machine_id=machine_id,
                    day_idx=day_idx, violation_type="BEFORE_SHIFT_START",
                    detail=f"start_min={start_min} < shift start ({SHIFT_X_START})",
                )
                violations.append(v)

            # 3. Weekend check
            if workdays is not None and 0 <= day_idx < len(workdays):
                if not workdays[day_idx]:
                    v = OutputViolation(
                        block_idx=i, op_id=op_id, machine_id=machine_id,
                        day_idx=day_idx, violation_type="WEEKEND_SCHEDULING",
                        detail=f"Scheduled on non-workday (dayIdx={day_idx})",
                    )
                    violations.append(v)

        # 4. Overlap check (same machine, same day)
        machine_day_blocks: dict[str, list[tuple[int, int, str, int]]] = {}
        for i, block in enumerate(blocks):
            block_type = _get(block, "type", "ok")
            if block_type in ("infeasible", "blocked"):
                continue

            machine_id = _get(block, "machineId", _get(block, "machine_id", "?"))
            day_idx = _get(block, "dayIdx", _get(block, "day_idx", 0))
            start_min = _get(block, "startMin", _get(block, "start_min", 0))
            end_min = _get(block, "endMin", _get(block, "end_min", 0))
            op_id = _get(block, "opId", _get(block, "op_id", f"block_{i}"))

            key = f"{machine_id}_{day_idx}"
            if key not in machine_day_blocks:
                machine_day_blocks[key] = []
            machine_day_blocks[key].append((start_min, end_min, op_id, i))

        for key, intervals in machine_day_blocks.items():
            sorted_intervals = sorted(intervals, key=lambda x: x[0])
            for j in range(1, len(sorted_intervals)):
                prev_start, prev_end, prev_op, prev_idx = sorted_intervals[j - 1]
                curr_start, curr_end, curr_op, curr_idx = sorted_intervals[j]
                if curr_start < prev_end:
                    machine_id = key.split("_")[0]
                    day_idx = int(key.split("_")[1])
                    overlap_min = prev_end - curr_start
                    v = OutputViolation(
                        block_idx=curr_idx, op_id=curr_op, machine_id=machine_id,
                        day_idx=day_idx, violation_type="OVERLAP",
                        detail=f"Overlaps with {prev_op} by {overlap_min}min "
                               f"({prev_start}-{prev_end} vs {curr_start}-{curr_end})",
                    )
                    violations.append(v)

        # Log results
        if violations:
            by_type: dict[str, int] = {}
            for v in violations:
                by_type[v.violation_type] = by_type.get(v.violation_type, 0) + 1

            self._journal.warn(
                JournalStep.VALIDATE_OUTPUT,
                f"Output validation: {len(violations)} violations",
                metadata={"by_type": by_type, "total": len(violations)},
            )

            if raise_on_error:
                critical = [v for v in violations if v.violation_type in ("ZERO_DURATION", "OVERLAP")]
                if critical:
                    raise SolverOutputError([v.detail for v in critical[:10]])
        else:
            self._journal.info(
                JournalStep.VALIDATE_OUTPUT,
                f"Output validation passed ({len(blocks)} blocks)",
            )

        return violations


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Get attribute from dict or object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
