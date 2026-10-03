"""Canonical planning policy: how "earlier" is measured (AGENTS.md §1).

One place for the anticipation measure shared by the improvement evaluator,
the CPO ranks, the local neighbourhoods and the explanations. Lots are
compared lexicographically in the commercial priority order
(``lot_priority_key``): production start, then production finish, of each
lot in turn. Setups, transfers and plan disturbance rank after it, in
``improvement.improvement_key``. Bump ``POLICY_VERSION`` with any change.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from backend.scheduler.priority import lot_priority_key
from backend.scheduler.types import Lot, Segment

POLICY_VERSION = "earliest-lexicographic-v1"
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
