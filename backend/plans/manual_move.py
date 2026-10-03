"""Exact lot movement with protected history and complete-plan validation."""

from __future__ import annotations

import copy
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

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


class ManualMoveError(ValueError):
    """A requested move cannot return an applicable candidate."""

    def __init__(self, message: str, *, gate_report: dict | None = None) -> None:
        super().__init__(message)
        self.gate_report = gate_report


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
        group=config.machine_groups.get(machine_id, "Grandes"), required=required,
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
    group = config.machine_groups.get(machine_id, "Grandes")
    capacity = max(1, int(config.setup_crews_by_group.get(group, 1)))
    events: list[tuple[float, int]] = [(start, 1), (start + setup_min, -1)]
    for segment in segments:
        if segment is ignore or segment.day_idx != day or segment.setup_min <= 0:
            continue
        if config.machine_groups.get(segment.machine_id, "Grandes") != group:
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
    group = config.machine_groups.get(machine_id, "Grandes")
    conflicting = sorted(
        (
            segment for segment in segments
            if segment.day_idx == day
            and segment.setup_min > 0
            and config.machine_groups.get(segment.machine_id, "Grandes") == group
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


def _check_immutable_start(
    data, config, baseline, lot, template, day, minute, machine_id, freeze_day,
):
    from backend.calendar import is_factory_workday
    from backend.plans.frozen import _protected_lots
    from backend.transform.calendars import calendar_window

    view = calendar_window(data, config, day, from_day=day)
    context = (
        f"Impedido iniciar {lot.id} exatamente no dia {day} "
        f"({str(data.workdays[day])[:10]}), às {minute // 60:02d}:{minute % 60:02d}, "
        f"em {machine_id}. "
    )
    if not is_factory_workday(day, view, config):
        raise ManualMoveError(context + "O calendário da fábrica não permite produção nesse dia.")
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
    protected, _lots, _anchors = _protected_lots(baseline, freeze_day, data, config)
    protected = [segment for segment in protected if segment.lot_id != lot.id]
    for segment in protected:
        if (segment.day_idx == day and segment.start_min <= minute < segment.end_min
                and (segment.machine_id == machine_id or segment.tool_id == lot.tool_id)):
            raise ManualMoveError(
                context + f"Conflito com o lote protegido {segment.lot_id} "
                f"({segment.machine_id}/{segment.tool_id}), das "
                f"{int(segment.start_min) // 60:02d}:{int(segment.start_min) % 60:02d} "
                f"às {segment.end_min // 60:02d}:{segment.end_min % 60:02d}."
            )
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
                group = config.machine_groups.get(machine_id, "Grandes")
                raise ManualMoveError(
                    context + f"Operadores {group}, turno {shift.id}: não há capacidade "
                    f"para {required} operador(es) nesse instante, considerando as "
                    "ausências e as produções protegidas."
                )


def _inconclusive_move(lot_id, day, minute, machine_id):
    return ManualMoveInconclusive(
        f"Verificação inconclusiva para iniciar {lot_id} exatamente no dia {day}, "
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
) -> list[Segment]:
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
    if retained_setup_at(segments, target_machine, identity, target_day, target_start_min):
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
        if not _crew_available(
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
) -> ScheduleResult | None:
    """Allocate existing productions using the shared physical solver, without lot sizing."""
    from backend.plans.frozen import (
        _current_planning_day,
        _install_frozen_reservations,
        _protected_lots,
        _splice_frozen_started_lots,
    )
    from backend.scheduler.global_jit import solve_global_jit
    from backend.scheduler.jit_policy import calendar_holidays
    from backend.scheduler.tool_grouping import create_tool_runs

    planning_checkpoint()
    residual_data = copy.deepcopy(candidate_data)
    protected_segments, protected_lots = [], []
    if baseline_result is not None:
        protected_segments, protected_lots, _ = _protected_lots(
            baseline_result, _current_planning_day(candidate_data, config),
            candidate_data, config,
        )
        _install_frozen_reservations(
            residual_data, protected_segments, protected_lots,
            _current_planning_day(candidate_data, config), config,
        )
    protected_ids = {lot.id for lot in protected_lots}
    movable = copy.deepcopy([lot for lot in source_lots if lot.id not in protected_ids])
    runs = create_tool_runs(
        movable, config=config,
        release_holidays=calendar_holidays(residual_data, -14, residual_data.n_days + 30),
    )
    result = ScheduleResult([], [], {}, 0, [], [])
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
    result = _splice_frozen_started_lots(result, protected_segments, protected_lots)
    if any(segment.day_idx < 0 or segment.day_idx >= candidate_data.n_days
           for segment in result.segments):
        return None
    if not _preserves_production(result, source_lots):
        return None
    result.score = compute_score(result.segments, result.lots, candidate_data, config)
    return result


def _replan_around_fixed_lot(
    candidate_data: EngineData,
    config: FactoryConfig,
    source_lots: list[Lot],
    frozen_segments: list[Segment],
    frozen_lots: list[Lot],
    frozen_proofs: dict,
    lot: Lot,
    template: Segment,
    target_day: int,
    target_machine: str,
    target_start_min: int,
    optimization_mode: str,
    cancel_event: threading.Event | None,
    time_budget_s: float,
) -> ScheduleResult | None:
    from backend.planning_control import planning_scope
    from backend.plans.frozen import (
        _current_planning_day,
        _install_frozen_reservations,
        _splice_frozen_started_lots,
    )
    from backend.scheduler.canonical import preserved_lot_proofs

    anchored_segments = _materialize_target(
        frozen_segments, lot, template, candidate_data, config,
        target_day, target_machine, target_start_min,
    )
    protected_segments = [*frozen_segments, *anchored_segments]
    protected_lots = [*frozen_lots, lot]
    protected_ids = {item.id for item in protected_lots}
    residual_data = copy.deepcopy(candidate_data)
    residual_data.plan_anchors = [
        anchor for anchor in residual_data.plan_anchors if anchor.lot_id not in protected_ids
    ]
    _install_frozen_reservations(
        residual_data, protected_segments, protected_lots,
        _current_planning_day(candidate_data, config), config,
    )
    with planning_scope(timeout_s=time_budget_s, cancel_event=cancel_event):
        result = _allocate_existing_lots(
            residual_data, source_lots=[
                item for item in source_lots if item.id not in protected_ids
            ], config=config, cancel_event=cancel_event,
            time_budget_s=time_budget_s,
        )
        if result is None:
            return None
        result = _splice_frozen_started_lots(
            result, protected_segments, protected_lots,
        )
        if not _preserves_production(result, source_lots):
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
    data, config, candidate_data, frozen_proofs,
):
    """Attempt one candidate with all other positions fixed; not an infeasibility proof."""
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


def _finalize_move_candidate(result, candidate_data, config, source_lots):
    from backend.planning_control import improvement_time_budget
    from backend.plans.frozen import (
        _current_planning_day,
        _protected_lots,
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
            freeze_day = _current_planning_day(candidate_data, config)
            protected_segments, protected_lots, _ = _protected_lots(
                result, freeze_day, candidate_data, config,
            )
            result, report = improve_preserving_protected_lots(
                result, candidate_data, copy.deepcopy(candidate_data), config,
                protected_segments, protected_lots, freeze_day, time_budget_s=budget,
            )
        else:
            report = {"status": "not_evaluated", "stop_reason": "no_time_left"}
    planning_checkpoint()
    if not _preserves_production(result, source_lots):
        raise ManualMoveError("A verificação alterou as quantidades ou identidades dos lotes.")
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
) -> ManualMoveResult:
    """Verify a move within one budget, including every fallback and validation."""
    with planning_scope(timeout_s=MANUAL_MOVE_BUDGET_S, cancel_event=cancel_event):
        return _move_lot(
            segments, lots, baseline_score, data, config,
            lot_id=lot_id, target_day=target_day, target_machine=target_machine,
            target_start_min=target_start_min, reason=reason, author=author,
            optimization_mode=optimization_mode, progress=progress,
            cancel_event=cancel_event,
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
) -> ManualMoveResult:
    """Anchor one complete lot and reoptimise every other production.

    ``target_start_min`` is the exact production start. Any required setup is
    placed immediately before it.
    """
    started = time.perf_counter()
    if target_day < 0 or target_day >= data.n_days:
        raise ManualMoveError(f"Dia alvo fora do horizonte: {target_day}.")

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
        _current_planning_day,
        _frozen_started_lots,
        _protected_lots,
    )
    from backend.scheduler.canonical import preserved_lot_proofs

    baseline_result = ScheduleResult(
        segments=segments,
        lots=lots,
        score=baseline_score,
        time_ms=0,
        warnings=[],
        operator_alerts=[],
    )
    freeze_day = _current_planning_day(data, config)
    frozen_segments, _ = _frozen_started_lots(baseline_result, freeze_day)
    frozen_ids = {segment.lot_id for segment in frozen_segments}
    frozen_lots = [item for item in lots if item.id in frozen_ids]
    frozen_proofs = preserved_lot_proofs(frozen_segments, frozen_lots)
    if any(segment.lot_id == lot_id for segment in frozen_segments):
        raise ManualMoveError(
            f"Lote {lot_id} já iniciado está congelado e não pode ser movido."
        )
    candidate_segments = [segment for segment in candidate_segments if segment.lot_id != lot_id]

    current_machine = moved_segments[0].machine_id
    machine_id = target_machine or current_machine
    allowed_machines = {lot.machine_id}
    if lot.alt_machine_id:
        allowed_machines.add(lot.alt_machine_id)
    if machine_id not in allowed_machines:
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
    _check_immutable_start(
        data, config, baseline_result, lot, first_moved,
        target_day, start_min, machine_id, freeze_day,
    )
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
    candidate_data.plan_anchors.append(
        PlanAnchor(
            lot_id=lot_id,
            machine_id=machine_id,
            start_at=target_at,
            reason=reason,
            author=author,
        )
    )
    if progress:
        progress("scheduling", 35, "A verificar o pedido mantendo as outras produções")
    try:
        result = _fixed_positions_move(
            segments, lots, lot_id, target_day, machine_id, start_min,
            data, config, candidate_data, frozen_proofs,
        )
    except ManualMoveError:
        result = None
    if result is None:
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
                time_budget_s=max(0.0, search_budget),
            )
        except (NoValidCandidateError, PlanningTimeout):
            if cancel_event is not None and cancel_event.is_set():
                raise PlanningCancelled("O movimento foi cancelado.") from None
            result = None
    planning_checkpoint()
    if result is not None and not _preserves_production(result, lots):
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
                protected_segments, protected_lots, _ = _protected_lots(
                    baseline_result, freeze_day, candidate_data, config,
                )
                fixed_result = _replan_around_fixed_lot(
                    candidate_data, config, lots, protected_segments, protected_lots,
                    frozen_proofs, rebound_lot, rebound_template,
                    target_day, machine_id, start_min, optimization_mode,
                    cancel_event, remaining_budget,
                )
            except (ManualMoveError, NoValidCandidateError, PlanningTimeout):
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
        raise _inconclusive_move(lot_id, target_day, start_min, machine_id)
    complete = ScheduleResult(
        candidate_segments, candidate_lots, score, 0, [], [], gate_report=gate_report,
        improvement_report=(result.improvement_report if result is not None
                            and result.segments == candidate_segments
                            and result.lots == candidate_lots else None),
        preserved_lot_proofs=frozen_proofs,
    )
    try:
        complete = _finalize_move_candidate(complete, candidate_data, config, lots)
    except ManualMoveError as exc:
        raise _inconclusive_move(lot_id, target_day, start_min, machine_id) from exc
    candidate_segments, candidate_lots = complete.segments, complete.lots
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
    old_dispatch = int(
        baseline_score.get("subcontract_dispatch_misses", 0) or 0
    )
    new_dispatch = int(score.get("subcontract_dispatch_misses", 0) or 0)
    if new_dispatch > old_dispatch:
        delivery_warnings.append(
            "Cria "
            f"{new_dispatch - old_dispatch} novo(s) atraso(s) de envio para "
            "subcontratação."
        )
    if int(gate_report["metrics"].get("early_window_violations", 0) or 0):
        delivery_warnings.append(
            "O plano inicia produção antes da libertação de material calculada "
            "a partir da entrega ou do envio para subcontratação."
        )
    if int(gate_report["metrics"].get("long_productions", 0) or 0):
        delivery_warnings.append(
            "O plano contém produções com mais de quatro dias úteis."
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
    )
