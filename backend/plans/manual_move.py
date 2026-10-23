"""Exact lot movement with protected history and complete-plan validation."""

from __future__ import annotations

import copy
import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.config.planning import lot_alternative_on, lot_tool_machines
from backend.config.types import FactoryConfig
from backend.planning_control import (
    closing_reserve,
    planning_checkpoint,
    planning_scope,
    remaining_time,
)
from backend.scheduler.gates import build_gate_report
from backend.scheduler.operators import operator_free_windows, segment_operator_demand
from backend.scheduler.resources import clone_run_for_machine
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, ScheduleResult, Segment, ToolRun
from backend.simulator.simulator import DeltaReport, _utilization
from backend.types import EngineData, PlanAnchor

MANUAL_MOVE_BUDGET_S = 60.0
ALLOCATION_MODEL_VERSION = 1
# Alarm for the legacy engine (plan Passo 1d): Python logging only, never the
# plan journal or the move result, so plans stay byte-identical.
_legacy_logger = logging.getLogger("backend.legacy")


class ManualMoveError(ValueError):
    """A requested move cannot return an applicable candidate."""

    def __init__(
        self,
        message: str,
        *,
        gate_report: dict | None = None,
        causes: list[str] | None = None,
        suggestion: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.gate_report = gate_report
        # Concrete pt-PT causes (``plans.refusal``), shown under the message.
        self.causes = list(causes or [])
        # ``{day, start_min, machine, label}``: a start where the lot fits in
        # one production (``plans.move_fit``); offered, never applied.
        self.suggestion = suggestion


class ManualMoveInconclusive(ManualMoveError):
    """Bounded search found no candidate, without proving infeasibility."""


@dataclass(slots=True)
class ManualMoveResult:
    segments: list[Segment]
    lots: list[Lot]
    score: dict
    delta: DeltaReport
    gate_report: dict
    lot_id: str
    source_days: list[int]
    target_day: int
    target_start_min: int
    target_machine: str
    requires_confirmation: bool
    delivery_warnings: list[str]
    time_ms: float
    improvement_report: dict | None = None
    # The instant the move was checked at (ISO); the commit guard reads
    # today's history at it (AGENTS §2 rule 4).
    planning_now: str | None = None
    # A move to a time of today already gone records what ran (decisão do
    # Luís, 20/10/2026): ``notice`` says what that means for the plan and
    # ``history_boundary`` goes with the plan (``ScheduleResult``).
    executed: bool = False
    notice: str | None = None
    history_boundary: list[int] | None = None


def _move_protection(
    baseline_result, freeze_day: int, data, config, lot_id: str, now=None, declaration=None,
):
    """What a manual move keeps exactly as in the baseline (AGENTS §2, rule 4).

    The production before the planning day, the run mounted at that boundary
    while it continues without a new setup, the mount supplier of every such
    continuation and the honoured anchors (``frozen._protected_plan``). The
    rest of a started lot is re-allocated as the same, pre-sized lot. The
    moved lot is the planner's decision: it is left out, so a running run it
    belonged to simply ends where it leaves.

    ``declaration`` (``history.displaced_by``): the moved lot is recorded as
    run today from its setup start; what the plan had on its machine or tool
    from then until now did not run (``_without_displaced``).
    """
    from backend.plans.frozen import _protected_plan

    others = copy.copy(baseline_result)
    others.segments = [s for s in baseline_result.segments if s.lot_id != lot_id]
    if declaration is not None:
        others.segments = _without_displaced(others.segments, declaration)
    others.lots = [item for item in baseline_result.lots if item.id != lot_id]
    return _protected_plan(others, freeze_day, data, config, now=now)


def _displaced_lot_ids(segments, declaration) -> set[str]:
    from backend.scheduler.history import displaced_by

    return {
        s.lot_id for s in segments
        if displaced_by(s.day_idx, s.start_min, s.end_min, s.machine_id, s.tool_id, declaration)
    }


def _without_displaced(segments, declaration) -> list[Segment]:
    """The plan without what a record of what ran says did not run.

    Each displaced segment (``history.displaced_by``) stops at the recorded
    setup start with the pieces made by then (``history.cut_segment``) or
    goes when it made none; what its lot had after that is replanned with
    its rest, so it leaves too.
    """
    from backend.scheduler.history import cut_segment, displaced_by

    day, setup_start = declaration[0], declaration[1]
    displaced = _displaced_lot_ids(segments, declaration)
    kept = []
    for segment in segments:
        if displaced_by(
            segment.day_idx, segment.start_min, segment.end_min, segment.machine_id,
            segment.tool_id, declaration,
        ):
            part = cut_segment(segment, setup_start)
            if part is not None:
                kept.append(part)
        elif segment.lot_id not in displaced or (segment.day_idx, segment.start_min) < (
            day, setup_start,
        ):
            kept.append(segment)
    return kept


def _started_lot_proofs(protection) -> dict:
    """Preservation proofs of the started lots kept whole.

    A lot whose rest is re-allocated has no proof: its started part is
    checked row by row (``_keeps_frozen``) and the lot against its contract.
    """
    from backend.scheduler.canonical import preserved_lot_proofs

    whole = [item for item in protection.lots if item.id in protection.started]
    ids = {item.id for item in whole}
    return preserved_lot_proofs(
        [segment for segment in protection.segments if segment.lot_id in ids], whole,
    )


def _lot_rows(segments: list[Segment], lot_id: str) -> list[tuple]:
    """The physical rows of one lot, in order (its exact placement)."""
    from backend.scheduler.improvement import _segment_physical_row

    return sorted(_segment_physical_row(item) for item in segments if item.lot_id == lot_id)


def _keeps_frozen(segments: list[Segment], frozen_segments: list[Segment]) -> bool:
    """Every frozen segment is still in the plan, physically unchanged."""
    from collections import Counter

    from backend.scheduler.improvement import _segment_physical_row

    needed = Counter(_segment_physical_row(segment) for segment in frozen_segments)
    if not needed:
        return True
    lot_ids = {segment.lot_id for segment in frozen_segments}
    present = Counter(
        _segment_physical_row(segment) for segment in segments if segment.lot_id in lot_ids
    )
    return not needed - present


_FROZEN_CHANGED = (
    "O movimento alteraria produção já iniciada ou a ferramenta montada que continua "
    "a produzir; o histórico deve permanecer intacto."
)
_NO_ROOM = (
    "com o lote nessa posição, o motor não encontrou lugar para as outras "
    "produções, inteiras, dentro do horizonte do plano."
)
_QUANTITIES_CHANGED = "a reorganização alteraria as quantidades ou identidades dos lotes."
_TARGET_MISSED = (
    "o motor não conseguiu respeitar exatamente o dia, a hora e a máquina pedidos."
)
_HISTORY_CHANGED = (
    "a reorganização alteraria produção já iniciada ou a ferramenta montada que "
    "continua a produzir."
)
_REORGANISED_INVALID = "o plano reorganizado não cumpre as regras físicas ou de quantidade."
logger = logging.getLogger(__name__)


def _overlaps(start: float, end: float, other_start: float, other_end: float) -> bool:
    return start < other_end - 0.01 and other_start < end - 0.01


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _mounted_tool_gaps(
    segments: list[Segment], machine_id: str, tool_id: str, day: int,
    shift_start: int, shift_end: int,
) -> list[tuple[int, int, str]]:
    """Reserve the mounted tool between fragments of a continuing run."""

    by_run: dict[str, list[Segment]] = {}
    for segment in segments:
        if segment.machine_id == machine_id:
            by_run.setdefault(segment.run_id, []).append(segment)
    reserved = []
    for run_segments in by_run.values():
        ordered = sorted(run_segments, key=lambda item: (item.day_idx, item.start_min))
        for previous, following in zip(ordered, ordered[1:]):
            if (
                following.setup_min > 0
                or following.tool_id != previous.tool_id
                or following.tool_id == tool_id
                or not (previous.day_idx <= day <= following.day_idx)
            ):
                continue
            start = previous.end_min if day == previous.day_idx else shift_start
            end = following.start_min if day == following.day_idx else shift_end
            start, end = max(shift_start, start), min(shift_end, end)
            if start < end:
                reserved.append((start, end, following.tool_id))
    return reserved


def _operator_free_gaps(
    segments: list[Segment], data: EngineData, config: FactoryConfig,
    *, day: int, shift: str, shift_start: int, shift_end: int,
    machine_id: str, required: int,
) -> list[tuple[int, int]]:
    return operator_free_windows(
        segments, data, config, day=day, shift=shift,
        group=config.machine_group(machine_id), required=required,
        start=shift_start, end=shift_end,
    )


def _free_gaps(
    segments: list[Segment],
    data: EngineData,
    *,
    day: int,
    shift_start: int,
    shift_end: int,
    machine_id: str,
    tool_id: str,
) -> list[tuple[int, int]]:
    scheduled = [
        (max(shift_start, segment.start_min), min(shift_end, segment.end_min))
        for segment in segments
        if segment.day_idx == day
        and (segment.machine_id == machine_id or segment.tool_id == tool_id)
        and segment.end_min > shift_start
        and segment.start_min < shift_end
    ]
    blocked = [
        (
            max(shift_start, int(interval.get("start_min", 0))),
            min(shift_end, int(interval.get("end_min", 1440))),
        )
        for interval in (
            data.machine_blocked_intervals.get(machine_id, [])
            + data.tool_blocked_intervals.get(tool_id, [])
        )
        if int(interval.get("start_day", -1)) == day
        and int(interval.get("end_min", 0)) > shift_start
        and int(interval.get("start_min", 0)) < shift_end
    ]
    mounted = [
        (start, end)
        for start, end, _tool in _mounted_tool_gaps(
            segments, machine_id, tool_id, day, shift_start, shift_end,
        )
    ]
    busy = _merge_intervals(scheduled + blocked + mounted)
    gaps: list[tuple[int, int]] = []
    cursor = shift_start
    for start, end in busy:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < shift_end:
        gaps.append((cursor, shift_end))
    return gaps


def _crew_available(
    segments: list[Segment],
    *,
    config: FactoryConfig,
    machine_id: str,
    day: int,
    start: float,
    setup_min: float,
    ignore: Segment | None = None,
) -> bool:
    if setup_min <= 0:
        return True
    group = config.machine_group(machine_id)
    capacity = max(1, int(config.setup_crews_by_group.get(group, 1)))
    events: list[tuple[float, int]] = [(start, 1), (start + setup_min, -1)]
    for segment in segments:
        if segment is ignore or segment.day_idx != day or segment.setup_min <= 0:
            continue
        if config.machine_group(segment.machine_id) != group:
            continue
        events.extend(
            [
                (float(segment.start_min), 1),
                (float(segment.start_min + segment.setup_min), -1),
            ]
        )

    active = 0
    for _minute, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        if active > capacity:
            return False
    return True


def _setup_crew_blockers(
    segments: list[Segment], config: FactoryConfig, machine_id: str,
    day: int, start: float, end: float,
) -> str:
    group = config.machine_group(machine_id)
    conflicting = sorted(
        (
            segment for segment in segments
            if segment.day_idx == day
            and segment.setup_min > 0
            and config.machine_group(segment.machine_id) == group
            and _overlaps(start, end, segment.start_min, segment.start_min + segment.setup_min)
        ),
        key=lambda item: (item.start_min, item.machine_id),
    )
    return ", ".join(
        f"{item.machine_id}/{item.tool_id} "
        f"{int(item.start_min) // 60:02d}:{int(item.start_min) % 60:02d}-"
        f"{int(item.start_min + item.setup_min) // 60:02d}:"
        f"{int(item.start_min + item.setup_min) % 60:02d}"
        for item in conflicting
    )


def _shift_ranges(config: FactoryConfig) -> list[tuple[str, int, int]]:
    ranges = []
    for shift in config.shifts:
        if shift.end_min <= shift.start_min:
            raise ManualMoveError("Movimentos manuais ainda não suportam turnos após a meia-noite.")
        ranges.append((shift.id, shift.start_min, shift.end_min))
    return ranges


def _resource_blocked(data: EngineData, machine_id: str, tool_id: str, day: int) -> bool:
    return (
        day in set(data.holidays or [])
        or day in data.machine_blocked_days.get(machine_id, set())
        or day in data.tool_blocked_days.get(tool_id, set())
    )


def _setup_material_floor(
    data, config, lot, template, day, minute, machine_id, mount_layouts,
):
    """Setup start and material floor when the setup would precede the material.

    The material gate (``validation`` rule ``setup_before_material``) refuses a
    setup that starts before ``earliest_allowed_start``. A move to the first
    minutes of a shift places the setup at the end of the previous working
    day, so checking only the production day is not enough. Returns
    ``(setup_day, floor, setup_start_min, setup_min)`` when every layout the
    move may use (``mount_layouts``) needs that setup and it would start before
    the floor, else ``None``. A retained mounting needs no setup.
    """
    from backend.scheduler.jit_policy import calendar_holidays, earliest_allowed_start
    from backend.scheduler.setup_identity import retained_setup_at, segment_setup_identity
    from backend.transform.calendars import calendar_window

    rebound_lot, rebound_template = _rebound_target(
        copy.deepcopy(lot), template, machine_id, data, config,
    )
    setup_total = float(max(
        rebound_lot.setup_min, rebound_template.run_setup_min, rebound_template.setup_min,
    ))
    if setup_total <= 0:
        return None
    identity = segment_setup_identity(replace(
        rebound_template, tool_id=lot.tool_id, twin_outputs=lot.twin_outputs,
    ))
    if any(
        retained_setup_at(layout, machine_id, identity, day, minute)
        for layout in mount_layouts
    ):
        return None
    view = calendar_window(data, config, data.n_days - 1)
    slices = _setup_slices_before_target(view, config, day, minute, setup_total)
    if not slices:
        return None
    setup_day = slices[0][0]
    holidays = calendar_holidays(data, min(setup_day, 0) - 7, data.n_days + 7)
    floor = max(0, earliest_allowed_start(lot, holidays))
    return (setup_day, floor, slices[0][2], setup_total) if setup_day < floor else None


def _check_immutable_start(
    data, config, protected_segments, lot, template, day, minute, machine_id,
    mount_layouts=(), elapsed_until=None,
):
    from backend.calendar import is_factory_workday
    from backend.scheduler.material_quantities import next_release_day, released_quantity
    from backend.transform.calendars import calendar_window

    view = calendar_window(data, config, day, from_day=day)
    context = (
        f"Impedido iniciar {lot.id} exatamente no dia {day} "
        f"({str(data.workdays[day])[:10]}), às {minute // 60:02d}:{minute % 60:02d}, "
        f"em {machine_id}. "
    )
    if not is_factory_workday(day, view, config):
        raise ManualMoveError(context + "O calendário da fábrica não permite produção nesse dia.")
    # Material release is a hard floor (AGENTS §2; the material gate blocks
    # any candidate that breaks it): no production before the lot's release,
    # 5 working days before the first delivery it serves.
    if released_quantity(lot, day) <= 0:
        release = next_release_day(lot, day)
        when = (
            f"só é libertado no dia {release} ({str(data.workdays[release])[:10]})"
            if release is not None and release < len(data.workdays)
            else "ainda não está libertado nesse dia"
        )
        raise ManualMoveError(
            context + f"O material deste lote {when} "
            "(5 dias úteis antes da primeira entrega que o lote serve)."
        )
    early_setup = _setup_material_floor(
        data, config, lot, template, day, minute, machine_id, mount_layouts,
    )
    if early_setup is not None:
        setup_day, floor, setup_start, setup_total = early_setup
        floor_date = (
            f" ({str(data.workdays[floor])[:10]})" if floor < len(data.workdays) else ""
        )
        raise ManualMoveError(
            context + f"O material deste lote só é libertado no dia {floor}{floor_date}, "
            f"mas a afinação de {int(round(setup_total))} min tem de terminar antes das "
            f"{minute // 60:02d}:{minute % 60:02d} e começaria no dia {setup_day} "
            f"({str(data.workdays[setup_day])[:10]}), às "
            f"{int(setup_start) // 60:02d}:{int(setup_start) % 60:02d}, antes do material. "
            "Escolha uma hora que deixe a afinação inteira a partir do dia "
            f"{floor}."
        )
    for label, resource, blocked_days, blocked_intervals in (
        ("Máquina", machine_id, view.machine_blocked_days, view.machine_blocked_intervals),
        ("Ferramenta", lot.tool_id, view.tool_blocked_days, view.tool_blocked_intervals),
    ):
        if day in blocked_days.get(resource, set()):
            raise ManualMoveError(context + f"{label} {resource} indisponível nesse dia.")
        for block in blocked_intervals.get(resource, []):
            start, end = int(block.get("start_min", 0)), int(block.get("end_min", 1440))
            if int(block.get("start_day", -1)) == day and start <= minute < end:
                raise ManualMoveError(
                    context + f"{label} {resource} indisponível das "
                    f"{start // 60:02d}:{start % 60:02d} às {end // 60:02d}:{end % 60:02d}."
                )
    protected = [segment for segment in protected_segments if segment.lot_id != lot.id]
    for segment in protected:
        if (segment.day_idx == day and segment.start_min <= minute < segment.end_min
                and (segment.machine_id == machine_id or segment.tool_id == lot.tool_id)):
            raise ManualMoveError(
                context + f"Conflito com o lote protegido {segment.lot_id} "
                f"({segment.machine_id}/{segment.tool_id}), das "
                f"{int(segment.start_min) // 60:02d}:{int(segment.start_min) % 60:02d} "
                f"às {segment.end_min // 60:02d}:{segment.end_min % 60:02d}."
            )
    # What ran before now (a record of it) is not judged by operators.
    if elapsed_until is not None and (day, minute) < tuple(elapsed_until):
        return
    required = segment_operator_demand(
        replace(template, machine_id=machine_id, twin_outputs=lot.twin_outputs), view,
    )
    for shift in config.shifts:
        if shift.start_min <= minute < shift.end_min:
            free = _operator_free_gaps(
                protected, view, config, day=day, shift=shift.id,
                shift_start=shift.start_min, shift_end=shift.end_min,
                machine_id=machine_id, required=required,
            )
            if not any(start <= minute < end for start, end in free):
                group = config.machine_group(machine_id)
                raise ManualMoveError(
                    context + f"Operadores {group}, turno {shift.id}: não há capacidade "
                    f"para {required} operador(es) nesse instante, considerando as "
                    "ausências e as produções protegidas."
                )


def _elapsed_text(day, minute, data, now_min, *, setup=False) -> str:
    """Plain text: a move cannot start (or set up) in time already gone today."""
    now_text = f"{int(now_min) // 60:02d}:{int(now_min) % 60:02d}"
    when = f"no dia {day} ({str(data.workdays[day])[:10]}), às {minute // 60:02d}:{minute % 60:02d}"
    if setup:
        return (
            f"Impedido iniciar {when}: a afinação começaria antes da hora atual "
            f"({now_text}), em tempo que já passou. Escolha uma hora mais tarde."
        )
    return (
        f"Impedido iniciar {when}: esse momento já passou (agora são {now_text}). "
        "Escolha uma hora a partir de agora."
    )


def _clock(minute: float) -> str:
    return f"{int(minute) // 60:02d}:{int(minute) % 60:02d}"


def _past_day_text(day, minute, data) -> str:
    """Plain text: only today's runs can be recorded (decisão de 20/10/2026)."""
    return (
        f"Impedido iniciar no dia {day} ({str(data.workdays[day])[:10]}), às "
        f"{_clock(minute)}: só se pode registar o que já correu hoje; os dias "
        "anteriores ficam como estão."
    )


def _declared_setup_start(data, config, segments, lot, template, day, minute, machine_id) -> int:
    """Where the setup of a lot recorded as run from ``minute`` began, that same day.

    The setup comes right before production (``_setup_slices_before_target``),
    unless production follows a segment with the same setup identity ending
    exactly there (the rule of ``_materialize_target`` with ``partial_layout``).
    A setup that would start the day before is refused, with the first
    minute that keeps it inside the day.
    """
    from backend.scheduler.setup_identity import segment_setup_identity
    from backend.transform.calendars import calendar_window

    rebound_lot, rebound_template = _rebound_target(
        copy.deepcopy(lot), template, machine_id, data, config,
    )
    setup_total = float(max(
        rebound_lot.setup_min, rebound_template.run_setup_min, rebound_template.setup_min,
    ))
    identity = segment_setup_identity(replace(
        rebound_template, tool_id=lot.tool_id, twin_outputs=lot.twin_outputs,
    ))
    if setup_total <= 0 or any(
        item.machine_id == machine_id and (item.day_idx, item.end_min) == (day, minute)
        and segment_setup_identity(item) == identity
        for item in segments
    ):
        return int(minute)
    view = calendar_window(data, config, data.n_days - 1)
    slices = _setup_slices_before_target(view, config, day, minute, setup_total)
    if slices and slices[0][0] == day:
        return int(math.floor(slices[0][2]))
    first_shift = min(int(shift.start_min) for shift in config.shifts)
    earliest = first_shift + int(math.ceil(setup_total))
    raise _refused_move(
        lot.id, day, minute, machine_id, data,
        f"a afinação de {int(round(setup_total))} min começaria no dia anterior. "
        f"Escolha as {_clock(earliest)} ou mais tarde.",
        lot=lot,
    )


def _refuse_fixed_displaced(segments, lots, data, declaration, lot, day, minute, machine_id):
    """Refuse a record of what ran over work that cannot be cut.

    A lot pinned by hand is the planner's decision: it is released first.
    A lot of an older material contract is kept whole by every replan.
    """
    from backend.plans.manual_edits import EXECUTED
    from backend.scheduler.canonical import _lot_label
    from backend.scheduler.history import displaced_by
    from backend.scheduler.lot_sizing import WHOLE_LOT_MATERIAL_VERSION
    from backend.scheduler.material_quantities import lot_material_version

    anchors = {anchor.lot_id: anchor for anchor in getattr(data, "plan_anchors", None) or []}
    lots_by_id = {item.id: item for item in lots}
    for segment in sorted(segments, key=lambda item: (item.start_min, item.machine_id)):
        if not displaced_by(
            segment.day_idx, segment.start_min, segment.end_min, segment.machine_id,
            segment.tool_id, declaration,
        ):
            continue
        other = lots_by_id.get(segment.lot_id)
        label = _lot_label(other) if other is not None else "outro lote"
        where = (
            f"ocupa a {segment.machine_id} das {_clock(segment.start_min)} às "
            f"{_clock(segment.end_min)}"
        )
        anchor = anchors.get(segment.lot_id)
        if anchor is not None and getattr(anchor, "kind", "") == EXECUTED:
            since = str(getattr(anchor, "start_at", "") or "")[11:16] or _clock(segment.start_min)
            detail = (
                f"a {label} já está registada como feita nessa máquina desde {since}; "
                "desfaça esse registo primeiro."
            )
        elif anchor is not None:
            detail = f"a {label}, fixada à mão, {where}; solte-a primeiro."
        elif other is None or lot_material_version(other) < WHOLE_LOT_MATERIAL_VERSION:
            detail = (
                f"a {label} {where} e segue regras de material antigas, que não deixam "
                "cortá-la; recalcule o plano primeiro."
            )
        else:
            continue
        raise _refused_move(lot.id, day, minute, machine_id, data, detail, lot=lot)


def _declared_history_changes(
    segments, lots, data, complete, candidate_data, config, freeze_day, now,
) -> list[str]:
    """What the commit guard would refuse in a record of what ran, checked now."""
    from dataclasses import asdict

    from backend.plans.frozen import historical_schedule_changes

    def snapshot(engine_data, plan_segments, plan_lots, boundary):
        return {
            "dataset_info": {"id": "move"},
            "engine_data": {
                "workdays": [str(day) for day in engine_data.workdays or []],
                "plan_anchors": [asdict(anchor) for anchor in engine_data.plan_anchors],
                **({"history_boundary": list(boundary)} if boundary else {}),
            },
            "config": {"timezone": str(getattr(config, "timezone", "Europe/Lisbon"))},
            "segments": [asdict(segment) for segment in plan_segments],
            "lots": [asdict(item) for item in plan_lots],
        }

    return historical_schedule_changes(
        snapshot(data, segments, lots, getattr(data, "history_boundary", None)),
        snapshot(candidate_data, complete.segments, complete.lots, complete.history_boundary),
        today=str(data.workdays[freeze_day])[:10], now=now,
        engine_data=candidate_data, config=config,
    )


def _executed_notice(complete, lot_id, declaration, start_min, baseline_segments, data):
    """«Vai ficar registado como já produzido desde 08:00 na PRM043: …»: what the
    record means for the plan, said before it is applied (a time typed by
    mistake must not become production unnoticed, 20/10/2026)."""
    from backend.plans.frozen import _date_label
    from backend.scheduler.canonical import _lot_label, result_validation_data
    from backend.scheduler.history import cut_segment, displaced_by
    from backend.scheduler.material_quantities import delivery_readiness, lot_customer_delays

    setup_start = declaration[1]
    lots_by_id = {item.id: item for item in complete.lots}
    moved = lots_by_id.get(lot_id)
    subject = _lot_label(moved) if moved is not None else "o lote"
    text = (
        f"Vai ficar registado como já produzido desde {_clock(start_min)} na "
        f"{declaration[3]}: a {subject}"
    )
    if setup_start < start_min:
        text += f", com afinação desde {_clock(setup_start)}"
    made: dict[str, int] = {}
    order: list[str] = []
    for segment in sorted(baseline_segments, key=lambda item: (item.day_idx, item.start_min)):
        if segment.lot_id == lot_id or not displaced_by(
            segment.day_idx, segment.start_min, segment.end_min, segment.machine_id,
            segment.tool_id, declaration,
        ):
            continue
        if segment.lot_id not in made:
            order.append(segment.lot_id)
            made[segment.lot_id] = 0
        part = cut_segment(segment, setup_start)
        made[segment.lot_id] += int(part.qty) if part is not None else 0
    if not order:
        return text + "."
    view = result_validation_data(data, complete)
    try:
        delays = lot_customer_delays(delivery_readiness(complete.lots, complete.segments, view))
    except ValueError:
        delays = {}
    parts = []
    for other_id in order:
        other = lots_by_id.get(other_id)
        label = _lot_label(other) if other is not None else "outro lote"
        if made[other_id]:
            what = (
                f"a {label} fica feita até às {_clock(setup_start)} ({made[other_id]} peças) "
                "e o resto é replaneado a partir de agora"
            )
        else:
            what = f"a {label} fica por fazer e é replaneada a partir de agora"
        last = max(
            (item for item in complete.segments
             if item.lot_id == other_id and item.end_min > item.start_min),
            key=lambda item: (item.day_idx, item.end_min), default=None,
        )
        if last is not None:
            what += f" (pronta a {_date_label(last.day_idx, view)} às {_clock(last.end_min)}"
            delay = int(delays.get(other_id, 0) or 0)
            if delay > 0:
                what += f", {delay} {'dia' if delay == 1 else 'dias'} depois da entrega"
            what += ")"
        parts.append(what)
    return text + "; " + "; ".join(parts) + "."


def _move_subject(lot, lot_id) -> str:
    """``a Referência 6800016767A.10 (PRM043)``: never the internal lot id."""
    from backend.scheduler.canonical import _lot_label

    return f"a {_lot_label(lot)}" if lot is not None else "o lote"


def _move_when(day, data) -> str:
    from backend.scheduler.validation import day_label

    return f"no {day_label(day, data)}" if data is not None else f"no dia {day}"


def _inconclusive_move(lot_id, day, minute, machine_id, *, lot=None, data=None):
    return ManualMoveInconclusive(
        f"Verificação inconclusiva para iniciar {_move_subject(lot, lot_id)} exatamente "
        f"{_move_when(day, data)}, "
        f"às {minute // 60:02d}:{minute % 60:02d}, em {machine_id}. "
        "A pesquisa de reorganização e a tentativa mantendo os restantes lotes fixos "
        "não produziram um candidato completo válido. Não foi demonstrada a "
        "impossibilidade do movimento; o plano não foi alterado."
    )


def _source_setup_repair(
    segments: list[Segment],
    lots_by_id: dict[str, Lot],
    moved_segments: list[Segment],
    config: FactoryConfig,
    data: EngineData,
) -> None:
    from backend.scheduler.setup_identity import retained_setup_at, segment_setup_identity

    run_ids = {segment.run_id for segment in moved_segments}
    for run_id in run_ids:
        moved_run = [segment for segment in moved_segments if segment.run_id == run_id]
        remaining = [segment for segment in segments if segment.run_id == run_id]
        if not remaining:
            continue

        remaining_lot_ids = {segment.lot_id for segment in remaining}
        run_qty = sum(
            lots_by_id[lot_id].qty for lot_id in remaining_lot_ids if lot_id in lots_by_id
        )
        setup_min = max(
            [segment.setup_min for segment in moved_run]
            + [segment.run_setup_min for segment in moved_run],
            default=0.0,
        )
        for segment in remaining:
            segment.run_qty = run_qty
            segment.run_lot_count = len(remaining_lot_ids)
            segment.run_setup_min = setup_min

        if setup_min <= 0 or any(segment.setup_min > 0 for segment in remaining):
            continue

        earliest = min(remaining, key=lambda item: (item.day_idx, item.start_min))
        if retained_setup_at(
            segments, earliest.machine_id, segment_setup_identity(earliest),
            earliest.day_idx, earliest.start_min, ignore_run_id=run_id,
        ):
            continue
        shift = next((item for item in config.shifts if item.id == earliest.shift), None)
        shift_start = shift.start_min if shift is not None else config.shift_a_start
        new_start = int(math.floor(earliest.start_min - setup_min))
        if new_start < shift_start:
            raise ManualMoveError(
                f"O movimento removeria o setup necessário da campanha {run_id}; "
                "não há espaço antes do segmento seguinte."
            )

        for other in segments:
            if other is earliest or other.day_idx != earliest.day_idx:
                continue
            if (
                other.machine_id == earliest.machine_id or other.tool_id == earliest.tool_id
            ) and _overlaps(new_start, earliest.start_min, other.start_min, other.end_min):
                raise ManualMoveError(
                    f"Não há espaço para preservar o setup da campanha de origem {run_id}."
                )
        exact_blocks = (
            data.machine_blocked_intervals.get(earliest.machine_id, [])
            + data.tool_blocked_intervals.get(earliest.tool_id, [])
        )
        if any(
            int(block.get("start_day", -1)) == earliest.day_idx
            and _overlaps(
                new_start,
                earliest.start_min,
                int(block.get("start_min", 0)),
                int(block.get("end_min", 1440)),
            )
            for block in exact_blocks
        ):
            raise ManualMoveError(
                f"Não há espaço disponível para preservar o setup da campanha {run_id}."
            )
        if not _crew_available(
            segments,
            config=config,
            machine_id=earliest.machine_id,
            day=earliest.day_idx,
            start=new_start,
            setup_min=setup_min,
            ignore=earliest,
        ):
            raise ManualMoveError(
                f"A equipa de setup não está livre para reparar a campanha {run_id}."
            )

        earliest.start_min = new_start
        earliest.setup_min = setup_min
        earliest.is_continuation = False


def _allocated_qty(
    total_qty: int, total_prod: float, chunk_prod: float, used_qty: int, last: bool
) -> int:
    remaining_qty = max(0, total_qty - used_qty)
    if last:
        return remaining_qty
    if total_prod <= 0 or remaining_qty <= 0:
        return 0
    proportional = int(round(total_qty * chunk_prod / total_prod))
    return min(remaining_qty, max(1, proportional))


def _setup_slices_before_target(
    data: EngineData, config: FactoryConfig, target_day: int,
    target_start_min: int, setup_min: float,
) -> list[tuple[int, str, float, float]] | None:
    """Place setup in contiguous factory-working time before production."""

    from backend.calendar import is_factory_workday

    shifts = _shift_ranges(config)
    if not is_factory_workday(target_day, data, config):
        return None
    active = next(
        (index for index, (_id, start, end) in enumerate(shifts)
         if start <= target_start_min < end),
        None,
    )
    if active is None:
        return None
    remaining = float(setup_min)
    cursor = float(target_start_min)
    day = target_day
    index = active
    slices: list[tuple[int, str, float, float]] = []
    while remaining > 0.01:
        planning_checkpoint()
        shift_id, shift_start, shift_end = shifts[index]
        if not shift_start <= cursor <= shift_end:
            return None
        start = max(float(shift_start), cursor - remaining)
        if start < cursor:
            slices.append((day, shift_id, start, cursor))
            remaining -= cursor - start
        if remaining <= 0.01:
            return list(reversed(slices))
        if index > 0:
            previous_end = shifts[index - 1][2]
            if previous_end != shift_start:
                return None
            index -= 1
            cursor = float(previous_end)
            continue
        previous_day = day - 1
        while previous_day >= 0 and not is_factory_workday(previous_day, data, config):
            previous_day -= 1
        if previous_day < 0:
            return None
        day = previous_day
        index = len(shifts) - 1
        cursor = float(shifts[index][2])
    return list(reversed(slices))


def _materialize_target(
    segments: list[Segment],
    lot: Lot,
    template: Segment,
    data: EngineData,
    config: FactoryConfig,
    target_day: int,
    target_machine: str,
    target_start_min: int,
    *,
    partial_layout: bool = False,
    elapsed_until: tuple[int, int] | None = None,
) -> list[Segment]:
    """The moved lot's segments, starting production exactly at the target.

    ``partial_layout``: ``segments`` are only part of the plan (the started
    work); the rest is placed afterwards, possibly in any gap before the
    target. A gap then proves nothing about the mounted tool, so its setup is
    kept unless production follows a same-setup segment with no gap at all.
    ``elapsed_until`` (``(day, minute)`` of now): the lot is recorded as run
    (decisão do Luís, 20/10/2026); before now the setup crew and the
    operators are not judged, it really happened.
    """

    def happened(day: int, minute: float) -> bool:
        return elapsed_until is not None and (day, minute) < tuple(elapsed_until)

    from backend.transform.calendars import calendar_window

    planning_checkpoint()
    data = calendar_window(data, config, data.n_days - 1)
    remaining_prod = float(lot.prod_min)
    used_qty = 0
    twin_used = [0 for _ in (lot.twin_outputs or [])]
    setup_total = float(max(lot.setup_min, template.run_setup_min, template.setup_min))
    from backend.scheduler.setup_identity import retained_setup_at, segment_setup_identity

    identity = segment_setup_identity(replace(
        template, tool_id=lot.tool_id, twin_outputs=lot.twin_outputs,
    ))
    if retained_setup_at(
        segments, target_machine, identity, target_day, target_start_min,
    ) and (not partial_layout or any(
        item.machine_id == target_machine
        and (item.day_idx, item.end_min) == (target_day, target_start_min)
        and segment_setup_identity(item) == identity
        for item in segments
    )):
        setup_total = 0.0
    setup_remaining = setup_total
    run_id = f"manual_{uuid4().hex[:12]}"
    created: list[Segment] = []
    production_started = False
    setup_slices = _setup_slices_before_target(
        data, config, target_day, target_start_min, setup_total,
    )
    target_shift = next(
        shift.id for shift in config.shifts
        if shift.start_min <= target_start_min < shift.end_min
    )
    for setup_day, shift_id, start, end in setup_slices or []:
        planning_checkpoint()
        if setup_day == target_day and shift_id == target_shift:
            continue
        shift = next(item for item in config.shifts if item.id == shift_id)
        gaps = _free_gaps(
            segments + created, data, day=setup_day,
            shift_start=shift.start_min, shift_end=shift.end_min,
            machine_id=target_machine, tool_id=lot.tool_id,
        )
        if _resource_blocked(data, target_machine, lot.tool_id, setup_day) or not any(
            left <= start and end <= right for left, right in gaps
        ):
            raise ManualMoveError(
                f"Não há capacidade de máquina ou ferramenta para preparar {lot.tool_id} "
                f"no dia {setup_day}, das {int(start) // 60:02d}:{int(start) % 60:02d} "
                f"às {int(end) // 60:02d}:{int(end) % 60:02d} em {target_machine}."
            )
        if not happened(setup_day, start) and not _crew_available(
            segments + created, config=config, machine_id=target_machine,
            day=setup_day, start=start, setup_min=end - start,
        ):
            blockers = _setup_crew_blockers(
                segments + created, config, target_machine, setup_day, start, end,
            )
            raise ManualMoveError(
                f"A equipa de setup não está livre para preparar {lot.tool_id} "
                f"no dia {setup_day} ({str(data.workdays[setup_day])[:10]}), "
                f"das {int(start) // 60:02d}:{int(start) % 60:02d} "
                f"às {int(end) // 60:02d}:{int(end) % 60:02d}."
                + (f" Ocupada por {blockers}." if blockers else "")
            )
        created.append(replace(
            template,
            run_id=run_id,
            machine_id=target_machine,
            day_idx=setup_day,
            start_min=start,
            end_min=int(end),
            shift=shift_id,
            qty=0,
            prod_min=0.0,
            setup_min=end - start,
            is_continuation=bool(created),
            twin_outputs=(
                [(op_id, sku, 0) for op_id, sku, _qty in lot.twin_outputs]
                if lot.twin_outputs is not None else None
            ),
            lot_qty=lot.qty,
            run_qty=lot.qty,
            run_setup_min=setup_total,
            run_lot_count=1,
            planning_source="manual",
        ))
        setup_remaining -= end - start
    required_operators = segment_operator_demand(
        replace(template, machine_id=target_machine, twin_outputs=lot.twin_outputs),
        data,
    )
    for _shift, shift_start, shift_end in _shift_ranges(config):
        if shift_start <= target_start_min < shift_end:
            mounted = _mounted_tool_gaps(
                segments, target_machine, lot.tool_id, target_day, shift_start, shift_end,
            )
            for start, end, mounted_tool in mounted:
                if start <= target_start_min < end:
                    raise ManualMoveError(
                        f"A {target_machine} mantém {mounted_tool} montada para uma "
                        "continuação sem novo setup. Este lote exige replanear essa campanha."
                    )
    operators_block_start = False

    for day in range(target_day, data.n_days):
        planning_checkpoint()
        if _resource_blocked(data, target_machine, lot.tool_id, day):
            continue
        for shift_id, shift_start, shift_end in _shift_ranges(config):
            planning_checkpoint()
            operator_gaps = _operator_free_gaps(
                segments + created, data, config,
                day=day, shift=shift_id, shift_start=shift_start, shift_end=shift_end,
                machine_id=target_machine, required=required_operators,
            )
            if elapsed_until is not None and day == elapsed_until[0] and (
                shift_start < elapsed_until[1]
            ):
                operator_gaps = _merge_intervals([
                    *operator_gaps, (shift_start, min(shift_end, int(elapsed_until[1]))),
                ])
            if day == target_day and shift_start <= target_start_min < shift_end:
                operators_block_start = not any(
                    start <= target_start_min < end for start, end in operator_gaps
                )
            for gap_start, gap_end in _free_gaps(
                segments + created,
                data,
                day=day,
                shift_start=shift_start,
                shift_end=shift_end,
                machine_id=target_machine,
                tool_id=lot.tool_id,
            ):
                if not production_started:
                    if day != target_day:
                        continue
                    setup_start = target_start_min - setup_remaining
                    if (
                        setup_start < gap_start
                        or target_start_min >= gap_end
                        or (
                            setup_remaining > 0
                            and not happened(day, setup_start)
                            and not _crew_available(
                                segments,
                                config=config,
                                machine_id=target_machine,
                                day=day,
                                start=setup_start,
                                setup_min=setup_remaining,
                            )
                        )
                    ):
                        continue
                    candidates = [
                        (setup_start, min(gap_end, end), setup_remaining)
                        for start, end in operator_gaps
                        if start <= target_start_min < end
                    ]
                else:
                    candidates = [
                        (max(gap_start, start), min(gap_end, end), 0.0)
                        for start, end in operator_gaps
                    ]

                for start, gap_limit, setup_here in candidates:
                    available_prod = gap_limit - start - setup_here
                    if remaining_prod > 0 and available_prod < min(1.0, remaining_prod) - 0.01:
                        continue
                    chunk_prod = min(remaining_prod, max(0.0, available_prod))
                    is_last = remaining_prod - chunk_prod <= 0.01
                    chunk_qty = _allocated_qty(
                        lot.qty, lot.prod_min, chunk_prod, used_qty, is_last,
                    )
                    twin_outputs = None
                    if lot.twin_outputs is not None:
                        twin_outputs = []
                        for index, (op_id, sku, total_qty) in enumerate(lot.twin_outputs):
                            quantity = _allocated_qty(
                                total_qty, lot.prod_min, chunk_prod, twin_used[index], is_last,
                            )
                            twin_used[index] += quantity
                            twin_outputs.append((op_id, sku, quantity))
                    end = int(math.ceil(start + setup_here + chunk_prod))
                    created.append(
                        replace(
                            template,
                            run_id=run_id,
                            machine_id=target_machine,
                            day_idx=day,
                            start_min=start,
                            end_min=end,
                            shift=shift_id,
                            qty=chunk_qty,
                            prod_min=chunk_prod,
                            setup_min=setup_here,
                            is_continuation=len(created) > 0,
                            twin_outputs=twin_outputs,
                            lot_qty=lot.qty,
                            run_qty=lot.qty,
                            run_setup_min=setup_total,
                            run_lot_count=1,
                            planning_source="manual",
                        )
                    )
                    remaining_prod -= chunk_prod
                    used_qty += chunk_qty
                    setup_remaining = 0.0
                    production_started = True
                    if remaining_prod <= 0.01:
                        return created

    if operators_block_start and not production_started:
        raise ManualMoveError(
            f"Não há operadores suficientes para iniciar {lot.id} na "
            f"{target_machine} às {target_start_min // 60:02d}:"
            f"{target_start_min % 60:02d}."
        )
    raise ManualMoveError(
        f"Não há capacidade física para iniciar {lot.id} exatamente no dia "
        f"{target_day}, às {target_start_min // 60:02d}:"
        f"{target_start_min % 60:02d}, em {target_machine}."
    )


def _production_start(
    segments: list[Segment],
    lot_id: str,
) -> tuple[int, float, str] | None:
    anchored = sorted(
        (segment for segment in segments if segment.lot_id == lot_id and segment.prod_min > 0),
        key=lambda item: (item.day_idx, item.start_min),
    )
    if not anchored:
        return None
    first = anchored[0]
    return (
        first.day_idx,
        float(first.start_min + first.setup_min),
        first.machine_id,
    )


def _matches_target(
    production_start: tuple[int, float, str] | None,
    *,
    day: int,
    minute: int,
    machine: str,
) -> bool:
    return bool(
        production_start is not None
        and production_start[0] == day
        and abs(production_start[1] - minute) <= 0.01
        and production_start[2] == machine
    )


def _preserves_production(result: ScheduleResult, source_lots: list[Lot]) -> bool:
    """Allocation may change; the production obligations of a move may not."""
    from backend.scheduler.canonical import production_lot_obligations
    from backend.scheduler.validation import coverage_violations

    before = production_lot_obligations(source_lots)
    after = production_lot_obligations(result.lots)
    return (
        len(before) == len(source_lots)
        and len(after) == len(result.lots)
        and before == after
        and not coverage_violations(result.segments, result.lots)
    )


def _delta(before: dict, after: dict) -> DeltaReport:
    return DeltaReport(
        otd_before=float(before.get("otd", 0.0) or 0.0),
        otd_after=float(after.get("otd", 0.0) or 0.0),
        otd_d_before=float(before.get("otd_d", 0.0) or 0.0),
        otd_d_after=float(after.get("otd_d", 0.0) or 0.0),
        setups_before=int(before.get("setups", 0) or 0),
        setups_after=int(after.get("setups", 0) or 0),
        earliness_before=float(before.get("earliness_avg_days", 0.0) or 0.0),
        earliness_after=float(after.get("earliness_avg_days", 0.0) or 0.0),
        tardy_before=int(before.get("tardy_count", 0) or 0),
        tardy_after=int(after.get("tardy_count", 0) or 0),
        early_window_before=int(before.get("early_window_violations", 0) or 0),
        early_window_after=int(after.get("early_window_violations", 0) or 0),
        utilization_before=_utilization(before),
        utilization_after=_utilization(after),
        subcontract_dispatch_before=int(
            before.get("subcontract_dispatch_misses", 0) or 0
        ),
        subcontract_dispatch_after=int(
            after.get("subcontract_dispatch_misses", 0) or 0
        ),
        subcontract_dispatch_late_workdays_before=int(
            before.get("subcontract_dispatch_late_workdays", 0) or 0
        ),
        subcontract_dispatch_late_workdays_after=int(
            after.get("subcontract_dispatch_late_workdays", 0) or 0
        ),
    )


def _rebound_target(
    lot: Lot, template: Segment, machine_id: str,
    data: EngineData, config: FactoryConfig,
) -> tuple[Lot, Segment]:
    setup_min = max(lot.setup_min, template.run_setup_min, template.setup_min)
    rebound = clone_run_for_machine(
        ToolRun(
            id=template.run_id,
            tool_id=lot.tool_id,
            machine_id=template.machine_id,
            alt_machine_id=lot.alt_machine_id,
            lots=[lot],
            setup_min=setup_min,
            total_prod_min=lot.prod_min,
            total_min=setup_min + lot.prod_min,
            edd=lot.edd,
        ),
        machine_id,
        data,
        config,
    )
    rebound_lot = rebound.lots[0]
    rebound_lot.planning_source = "manual"
    # Where it goes, with the other machine of its tool as its alternative:
    # a lot never loses its primary (E13).
    rebound_lot.machine_id = machine_id
    rebound_lot.alt_machine_id = lot_alternative_on(lot, machine_id, data)
    return rebound_lot, replace(
        template, setup_min=rebound.setup_min, run_setup_min=rebound.setup_min,
    )


def _allocate_existing_lots(
    candidate_data: EngineData,
    *,
    source_lots: list[Lot],
    config: FactoryConfig,
    baseline_result: ScheduleResult | None = None,
    cancel_event: threading.Event | None = None,
    time_budget_s: float | None = None,
    protection=None,
    now: datetime | None = None,
    pinned: dict[str, tuple[str, list[Segment]]] | None = None,
    reasons: list[str] | None = None,
    violations: list[dict] | None = None,
) -> ScheduleResult | None:
    """Allocate existing productions using the shared physical solver, without lot sizing.

    ``protection`` (a ``frozen.ProtectedPlan``; derived from ``baseline_result``
    when omitted) stays exactly as in the baseline. The rest of a started lot
    is allocated as its pre-sized remainder and rejoins the lot (rule 4).
    ``pinned``: lots of ``source_lots`` already placed (lot id -> machine and
    segments); only the campaign builder (material released by quantity)
    takes them. ``reasons`` receives a plain pt-PT reason when ``None`` is
    returned.
    """

    def refuse(reason: str) -> None:
        if reasons is not None:
            reasons.append(reason)
        return None

    from backend.plans.frozen import (
        _current_planning_day,
        _install_frozen_reservations,
        _protected_plan,
        _splice_frozen_started_lots,
        calculation_now,
        elapsed_on_planning_day,
    )
    from backend.scheduler.global_jit import solve_global_jit
    from backend.scheduler.jit_policy import calendar_holidays
    from backend.scheduler.quantity_dispatch import (
        has_quantity_releases,
        schedule_quantity_releases,
    )
    from backend.scheduler.tool_grouping import create_tool_runs

    planning_checkpoint()
    residual_data = copy.deepcopy(candidate_data)
    now = calculation_now(config, now)
    freeze_day = _current_planning_day(candidate_data, config, now)
    if protection is None and baseline_result is not None:
        protection = _protected_plan(baseline_result, freeze_day, candidate_data, config, now=now)
    protected_segments, protected_lots, partial, not_started = [], [], [], set()
    if protection is not None:
        protected_segments = list(protection.segments)
        protected_lots, partial = list(protection.lots), list(protection.partial)
        not_started = set(protection.pinned)
        _install_frozen_reservations(
            residual_data, protected_segments, protected_lots, freeze_day, config, partial,
            now_min=elapsed_on_planning_day(freeze_day, candidate_data, config, now),
            pinned=not_started,
        )
    protected_ids = {lot.id for lot in protected_lots}
    rests = {original.id: rest for original, rest in partial}
    movable = copy.deepcopy([
        rests.get(lot.id, lot) for lot in source_lots if lot.id not in protected_ids
    ])
    result = ScheduleResult([], [], {}, 0, [], [])
    if has_quantity_releases(movable):
        # Material released by delivery (AGENTS §2): the same campaign builder
        # as a recalculation, on the existing, already sized lots. The
        # contiguous run model cannot place quantity-dependent releases.
        with planning_scope(timeout_s=time_budget_s, cancel_event=cancel_event):
            try:
                built_segments, built_lots = schedule_quantity_releases(
                    movable, residual_data, config, pinned=pinned,
                )
            except ValueError as error:  # includes PlanValidationError
                from backend.plans.refusal import causes_for_log, violations_of
                from backend.scheduler.validation import PlanValidationError

                logger.info(
                    "Realocação recusada: %s %s", error,
                    causes_for_log(error, candidate_data, source_lots),
                )
                if violations is not None:
                    violations.extend(violations_of(error))
                return refuse(
                    _REORGANISED_INVALID if isinstance(error, PlanValidationError) else _NO_ROOM
                )
            planning_checkpoint()
        result = ScheduleResult(built_segments, built_lots, {}, 0, [], [])
        runs = []
    else:
        if pinned:
            raise ValueError("Lotes fixados exigem o construtor por quantidades libertadas.")
        _legacy_logger.warning("motor antigo usado: %s", "manual_move._allocate_existing_lots")
        runs = create_tool_runs(
            movable, config=config,
            release_holidays=calendar_holidays(residual_data, -14, residual_data.n_days + 30),
        )
    if runs:
        with planning_scope(timeout_s=time_budget_s, cancel_event=cancel_event):
            allocated = solve_global_jit(
                runs, residual_data, config,
                baseline_segments=(baseline_result.segments if baseline_result else None),
                time_limit_s=time_budget_s,
                horizon_end_day=candidate_data.n_days - 1,
            )
            planning_checkpoint()
        if allocated is None or not allocated.candidate_found:
            return None
        result = ScheduleResult(
            allocated.segments, allocated.lots, {}, 0, allocated.warnings, [],
            machine_runs=allocated.machine_runs, solver_status=allocated.solver_status,
            feasibility=allocated.feasibility,
        )
    result = _splice_frozen_started_lots(
        result, protected_segments, protected_lots, partial, not_started,
    )
    if any(segment.day_idx < 0 or segment.day_idx >= candidate_data.n_days
           for segment in result.segments):
        return refuse(_NO_ROOM)
    if not _preserves_production(result, source_lots):
        return refuse(_QUANTITIES_CHANGED)
    if not _keeps_frozen(result.segments, protected_segments):
        return refuse(_HISTORY_CHANGED)
    result.score = compute_score(result.segments, result.lots, candidate_data, config)
    return result


def _reallocation_ignores_target(source_lots: list[Lot], protection) -> bool:
    """Whether ``_allocate_existing_lots`` would use the quantity-release builder.

    That builder (``schedule_quantity_releases``, the one «Recalcular plano»
    uses) places lots by material portions and ignores ``plan_anchors``, so a
    reallocation through it cannot place the moved lot at the requested start.
    Same movable set as ``_allocate_existing_lots``.
    """
    from backend.scheduler.quantity_dispatch import has_quantity_releases

    protected_ids = {item.id for item in protection.lots} if protection is not None else set()
    rests = (
        {original.id: rest for original, rest in protection.partial}
        if protection is not None else {}
    )
    return has_quantity_releases(
        [rests.get(item.id, item) for item in source_lots if item.id not in protected_ids]
    )


def _refused_move(
    lot_id, day, minute, machine_id, data, detail, *, gate_report=None, causes=None, lot=None,
    suggestion=None,
):
    """A move that was checked and cannot be applied, with its reason and causes."""
    return ManualMoveError(
        f"Não é possível iniciar {_move_subject(lot, lot_id)} {_move_when(day, data)}, "
        f"às {minute // 60:02d}:{minute % 60:02d}, "
        f"em {machine_id}: {detail} O plano não foi alterado.",
        gate_report=gate_report,
        causes=causes or _gate_causes(gate_report, data, subject=lot_id),
        suggestion=suggestion,
    )


def _gate_causes(gate_report: dict | None, data, lots=None, subject=None) -> list[str]:
    """Causes from a gate report's physical violations (``plans.refusal``)."""
    return _violation_causes((gate_report or {}).get("violations") or [], data, lots, subject)


def _violation_causes(violations, data, lots=None, subject=None) -> list[str]:
    from backend.plans.refusal import refusal_causes

    return refusal_causes(
        [item for item in violations if isinstance(item, dict)], data,
        lots=lots, subject=subject,
    )


def _gate_failure_kinds(gate_report: dict | None) -> list[str]:
    violations = (gate_report or {}).get("violations") or []
    return sorted({
        str(item.get("kind") or item.get("type") or "?")
        for item in violations if isinstance(item, dict)
    })


def _replan_around_fixed_lot(
    candidate_data: EngineData,
    config: FactoryConfig,
    source_lots: list[Lot],
    protection,
    frozen_proofs: dict,
    lot: Lot,
    template: Segment,
    target_day: int,
    target_machine: str,
    target_start_min: int,
    optimization_mode: str,
    cancel_event: threading.Event | None,
    time_budget_s: float,
    now: datetime | None = None,
    declared: bool = False,
) -> ScheduleResult | None:
    """Place the moved lot exactly, then allocate the rest around it.

    ``protection`` (``frozen.ProtectedPlan``) is kept as in the baseline; the
    rest of each started lot is re-allocated as its remainder (rule 4). The
    moved lot is not started work: it is pinned inside the same allocation
    as the other lots (never credited as stock), so the plan is checked with
    every lot of its operation. Raises ``ManualMoveError`` with the reason
    when no valid plan keeps the lot there. Lots of the legacy engine keep
    the previous attempt (``None`` when it finds no plan).

    ``declared``: the lot is recorded as run from a time of today already
    gone (decisão do Luís, 20/10/2026). It is placed first, judged before
    now only by calendar, material and unavailabilities, and kept as frozen
    work (credited on the days of its deliveries, like a pinned lot); the
    rest goes after now. The plan carries the history boundary of now.
    """
    from backend.planning_control import planning_scope
    from backend.plans.frozen import (
        _current_planning_day,
        _install_frozen_reservations,
        _splice_frozen_started_lots,
        calculation_now,
        elapsed_on_planning_day,
    )
    from backend.scheduler.canonical import preserved_lot_proofs

    if not declared and not _reallocation_ignores_target(source_lots, protection):
        return _legacy_replan_around_fixed_lot(
            candidate_data, config, source_lots, protection, frozen_proofs, lot, template,
            target_day, target_machine, target_start_min, optimization_mode,
            cancel_event, time_budget_s, now,
        )

    def refused(detail, gate_report=None, causes=None):
        causes = causes or _gate_causes(gate_report, candidate_data, source_lots, lot.id)
        logger.info(
            "Movimento de %s recusado: %s %s %s", lot.id, detail,
            _gate_failure_kinds(gate_report), " | ".join(causes[:3]),
        )
        return _refused_move(
            lot.id, target_day, target_start_min, target_machine, candidate_data, detail,
            gate_report=gate_report, causes=causes, lot=lot,
        )

    now = calculation_now(config, now)
    freeze_day = _current_planning_day(candidate_data, config, now)
    now_min = elapsed_on_planning_day(freeze_day, candidate_data, config, now)
    frozen_segments = list(protection.segments)
    partial = list(protection.partial)
    pinned_segments = _materialize_target(
        frozen_segments, lot, template, candidate_data, config,
        target_day, target_machine, target_start_min, partial_layout=True,
        elapsed_until=(freeze_day, now_min) if declared else None,
    )
    protected_lots = list(protection.lots)
    not_started = set(protection.pinned)
    builder_pins = {lot.id: (target_machine, pinned_segments)}
    if declared:
        frozen_segments = [*frozen_segments, *pinned_segments]
        protected_lots = [*protected_lots, lot]
        not_started.add(lot.id)
        builder_pins = None
    protected_ids = {item.id for item in protected_lots}
    rests = {original.id: rest for original, rest in partial}
    residual_data = copy.deepcopy(candidate_data)
    residual_data.plan_anchors = [
        anchor for anchor in residual_data.plan_anchors
        if anchor.lot_id not in protected_ids and anchor.lot_id != lot.id
    ]
    _install_frozen_reservations(
        residual_data, frozen_segments, protected_lots, freeze_day, config, partial,
        now_min=now_min, pinned=not_started,
    )
    reasons: list[str] = []
    violations: list[dict] = []
    with planning_scope(timeout_s=time_budget_s, cancel_event=cancel_event):
        result = _allocate_existing_lots(
            residual_data, source_lots=[
                rests.get(item.id, item) for item in source_lots
                if item.id not in protected_ids
            ], config=config, cancel_event=cancel_event,
            time_budget_s=time_budget_s, now=now,
            pinned=builder_pins, reasons=reasons,
            violations=violations,
        )
        if result is None:
            # Causes read the full data: the residual copy has no plan anchors,
            # so it could not say which lots were pinned by hand.
            raise refused(
                reasons[0] if reasons else _NO_ROOM,
                causes=_violation_causes(violations, candidate_data, source_lots, lot.id),
            )
        result = _splice_frozen_started_lots(
            result, frozen_segments, protected_lots, partial, not_started,
        )
        if declared:
            from backend.plans.frozen import planning_boundary

            result.history_boundary = planning_boundary(freeze_day, now_min)
        if not _preserves_production(result, source_lots):
            raise refused(_QUANTITIES_CHANGED)
        if not _keeps_frozen(result.segments, frozen_segments):
            raise refused(_HISTORY_CHANGED)
        if frozen_proofs:
            frozen_ids = set(frozen_proofs)
            actual_proofs = preserved_lot_proofs(
                [item for item in result.segments if item.lot_id in frozen_ids],
                [item for item in result.lots if item.id in frozen_ids],
            )
            if actual_proofs != frozen_proofs:
                raise refused(_HISTORY_CHANGED)
        validation_data = copy.copy(candidate_data)
        validation_data.preserved_lot_proofs = frozen_proofs
        if result.history_boundary is not None:
            validation_data.history_boundary = list(result.history_boundary)
        result.score = compute_score(result.segments, result.lots, validation_data, config)
        result.gate_report = build_gate_report(
            result.segments, result.lots, result.score, validation_data, config,
        )
        if not (
            result.gate_report.get("physical_gate_passed")
            and result.gate_report.get("coverage_gate_passed")
        ):
            raise refused(_REORGANISED_INVALID, result.gate_report)
        if not _matches_target(
            _production_start(result.segments, lot.id),
            day=target_day, minute=target_start_min, machine=target_machine,
        ):
            raise refused(_TARGET_MISSED, result.gate_report)
    return result


def _legacy_replan_around_fixed_lot(
    candidate_data: EngineData,
    config: FactoryConfig,
    source_lots: list[Lot],
    protection,
    frozen_proofs: dict,
    lot: Lot,
    template: Segment,
    target_day: int,
    target_machine: str,
    target_start_min: int,
    optimization_mode: str,
    cancel_event: threading.Event | None,
    time_budget_s: float,
    now: datetime | None = None,
) -> ScheduleResult | None:
    """Legacy engine (lots without material released by quantity): place the
    moved lot exactly, then allocate the rest around it.

    ``protection`` (``frozen.ProtectedPlan``) is kept as in the baseline; the
    rest of each started lot is re-allocated as its remainder (rule 4).
    """
    from backend.planning_control import planning_scope
    from backend.plans.frozen import (
        _current_planning_day,
        _install_frozen_reservations,
        _splice_frozen_started_lots,
        calculation_now,
        elapsed_on_planning_day,
    )
    from backend.scheduler.canonical import preserved_lot_proofs

    now = calculation_now(config, now)
    freeze_day = _current_planning_day(candidate_data, config, now)
    frozen_segments = list(protection.segments)
    partial = list(protection.partial)
    anchored_segments = _materialize_target(
        frozen_segments, lot, template, candidate_data, config,
        target_day, target_machine, target_start_min,
    )
    protected_segments = [*frozen_segments, *anchored_segments]
    protected_lots = [*protection.lots, lot]
    protected_ids = {item.id for item in protected_lots}
    rests = {original.id: rest for original, rest in partial}
    residual_data = copy.deepcopy(candidate_data)
    residual_data.plan_anchors = [
        anchor for anchor in residual_data.plan_anchors if anchor.lot_id not in protected_ids
    ]
    _install_frozen_reservations(
        residual_data, protected_segments, protected_lots, freeze_day, config, partial,
        now_min=elapsed_on_planning_day(freeze_day, candidate_data, config, now),
    )
    with planning_scope(timeout_s=time_budget_s, cancel_event=cancel_event):
        result = _allocate_existing_lots(
            residual_data, source_lots=[
                rests.get(item.id, item) for item in source_lots
                if item.id not in protected_ids
            ], config=config, cancel_event=cancel_event,
            time_budget_s=time_budget_s, now=now,
        )
        if result is None:
            return None
        result = _splice_frozen_started_lots(
            result, protected_segments, protected_lots, partial,
        )
        if not _preserves_production(result, source_lots):
            return None
        if not _keeps_frozen(result.segments, frozen_segments):
            return None
        if frozen_proofs:
            frozen_ids = set(frozen_proofs)
            actual_proofs = preserved_lot_proofs(
                [item for item in result.segments if item.lot_id in frozen_ids],
                [item for item in result.lots if item.id in frozen_ids],
            )
            if actual_proofs != frozen_proofs:
                return None
        validation_data = copy.copy(candidate_data)
        validation_data.preserved_lot_proofs = frozen_proofs
        result.score = compute_score(result.segments, result.lots, validation_data, config)
        result.gate_report = build_gate_report(
            result.segments, result.lots, result.score, validation_data, config,
        )
        if (
            result.gate_report.get("physical_gate_passed")
            and result.gate_report.get("coverage_gate_passed")
            and _matches_target(
                _production_start(result.segments, lot.id),
                day=target_day, minute=target_start_min, machine=target_machine,
            )
        ):
            return result
    return None


def _fixed_positions_move(
    segments, lots, lot_id, target_day, machine_id, start_min,
    data, config, candidate_data, frozen_proofs, frozen_segments=(),
):
    """Attempt one candidate with all other positions fixed; not an infeasibility proof.

    ``frozen_segments``: production that must stay exactly as it is (rule 4).
    """
    from backend.scheduler.canonical import preserved_lot_proofs

    candidate_segments = copy.deepcopy(segments)
    candidate_lots = copy.deepcopy(lots)
    fallback_lot = next(item for item in candidate_lots if item.id == lot_id)
    fallback_moved = [
        segment for segment in candidate_segments if segment.lot_id == lot_id
    ]
    candidate_segments = [
        segment for segment in candidate_segments if segment.lot_id != lot_id
    ]
    lots_by_id = {item.id: item for item in candidate_lots}
    template = min(
        fallback_moved,
        key=lambda item: (item.day_idx, item.start_min),
    )
    fallback_lot, template = _rebound_target(
        fallback_lot, template, machine_id, data, config,
    )
    candidate_lots = [
        fallback_lot if item.id == lot_id else item for item in candidate_lots
    ]
    created = _materialize_target(
        candidate_segments,
        fallback_lot,
        template,
        data,
        config,
        target_day,
        machine_id,
        start_min,
    )
    candidate_segments.extend(created)
    # Repair the source only after the new placement can prove retained mounting.
    _source_setup_repair(candidate_segments, lots_by_id, fallback_moved, config, data)
    candidate_segments.sort(
        key=lambda item: (item.day_idx, item.machine_id, item.start_min)
    )
    if frozen_proofs:
        frozen_ids = set(frozen_proofs)
        candidate_proofs = preserved_lot_proofs(
            [item for item in candidate_segments if item.lot_id in frozen_ids],
            [item for item in candidate_lots if item.id in frozen_ids],
        )
        if candidate_proofs != frozen_proofs:
            raise ManualMoveError(
                "O movimento alteraria um lote já iniciado; "
                "o histórico deve permanecer intacto."
            )
    if not _keeps_frozen(candidate_segments, list(frozen_segments)):
        raise ManualMoveError(_FROZEN_CHANGED)
    validation_data = copy.copy(candidate_data)
    validation_data.preserved_lot_proofs = frozen_proofs
    score = compute_score(candidate_segments, candidate_lots, validation_data, config)
    gate_report = build_gate_report(
        candidate_segments,
        candidate_lots,
        score,
        validation_data,
        config,
    )
    if not gate_report.get("physical_gate_passed", False):
        raise ManualMoveError(
            "O movimento cria um conflito físico e não pode ser aplicado.",
            gate_report=gate_report,
        )
    anchored_start = _production_start(candidate_segments, lot_id)
    if not _matches_target(
        anchored_start,
        day=target_day,
        minute=start_min,
        machine=machine_id,
    ):
        raise ManualMoveError(
            "O motor não conseguiu respeitar exatamente o dia, a hora e "
            "a máquina pedidos.",
            gate_report=gate_report,
        )

    return ScheduleResult(
        candidate_segments, candidate_lots, score, 0, [], [], gate_report=gate_report,
        preserved_lot_proofs=frozen_proofs,
    )


def _finalize_move_candidate(
    result, candidate_data, config, source_lots, frozen_segments=(), lot_id=None, now=None,
    declared=False,
):
    """Improve and validate the complete candidate; ``frozen_segments`` stay as they are.

    ``lot_id``: the requested lot, kept whole where it was placed.
    ``declared``: that lot is recorded as run (it has production before now):
    protected like any started lot and credited on its delivery days.
    """
    from backend.planning_control import improvement_time_budget
    from backend.plans.frozen import (
        _current_planning_day,
        _protected_plan,
        calculation_now,
        improve_preserving_protected_lots,
    )
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.improvement import improvement_gate_summary, physical_signature

    report = dict(result.improvement_report or {})
    signature = physical_signature(result.segments, result.lots)
    # Residual and fallback allocations are not the state an earlier report
    # checked. Improve the complete candidate, with the requested lot fixed.
    if report.get("final_signature") != signature:
        budget = improvement_time_budget(MANUAL_MOVE_BUDGET_S)
        if budget > 0:
            now = calculation_now(config, now)
            freeze_day = _current_planning_day(candidate_data, config, now)
            # Rule 4: of a started lot only what started is fixed, its rest
            # may still improve. The requested lot is not started work: it
            # stays in the improved plan with every lot of its operation
            # (protecting it would credit it as stock from day 0 and make the
            # plan invalid). Its manual position (plan anchor) is kept by the
            # improvement; it must also keep its exact segments, or the
            # improvement is not used. What precedes it may still be improved
            # (the merged plan is validated, so its mounting is never lost).
            if lot_id is None or declared:
                protection = _protected_plan(result, freeze_day, candidate_data, config, now=now)
            else:
                protection = _move_protection(
                    result, freeze_day, candidate_data, config, lot_id, now=now,
                )
            pinned = set(protection.pinned) | ({lot_id} if declared else set())
            unimproved = result
            result, report = improve_preserving_protected_lots(
                result, candidate_data, copy.deepcopy(candidate_data), config,
                protection.segments, protection.lots, freeze_day, time_budget_s=budget,
                partial=protection.partial, now=now,
                cut=protection.cut, pinned=pinned,
            )
            if lot_id is not None and _lot_rows(result.segments, lot_id) != _lot_rows(
                unimproved.segments, lot_id,
            ):
                result = unimproved
                report = {
                    **report, "status": "partial", "stop_reason": "moved_lot_changed",
                    "rolled_back_moves": int(report.get("rolled_back_moves", 0))
                    + int(report.get("moves_accepted", 0)),
                    "moves_accepted": 0, "accepted_by_scope": {},
                    "final": report.get("reference"), "final_signature": signature,
                }
        else:
            report = {"status": "not_evaluated", "stop_reason": "no_time_left"}
    planning_checkpoint()
    if not _preserves_production(result, source_lots):
        raise ManualMoveError("A verificação alterou as quantidades ou identidades dos lotes.")
    if not _keeps_frozen(result.segments, list(frozen_segments)):
        raise ManualMoveError(_FROZEN_CHANGED)
    view = result_validation_data(candidate_data, result)
    old_gate = dict(result.gate_report or {})
    result.gate_report = build_gate_report(
        result.segments, result.lots, result.score, view, config,
    )
    for key, value in old_gate.items():
        result.gate_report.setdefault(key, value)
    if not (result.gate_report.get("physical_gate_passed")
            and result.gate_report.get("coverage_gate_passed")):
        raise ManualMoveError(
            "O movimento cria um conflito físico ou de quantidade e não pode ser aplicado.",
            gate_report=result.gate_report,
        )
    result.improvement_report = report
    result.gate_report["improvement"] = improvement_gate_summary(
        report, result.segments, result.lots, view, config,
    )
    planning_checkpoint()
    return result


def move_lot(
    segments: list[Segment],
    lots: list[Lot],
    baseline_score: dict,
    data: EngineData,
    config: FactoryConfig,
    *,
    lot_id: str,
    target_day: int,
    target_machine: str | None = None,
    target_start_min: int | None = None,
    reason: str = "",
    author: str = "utilizador",
    optimization_mode: str = "quick",
    progress: Callable[[str, int, str], None] | None = None,
    cancel_event: threading.Event | None = None,
    now: datetime | None = None,
) -> ManualMoveResult:
    """Verify a move within one budget, including every fallback and validation.

    ``now``: the instant of the check (default: the calculation's,
    ``frozen.calculation_now``), one for the whole check (AGENTS §2 rule 4).
    """
    from backend.calendar import fixed_factory_clock
    from backend.plans.frozen import calculation_now

    now = calculation_now(config, now)
    with planning_scope(
        timeout_s=MANUAL_MOVE_BUDGET_S, cancel_event=cancel_event,
    ), fixed_factory_clock(now):
        return _move_lot(
            segments, lots, baseline_score, data, config,
            lot_id=lot_id, target_day=target_day, target_machine=target_machine,
            target_start_min=target_start_min, reason=reason, author=author,
            optimization_mode=optimization_mode, progress=progress,
            cancel_event=cancel_event, now=now,
        )


def _fit_machines(lot: Lot, machine_id: str, data: EngineData) -> list[str]:
    """The requested machine, then the other machine of the lot's tool when
    it is active (``lot_tool_machines``, E13)."""
    active = {machine.id for machine in data.machines}
    machines = [machine_id]
    for other in lot_tool_machines(lot, data):
        if other and other not in machines and other in active:
            machines.append(other)
    return machines


def _fit_timeline(data, config, protected_segments, lot, template, machine_id, freeze_day, now_min):
    """``(timeline, setup_min, prod_min)`` of the lot on ``machine_id``.

    Durations as the move computes them on that machine (``_rebound_target``,
    the setup of ``_materialize_target``).
    """
    from backend.plans.move_fit import MachineTimeline

    rebound_lot, rebound_template = _rebound_target(
        copy.deepcopy(lot), template, machine_id, data, config,
    )
    setup = float(max(
        rebound_lot.setup_min, rebound_template.run_setup_min, rebound_template.setup_min,
    ))
    timeline = MachineTimeline(
        data, config, protected_segments, rebound_lot, rebound_template, machine_id,
        freeze_day=freeze_day, now_min=now_min,
    )
    return timeline, setup, float(rebound_lot.prod_min)


def _move_suggestion(
    data, config, protected_segments, lot, template, machines, from_day, from_min,
    freeze_day, now_min, *, after: bool = False,
) -> dict | None:
    """The first start from the requested one where the lot fits in one production.

    Same machine first, then the alternative. Every start offered also passes
    the move's own quick checks (calendar, material, unavailability,
    operators: ``_check_immutable_start``). A suggestion, never applied.
    """
    from backend.plans.move_fit import DAY_MIN, at_label, earliest_fit
    from backend.scheduler.material_quantities import released_quantity

    for machine_id in machines:
        planning_checkpoint()
        timeline, setup, prod = _fit_timeline(
            data, config, protected_segments, lot, template, machine_id, freeze_day, now_min,
        )

        def accept(candidate, machine_id=machine_id):
            day, minute = divmod(candidate, DAY_MIN)
            try:
                _check_immutable_start(
                    data, config, protected_segments, lot, template, day, minute,
                    machine_id, mount_layouts=(protected_segments,),
                )
            except ManualMoveError:
                return False
            return True

        found = earliest_fit(
            timeline, setup, prod, from_day * DAY_MIN + int(from_min), after=after,
            day_ok=lambda day: released_quantity(lot, day) > 0, accept=accept,
        )
        if found is not None:
            day, minute = divmod(found, DAY_MIN)
            return {
                "day": int(day), "start_min": int(minute), "machine": machine_id,
                "label": f"{at_label(found, data)} ({machine_id})",
            }
    return None


def _later_suggestion(
    data, config, protected_segments, lot, template, machine_id, target_day, start_min,
    freeze_day, now_min,
) -> dict | None:
    """After a refusal for other reasons: the next start where the lot fits in a row.

    Only windows later than the requested start (that one fits in a row and
    still failed); a cheap hint, never a promise. ``None`` when the search
    itself cannot run (out of time, or anything unexpected).
    """
    from backend.planning_control import PlanningCancelled
    from backend.plans.move_fit import one_production_lot

    if not one_production_lot(lot):
        return None
    try:
        return _move_suggestion(
            data, config, protected_segments, lot, template,
            _fit_machines(lot, machine_id, data), target_day, start_min,
            freeze_day, now_min, after=True,
        )
    except PlanningCancelled:
        raise
    except Exception:  # a hint must never hide the refusal it goes with
        logger.warning("Sugestão de início não calculada para %s", lot.id, exc_info=True)
        return None


def _contiguous_fit_refusal(
    data, config, protected_segments, lot, template, target_day, start_min, machine_id,
    *, lots, layouts, freeze_day, now_min,
) -> ManualMoveError | None:
    """Refusal, before any reorganisation, of a lot that cannot be one production.

    Decision of 15/10/2026 (Luís): setup + production must fit in a row from
    the requested start, in working time, before the next work that stays
    where it is (``plans.move_fit``). Only a certain impossibility is refused
    here; anything else goes on to the full check.
    """
    from backend.plans.move_fit import DAY_MIN, one_production_lot, refusal_texts
    from backend.scheduler.setup_identity import retained_setup_at, segment_setup_identity

    if not one_production_lot(lot):
        return None
    started = time.perf_counter()
    timeline, setup, prod = _fit_timeline(
        data, config, protected_segments, lot, template, machine_id, freeze_day, now_min,
    )
    identity = segment_setup_identity(replace(
        template, tool_id=lot.tool_id, twin_outputs=lot.twin_outputs,
    ))
    # The setup the move places around the work that stays (``_materialize_target``
    # with ``partial_layout``): saved only right after the same mounting.
    shown_setup = 0.0 if any(
        item.machine_id == machine_id
        and (item.day_idx, item.end_min) == (target_day, start_min)
        and segment_setup_identity(item) == identity
        for item in protected_segments
    ) else setup
    # A mounted tool saves the setup on some layout: the least the lot needs.
    if any(
        retained_setup_at(list(layout), machine_id, identity, target_day, start_min)
        for layout in layouts
    ):
        setup = 0.0
    verdict = timeline.check(target_day * DAY_MIN + int(start_min), setup, prod)
    if verdict is None or verdict.fits or verdict.excusable:
        return None
    if not verdict.setup_blocked:
        verdict = replace(verdict, setup_min=shown_setup)
    lots_by_id = {item.id: item for item in lots}
    detail, causes = refusal_texts(verdict, timeline, data, lots_by_id)
    suggestion = _move_suggestion(
        data, config, protected_segments, lot, template,
        _fit_machines(lot, machine_id, data), target_day, start_min, freeze_day, now_min,
    )
    logger.info(
        "Movimento de %s recusado antes de planear (%.0f ms): %s Sugestão: %s",
        lot.id, (time.perf_counter() - started) * 1000, detail,
        suggestion["label"] if suggestion else "nenhuma",
    )
    return _refused_move(
        lot.id, target_day, start_min, machine_id, data, detail,
        causes=causes, lot=lot, suggestion=suggestion,
    )


def _move_lot(
    segments: list[Segment],
    lots: list[Lot],
    baseline_score: dict,
    data: EngineData,
    config: FactoryConfig,
    *,
    lot_id: str,
    target_day: int,
    target_machine: str | None = None,
    target_start_min: int | None = None,
    reason: str = "",
    author: str = "utilizador",
    optimization_mode: str = "quick",
    progress: Callable[[str, int, str], None] | None = None,
    cancel_event: threading.Event | None = None,
    now: datetime | None = None,
) -> ManualMoveResult:
    """Anchor one complete lot and reoptimise every other production.

    ``target_start_min`` is the exact production start. Any required setup is
    placed immediately before it.
    """
    started = time.perf_counter()
    if target_day < 0 or target_day >= data.n_days:
        raise ManualMoveError(f"Dia alvo fora do horizonte: {target_day}.")
    from types import SimpleNamespace

    from backend.plans.frozen import (
        _current_planning_day,
        calculation_now,
        elapsed_on_planning_day,
        planning_boundary,
        with_current_material,
    )

    # The boundary is the current factory minute (AGENTS §2 rule 4, 13/10/2026);
    # the helpers below read the same instant (``move_lot`` fixes the clock).
    now = calculation_now(config, now)
    freeze_day = _current_planning_day(data, config, now)
    now_min = elapsed_on_planning_day(freeze_day, data, config, now)
    # A start of today already gone records what ran (decisão do Luís,
    # 20/10/2026): the lot ran from there, what the plan had on its machine
    # since then did not, and the rest is replanned from now. Earlier days
    # stay as they are.
    declared = target_start_min is not None and (target_day, int(target_start_min)) < (
        freeze_day, now_min,
    )
    if declared and target_day < freeze_day:
        raise ManualMoveError(_past_day_text(target_day, int(target_start_min), data))
    input_lots = lots
    # A plan of material version 1-2 is moved under version 3 (AGENTS §2);
    # each lot taken over keeps the productions it has here, never more.
    # Counted at the plan's stored history boundary: a move result carries
    # none of its own, so every validation of it (the final view below, the
    # apply and the commit) reads that one, and a history break it does not
    # judge must not be allowed as a production either. A record of what
    # ran carries the boundary of now.
    boundary = (
        planning_boundary(freeze_day, now_min) if declared
        else getattr(data, "history_boundary", None)
    )
    lots = with_current_material(
        SimpleNamespace(segments=segments, lots=lots), data, config, boundary,
    ).lots

    candidate_segments = copy.deepcopy(segments)
    candidate_lots = copy.deepcopy(lots)
    lot = next((item for item in candidate_lots if item.id == lot_id), None)
    if lot is None:
        raise ManualMoveError(f"Lote {lot_id} não existe.")

    moved_segments = [segment for segment in candidate_segments if segment.lot_id == lot_id]
    if not moved_segments:
        raise ManualMoveError(f"Lote {lot_id} não tem produção materializada.")

    from backend.planning_control import PlanningCancelled, PlanningTimeout
    from backend.plans.frozen import (
        NoValidCandidateError,
        _frozen_started_lots,
        started_before,
    )

    baseline_result = ScheduleResult(
        segments=segments,
        lots=lots,
        score=baseline_score,
        time_ms=0,
        warnings=[],
        operator_alerts=[],
    )
    started_segments, _ = _frozen_started_lots(baseline_result, freeze_day, now_min)
    if any(segment.lot_id == lot_id for segment in started_segments):
        raise ManualMoveError(
            f"Lote {lot_id} já iniciado está congelado e não pode ser movido."
        )

    current_machine = moved_segments[0].machine_id
    machine_id = target_machine or current_machine
    # The machines of its tool, by its operations: a lot an earlier
    # calculation put on its alternative may come back to its primary (E13).
    if machine_id not in lot_tool_machines(lot, data):
        raise ManualMoveError(
            f"Máquina {machine_id} não é primária nem alternativa do lote {lot_id}."
        )
    active_machines = {machine.id for machine in data.machines}
    if machine_id not in active_machines:
        raise ManualMoveError(f"Máquina {machine_id} não está ativa.")

    first_moved = min(
        moved_segments,
        key=lambda segment: (segment.day_idx, segment.start_min),
    )
    source_start = _production_start(moved_segments, lot_id)
    if source_start is None:
        raise ManualMoveError(f"Lote {lot_id} não tem produção materializada.")
    start_min = int(
        target_start_min
        if target_start_min is not None
        else source_start[1]
    )
    if not any(
        shift.start_min <= start_min < shift.end_min for shift in config.shifts
    ):
        raise ManualMoveError("A hora alvo tem de ficar dentro de um turno ativo.")
    if target_day >= len(data.workdays):
        raise ManualMoveError(f"Dia alvo fora do calendário: {target_day}.")
    if not declared and (target_day, start_min) < (freeze_day, now_min):
        raise ManualMoveError(_elapsed_text(target_day, start_min, data, now_min))
    declaration = None
    if declared:
        setup_start = _declared_setup_start(
            data, config, [segment for segment in segments if segment.lot_id != lot_id],
            lot, first_moved, target_day, start_min, machine_id,
        )
        declaration = (target_day, setup_start, now_min, machine_id, lot.tool_id)
        _refuse_fixed_displaced(
            [segment for segment in segments if segment.lot_id != lot_id],
            lots, data, declaration, lot, target_day, start_min, machine_id,
        )
    # Rule 4 (AGENTS §2): only what started (and the run mounted at the
    # boundary, with its mount supplier) is fixed; the rest of a started lot
    # may be re-allocated, never re-sized.
    protection = _move_protection(
        baseline_result, freeze_day, data, config, lot_id, now=now, declaration=declaration,
    )
    frozen_segments = protection.segments
    frozen_proofs = _started_lot_proofs(protection)
    candidate_segments = [segment for segment in candidate_segments if segment.lot_id != lot_id]
    _check_immutable_start(
        data, config, frozen_segments, lot, first_moved,
        target_day, start_min, machine_id,
        mount_layouts=(frozen_segments,) if declared else (candidate_segments, frozen_segments),
        elapsed_until=(freeze_day, now_min) if declared else None,
    )
    # One production or nothing (AGENTS §6, 15/10/2026): refused here, in
    # milliseconds, when it is certain; otherwise the full check decides.
    # A record of what ran is placed as it ran: the full check judges it.
    fit_refusal = None if declared else _contiguous_fit_refusal(
        data, config, frozen_segments, lot, first_moved, target_day, start_min, machine_id,
        lots=lots, layouts=(frozen_segments, candidate_segments),
        freeze_day=freeze_day, now_min=now_min,
    )
    if fit_refusal is not None:
        raise fit_refusal
    timezone = ZoneInfo(config.timezone)
    target_date = datetime.fromisoformat(str(data.workdays[target_day])[:10])
    target_at = target_date.replace(
        hour=start_min // 60,
        minute=start_min % 60,
        tzinfo=timezone,
    ).isoformat(timespec="minutes")

    candidate_data = copy.deepcopy(data)
    candidate_data.plan_anchors = [
        anchor for anchor in candidate_data.plan_anchors if anchor.lot_id != lot_id
    ]
    from backend.plans.manual_edits import EXECUTED

    candidate_data.plan_anchors.append(
        PlanAnchor(
            lot_id=lot_id,
            machine_id=machine_id,
            start_at=target_at,
            reason=reason,
            author=author,
            kind=EXECUTED if declared else "",
        )
    )
    if declared:
        # Crew and operators before now are not judged: it happened.
        candidate_data.history_boundary = planning_boundary(freeze_day, now_min)
    if progress:
        progress("scheduling", 35, "A verificar o pedido mantendo as outras produções")
    fixed_causes: list[str] = []
    result = None
    try:
        # A record of what ran: only the attempt that places the lot first
        # (``_replan_around_fixed_lot``) keeps it as it ran.
        if not declared:
            result = _fixed_positions_move(
                segments, lots, lot_id, target_day, machine_id, start_min,
                data, config, candidate_data, frozen_proofs, frozen_segments,
            )
    except ManualMoveError as exc:
        logger.info("Movimento de %s com as outras produções fixas recusado: %s", lot_id, exc)
        # What collides when nothing else moves: the planner's clearest "why"
        # when the reorganised attempt has no causes of its own.
        fixed_causes = [
            f"Mantendo as outras produções onde estão: {cause[0].lower()}{cause[1:]}"
            for cause in exc.causes or _gate_causes(
                exc.gate_report, candidate_data, lots, lot_id,
            )
            if cause and not cause.startswith("…")
        ]
        result = None
    # Why the reorganised attempt refused the move (shown when nothing works).
    refusal: ManualMoveError | None = None
    # With material released by quantity the reallocation builder does not
    # read plan anchors: it leaves the moved lot where the campaigns put it
    # and cannot honour the requested start. The budget then goes straight
    # to the attempt that fixes the moved lot first (_replan_around_fixed_lot).
    if result is None and not declared and not _reallocation_ignores_target(lots, protection):
        _legacy_logger.warning("motor antigo usado: %s", "manual_move._move_lot")
        if progress:
            progress("scheduling", 50, "A reorganizar as produções existentes")
        try:
            search_budget = (
                remaining_time(MANUAL_MOVE_BUDGET_S)
                - closing_reserve(MANUAL_MOVE_BUDGET_S)
            )
            result = _allocate_existing_lots(
                candidate_data, source_lots=lots, config=config,
                baseline_result=baseline_result, cancel_event=cancel_event,
                time_budget_s=max(0.0, search_budget), protection=protection,
            )
        except (NoValidCandidateError, PlanningTimeout):
            if cancel_event is not None and cancel_event.is_set():
                raise PlanningCancelled("O movimento foi cancelado.") from None
            result = None
    planning_checkpoint()
    if result is not None and not (
        _preserves_production(result, lots) and _keeps_frozen(result.segments, frozen_segments)
    ):
        result = None
    if progress:
        progress("validating", 80, "A validar recursos e riscos")
    candidate_segments = result.segments if result is not None else []
    candidate_lots = result.lots if result is not None else []
    score = result.score if result is not None else {}
    gate_report = {}
    if result is not None:
        validation_data = copy.copy(candidate_data)
        validation_data.preserved_lot_proofs = frozen_proofs
        gate_report = result.gate_report or build_gate_report(
            candidate_segments, candidate_lots, score, validation_data, config,
        )
    anchored_start = _production_start(candidate_segments, lot_id)
    if result is None or not gate_report.get("physical_gate_passed", False) or not _matches_target(
        anchored_start,
        day=target_day,
        minute=start_min,
        machine=machine_id,
    ):
        remaining_budget = (
            remaining_time(MANUAL_MOVE_BUDGET_S)
            - closing_reserve(MANUAL_MOVE_BUDGET_S)
        )
        if remaining_budget > 2:
            try:
                rebound_lot, rebound_template = _rebound_target(
                    lot, first_moved, machine_id, data, config,
                )
                fixed_result = _replan_around_fixed_lot(
                    candidate_data, config, lots, protection, frozen_proofs,
                    rebound_lot, rebound_template,
                    target_day, machine_id, start_min, optimization_mode,
                    cancel_event, remaining_budget,
                    **({"now": now, "declared": True} if declared else {}),
                )
            except ManualMoveInconclusive:
                fixed_result = None
            except ManualMoveError as exc:
                refusal = exc
                fixed_result = None
            except (NoValidCandidateError, PlanningTimeout):
                if cancel_event is not None and cancel_event.is_set():
                    raise PlanningCancelled("O movimento foi cancelado.") from None
                fixed_result = None
            if fixed_result is not None:
                result = fixed_result
                candidate_segments = result.segments
                candidate_lots = result.lots
                score = result.score
                gate_report = result.gate_report or {}
                anchored_start = _production_start(candidate_segments, lot_id)
    if result is None or not gate_report.get("physical_gate_passed", False) or not _matches_target(
        anchored_start,
        day=target_day,
        minute=start_min,
        machine=machine_id,
    ):
        if cancel_event is not None and cancel_event.is_set():
            raise PlanningCancelled("O movimento foi cancelado.")
        failure = refusal
        if failure is None:
            failure = _inconclusive_move(
                lot_id, target_day, start_min, machine_id, lot=lot, data=candidate_data,
            )
        if not failure.causes:
            failure.causes = list(fixed_causes)
        if failure.suggestion is None and not declared:
            failure.suggestion = _later_suggestion(
                data, config, frozen_segments, lot, first_moved, machine_id,
                target_day, start_min, freeze_day, now_min,
            )
        raise failure
    complete = ScheduleResult(
        candidate_segments, candidate_lots, score, 0, [], [], gate_report=gate_report,
        improvement_report=(result.improvement_report if result is not None
                            and result.segments == candidate_segments
                            and result.lots == candidate_lots else None),
        preserved_lot_proofs=frozen_proofs,
        history_boundary=planning_boundary(freeze_day, now_min) if declared else None,
    )
    # A refusal of the final validation is a real reason, shown as it is.
    complete = _finalize_move_candidate(
        complete, candidate_data, config, lots, frozen_segments, lot_id=lot_id,
        **({"now": now, "declared": True} if declared else {}),
    )
    candidate_segments, candidate_lots = complete.segments, complete.lots
    notice = None
    if declared:
        # The commit guard's own reading, now: only the record changes the
        # morning (``frozen._declared_today``).
        if _declared_history_changes(
            segments, input_lots, data, complete, candidate_data, config, freeze_day, now,
        ):
            raise _refused_move(
                lot_id, target_day, start_min, machine_id, data, _HISTORY_CHANGED, lot=lot,
            )
        notice = _executed_notice(
            complete, lot_id, declaration, start_min, segments, candidate_data,
        )
    # Its setup too: nothing new is placed in time already gone today.
    elif any(
        segment.lot_id == lot_id and started_before(segment, freeze_day, now_min)
        for segment in candidate_segments
    ):
        raise ManualMoveError(_elapsed_text(target_day, start_min, data, now_min, setup=True))
    score, gate_report = complete.score, complete.gate_report
    if progress:
        progress("finalizing", 90, "A preparar a comparação")
    delivery_warnings = []
    old_otd_d = float(baseline_score.get("otd_d", 0) or 0)
    new_otd_d = float(score.get("otd_d", 0) or 0)
    if new_otd_d < old_otd_d - 0.001:
        delivery_warnings.append(f"OTD-D desce de {old_otd_d:.1f}% para {new_otd_d:.1f}%.")
    old_tardy = int(baseline_score.get("tardy_count", 0) or 0)
    new_tardy = int(score.get("tardy_count", 0) or 0)
    if new_tardy > old_tardy:
        delivery_warnings.append(f"Cria {new_tardy - old_tardy} novo(s) atraso(s).")
    if int(gate_report["metrics"].get("early_window_violations", 0) or 0):
        delivery_warnings.append(
            "O plano inicia produção antes da libertação de material calculada "
            "a partir da entrega ou do envio para subcontratação."
        )

    requires_confirmation = bool(gate_report.get("requires_approval"))

    return ManualMoveResult(
        segments=candidate_segments,
        lots=candidate_lots,
        score=score,
        delta=_delta(baseline_score, score),
        improvement_report=copy.deepcopy(complete.improvement_report),
        gate_report=gate_report,
        lot_id=lot_id,
        source_days=sorted({segment.day_idx for segment in moved_segments}),
        target_day=target_day,
        target_start_min=start_min,
        target_machine=machine_id,
        requires_confirmation=requires_confirmation,
        delivery_warnings=delivery_warnings,
        time_ms=round((time.perf_counter() - started) * 1000, 1),
        planning_now=now.isoformat(),
        executed=declared,
        notice=notice,
        history_boundary=list(complete.history_boundary) if declared else None,
    )
