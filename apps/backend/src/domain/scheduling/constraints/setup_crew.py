"""SetupCrew constraint — max 1 setup simultâneo em toda a fábrica.

Port of constraints/setup-crew.ts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SetupSlot:
    start: int
    end: int
    machine_id: str


@dataclass
class SetupCrewResult:
    available_at: int
    has_conflict: bool
    conflict_with: str | None = None


class SetupCrew:
    """Factory-wide setup crew — max 1 setup at a time."""

    def __init__(self) -> None:
        self._slots: list[SetupSlot] = []

    def find_next_available(self, earliest: int, duration: int, shift_end: int) -> int:
        """Find the earliest time >= earliest where duration fits without overlap."""
        candidate = earliest
        for slot in self._slots:
            if candidate < slot.end and candidate + duration > slot.start:
                candidate = slot.end
        if candidate + duration > shift_end:
            return -1
        return candidate

    def check(
        self, earliest: int, duration: int, shift_end: int, machine_id: str
    ) -> SetupCrewResult:
        """Check if setup can start at earliest."""
        for slot in self._slots:
            if earliest < slot.end and earliest + duration > slot.start:
                available = slot.end
                if available + duration > shift_end:
                    return SetupCrewResult(
                        available_at=-1, has_conflict=True, conflict_with=slot.machine_id
                    )
                return SetupCrewResult(
                    available_at=available, has_conflict=True, conflict_with=slot.machine_id
                )
        return SetupCrewResult(available_at=earliest, has_conflict=False)

    def book(self, start: int, end: int, machine_id: str) -> None:
        """Record a setup booking."""
        self._slots.append(SetupSlot(start=start, end=end, machine_id=machine_id))

    def unbook(self, start: int, end: int, machine_id: str) -> None:
        """Remove a specific booking (exact match)."""
        self._slots = [
            s
            for s in self._slots
            if not (s.start == start and s.end == end and s.machine_id == machine_id)
        ]

    def get_slots(self) -> list[SetupSlot]:
        return list(self._slots)

    def clear(self) -> None:
        self._slots.clear()
