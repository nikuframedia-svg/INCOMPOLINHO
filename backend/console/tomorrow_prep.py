"""Tomorrow prep — Spec 11 §4.3.

What the encarregado needs to know: setups, operators, expeditions, problems.
"""

from __future__ import annotations

from collections import defaultdict

from backend.analytics.expedition import compute_expedition
from backend.config.loader import _min_to_time
from backend.config.types import FactoryConfig
from backend.scheduler.operators import compute_operator_alerts
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData


def _find_previous_tool(segments: list[Segment], machine_id: str, day_idx: int) -> str | None:
    """Last tool_id on this machine the day before."""
    prev_segs = [s for s in segments if s.machine_id == machine_id and s.day_idx == day_idx - 1]
    if not prev_segs:
        return None
    return max(prev_segs, key=lambda s: s.end_min).tool_id


def check_crew_bottleneck(
    segments: list[Segment],
    day_idx: int,
    window_min: int = 120,
) -> list[dict]:
    """Detect >=3 setups within a time window on the same day.

    Returns list of {"time": str, "simultaneous": int, "machines": [...], "wait_min": float}.
    """
    setup_segs = sorted(
        [s for s in segments if s.day_idx == day_idx and s.setup_min > 0],
        key=lambda s: s.start_min,
    )

    if len(setup_segs) < 3:
        return []

    conflicts = []
    seen = set()

    for i, s in enumerate(setup_segs):
        if i in seen:
            continue
        # Setup starts approximately at start_min (post-setup, but close enough)
        nearby = [s]
        nearby_idx = [i]
        for j, s2 in enumerate(setup_segs):
            if j == i or j in seen:
                continue
            if abs(s2.start_min - s.start_min) < window_min:
                nearby.append(s2)
                nearby_idx.append(j)

        if len(nearby) >= 3:
            for idx in nearby_idx:
                seen.add(idx)
            total_setup = sum(ns.setup_min for ns in nearby)
            conflicts.append(
                {
                    "time": _min_to_time(s.start_min),
                    "simultaneous": len(nearby),
                    "machines": [ns.machine_id for ns in nearby],
                    "wait_min": round(total_setup - max(ns.setup_min for ns in nearby), 1),
                }
            )

    return conflicts


def compute_tomorrow_prep(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    config: FactoryConfig,
    day_idx: int = 1,
) -> dict:
    """Return tomorrow preparation summary.

    Keys: date, setups, operators, expeditions_summary, problems, ok.
    """
    segs_day = [s for s in segments if s.day_idx == day_idx]

    # ── Setups ──
    setup_segs = sorted(
        [s for s in segs_day if s.setup_min > 0],
        key=lambda s: s.start_min,
    )
    setups = []
    for s in setup_segs:
        prev = _find_previous_tool(segments, s.machine_id, day_idx)
        already_mounted = prev is not None and prev == s.tool_id
        setups.append(
            {
                "time": _min_to_time(s.start_min),
                "machine": s.machine_id,
                "from_tool": prev,
                "to_tool": s.tool_id,
                "duration_min": round(s.setup_min, 1),
                "already_mounted": already_mounted,
            }
        )

    # ── Operators ──
    op_alerts = compute_operator_alerts(segments, engine_data, config)
    day_alerts = [a for a in op_alerts if a.day_idx == day_idx]
    operators = [
        {
            "shift": a.shift,
            "group": a.machine_group,
            "required": a.required,
            "available": a.available,
            "deficit": a.deficit,
        }
        for a in day_alerts
    ]

    # ── Expeditions summary ──
    exp = compute_expedition(segments, lots, engine_data)
    tomorrow_exp = next((d for d in exp.days if d.day_idx == day_idx), None)
    exp_summary = ""
    if tomorrow_exp and tomorrow_exp.entries:
        by_c: dict[str, int] = defaultdict(int)
        for e in tomorrow_exp.entries:
            by_c[e.client] += 1
        parts = [f"{c} ×{n}" for c, n in sorted(by_c.items())]
        exp_summary = f"{len(tomorrow_exp.entries)} ({', '.join(parts)})"

    # ── Problems ──
    problems = []
    for a in day_alerts:
        if a.deficit > 0:
            pl = "m" if a.deficit > 1 else ""
            ps = "es" if a.deficit > 1 else ""
            problems.append(f"Falta{pl} {a.deficit} operador{ps} {a.machine_group} turno {a.shift}")

    crew = check_crew_bottleneck(segments, day_idx)
    for c in crew:
        problems.append(
            f"{c['simultaneous']} setups próximos às {c['time']} ({', '.join(c['machines'])})"
        )

    # ── Date ──
    date = ""
    if day_idx < len(engine_data.workdays):
        date = engine_data.workdays[day_idx]

    return {
        "date": date,
        "setups": setups,
        "operators": operators,
        "expeditions_summary": exp_summary,
        "problems": problems,
        "ok": len(problems) == 0,
    }
