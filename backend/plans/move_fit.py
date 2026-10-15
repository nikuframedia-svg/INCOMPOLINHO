"""Does a moved lot fit in one production? Checked before any reorganisation.

Decision of 15/10/2026 (Luís, after moving JTE001 to 03/12 08:45 at
Incompol): a manual move that cannot fit is refused at once, in plain words,
with the first start where the lot does fit. Before, the refusal came only
after the full reorganisation (2–50 s), with technical causes.

The rule is the one of the plan (AGENTS §2, «Lote económico = uma
produção»): a lot is one production, its setup followed by its production,
continuing through nights, weekends, holidays and unavailabilities, never
past free shift time nor around other work. The only work that is certain to
stay where it is during a move is the move's own protection
(``manual_move._move_protection``: started production, the run mounted at
the boundary, lots pinned by hand) plus the tool those keep mounted between
a segment and its continuation without setup (the same reservation as
``frozen._install_frozen_reservations``). Everything else can still move, so
the check only refuses when the lot does not fit even with all of it gone,
and never when a machine or tool block over working time could excuse the
break (``validation._BreakFinder``).

Times are absolute factory minutes: ``day * 1440 + minute``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, replace

from backend.calendar import MIN_FREE_INTERVAL_MIN

DAY_MIN = 1440
_TOLERANCE = 0.01


@dataclass(slots=True)
class Obstacle:
    """Work that stays where it is, from ``start`` to ``end`` (absolute minutes)."""

    start: int
    end: int
    segment: object
    # The tool stays mounted until ``segment`` continues without a setup.
    mounted: bool = False


@dataclass(slots=True)
class FitVerdict:
    fits: bool
    setup_min: float
    prod_min: float
    start: int
    # Working time for production from ``start`` until ``obstacle``.
    free_min: float
    # ``None`` with ``fits=False``: the plan horizon ends first.
    obstacle: Obstacle | None
    setup_blocked: bool = False
    # A machine or tool block over working time could excuse the break.
    excusable: bool = False


def one_production_lot(lot) -> bool:
    """Whether the lot must be one production (``validation.lot_split_violations``).

    A lot of an older material contract is not judged; one taken over from
    versions 1-2 may keep the productions its old contract made.
    """
    from backend.scheduler.lot_sizing import UPGRADED_MATERIAL_KEY
    from backend.scheduler.material_quantities import lot_material_version
    from backend.scheduler.validation import _upgraded_productions

    if lot_material_version(lot) < 3:
        return False
    if not any(output.get(UPGRADED_MATERIAL_KEY) for output in lot.output_milestones or []):
        return True
    allowed = _upgraded_productions(lot)
    return allowed is None or allowed <= 1


def _absolute(day: int, minute: float, *, up: bool = False) -> int:
    return int(day) * DAY_MIN + (math.ceil(minute) if up else math.floor(minute))


class MachineTimeline:
    """Fixed obstacles and the lot's working time on one machine."""

    def __init__(
        self, data, config, protected_segments, lot, template, machine_id: str,
        *, freeze_day: int, now_min: float,
    ) -> None:
        from backend.scheduler.operators import segment_operator_demand
        from backend.scheduler.setup_identity import segment_setup_identity
        from backend.transform.calendars import calendar_window

        self.data = data
        self.config = config
        self.view = calendar_window(data, config, data.n_days - 1)
        self.lot = lot
        self.machine = machine_id
        self.tool = lot.tool_id
        self.horizon = int(data.n_days) * DAY_MIN
        self.now = _absolute(freeze_day, now_min, up=True)
        self.group = (
            config.machine_group(machine_id) if hasattr(config, "machine_group")
            else next((m.group for m in data.machines if m.id == machine_id), None)
        )
        self.required = max(1, int(segment_operator_demand(
            replace(template, machine_id=machine_id, twin_outputs=lot.twin_outputs), self.view,
        )))
        self.identity = segment_setup_identity(replace(
            template, tool_id=lot.tool_id, twin_outputs=lot.twin_outputs,
        ))
        others = [
            segment for segment in protected_segments
            if segment.lot_id != lot.id and segment.end_min > segment.start_min
        ]
        self.by_day: dict[int, list] = defaultdict(list)
        for segment in others:
            self.by_day[segment.day_idx].append(segment)
        obstacles = [
            Obstacle(
                _absolute(segment.day_idx, segment.start_min),
                _absolute(segment.day_idx, segment.end_min, up=True),
                segment,
            )
            for segment in others
            if segment.machine_id == machine_id or segment.tool_id == lot.tool_id
        ]
        # A protected continuation without setup keeps its tool mounted from
        # the segment before it (``frozen._install_frozen_reservations``).
        previous_by_machine: dict[str, object] = {}
        chronological = sorted(
            others, key=lambda item: (item.day_idx, item.start_min, item.end_min),
        )
        for segment in chronological:
            previous = previous_by_machine.get(segment.machine_id)
            previous_by_machine[segment.machine_id] = segment
            if (
                previous is None or segment.day_idx < freeze_day or segment.setup_min > 0
                or segment_setup_identity(previous) != segment_setup_identity(segment)
                or segment_setup_identity(segment) == self.identity
                or (segment.machine_id != machine_id and segment.tool_id != lot.tool_id)
            ):
                continue
            start = max(
                freeze_day * DAY_MIN, _absolute(previous.day_idx, previous.end_min, up=True),
            )
            end = _absolute(segment.day_idx, segment.start_min)
            if start < end:
                obstacles.append(Obstacle(start, end, segment, mounted=True))
        self.obstacles = sorted(obstacles, key=lambda item: (item.start, item.end))
        self._available: dict[int, list[tuple[int, int]]] = {}

    def _blocks(self, day: int) -> list[tuple[int, int]]:
        return [
            (int(block.get("start_min", 0)), int(block.get("end_min", DAY_MIN)))
            for block in (
                *self.view.machine_blocked_intervals.get(self.machine, []),
                *self.view.tool_blocked_intervals.get(self.tool, []),
            )
            if int(block.get("start_day", -1)) == day
        ]

    def _workday(self, day: int) -> bool:
        from backend.calendar import is_factory_workday

        return is_factory_workday(day, self.view, self.config)

    def available(self, day: int) -> list[tuple[int, int]]:
        """Working time of the lot on ``day``, per shift (absolute minutes).

        Shift time of a factory working day, outside machine and tool
        unavailabilities, with the operators of the group free of the
        protected work, from the current minute on: the time the lot may
        produce in. Everything else may interrupt it (AGENTS §2, «Continua»).
        Obstacles are not removed here.
        """
        if day in self._available:
            return self._available[day]
        from backend.calendar import _subtract_intervals
        from backend.config.shifts import ordered_shifts
        from backend.scheduler.operators import operator_free_windows

        pieces: list[tuple[int, int]] = []
        if (
            0 <= day < self.data.n_days and self._workday(day)
            and day not in self.view.machine_blocked_days.get(self.machine, set())
            and day not in self.view.tool_blocked_days.get(self.tool, set())
        ):
            blocks = self._blocks(day)
            for shift in ordered_shifts(self.config):
                low, high = int(shift.start_min), int(shift.end_min)
                staffed = (
                    operator_free_windows(
                        self.by_day.get(day, []), self.data, self.config, day=day,
                        shift=shift.id, group=self.group, required=self.required,
                        start=low, end=high,
                    )
                    if self.group else [(low, high)]
                )
                for start, end in staffed:
                    for left, right in _subtract_intervals(
                        (math.ceil(start), math.floor(end)), blocks,
                    ):
                        left, right = max(day * DAY_MIN + left, self.now), day * DAY_MIN + right
                        if left < right:
                            pieces.append((left, right))
        self._available[day] = pieces
        return pieces

    def working_between(self, start: int, stop: int, need: float | None = None):
        """``(minutes, reached)``: working time in ``[start, stop)``.

        With ``need``, stops at the minute the lot has had ``need`` minutes.
        """
        total = 0.0
        day = max(0, start // DAY_MIN)
        while day * DAY_MIN < stop and day < self.data.n_days:
            for left, right in self.available(day):
                low, high = max(left, start), min(right, stop)
                if high <= low:
                    continue
                if need is not None and total + (high - low) >= need - _TOLERANCE:
                    return need, low + (need - total)
                total += high - low
            day += 1
        return total, None

    def obstacle_at_or_after(self, minute: int) -> Obstacle | None:
        """The first obstacle still there at ``minute`` (it may already have begun)."""
        candidates = [item for item in self.obstacles if item.end > minute]
        return min(candidates, key=lambda item: (item.start, item.end), default=None)

    def overlapping(self, start: int, end: int) -> Obstacle | None:
        return next(
            (item for item in self.obstacles if item.start < end and start < item.end), None,
        )

    def _block_in_working_time(self, start: int, end: int) -> bool:
        """A machine or tool block over shift time of a working day in ``[start, end)``."""
        for day in range(max(0, start // DAY_MIN), min(self.data.n_days, end // DAY_MIN + 1)):
            if not self._workday(day):
                continue
            if (day in self.view.machine_blocked_days.get(self.machine, set())
                    or day in self.view.tool_blocked_days.get(self.tool, set())):
                return True
            for left, right in self._blocks(day):
                for shift in self.config.shifts:
                    low = max(left, int(shift.start_min), start - day * DAY_MIN)
                    high = min(right, int(shift.end_min), end - day * DAY_MIN)
                    if low < high:
                        return True
        return False

    def _materialized_end(self, start: int, prod_min: float) -> int:
        """Where production started at ``start`` would end, going around obstacles."""
        total, cursor = 0.0, start
        while cursor < self.horizon:
            obstacle = self.obstacle_at_or_after(cursor)
            if obstacle is not None and obstacle.start <= cursor:
                cursor = obstacle.end
                continue
            stop = obstacle.start if obstacle is not None else self.horizon
            free, reached = self.working_between(cursor, stop, need=prod_min - total)
            if reached is not None:
                return math.ceil(reached)
            total += free
            cursor = stop
        return self.horizon

    def check(self, start: int, setup_min: float, prod_min: float) -> FitVerdict | None:
        """Whether setup + production fit in one production from ``start``.

        ``start`` is the production start; the setup comes right before it,
        as the move places it (``manual_move._setup_slices_before_target``).
        ``None`` when the setup cannot be placed there at all (another check
        says why).
        """
        from backend.plans.manual_move import _setup_slices_before_target

        day, minute = divmod(int(start), DAY_MIN)
        setup_start = start
        if setup_min > 0:
            slices = _setup_slices_before_target(self.view, self.config, day, minute, setup_min)
            if not slices:
                return None
            setup_start = _absolute(slices[0][0], slices[0][2])
            for slice_day, _shift, left, right in slices:
                hit = self.overlapping(
                    _absolute(slice_day, left), _absolute(slice_day, right, up=True),
                )
                if hit is not None:
                    return FitVerdict(
                        False, setup_min, prod_min, start, 0.0, hit, setup_blocked=True,
                        excusable=False,
                    )
        obstacle = self.obstacle_at_or_after(start)
        stop = self.horizon if obstacle is None else max(start, obstacle.start)
        free, reached = self.working_between(start, stop, need=prod_min)
        if reached is not None:
            return FitVerdict(True, setup_min, prod_min, start, free, obstacle)
        excusable = self._block_in_working_time(
            setup_start, self._materialized_end(start, prod_min),
        )
        return FitVerdict(False, setup_min, prod_min, start, free, obstacle, excusable=excusable)

    def pieces(self, day: int) -> list[tuple[int, int]]:
        """Working time of ``day`` without any obstacle, per shift."""
        from backend.calendar import _subtract_intervals

        busy = [
            (item.start, item.end) for item in self.obstacles
            if item.start < (day + 1) * DAY_MIN and item.end > day * DAY_MIN
        ]
        return [
            piece for interval in self.available(day)
            for piece in _subtract_intervals(interval, busy)
        ]


def earliest_fit(
    timeline: MachineTimeline, setup_min: float, prod_min: float, from_start: int,
    *, after: bool = False, day_ok=None, accept=None,
) -> int | None:
    """The first production start from ``from_start`` where the lot fits.

    The setup and the first production minute share a shift window (AGENTS
    §4, decision of 03/10/2026), in working time free of obstacles, with at
    least ``MIN_FREE_INTERVAL_MIN`` of production in that window; within
    such a window an earlier start only gains room, so its first minute after
    the setup (or ``from_start``) is the one to try. ``after``: only after
    the next work that stays where it is (the requested start fits in a row
    and failed for another reason: the same stretch would fail alike).
    ``day_ok``/``accept`` filter days and starts with the move's other checks
    (material, calendar, operators).
    """
    floor = max(int(from_start), timeline.now)
    if after:
        boundary = timeline.obstacle_at_or_after(floor)
        if boundary is None:
            return None
        floor = max(floor, boundary.end)
    for day in range(max(0, floor // DAY_MIN), timeline.data.n_days):
        if day_ok is not None and not day_ok(day):
            continue
        for left, right in timeline.pieces(day):
            candidate = max(math.ceil(left + setup_min), floor)
            # Less than ``MIN_FREE_INTERVAL_MIN`` of production in the window
            # is a gap, not usable time (``calendar.free_shift_intervals``).
            if right - candidate < MIN_FREE_INTERVAL_MIN:
                continue
            verdict = timeline.check(candidate, setup_min, prod_min)
            if verdict is None or not verdict.fits:
                continue
            if accept is None or accept(candidate):
                return candidate
    return None


def date_label(day: int, data) -> str:
    """``03/12`` (``dia 51`` without a calendar date)."""
    try:
        raw = str(data.workdays[day])
    except (IndexError, TypeError):
        return f"dia {day}"
    return f"{raw[8:10]}/{raw[5:7]}" if len(raw) >= 10 and raw[4] == "-" else f"dia {day}"


def clock(minute: float) -> str:
    value = int(round(minute))
    return f"{value // 60:02d}:{value % 60:02d}"


def at_label(absolute: int, data) -> str:
    """``03/12 às 08:45``."""
    day, minute = divmod(int(absolute), DAY_MIN)
    return f"{date_label(day, data)} às {clock(minute)}"


def hours_text(minutes: float) -> str:
    """``7,8 h``; ``45 min`` under an hour; ``1 h`` for whole hours."""
    if minutes < 59.5:
        return f"{max(0, round(minutes))} min"
    text = f"{minutes / 60:.1f}".replace(".", ",")
    return f"{text.removesuffix(',0')} h"


def _holder(obstacle: Obstacle, data, lots_by_id: dict, pinned: dict[str, str]):
    """``(label, tail, pinned_when)``: who holds the obstacle, never a lot id."""
    from backend.scheduler.canonical import _lot_label

    segment = obstacle.segment
    lot = lots_by_id.get(segment.lot_id)
    label = _lot_label(lot, segment.machine_id) if lot is not None else (
        f"produção na {segment.machine_id}"
    )
    when = pinned.get(segment.lot_id) if segment.lot_id in pinned else None
    if when is not None:
        tail = f", fixada à mão para {when}" if when else ", fixada à mão"
    else:
        tail = ", que fica onde está"
    return label, tail, when


def _event(obstacle: Obstacle, timeline: MachineTimeline, label: str, tail: str) -> str:
    """What happens at the obstacle, after «quando»."""
    segment = obstacle.segment
    if obstacle.mounted:
        return (
            f"a ferramenta {segment.tool_id} fica montada na {segment.machine_id} "
            f"à espera da {label}{tail}"
        )
    if segment.machine_id != timeline.machine:
        return f"a ferramenta {segment.tool_id} passa para a {label}{tail}"
    if segment.setup_min > 0:
        return f"começa a afinação da {label}{tail}"
    return f"começa a produção da {label}{tail}"


def _state(obstacle: Obstacle, timeline: MachineTimeline, label: str, tail: str, data) -> str:
    """What occupies the machine at the requested start."""
    segment = obstacle.segment
    if obstacle.mounted:
        return (
            f"a ferramenta {segment.tool_id} fica montada na {segment.machine_id} até "
            f"{at_label(obstacle.end, data)}, à espera da {label}{tail}"
        )
    if segment.machine_id != timeline.machine:
        return f"a ferramenta {segment.tool_id} está a ser usada pela {label}{tail}"
    return f"a máquina está ocupada pela {label}{tail}"


RULE_CAUSE = (
    "Um lote faz-se numa só produção: pode parar à noite, ao fim de semana, num "
    "feriado ou numa indisponibilidade, mas nunca com tempo de turno livre ou outro "
    "trabalho pelo meio."
)


def refusal_texts(
    verdict: FitVerdict, timeline: MachineTimeline, data, lots_by_id: dict,
) -> tuple[str, list[str]]:
    """``(detail, causes)`` of a lot that does not fit in one production."""
    from backend.plans.refusal import _anchor_starts

    pinned = _anchor_starts(data)
    start = verdict.start
    start_clock = clock(start % DAY_MIN)
    setup, prod = verdict.setup_min, verdict.prod_min
    if setup > 0:
        need = (
            f"o lote precisa de {hours_text(setup + prod)} seguidas "
            f"({hours_text(setup)} de afinação antes das {start_clock} + "
            f"{hours_text(prod)} de produção)"
        )
    else:
        need = f"o lote precisa de {hours_text(prod)} seguidas de produção"
    obstacle = verdict.obstacle
    if obstacle is None:
        detail = (
            f"{need}; a partir de {at_label(start, data)} só há "
            f"{hours_text(verdict.free_min)} livres até ao fim do horizonte do plano "
            f"({date_label(data.n_days - 1, data)})."
        )
        cause = (
            f"De {at_label(start, data)} até ao fim do horizonte do plano: "
            f"{hours_text(verdict.free_min)} de tempo de turno na {timeline.machine}, "
            f"menos do que as {hours_text(prod)} de produção do lote."
        )
        return detail, [cause, RULE_CAUSE]
    label, tail, when = _holder(obstacle, data, lots_by_id, pinned)
    if when is not None:
        clash = "; choca com a alteração manual da " + label + (
            f" (fixada para {when})" if when else ""
        )
    else:
        clash = f"; a {label} fica onde está"
    if verdict.setup_blocked:
        detail = (
            f"{need}, mas a afinação antes das {start_clock} de "
            f"{date_label(start // DAY_MIN, data)} não cabe: "
            f"{_state(obstacle, timeline, label, tail, data)}."
        )
        cause = (
            f"Afinação de {hours_text(setup)} antes de {at_label(start, data)} na "
            f"{timeline.machine}: o tempo não está livre{clash}."
        )
        return detail, [cause, RULE_CAUSE]
    if obstacle.start <= start:
        detail = (
            f"{need}, mas em {at_label(start, data)} "
            f"{_state(obstacle, timeline, label, tail, data)}."
        )
        cause = (
            f"Em {at_label(start, data)} a {timeline.machine} não está livre{clash}."
        )
        return detail, [cause, RULE_CAUSE]
    detail = (
        f"{need}; a partir de {at_label(start, data)} só há "
        f"{hours_text(verdict.free_min)} livres até {at_label(obstacle.start, data)}, "
        f"quando {_event(obstacle, timeline, label, tail)}."
    )
    cause = (
        f"De {at_label(start, data)} a {at_label(obstacle.start, data)}: "
        f"{hours_text(verdict.free_min)} de tempo de turno na {timeline.machine}, "
        f"menos do que as {hours_text(prod)} de produção do lote{clash}."
    )
    return detail, [cause, RULE_CAUSE]
