"""Canonical anticipation policy: tolerance and setups inside it (AGENTS §1)."""

from __future__ import annotations

from backend.scheduler.policy import (
    ANTICIPATION_TOLERANCE_MIN,
    anticipation_better,
    anticipation_compare,
    anticipation_exact,
    tolerant_tiebreak,
)


def _vector(*windows):
    return tuple((f"L{i}", start, end) for i, (start, end) in enumerate(windows))


def test_tolerance_is_one_hour():
    assert ANTICIPATION_TOLERANCE_MIN == 60.0


def test_59_minutes_do_not_decide_60_do():
    base = _vector((480, 570), (3300, 3390))
    assert anticipation_compare(_vector((539, 629), (3300, 3390)), base) == 0
    assert anticipation_compare(_vector((540, 630), (3300, 3390)), base) == 1


def test_exact_projection_drops_lot_ids():
    assert anticipation_exact(_vector((1, 2), (3, 4))) == ((1, 2), (3, 4))


def test_setups_rank_before_exact_minutes_inside_the_tolerance():
    earlier = _vector((480, 570))
    later = _vector((530, 620))
    assert anticipation_compare(later, earlier) == 0
    assert anticipation_better(earlier, later)  # without setups, minutes decide
    assert tolerant_tiebreak(later, (1, 30.0)) < tolerant_tiebreak(earlier, (2, 60.0))
    assert tolerant_tiebreak(later, (1, 30.0)) < tolerant_tiebreak(earlier, (1, 45.0))
    assert tolerant_tiebreak(earlier, (1, 30.0)) < tolerant_tiebreak(later, (1, 30.0))
