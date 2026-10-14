"""Hard physical validation for schedule plans."""

from __future__ import annotations

import copy
import dataclasses
import math
from datetime import datetime
from operator import attrgetter
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
        count = len(violations)
        super().__init__(
            f"Plano inválido: {count} {'conflito' if count == 1 else 'conflitos'}."
        )


def pt_int(value: float) -> str:
    """Whole number in pt-PT style: ``1200``, ``12 345`` (space from 5 digits)."""

    number = int(round(float(value)))
    digits = f"{abs(number):d}"
    if len(digits) >= 5:
        digits = f"{abs(number):,d}".replace(",", " ")
    return f"-{digits}" if number < 0 else digits


def plural(count: float, singular: str, plural_form: str) -> str:
    return singular if int(round(float(count))) == 1 else plural_form


def day_label(day_idx: int, data: EngineData | None = None) -> str:
    """``dia 13 (26/10)``; only ``dia 13`` when the calendar has no date."""

    from backend.calendar import _day_date

    calendar_date = _day_date(int(day_idx), data) if data is not None else None
    if calendar_date is None:
        return f"dia {int(day_idx)}"
    return f"dia {int(day_idx)} ({calendar_date:%d/%m})"


def _identity_refs(identity: tuple[str, tuple[str, ...]]) -> list[str]:
    refs: list[str] = []
    for reference in identity[1]:
        text = str(reference)
        if text.startswith("family:"):
            refs.extend(part for part in text[len("family:"):].split("|") if part)
        elif text:
            refs.append(text)
    return refs


def setup_identity_label(identity: tuple[str, tuple[str, ...]]) -> str:
    """``VUL115 (ref. 8718696125)`` instead of the internal identity tuple."""

    refs = _identity_refs(identity)
    if not refs:
        return str(identity[0])
    prefix = "ref." if len(refs) == 1 else "refs."
    return f"{identity[0]} ({prefix} {', '.join(refs)})"


def _transition_message(
    current: Segment,
    previous: Segment,
    machine_id: str,
    actual_setup: float,
    required_setup: float,
    data: EngineData | None,
) -> str:
    current_identity = segment_setup_identity(current)
    previous_identity = segment_setup_identity(previous)
    previous_text = (
        str(previous_identity[0])
        if previous_identity[0] != current_identity[0]
        else setup_identity_label(previous_identity)
    )
    return (
        f"Falta afinação: a ferramenta {setup_identity_label(current_identity)} entra na "
        f"{machine_id} depois da {previous_text}, no {day_label(current.day_idx, data)}, "
        f"com {pt_int(actual_setup)} de {pt_int(required_setup)} min de afinação."
    )


def _protected_context(
    segments: list[Segment],
    data: EngineData | None,
) -> list[Segment]:
    """Started-lot segments kept outside a residual plan, as physical evidence.

    A residual calculation (frozen started lots) leaves those lots out of
    ``segments`` but records them in ``data.protected_mounting_segments``.
    Setup transitions, tool movements and machine occupancy must be judged
    with them in place: without them the validator sees the wrong
    predecessor (a false missing setup) and misses a real interruption of a
    tool the started lot keeps mounted.  Lots already in the plan are
    judged by the plan's segments only.
    """

    if data is None or not getattr(data, "protected_mounting_segments", None):
        return []
    from backend.scheduler.resources import protected_mounting_segments

    # A lot carried by the plan itself is judged by the plan's own segments:
    # a stale protected copy of a moved lot must never bridge a real missing
    # setup (it would act as a phantom predecessor). The rest of a started
    # lot (``residual_lot_remainders``) is the exception: its started part is
    # not in the residual plan and is the real predecessor of that rest (a
    # run released after it goes on with the tool still mounted, rule 4; an
    # economic lot released whole resumes right after it, AGENTS §2).
    planned_lots = {segment.lot_id for segment in segments}
    rests = {
        str(rest.get("id")) for rest in getattr(data, "residual_lot_remainders", None) or []
    }
    return [
        segment
        for segment in protected_mounting_segments(data)
        if segment.end_min > segment.start_min
        and (segment.lot_id not in planned_lots or segment.lot_id in rests)
    ]


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


# ── B4.2: each candidate is validated once per calculation ─────────────────
#
# One improvement candidate used to be validated three times with the same
# inputs: by its generator, by the evaluator's physical check and inside its
# score.  ``validate_plan`` is a pure function of the plan content, the
# scenario and the configuration, so inside one planning calculation the
# verdict is memoised (transparent to every caller).  An entry is reused only
# after exact equality of:
#   * every field of every segment, in list order, compared by ``repr`` of
#     the record's whole field tuple: the value AND its type (420 and 420.0,
#     True and 1, 0.0 and -0.0 never share an entry), nested values included
#     (the types inside ``twin_outputs``, milestones, left-shift blockers).
#     ``repr`` is at least as strict as the ``schedule_fingerprint``
#     (``json.dumps``) a frozen recalculation uses to prove each preserved
#     lot, so a value change that can change the verdict always changes the
#     key (tests/test_validation_once.py has the cases);
#   * every field of every lot, in list order, by the same rule;
#   * the whole scenario (``EngineData`` equality against a private deep copy,
#     so preserved-lot proofs, anchors, calendars and supplies are all part of
#     the identity) and the configuration (same rule).
# ``repr`` can only miss, never collide, for the values these records carry
# (numbers, text, booleans, None, tuples, lists, flat dicts): a different
# dict key order or an object with an identity ``repr`` just validates again.
# Outside a planning scope nothing is cached.  Callers receive a private copy
# of the violations, so mutating one never alters another caller's verdict.

_MEMO_PLANS = 16
_MEMO_CONTEXTS = 4


def _record_getter(cls):
    return attrgetter(*(item.name for item in dataclasses.fields(cls)))


# Built from the dataclass fields, so a new field is part of the key at once.
_segment_fields = _record_getter(Segment)
_lot_fields = _record_getter(Lot)


def _plan_key(segments, lots):
    """Exact content of the plan as validation reads it, values and types."""

    segment_key = (
        tuple(map(type, segments)),
        tuple(map(repr, map(_segment_fields, segments))),
    )
    if lots is None:
        return segment_key, None
    return segment_key, (
        tuple(map(type, lots)),
        tuple(map(repr, map(_lot_fields, lots))),
    )


def _context_token(memo: dict, data, config) -> int:
    """Index of a private snapshot equal to (data, config); new one if none."""

    contexts = memo.setdefault("contexts", [])
    for token, snapshot_data, snapshot_config in contexts:
        if snapshot_config == config and snapshot_data == data:
            return token
    token = memo.get("next_token", 0)
    memo["next_token"] = token + 1
    contexts.append((token, copy.deepcopy(data), copy.deepcopy(config)))
    if len(contexts) > _MEMO_CONTEXTS:
        stale = contexts.pop(0)[0]
        plans = memo.get("plans", {})
        for key in [key for key in plans if key[1] == stale]:
            del plans[key]
    return token


def validation_counts() -> dict[str, int]:
    """Calls and real validations in the current planning calculation."""

    from backend.planning_control import execution_cache

    memo = execution_cache("validate_plan")
    return {"calls": memo.get("calls", 0), "validations": memo.get("validations", 0)}


def validate_plan(
    segments: list[Segment],
    data: EngineData | None = None,
    config: FactoryConfig | None = None,
    lots: list[Lot] | None = None,
    *,
    memo: bool = True,
) -> list[dict[str, Any]]:
    """Return hard physical violations for a schedule plan.

    Memoised inside one planning calculation (B4.2, see above); the verdict
    and its details are identical with and without the memo. ``memo=False``
    is for callers whose plans are new by construction (one-off
    counterfactuals): it skips the key cost but still counts the validation.
    """

    from backend.planning_control import current_planning_control, execution_cache

    if current_planning_control() is None:
        return _validate_plan(segments, data, config, lots)
    if not memo:
        counts = execution_cache("validate_plan")
        counts["calls"] = counts.get("calls", 0) + 1
        counts["validations"] = counts.get("validations", 0) + 1
        return _validate_plan(segments, data, config, lots)
    memo = execution_cache("validate_plan")
    memo["calls"] = memo.get("calls", 0) + 1
    plans = memo.setdefault("plans", {})
    try:
        key = (_plan_key(segments, lots), _context_token(memo, data, config))
        cached = plans.pop(key, None)
    except (AttributeError, TypeError):
        # Not plain segments/lots, or unhashable output fields: no memo.
        key = cached = None
    if cached is not None:
        plans[key] = cached  # most recently used last
        return copy.deepcopy(cached)
    memo["validations"] = memo.get("validations", 0) + 1
    violations = _validate_plan(segments, data, config, lots)
    if key is not None:
        if len(plans) >= _MEMO_PLANS:
            del plans[next(iter(plans))]
        plans[key] = copy.deepcopy(violations)
    return violations


def _validate_plan(
    segments: list[Segment],
    data: EngineData | None,
    config: FactoryConfig | None,
    lots: list[Lot] | None,
) -> list[dict[str, Any]]:
    if data is not None:
        from backend.transform.calendars import calendar_window

        data = calendar_window(data, config, max((s.day_idx for s in segments), default=0))

    violations: list[dict[str, Any]] = []
    active = [s for s in segments if s.end_min > s.start_min]
    from backend.scheduler.canonical import source_contract_violations
    from backend.scheduler.history import history_boundary, is_history, judged_start

    # AGENTS §2 rule 4: the inputs judge the plan only from its history
    # boundary on; what started before it already happened.
    boundary = history_boundary(data)

    def judged_from(seg: Segment) -> float | None:
        return judged_start(seg.day_idx, seg.start_min, seg.end_min, boundary)

    violations.extend(source_contract_violations(segments, lots, data, config))
    shift_a_start, _shift_b_end, day_cap = _timing(config)
    # The plan and shifts are immutable during one validation pass.
    intervals = {id(segment): segment_abs(segment, config) for segment in active}
    protected_context = _protected_context(segments, data)
    protected_ids = {id(segment) for segment in protected_context}
    intervals.update(
        {id(segment): segment_abs(segment, config) for segment in protected_context}
    )

    def judged(*items: Segment) -> bool:
        """At least one side belongs to the plan under validation."""

        return any(id(item) not in protected_ids for item in items)

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
        if config is not None and judged_from(seg) is not None and not any(
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
        judged_min = judged_from(seg)
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
        if judged_min is None:
            continue
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
                            f"A referência {lot.sku or lot.op_id} não pode ser produzida "
                            f"na {seg.machine_id}."
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
                            f"A referência {lot.sku or lot.op_id} não pode ser produzida "
                            f"com a ferramenta {seg.tool_id}."
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
                    f"Máquina {seg.machine_id} inativa.",
                    seg,
                )
            )
        if seg.day_idx in machine_blocked.get(seg.machine_id, set()):
            violations.append(
                _violation(
                    "machine_down",
                    f"Máquina {seg.machine_id} indisponível no {day_label(seg.day_idx, data)}.",
                    seg,
                )
            )
        if seg.day_idx in tool_blocked.get(seg.tool_id, set()):
            violations.append(
                _violation(
                    "tool_down",
                    f"Ferramenta {seg.tool_id} indisponível no {day_label(seg.day_idx, data)}.",
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
                and judged_min < int(block.get("end_min", 0))
                and seg.end_min > int(block.get("start_min", 0))
            ):
                violations.append(
                    _violation(
                        "machine_down",
                        (
                            f"Máquina {seg.machine_id} indisponível entre "
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
                and judged_min < int(block.get("end_min", 0))
                and seg.end_min > int(block.get("start_min", 0))
            ):
                violations.append(
                    _violation(
                        "tool_down",
                        (
                            f"Ferramenta {seg.tool_id} indisponível entre "
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
                        f"Referência {lot.sku or lot.op_id} ({lot.machine_id}): o plano tem "
                        f"{pt_int(actual_prod_min)} de {pt_int(expected_prod_min)} min "
                        "de produção."
                    ),
                    "lot_id": lot_id,
                    "actual_prod_min": round(actual_prod_min, 3),
                    "expected_prod_min": round(expected_prod_min, 3),
                }
            )

    by_machine: dict[str, list[Segment]] = {}
    for seg in active:
        by_machine.setdefault(seg.machine_id, []).append(seg)
    protected_by_machine: dict[str, list[Segment]] = {}
    for seg in protected_context:
        protected_by_machine.setdefault(seg.machine_id, []).append(seg)
    ordered_by_machine: dict[str, list[Segment]] = {}
    transition_setup_by_segment: dict[int, float] = {}
    for machine_id, segs in by_machine.items():
        used_by_day: dict[int, float] = {}
        # Protected capacity is reserved by calendar blocks, so the daily
        # load counts only the plan under validation.
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
                            f"Máquina {machine_id} excede a capacidade diária no "
                            f"{day_label(day_idx, data)}: {pt_int(used_min)} de "
                            f"{pt_int(day_cap)} min."
                        ),
                        machine_id=machine_id,
                        day_idx=day_idx,
                        used_min=round(used_min, 1),
                        capacity_min=day_cap,
                    )
                )

        ordered = sorted(
            [*segs, *protected_by_machine.get(machine_id, [])],
            key=lambda s: interval(s)[0],
        )
        ordered_by_machine[machine_id] = ordered
        for index, (prev, curr) in enumerate(zip(ordered, ordered[1:]), start=1):
            if not judged(prev, curr):
                continue
            prev_start, prev_end = interval(prev)
            curr_start, curr_end = interval(curr)
            if curr_start < prev_end - 0.01 and curr_end > prev_start + 0.01:
                violations.append(
                    _violation(
                        "machine_overlap",
                        f"Máquina {machine_id} com produções sobrepostas.",
                        *((prev, curr) if id(curr) in protected_ids else (curr, prev)),
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
                if id(curr) in protected_ids:
                    # The started lot relies on its tool staying mounted; the
                    # plan placed another tool in between.  Report it on the
                    # plan segment, the one a repair can move.
                    violations.append(
                        _violation(
                            kind,
                            (
                                f"A produção já iniciada da ferramenta "
                                f"{setup_identity_label(segment_setup_identity(curr))} na "
                                f"{machine_id}, no {day_label(curr.day_idx, data)}, precisa "
                                f"da ferramenta montada, mas o plano coloca antes a "
                                f"{setup_identity_label(segment_setup_identity(prev))}."
                            ),
                            prev,
                            curr,
                            actual_setup_min=actual_setup,
                            required_setup_min=required_setup,
                            transition="protected_mounting_interrupted",
                        )
                    )
                    continue
                violations.append(
                    _violation(
                        kind,
                        _transition_message(
                            curr, prev, machine_id, actual_setup, required_setup, data,
                        ),
                        curr,
                        prev,
                        actual_setup_min=actual_setup,
                        required_setup_min=required_setup,
                        transition="machine_setup_change",
                    )
                )

    violations.extend(lot_split_violations(
        ordered_by_machine, lots_by_id, data, config, history_ids=protected_ids,
    ))

    by_tool: dict[str, list[Segment]] = {}
    for seg in active:
        by_tool.setdefault(seg.tool_id, []).append(seg)
    protected_by_tool: dict[str, list[Segment]] = {}
    for seg in protected_context:
        protected_by_tool.setdefault(seg.tool_id, []).append(seg)
    for tool_id, segs in by_tool.items():
        ordered = sorted(
            [*segs, *protected_by_tool.get(tool_id, [])],
            key=lambda s: interval(s)[0],
        )
        for i, first in enumerate(ordered):
            first_start, first_end = interval(first)
            for second in ordered[i + 1 :]:
                second_start, second_end = interval(second)
                if second_start >= first_end - 0.01:
                    break
                if (
                    judged(first, second)
                    and first.machine_id != second.machine_id
                    and second_end > first_start + 0.01
                ):
                    violations.append(
                        _violation(
                            "tool_conflict",
                            f"Ferramenta {tool_id} em duas máquinas ao mesmo tempo.",
                            *((first, second) if id(second) in protected_ids else (second, first)),
                        )
                    )
        for previous, current in zip(ordered, ordered[1:]):
            if not judged(previous, current):
                continue
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
                            f"Falta afinação: a ferramenta {tool_id} passa da "
                            f"{previous.machine_id} para a {current.machine_id}, no "
                            f"{day_label(current.day_idx, data)}, com "
                            f"{pt_int(actual_setup)} de {pt_int(required_setup)} min de "
                            "afinação."
                        ),
                        *(
                            (previous, current)
                            if id(current) in protected_ids
                            else (current, previous)
                        ),
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
        if lot is not None and judged_from(seg) is not None:
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
            if is_history(day_idx, start_min, boundary):
                continue
            violations.append(
                _violation(
                    "setup_crew_overlap",
                    (
                        f"{len(active_setups)} afinações em simultâneo para "
                        f"{capacity} {plural(capacity, 'equipa', 'equipas')} de afinação "
                        f"de {group}, no {day_label(day_idx, data)}."
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
                    (
                        f"Afinação da ferramenta {setup.tool_id} na {setup.machine_id}, no "
                        f"{day_label(setup.day_idx, data)}, sem produção a seguir."
                    ),
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
                        f"Afinação da ferramenta {setup.tool_id} na {setup.machine_id}, no "
                        f"{day_label(setup.day_idx, data)}, separada da primeira "
                        "produção por tempo de fábrica utilizável."
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
                        (
                            f"A ferramenta {seg.tool_id} produz na {seg.machine_id}, no "
                            f"{day_label(seg.day_idx, data)}, antes de a afinação terminar."
                        ),
                        seg,
                        setup,
                        setup_done=setup_done,
                    )
                )

    return violations


def _working_gap(
    start: tuple[int, float], end: tuple[int, float],
    data: EngineData | None, config: FactoryConfig | None, *, workday=None,
) -> list[tuple[int, float, float]]:
    """Shift time of factory working days inside ``[start, end)``.

    ``start``/``end`` are ``(day, minute)``. Nights, weekends, holidays and
    the days before day 0 hold none. Returns ``(day, low, high)`` pieces.
    ``workday(day)`` may replace ``calendar.is_factory_workday`` (a cache).
    """

    from backend.config.shifts import ordered_shifts

    config = config or FactoryConfig()
    if workday is None:
        def workday(day: int) -> bool:
            return is_factory_workday(day, data, config)
    pieces: list[tuple[int, float, float]] = []
    for day in range(int(start[0]), int(end[0]) + 1):
        low = float(start[1]) if day == start[0] else 0.0
        high = float(end[1]) if day == end[0] else 1440.0
        if high <= low or data is None or not workday(day):
            continue
        for shift in ordered_shifts(config):
            piece_low = max(low, float(shift.start_min))
            piece_high = min(high, float(shift.end_min))
            if piece_high > piece_low:
                pieces.append((day, piece_low, piece_high))
    return pieces


def _block_in_working_time(
    machine_id: str, tool_id: str, pieces: list[tuple[int, float, float]],
    data: EngineData | None,
) -> bool:
    """Whether a machine or tool unavailability covers part of ``pieces``.

    Unavailable days and the daily intervals of the calendar window
    (``machine_blocked_intervals``, ``tool_blocked_intervals``) count only
    where they meet working time: a block at night, on a weekend or on a
    holiday stops nothing.
    """

    if data is None or not pieces:
        return False
    blocked_days = (
        data.machine_blocked_days.get(machine_id, set())
        | data.tool_blocked_days.get(tool_id, set())
    )
    blocks = [
        *data.machine_blocked_intervals.get(machine_id, []),
        *data.tool_blocked_intervals.get(tool_id, []),
    ]
    for day, low, high in pieces:
        if day in blocked_days:
            return True
        for block in blocks:
            if int(block.get("start_day", -1)) != day:
                continue
            if (int(block.get("start_min", 0)) < high
                    and int(block.get("end_min", 1440)) > low):
                return True
    return False


@dataclasses.dataclass(frozen=True, slots=True)
class _ProductionBreak:
    """Where one lot stops being one production on a machine."""

    before: Segment
    after: Segment
    kind: str  # "interleaved", "remount" or "pause"


class _BreakFinder:
    """The places where economic lots are split on their machines.

    One lot is one production (AGENTS §2, 13/10/2026): one setup, and the
    production goes on through shifts, nights, weekends and the following
    days. On a machine (``ordered_by_machine``, in time order) a lot breaks
    between two of its segments when

    * ``interleaved``: another lot's work comes between them;
    * ``remount``: the later segment mounts the tool again after the lot
      has produced;
    * ``pause``: nothing comes between, the tool stays mounted, but free
      working time lies in the gap — shift time of a working day the
      machine and tool could work, with enough operators, at least
      ``calendar.MIN_FREE_INTERVAL_MIN`` long (``calendar.free_shift_intervals``,
      the definition of rule 4's «Continua»).

    An interleaving or a remount is excused when a machine or tool
    unavailability covers part of the working time between the two parts
    (``_block_in_working_time``); a pause never needs it, blocked time is
    not free. A break is history, never judged, when its earlier part
    started before the boundary of the plan (``scheduler.history``, the
    current factory minute of the calculation) or is the started part of a
    residual rest (``history_ids``). ``excuse_blocks=False`` counts every
    interleaving and remount (an upper bound, see ``lot_productions``).
    """

    def __init__(
        self, ordered_by_machine, lots_by_id, data, config, *, boundary, history_ids=(),
        excuse_blocks: bool = True,
    ):
        self.excuse_blocks = excuse_blocks
        self.ordered_by_machine = ordered_by_machine
        self.lots_by_id = lots_by_id
        self.data = data
        self.config = config or FactoryConfig()
        self.boundary = boundary
        self.history_ids = set(history_ids)
        self._by_day: dict[int, list[Segment]] | None = None
        self._operators: dict[str, int] | None = None
        self._workdays: dict[int, bool] = {}

    def breaks(self, lot_ids: set[str]) -> dict[str, list[_ProductionBreak]]:
        from backend.scheduler.history import is_history

        found: dict[str, list[_ProductionBreak]] = {}
        if not lot_ids:
            return found
        for ordered in self.ordered_by_machine.values():
            last: dict[str, int] = {}
            produced: set[str] = set()
            for index, segment in enumerate(ordered):
                lot_id = segment.lot_id
                previous = last.get(lot_id)
                last[lot_id] = index
                had_produced = lot_id in produced
                if segment.prod_min > 0:
                    produced.add(lot_id)
                if previous is None or lot_id not in lot_ids:
                    continue
                before = ordered[previous]
                if id(before) in self.history_ids or is_history(
                    before.day_idx, before.start_min, self.boundary,
                ):
                    continue
                kind = None
                if index - previous > 1:
                    kind = "interleaved"
                elif segment.setup_min > 0 and had_produced:
                    kind = "remount"
                elif had_produced and self._free_pause(before, segment):
                    kind = "pause"
                if kind is None:
                    continue
                if kind != "pause" and self._excused(before, segment):
                    continue
                found.setdefault(lot_id, []).append(_ProductionBreak(before, segment, kind))
        return found

    def productions(
        self, lot_ids: set[str], breaks: dict[str, list[_ProductionBreak]] | None = None,
    ) -> dict[str, int]:
        """Productions of each lot: one per machine it runs on, plus its breaks."""

        machines: dict[str, set[str]] = {}
        for machine_id, ordered in self.ordered_by_machine.items():
            for segment in ordered:
                if segment.lot_id in lot_ids and id(segment) not in self.history_ids:
                    machines.setdefault(segment.lot_id, set()).add(machine_id)
        if breaks is None:
            breaks = self.breaks(lot_ids)
        return {
            lot_id: len(used) + len(breaks.get(lot_id, []))
            for lot_id, used in machines.items()
        }

    def _workday(self, day: int) -> bool:
        if day not in self._workdays:
            self._workdays[day] = is_factory_workday(day, self.data, self.config)
        return self._workdays[day]

    def _gap(self, before: Segment, after: Segment) -> list[tuple[int, float, float]]:
        return _working_gap(
            (before.day_idx, float(before.end_min)), (after.day_idx, float(after.start_min)),
            self.data, self.config, workday=self._workday,
        )

    def _excused(self, before: Segment, after: Segment) -> bool:
        """An outage or block over the working time between the two parts."""

        data = self.data
        if not self.excuse_blocks or data is None:
            return False
        machine_id, tool_id = after.machine_id, after.tool_id
        if not (data.machine_blocked_days.get(machine_id)
                or data.tool_blocked_days.get(tool_id)
                or data.machine_blocked_intervals.get(machine_id)
                or data.tool_blocked_intervals.get(tool_id)):
            return False
        return _block_in_working_time(machine_id, tool_id, self._gap(before, after), data)

    def _free_pause(self, before: Segment, after: Segment) -> bool:
        from backend.calendar import MIN_FREE_INTERVAL_MIN, free_shift_intervals

        start = (before.day_idx, float(before.end_min))
        end = (after.day_idx, float(after.start_min))
        if (end[0] - start[0]) * 1440 + end[1] - start[1] < MIN_FREE_INTERVAL_MIN:
            return False
        pieces = self._gap(before, after)
        if not any(high - low >= MIN_FREE_INTERVAL_MIN for _day, low, high in pieces):
            return False
        required = self._required_operators(after)
        for day, low, high in pieces:
            if high - low < MIN_FREE_INTERVAL_MIN:
                continue
            if free_shift_intervals(
                after.machine_id, after.tool_id, day, self.data, self.config,
                segments=self._segments_by_day().get(day, []),
                required_operators=required, start_min=low, end_min=high,
            ):
                return True
        return False

    def _segments_by_day(self) -> dict[int, list[Segment]]:
        if self._by_day is None:
            by_day: dict[int, list[Segment]] = {}
            for ordered in self.ordered_by_machine.values():
                for segment in ordered:
                    by_day.setdefault(segment.day_idx, []).append(segment)
            self._by_day = by_day
        return self._by_day

    def _required_operators(self, segment: Segment) -> int:
        """Operators the lot needs to run (the larger side of a twin cycle)."""

        if self._operators is None:
            self._operators = {
                op.id: max(1, int(getattr(op, "operators", 1) or 1))
                for op in getattr(self.data, "ops", None) or []
            }
        lot = self.lots_by_id.get(segment.lot_id)
        if lot is None:
            return 1
        op_ids = [str(op_id) for op_id, _sku, _qty in lot.twin_outputs or []] or [lot.op_id]
        return max((self._operators.get(op_id, 1) for op_id in op_ids), default=1)


def _upgraded_productions(lot: Lot) -> int | None:
    """Productions an upgraded lot had in the plan it was calculated from."""

    from backend.scheduler.lot_sizing import UPGRADED_PRODUCTIONS_KEY

    values = [
        int(output[UPGRADED_PRODUCTIONS_KEY])
        for output in lot.output_milestones or []
        if output.get(UPGRADED_PRODUCTIONS_KEY) is not None
    ]
    return max(values) if values else None


def lot_productions(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData | None,
    config: FactoryConfig | None,
    *,
    boundary=None,
) -> dict[str, int]:
    """Productions of every lot of a stored plan, the most the check may allow.

    ``boundary`` is the history boundary (``scheduler.history``) of the
    calculation the plan is the baseline of: breaks whose earlier part is
    history are not counted, as the check does not judge them. Interleavings
    and remounts count even with a block in between: the calendar may have
    changed since the plan was made (a new outage would excuse the old
    break there, while the plan that answers it moves the work elsewhere).
    """

    config = config or FactoryConfig()
    by_machine: dict[str, list[Segment]] = {}
    for segment in segments:
        if segment.end_min > segment.start_min:
            by_machine.setdefault(segment.machine_id, []).append(segment)
    ordered = {
        machine_id: sorted(items, key=lambda item: segment_abs(item, config)[0])
        for machine_id, items in by_machine.items()
    }
    finder = _BreakFinder(
        ordered, {lot.id: lot for lot in lots}, data, config, boundary=boundary,
        excuse_blocks=False,
    )
    return finder.productions({lot.id for lot in lots})


def plan_lot_split_violations(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData | None,
    config: FactoryConfig | None,
) -> list[dict[str, Any]]:
    """``lot_split_violations`` of a complete plan, at ``data``'s history boundary.

    Only the one-production check, without the rest of ``validate_plan``:
    whether a stored plan is still one production per economic lot when it
    is judged from another boundary (from D0 for «Recalcular plano»).
    """

    config = config or FactoryConfig()
    by_machine: dict[str, list[Segment]] = {}
    for segment in segments:
        if segment.end_min > segment.start_min:
            by_machine.setdefault(segment.machine_id, []).append(segment)
    ordered = {
        machine_id: sorted(items, key=lambda item: segment_abs(item, config)[0])
        for machine_id, items in by_machine.items()
    }
    return lot_split_violations(ordered, {lot.id: lot for lot in lots}, data, config)


def lot_split_violations(
    ordered_by_machine: dict[str, list[Segment]],
    lots_by_id: dict[str, Lot],
    data: EngineData | None,
    config: FactoryConfig | None,
    *,
    history_ids=(),
) -> list[dict[str, Any]]:
    """Economic lots produced in more than one production (AGENTS §2, 13/10/2026).

    Material version 3: an economic lot is one production, one setup, which
    continues through shifts, nights, weekends and the following days. The
    breaks of a lot are found by ``_BreakFinder``: another lot's work in
    between, a new setup after the lot produced, or a pause with free
    working time while nothing else runs; an outage or block of the machine
    or tool over the working time in between excuses the first two. A break
    whose earlier part is history is not judged: it started before the
    calculation's boundary, the current factory minute of rule 4
    (``scheduler.history``, read from the plan's ``history_boundary``), or
    it is the started part of a residual rest (``history_ids``), so the rest
    of a lot started today may follow other work. In the residual problem
    of a replan the frozen work is itself a machine and tool block
    (``frozen._install_frozen_reservations``).

    Lots of an older material contract and lots preserved unchanged are not
    judged. A lot taken over from versions 1-2
    (``lot_sizing.UPGRADED_MATERIAL_KEY``) may keep the productions its old
    contract made, but never gain one: it is split when it has more
    productions than in the plan it was calculated from
    (``lot_sizing.UPGRADED_PRODUCTIONS_KEY``, written by
    ``plans.frozen.with_current_material``); one with no recorded count is
    judged strictly, as a lot of the current contract.
    """

    from backend.scheduler.history import history_boundary
    from backend.scheduler.lot_sizing import UPGRADED_MATERIAL_KEY
    from backend.scheduler.material_quantities import lot_material_version

    preserved = set(getattr(data, "preserved_lot_proofs", None) or {})
    planned = {segment.lot_id for ordered in ordered_by_machine.values() for segment in ordered}
    strict: set[str] = set()
    allowed: dict[str, int] = {}
    for lot_id in planned:
        lot = lots_by_id.get(lot_id)
        if lot is None or lot_id in preserved or lot_material_version(lot) < 3:
            continue
        if not any(output.get(UPGRADED_MATERIAL_KEY) for output in lot.output_milestones or []):
            strict.add(lot_id)
            continue
        limit = _upgraded_productions(lot)
        if limit is None:
            # No recorded count: nothing proves which productions it had, so
            # it is judged like a lot of the current contract (fail closed).
            strict.add(lot_id)
        else:
            allowed[lot_id] = limit
    if not strict and not allowed:
        return []

    finder = _BreakFinder(
        ordered_by_machine, lots_by_id, data, config,
        boundary=history_boundary(data), history_ids=history_ids,
    )
    violations: list[dict[str, Any]] = []
    breaks = finder.breaks(strict | set(allowed))
    counts = finder.productions(set(allowed), breaks) if allowed else {}
    for lot_id in sorted(strict & set(breaks)):
        violations.append(_split_violation(lots_by_id[lot_id], breaks[lot_id][0], data))
    for lot_id in sorted(allowed):
        # More productions with no break means more machines: rule 3, checked elsewhere.
        if counts.get(lot_id, 0) > allowed[lot_id] and breaks.get(lot_id):
            violations.append(_split_violation(
                lots_by_id[lot_id], breaks[lot_id][-1], data,
                productions=counts[lot_id], allowed=allowed[lot_id],
            ))
    return violations


def _split_violation(
    lot: Lot, item: _ProductionBreak, data: EngineData | None, *,
    productions: int | None = None, allowed: int | None = None,
) -> dict[str, Any]:
    segment, before = item.after, item.before
    if productions is not None:
        message = (
            f"Referência {lot.sku or lot.op_id} ({segment.machine_id}): o lote económico "
            f"passa de {allowed} para {productions} produções separadas (no "
            f"{day_label(segment.day_idx, data)}), sem avaria nem bloqueio pelo meio. "
            "Um lote de um plano anterior pode manter as produções que tinha, "
            "mas não ganhar outra."
        )
    elif item.kind == "pause":
        message = (
            f"Referência {lot.sku or lot.op_id} ({segment.machine_id}): o lote económico "
            f"para com a ferramenta montada e retoma no {day_label(segment.day_idx, data)}, "
            "com tempo de turno livre pelo meio. Um lote económico produz-se de uma só "
            "vez, sem paragens."
        )
    else:
        message = (
            f"Referência {lot.sku or lot.op_id} ({segment.machine_id}): o lote económico "
            f"volta a ser produzido no {day_label(segment.day_idx, data)} "
            "numa produção separada, sem avaria nem bloqueio pelo meio. "
            "Um lote económico produz-se de uma só vez, com um único setup."
        )
    return _violation(
        "lot_split",
        message,
        segment,
        before,
        interleaved=item.kind == "interleaved",
        remount=item.kind == "remount",
        pause=item.kind == "pause",
        **({"productions": productions, "allowed_productions": allowed}
           if productions is not None else {}),
    )


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
        "lot_split_violations": 0,
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
        "lot_split": "lot_split_violations",
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
            # Per-delivery twin outputs (material version 2, Fase B2): carry-
            # forward legitimately splits one delivery over several cycles,
            # like any economic lot. Their totals per delivery are reconciled
            # by the source contract (canonical obligations) and demand coverage.
            if int(output.get("quantity_material_version") or 0) >= 2:
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
    for key, kind, one, many in (
        ("missing_lots", "missing_lots", "lote sem produção", "lotes sem produção"),
        ("missing_qty", "missing_quantity", "peça em falta", "peças em falta"),
        ("unexpected_lots", "unexpected_lots", "lote desconhecido", "lotes desconhecidos"),
        (
            "overproduced_qty", "duplicate_production",
            "peça produzida em excesso", "peças produzidas em excesso",
        ),
        (
            "duplicate_twin_output_qty",
            "duplicate_twin_output",
            "peça gémea repetida noutro lote",
            "peças gémeas repetidas noutro lote",
        ),
        (
            "twin_output_mismatches", "twin_output_mismatch",
            "inconsistência de gémeas", "inconsistências de gémeas",
        ),
    ):
        value = int(metrics[key])
        if value:
            violations.append(
                {
                    "kind": kind,
                    "message": f"Cobertura inválida: {pt_int(value)} {plural(value, one, many)}.",
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
