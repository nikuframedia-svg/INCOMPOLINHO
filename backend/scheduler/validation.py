"""Hard physical validation for schedule plans."""

from __future__ import annotations

import math
from typing import Any

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.types import Segment
from backend.types import EngineData


class PlanValidationError(ValueError):
    """Raised when a schedule violates non-negotiable physical constraints."""

    def __init__(self, violations: list[dict[str, Any]]) -> None:
        self.violations = violations
        super().__init__(f"Plano invalido: {len(violations)} conflito(s) fisico(s).")


def _timing(config: FactoryConfig | None) -> tuple[int, int, int]:
    shift_a_start = config.shift_a_start if config else 420
    shift_b_end = config.shift_b_end if config else 1440
    day_cap = config.day_capacity_min if config else DAY_CAP
    return shift_a_start, shift_b_end, day_cap


def segment_abs(seg: Segment, config: FactoryConfig | None = None) -> tuple[float, float]:
    """Return absolute work-minute interval for a segment."""

    shift_a_start, _shift_b_end, day_cap = _timing(config)
    start_abs = seg.day_idx * day_cap + (seg.start_min - shift_a_start)
    end_abs = seg.day_idx * day_cap + (seg.end_min - shift_a_start)
    return start_abs, end_abs


def abs_to_day_min(abs_min: float, config: FactoryConfig | None = None) -> tuple[int, int]:
    """Convert absolute work-minute to (day_idx, minute-of-day)."""

    shift_a_start, _shift_b_end, day_cap = _timing(config)
    day = math.floor(abs_min / day_cap)
    offset = abs_min - day * day_cap
    return day, shift_a_start + int(math.ceil(offset))


def _violation(
    kind: str,
    message: str,
    seg: Segment | None = None,
    other: Segment | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"kind": kind, "message": message}
    if seg is not None:
        payload.update(
            {
                "lot_id": seg.lot_id,
                "run_id": seg.run_id,
                "machine_id": seg.machine_id,
                "tool_id": seg.tool_id,
                "day_idx": seg.day_idx,
                "start_min": seg.start_min,
                "end_min": seg.end_min,
            }
        )
    if other is not None:
        payload["other"] = {
            "lot_id": other.lot_id,
            "run_id": other.run_id,
            "machine_id": other.machine_id,
            "tool_id": other.tool_id,
            "day_idx": other.day_idx,
            "start_min": other.start_min,
            "end_min": other.end_min,
        }
    payload.update(extra)
    return payload


def validate_plan(
    segments: list[Segment],
    data: EngineData | None = None,
    config: FactoryConfig | None = None,
) -> list[dict[str, Any]]:
    """Return hard physical violations for a schedule plan."""

    violations: list[dict[str, Any]] = []
    active = [s for s in segments if s.end_min > s.start_min]
    shift_a_start, _shift_b_end, day_cap = _timing(config)

    for seg in segments:
        duration = seg.end_min - seg.start_min
        required = seg.prod_min + seg.setup_min
        if duration <= 0 or (required > 1.0 and duration < required - 1.0):
            violations.append(
                _violation(
                    "ghost_segment",
                    (
                        f"Segmento fantasma em {seg.machine_id}: "
                        f"{duration:.0f} min disponíveis para {required:.0f} min necessários."
                    ),
                    seg,
                    duration_min=duration,
                    required_min=required,
                )
            )

    machine_blocked = getattr(data, "machine_blocked_days", {}) if data else {}
    tool_blocked = getattr(data, "tool_blocked_days", {}) if data else {}

    for seg in active:
        if seg.day_idx in machine_blocked.get(seg.machine_id, set()):
            violations.append(
                _violation(
                    "machine_down",
                    f"Maquina {seg.machine_id} indisponivel no dia {seg.day_idx}.",
                    seg,
                )
            )
        if seg.day_idx in tool_blocked.get(seg.tool_id, set()):
            violations.append(
                _violation(
                    "tool_down",
                    f"Ferramenta {seg.tool_id} indisponivel no dia {seg.day_idx}.",
                    seg,
                )
            )

    by_machine: dict[str, list[Segment]] = {}
    for seg in active:
        by_machine.setdefault(seg.machine_id, []).append(seg)
    for machine_id, segs in by_machine.items():
        used_by_day: dict[int, float] = {}
        for seg in segs:
            used_by_day[seg.day_idx] = used_by_day.get(seg.day_idx, 0.0) + (
                seg.end_min - seg.start_min
            )
        for day_idx, used_min in used_by_day.items():
            if used_min > day_cap + 1.0:
                violations.append(
                    _violation(
                        "day_cap_violation",
                        (
                            f"Maquina {machine_id} excede capacidade diaria no dia {day_idx}: "
                            f"{used_min:.0f}/{day_cap} min."
                        ),
                        machine_id=machine_id,
                        day_idx=day_idx,
                        used_min=round(used_min, 1),
                        capacity_min=day_cap,
                    )
                )

        ordered = sorted(segs, key=lambda s: segment_abs(s, config)[0])
        for prev, curr in zip(ordered, ordered[1:]):
            prev_start, prev_end = segment_abs(prev, config)
            curr_start, curr_end = segment_abs(curr, config)
            if curr_start < prev_end - 0.01 and curr_end > prev_start + 0.01:
                violations.append(
                    _violation(
                        "machine_overlap",
                        f"Maquina {machine_id} com segmentos sobrepostos.",
                        curr,
                        prev,
                    )
                )

    by_tool: dict[str, list[Segment]] = {}
    for seg in active:
        by_tool.setdefault(seg.tool_id, []).append(seg)
    for tool_id, segs in by_tool.items():
        ordered = sorted(segs, key=lambda s: segment_abs(s, config)[0])
        for i, first in enumerate(ordered):
            first_start, first_end = segment_abs(first, config)
            for second in ordered[i + 1 :]:
                second_start, second_end = segment_abs(second, config)
                if second_start >= first_end - 0.01:
                    break
                if first.machine_id != second.machine_id and second_end > first_start + 0.01:
                    violations.append(
                        _violation(
                            "tool_conflict",
                            f"Ferramenta {tool_id} em duas maquinas ao mesmo tempo.",
                            second,
                            first,
                        )
                    )

    setup_entries: list[tuple[float, float, Segment]] = []
    for seg in active:
        if seg.setup_min <= 0:
            continue
        setup_start, _seg_end = segment_abs(seg, config)
        setup_end = setup_start + seg.setup_min
        setup_entries.append((setup_start, setup_end, seg))

    setup_entries.sort(key=lambda item: item[0])
    for i, (first_start, first_end, first_seg) in enumerate(setup_entries):
        for second_start, second_end, second_seg in setup_entries[i + 1 :]:
            if second_start >= first_end - 0.01:
                break
            if second_end > first_start + 0.01:
                overlap_start = max(first_start, second_start)
                day_idx, start_min = abs_to_day_min(overlap_start, config)
                violations.append(
                    _violation(
                        "setup_crew_overlap",
                        "Duas preparacoes usam a unica equipa de setup ao mesmo tempo.",
                        second_seg,
                        first_seg,
                        overlap_abs_start=round(overlap_start, 2),
                        overlap_day_idx=day_idx,
                        overlap_start_min=start_min,
                        first_setup_abs_start=round(first_start, 2),
                        first_setup_abs_end=round(first_end, 2),
                        second_setup_abs_start=round(second_start, 2),
                        second_setup_abs_end=round(second_end, 2),
                    )
                )

    by_run: dict[str, list[Segment]] = {}
    for seg in active:
        by_run.setdefault(seg.run_id, []).append(seg)
    for run_id, segs in by_run.items():
        setup_segs = [s for s in segs if s.setup_min > 0]
        if not setup_segs:
            continue
        setup = min(setup_segs, key=lambda s: segment_abs(s, config)[0])
        setup_start, _setup_end = segment_abs(setup, config)
        setup_done = setup_start + setup.setup_min
        for seg in segs:
            if seg is setup:
                continue
            seg_start, _seg_end = segment_abs(seg, config)
            if seg_start < setup_done - 0.01:
                violations.append(
                    _violation(
                        "run_setup_order",
                        f"Run {run_id} produz antes do setup terminar.",
                        seg,
                        setup,
                        setup_done=setup_done,
                    )
                )

    return violations


def hard_gate_metrics(violations: list[dict[str, Any]]) -> dict[str, int]:
    """Aggregate physical validation violations into public hard-gate metrics."""

    counts: dict[str, int] = {
        "setup_crew_overlaps": 0,
        "machine_overlaps": 0,
        "tool_conflicts": 0,
        "day_cap_violations": 0,
        "blocked_machine_segments": 0,
        "blocked_tool_segments": 0,
        "ghost_segments": 0,
        "run_setup_order_violations": 0,
    }
    mapping = {
        "setup_crew_overlap": "setup_crew_overlaps",
        "machine_overlap": "machine_overlaps",
        "tool_conflict": "tool_conflicts",
        "day_cap_violation": "day_cap_violations",
        "machine_down": "blocked_machine_segments",
        "tool_down": "blocked_tool_segments",
        "ghost_segment": "ghost_segments",
        "run_setup_order": "run_setup_order_violations",
    }
    for violation in violations:
        key = mapping.get(str(violation.get("kind")))
        if key:
            counts[key] += 1
    return counts


def validate_plan_metrics(
    segments: list[Segment],
    data: EngineData | None = None,
    config: FactoryConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return hard physical violations and their public metric counters."""

    violations = validate_plan(segments, data, config)
    return violations, hard_gate_metrics(violations)


def assert_plan_valid(
    segments: list[Segment],
    data: EngineData | None = None,
    config: FactoryConfig | None = None,
) -> None:
    """Raise PlanValidationError if a plan has hard physical violations."""

    violations = validate_plan(segments, data, config)
    if violations:
        raise PlanValidationError(violations)
