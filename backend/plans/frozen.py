"""Preserve what has started before the current planning day (AGENTS §2, rule 4).

A lot that has started keeps exactly the production that started: every
segment before the planning day plus the run that is mounted at that boundary
and continues without a new setup and without free working time in between
(``free_working_time_between``). Its later portions stay in the residual
problem and are replanned, but the lot is never re-sized: the residual
receives the rest of the same economic lot as a pre-sized lot
(``EngineData.residual_lot_remainders``) while the whole lot is credited as
committed supply, so lot sizing never sizes it a second time. The complete
plan joins both parts back into the original lot.

Frozen work never depends on movable work: a frozen segment that continues a
mounted tool without setup keeps its mount supplier frozen too (with the
earlier production of that supplier's lot).
"""

from __future__ import annotations

import copy
import json
import logging
import math
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from types import SimpleNamespace

from backend.config.planning import NO_ACTIVE_MACHINE_PREFIX, allowed_machines
from backend.types import CommittedSupply

logger = logging.getLogger(__name__)


class NoValidCandidateError(ValueError):
    """The optimizer finished without a complete executable candidate."""



def preserved_lots_warning(started: int, freeze_day: int, now_label: str | None = None) -> str:
    """One wording for every path that keeps started production unchanged.

    ``now_label`` (``"13/10 15:39"``): the boundary is that minute of the
    planning day (AGENTS §2 rule 4), not the start of day ``freeze_day``.
    """

    lots = "1 lote" if started == 1 else f"{started} lotes"
    if now_label:
        started_text = "já iniciado" if started == 1 else "já iniciados"
        return (
            f"Plano anterior preservado: {lots} {started_text} até agora ({now_label}); "
            "a produção já feita mantém-se sem alterações."
        )
    started_text = "iniciado" if started == 1 else "iniciados"
    return (
        f"Plano anterior preservado: {lots} {started_text} antes do dia {freeze_day}; "
        "a produção já iniciada mantém-se sem alterações."
    )


def boundary_label(freeze_day: int, now_min: int, engine_data) -> str | None:
    """``"13/10 15:39"``: the minute boundary of the planning day, if any."""

    workdays = list(getattr(engine_data, "workdays", None) or [])
    if now_min <= 0 or not 0 <= freeze_day < len(workdays):
        return None
    day = str(workdays[freeze_day])[:10]
    return f"{day[8:10]}/{day[5:7]} {int(now_min) // 60:02d}:{int(now_min) % 60:02d}"


@dataclass
class ProtectedPlan:
    """What a replan keeps exactly as in the baseline (AGENTS §2, rule 4).

    ``segments``: every frozen segment (whole lots and the started part of
    partial lots). ``lots``: lots kept whole (all their production started,
    manual anchors, lots of an older material contract, mount suppliers).
    ``partial``: ``(original lot, remainder lot)`` of started lots whose later
    portions are replanned; the remainder is the rest of the same economic
    lot, never re-sized. ``started``: lots with production before the planning
    day, for the plan warning. ``cut``: ``(baseline segment, rest)`` of each
    protected segment cut where a new input conflicts with it
    (``scheduler.history``): its frozen part is in ``segments``, ``rest`` is
    what the residual starts from. ``now_label``: the minute boundary, for
    the warning. ``pinned``: lots of ``lots`` kept whole only for a manual
    anchor (and the lots that mount their tool), none of whose production
    has started: a position, not history (``_protected_plan``).
    """

    segments: list = dataclass_field(default_factory=list)
    lots: list = dataclass_field(default_factory=list)
    partial: list = dataclass_field(default_factory=list)
    anchored: set = dataclass_field(default_factory=set)
    pinned: set = dataclass_field(default_factory=set)
    started: set = dataclass_field(default_factory=set)
    cut: list = dataclass_field(default_factory=list)
    now_label: str | None = None

    def __bool__(self) -> bool:
        return bool(self.lots or self.partial)

def calculation_now(config, now: datetime | None = None) -> datetime:
    """The one "now" of a calculation, in factory time (AGENTS §2 rule 4).

    ``now`` when the caller captured it (a replan job, a manual move), else
    the instant fixed for the running write (``calendar.fixed_factory_clock``),
    else the factory clock. Captured once per calculation and passed down, so
    the planning day, today's elapsed minutes and the history guard agree.
    """
    from backend.calendar import factory_now

    return factory_now(config, now=now)


def _horizon_start(engine_data, config, now: datetime) -> datetime:
    """00:00 of the plan's first day: «Recalcular plano» plans from D0 (§5)."""
    from backend.calendar import factory_now

    workdays = list(getattr(engine_data, "workdays", []) or [])
    if not workdays:
        return now
    zone = factory_now(config, now=now).tzinfo
    first = datetime.fromisoformat(str(workdays[0])[:10])
    return first.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=zone)


def elapsed_on_planning_day(freeze_day: int, engine_data, config, now: datetime | None) -> int:
    """Minutes of the planning day already gone at ``now`` (0 if it is not today)."""
    from backend.calendar import elapsed_minutes

    if not getattr(engine_data, "workdays", None):
        return 0
    return int(elapsed_minutes(freeze_day, engine_data, config, now=now))


def planning_boundary(freeze_day: int, now_min: float) -> list[int]:
    """The history boundary of a calculation (``scheduler.history``).

    ``[planning day, minutes of it already gone]``; ``[0, 0]`` is none. It
    travels with the calculated plan (``ScheduleResult.history_boundary``).
    """

    return [int(freeze_day), int(now_min)]


# A candidate is applied on the day and close to the instant it was
# calculated at (AGENTS §2 rule 4): later, the factory has moved on.
CALCULATION_MAX_AGE_MIN = 15
OTHER_DAY_TEXT = "O plano foi calculado noutro dia; calcule novamente."
TOO_OLD_TEXT = (
    f"O plano foi calculado há mais de {CALCULATION_MAX_AGE_MIN} minutos; calcule novamente."
)


class StaleCalculationError(ValueError):
    """A candidate calculated on another day, or too long ago, cannot be applied."""

    code = "stale_calculation"


def _parsed_instant(value, zone_source) -> datetime | None:
    from backend.calendar import factory_now

    if not value:
        return None
    instant = datetime.fromisoformat(value) if isinstance(value, str) else value
    return factory_now(zone_source, now=instant)


def commit_instant(planning_now, zone_source) -> tuple[str, datetime | None]:
    """``(today, now)`` the commit guard reads history at.

    The date is the real factory clock's at commit; the calculation's own
    instant applies only on that same date. A candidate calculated on an
    earlier date is refused (``StaleCalculationError``).
    """
    from backend.calendar import wall_factory_now

    real = wall_factory_now(zone_source)
    calculated = _parsed_instant(planning_now, zone_source)
    today = real.date().isoformat()
    if calculated is None:
        return today, None
    if calculated.date() < real.date():
        raise StaleCalculationError(OTHER_DAY_TEXT)
    return today, calculated if calculated.date() == real.date() else None


def assert_fresh_calculation(planning_now, zone_source) -> None:
    """Refuse applying a candidate calculated on another day or too long ago.

    Replan jobs and prepared previews (manual moves, recalculations waiting
    for approval): at most ``CALCULATION_MAX_AGE_MIN`` minutes old.
    """
    from datetime import timedelta

    from backend.calendar import wall_factory_now

    calculated = _parsed_instant(planning_now, zone_source)
    if calculated is None:
        return
    real = wall_factory_now(zone_source)
    if calculated.date() != real.date():
        raise StaleCalculationError(OTHER_DAY_TEXT)
    if real - calculated > timedelta(minutes=CALCULATION_MAX_AGE_MIN):
        raise StaleCalculationError(TOO_OLD_TEXT)


def started_before(segment, freeze_day: int, now_min: float = 0) -> bool:
    """Production that started before the planning boundary (AGENTS §2 rule 4).

    The boundary is the current factory minute (13/10/2026): every segment of
    an earlier day, and of the planning day every segment that starts before
    ``now_min`` (one running at that minute too, as a whole).
    """
    return segment.end_min > segment.start_min and (
        segment.day_idx < freeze_day
        or (segment.day_idx == freeze_day and segment.start_min < now_min)
    )


def _current_planning_day(engine_data, config, now: datetime | None = None) -> int:
    workdays = list(getattr(engine_data, "workdays", []) or [])
    if not workdays:
        return 0
    today = calculation_now(config, now).date().isoformat()
    # Historical imports and future scenarios have no executed prefix.
    if today < str(workdays[0])[:10] or today > str(workdays[-1])[:10]:
        return 0
    for day_idx, value in enumerate(workdays):
        if str(value)[:10] >= today:
            return day_idx
    return 0


def _frozen_started_lots(baseline_result, freeze_day: int, now_min: float = 0):
    """Lots with production before the boundary ``(freeze_day, now_min)``."""
    if baseline_result is None or (freeze_day <= 0 and now_min <= 0):
        return [], []
    frozen_ids = {
        segment.lot_id
        for segment in baseline_result.segments
        if started_before(segment, freeze_day, now_min)
    }
    return (
        [copy.deepcopy(s) for s in baseline_result.segments if s.lot_id in frozen_ids],
        [copy.deepcopy(lot) for lot in baseline_result.lots if lot.id in frozen_ids],
    )


_HISTORICAL_SEGMENT_FIELDS = (
    "lot_id", "run_id", "machine_id", "tool_id", "day_idx", "start_min",
    "end_min", "shift", "qty", "prod_min", "setup_min", "is_continuation",
    "twin_outputs",
)
_HISTORICAL_LOT_FIELDS = (
    "id", "op_id", "tool_id", "machine_id", "qty", "prod_min",
    "setup_min", "is_twin", "twin_outputs",
)
# The rest of a started lot moves when the lot may no longer use its machine
# (owner decision, 16/10/2026): machine and the times on it are not history.
_MOVABLE_LOT_FIELDS = ("machine_id", "prod_min", "setup_min")


def historical_schedule_changes(
    before: dict, after: dict, *, today: str | None = None, now: datetime | None = None,
    engine_data=None, config=None,
) -> list[str]:
    """Started lots whose history changed (same dataset), or new past production.

    History is what happened before the boundary: the production of a started
    lot before today and the lot itself (never re-sized). Its later portions
    may be replanned (AGENTS §2, rule 4). ``today`` is the calendar date of
    the boundary (default: the factory date of ``now``). With ``now`` — the
    instant the calculation used — today's segments that start before its
    minute are history too (13/10/2026), under the one rule of
    ``scheduler.history``: each stays as it was or stops at a minute not
    before ``now`` (``cut_row``, the cut of a new input over it); it may be
    missing only if it made no piece before ``now``; no production is added
    before ``now``; a lot with such a segment keeps its size.

    The rest of a started lot may change machine only when the lot may no
    longer use its old one (owner decision, 16/10/2026), judged by the
    candidate's own operations and configuration: ``engine_data`` and
    ``config`` when given, else the ones ``after`` carries.

    A record of what ran today (decisão do Luís, 20/10/2026;
    ``_declared_today``) rewrites exactly one machine's morning: its own
    rows, and what it displaced cut at its setup start, are set aside;
    every other row before ``now`` is judged as above. The same reading
    in the other direction lets «Desfazer» take the record back that day.
    """
    from backend.calendar import factory_now
    from backend.scheduler.history import cut_row

    before_id = str((before.get("dataset_info") or {}).get("id") or "")
    after_id = str((after.get("dataset_info") or {}).get("id") or "")
    if not before_id or before_id != after_id:
        return []
    workdays = list((before.get("engine_data") or {}).get("workdays") or [])
    if not workdays:
        return []
    timezone = str((before.get("config") or {}).get("timezone") or "Europe/Lisbon")
    current = factory_now(timezone, now=now)
    current_day = today or current.date().isoformat()
    # Minutes of ``current_day`` already gone: only with an explicit instant
    # on that same date (a plan replayed on another date has none).
    now_min = (
        current.hour * 60 + current.minute
        if now is not None and current.date().isoformat() == current_day else 0
    )
    if current_day < str(workdays[0])[:10] or (
        current_day == str(workdays[0])[:10] and not now_min
    ):
        return []
    freeze_day = next(
        (index for index, value in enumerate(workdays) if str(value)[:10] >= current_day),
        len(workdays),
    )
    started = {
        segment["lot_id"]
        for segment in before.get("segments", [])
        if int(segment["day_idx"]) < freeze_day
        and float(segment["end_min"]) > float(segment["start_min"])
    }

    def calendar_dates(snapshot: dict):
        snapshot_days = list((snapshot.get("engine_data") or {}).get("workdays") or [])

        def calendar_date(segment):
            day = int(segment["day_idx"])
            return str(snapshot_days[day])[:10] if 0 <= day < len(snapshot_days) else None

        return calendar_date

    def row(segment, calendar_date) -> str:
        return json.dumps(
            {
                **{field: segment.get(field) for field in _HISTORICAL_SEGMENT_FIELDS},
                "calendar_date": calendar_date(segment),
            },
            sort_keys=True, separators=(",", ":"),
        )

    def lot_rows(snapshot: dict, lot_id: str):
        calendar_date = calendar_dates(snapshot)
        segments = [
            row(segment, calendar_date)
            for segment in snapshot.get("segments", [])
            if segment.get("lot_id") == lot_id
            and (calendar_date(segment) is None or calendar_date(segment) < current_day)
        ]
        return sorted(segments)

    def lot_fields(snapshot: dict, lot_id: str, ignored=()):
        return sorted(
            json.dumps(
                {field: lot.get(field) for field in _HISTORICAL_LOT_FIELDS
                 if field not in ignored},
                sort_keys=True, separators=(",", ":"),
            )
            for lot in snapshot.get("lots", [])
            if lot.get("id") == lot_id
        )

    def lot_machines(snapshot: dict, lot_id: str) -> list:
        return sorted(
            str(lot.get("machine_id")) for lot in snapshot.get("lots", [])
            if lot.get("id") == lot_id
        )

    def made_only(lot_id: str) -> bool:
        """The lot ends with what it made: no production left from ``now``."""
        lots = [lot for lot in after.get("lots", []) if lot.get("id") == lot_id]
        previous = [lot for lot in before.get("lots", []) if lot.get("id") == lot_id]
        if len(lots) != 1 or len(previous) != 1:
            return False
        after_date = calendar_dates(after)
        segments = [s for s in after.get("segments", []) if s.get("lot_id") == lot_id]
        return all(
            (after_date(s) or "") < current_day
            or (after_date(s) == current_day and float(s["end_min"]) <= now_min)
            for s in segments
        ) and int(lots[0].get("qty") or 0) == sum(int(s.get("qty") or 0) for s in segments) <= (
            int(previous[0].get("qty") or 0)
        )

    eligibility: list = []

    def allowed_now(snapshot: dict, lot_id: str) -> set[str] | None:
        """Machines the lot may use under the candidate's own data."""
        if not eligibility:
            eligibility.append(_candidate_eligibility(after, engine_data, config))
        data, factory = eligibility[0]
        lots = [lot for lot in snapshot.get("lots", []) if lot.get("id") == lot_id]
        if data is None or len(lots) != 1:
            return None
        lot = SimpleNamespace(
            op_id=lots[0].get("op_id"), twin_outputs=lots[0].get("twin_outputs") or [],
        )
        allowed = allowed_machines(lot, data, factory)
        return None if allowed is None else set(allowed)

    def move_justified(lot_id: str) -> bool:
        """The old machine may no longer be used, the new one may."""
        allowed = allowed_now(after, lot_id)
        if allowed is None:
            return False
        old = set(lot_machines(before, lot_id))
        new = set(lot_machines(after, lot_id))
        return not (old & allowed) and new <= allowed

    def dropped_unmade(lot_id: str) -> bool:
        """A started lot that made nothing (a setup alone) left out because
        no allowed machine is active for it: it ends with what it made."""
        if any(lot.get("id") == lot_id for lot in after.get("lots", [])) or any(
            segment.get("lot_id") == lot_id for segment in after.get("segments", [])
        ):
            return False
        before_date = calendar_dates(before)
        history = [
            segment for segment in before.get("segments", [])
            if segment.get("lot_id") == lot_id and (
                (before_date(segment) or "") < current_day
                or (before_date(segment) == current_day
                    and float(segment["start_min"]) < now_min)
            )
        ]
        if any(
            int(segment.get("qty") or 0) or float(segment.get("prod_min") or 0)
            or any(int(output[2] or 0) for output in segment.get("twin_outputs") or [])
            for segment in history
        ):
            return False
        allowed = allowed_now(before, lot_id)
        return allowed is not None and not (set(lot_machines(before, lot_id)) & allowed)

    def lot_changed(lot_id: str) -> bool:
        """Whether a started lot was re-sized (rule 4) or moved without cause.

        Its rest may move to another allowed active machine, with that
        machine's times, only when it may no longer use its own, and with
        none it ends with what it made (owner decision, 16/10/2026); its
        history rows are compared apart.
        """
        if lot_fields(before, lot_id) == lot_fields(after, lot_id):
            return False
        moved = lot_machines(before, lot_id) != lot_machines(after, lot_id)
        if moved and not move_justified(lot_id):
            return True
        if moved and lot_fields(before, lot_id, _MOVABLE_LOT_FIELDS) == lot_fields(
            after, lot_id, _MOVABLE_LOT_FIELDS,
        ):
            return False
        shrinkable = (*_MOVABLE_LOT_FIELDS, "qty", "twin_outputs")
        return lot_fields(before, lot_id, shrinkable) != lot_fields(
            after, lot_id, shrinkable,
        ) or not made_only(lot_id)

    def elapsed_today(snapshot: dict) -> list[tuple[dict, str]]:
        """Today's production that starts before ``now_min``, with its row."""
        calendar_date = calendar_dates(snapshot)
        return [
            (segment, row(segment, calendar_date))
            for segment in snapshot.get("segments", [])
            if now_min and calendar_date(segment) == current_day
            and float(segment["start_min"]) < now_min
            and float(segment["end_min"]) > float(segment["start_min"])
        ]

    after_days = list((after.get("engine_data") or {}).get("workdays") or [])
    newly_past = {
        segment["lot_id"]
        for segment in after.get("segments", [])
        if segment["lot_id"] not in started
        and 0 <= int(segment["day_idx"]) < len(after_days)
        and str(after_days[int(segment["day_idx"])])[:10] < current_day
        and float(segment["end_min"]) > float(segment["start_min"])
    }
    # Today before ``now``: every row of the active plan stays as it was or
    # stops at a minute not before ``now`` (the same cut as the release); a
    # row may be missing only when it made nothing before ``now``; any other
    # row is production added (or changed) in time already gone.
    kept_today = elapsed_today(before)
    after_today = elapsed_today(after)
    after_dates = calendar_dates(after)
    declared = _declared_today(before, after, current_day, now_min)
    if declared is not None:
        from backend.scheduler.history import displaced_by

        record_side, lot_id, declaration = declared
        setup_start = declaration[1]

        def ran(rows):
            # Only the record's own rows, on both sides (on the other one,
            # where the lot was planned instead): everything else is still
            # compared up to ``now`` (a later «Desfazer» or «Repor» may not
            # erase or add work that has started since).
            return [(segment, text) for segment, text in rows if segment.get("lot_id") != lot_id]

        def without_displaced(rows, snapshot):
            dates = calendar_dates(snapshot)
            kept = []
            for segment, text in rows:
                if segment.get("lot_id") != lot_id and displaced_by(
                    int(segment["day_idx"]), float(segment["start_min"]),
                    float(segment["end_min"]), segment.get("machine_id"),
                    segment.get("tool_id"), declaration,
                ):
                    part = cut_row(segment, setup_start)
                    if part is not None:
                        kept.append((part, row(part, dates)))
                    continue
                kept.append((segment, text))
            return kept

        def outside_record_time(rows):
            # «Desfazer»: on the plan without the record, what it had on the
            # record's machine (or tool) from the record's instant to ``now``
            # is the time the record occupied; it never ran, as the record's
            # own rows did not on the other side. What the record replanned
            # and has started since is on the record side, still compared.
            day, _setup, since, machine, tool = declaration
            return [
                (segment, text) for segment, text in rows
                if not (
                    int(segment["day_idx"]) == int(day)
                    and float(segment["start_min"]) >= float(since)
                    and (segment.get("machine_id") == machine
                         or (bool(tool) and segment.get("tool_id") == tool))
                )
            ]

        if record_side == "after":
            after_today = ran(after_today)
            kept_today = ran(without_displaced(kept_today, before))
        else:
            kept_today = ran(kept_today)
            after_today = ran(outside_record_time(without_displaced(after_today, after)))
    pending: dict[tuple, list[tuple[dict, str]]] = {}
    for segment, text in kept_today:
        pending.setdefault(_cut_key(segment), []).append((segment, text))
    for segment, text in after_today:
        candidates = pending.get(_cut_key(segment), [])
        match = next(
            (
                position for position, (original, original_text) in enumerate(candidates)
                if original_text == text or (
                    now_min <= float(segment["end_min"]) < float(original["end_min"])
                    and (cut := cut_row(original, segment["end_min"])) is not None
                    and row(cut, after_dates) == text
                )
            ),
            None,
        )
        if match is None:
            newly_past.add(segment["lot_id"])
        else:
            candidates.pop(match)
    newly_past |= {
        segment["lot_id"]
        for candidates in pending.values()
        for segment, _text in candidates
        if cut_row(segment, now_min) is not None
    }
    resized_today = {
        lot_id
        for lot_id in {segment["lot_id"] for segment, _text in kept_today}
        if lot_id not in started and lot_changed(lot_id)
    }
    changed = newly_past | resized_today | {
        lot_id for lot_id in started
        if lot_rows(before, lot_id) != lot_rows(after, lot_id) or lot_changed(lot_id)
    }
    return sorted(lot_id for lot_id in changed if not dropped_unmade(lot_id))


def _declared_today(before: dict, after: dict, current_day: str, now_min: int):
    """The one record of what ran today that differs between two snapshots.

    ``(side holding it, lot id, declaration)`` (``history.displaced_by``),
    or ``None``. Only an anchor written by a move to a time of today already
    gone (``manual_edits.EXECUTED``, decisão do Luís, 20/10/2026), exactly
    one, dated today: its lot has rows before ``now`` on the anchor's
    machine only, on that side; on the other, none that started before the
    record's instant (where the lot was planned before it, once that time
    has come too, is the position the record replaced). The setup start is
    the lot's first row; ``since`` is the record's own instant (its history
    boundary), so «Desfazer» later that day reads the same morning.
    """
    from backend.plans.manual_edits import EXECUTED
    from backend.scheduler.history import as_boundary

    if not now_min:
        return None

    def executed(snapshot: dict) -> list[dict]:
        return [
            anchor for anchor in (snapshot.get("engine_data") or {}).get("plan_anchors") or []
            if isinstance(anchor, dict) and anchor.get("kind") == EXECUTED
        ]

    old, new = executed(before), executed(after)
    changed = [("before", a) for a in old if a not in new] + [
        ("after", a) for a in new if a not in old
    ]
    if len(changed) != 1 or str(changed[0][1].get("start_at") or "")[:10] != current_day:
        return None
    side, anchor = changed[0]
    record, other = (before, after) if side == "before" else (after, before)
    lot_id, machine = anchor.get("lot_id"), anchor.get("machine_id")
    workdays = [str(day)[:10] for day in (record.get("engine_data") or {}).get("workdays") or []]
    if current_day not in workdays or [
        str(day)[:10] for day in (other.get("engine_data") or {}).get("workdays") or []
    ] != workdays:
        return None
    day = workdays.index(current_day)

    def rows_before_now(snapshot: dict) -> list[dict]:
        return [
            segment for segment in snapshot.get("segments") or []
            if segment.get("lot_id") == lot_id and int(segment["day_idx"]) <= day
            and (int(segment["day_idx"]) < day or float(segment["start_min"]) < now_min)
            and float(segment["end_min"]) > float(segment["start_min"])
        ]

    ran = rows_before_now(record)
    if (
        not ran
        or any(int(s["day_idx"]) != day or s.get("machine_id") != machine for s in ran)
        or len({s.get("tool_id") for s in ran}) != 1
    ):
        return None
    # Whole minutes, as the move cuts (``manual_move._declared_setup_start``).
    setup_start = int(math.floor(min(float(segment["start_min"]) for segment in ran)))
    boundary = as_boundary((record.get("engine_data") or {}).get("history_boundary"))
    since = min(boundary[1], now_min) if boundary is not None and boundary[0] == day else now_min
    if since <= setup_start or any(
        (int(s["day_idx"]), float(s["start_min"])) < (day, since) for s in rows_before_now(other)
    ):
        return None
    return side, lot_id, (day, setup_start, since, machine, ran[0].get("tool_id"))


def _candidate_eligibility(after: dict, engine_data, config):
    """``(engine_data, config)`` that judge where ``after``'s lots may run:
    the given ones, else restored from ``after``; ``(None, None)`` when it
    carries no operations (nothing justifies a change of machine)."""
    if engine_data is not None:
        return engine_data, config
    from backend.plans.serialize import deserialize_config, deserialize_engine_data

    try:
        data = deserialize_engine_data(after.get("engine_data") or {})
        factory = deserialize_config(after.get("config"))
    except Exception:  # a payload that cannot be restored justifies nothing
        logger.debug("candidate eligibility not restorable", exc_info=True)
        return None, None
    return (data, factory) if data.ops else (None, None)


def _cut_key(segment: dict) -> tuple:
    """What a cut never changes of a segment (``scheduler.history.cut_values``)."""

    return tuple(
        json.dumps(segment.get(field), sort_keys=True)
        for field in ("lot_id", "run_id", "machine_id", "tool_id", "day_idx", "start_min",
                      "shift", "setup_min", "is_continuation")
    )


def _honoured_anchor_lot_ids(baseline_result, engine_data, config) -> set[str]:
    """Anchored lots whose baseline placement already satisfies the anchor."""

    from backend.scheduler.validation import plan_anchor_violations

    anchors = list(getattr(engine_data, "plan_anchors", None) or [])
    if baseline_result is None or not anchors:
        return set()
    violated = {
        str(violation.get("lot_id"))
        for violation in plan_anchor_violations(baseline_result.segments, engine_data, config)
    }
    present = {segment.lot_id for segment in baseline_result.segments}
    return {
        anchor.lot_id
        for anchor in anchors
        if anchor.lot_id in present and anchor.lot_id not in violated
    }


# ── Manual anchors that no longer fit (decisão do Luís, 15/10/2026) ──────────
# A new input (holiday, extra day, outage, operators, ISOP, any replan) that
# clashes with a lot pinned by hand is applied; the pin is released and the
# planner is told which lot and why. A calculation is never aborted because of
# a pin; the pins that still fit are kept.

RELEASED_ANCHOR_PREFIX = "Soltei a alteração manual"
# Conflicts of a pinned lot with the calendar, its resources, its eligibility
# and its material: they hold whatever the other lots do. Shared capacity
# (overlaps, operators, setup crew) depends on the movable work and is left
# to the calculation and its safety net.
_ANCHOR_FIT_KINDS = frozenset({
    "machine_down", "tool_down", "outside_shift", "ineligible_machine", "ineligible_tool",
    "unknown_machine", "unknown_tool", "setup_before_material", "ghost_segment",
    "lot_production_minutes", "plan_anchor",
})


def _date_label(day_idx: int, data) -> str:
    """``07/12`` (``dia N`` when the calendar has no date)."""
    from backend.calendar import _day_date

    calendar_date = _day_date(int(day_idx), data) if data is not None else None
    return f"{calendar_date:%d/%m}" if calendar_date is not None else f"dia {int(day_idx)}"


def _anchor_when(anchor) -> str:
    """``03/12 17:30`` of an anchor (empty when its start cannot be read)."""
    raw = str(getattr(anchor, "start_at", "") or "")
    if len(raw) >= 16 and raw[4] == "-" and raw[10] in "T ":
        return f"{raw[8:10]}/{raw[5:7]} {raw[11:16]}"
    return ""


def released_anchor_notice(anchor, lot, reason: str) -> str:
    """«Soltei a alteração manual da Referência X (PRM043), fixada para 03/12
    17:30: <reason>.» Never the internal lot id."""
    from backend.scheduler.canonical import _lot_label

    subject = f"da {_lot_label(lot, anchor.machine_id)}" if lot is not None else "de um lote"
    when = _anchor_when(anchor)
    reason = str(reason).strip().rstrip(".")
    return (
        f"{RELEASED_ANCHOR_PREFIX} {subject}"
        + (f", fixada para {when}" if when else "")
        + f": {reason}."
    )


def _not_workday_reason(day_idx: int, data, config) -> str:
    from backend.calendar import _day_date, _is_explicit_holiday

    label = _date_label(day_idx, data)
    if _is_explicit_holiday(day_idx, _day_date(day_idx, data), data, config):
        return f"o dia {label} passou a feriado e o lote deixou de caber"
    return f"o dia {label} deixou de ser dia de trabalho e o lote deixou de caber"


def _anchor_violation_reason(violation: dict, lot, data, config) -> str:
    """Why a conflict of the pinned lot with the current inputs releases it."""
    from backend.calendar import is_factory_workday

    kind = violation.get("kind")
    day = violation.get("day_idx")
    if kind in {"machine_down", "tool_down"} and day is not None:
        if not is_factory_workday(int(day), data, config):
            return _not_workday_reason(int(day), data, config)
        resource = (
            f"a {violation.get('machine_id') or lot.machine_id}" if kind == "machine_down"
            else f"a ferramenta {violation.get('tool_id') or lot.tool_id}"
        )
        block = violation.get("unavailability")
        hours = ""
        if isinstance(block, dict) and block.get("end_min") is not None:
            start, end = int(block.get("start_min", 0)), int(block["end_min"])
            hours = f" das {start // 60:02d}:{start % 60:02d} às {end // 60:02d}:{end % 60:02d}"
        return (
            f"{resource} fica indisponível no dia {_date_label(int(day), data)}{hours} "
            "e o lote deixou de caber"
        )
    if kind in {"ineligible_machine", "unknown_machine"}:
        return f"o lote deixou de poder ser feito na {violation.get('machine_id')}"
    if kind in {"ineligible_tool", "unknown_tool"}:
        return f"o lote deixou de poder ser feito com a ferramenta {violation.get('tool_id')}"
    if kind == "outside_shift":
        return "os turnos mudaram e o lote deixou de caber nas horas fixadas"
    if kind in {"setup_before_material", "source_contract"}:
        floor = violation.get("material_floor_day")
        if floor is not None:
            return (
                "o material deste lote só é libertado no dia "
                f"{_date_label(int(floor), data)}"
            )
        return "o material deste lote ainda não está libertado nessa data"
    message = str(violation.get("message") or "").strip().rstrip(".")
    return (message[:1].lower() + message[1:]) if message else "o lote deixou de caber"


def _anchor_misfits(anchors, baseline, engine_data, config, history: set[str]) -> dict:
    """``{lot_id: reason}`` of the anchors that no longer fit the current inputs.

    Each pinned lot that has not started is judged where the baseline has it,
    against the current data: its days are working days, its machine is
    active, then the same validator as any plan for the conflicts that hold
    whatever the other lots do (``_ANCHOR_FIT_KINDS``: machine and tool
    availability, shifts, eligibility, the material release ``R`` with the
    lot's deliveries dated by the current calendar, the anchor itself).
    """
    from backend.calendar import is_factory_workday
    from backend.scheduler.validation import plan_anchor_violations, validate_plan

    lots_by_id = {lot.id: lot for lot in baseline.lots}
    by_lot: dict[str, list] = {}
    for segment in baseline.segments:
        by_lot.setdefault(segment.lot_id, []).append(segment)
    active = {machine.id for machine in engine_data.machines}
    misfits: dict[str, str] = {}
    checked = []
    for anchor in anchors:
        if anchor.lot_id in history:
            continue
        lot = lots_by_id.get(anchor.lot_id)
        segments = [s for s in by_lot.get(anchor.lot_id, []) if s.end_min > s.start_min]
        if lot is None or not segments:
            misfits[anchor.lot_id] = "o lote deixou de existir no plano"
            continue
        if anchor.machine_id not in active:
            misfits[anchor.lot_id] = f"a máquina {anchor.machine_id} deixou de estar ativa"
            continue
        off = next(
            (s.day_idx for s in segments
             if not is_factory_workday(s.day_idx, engine_data, config)),
            None,
        )
        if off is not None:
            misfits[anchor.lot_id] = _not_workday_reason(off, engine_data, config)
            continue
        checked.append(anchor)
    if not checked:
        return misfits
    # A pinned lot that continues a mounted tool without setup is kept with
    # the lots that mount it (``_protected_plan``): they are judged with it.
    suppliers = _anchor_mount_suppliers(baseline.segments, [a.lot_id for a in checked])
    judged = {
        lot_id for anchor in checked for lot_id in suppliers[anchor.lot_id] | {anchor.lot_id}
    } - history
    view = copy.copy(engine_data)
    view.plan_anchors = list(checked)
    # A pinned lot is a position, not history: judged with its deliveries
    # dated by the current calendar and without a preservation proof.
    view.preserved_lot_proofs = {
        lot_id: proof for lot_id, proof in (engine_data.preserved_lot_proofs or {}).items()
        if lot_id not in judged
    }
    lots = [
        _current_delivery_dates(lot, engine_data) if lot.id in judged else lot
        for lot in baseline.lots
    ]
    violations = [
        *plan_anchor_violations(baseline.segments, view, config),
        *validate_plan(baseline.segments, view, config, lots=lots),
    ]
    unfit: dict[str, str] = {}
    for violation in violations:
        lot_id = str(violation.get("lot_id") or "")
        if lot_id not in judged or lot_id in unfit or lot_id not in lots_by_id:
            continue
        kind = violation.get("kind")
        if kind not in _ANCHOR_FIT_KINDS and not (
            kind == "source_contract" and violation.get("field") == "material_quantity"
        ):
            continue
        unfit[lot_id] = _anchor_violation_reason(
            violation, lots_by_id[lot_id], engine_data, config,
        )
    from backend.scheduler.canonical import _lot_label

    anchored_ids = {anchor.lot_id for anchor in anchors}
    for anchor in checked:
        if anchor.lot_id in unfit:
            misfits[anchor.lot_id] = unfit[anchor.lot_id]
            continue
        supplier = next((
            lot_id for lot_id in sorted(suppliers[anchor.lot_id])
            if lot_id in unfit or lot_id in misfits
        ), None)
        if supplier is None:
            continue
        label = _lot_label(lots_by_id[supplier])
        if supplier in anchored_ids:
            misfits[anchor.lot_id] = (
                f"seguia sem nova afinação a seguir à {label}, que também foi solta"
            )
        else:
            misfits[anchor.lot_id] = (
                f"seguia sem nova afinação a seguir à {label}, que deixou de caber "
                f"({unfit.get(supplier) or misfits[supplier]})"
            )
    return misfits


def _anchor_mount_suppliers(segments, lot_ids) -> dict[str, set[str]]:
    """``{lot_id: lots whose mounted tool it continues without setup}``, transitively."""
    previous = _machine_order(segments)
    by_lot: dict[str, set[int]] = {}
    for index, segment in enumerate(segments):
        by_lot.setdefault(segment.lot_id, set()).add(index)
    result = {}
    for lot_id in lot_ids:
        found: set[str] = set()
        while True:
            selected = set().union(*(by_lot.get(item, set()) for item in found | {lot_id}))
            missing = {
                segments[index].lot_id
                for index in _mount_suppliers(segments, selected, previous)
            } - found - {lot_id}
            if not missing:
                break
            found |= missing
        result[lot_id] = found
    return result


# Pins released during one replan job (``{lot_id: notice}``). The job may
# discard the calculation whose warnings carried a notice while keeping the
# staging data the pin was removed from; the ledger lets it still say so.
_RELEASED_ANCHORS: ContextVar[dict[str, str] | None] = ContextVar(
    "released_anchors", default=None,
)


@contextmanager
def released_anchor_ledger() -> Iterator[dict[str, str]]:
    """Record every pin ``release_anchors`` removes inside this block."""
    ledger: dict[str, str] = {}
    token = _RELEASED_ANCHORS.set(ledger)
    try:
        yield ledger
    finally:
        _RELEASED_ANCHORS.reset(token)


def released_anchor_notices_missing(engine_data) -> list[str]:
    """Notices of recorded pins absent from ``engine_data.plan_anchors``."""
    ledger = _RELEASED_ANCHORS.get() or {}
    kept = {anchor.lot_id for anchor in getattr(engine_data, "plan_anchors", None) or []}
    return [notice for lot_id, notice in ledger.items() if lot_id not in kept]


def release_anchors(engine_data, lots, reasons: dict) -> list[str]:
    """Remove the anchors of ``reasons`` (``{lot_id: reason}``); their notices."""
    if not reasons:
        return []
    lots_by_id = {lot.id: lot for lot in lots or []}
    anchors = list(getattr(engine_data, "plan_anchors", None) or [])
    notices = []
    for anchor in anchors:
        if anchor.lot_id in reasons:
            notice = released_anchor_notice(
                anchor, lots_by_id.get(anchor.lot_id), reasons[anchor.lot_id],
            )
            logger.info("Fixação manual solta (%s): %s", anchor.lot_id, notice)
            notices.append(notice)
            ledger = _RELEASED_ANCHORS.get()
            if ledger is not None:
                ledger[anchor.lot_id] = notice
    engine_data.plan_anchors = [anchor for anchor in anchors if anchor.lot_id not in reasons]
    return notices


def reconcile_manual_anchors(
    engine_data, config, baseline_result, *, now: datetime | None = None,
) -> list[str]:
    """Release the manual anchors the current inputs no longer allow.

    Called at the start of every calculation that keeps the manual positions
    (``optimize_preserving_started_lots``, ``compact_preserving_started_lots``),
    so a holiday, an extra day, an outage, an operator change, a new ISOP or
    any replan never aborts because of a pin (decisão do Luís, 15/10/2026).
    Each anchor is checked against ``engine_data`` as it is now
    (``_anchor_misfits``). The anchors that fail are removed from
    ``engine_data.plan_anchors`` (the write's staging data, so
    ``manual_edits.sync_manual_edits`` drops their records); the others are
    kept. A pinned lot that has started is history and stays protected.

    Returns one plain pt-PT notice per released pin
    (``released_anchor_notice``), for the plan warnings.
    """
    anchors = list(getattr(engine_data, "plan_anchors", None) or [])
    if not anchors or baseline_result is None:
        return []
    now = calculation_now(config, now)
    freeze_day = _current_planning_day(engine_data, config, now)
    now_min = elapsed_on_planning_day(freeze_day, engine_data, config, now)
    baseline = with_current_material(baseline_result, engine_data, record=False)
    history = {
        segment.lot_id for segment in baseline.segments
        if started_before(segment, freeze_day, now_min)
    }
    misfits = _anchor_misfits(anchors, baseline, engine_data, config, history)
    misfits.update(_records_stopped_unmade(
        anchors, baseline, engine_data, config, history, freeze_day, now,
    ))
    return release_anchors(engine_data, baseline.lots, misfits)


# A record of what ran (``manual_edits.EXECUTED``) that a new input stops
# before its first piece: like any started lot it is released whole and
# replanned (``scheduler.history``), so the record goes too (20/10/2026).
_RECORD_STOPPED_UNMADE = (
    "a alteração nova parou-a antes da primeira peça; deixa de estar registada como "
    "feita e é replaneada a partir de agora"
)


def _records_stopped_unmade(
    anchors, baseline, engine_data, config, history: set[str], freeze_day: int, now,
) -> dict[str, str]:
    """``{lot_id: reason}`` of the records of what ran the protection releases whole.

    A record is protected during the day like any started lot: a new input
    cuts it at ``max(now, conflict start)`` and the part made stays, so its
    anchor still holds. When nothing was made by then the lot is released
    whole (``_conflict_cuts``); its anchor can no longer hold and is released
    with a notice instead of failing the whole replan.
    """
    from backend.plans.manual_edits import EXECUTED

    records = {
        anchor.lot_id for anchor in anchors
        if getattr(anchor, "kind", "") == EXECUTED and anchor.lot_id in history
    }
    if not records:
        return {}
    protection = _protected_plan(baseline, freeze_day, engine_data, config, now=now)
    kept = {segment.lot_id for segment in protection.segments}
    return {lot_id: _RECORD_STOPPED_UNMADE for lot_id in sorted(records - kept)}


def anchors_in_violations(violations, engine_data, segments=()) -> set[str]:
    """Anchored lots a refusal involves; every anchor when it names no lot.

    A conflict names its lot (``lot_id``), the lot it clashes with
    (``other``) and the reservation's holder (``unavailability``). An anchor
    is involved too when a named lot mounts the tool it continues without
    setup in ``segments`` (the baseline): that lot is kept with it.
    """
    anchored = {anchor.lot_id for anchor in getattr(engine_data, "plan_anchors", None) or []}
    named = set()
    for violation in violations or []:
        if not isinstance(violation, dict):
            continue
        for item in (violation, violation.get("other"), violation.get("unavailability")):
            if isinstance(item, dict) and item.get("lot_id"):
                named.add(str(item["lot_id"]))
    if not named:
        return anchored
    segments = list(segments or [])
    suppliers = _anchor_mount_suppliers(segments, sorted(anchored)) if segments else {}
    return {
        lot_id for lot_id in anchored
        if lot_id in named or suppliers.get(lot_id, set()) & named
    }


def with_released_anchor_notices(result, notices):
    """``result`` with the released-pin notices first among its warnings."""
    if notices:
        result.warnings = [
            *notices,
            *(warning for warning in result.warnings or [] if warning not in notices),
        ]
    return result


def _protected_lots(
    baseline_result, freeze_day: int, engine_data, config, *, mount_suppliers: bool = False,
):
    """Started lots plus manually anchored lots, kept exactly as in the baseline.

    Whole lots (manual moves). ``mount_suppliers``: for a calculation that
    re-allocates the other lots, also keep whole every lot whose mounted tool
    a protected setup-free continuation needs (transitively). Improvement
    alone does not need it: it validates the complete plan.

    An anchor is a saved manual decision. The constructive solver can only
    honour it inside the CP-SAT model; when that model times out the fallback
    and the post-processing ignore it, and every candidate is rejected by the
    anchor gate. Reserving the anchored lot like confirmed history keeps the
    decision intact and lets the rest of the plan be recalculated around it.
    """

    segments, lots = _frozen_started_lots(baseline_result, freeze_day)
    anchored = _honoured_anchor_lot_ids(baseline_result, engine_data, config) - {
        lot.id for lot in lots
    }
    if anchored:
        segments = [
            *segments,
            *(copy.deepcopy(s) for s in baseline_result.segments if s.lot_id in anchored),
        ]
        lots = [
            *lots,
            *(copy.deepcopy(lot) for lot in baseline_result.lots if lot.id in anchored),
        ]
    # A protected setup-free continuation needs the lot that mounted its tool:
    # keep that supplier whole too (never leave a frozen continuation without
    # its mounting, AGENTS §4).
    if not lots or not mount_suppliers:
        return segments, lots, anchored
    protected = {lot.id for lot in lots}
    suppliers = set()
    previous = _machine_order(baseline_result.segments)
    while True:
        selected = {
            index for index, segment in enumerate(baseline_result.segments)
            if segment.lot_id in protected | suppliers
        }
        missing = {
            baseline_result.segments[supplier].lot_id
            for supplier in _mount_suppliers(baseline_result.segments, selected, previous)
        } - protected - suppliers
        if not missing:
            break
        suppliers |= missing
    if suppliers:
        segments = [
            *segments,
            *(copy.deepcopy(s) for s in baseline_result.segments if s.lot_id in suppliers),
        ]
        lots = [
            *lots,
            *(copy.deepcopy(lot) for lot in baseline_result.lots if lot.id in suppliers),
        ]
    return segments, lots, anchored


def _machine_order(segments) -> dict[int, int | None]:
    """Index of the previous productive segment on the same machine."""

    previous: dict[int, int | None] = {}
    last_by_machine: dict[str, int] = {}
    order = sorted(
        (index for index, segment in enumerate(segments) if segment.end_min > segment.start_min),
        key=lambda index: (
            segments[index].day_idx, segments[index].start_min, segments[index].end_min,
        ),
    )
    for index in order:
        machine = segments[index].machine_id
        previous[index] = last_by_machine.get(machine)
        last_by_machine[machine] = index
    return previous


def _mount_suppliers(segments, selected: set[int], previous=None) -> set[int]:
    """Unselected segments whose mounted tool a selected one continues.

    A setup-free segment relies on the preceding segment of the same machine
    when it has the same setup identity (the mounting is retained).
    """
    from backend.scheduler.setup_identity import segment_setup_identity

    previous = _machine_order(segments) if previous is None else previous
    suppliers = set()
    for index in selected:
        segment = segments[index]
        before = previous.get(index)
        if (
            before is not None and before not in selected and segment.setup_min <= 0
            and segment_setup_identity(segments[before]) == segment_setup_identity(segment)
        ):
            suppliers.add(before)
    return suppliers


def free_working_time_between(
    machine_id: str, tool_id: str, start: tuple[int, float], end: tuple[int, float],
    freeze_day: int, engine_data, config, *, segments=(), required_operators: int = 1,
    now: datetime | None = None,
) -> bool:
    """Whether ``[start, end)`` holds free shift time the machine and tool could work.

    ``start``/``end`` are ``(day, minute)``. Judged on the current inputs by
    ``backend.calendar.free_shift_intervals``, the same definition as the
    idle-capacity check: only a free interval of at least
    ``MIN_FREE_INTERVAL_MIN`` counts. Not free: elapsed time (days before
    ``freeze_day`` and, today, the minutes before the current factory minute,
    ``now`` replacing the clock), time outside the shifts, weekends and
    holidays, machine and tool unavailabilities, the tool at work on another
    machine and time without ``required_operators`` operators of the
    machine's group left by ``segments`` (the plan). The interval holds no
    other productive segment of the machine (it is the gap between two
    consecutive ones).
    """
    from backend.calendar import elapsed_minutes, free_shift_intervals
    from backend.config.types import FactoryConfig

    config = config or FactoryConfig()
    start_day, start_min = start
    end_day, end_min = end
    by_day: dict[int, list] = {}
    for segment in segments:
        by_day.setdefault(segment.day_idx, []).append(segment)
    for day in range(max(int(start_day), int(freeze_day)), int(end_day) + 1):
        low = float(start_min) if day == start_day else 0.0
        high = float(end_min) if day == end_day else 1440.0
        low = max(low, float(elapsed_minutes(day, engine_data, config, now=now)))
        if high <= low:
            continue
        if free_shift_intervals(
            machine_id, tool_id, day, engine_data, config, segments=by_day.get(day, []),
            required_operators=required_operators, start_min=low, end_min=high,
        ):
            return True
    return False


def _running_continuations(
    segments, freeze_day: int, previous, engine_data, config, *, now: datetime | None = None,
    started: set[int] | None = None,
) -> list[tuple[int, list[int]]]:
    """Per machine, the run mounted at the planning boundary that goes on.

    Starting from the last started segment (``started``, default: those
    before ``freeze_day``; the boundary), the
    following segments of the same machine with the same setup identity and
    no new setup (or the rest of a setup split before the boundary) are the
    same physical run continuing, while no free working time separates them
    (``free_working_time_between``, decided 13/10/2026): nights, weekends,
    holidays, unavailabilities, elapsed time and gaps shorter than
    ``MIN_FREE_INTERVAL_MIN`` do not interrupt a run; idle shift time does,
    and the rest of the lot is replanned. ``engine_data`` (the current
    calendar) is required: without it every gap would look free. Returns
    ``(boundary, continuation)`` pairs.
    """
    from backend.scheduler.operators import segment_operator_demand
    from backend.scheduler.setup_identity import segment_setup_identity

    if engine_data is None:
        raise ValueError("Rule 4 contiguity needs the current calendar (EngineData).")
    following: dict[int, int] = {
        before: index for index, before in previous.items() if before is not None
    }
    chains = []
    last_started: dict[str, int] = {}
    for index in previous:
        segment = segments[index]
        if (index in started) if started is not None else segment.day_idx < freeze_day:
            current = last_started.get(segment.machine_id)
            if current is None or (
                (segment.day_idx, segment.start_min, segment.end_min)
                > (segments[current].day_idx, segments[current].start_min,
                   segments[current].end_min)
            ):
                last_started[segment.machine_id] = index
    productive = [segment for segment in segments if segment.end_min > segment.start_min]
    for boundary in last_started.values():
        chain = []
        before = boundary
        index = following.get(before)
        while index is not None:
            segment, mounted = segments[index], segments[before]
            if segment_setup_identity(segment) != segment_setup_identity(mounted) or not (
                segment.setup_min <= 0 or mounted.prod_min <= 0
            ):
                break
            if free_working_time_between(
                segment.machine_id, segment.tool_id,
                (mounted.day_idx, mounted.end_min), (segment.day_idx, segment.start_min),
                freeze_day, engine_data, config, segments=productive,
                required_operators=segment_operator_demand(segment, engine_data), now=now,
            ):
                break
            chain.append(index)
            before, index = index, following.get(index)
        if chain:
            chains.append((boundary, chain))
    return chains


def _stop_minute(segment, conflict: float, boundary: tuple[int, int]) -> int:
    """Where a conflict starting at ``conflict`` stops ``segment``.

    ``max(boundary, conflict start)`` (``scheduler.history``): never before
    the segment starts, never in time already gone.
    """
    minute = max(float(segment.start_min), float(conflict))
    if segment.day_idx == boundary[0]:
        minute = max(minute, float(boundary[1]))
    return int(math.ceil(minute))


def _conflict_cuts(
    segments, started: set[int], chains, previous, boundary: tuple[int, int], engine_data,
    config, lots_by_id=None,
) -> tuple[dict, set[int]]:
    """Where the current inputs stop the protected work (AGENTS §2 rule 4).

    The protected work the inputs judge is, per machine, the planning day's
    started segments and the run mounted at the boundary that goes on
    (``chains``). It is validated with the plan's history boundary
    (``scheduler.history``): an input judges it only from
    ``max(boundary, its start)`` on. A segment an input conflicts with stops
    at ``max(boundary, conflict start)`` (``_stop_minute``); what that machine
    protects after it is released. A day that stopped being a working day (a
    holiday entered today) stops its protected work the same way. An
    operator shortage names no lot: the protected segment of that group and
    shift that starts last (machine, lot as tie-breakers) stops at the
    boundary, until the shortage is gone.
    A machine the lot may no longer use (deactivated, or no longer its
    primary or alternative; ``lots_by_id`` names the lots) stops its work
    the same way (owner decision, 16/10/2026).
    Returns ``({index: frozen part or None}, released indexes)``; ``None``
    means the segment made nothing before its stop and is released whole.
    """
    from backend.calendar import is_factory_workday
    from backend.scheduler.history import cut_segment, judged_start
    from backend.scheduler.validation import validate_plan

    if engine_data is None:
        return {}, set()
    sequences: dict[str, list[int]] = {}
    chained = {index for _boundary, chain in chains for index in chain}
    for index in {*chained, *(i for i in started if segments[i].day_idx >= boundary[0])}:
        sequences.setdefault(segments[index].machine_id, []).append(index)
    if not sequences:
        return {}, set()
    for sequence in sequences.values():
        sequence.sort(key=lambda index: (
            segments[index].day_idx, segments[index].start_min, segments[index].end_min,
        ))
    view = copy.copy(engine_data)
    view.history_boundary = [int(boundary[0]), int(boundary[1])]
    groups = {
        machine.id: config.machine_group(machine.id) if config is not None else machine.group
        for machine in engine_data.machines
    }
    if config is not None:
        groups.update({mid: config.machine_group(mid) for mid in config.machines})
    shifts = (
        {shift.id: (shift.start_min, shift.end_min) for shift in config.shifts}
        if config is not None else {"A": (420, 930), "B": (930, 1440)}
    )
    # The mounting evidence of each sequence: the segment before it.
    evidence = [
        segments[previous[sequence[0]]] for sequence in sequences.values()
        if previous.get(sequence[0]) is not None
    ]
    stops: dict[str, tuple[int, float]] = {}
    working: dict[int, bool] = {}

    def protected():
        entries = []
        for machine, sequence in sequences.items():
            stop = stops.get(machine)
            for position, index in enumerate(sequence):
                segment = segments[index]
                if stop is not None and position >= stop[0]:
                    if position > stop[0]:
                        break
                    segment = cut_segment(segment, stop[1])
                    if segment is None:
                        break
                entries.append((segment, machine, position))
        return entries

    for _round in range(sum(map(len, sequences.values())) + 1):
        entries = protected()
        by_key = {
            (s.lot_id, s.machine_id, s.day_idx, s.start_min, s.end_min): (s, m, p)
            for s, m, p in entries
        }
        proposals: dict[str, tuple[int, float]] = {}

        def propose(machine: str, position: int, minute: float) -> None:
            if machine not in proposals or (position, minute) < proposals[machine]:
                proposals[machine] = (position, minute)

        shortages = set()
        violations = validate_plan(
            [*evidence, *(segment for segment, _m, _p in entries)], view, config, memo=False,
        )
        for violation in violations:
            if violation.get("kind") == "operator_capacity":
                shortages.add((
                    int(violation.get("day_idx", -1)), str(violation.get("group", "")),
                    str(violation.get("shift", "")),
                ))
                continue
            for item in (violation, violation.get("other") or {}):
                key = (item.get("lot_id"), item.get("machine_id"), item.get("day_idx"),
                       item.get("start_min"), item.get("end_min"))
                if key not in by_key:
                    continue
                segment, machine, position = by_key[key]
                block = violation.get("unavailability") if item is violation else None
                conflict = float(block.get("start_min", 0)) if block else segment.start_min
                minute = _stop_minute(segment, conflict, boundary)
                # A segment over by then is history: nothing of it to stop.
                if minute < segment.end_min:
                    propose(machine, position, minute)
        # A day that is no longer a working day (a holiday entered today) is
        # not a violation the validator reports: its judged part stops. Nor
        # is a machine the lot may no longer use.
        for segment, machine, position in entries:
            lot = (lots_by_id or {}).get(segment.lot_id)
            allowed = allowed_machines(lot, engine_data, config) if lot is not None else None
            if allowed is not None and machine not in allowed and judged_start(
                segment.day_idx, segment.start_min, segment.end_min, boundary,
            ) is not None:
                propose(machine, position, _stop_minute(segment, segment.start_min, boundary))
            day = segment.day_idx
            if day not in working:
                working[day] = is_factory_workday(day, engine_data, config)
            if not working[day] and judged_start(
                day, segment.start_min, segment.end_min, boundary,
            ) is not None:
                propose(machine, position, _stop_minute(segment, segment.start_min, boundary))
        for day, group, shift in sorted(shortages):
            shift_start, shift_end = shifts.get(shift, (0, 1440))
            staffed = []
            for segment, machine, position in entries:
                judged = judged_start(
                    segment.day_idx, segment.start_min, segment.end_min, boundary,
                )
                if (
                    segment.day_idx == day and groups.get(machine, "Grandes") == group
                    and segment.prod_min > 0 and judged is not None
                    and max(segment.production_start_min, judged, shift_start)
                    < min(segment.end_min, shift_end)
                ):
                    staffed.append((segment, machine, position))
            if staffed:
                segment, machine, position = max(
                    staffed, key=lambda entry: (entry[0].start_min, entry[1], entry[0].lot_id),
                )
                propose(machine, position, _stop_minute(segment, segment.start_min, boundary))
        changed = False
        for machine, stop in proposals.items():
            if machine not in stops or stop < stops[machine]:
                stops[machine] = stop
                changed = True
        if not changed:
            break
    cuts, released = {}, set()
    for machine, (position, minute) in stops.items():
        sequence = sequences[machine]
        cuts[sequence[position]] = cut_segment(segments[sequence[position]], minute)
        released.update(sequence[position + 1:])
    return cuts, released


def _protected_plan(
    baseline_result, freeze_day: int, engine_data, config, *, now: datetime | None = None,
) -> ProtectedPlan:
    """Frozen segments and lots of a replan under AGENTS §2, rule 4.

    Frozen: every segment before ``freeze_day``, the run mounted at that
    boundary while it continues without a new setup and without free working
    time in between, manually anchored lots, and — closed under these two
    rules until nothing changes — the earlier production of each touched lot
    (a frozen part is always a prefix of its lot) and the mount supplier of
    every frozen setup-free continuation. A touched lot whose rest cannot be
    replanned on its own (older material contract, anchored, nothing left)
    is kept whole.

    The boundary is the current factory minute (13/10/2026): on the planning
    day the segments that start before ``now`` (the calculation's instant,
    ``calculation_now``) have started like the days before, one running at
    ``now`` as a whole, and the mounted run continues from the last of them;
    today's elapsed minutes are not free time. The current inputs judge this
    protected work only from the boundary on; where one conflicts with it,
    the segment stops at ``max(now, conflict start)`` — the part before stays
    as it was, the rest is replanned as the rest of the same lot — and what
    the machine protects after it is released (``_conflict_cuts``, the one
    rule of ``scheduler.history`` that validation and the commit guard read).
    """
    from backend.scheduler.history import rest_of_cut
    from backend.scheduler.lot_sizing import WHOLE_LOT_MATERIAL_VERSION
    from backend.scheduler.material_quantities import lot_material_version

    if baseline_result is None:
        return ProtectedPlan()
    now = calculation_now(config, now)
    now_min = elapsed_on_planning_day(freeze_day, engine_data, config, now)
    # A per-delivery plan (versions 1-2) is protected as version 3: its
    # started lots are frozen only where they started. The productions of
    # upgraded lots are recorded by the calculation's entry point, from the
    # stored plan; ``baseline_result`` here may be a candidate.
    baseline_result = with_current_material(baseline_result, engine_data, record=False)
    segments = list(baseline_result.segments)
    lots_by_id = {lot.id: lot for lot in baseline_result.lots}
    anchored = _honoured_anchor_lot_ids(baseline_result, engine_data, config)
    if freeze_day > 0 or now_min > 0:
        from backend.plans.manual_edits import executed_lot_ids

        # A record of what ran is history during the day, like any started
        # lot: a new input may cut it and the record stays (20/10/2026).
        # From D0 («Recalcular plano») it pins the lot where it ran.
        anchored -= executed_lot_ids(engine_data)
    previous = _machine_order(segments)
    started_ids = set()
    started_lots: set[str] = set()
    selected: set[int] = set()
    kept: set[int] = set()
    parts: dict[int, object] = {}
    if freeze_day > 0 or now_min > 0:
        started = {
            index for index, segment in enumerate(segments)
            if started_before(segment, freeze_day, now_min)
        }
        chains = _running_continuations(
            segments, freeze_day, previous, engine_data, config, now=now, started=started,
        )
        cuts, released = _conflict_cuts(
            segments, started, chains, previous, (freeze_day, now_min), engine_data, config,
            lots_by_id,
        )
        parts = {index: part for index, part in cuts.items() if part is not None}
        kept = (started | {index for _boundary, chain in chains for index in chain}) - released
        selected.update(index for index in kept if index not in cuts or index in parts)
        started_ids = {segments[index].lot_id for index in started & selected}
        started_lots = {segments[index].lot_id for index in started}
    selected.update(
        index for index, segment in enumerate(segments) if segment.lot_id in anchored
    )
    if not selected and not started_lots:
        return ProtectedPlan(anchored=set())
    by_lot: dict[str, list[int]] = {}
    for index, segment in enumerate(segments):
        by_lot.setdefault(segment.lot_id, []).append(index)
    for indexes in by_lot.values():
        indexes.sort(key=lambda index: (
            segments[index].day_idx, segments[index].start_min, segments[index].end_min,
        ))
    forced_whole: set[str] = set()

    def keeps_whole(lot_id: str) -> bool:
        lot = lots_by_id.get(lot_id)
        if lot is None or lot_id in anchored or (
            lot_material_version(lot) < WHOLE_LOT_MATERIAL_VERSION
        ):
            forced_whole.add(lot_id)
            return True
        frozen_qty = sum(
            int(parts.get(index, segments[index]).qty)
            for index in by_lot[lot_id] if index in selected
        )
        return frozen_qty >= int(lot.qty)

    while True:
        before = len(selected)
        for lot_id in {segments[index].lot_id for index in selected}:
            indexes = by_lot[lot_id]
            if keeps_whole(lot_id):
                selected.update(indexes)
                continue
            last = max(position for position, index in enumerate(indexes) if index in selected)
            selected.update(indexes[: last + 1])
        selected |= _mount_suppliers(segments, selected, previous)
        if len(selected) == before:
            break

    # A started lot whose started segments were all released (a setup under
    # way at "now" that a new input stops) is still started: never re-sized,
    # its whole quantity is replanned as its rest (rule 4). One that cannot
    # be replanned on its own stays as it was.
    released_lots = {
        lot_id for lot_id in started_lots
        if not any(index in selected for index in by_lot[lot_id])
    }
    for lot_id in sorted(released_lots):
        lot = lots_by_id.get(lot_id)
        if lot is None or lot_id in anchored or (
            lot_material_version(lot) < WHOLE_LOT_MATERIAL_VERSION
        ):
            forced_whole.add(lot_id)
            selected.update(by_lot[lot_id])
            released_lots.discard(lot_id)
    # A lot that cannot be replanned on its own stays as it was (no cut).
    parts = {
        index: part for index, part in parts.items()
        if segments[index].lot_id not in forced_whole
    }
    touched = {segments[index].lot_id for index in selected}
    # Rows holding fewer pieces than their lot (what a record of what ran
    # left of a displaced lot, ``manual_move._without_displaced``): the lot
    # is not whole, its rest is replanned.
    short = {
        lot_id for lot_id in touched
        if lot_id not in forced_whole and lot_id in lots_by_id
        and sum(int(segments[index].qty) for index in by_lot[lot_id])
        < int(lots_by_id[lot_id].qty)
    }
    whole = {
        lot_id for lot_id in touched
        if set(by_lot[lot_id]) <= selected and not any(i in parts for i in by_lot[lot_id])
        and lot_id not in short
    }
    # Kept whole only for a manual anchor (or to mount an anchored lot's
    # tool): nothing of it has started, so it is a position, not history.
    # It follows the current calendar like every lot (its deliveries are
    # dated again, ``_current_delivery_dates``), its output is credited on
    # the days of the deliveries it serves, never as stock on day 0
    # (``_install_frozen_reservations``), and it carries no preservation
    # proof: the complete plan judges it against the current sizing.
    history = {segments[index].lot_id for index in kept} | started_lots
    pinned = {lot_id for lot_id in whole if lot_id not in history and lot_id in lots_by_id}
    redated = {
        lot_id: lot for lot_id in sorted(pinned)
        if (lot := _current_delivery_dates(lots_by_id[lot_id], engine_data))
        != lots_by_id[lot_id]
    }
    frozen_segments = [
        _with_lot_metadata(copy.deepcopy(segment), redated[segment.lot_id])
        if segment.lot_id in redated else copy.deepcopy(parts.get(index, segment))
        for index, segment in enumerate(segments) if index in selected
    ]
    frozen_lots = [copy.deepcopy(redated.get(lot_id, lots_by_id[lot_id]))
                   for lot_id in sorted(whole) if lot_id in lots_by_id]
    partial = []
    for lot_id in sorted((touched - whole) | released_lots):
        # Never re-sized, but its deliveries are dated by the current calendar
        # (a holiday added since it was sized moves U and R like for any lot).
        lot = _current_delivery_dates(lots_by_id[lot_id], engine_data)
        started = [parts.get(index, segments[index]) for index in by_lot[lot_id]
                   if index in selected]
        # The rest stays on the machine it started on while the lot may still
        # use it; otherwise it moves to an allowed active machine (new setup)
        # and, with none, it is unmet demand: the lot keeps only what it made
        # (owner decision, 16/10/2026).
        machine = next((s.machine_id for s in started if s.prod_min > 0), lot.machine_id)
        allowed = allowed_machines(lot, engine_data, config)
        alt = None
        if allowed is not None and machine not in allowed:
            if allowed:
                # The second allowed machine stays its alternative: dispatch
                # may use it when the first is full.
                alt = allowed[1] if len(allowed) > 1 else None
                lot = _on_machine(lot, allowed[0], engine_data, config, alt=alt)
                machine = allowed[0]
            else:
                made = _made_part(lot, started)
                if made is not None:
                    frozen_lots.append(made)
                    frozen_segments = [
                        _with_lot_metadata(segment, made) if segment.lot_id == lot_id
                        else segment
                        for segment in frozen_segments
                    ]
                else:
                    frozen_segments = [s for s in frozen_segments if s.lot_id != lot_id]
                continue
        partial.append((
            copy.deepcopy(lot),
            _remainder_lot(lot, started, engine_data, config, machine, alt=alt),
        ))
    return ProtectedPlan(
        segments=frozen_segments, lots=frozen_lots, partial=partial,
        anchored=anchored - started_ids, started=started_ids, pinned=pinned,
        cut=[
            (copy.deepcopy(segments[index]), rest_of_cut(segments[index], part))
            for index, part in sorted(parts.items())
        ],
        now_label=boundary_label(freeze_day, now_min, engine_data),
    )


def with_current_material(
    baseline_result, engine_data, config=None, boundary=None, *, record: bool = True,
):
    """The baseline with the lots of a per-delivery plan under material version 3.

    A plan saved under versions 1-2 stays valid (``legacy_material_plan``);
    a replan, repair or manual move takes its lots over as version 3
    (``lot_sizing.upgrade_plan_material``), so the started ones are frozen
    only where they started (rule 4) and the plan never mixes release
    contracts. Their quantities stay as sized (multiples of the economic lot,
    before 14/10/2026); «Recalcular plano» sizes them again.

    Each lot taken over records how many productions it has in this
    baseline (``lot_sizing.UPGRADED_PRODUCTIONS_KEY``, counted by
    ``validation.lot_productions`` at the calculation's history ``boundary``,
    ``planning_boundary``): it may keep them, never gain one
    (``validation.lot_split_violations``). Only a calculation's entry point
    records them, from the stored plan (``record``); the counts it wrote stay
    with the lots. Returns ``baseline_result`` itself when nothing changes.
    """
    from backend.scheduler.lot_sizing import upgrade_plan_material

    if baseline_result is None or engine_data is None:
        return baseline_result
    lots = upgrade_plan_material(list(baseline_result.lots), engine_data)
    if record:
        lots = _with_upgraded_productions(
            lots, baseline_result.segments, engine_data, config, boundary,
        )
    if all(new is old for new, old in zip(lots, baseline_result.lots, strict=True)):
        return baseline_result
    upgraded = copy.copy(baseline_result)
    upgraded.lots = lots
    return upgraded


def _with_upgraded_productions(lots, segments, engine_data, config, boundary):
    """``lots`` with the productions of each upgraded lot in ``segments`` recorded."""
    from backend.scheduler.history import as_boundary
    from backend.scheduler.lot_sizing import UPGRADED_MATERIAL_KEY, UPGRADED_PRODUCTIONS_KEY
    from backend.scheduler.validation import lot_productions

    upgraded = [
        lot for lot in lots
        if any(output.get(UPGRADED_MATERIAL_KEY) for output in lot.output_milestones or [])
    ]
    if not upgraded:
        return lots
    counts = lot_productions(
        list(segments or []), upgraded, engine_data, config, boundary=as_boundary(boundary),
    )
    marked = {id(lot) for lot in upgraded}
    result = []
    for lot in lots:
        count = max(1, counts.get(lot.id, 0)) if id(lot) in marked else None
        if count is None or all(
            output.get(UPGRADED_PRODUCTIONS_KEY) == count for output in lot.output_milestones
        ):
            result.append(lot)
            continue
        recorded = copy.deepcopy(lot)
        for output in recorded.output_milestones:
            output[UPGRADED_PRODUCTIONS_KEY] = count
        result.append(recorded)
    return result


def _current_delivery_dates(lot, engine_data):
    """A started lot whose rest is replanned, dated by the current inputs.

    The lot keeps its size and deliveries (rule 4); the delivery dates derived
    from the calendar follow the current one (``lot_sizing.redate_lot_outputs``).
    The full-plan contract check compares the lot with the lots sized from the
    current inputs, and the rest is planned with the current material windows.
    """
    from backend.scheduler.lot_sizing import redate_lot_outputs

    if engine_data is None or not getattr(engine_data, "ops", None):
        return lot
    return redate_lot_outputs(lot, engine_data)


def _trim_outputs(outputs: list[dict], made: dict[str, int]) -> list[dict]:
    """Outputs left after the pieces already made, first in, first out per side."""

    left = dict(made)
    remaining = []
    for output in outputs:
        side = str(output.get("op_id"))
        qty = int(output.get("qty", 0))
        used = min(qty, left.get(side, 0))
        left[side] = left.get(side, 0) - used
        if qty - used > 0:
            remaining.append({**copy.deepcopy(output), "qty": qty - used})
    return remaining


def _lot_times(lot, machine, engine_data, config, qty_by_op=None) -> tuple[float, float] | None:
    """``(prod_min, setup_min)`` of ``lot`` on ``machine`` by the source contract."""
    from backend.scheduler.resources import (
        build_setup_override_map,
        effective_oee,
        resolve_setup_hours,
    )

    ops = {op.id: op for op in getattr(engine_data, "ops", None) or []}
    overrides = build_setup_override_map(config)
    times, setups = [], []
    for op_id, _sku, qty in lot.twin_outputs or [(lot.op_id, lot.sku, lot.qty)]:
        op = ops.get(op_id)
        if op is None:
            continue
        oee = effective_oee(op, machine, config)
        times.append(qty / (op.pH * oee) * 60.0 if op.pH > 0 and oee > 0 else 0.0)
        setups.append(resolve_setup_hours(op.sku, machine, op.sH, config, overrides) * 60)
    if not times:
        return None
    return max([config.min_prod_min, *times]), max(setups, default=0.0)


def _on_machine(lot, machine, engine_data, config, alt=None):
    """A started lot whose rest moves to ``machine``: the same economic lot
    (never re-sized), timed on its new machine; its started part stays as it
    ran on the old one (history)."""
    from backend.config.types import FactoryConfig

    moved = copy.deepcopy(lot)
    moved.machine_id, moved.alt_machine_id = machine, alt
    times = _lot_times(moved, machine, engine_data, config or FactoryConfig())
    if times is not None:
        moved.prod_min, moved.setup_min = times
    return moved


def _made_part(lot, started_segments):
    """The part of a started lot already made, as a lot of its own; ``None``
    when nothing was made. Used when no allowed machine is active for its
    rest: the rest is unmet demand (owner decision, 16/10/2026)."""
    from backend.scheduler.lot_sizing import _aggregate_milestones

    made_cycles = sum(int(segment.qty) for segment in started_segments)
    made_pieces = made_cycles + sum(
        int(qty) for segment in started_segments for _op, _sku, qty in segment.twin_outputs or []
    )
    if not started_segments or made_pieces <= 0:  # a setup alone made nothing
        return None
    part = copy.deepcopy(lot)
    part.qty = made_cycles
    part.prod_min = sum(float(segment.prod_min) for segment in started_segments)
    if lot.twin_outputs:
        made = {str(op_id): 0 for op_id, _sku, _qty in lot.twin_outputs}
        for segment in started_segments:
            for op_id, _sku, qty in segment.twin_outputs or []:
                made[str(op_id)] = made.get(str(op_id), 0) + int(qty)
        part.twin_outputs = [
            (op_id, sku, made.get(str(op_id), 0)) for op_id, sku, _qty in lot.twin_outputs
        ]
    else:
        made = {str(lot.op_id): made_cycles}
    if lot.output_milestones:
        left = dict(made)
        outputs = []
        for output in lot.output_milestones:
            side = str(output.get("op_id"))
            used = min(int(output.get("qty", 0)), left.get(side, 0))
            left[side] = left.get(side, 0) - used
            if used > 0:
                outputs.append({**copy.deepcopy(output), "qty": used})
        if outputs:
            part.output_milestones = outputs
            for name, value in _aggregate_milestones(outputs).items():
                setattr(part, name, value)
    return part


def _remainder_lot(lot, started_segments, engine_data, config, machine=None, alt=None):
    """The rest of a started economic lot, as one pre-sized lot (never re-sized).

    Same identity, operation, tool and machine (a started lot never changes
    machine, rule 3, unless the lot may no longer use it: ``machine``, owner
    decision of 16/10/2026); its quantity and deliveries are what the started part
    did not make, first in, first out (the readiness rule). Durations follow
    the source contract for that quantity on that machine.

    Its lot-level dates are those of its first remaining delivery (the
    source contract checks them against the remaining deliveries), so they
    rank it neither as the complete plan ranks the lot nor each of its later
    runs by the deliveries it serves: a lot-level reordering of the residual
    keeps it where it is (``repair_preserving_protected_lots``).
    """
    from backend.config.types import FactoryConfig
    from backend.scheduler.lot_sizing import _aggregate_milestones

    config = config or FactoryConfig()
    rest = copy.deepcopy(lot)
    made_cycles = sum(int(segment.qty) for segment in started_segments)
    rest.qty = int(lot.qty) - made_cycles
    machine = machine or next(
        (s.machine_id for s in started_segments if s.prod_min > 0), lot.machine_id,
    )
    rest.machine_id, rest.alt_machine_id = machine, alt
    if lot.twin_outputs:
        made = {str(op_id): 0 for op_id, _sku, _qty in lot.twin_outputs}
        for segment in started_segments:
            for op_id, _sku, qty in segment.twin_outputs or []:
                made[str(op_id)] = made.get(str(op_id), 0) + int(qty)
        rest.twin_outputs = [
            (op_id, sku, int(qty) - made.get(str(op_id), 0))
            for op_id, sku, qty in lot.twin_outputs
        ]
    else:
        made = {str(lot.op_id): made_cycles}
    if lot.output_milestones:
        outputs = _trim_outputs(list(lot.output_milestones), made)
        for name, value in _aggregate_milestones(outputs).items():
            setattr(rest, name, value)
        rest.edd = int(rest.production_due_day)
        rest.original_edd = rest.delivery_day = int(rest.customer_delivery_day)
        rest.internal_deadline = int(rest.internal_target_day)
        demand_days = [
            int(output["customer_delivery_day"]) for output in outputs
            if not (output.get("is_economic_surplus") or output.get("is_coproduced_surplus"))
        ]
        if demand_days and lot.target_start_day is not None:
            rest.target_start_day = max(0, min(demand_days) - int(lot.start_buffer_days or 0))
    times = _lot_times(rest, machine, engine_data, config)
    if times is not None:
        rest.prod_min, rest.setup_min = times
    else:
        rest.prod_min = lot.prod_min * rest.qty / lot.qty if lot.qty else 0.0
    return rest


def _install_frozen_reservations(
    engine_data, frozen_segments, frozen_lots, freeze_day: int, config=None, partial=(),
    *, now_min: float = 0, pinned=(),
) -> dict:
    """Temporarily reserve frozen output and all future resource occupancy.

    ``partial``: ``(original, remainder)`` of started lots whose rest is
    replanned. The whole original lot is credited (lot sizing must not size
    it again) and the remainder is handed to lot sizing as a pre-sized lot.
    ``pinned`` (``ProtectedPlan.pinned``): frozen lots that have not started
    (manual anchors). Each delivery they serve is credited on its own day,
    so lot sizing sizes exactly the other lots of the complete sizing.
    Credited as stock on day 0, a lot pinned on day 57 covered the first
    deliveries of its operation instead, the residual sized a lot with its
    id for the later ones and the complete plan lost a lot (revision 156,
    15/10/2026: 43 940 pieces missing in every replan).
    ``now_min``: minutes of the planning day already gone; every machine and
    tool is blocked until then, so nothing new (production or setup) is
    placed in elapsed time (AGENTS §2 rule 4, 13/10/2026). Never persisted.
    """
    from backend.scheduler.operators import segment_operator_demand

    snapshot = {
        field: copy.deepcopy(getattr(engine_data, field))
        for field in (
            "holidays", "machine_blocked_intervals", "tool_blocked_intervals",
            "operator_blocked_intervals", "committed_supplies",
            "machine_blocked_days", "tool_blocked_days",
            "setup_crew_reservations", "plan_anchors", "protected_mounting_segments",
            "residual_lot_remainders", "history_boundary",
        )
    }
    # The residual plan is all new work: none of it is history, so it is
    # judged as a whole (a segment placed in elapsed time meets the block
    # below); the frozen history is context, never judged here.
    engine_data.history_boundary = None
    # Protected lots are spliced back unchanged; the residual problem must
    # not be asked to place them again.
    protected_ids = {lot.id for lot in frozen_lots}
    engine_data.protected_mounting_segments.extend(asdict(s) for s in frozen_segments)
    engine_data.residual_lot_remainders.extend(asdict(rest) for _lot, rest in partial)
    engine_data.plan_anchors = [
        anchor for anchor in engine_data.plan_anchors if anchor.lot_id not in protected_ids
    ]
    # Reserve elapsed capacity without changing the industrial calendar used
    # to derive material and subcontracting dates.
    elapsed = set(range(freeze_day))
    machines = {m.id for m in engine_data.machines}
    tools = {op.t for op in engine_data.ops}
    if config is not None:
        machines.update(config.machine_groups)
    for machine in machines:
        engine_data.machine_blocked_days.setdefault(machine, set()).update(elapsed)
    for tool in tools:
        engine_data.tool_blocked_days.setdefault(tool, set()).update(elapsed)
    if now_min > 0:
        elapsed_today = {
            "id": f"elapsed-today-{freeze_day}", "start_day": freeze_day, "start_min": 0,
            "end_day": freeze_day, "end_min": int(math.ceil(now_min)),
            "category": "Plano passado", "reason": "Tempo já decorrido hoje",
        }
        for machine in machines:
            engine_data.machine_blocked_intervals.setdefault(machine, []).append(
                dict(elapsed_today)
            )
        for tool in tools:
            engine_data.tool_blocked_intervals.setdefault(tool, []).append(dict(elapsed_today))
    groups = {
        machine.id: config.machine_group(machine.id) if config is not None else machine.group
        for machine in engine_data.machines
    }
    if config is not None:
        groups.update({mid: config.machine_group(mid) for mid in config.machines})
    shifts = (
        [(s.id, s.start_min, s.end_min) for s in config.shifts]
        if config is not None else [("A", 420, 930), ("B", 930, 1440)]
    )
    from backend.scheduler.setup_identity import segment_setup_identity

    # A protected continuation without setup requires its adjustment to remain
    # mounted. Inserting another tool in that gap would change the frozen lot.
    previous_by_machine = {}
    for segment in sorted(frozen_segments, key=lambda s: (s.day_idx, s.start_min, s.end_min)):
        previous = previous_by_machine.get(segment.machine_id)
        previous_by_machine[segment.machine_id] = segment
        if (previous is None or segment.day_idx < freeze_day or segment.setup_min > 0
                or segment_setup_identity(previous) != segment_setup_identity(segment)):
            continue
        start_day, start_min = max((freeze_day, 0), (previous.day_idx, previous.end_min))
        if (start_day, start_min) >= (segment.day_idx, segment.start_min):
            continue
        block = {
            "id": f"frozen-mounted-{segment.machine_id}-{segment.day_idx}-{segment.start_min}",
            "start_day": start_day, "start_min": int(start_min),
            "end_day": segment.day_idx, "end_min": int(segment.start_min),
            "category": "Plano passado", "reason": "Continuação sem reinstalação",
            "lot_id": segment.lot_id, "tool_id": segment.tool_id,
        }
        for day in range(start_day, segment.day_idx + 1):
            daily = {**block, "start_day": day, "end_day": day,
                     "start_min": int(start_min) if day == start_day else 0,
                     "end_min": int(segment.start_min) if day == segment.day_idx else 1440}
            if daily["end_min"] > daily["start_min"]:
                engine_data.machine_blocked_intervals.setdefault(segment.machine_id, []).append(
                    copy.deepcopy(daily)
                )
                engine_data.tool_blocked_intervals.setdefault(segment.tool_id, []).append(
                    copy.deepcopy(daily)
                )
    for index, segment in enumerate(frozen_segments):
        if segment.day_idx < freeze_day or segment.end_min <= segment.start_min:
            continue
        block = {
            "id": f"frozen-prefix-{index}",
            "start_day": int(segment.day_idx), "start_min": int(segment.start_min),
            "end_day": int(segment.day_idx), "end_min": int(segment.end_min),
            "category": "Plano passado",
            "reason": "Lote iniciado antes do dia atual",
            # Which lot holds the reservation: a refusal can then name it
            # (e.g. a lot pinned by hand), plans.refusal.
            "lot_id": segment.lot_id,
        }
        engine_data.machine_blocked_intervals.setdefault(segment.machine_id, []).append(
            copy.deepcopy(block)
        )
        engine_data.tool_blocked_intervals.setdefault(segment.tool_id, []).append(
            copy.deepcopy(block)
        )
        setup_end = min(segment.end_min, segment.start_min + segment.setup_min)
        # Today the crew is reserved only from now on: an elapsed setup blocks
        # nothing new (every machine is blocked until now) and, after a
        # regrouping, could only collide with another elapsed one.
        setup_start = (
            max(int(segment.start_min), int(math.ceil(now_min)))
            if segment.day_idx == freeze_day else int(segment.start_min)
        )
        if segment.setup_min > 0 and setup_end > setup_start:
            engine_data.setup_crew_reservations.append({
                **block, "machine_id": segment.machine_id, "tool_id": segment.tool_id,
                "group": groups.get(segment.machine_id, "Grandes"),
                "start_min": setup_start, "end_min": setup_end,
            })
        if segment.prod_min <= 0:
            continue
        production_start = segment.production_start_min
        for shift_id, shift_start, shift_end in shifts:
            start = max(production_start, shift_start)
            end = min(int(segment.end_min), shift_end)
            if start < end:
                engine_data.operator_blocked_intervals.append({
                    **block,
                    "id": f"frozen-operator-{index}-{shift_id}",
                    "group": groups.get(segment.machine_id, "Grandes"),
                    "shift": shift_id,
                    "start_min": start, "end_min": end,
                    "count": segment_operator_demand(segment, engine_data),
                })

    first_by_lot = {}
    for segment in sorted(
        frozen_segments, key=lambda item: (item.day_idx, item.start_min, item.end_min),
    ):
        first_by_lot.setdefault(segment.lot_id, segment)
    available_at = (
        f"{str(engine_data.workdays[0])[:10]}T00:00:00" if engine_data.workdays else ""
    )
    originals = {original.id for original, _rest in partial}
    for lot in [*frozen_lots, *(original for original, _rest in partial)]:
        segment = first_by_lot.get(lot.id)
        if segment is None and lot.id not in originals:
            continue
        # A started lot with nothing frozen (released at "now") is credited
        # on its own machine and tool: its rest is the whole lot.
        machine_id = segment.machine_id if segment is not None else lot.machine_id
        tool_id = segment.tool_id if segment is not None else lot.tool_id
        if lot.id in pinned and lot.output_milestones:
            for output in lot.output_milestones:
                day = max(0, int(output.get("customer_delivery_day") or 0))
                engine_data.committed_supplies.append(CommittedSupply(
                    op_id=str(output.get("op_id")), sku=str(output.get("sku") or lot.sku),
                    qty=int(output.get("qty", 0)),
                    available_at=(
                        f"{str(engine_data.workdays[day])[:10]}T00:00:00"
                        if day < len(engine_data.workdays or []) else ""
                    ),
                    available_day=day, machine_id=machine_id, tool_id=tool_id,
                ))
            continue
        for op_id, sku, qty in lot.twin_outputs or [(lot.op_id, lot.sku, lot.qty)]:
            engine_data.committed_supplies.append(CommittedSupply(
                op_id=str(op_id), sku=str(sku), qty=int(qty),
                available_at=available_at, available_day=0,
                machine_id=machine_id, tool_id=tool_id,
            ))
    return snapshot


def _restore_frozen_reservations(engine_data, snapshot: dict) -> None:
    for field, value in snapshot.items():
        setattr(engine_data, field, value)


def _with_lot_metadata(segment, lot):
    """A copy of ``segment`` carrying ``lot``'s own metadata, as the builder writes it."""
    from backend.scheduler.quantity_dispatch import _LOT_FIELDS

    segment = copy.copy(segment)
    segment.lot_qty = lot.qty
    segment.output_milestones = copy.deepcopy(lot.output_milestones)
    for name in _LOT_FIELDS:
        setattr(segment, name, getattr(lot, name))
    return segment


def _splice_frozen_started_lots(result, frozen_segments, frozen_lots, partial=(), pinned=()):
    """Join the residual plan with the frozen work into the complete plan.

    A partial lot's residual segments rejoin its original lot: the remainder
    record is replaced by the original economic lot and the segments carry
    the lot's own metadata, as the builder writes it. ``pinned`` lots
    (``ProtectedPlan.pinned``) have not started: they carry no preservation
    proof, so the plan is judged with them against the current sizing.
    """
    from backend.scheduler.canonical import preserved_lot_proofs

    frozen_ids = {lot.id for lot in frozen_lots}
    originals = {original.id: original for original, _rest in partial}
    if not frozen_ids and not originals:
        return result
    # Run identifiers are deterministic within one optimizer execution. A
    # residual plan can therefore reuse an identifier already present in the
    # historical prefix for a later, independent campaign. Keep those
    # campaigns distinct before joining them; otherwise setup validation
    # associates the future production with the historical setup.
    frozen_run_ids = {segment.run_id for segment in frozen_segments}
    residual_run_ids = {
        segment.run_id
        for segment in result.segments
        if segment.lot_id not in frozen_ids
    }
    used_run_ids = frozen_run_ids | residual_run_ids
    replacements: dict[str, str] = {}
    for run_id in sorted(frozen_run_ids & residual_run_ids):
        suffix = 1
        candidate = f"{run_id}__replanned_{suffix}"
        while candidate in used_run_ids:
            suffix += 1
            candidate = f"{run_id}__replanned_{suffix}"
        replacements[run_id] = candidate
        used_run_ids.add(candidate)
    if replacements:
        for segment in result.segments:
            if segment.lot_id not in frozen_ids and segment.run_id in replacements:
                segment.run_id = replacements[segment.run_id]
    def rejoined(segment):
        original = originals.get(segment.lot_id)
        return segment if original is None else _with_lot_metadata(segment, original)

    result.segments = [rejoined(s) for s in result.segments if s.lot_id not in frozen_ids]
    # The started part of a partial lot carries the same lot metadata as its
    # rest (its deliveries dated by the current calendar); physically it is
    # the frozen segment unchanged.
    result.segments.extend(rejoined(s) for s in copy.deepcopy(frozen_segments))
    result.segments.sort(key=lambda s: (
        s.day_idx, s.start_min, s.machine_id, s.tool_id, s.lot_id,
    ))
    result.lots = [
        copy.deepcopy(originals[lot.id]) if lot.id in originals else lot
        for lot in result.lots if lot.id not in frozen_ids
    ]
    result.lots.extend(copy.deepcopy(frozen_lots))
    proven = frozen_ids - set(pinned)
    result.preserved_lot_proofs = preserved_lot_proofs(
        [s for s in frozen_segments if s.lot_id in proven],
        [lot for lot in frozen_lots if lot.id in proven],
    )
    return result


def _residual_of(result, protected: ProtectedPlan):
    """The residual part of a complete plan: what a replan may still move."""
    from backend.scheduler.improvement import _segment_physical_row

    whole = {lot.id for lot in protected.lots}
    rests = {rest.id: rest for _original, rest in protected.partial}
    frozen_rows = Counter(
        _segment_physical_row(s) for s in protected.segments if s.lot_id in rests
    )
    # A segment cut by a new input goes on in the residual from its stop.
    cut_rows: dict[tuple, list] = {}
    for original, rest in protected.cut:
        cut_rows.setdefault(_segment_physical_row(original), []).append(rest)
    segments = []
    for segment in result.segments:
        if segment.lot_id in whole:
            continue
        row = _segment_physical_row(segment) if segment.lot_id in rests else None
        if row is not None and frozen_rows[row] > 0:
            frozen_rows[row] -= 1
            continue
        if row is not None and cut_rows.get(row):
            segments.append(copy.deepcopy(cut_rows[row].pop()))
            continue
        segments.append(segment)
    lots = [rests.get(lot.id, lot) for lot in result.lots if lot.id not in whole]
    return segments, lots


def _recalculation_context(
    engine_data, config, baseline_result, recalculate_from_start, now: datetime | None = None,
):
    """``(data, baseline, planning day, now)`` of a calculation.

    «Recalcular plano» plans from D0 (§5): its planning day is 0 and its
    "now" is 00:00 of D0, so nothing of today counts as elapsed either.

    The plan's history boundary (``scheduler.history``) is
    ``planning_boundary(freeze_day, elapsed minutes at now)``: none for
    «Recalcular plano».
    """
    now = calculation_now(config, now)
    if not recalculate_from_start:
        return (
            engine_data, baseline_result, _current_planning_day(engine_data, config, now), now,
        )
    # Date-derived proofs belong to the old protected plan, not to observed
    # execution. Clear them only on detached inputs; keep anchors/observations.
    data, baseline = copy.deepcopy((engine_data, baseline_result))
    data.preserved_lot_proofs = {}
    baseline.preserved_lot_proofs = {}
    baseline.warnings = [
        warning for warning in baseline.warnings
        if not warning.startswith("Plano anterior preservado:")
    ]
    return data, baseline, 0, _horizon_start(data, config, now)


def compact_preserving_started_lots(
    engine_data, config, baseline_result, *, recalculate_from_start=False,
    now: datetime | None = None,
):
    """Recompact a valid active plan after capacity is released.

    ``now``: the calculation's instant (``calculation_now``). Manual anchors
    the current inputs no longer allow are released first, with a notice
    (``reconcile_manual_anchors``, decisão de 15/10/2026).
    """
    from backend.planning_control import planning_scope

    notices = reconcile_manual_anchors(engine_data, config, baseline_result, now=now)
    with planning_scope(timeout_s=60.0):
        result = _compact_preserving_started_lots(
            engine_data, config, baseline_result, recalculate_from_start=recalculate_from_start,
            now=now,
        )
    return with_released_anchor_notices(result, notices)


def _compact_preserving_started_lots(
    engine_data, config, baseline_result, *, recalculate_from_start=False, now=None,
):
    from backend.planning_control import improvement_time_budget
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.operators import compute_operator_alerts
    from backend.scheduler.scoring import compute_score
    from backend.scheduler.validation import assert_plan_valid

    started_at = time.perf_counter()
    engine_data, baseline_result, freeze_day, now = _recalculation_context(
        engine_data, config, baseline_result, recalculate_from_start, now,
    )
    # Every validation of this plan reads its history boundary (rule 4).
    boundary = planning_boundary(
        freeze_day, elapsed_on_planning_day(freeze_day, engine_data, config, now),
    )
    result = copy.deepcopy(with_current_material(baseline_result, engine_data, config, boundary))
    result.history_boundary = boundary
    protected = _protected_plan(result, freeze_day, engine_data, config, now=now)
    result, improvement = improve_preserving_protected_lots(
        result, engine_data, copy.deepcopy(engine_data), config,
        protected.segments, protected.lots, freeze_day,
        time_budget_s=improvement_time_budget(60.0), partial=protected.partial, now=now,
        cut=protected.cut, pinned=protected.pinned,
    )
    result.improvement_report = improvement
    engine_data = result_validation_data(engine_data, result)
    result.score = compute_score(
        result.segments,
        result.lots,
        engine_data,
        config=config,
    )
    result.operator_alerts = compute_operator_alerts(
        result.segments,
        engine_data,
        config=config,
    )
    assert_plan_valid(result.segments, engine_data, config, lots=result.lots)
    result.time_ms = round((time.perf_counter() - started_at) * 1000, 1)
    result.warnings = [
        *without_calculation_notes(_without_protection_warnings(result.warnings)),
        "Capacidade libertada: o plano ativo foi novamente compactado.",
    ]
    result.warnings.extend(_protection_warnings(protected, freeze_day))
    return result


# Notes on how one calculation was made (complete rebuild, quick adjustment,
# compaction, fallbacks of a replan job). A later calculation that keeps or
# compacts that plan writes its own; it never inherits these.
CALCULATION_NOTE_PREFIXES = (
    "A alteração afeta ",
    "A alteração apenas liberta capacidade",
    "O ajuste rápido não terminou",
    "Calendário aplicado com um ajuste rápido",
    "Troca entre turnos validada",
    "Capacidade libertada:",
    "O recálculo completo não terminou",
    "Foi mantido o melhor plano de base",
    "O plano ativo deixou de ser uma referência válida",
    "Tempo de melhoria esgotado",
    # Pins released by that calculation (``reconcile_manual_anchors``): true
    # of the write that released them, never inherited by a later one.
    RELEASED_ANCHOR_PREFIX,
    # Operations without an allowed active machine: stated again by each
    # calculation that still has them (``config.planning``).
    NO_ACTIVE_MACHINE_PREFIX,
)


def without_calculation_notes(warnings) -> list[str]:
    """Drop the notes of an earlier calculation (``CALCULATION_NOTE_PREFIXES``)."""

    return [
        warning for warning in warnings or []
        if not str(warning).startswith(CALCULATION_NOTE_PREFIXES)
    ]


def _without_protection_warnings(warnings) -> list[str]:
    """Drop protection notes of an earlier calculation (they are restated)."""

    return [
        warning for warning in warnings
        if not warning.startswith(("Plano anterior preservado:", "Posições manuais preservadas:"))
    ]


def _protection_warnings(protected: ProtectedPlan, freeze_day: int) -> list[str]:
    warnings = []
    if protected.started:
        warnings.append(
            preserved_lots_warning(len(protected.started), freeze_day, protected.now_label)
        )
    if protected.anchored:
        warnings.append(_anchor_warning(protected.anchored))
    return warnings


def _anchor_warning(anchored: set[str]) -> str:
    return (
        f"Posições manuais preservadas: {len(anchored)} lote(s) ancorado(s) "
        "mantido(s) sem alterações."
    )


def improve_preserving_protected_lots(
    result, engine_data, original_data, config, protected_segments, protected_lots,
    freeze_day: int, *, time_budget_s: float, partial=(), now: datetime | None = None,
    cut=(), pinned=(),
):
    """Run the no-loss improvement cycle on the residual plan only.

    ``now``: the calculation's instant; nothing moves into today's elapsed
    minutes (``_install_frozen_reservations``). ``cut``: the protection's
    cut segments, so the residual starts from their rest, not the uncut row.
    ``pinned``: protected lots that have not started (``ProtectedPlan.pinned``).

    Frozen work (``protected_segments``: whole protected lots and the started
    part of ``partial`` lots) stays reserved exactly as in the complete
    candidate; the rest of a partial lot is residual work. The improved
    residual is spliced back and the merged plan is re-validated on the
    original inputs; on any failure the complete candidate is kept unchanged.
    Returns ``(result, report)``.
    """
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.gates import build_gate_report
    from backend.scheduler.improvement import improve_plan
    from backend.scheduler.operators import compute_operator_alerts
    from backend.scheduler.scoring import compute_score
    from backend.scheduler.validation import validate_plan

    frozen_run_ids = {segment.run_id for segment in protected_segments}

    def evaluation_plan(segments, lots):
        # Consumers read the complete plan exactly as they read an unprotected
        # candidate (never mutating it), so no deep copy is needed (B4.3).
        # Nothing protected: the residual already is the complete plan.
        if not protected_lots and not partial:
            return segments, lots, result_validation_data(original_data, result)
        # The splice only rewrites ``run_id`` of residual segments whose run
        # id collides with a protected run: copy just those, so the
        # candidate itself is never changed.
        complete = copy.copy(result)
        complete.segments = [
            copy.copy(segment) if segment.run_id in frozen_run_ids else segment
            for segment in segments
        ]
        complete.lots = list(lots)
        complete = _splice_frozen_started_lots(
            complete, protected_segments, protected_lots, partial, pinned,
        )
        return complete.segments, complete.lots, result_validation_data(original_data, complete)

    residual_segments, residual_lots = _residual_of(
        result, ProtectedPlan(
            list(protected_segments), list(protected_lots), list(partial), cut=list(cut),
        ),
    )
    snapshot = _install_frozen_reservations(
        engine_data, protected_segments, protected_lots, freeze_day, config, partial,
        now_min=elapsed_on_planning_day(
            freeze_day, engine_data, config, calculation_now(config, now),
        ),
        pinned=pinned,
    )
    try:
        segments, lots, report = improve_plan(
            residual_segments, residual_lots, engine_data, config,
            time_budget_s=time_budget_s, evaluation_plan=evaluation_plan,
        )
    finally:
        _restore_frozen_reservations(engine_data, snapshot)
    if not report.get("moves_accepted"):
        return result, report

    def reject_merged(reason):
        from backend.scheduler.improvement import physical_signature

        return result, {
            **report, "status": "partial", "stop_reason": reason,
            "rolled_back_moves": int(report.get("rolled_back_moves", 0)) + report["moves_accepted"],
            "moves_accepted": 0, "accepted_by_scope": {},
            "proposal_log": {key: entry for key, entry in report.get("proposal_log", {}).items()
                             if entry.get("outcome") != "accepted"},
            "final": report.get("reference"),
            "final_signature": physical_signature(result.segments, result.lots),
        }

    improved = copy.copy(result)
    improved.segments, improved.lots = segments, lots
    if protected_lots or partial:
        improved = _splice_frozen_started_lots(
            improved, protected_segments, protected_lots, partial, pinned,
        )
    view = result_validation_data(original_data, improved)
    if validate_plan(improved.segments, view, config, lots=improved.lots):
        return reject_merged("merged_validation_failed")
    from backend.scheduler.improvement import contract_verdict

    if not contract_verdict(
        improved.segments, result.segments, view,
        candidate_lots=improved.lots, reference_lots=result.lots,
    ).admissible:
        return reject_merged("merged_contract_failed")
    improved.score = compute_score(improved.segments, improved.lots, view, config=config)
    improved.operator_alerts = compute_operator_alerts(improved.segments, view, config=config)
    improved.gate_report = build_gate_report(
        improved.segments, improved.lots, improved.score, view, config,
    )
    if not (improved.gate_report.get("physical_gate_passed")
            and improved.gate_report.get("coverage_gate_passed")):
        return reject_merged("merged_gate_failed")
    return improved, report


def repair_preserving_protected_lots(
    baseline_result, engine_data, config, freeze_day: int, repair, *, now: datetime | None = None,
):
    """Run a repair on the movable part of a plan only (AGENTS §2 rule 4, §5).

    ``repair(segments, lots, started_rests) -> (segments, lots)`` receives a
    copy of the residual plan (``_residual_of``) while the protected work of
    ``_protected_plan`` (production started before ``freeze_day``, the run
    mounted at that boundary, its mount suppliers, honoured anchors) is
    reserved in ``engine_data``, exactly as the improvement cycle sees it. The
    protected work is spliced back unchanged and the rest of a started lot
    rejoins its lot, never re-sized. Reservations are always removed. Returns
    the complete repaired plan (a new result; ``baseline_result`` is not
    changed); the caller validates it.

    ``started_rests`` holds the ids of the started lots whose rest is in the
    residual. A lot-level reordering (the canonical normalisation) must keep
    them where they are, as the improvement cycle's compaction keeps them
    (``improvement.default_generators``, ``earliest_legal``): a rest's
    lot-level dates are those of its first remaining delivery
    (``_remainder_lot``), which rank neither the lot as the complete plan
    ranks it nor its later runs by the deliveries they serve. Ranked by them,
    the rest of a twin lot due on day 3 became due on day 12 and its run on
    day 40 (deliveries due on day 46) went behind a run due on day 47 of a
    lot due on day 11 (revision 124, small PRM031 outage). A hard-constraint
    repair still moves a rest the change invalidates.

    ``now``: the calculation's instant; today's minutes before it are
    reserved, so the repair never places work in elapsed time.
    """
    now = calculation_now(config, now)
    now_min = elapsed_on_planning_day(freeze_day, engine_data, config, now)
    baseline_result = with_current_material(
        baseline_result, engine_data, config, planning_boundary(freeze_day, now_min),
    )
    protected = _protected_plan(baseline_result, freeze_day, engine_data, config, now=now)
    repaired = copy.deepcopy(baseline_result)
    if not protected and not now_min:
        repaired.segments, repaired.lots = repair(repaired.segments, repaired.lots, set())
        repaired.history_boundary = planning_boundary(freeze_day, now_min)
        return repaired
    segments, lots = _residual_of(repaired, protected)
    started_rests = {rest.id for _original, rest in protected.partial}
    snapshot = _install_frozen_reservations(
        engine_data, protected.segments, protected.lots, freeze_day, config, protected.partial,
        now_min=now_min, pinned=protected.pinned,
    )
    try:
        segments, lots = repair(copy.deepcopy(segments), copy.deepcopy(lots), started_rests)
    finally:
        _restore_frozen_reservations(engine_data, snapshot)
    repaired.segments, repaired.lots = segments, lots
    repaired.history_boundary = planning_boundary(freeze_day, now_min)
    return _splice_frozen_started_lots(
        repaired, protected.segments, protected.lots, protected.partial, protected.pinned,
    )


def candidate_history_changes(
    baseline_snapshot: dict | None, result, engine_data, config, *, freeze_day: int,
    now: datetime | None = None,
):
    """Started lots a candidate would change: the commit guard, applied early.

    The same rule as ``plans.store`` at commit (``historical_schedule_changes``)
    against the active plan the calculation started from, read on the
    calculation's own planning day (``freeze_day``, the day the commit sees
    as today) and instant (``now``: today's segments before it are history),
    so a candidate the commit would refuse is never offered. Nothing is
    history when the calculation protects no prefix.
    """
    workdays = list(getattr(engine_data, "workdays", None) or [])
    if not baseline_snapshot or not 0 <= freeze_day < len(workdays):
        return []
    if freeze_day == 0 and (
        now is None or not elapsed_on_planning_day(0, engine_data, config, now)
    ):
        return []
    candidate = {
        "dataset_info": baseline_snapshot.get("dataset_info"),
        "engine_data": {
            "workdays": [str(day) for day in engine_data.workdays or []],
            # The records of what ran it keeps (``_declared_today``).
            "plan_anchors": [
                asdict(anchor) for anchor in getattr(engine_data, "plan_anchors", None) or []
            ],
        },
        "config": {"timezone": str(getattr(config, "timezone", "Europe/Lisbon"))},
        "segments": [asdict(segment) for segment in result.segments],
        "lots": [asdict(lot) for lot in result.lots],
    }
    return historical_schedule_changes(
        baseline_snapshot, candidate, today=str(workdays[freeze_day])[:10], now=now,
        engine_data=engine_data, config=config,
    )


def _safety_net_reason(violations, lot_id: str) -> str:
    """Why the safety net released a pin: the first conflict naming its lot."""
    for violation in violations or []:
        if not isinstance(violation, dict):
            continue
        named = {
            str(item.get("lot_id")) for item in (
                violation, violation.get("other"), violation.get("unavailability"),
            ) if isinstance(item, dict) and item.get("lot_id")
        }
        message = str(violation.get("message") or "").strip().rstrip(".")
        if lot_id in named and message and "LOT_" not in message:
            return (
                "com a alteração nova o plano deixou de ter solução com o lote nesse "
                f"sítio ({message[:1].lower() + message[1:]})"
            )
    return "com a alteração nova o plano deixou de ter solução com o lote nesse sítio"


def optimize_preserving_started_lots(
    engine_data, config, baseline_result, *, mode="normal", audit=False, cancel_event=None,
    optimizer=None, recalculate_from_start=False, now: datetime | None = None,
):
    """Optimize a detached input, preserving the production that has started.

    Only what started is frozen (AGENTS §2, rule 4, ``_protected_plan``); the
    rest of a started lot is replanned as the same, pre-sized lot.
    Temporary reservations are always removed. The optimizer and final merged
    validation share one budget and propagate PlanningCancelled/PlanningTimeout.
    ``now``: the calculation's instant (``calculation_now``); nothing new is
    placed in today's minutes before it.

    Manual anchors (decisão do Luís, 15/10/2026): the ones the current inputs
    no longer allow are released first (``reconcile_manual_anchors``). If no
    complete candidate is valid and the conflicts involve pinned lots (or
    name no lot at all, then every pin), those pins are released and the
    calculation runs once more; a second failure is refused as before, with
    its conflicts. Every released pin is named in the plan warnings
    (``RELEASED_ANCHOR_PREFIX``). ``engine_data`` is the write's staging data:
    its ``plan_anchors`` lose the released pins.
    """
    from backend.plans.refusal import causes_for_log
    from backend.scheduler.validation import PlanValidationError

    notices = reconcile_manual_anchors(engine_data, config, baseline_result, now=now)
    options = dict(
        mode=mode, audit=audit, cancel_event=cancel_event, optimizer=optimizer,
        recalculate_from_start=recalculate_from_start, now=now,
    )
    try:
        result = _optimize_preserving_started_lots(
            engine_data, config, baseline_result, **options,
        )
    except PlanValidationError as error:
        involved = anchors_in_violations(
            error.violations, engine_data, getattr(baseline_result, "segments", None),
        )
        if not recalculate_from_start:
            from backend.plans.manual_edits import executed_lot_ids

            # A record of what ran is history during the day, never released.
            involved -= executed_lot_ids(engine_data)
        if not involved:
            raise
        lots = list(getattr(baseline_result, "lots", None) or [])
        logger.info(
            "Sem plano válido com %d fixação(ões) manual(is); solto-as e recalculo uma vez: %s",
            len(involved), causes_for_log(error, engine_data, lots),
        )
        notices.extend(release_anchors(engine_data, lots, {
            lot_id: _safety_net_reason(error.violations, lot_id) for lot_id in sorted(involved)
        }))
        result = _optimize_preserving_started_lots(
            engine_data, config, baseline_result, **options,
        )
    return with_released_anchor_notices(result, notices)


def _optimize_preserving_started_lots(
    engine_data, config, baseline_result, *, mode="normal", audit=False, cancel_event=None,
    optimizer=None, recalculate_from_start=False, now: datetime | None = None,
):
    from backend.cpo import optimize
    from backend.cpo.optimizer import (
        MODE_CONFIG,
        _strip_score_policy,
    )
    from backend.planning_control import (
        PlanningTimeout,
        candidate_observer,
        closing_reserve,
        improvement_time_budget,
        planning_checkpoint,
        planning_scope,
        remaining_time,
    )
    from backend.plans.refusal import causes_for_log
    from backend.plans.serialize import schedule_fingerprint
    from backend.scheduler.canonical import result_validation_data, stored_history_boundary
    from backend.scheduler.gates import build_gate_report
    from backend.scheduler.operators import compute_operator_alerts
    from backend.scheduler.scoring import compute_score
    from backend.scheduler.validation import PlanValidationError, assert_plan_valid

    if mode not in MODE_CONFIG:
        raise ValueError(f"Unknown mode: {mode}. Use: {list(MODE_CONFIG)}")
    with planning_scope(
        timeout_s=float(MODE_CONFIG[mode].get("time_budget_s", 60.0)),
        cancel_event=cancel_event,
    ):
        engine_data, baseline_result, freeze_day, now = _recalculation_context(
            engine_data, config, baseline_result, recalculate_from_start, now,
        )
        # Every validation of the plan reads its history boundary (rule 4).
        boundary = planning_boundary(
            freeze_day, elapsed_on_planning_day(freeze_day, engine_data, config, now),
        )
        baseline_result = with_current_material(baseline_result, engine_data, config, boundary)
        protected = _protected_plan(baseline_result, freeze_day, engine_data, config, now=now)
        segments, lots, partial = protected.segments, protected.lots, protected.partial
        pinned = protected.pinned
        original_data = copy.deepcopy(engine_data)
        complete = None
        complete_fingerprint = None
        # Conflicts of the first complete candidate the validation rejected:
        # the refusal when no candidate is valid.
        rejected: list[dict] = []

        def retain(candidate):
            nonlocal complete, complete_fingerprint
            fingerprint = schedule_fingerprint(candidate.segments, candidate.lots)
            if fingerprint == complete_fingerprint:
                for field in ("solver_status", "feasibility", "time_ms", "journal"):
                    setattr(complete, field, copy.deepcopy(getattr(candidate, field)))
                complete.warnings = list(dict.fromkeys([*complete.warnings, *candidate.warnings]))
                if not protected:
                    complete.score = copy.deepcopy(candidate.score)
                if "solver_trace" in (candidate.gate_report or {}):
                    complete.gate_report["solver_trace"] = copy.deepcopy(
                        candidate.gate_report["solver_trace"],
                    )
                return
            merged = copy.deepcopy(candidate)
            merged.history_boundary = list(boundary)
            if recalculate_from_start:
                merged.preserved_lot_proofs = {}
            if protected:
                merged = _splice_frozen_started_lots(merged, segments, lots, partial, pinned)
                view = result_validation_data(original_data, merged)
                merged.score = compute_score(merged.segments, merged.lots, view, config=config)
                merged.operator_alerts = compute_operator_alerts(
                    merged.segments, view, config=config
                )
                for warning in _protection_warnings(protected, freeze_day):
                    if warning not in merged.warnings:
                        merged.warnings.append(warning)
            else:
                view = copy.copy(original_data)
                view.history_boundary = stored_history_boundary(boundary)
            try:
                assert_plan_valid(merged.segments, view, config, lots=merged.lots)
            except PlanValidationError as error:
                # Rejected like a candidate that fails the gate below: the
                # optimizer goes on with the next ones (15/10/2026: the first
                # invalid candidate used to abort the whole calculation).
                logger.info(
                    "Candidato completo rejeitado pela validação: %s",
                    causes_for_log(error, view, merged.lots),
                )
                if not rejected:
                    rejected.extend(error.violations)
                return
            merged.gate_report = build_gate_report(
                merged.segments, merged.lots, merged.score, view, config,
            )
            if not (merged.gate_report.get("physical_gate_passed")
                    and merged.gate_report.get("coverage_gate_passed")):
                return
            planning_checkpoint()
            complete, complete_fingerprint = merged, fingerprint

        snapshot = _install_frozen_reservations(
            engine_data, segments, lots, freeze_day, config, partial,
            now_min=elapsed_on_planning_day(freeze_day, engine_data, config, now),
            pinned=pinned,
        )
        try:
            planning_checkpoint()
            remaining = remaining_time()
            reserve = closing_reserve(float(MODE_CONFIG[mode].get("time_budget_s", 60.0)))
            with candidate_observer(retain):
                try:
                    # The improvement cycle runs once below, on the residual
                    # plan with protected lots reserved; defer it here.
                    defer = {"improve": False} if optimizer in (None, optimize) else {}
                    if defer and mode != "quick":
                        defer["reserve_improvement"] = True
                    with planning_scope(timeout_s=max(0.0, remaining - reserve)):
                        result = (optimizer or optimize)(
                            engine_data,
                            mode=mode,
                            audit=audit,
                            config=config,
                            cancel_event=cancel_event,
                            **defer,
                        )
                    retain(result)
                except PlanningTimeout:
                    planning_checkpoint()
                    if complete is None:
                        if rejected:
                            raise PlanValidationError(list(rejected)) from None
                        raise
                    complete.warnings.append(
                        "Tempo de melhoria esgotado; conservado o candidato completo validado."
                    )
        finally:
            _restore_frozen_reservations(engine_data, snapshot)
        planning_checkpoint()
        if complete is None:
            if rejected:
                # Refused as before, with the conflicts of a rejected candidate.
                raise PlanValidationError(list(rejected))
            raise NoValidCandidateError(
                "O cálculo não produziu um candidato completo fisicamente válido."
            )
        result = complete
        solver_trace = copy.deepcopy((result.gate_report or {}).get("solver_trace"))
        # Improvement phase (plan §5): only on a complete validated candidate,
        # inside the same deadline, keeping a closing margin.
        budget = improvement_time_budget(float(MODE_CONFIG[mode]["time_budget_s"]))
        if mode == "quick":
            budget = min(10.0, budget)
        verified = dict(getattr(result, "improvement_report", None) or {})
        if budget > 0:
            result, report = improve_preserving_protected_lots(
                result, engine_data, original_data, config, segments, lots, freeze_day,
                time_budget_s=budget, partial=partial, now=now, pinned=pinned,
            )
        else:
            report = {"status": "not_evaluated", "stop_reason": "no_time_left"}
        # Search verifications of the pre-improvement state no longer apply
        # to a changed plan; keep them only when nothing was accepted.
        result.improvement_report = {
            **({"verified": verified["verified"]}
               if verified.get("verified") and not report.get("moves_accepted") else {}),
            **report,
        }
        planning_checkpoint()
        engine_data = result_validation_data(engine_data, result)
        result.gate_report = build_gate_report(
            result.segments, result.lots, result.score, engine_data, config,
        )
        if result.solver_status is not None:
            result.gate_report["solver_status"] = result.solver_status
        result.gate_report["feasibility"] = result.feasibility
        if solver_trace is not None:
            result.gate_report["solver_trace"] = solver_trace
        from backend.scheduler.improvement import improvement_gate_summary

        # Informational: explains the merged plan (history included) and
        # never changes the apply decision.
        result.gate_report["improvement"] = improvement_gate_summary(
            result.improvement_report, result.segments, result.lots, engine_data, config,
        )
        _strip_score_policy(result)
        planning_checkpoint()
        return result
