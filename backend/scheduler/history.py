"""The plan's history boundary (AGENTS §2 rule 4, decided 13/10/2026).

One rule, shared by the release of protected work (``plans.frozen``), the
validation of a plan (``scheduler.validation``, ``scheduler.operators``) and
the commit guard (``plans.frozen.historical_schedule_changes``):

* What starts before the boundary ``(day, minute)`` — the current factory
  minute of the calculation — already happened.
* A time-bound input (machine or tool unavailability, operator absence or
  cut, holiday, eligibility, shifts) judges the plan only from
  ``max(boundary, start of the input)`` on: an absence from 07:00 entered at
  10:00 says nothing about the production of 07:00–10:00, which is history.
* When an input conflicts with protected work, the segment is cut at
  ``max(boundary, start of the conflict)``: the part before stays exactly as
  it was (it really ran), the rest is replanned as the rest of the same lot
  (never re-sized). A segment that made no piece before that minute is
  released whole.

The boundary travels with the plan's inputs (``EngineData.history_boundary``)
so every validation of that plan — in the calculation, at apply and at
commit — reads the same rule.
"""

from __future__ import annotations

import copy
import math
from typing import Any


def history_boundary(data) -> tuple[int, int] | None:
    """``(day, minute)`` before which the plan is history, or ``None``."""

    raw = getattr(data, "history_boundary", None) if data is not None else None
    if not raw:
        return None
    day, minute = int(raw[0]), int(raw[1])
    if day <= 0 and minute <= 0:
        return None
    return day, minute


def judged_start(day_idx: int, start_min: float, end_min: float, boundary) -> float | None:
    """First minute of a segment the inputs judge, ``None`` if none (history)."""

    if boundary is None:
        return start_min
    day, minute = boundary
    if day_idx < day:
        return None
    if day_idx > day:
        return start_min
    start = max(float(start_min), float(minute))
    return start if start < end_min else None


def is_history(day_idx: int, minute: float, boundary) -> bool:
    """Whether the instant ``(day_idx, minute)`` lies before the boundary."""

    return boundary is not None and (day_idx, minute) < boundary


def cut_values(
    start: float, end: float, setup: float, prod: float, qty: int,
    twin_outputs, at: float,
) -> dict[str, Any] | None:
    """Fields of a segment that stops at minute ``at`` (same day).

    The pieces made by then (production runs at a constant rate from the end
    of the setup), rounded down: a piece under way is not made. ``None`` when
    nothing was made by ``at`` (the segment is released whole). ``at`` at or
    after the end leaves the segment unchanged (``{}``).
    """

    if at >= end:
        return {}
    done = float(at) - float(start) - max(0.0, float(setup))
    if done <= 0 or prod <= 0 or qty <= 0:
        return None
    made = min(int(qty), int(math.floor(int(qty) * min(1.0, done / float(prod)) + 1e-9)))
    if made <= 0:
        return None
    values: dict[str, Any] = {
        "end_min": at,
        "qty": made,
        "prod_min": float(prod) * made / int(qty),
    }
    if twin_outputs:
        values["twin_outputs"] = [
            (side[0], side[1], int(side[2]) * made // int(qty)) for side in twin_outputs
        ]
    return values


def cut_segment(segment, at: float):
    """``segment`` stopped at minute ``at`` (a copy), or ``None`` (released)."""

    values = cut_values(
        segment.start_min, segment.end_min, segment.setup_min, segment.prod_min,
        segment.qty, segment.twin_outputs, at,
    )
    if values is None:
        return None
    part = copy.deepcopy(segment)
    for name, value in values.items():
        setattr(part, name, value)
    return part


def rest_of_cut(segment, part):
    """What a cut leaves of ``segment`` after ``part``: the same run going on."""

    rest = copy.deepcopy(segment)
    rest.start_min = part.end_min
    rest.setup_min = 0.0
    rest.is_continuation = True
    rest.qty = int(segment.qty) - int(part.qty)
    rest.prod_min = max(0.0, float(segment.prod_min) - float(part.prod_min))
    if segment.twin_outputs:
        made = {(side[0], side[1]): int(side[2]) for side in part.twin_outputs or []}
        rest.twin_outputs = [
            (side[0], side[1], int(side[2]) - made.get((side[0], side[1]), 0))
            for side in segment.twin_outputs
        ]
    return rest


def cut_row(row: dict, at: float) -> dict | None:
    """``cut_segment`` on a serialized segment (the commit guard's reading)."""

    values = cut_values(
        float(row["start_min"]), float(row["end_min"]), float(row.get("setup_min") or 0),
        float(row.get("prod_min") or 0), int(row.get("qty") or 0), row.get("twin_outputs"), at,
    )
    if values is None:
        return None
    if "twin_outputs" in values:
        values["twin_outputs"] = [list(side) for side in values["twin_outputs"]]
    return {**row, **values}
