"""Journal — Spec 12 §2.

Structured phase-level telemetry for the scheduling pipeline.
Extends (never replaces) ScheduleResult.warnings.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(slots=True)
class JournalEntry:
    step: str  # "guardian" | "lot_sizing" | "tool_grouping" | "dispatch" | "jit" | "scoring"
    severity: str  # "info" | "warn" | "error"
    message: str
    metadata: dict
    elapsed_ms: float


class Journal:
    """Accumulates JournalEntry items during a scheduling run."""

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []
        self._timers: dict[str, float] = {}

    def phase_start(self, step: str) -> None:
        """Mark the start of a phase."""
        self._timers[step] = time.perf_counter()

    def phase_end(self, step: str, message: str, **metadata: object) -> None:
        """Mark end of a phase, recording elapsed time and metadata."""
        t0 = self._timers.pop(step, time.perf_counter())
        elapsed = (time.perf_counter() - t0) * 1000
        self._entries.append(
            JournalEntry(
                step=step,
                severity="info",
                message=message,
                metadata=dict(metadata),
                elapsed_ms=round(elapsed, 2),
            )
        )

    def log(self, step: str, severity: str, message: str, **metadata: object) -> None:
        """Log an arbitrary entry (warn/error during a phase)."""
        self._entries.append(
            JournalEntry(
                step=step,
                severity=severity,
                message=message,
                metadata=dict(metadata),
                elapsed_ms=0.0,
            )
        )

    def to_entries(self) -> list[JournalEntry]:
        """Return all entries."""
        return list(self._entries)

    def to_warnings(self) -> list[str]:
        """Convert entries with severity >= warn to plain strings."""
        return [f"[{e.step}] {e.message}" for e in self._entries if e.severity in ("warn", "error")]

    def to_dicts(self) -> list[dict]:
        """Serialize entries for ScheduleResult.journal."""
        return [
            {
                "step": e.step,
                "severity": e.severity,
                "message": e.message,
                "metadata": e.metadata,
                "elapsed_ms": e.elapsed_ms,
            }
            for e in self._entries
        ]

    def summary(self) -> dict:
        """Consolidated summary for API responses."""
        return {
            "total": len(self._entries),
            "steps": sorted({e.step for e in self._entries}),
            "warnings": len([e for e in self._entries if e.severity in ("warn", "error")]),
            "total_ms": round(sum(e.elapsed_ms for e in self._entries), 1),
        }
