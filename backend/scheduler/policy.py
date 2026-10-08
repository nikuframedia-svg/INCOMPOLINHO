"""Canonical planning policy: how "earlier" is measured (AGENTS.md §1).

One place for the anticipation measure shared by the improvement evaluator,
the CPO ranks, the local neighbourhoods and the explanations. Lots are
compared in the commercial priority order (``lot_priority_key``): production
start, then production finish, of each lot in turn. Setups, transfers and plan
disturbance rank after it, in ``improvement.improvement_key``. Bump
``POLICY_VERSION`` with any change.

Tolerance (decision of 05/10/2026): a difference smaller than
``ANTICIPATION_TOLERANCE_MIN`` does not decide between lots. A lot may only
start or finish that much later when a more urgent lot gains at least as
much. Exact minutes still break ties afterwards, so small gains are taken
when nothing larger is at stake. The tolerant comparison is not transitive:
callers compare against both the current and the reference plan.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from backend.scheduler.priority import lot_priority_key
from backend.scheduler.types import Lot, Segment

POLICY_VERSION = "earliest-lexicographic-tolerant-v2"
ANTICIPATION_TOLERANCE_MIN = 60.0
_MISSING = math.inf

# Per lot, in commercial priority order: (lot id, production start, production
# finish) in absolute plan minutes. Lots without production rank last.
type AnticipationKey = tuple[tuple[str, float, float], ...]


def production_windows(segments: Iterable[Segment]) -> dict[str, tuple[float, float]]:
    """First productive minute and end of production per lot, absolute minutes.

    Setup minutes are excluded from the start: a lot "starts" when it starts
    producing. Duration enters only through the finish, so a slower machine
    cannot win merely by having fewer productive minutes.
    """

    windows: dict[str, tuple[float, float]] = {}
    for segment in segments:
        if segment.prod_min <= 0:
            continue
        base = float(segment.day_idx) * 1440.0
        start = base + float(segment.start_min) + max(0.0, float(segment.setup_min))
        end = base + float(segment.end_min)
        before = windows.get(segment.lot_id)
        windows[segment.lot_id] = (
            (start, end) if before is None else (min(before[0], start), max(before[1], end))
        )
    return windows

def anticipation_key(segments: Iterable[Segment], lots: Iterable[Lot]) -> AnticipationKey:
    """Lexicographic anticipation vector, smaller is earlier.

    Lots are ordered once by the canonical commercial priority, so advancing
    a less urgent lot never compensates delaying a more urgent one. The
    material release ``R`` of a lot is the same in every candidate of one
    scenario, so comparing ``S`` and ``F`` is comparing ``S-R`` and ``F-R``.
    Only meaningful between candidates with the same lots.
    """

    windows = production_windows(segments)
    return tuple(
        (lot.id, *windows.get(lot.id, (_MISSING, _MISSING)))
        for lot in sorted(lots, key=lot_priority_key)
    )


def anticipation_compare(
    candidate, reference, tolerance: float = ANTICIPATION_TOLERANCE_MIN,
) -> int:
    """-1 if ``candidate`` is earlier, 1 if later, 0 if no difference reaches
    ``tolerance``. Elements end with (start, finish); both vectors list the
    same lots in the same order."""

    for left, right in zip(candidate, reference, strict=True):
        for a, b in ((left[-2], right[-2]), (left[-1], right[-1])):
            if a == b:
                continue
            if math.isinf(a) or math.isinf(b) or abs(a - b) >= tolerance:
                return -1 if a < b else 1
    return 0


def anticipation_better(
    candidate, reference, tolerance: float = ANTICIPATION_TOLERANCE_MIN,
) -> bool:
    """Tolerant comparison first, exact lexicographic minutes as tie-break."""

    decided = anticipation_compare(candidate, reference, tolerance)
    if decided:
        return decided < 0
    return tuple(item[-2:] for item in candidate) < tuple(item[-2:] for item in reference)

