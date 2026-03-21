"""Journal — Structured audit trail for the scheduling pipeline.

Every pipeline step, every dropped operation, every warning gets a journal entry.
Consumed by:
- Copilot (explain_decision tool)
- Frontend (transparency panel)
- Audit trail (persistence)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class JournalStep(str, Enum):
    """Pipeline steps tracked by the journal."""

    PARSE = "PARSE"
    TRANSFORM = "TRANSFORM"
    VALIDATE_INPUT = "VALIDATE_INPUT"
    TWIN_MERGE = "TWIN_MERGE"
    SOLVE = "SOLVE"
    VALIDATE_OUTPUT = "VALIDATE_OUTPUT"
    RECOVERY = "RECOVERY"
    ANALYTICS = "ANALYTICS"
    CACHE = "CACHE"


class JournalSeverity(str, Enum):
    """Severity levels for journal entries."""

    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    DROP = "DROP"


@dataclass
class JournalEntry:
    """A single journal entry."""

    step: JournalStep
    severity: JournalSeverity
    message: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "step": self.step.value,
            "severity": self.severity.value,
            "message": self.message,
            "timestamp": self.timestamp,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        if self.elapsed_ms is not None:
            d["elapsed_ms"] = round(self.elapsed_ms, 2)
        return d


class Journal:
    """Pipeline audit journal. Collects entries across all steps."""

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []
        self._step_starts: dict[str, float] = {}

    @property
    def entries(self) -> list[JournalEntry]:
        return list(self._entries)

    def step(self, step: JournalStep, message: str, **kwargs: Any) -> None:
        """Mark the start of a pipeline step."""
        self._step_starts[step.value] = time.perf_counter()
        self._entries.append(JournalEntry(
            step=step, severity=JournalSeverity.INFO,
            message=message, **kwargs,
        ))

    def info(
        self, step: JournalStep, message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        elapsed = self._elapsed(step)
        self._entries.append(JournalEntry(
            step=step, severity=JournalSeverity.INFO,
            message=message, metadata=metadata or {},
            elapsed_ms=elapsed,
        ))

    def warn(
        self, step: JournalStep, message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        elapsed = self._elapsed(step)
        self._entries.append(JournalEntry(
            step=step, severity=JournalSeverity.WARN,
            message=message, metadata=metadata or {},
            elapsed_ms=elapsed,
        ))

    def error(
        self, step: JournalStep, message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        elapsed = self._elapsed(step)
        self._entries.append(JournalEntry(
            step=step, severity=JournalSeverity.ERROR,
            message=message, metadata=metadata or {},
            elapsed_ms=elapsed,
        ))

    def drop(
        self, step: JournalStep, message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a dropped item (operation, data point, etc)."""
        self._entries.append(JournalEntry(
            step=step, severity=JournalSeverity.DROP,
            message=message, metadata=metadata or {},
        ))

    def _elapsed(self, step: JournalStep) -> float | None:
        start = self._step_starts.get(step.value)
        if start is None:
            return None
        return (time.perf_counter() - start) * 1000

    # ── Summary methods ──

    def summary(self) -> dict[str, Any]:
        """Produce a summary dict for API responses."""
        by_severity: dict[str, int] = {}
        by_step: dict[str, int] = {}
        drops: list[dict[str, Any]] = []

        for entry in self._entries:
            sev = entry.severity.value
            by_severity[sev] = by_severity.get(sev, 0) + 1
            step = entry.step.value
            by_step[step] = by_step.get(step, 0) + 1
            if entry.severity == JournalSeverity.DROP:
                drops.append({
                    "step": step,
                    "message": entry.message,
                    **({"metadata": entry.metadata} if entry.metadata else {}),
                })

        return {
            "total_entries": len(self._entries),
            "by_severity": by_severity,
            "by_step": by_step,
            "drops": drops[:50],  # Cap at 50 to avoid bloated responses
            "has_errors": by_severity.get("ERROR", 0) > 0,
            "has_warnings": by_severity.get("WARN", 0) > 0,
        }

    def to_decisions(self) -> list[dict[str, Any]]:
        """Convert journal entries to decision-like dicts for copilot/UI.

        Only includes WARN, ERROR, and DROP entries — INFO is noise for decisions.
        """
        decisions: list[dict[str, Any]] = []
        for entry in self._entries:
            if entry.severity == JournalSeverity.INFO:
                continue
            decisions.append({
                "type": f"GUARDIAN_{entry.severity.value}",
                "step": entry.step.value,
                "detail": entry.message,
                "metadata": entry.metadata,
                "timestamp": entry.timestamp,
            })
        return decisions

    def to_list(self) -> list[dict[str, Any]]:
        """Serialize all entries to dicts."""
        return [e.to_dict() for e in self._entries]
