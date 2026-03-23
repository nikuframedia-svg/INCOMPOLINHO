"""ToolTimeline constraint — ferramenta em 1 máquina de cada vez.

Port of constraints/tool-timeline.ts.
Same-machine reuse is OK (no self-conflict).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolBooking:
    start: int
    end: int
    machine_id: str


@dataclass
class ToolCheckResult:
    is_available: bool
    available_at: int
    conflict_count: int = 0
    conflicting_machines: list[str] | None = None


class ToolTimeline:
    """Physical tool constraint: 1 tool instance per machine at a time."""

    def __init__(self) -> None:
        self._bookings: dict[str, list[ToolBooking]] = {}

    def is_available(self, tool_id: str, start: int, end: int, machine_id: str) -> bool:
        """Check if tool is available at [start, end) on machine_id."""
        for bk in self._bookings.get(tool_id, []):
            if bk.machine_id == machine_id:
                continue  # same machine OK
            if start < bk.end and end > bk.start:
                return False
        return True

    def find_next_available(
        self,
        tool_id: str,
        earliest: int,
        duration: int,
        shift_end: int,
        machine_id: str,
    ) -> int:
        """Find earliest start >= earliest where tool is free for duration."""
        candidate = earliest
        changed = True
        while changed:
            changed = False
            for bk in self._bookings.get(tool_id, []):
                if bk.machine_id == machine_id:
                    continue
                if candidate < bk.end and candidate + duration > bk.start:
                    candidate = bk.end
                    changed = True
        if candidate + duration > shift_end:
            return -1
        return candidate

    def check(
        self,
        tool_id: str,
        start: int,
        end: int,
        machine_id: str,
    ) -> ToolCheckResult:
        """Full check with conflict details."""
        conflicts: list[str] = []
        latest_end = start
        for bk in self._bookings.get(tool_id, []):
            if bk.machine_id == machine_id:
                continue
            if start < bk.end and end > bk.start:
                conflicts.append(bk.machine_id)
                latest_end = max(latest_end, bk.end)
        if conflicts:
            return ToolCheckResult(
                is_available=False,
                available_at=latest_end,
                conflict_count=len(conflicts),
                conflicting_machines=conflicts,
            )
        return ToolCheckResult(is_available=True, available_at=start)

    def book(self, tool_id: str, start: int, end: int, machine_id: str) -> None:
        self._bookings.setdefault(tool_id, []).append(
            ToolBooking(start=start, end=end, machine_id=machine_id)
        )

    def unbook(self, tool_id: str, start: int, end: int, machine_id: str) -> None:
        """Remove a specific booking (exact match)."""
        bks = self._bookings.get(tool_id, [])
        self._bookings[tool_id] = [
            bk
            for bk in bks
            if not (bk.start == start and bk.end == end and bk.machine_id == machine_id)
        ]

    def get_bookings(self, tool_id: str) -> list[ToolBooking]:
        return list(self._bookings.get(tool_id, []))

    def clear(self) -> None:
        self._bookings.clear()
