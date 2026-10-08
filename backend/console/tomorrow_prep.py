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


def _find_previous_tool(
    segments: list[Segment],
    machine_id: str,
    day_idx: int,
    start_min: int,
    initial_tools: dict[str, str] | None = None,
) -> str | None:
    """Tool really mounted immediately before a setup."""
    prev_segs = [
        s
        for s in segments
        if s.machine_id == machine_id
        and (s.day_idx < day_idx or (s.day_idx == day_idx and s.start_min < start_min))
    ]
    if not prev_segs:
        return (initial_tools or {}).get(machine_id)
    return max(prev_segs, key=lambda s: (s.day_idx, s.end_min)).tool_id


def check_crew_bottleneck(
    segments: list[Segment],
    day_idx: int,
    window_min: int = 120,
    *,
    config: FactoryConfig | None = None,
) -> list[dict]:
    """Use the physical validator's overlap and group-capacity rules.

    ``window_min`` remains accepted for compatibility; nearby sequential
    setups are not simultaneous and do not imply crew overload.
    """
    from backend.scheduler.validation import validate_plan

    config = config or FactoryConfig()
    setups = [s for s in segments if s.day_idx == day_idx and s.setup_min > 0]
    conflicts = {}
    for violation in validate_plan(setups, config=config):
        if violation["kind"] != "setup_crew_overlap":
            continue
        group, start = violation["setup_group"], violation["overlap_start_min"]
        concurrent = [s for s in setups
                      if config.machine_groups.get(s.machine_id, "Grandes") == group
                      and s.start_min <= start < s.start_min + s.setup_min]
        capacity = violation["setup_capacity"]
        ends = sorted(s.start_min + s.setup_min for s in concurrent)
        conflicts[(group, start)] = {
            "time": _min_to_time(start), "simultaneous": len(concurrent),
            "machines": sorted({s.machine_id for s in concurrent}),
            "wait_min": round(ends[len(concurrent) - capacity - 1] - start, 1),
        }
    return list(conflicts.values())


def compute_day_setups(
    segments: list[Segment],
    day_idx: int,
    engine_data: EngineData | None = None,
) -> list[dict]:
    """Return setup work for one day, including the responsible shift."""
    setup_segs = sorted(
        [s for s in segments if s.day_idx == day_idx and s.setup_min > 0],
        key=lambda s: s.start_min,
    )
    setups = []
    initial_tools = {
        item.machine_id: item.tool_id
        for item in (engine_data.current_machine_states if engine_data else [])
        if item.tool_id
    }
    for segment in setup_segs:
        previous = _find_previous_tool(
            segments,
            segment.machine_id,
            day_idx,
            segment.start_min,
            initial_tools,
        )
        setups.append(
            {
                "time": _min_to_time(segment.start_min),
                "start_min": segment.start_min,
                "shift": segment.shift or ("A" if segment.start_min < 930 else "B"),
                "machine": segment.machine_id,
                "from_tool": previous if previous != segment.tool_id else None,
                "to_tool": segment.tool_id,
                "sku": segment.sku,
                "duration_min": round(segment.setup_min, 1),
                "already_mounted": previous is not None and previous == segment.tool_id,
            }
        )
    return setups


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
    # ── Setups ──
    setups = compute_day_setups(segments, day_idx, engine_data)

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

    crew = check_crew_bottleneck(segments, day_idx, config=config)
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
