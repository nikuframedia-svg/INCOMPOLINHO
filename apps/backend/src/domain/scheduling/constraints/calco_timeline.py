"""CalcoTimeline constraint — calço em 1 máquina de cada vez.

Port of constraints/calco-timeline.ts.
More restrictive than ToolTimeline: NO same-machine exception.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CalcoBooking:
    start: int
    end: int
    machine_id: str


@dataclass
class CalcoCheckResult:
    is_available: bool
    available_at: int
    conflict_machine: str | None = None


class CalcoTimeline:
    """Calco constraint: 1 calco, no parallel usage anywhere."""

    def __init__(self) -> None:
        self._bookings: dict[str, list[CalcoBooking]] = {}

    def is_available(self, calco_code: str, start: int, end: int) -> bool:
        if not calco_code:
            return True
        for bk in self._bookings.get(calco_code, []):
            if start < bk.end and end > bk.start:
                return False
        return True

    def find_next_available(
        self,
        calco_code: str,
        earliest: int,
        duration: int,
        shift_end: int,
    ) -> int:
        if not calco_code:
            return earliest
        candidate = earliest
        changed = True
        while changed:
            changed = False
            for bk in self._bookings.get(calco_code, []):
                if candidate < bk.end and candidate + duration > bk.start:
                    candidate = bk.end
                    changed = True
        if candidate + duration > shift_end:
            return -1
        return candidate

    def check(self, calco_code: str, start: int, end: int) -> CalcoCheckResult:
        if not calco_code:
            return CalcoCheckResult(is_available=True, available_at=start)
        for bk in self._bookings.get(calco_code, []):
            if start < bk.end and end > bk.start:
                return CalcoCheckResult(
                    is_available=False,
                    available_at=bk.end,
                    conflict_machine=bk.machine_id,
                )
        return CalcoCheckResult(is_available=True, available_at=start)

    def book(self, calco_code: str, start: int, end: int, machine_id: str) -> None:
        if not calco_code:
            return
        self._bookings.setdefault(calco_code, []).append(
            CalcoBooking(start=start, end=end, machine_id=machine_id)
        )

    def unbook(self, calco_code: str, start: int, end: int, machine_id: str) -> None:
        """Remove a specific booking (exact match)."""
        if not calco_code:
            return
        bks = self._bookings.get(calco_code, [])
        self._bookings[calco_code] = [
            bk
            for bk in bks
            if not (bk.start == start and bk.end == end and bk.machine_id == machine_id)
        ]

    def get_bookings(self, calco_code: str) -> list[CalcoBooking]:
        return list(self._bookings.get(calco_code, []))

    def clear(self) -> None:
        self._bookings.clear()
