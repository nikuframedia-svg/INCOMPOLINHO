"""Hard physical validation for schedule plans."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.calendar import is_factory_workday
from backend.config.shifts import (
    clock_to_productive_offset,
    productive_offset_to_clock,
)
from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.jit_policy import calendar_holidays, earliest_allowed_start
from backend.scheduler.setup_identity import segment_setup_identity
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData


class PlanValidationError(ValueError):
    """Raised when a schedule violates non-negotiable plan constraints."""

    def __init__(self, violations: list[dict[str, Any]]) -> None:
        self.violations = violations
        super().__init__(f"Plano invalido: {len(violations)} conflito(s) de plano.")


def _timing(config: FactoryConfig | None) -> tuple[int, int, int]:
    shift_a_start = config.shift_a_start if config else 420
    shift_b_end = config.shift_b_end if config else 1440
    day_cap = config.day_capacity_min if config else DAY_CAP
    return shift_a_start, shift_b_end, day_cap


def _work_minute_offset(minute: float, config: FactoryConfig | None) -> float:
    """Map a wall-clock minute to its compressed productive-day offset.

    Factory time deliberately removes closed periods, including pauses between
    shifts.  The old ``minute - shift_a_start`` shortcut only worked while all
    shifts touched.  Once a user introduced a break, the last minutes of one
    day overlapped the first minutes of the next in the compressed timeline.
    """

    if config is None or not config.shifts:
        return float(minute) - 420.0

    return float(clock_to_productive_offset(config, minute))


def _work_offset_to_minute(offset: float, config: FactoryConfig | None) -> int:
    """Inverse of :func:`_work_minute_offset` for one productive day."""

    if config is None or not config.shifts:
        return 420 + int(math.ceil(offset))

    return productive_offset_to_clock(
        config,
        math.ceil(max(0.0, float(offset))),
        boundary="start",
    )


def segment_abs(seg: Segment, config: FactoryConfig | None = None) -> tuple[float, float]:
    """Return absolute work-minute interval for a segment."""

    _shift_a_start, _shift_b_end, day_cap = _timing(config)
    start_abs = seg.day_idx * day_cap + _work_minute_offset(seg.start_min, config)
    end_abs = seg.day_idx * day_cap + _work_minute_offset(seg.end_min, config)
    return start_abs, end_abs


def abs_to_day_min(abs_min: float, config: FactoryConfig | None = None) -> tuple[int, int]:
    """Convert absolute work-minute to (day_idx, minute-of-day)."""

    _shift_a_start, _shift_b_end, day_cap = _timing(config)
    day = math.floor(abs_min / day_cap)
    offset = abs_min - day * day_cap
    return day, _work_offset_to_minute(offset, config)


def _setup_is_immediately_followed_by_production(
    setup: Segment,
    production: Segment,
    active: list[Segment],
    data: EngineData | None,
    config: FactoryConfig | None,
) -> bool:
    """Return whether a setup-only block is adjacent in factory work-time.

    A setup may end at the final shift boundary and production may begin at
    the first minute of the next factory workday.  Calendar-closed time in
    between is not an operational gap, but another productive workday or any
    intervening use of the machine is.
    """

    shift_a_start, shift_b_end, _day_cap = _timing(config)
    if setup.day_idx == production.day_idx:
        adjacent = setup.end_min == production.start_min
    else:
        adjacent = setup.end_min == shift_b_end and production.start_min == shift_a_start
        if adjacent:
            if data is None:
                adjacent = production.day_idx == setup.day_idx + 1
            else:
                adjacent = all(
                    not is_factory_workday(day, data, config)
                    for day in range(setup.day_idx + 1, production.day_idx)
                )
    if not adjacent:
        return False

    setup_start, _setup_end = segment_abs(setup, config)
    _production_start, production_end = segment_abs(production, config)
    return not any(
        segment is not setup
        and segment is not production
        and segment.machine_id == setup.machine_id
        and segment.end_min > segment.start_min
        and segment_abs(segment, config)[0] < production_end
        and setup_start < segment_abs(segment, config)[1]
        for segment in active
    )


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


def required_setup_minutes(
    segment: Segment,
    lots_by_id: dict[str, Lot] | None = None,
) -> float:
    """Return the known physical setup requirement for a segment's tool."""

    lot = (lots_by_id or {}).get(segment.lot_id)
    return max(
        0.0,
        float(segment.run_setup_min or 0.0),
        float(lot.setup_min if lot is not None else 0.0),
    )


def _factory_work_adjacent(
    previous: Segment,
    following: Segment,
    data: EngineData | None,
    config: FactoryConfig | None,
) -> bool:
    """Return whether two blocks touch in usable factory time."""

    shift_a_start, shift_b_end, _day_cap = _timing(config)
    if previous.day_idx == following.day_idx:
        return abs(float(previous.end_min) - float(following.start_min)) <= 0.01
    if (
        int(previous.end_min) != int(shift_b_end)
        or int(following.start_min) != int(shift_a_start)
    ):
        return False
    if data is None:
        return following.day_idx == previous.day_idx + 1
    return all(
        not is_factory_workday(day_idx, data, config)
        for day_idx in range(previous.day_idx + 1, following.day_idx)
    )


def _transition_setup_minutes(
    ordered_machine_segments: list[Segment],
    transition_index: int,
    data: EngineData | None,
    config: FactoryConfig | None,
) -> float:
    """Sum the complete contiguous setup attached to one tool transition."""

    first = ordered_machine_segments[transition_index]
    total = 0.0
    previous: Segment | None = None
    for segment in ordered_machine_segments[transition_index:]:
        if (
            segment.machine_id != first.machine_id
            or segment.run_id != first.run_id
            or segment.tool_id != first.tool_id
            or (
                previous is not None
                and not _factory_work_adjacent(previous, segment, data, config)
            )
        ):
            break
        total += max(0.0, float(segment.setup_min))
        previous = segment
        if segment.prod_min > 0:
            break
    return total


def validate_plan(
    segments: list[Segment],
    data: EngineData | None = None,
    config: FactoryConfig | None = None,
    lots: list[Lot] | None = None,
) -> list[dict[str, Any]]:
    """Return hard physical violations for a schedule plan."""
    if data is not None:
        from backend.transform.calendars import calendar_window

        data = calendar_window(data, config, max((s.day_idx for s in segments), default=0))

    violations: list[dict[str, Any]] = []
    active = [s for s in segments if s.end_min > s.start_min]
    from backend.scheduler.canonical import source_contract_violations

    violations.extend(source_contract_violations(segments, lots, data, config))
    shift_a_start, _shift_b_end, day_cap = _timing(config)
    # The plan and shifts are immutable during one validation pass.
    intervals = {id(segment): segment_abs(segment, config) for segment in active}

    def interval(segment: Segment) -> tuple[float, float]:
        return intervals[id(segment)]

    lots_by_id = {lot.id: lot for lot in (lots or [])}
    ops_by_id = {op.id: op for op in data.ops} if data is not None else {}
    known_machines = {machine.id for machine in data.machines} if data is not None else set()
    known_tools = {op.t for op in data.ops} if data is not None else set()
    if config is not None:
        known_machines.update(config.machines)
        known_tools.update(config.tools)
    material_holidays = (
        calendar_holidays(
            data,
            min((segment.day_idx for segment in segments), default=0) - 7,
            data.n_days + 7,
        )
        if data is not None and lots_by_id
        else set()
    )

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
        if config is not None and not any(
            int(shift.start_min) <= int(seg.start_min)
            and int(seg.end_min) <= int(shift.end_min)
            for shift in config.shifts
        ):
            violations.append(
                _violation(
                    "outside_shift",
                    (
                        f"Segmento em {seg.machine_id} fica fora de um turno "
                        f"produtivo: {seg.start_min}-{seg.end_min}."
                    ),
                    seg,
                )
            )

    machine_blocked = getattr(data, "machine_blocked_days", {}) if data else {}
    tool_blocked = getattr(data, "tool_blocked_days", {}) if data else {}
    machine_intervals = getattr(data, "machine_blocked_intervals", {}) if data else {}
    tool_intervals = getattr(data, "tool_blocked_intervals", {}) if data else {}

    for seg in active:
        if known_machines and seg.machine_id not in known_machines:
            violations.append(
                _violation(
                    "unknown_machine",
                    f"Máquina desconhecida no plano: {seg.machine_id}.",
                    seg,
                )
            )
        if known_tools and seg.tool_id not in known_tools:
            violations.append(
                _violation(
                    "unknown_tool",
                    f"Ferramenta desconhecida no plano: {seg.tool_id}.",
                    seg,
                )
            )
        lot = lots_by_id.get(seg.lot_id)
        if lot is not None:
            lot_op_ids = (
                [str(op_id) for op_id, _sku, _qty in lot.twin_outputs]
                if lot.twin_outputs
                else [lot.op_id]
            )
            lot_ops = [ops_by_id[op_id] for op_id in lot_op_ids if op_id in ops_by_id]
            eligible_machines = {
                machine
                for op in lot_ops
                for machine in (op.m, op.alt)
                if machine
            } or {machine for machine in (lot.machine_id, lot.alt_machine_id) if machine}
            eligible_tools = {op.t for op in lot_ops} or {lot.tool_id}
            if seg.machine_id not in eligible_machines:
                violations.append(
                    _violation(
                        "ineligible_machine",
                        (
                            f"Lote {lot.id} não é elegível para a máquina "
                            f"{seg.machine_id}."
                        ),
                        seg,
                        eligible_machines=sorted(eligible_machines),
                    )
                )
            if seg.tool_id not in eligible_tools or seg.tool_id != lot.tool_id:
                violations.append(
                    _violation(
                        "ineligible_tool",
                        (
                            f"Lote {lot.id} não é elegível para a ferramenta "
                            f"{seg.tool_id}."
                        ),
                        seg,
                        eligible_tools=sorted(eligible_tools),
                    )
                )
        machine_cfg = config.machines.get(seg.machine_id) if config else None
        if machine_cfg is not None and not machine_cfg.active:
            violations.append(
                _violation(
                    "machine_down",
                    f"Maquina {seg.machine_id} inativa.",
                    seg,
                )
            )
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
        for block in (
            []
            if seg.day_idx in machine_blocked.get(seg.machine_id, set())
            else machine_intervals.get(seg.machine_id, [])
        ):
            if (
                int(block.get("start_day", -1)) == seg.day_idx
                and seg.start_min < int(block.get("end_min", 0))
                and seg.end_min > int(block.get("start_min", 0))
            ):
                violations.append(
                    _violation(
                        "machine_down",
                        (
                            f"Maquina {seg.machine_id} indisponivel entre "
                            f"{block.get('start_min')} e {block.get('end_min')}."
                        ),
                        seg,
                        unavailability=block,
                    )
                )
        for block in (
            []
            if seg.day_idx in tool_blocked.get(seg.tool_id, set())
            else tool_intervals.get(seg.tool_id, [])
        ):
            if (
                int(block.get("start_day", -1)) == seg.day_idx
                and seg.start_min < int(block.get("end_min", 0))
                and seg.end_min > int(block.get("start_min", 0))
            ):
                violations.append(
                    _violation(
                        "tool_down",
                        (
                            f"Ferramenta {seg.tool_id} indisponivel entre "
                            f"{block.get('start_min')} e {block.get('end_min')}."
                        ),
                        seg,
                        unavailability=block,
                    )
                )

    productive_minutes_by_lot: dict[str, float] = {}
    for seg in active:
        productive_minutes_by_lot[seg.lot_id] = (
            productive_minutes_by_lot.get(seg.lot_id, 0.0)
            + max(0.0, float(seg.prod_min))
        )
    for lot_id, actual_prod_min in productive_minutes_by_lot.items():
        lot = lots_by_id.get(lot_id)
        if lot is None:
            continue
        expected_prod_min = max(0.0, float(lot.prod_min))
        tolerance = max(1.0, expected_prod_min * 0.01)
        if abs(actual_prod_min - expected_prod_min) > tolerance:
            violations.append(
                {
                    "kind": "lot_production_minutes",
                    "message": (
                        f"Lote {lot_id}: segmentos representam {actual_prod_min:.1f} "
                        f"de {expected_prod_min:.1f} min de produção."
                    ),
                    "lot_id": lot_id,
                    "actual_prod_min": round(actual_prod_min, 3),
                    "expected_prod_min": round(expected_prod_min, 3),
                }
            )

    by_machine: dict[str, list[Segment]] = {}
    for seg in active:
        by_machine.setdefault(seg.machine_id, []).append(seg)
    ordered_by_machine: dict[str, list[Segment]] = {}
    transition_setup_by_segment: dict[int, float] = {}
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

        ordered = sorted(segs, key=lambda s: interval(s)[0])
        ordered_by_machine[machine_id] = ordered
        for index, (prev, curr) in enumerate(zip(ordered, ordered[1:]), start=1):
            prev_start, prev_end = interval(prev)
            curr_start, curr_end = interval(curr)
            if curr_start < prev_end - 0.01 and curr_end > prev_start + 0.01:
                violations.append(
                    _violation(
                        "machine_overlap",
                        f"Maquina {machine_id} com segmentos sobrepostos.",
                        curr,
                        prev,
                    )
                )
            required_setup = required_setup_minutes(curr, lots_by_id)
            actual_setup = _transition_setup_minutes(
                ordered,
                index,
                data,
                config,
            )
            transition_setup_by_segment[id(curr)] = actual_setup
            if (
                segment_setup_identity(curr) != segment_setup_identity(prev)
                and actual_setup + 0.01 < required_setup
            ):
                kind = (
                    "missing_tool_change_setup"
                    if actual_setup <= 0.01
                    else "insufficient_tool_change_setup"
                )
                violations.append(
                    _violation(
                        kind,
                        (
                            f"Afinação {segment_setup_identity(curr)} entra em {machine_id} "
                            f"depois de {segment_setup_identity(prev)}, com {actual_setup:.0f} de "
                            f"{required_setup:.0f} min de setup."
                        ),
                        curr,
                        prev,
                        actual_setup_min=actual_setup,
                        required_setup_min=required_setup,
                        transition="machine_setup_change",
                    )
                )

    by_tool: dict[str, list[Segment]] = {}
    for seg in active:
        by_tool.setdefault(seg.tool_id, []).append(seg)
    for tool_id, segs in by_tool.items():
        ordered = sorted(segs, key=lambda s: interval(s)[0])
        for i, first in enumerate(ordered):
            first_start, first_end = interval(first)
            for second in ordered[i + 1 :]:
                second_start, second_end = interval(second)
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
        for previous, current in zip(ordered, ordered[1:]):
            machine_ordered = ordered_by_machine.get(current.machine_id, [])
            machine_index = next(
                (
                    index
                    for index, segment in enumerate(machine_ordered)
                    if segment is current
                ),
                None,
            )
            actual_setup = transition_setup_by_segment.get(id(current))
            if actual_setup is None and machine_index is not None:
                actual_setup = _transition_setup_minutes(
                    machine_ordered,
                    machine_index,
                    data,
                    config,
                )
            actual_setup = float(actual_setup or 0.0)
            required_setup = required_setup_minutes(current, lots_by_id)
            if (
                previous.machine_id != current.machine_id
                and actual_setup + 0.01 < required_setup
                and not any(
                    violation.get("kind")
                    in {
                        "missing_tool_change_setup",
                        "insufficient_tool_change_setup",
                    }
                    and violation.get("lot_id") == current.lot_id
                    and violation.get("run_id") == current.run_id
                    and violation.get("day_idx") == current.day_idx
                    and violation.get("start_min") == current.start_min
                    for violation in violations
                )
            ):
                kind = (
                    "missing_tool_change_setup"
                    if actual_setup <= 0.01
                    else "insufficient_tool_change_setup"
                )
                violations.append(
                    _violation(
                        kind,
                        (
                            f"Ferramenta {tool_id} regressa de "
                            f"{previous.machine_id} para {current.machine_id} com "
                            f"{actual_setup:.0f} de {required_setup:.0f} min de setup."
                        ),
                        current,
                        previous,
                        actual_setup_min=actual_setup,
                        required_setup_min=required_setup,
                        transition="tool_machine_change",
                    )
                )

    setup_entries: list[tuple[float, float, Segment]] = []
    for seg in active:
        if seg.setup_min <= 0:
            continue
        lot = lots_by_id.get(seg.lot_id)
        if lot is not None:
            material_floor = max(0, earliest_allowed_start(lot, material_holidays))
            if seg.day_idx < material_floor:
                violations.append(
                    _violation(
                        "setup_before_material",
                        (
                            f"Setup de {seg.tool_id} começa no dia {seg.day_idx}, "
                            f"antes da disponibilidade de material no dia {material_floor}."
                        ),
                        seg,
                        material_floor_day=material_floor,
                    )
                )
        setup_start, _seg_end = interval(seg)
        setup_end = setup_start + seg.setup_min
        setup_entries.append((setup_start, setup_end, seg))

    machine_groups = config.machine_groups if config else {}
    from backend.scheduler.resources import reserved_setup_segments

    for fixed in reserved_setup_segments(data):
        start, _ = segment_abs(fixed, config)
        setup_entries.append((start, start + fixed.setup_min, fixed))
    setup_by_group: dict[str, list[tuple[float, int, Segment, float]]] = {}
    for start, end, segment in setup_entries:
        group = machine_groups.get(segment.machine_id, "Grandes")
        setup_by_group.setdefault(group, []).extend(
            [(start, 1, segment, end), (end, -1, segment, start)]
        )
    for group, events in setup_by_group.items():
        capacity = (
            max(1, int(config.setup_crews_by_group.get(group, 1)))
            if config
            else 1
        )
        active_setups: list[tuple[Segment, float, float]] = []
        for instant, delta, segment, other_end in sorted(
            events,
            key=lambda item: (item[0], item[1]),
        ):
            if delta < 0:
                active_setups = [
                    entry for entry in active_setups if entry[0] is not segment
                ]
                continue
            active_setups.append((segment, instant, other_end))
            if len(active_setups) <= capacity:
                continue
            first_seg, first_start, first_end = active_setups[0]
            day_idx, start_min = abs_to_day_min(instant, config)
            violations.append(
                _violation(
                    "setup_crew_overlap",
                    (
                        f"{len(active_setups)} preparacoes usam {capacity} "
                        f"equipa(s) de setup de {group} ao mesmo tempo."
                    ),
                    segment,
                    first_seg,
                    overlap_abs_start=round(instant, 2),
                    overlap_day_idx=day_idx,
                    overlap_start_min=start_min,
                    first_setup_abs_start=round(first_start, 2),
                    first_setup_abs_end=round(first_end, 2),
                    second_setup_abs_start=round(instant, 2),
                    second_setup_abs_end=round(other_end, 2),
                    setup_group=group,
                    setup_capacity=capacity,
                    setup_demand=len(active_setups),
                )
            )

    if data is not None:
        from backend.scheduler.operators import compute_operator_alerts

        for alert in compute_operator_alerts(segments, data, config):
            violations.append(
                _violation(
                    "operator_capacity",
                    (
                        f"{alert.machine_group} turno {alert.shift}: "
                        f"{alert.required} operadores para {alert.available} disponíveis."
                    ),
                    day_idx=alert.day_idx,
                    group=alert.machine_group,
                    shift=alert.shift,
                    required=alert.required,
                    available=alert.available,
                    deficit=alert.deficit,
                )
            )

    by_run: dict[str, list[Segment]] = {}
    for seg in active:
        by_run.setdefault(seg.run_id, []).append(seg)
    for run_id, segs in by_run.items():
        setup_segs = sorted(
            (s for s in segs if s.setup_min > 0),
            key=lambda s: interval(s)[0],
        )
        if not setup_segs:
            continue
        setup = setup_segs[0]
        productive = sorted(
            (s for s in segs if s.prod_min > 0 and s.end_min > s.start_min),
            key=lambda s: interval(s)[0],
        )
        if not productive:
            violations.append(
                _violation(
                    "detached_setup",
                    f"Run {run_id} tem setup sem produção associada.",
                    setup,
                )
            )
            continue

        fragments_contiguous = True
        for previous, following in zip(setup_segs, setup_segs[1:]):
            if (
                previous.prod_min > 0
                or not _factory_work_adjacent(previous, following, data, config)
            ):
                fragments_contiguous = False
                break

        final_setup = setup_segs[-1]
        final_setup_start, _final_setup_end = interval(final_setup)
        setup_done = final_setup_start + final_setup.setup_min
        first_production_start, _first_production_end = interval(productive[0])
        first_production_start += productive[0].setup_min
        setup_attached = (
            final_setup is productive[0]
            and abs(first_production_start - setup_done) <= 0.01
        ) or (
            final_setup is not productive[0]
            and _setup_is_immediately_followed_by_production(
                final_setup,
                productive[0],
                active,
                data,
                config,
            )
        )
        if not fragments_contiguous or not setup_attached:
            violations.append(
                _violation(
                    "detached_setup",
                    (
                        f"Run {run_id} tem setup separado da primeira "
                        "produção por tempo fabril utilizável."
                    ),
                    setup,
                    productive[0],
                )
            )

        for seg in productive:
            seg_start, _seg_end = interval(seg)
            production_start = seg_start + seg.setup_min
            if production_start < setup_done - 0.01:
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
        "outside_shift_segments": 0,
        "unknown_machine_segments": 0,
        "unknown_tool_segments": 0,
        "ineligible_machine_segments": 0,
        "ineligible_tool_segments": 0,
        "lot_production_minute_violations": 0,
        "source_contract_violations": 0,
        "run_setup_order_violations": 0,
        "detached_setup_violations": 0,
        "setup_production_discontinuity_violations": 0,
        "operator_capacity_violations": 0,
        "setup_before_material_violations": 0,
        "missing_tool_change_setup_violations": 0,
        "insufficient_tool_change_setup_violations": 0,
        "plan_anchor_violations": 0,
    }
    mapping = {
        "setup_crew_overlap": "setup_crew_overlaps",
        "machine_overlap": "machine_overlaps",
        "tool_conflict": "tool_conflicts",
        "day_cap_violation": "day_cap_violations",
        "machine_down": "blocked_machine_segments",
        "tool_down": "blocked_tool_segments",
        "ghost_segment": "ghost_segments",
        "outside_shift": "outside_shift_segments",
        "unknown_machine": "unknown_machine_segments",
        "unknown_tool": "unknown_tool_segments",
        "ineligible_machine": "ineligible_machine_segments",
        "ineligible_tool": "ineligible_tool_segments",
        "lot_production_minutes": "lot_production_minute_violations",
        "source_contract": "source_contract_violations",
        "run_setup_order": "run_setup_order_violations",
        "detached_setup": "detached_setup_violations",
        "setup_production_discontinuity": "setup_production_discontinuity_violations",
        "operator_capacity": "operator_capacity_violations",
        "setup_before_material": "setup_before_material_violations",
        "missing_tool_change_setup": "missing_tool_change_setup_violations",
        "insufficient_tool_change_setup": (
            "insufficient_tool_change_setup_violations"
        ),
        "plan_anchor": "plan_anchor_violations",
    }
    for violation in violations:
        key = mapping.get(str(violation.get("kind")))
        if key:
            counts[key] += 1
    return counts


def plan_anchor_violations(
    segments: list[Segment], data: EngineData | None, config: FactoryConfig | None,
) -> list[dict[str, Any]]:
    """A saved manual position must survive every later plan calculation."""

    if data is None or not data.plan_anchors:
        return []
    timezone = ZoneInfo(config.timezone if config is not None else "Europe/Lisbon")
    day_by_date = {str(value)[:10]: day for day, value in enumerate(data.workdays)}
    first_by_lot: dict[str, Segment] = {}
    for segment in sorted(segments, key=lambda item: (item.day_idx, item.start_min)):
        if segment.prod_min > 0:
            first_by_lot.setdefault(segment.lot_id, segment)
    violations = []
    for anchor in data.plan_anchors:
        try:
            expected_at = datetime.fromisoformat(anchor.start_at)
            if expected_at.tzinfo is None:
                expected_at = expected_at.replace(tzinfo=timezone)
            expected_at = expected_at.astimezone(timezone)
            expected_day = day_by_date[expected_at.date().isoformat()]
        except (ValueError, KeyError):
            violations.append({
                "kind": "plan_anchor", "lot_id": anchor.lot_id,
                "message": f"Posição manual inválida para o lote {anchor.lot_id}.",
            })
            continue
        actual = first_by_lot.get(anchor.lot_id)
        expected_min = expected_at.hour * 60 + expected_at.minute
        if (
            actual is None
            or actual.machine_id != anchor.machine_id
            or actual.day_idx != expected_day
            or abs(actual.start_min + actual.setup_min - expected_min) > 0.01
        ):
            violations.append({
                "kind": "plan_anchor", "lot_id": anchor.lot_id,
                "machine_id": anchor.machine_id, "day_idx": expected_day,
                "message": (
                    f"A posição manual do lote {anchor.lot_id} em {anchor.machine_id} "
                    f"no dia {expected_day} às {expected_min // 60:02d}:"
                    f"{expected_min % 60:02d} não foi respeitada."
                ),
            })
    return violations


def coverage_metrics(segments: list[Segment], lots: list[Lot]) -> dict[str, int]:
    """Measure lot/output conservation without hiding partially scheduled work.

    Twin lots are accounted by operation output, not by the synthetic primary
    quantity carried by ``Segment.qty``.  This prevents a twin output from
    being counted twice and makes rounding losses in split segments visible.
    """

    lots_by_id = {lot.id: lot for lot in lots}
    expected_by_lot: dict[str, dict[str, int]] = {}
    twin_output_mismatches = 0
    for lot in lots:
        if lot.is_twin:
            outputs = lot.twin_outputs or []
            quantities = [int(qty) for _op_id, _sku, qty in outputs]
            op_ids = {str(op_id) for op_id, _sku, _qty in outputs}
            if (
                len(outputs) != 2
                or len(op_ids) != 2
                or any(qty <= 0 for qty in quantities)
                or len(set(quantities)) != 1
            ):
                twin_output_mismatches += 1
        elif lot.twin_outputs:
            twin_output_mismatches += 1

        if lot.twin_outputs is not None:
            expected_by_lot[lot.id] = {
                op_id: int(qty) for op_id, _sku, qty in lot.twin_outputs
            }
        else:
            expected_by_lot[lot.id] = {lot.op_id: int(lot.qty)}

    produced_by_lot: dict[str, dict[str, int]] = {}
    productive_lots: set[str] = set()
    unexpected_lot_ids: set[str] = set()

    for segment in segments:
        if segment.prod_min <= 0:
            continue
        productive_lots.add(segment.lot_id)
        lot = lots_by_id.get(segment.lot_id)
        if lot is None:
            unexpected_lot_ids.add(segment.lot_id)
            continue

        actual = produced_by_lot.setdefault(segment.lot_id, {})
        if lot.twin_outputs is not None:
            if segment.twin_outputs is None:
                twin_output_mismatches += 1
                continue
            expected_ops = set(expected_by_lot[lot.id])
            actual_ops = {op_id for op_id, _sku, _qty in segment.twin_outputs}
            segment_quantities = [
                int(qty) for _op_id, _sku, qty in segment.twin_outputs
            ]
            if (
                actual_ops != expected_ops
                or len(segment.twin_outputs) != 2
                or any(qty < 0 for qty in segment_quantities)
                or len(set(segment_quantities)) != 1
            ):
                twin_output_mismatches += 1
            for op_id, _sku, qty in segment.twin_outputs:
                actual[op_id] = actual.get(op_id, 0) + int(qty)
        else:
            if segment.twin_outputs:
                twin_output_mismatches += 1
            actual[lot.op_id] = actual.get(lot.op_id, 0) + int(segment.qty)

    expected_qty = 0
    produced_qty = 0
    missing_qty = 0
    overproduced_qty = 0
    for lot_id, expected in expected_by_lot.items():
        actual = produced_by_lot.get(lot_id, {})
        for op_id, qty in expected.items():
            produced = int(actual.get(op_id, 0))
            expected_qty += qty
            produced_qty += produced
            missing_qty += max(0, qty - produced)
            overproduced_qty += max(0, produced - qty)
        for op_id, produced in actual.items():
            if op_id not in expected:
                produced_qty += int(produced)
                overproduced_qty += max(0, int(produced))

    missing_lots = sum(1 for lot in lots if lot.id not in productive_lots)
    duplicate_twin_output_qty = _duplicate_twin_output_qty(lots)
    return {
        "expected_lots": len(lots),
        "scheduled_lots": len(productive_lots & set(lots_by_id)),
        "missing_lots": missing_lots,
        "unexpected_lots": len(unexpected_lot_ids),
        "expected_qty": expected_qty,
        "produced_qty": produced_qty,
        "missing_qty": missing_qty,
        "overproduced_qty": overproduced_qty,
        "duplicate_twin_output_qty": duplicate_twin_output_qty,
        "duplicate_production_qty": overproduced_qty + duplicate_twin_output_qty,
        "twin_output_mismatches": twin_output_mismatches,
    }


def _duplicate_twin_output_qty(lots: list[Lot]) -> int:
    """Count repeated twin obligations carried by different physical lots."""

    def milestone_day(output: dict[str, object], field: str, fallback: int) -> int:
        value = output.get(field)
        return int(fallback if value is None else value)

    grouped: dict[tuple[str, int, int, int], dict[str, int]] = {}
    for lot in lots:
        if not lot.is_twin:
            continue
        for output in lot.output_milestones or []:
            if bool(output.get("is_coproduced_surplus")):
                continue
            qty = int(output.get("qty", 0) or 0)
            if qty <= 0:
                continue
            fingerprint = (
                str(output.get("op_id", lot.op_id)),
                milestone_day(
                    output,
                    "customer_delivery_day",
                    lot.delivery_day if lot.delivery_day is not None else lot.edd,
                ),
                milestone_day(
                    output,
                    "production_due_day",
                    lot.production_due_day
                    if lot.production_due_day is not None
                    else lot.edd,
                ),
                milestone_day(
                    output,
                    "material_release_day",
                    lot.material_release_day
                    if lot.material_release_day is not None
                    else 0,
                ),
            )
            by_lot = grouped.setdefault(fingerprint, {})
            by_lot[lot.id] = by_lot.get(lot.id, 0) + qty

    duplicate_qty = 0
    for by_lot in grouped.values():
        if len(by_lot) > 1:
            quantities = list(by_lot.values())
            duplicate_qty += sum(quantities) - max(quantities)
    return duplicate_qty


def coverage_violations(segments: list[Segment], lots: list[Lot]) -> list[dict[str, Any]]:
    """Return concise hard-gate violations for production conservation."""

    metrics = coverage_metrics(segments, lots)
    violations: list[dict[str, Any]] = []
    for key, kind, label in (
        ("missing_lots", "missing_lots", "lote(s) sem producao"),
        ("missing_qty", "missing_quantity", "peca(s) em falta"),
        ("unexpected_lots", "unexpected_lots", "lote(s) desconhecido(s)"),
        ("overproduced_qty", "duplicate_production", "peca(s) produzida(s) em excesso"),
        (
            "duplicate_twin_output_qty",
            "duplicate_twin_output",
            "peca(s) gémea(s) repetida(s) noutro lote",
        ),
        ("twin_output_mismatches", "twin_output_mismatch", "inconsistencia(s) de gemeas"),
    ):
        value = int(metrics[key])
        if value:
            violations.append(
                {
                    "kind": kind,
                    "message": f"Cobertura invalida: {value} {label}.",
                    "count": value,
                }
            )
    return violations


def demand_coverage_metrics(
    data: EngineData,
    lots: list[Lot],
    config: FactoryConfig | None = None,
) -> dict[str, int]:
    """Reconcile candidate lot obligations with the current source demand."""

    from backend.scheduler.lot_sizing import create_lots

    def quantities(candidate_lots: list[Lot]) -> dict[str, int]:
        result: dict[str, int] = {}
        for lot in candidate_lots:
            outputs = lot.twin_outputs or [(lot.op_id, lot.sku, lot.qty)]
            for op_id, _sku, qty in outputs:
                result[str(op_id)] = result.get(str(op_id), 0) + int(qty)
        return result

    expected = quantities(create_lots(data, config))
    actual = quantities(lots)
    op_ids = set(expected) | set(actual)
    missing = sum(max(0, expected.get(op_id, 0) - actual.get(op_id, 0)) for op_id in op_ids)
    excess = sum(max(0, actual.get(op_id, 0) - expected.get(op_id, 0)) for op_id in op_ids)
    return {
        "source_expected_qty": sum(expected.values()),
        "source_planned_qty": sum(actual.values()),
        "source_missing_qty": missing,
        "source_overproduced_qty": excess,
    }


def demand_coverage_violations(
    data: EngineData,
    lots: list[Lot],
    config: FactoryConfig | None = None,
) -> list[dict[str, Any]]:
    metrics = demand_coverage_metrics(data, lots, config)
    violations: list[dict[str, Any]] = []
    for key, kind, label in (
        ("source_missing_qty", "source_missing_quantity", "peça(s) em falta face à procura"),
        (
            "source_overproduced_qty",
            "source_overproduction",
            "peça(s) em excesso face à procura",
        ),
    ):
        value = int(metrics[key])
        if value:
            violations.append(
                {
                    "kind": kind,
                    "message": f"Procura e lotes não reconciliam: {value} {label}.",
                    "count": value,
                }
            )
    return violations


def validate_plan_metrics(
    segments: list[Segment],
    data: EngineData | None = None,
    config: FactoryConfig | None = None,
    lots: list[Lot] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return hard physical violations and their public metric counters."""

    violations = validate_plan(segments, data, config, lots=lots)
    return violations, hard_gate_metrics(violations)


def assert_plan_valid(
    segments: list[Segment],
    data: EngineData | None = None,
    config: FactoryConfig | None = None,
    lots: list[Lot] | None = None,
) -> None:
    """Raise PlanValidationError for physical or quantity-conservation failures."""

    violations = validate_plan(segments, data, config, lots=lots)
    if lots is not None:
        violations.extend(coverage_violations(segments, lots))
        if data is not None and data.ops:
            violations.extend(demand_coverage_violations(data, lots, config))
    if violations:
        raise PlanValidationError(violations)
