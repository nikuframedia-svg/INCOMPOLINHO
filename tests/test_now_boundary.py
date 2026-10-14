"""The protection boundary is the current factory minute (AGENTS §2 rule 4, 13/10/2026).

A replan during the day keeps today's production that started before "now"
exactly where it is (one running at "now" whole), never places new
production or a setup in the minutes already gone, and the commit guard
reads today's history at the calculation's own instant. «Recalcular plano»
keeps planning from D0 (§5, decision of 06/10/2026).
"""

from __future__ import annotations

import copy
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend import calendar as factory_calendar
from backend.api.data import stored_plan_needs_rebuild
from backend.config.types import FactoryConfig, MachineConfig
from backend.plans import frozen
from backend.scheduler.canonical import result_validation_data
from backend.scheduler.improvement import _segment_physical_row
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.types import ScheduleResult, Segment
from backend.scheduler.validation import assert_plan_valid
from backend.types import EngineData, EOp, MachineInfo
from tests.snapshot_fixture import load_payload

START = date(2026, 3, 2)  # a Monday; day 1 is "today" in these tests
LISBON = ZoneInfo("Europe/Lisbon")


def _at(day: int, minute: int) -> datetime:
    when = START + timedelta(days=day)
    return datetime(when.year, when.month, when.day, minute // 60, minute % 60, tzinfo=LISBON)


def _config() -> FactoryConfig:
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    config.tools = {
        "T1": {"primary": "M1", "setup_hours": 0.5},
        "T2": {"primary": "M1", "setup_hours": 0.5},
    }
    return config


def _op(op_id: str, tool: str, due_day: int, days: list[str]) -> EOp:
    demand = [0] * len(days)
    demand[due_day] = 200
    return EOp(
        id=op_id, sku=f"SKU_{op_id}", client="C", designation="Peça", m="M1", t=tool,
        pH=100, sH=0.5, operators=1, eco_lot=200, alt=None, stk=0, backlog=0, d=demand,
        oee=1.0, wip=0,
    )


def _data(*, second_due: int | None = None) -> EngineData:
    days = [(START + timedelta(days=i)).isoformat() for i in range(14)]
    ops = [_op("OP1", "T1", 4, days)]
    if second_due is not None:
        ops.append(_op("OP2", "T2", second_due, days))
    return EngineData(
        ops=ops, machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[],
        client_demands={}, workdays=days, n_days=len(days),
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )


def _segment(lot, day, start, qty, setup):
    prod = lot.prod_min * qty / lot.qty
    return Segment(
        lot.id, f"quantity:{lot.id}:0", "M1", lot.tool_id, day, start,
        start + int(setup + prod), "A" if start < 930 else "B", qty, prod, setup,
        sku=lot.sku, lot_qty=lot.qty, output_milestones=copy.deepcopy(lot.output_milestones),
    )


def _plan(data, config, blocks_by_op):
    """``blocks_by_op``: op id -> [(day, start, qty, setup)], one run per lot."""
    lots = {lot.op_id: lot for lot in create_lots(data, config)}
    segments = [
        _segment(lots[op_id], day, start, qty, setup)
        for op_id, blocks in blocks_by_op.items()
        for day, start, qty, setup in blocks
    ]
    return ScheduleResult(
        segments=segments, lots=list(lots.values()), score={}, time_ms=0, warnings=[],
        operator_alerts=[],
    ), lots


def _rows(segments):
    return {_segment_physical_row(segment) for segment in segments}


def _assert_boundary(result, baseline, now_min, day=1):
    """Started rows kept; nothing else on ``day`` starts before ``now_min``."""
    started = [
        s for s in baseline.segments
        if frozen.started_before(s, day, now_min)
    ]
    assert _rows(started) <= _rows(result.segments)
    kept = _rows(started)
    assert not [
        s for s in result.segments
        if s.day_idx == day and s.start_min < now_min and s.end_min > s.start_min
        and _segment_physical_row(s) not in kept
    ]
    assert not [s for s in result.segments if s.day_idx < day and _segment_physical_row(s)
                not in _rows(baseline.segments)]


# Started at 07:00 today (day 1), the rest on day 3 after free shift time.
MORNING = {"OP1": [(1, 420, 100, 30), (3, 420, 100, 0)]}


def test_replan_at_ten_keeps_the_morning_and_places_nothing_before_now():
    config = _config()
    data = _data()
    baseline, lots = _plan(data, config, MORNING)
    now = _at(1, 600)

    for result in (
        frozen.compact_preserving_started_lots(data, config, copy.deepcopy(baseline), now=now),
        frozen.optimize_preserving_started_lots(data, config, baseline, mode="quick", now=now),
    ):
        assert_plan_valid(
            result.segments, result_validation_data(data, result), config, lots=result.lots,
        )
        _assert_boundary(result, baseline, 600)
        # The rest of the started lot goes on after 10:00 today with the tool
        # still mounted, never in the morning already gone.
        rest = sorted(
            (s for s in result.segments
             if _segment_physical_row(s) != _segment_physical_row(baseline.segments[0])),
            key=lambda s: (s.day_idx, s.start_min),
        )
        assert (rest[0].day_idx, rest[0].start_min) >= (1, 600)
        assert sum(s.qty for s in result.segments) == lots["OP1"].qty
        assert frozen.historical_schedule_changes(
            _snapshot(baseline, data), _snapshot(result, data), now=now,
        ) == []


def test_before_the_shift_the_boundary_is_the_start_of_the_day():
    """At 06:30 nothing of today has gone by: unchanged from the day rule."""
    config = _config()
    data = _data()
    baseline, _lots = _plan(data, config, MORNING)

    protected = frozen._protected_plan(baseline, 1, data, config, now=_at(1, 390))

    assert protected.segments == [] and not protected


def test_running_segment_is_frozen_whole_and_its_run_continues():
    config = _config()
    data = _data()
    # 09:00-11:30 running at 10:00, then the same run goes on without setup.
    baseline, lots = _plan(data, config, {"OP1": [(1, 540, 100, 30), (1, 630, 100, 0)]})
    assert baseline.segments[0].end_min == 630

    protected = frozen._protected_plan(baseline, 1, data, config, now=_at(1, 600))

    assert [(s.day_idx, s.start_min, s.end_min) for s in protected.segments] == [
        (1, 540, 630), (1, 630, 690),
    ]
    assert [lot.id for lot in protected.lots] == [lots["OP1"].id]

    # Free shift time between them: the run stops at the running segment.
    gap = _plan(data, config, {"OP1": [(1, 540, 100, 30), (1, 720, 100, 0)]})[0]
    protected = frozen._protected_plan(gap, 1, data, config, now=_at(1, 600))
    assert [(s.day_idx, s.start_min) for s in protected.segments] == [(1, 540)]
    (original, rest), = protected.partial
    assert rest.qty == 100


def test_elapsed_minutes_are_reserved_on_every_machine_and_tool():
    config = _config()
    data = _data()
    snapshot = frozen._install_frozen_reservations(data, [], [], 1, config, now_min=600)
    try:
        for resource, blocks in (
            ("M1", data.machine_blocked_intervals), ("T1", data.tool_blocked_intervals),
        ):
            assert {(b["start_day"], b["start_min"], b["end_min"]) for b in blocks[resource]} == {
                (1, 0, 600),
            }
    finally:
        frozen._restore_frozen_reservations(data, snapshot)
    assert not data.machine_blocked_intervals.get("M1")


def _blocked(data, start, end, day=1):
    blocked = copy.deepcopy(data)
    blocked.machine_blocked_intervals = {"M1": [{
        "id": "u1", "start_day": day, "start_min": start, "end_day": day, "end_min": end,
    }]}
    return blocked


def _replan(data, config, baseline, now):
    result = frozen.optimize_preserving_started_lots(
        data, config, baseline, mode="quick", now=now,
    )
    assert_plan_valid(
        result.segments, result_validation_data(data, result), config, lots=result.lots,
    )
    return result


def _shape(segments, lot_id=None):
    return sorted(
        (s.day_idx, s.start_min, s.end_min, s.qty, s.setup_min)
        for s in segments if lot_id is None or s.lot_id == lot_id
    )


def test_outage_over_the_running_segment_cuts_it_at_now():
    """The machine broke at 09:30, declared at 10:00. The outage judges the
    running segment only from 10:00 on (``scheduler.history``): it stops at
    10:00 with the 50 pieces made (the morning ran), the rest of the same lot
    goes on after the outage with the tool still mounted (no new setup)."""
    config = _config()
    data = _data()
    baseline, lots = _plan(data, config, {"OP1": [(1, 540, 200, 30)]})
    outage = _blocked(data, 570, 720)
    now = _at(1, 600)

    protected = frozen._protected_plan(baseline, 1, outage, config, now=now)
    assert _shape(protected.segments) == [(1, 540, 600, 50, 30)]
    (_original, rest), = protected.partial
    assert rest.qty == 150

    result = _replan(outage, config, baseline, now)
    lot = lots["OP1"].id
    assert _shape(result.segments, lot)[0] == (1, 540, 600, 50, 30)
    later = _shape(result.segments, lot)[1:]
    assert later and min((day, start) for day, start, *_ in later) >= (1, 720)
    assert sum(qty for *_, qty, _setup in later) == 150
    assert sum(setup for *_, setup in later) == 0  # the tool stayed mounted
    before = _snapshot(baseline, data)
    assert frozen.historical_schedule_changes(before, _snapshot(result, outage), now=now) == []
    assert frozen.candidate_history_changes(
        before, result, outage, config, freeze_day=1, now=now,
    ) == []
    # Throwing the morning away (the whole segment after the outage) is a
    # change of production already made, whatever the inputs say.
    assert frozen.historical_schedule_changes(
        before, _snapshot(_moved(baseline, 0, 180), outage), now=now,
    ) == [lot]


def test_future_outage_over_the_running_segment_cuts_it_at_its_start():
    """Review probe: running 09:00–11:30, an outage of 11:00–13:00 entered at
    10:00. The segment goes on until 11:00 (09:00–11:00 kept, 150 pieces), no
    new setup after the outage; nothing is thrown away."""
    config = _config()
    data = _data()
    baseline, lots = _plan(data, config, {"OP1": [(1, 540, 200, 30)]})
    outage = _blocked(data, 660, 780)
    now = _at(1, 600)

    result = _replan(outage, config, baseline, now)
    shape = _shape(result.segments, lots["OP1"].id)
    assert shape[0] == (1, 540, 660, 150, 30)
    assert min((day, start) for day, start, *_ in shape[1:]) >= (1, 780)
    assert sum(setup for *_, setup in shape) == 30
    assert frozen.historical_schedule_changes(
        _snapshot(baseline, data), _snapshot(result, outage), now=now,
    ) == []


def test_retroactive_outage_keeps_the_morning():
    """Review probe: OP1 07:00–09:30 and OP2 09:30–12:00 ran; an outage of
    07:00–08:00 is entered at 13:00. It is history: both stay as they were
    (the job used to erase the 09:30–12:00 production and then fail)."""
    config = _config()
    data = _data(second_due=6)
    baseline, _lots = _plan(data, config, {
        "OP1": [(1, 420, 200, 30)], "OP2": [(1, 570, 200, 30)],
    })
    outage = _blocked(data, 420, 480)
    now = _at(1, 780)

    protected = frozen._protected_plan(baseline, 1, outage, config, now=now)
    assert _shape(protected.segments) == _shape(baseline.segments)
    result = _replan(outage, config, baseline, now)
    assert _shape(result.segments) == _shape(baseline.segments)
    assert frozen.historical_schedule_changes(
        _snapshot(baseline, data), _snapshot(result, outage), now=now,
    ) == []
    # Without the boundary the same plan breaks the outage: the boundary is
    # what lets the plan keep its history.
    from backend.scheduler.validation import validate_plan

    unbounded = copy.deepcopy(outage)
    unbounded.history_boundary = None
    assert any(
        v["kind"] == "machine_down"
        for v in validate_plan(result.segments, unbounded, config, lots=result.lots)
    )


@pytest.mark.parametrize("absent_from", [420, 600])
def test_operator_absence_entered_mid_shift(absent_from):
    """The whole shift A of Grandes absent from 07:00 (or from 10:00), entered
    at 10:00. Staffing judges the plan from 10:00 on: the morning stays; OP2,
    whose setup ended at 10:00 and made nothing, is released and goes to
    shift B. The commit guard accepts exactly that."""
    config = _config()
    data = _data(second_due=6)
    baseline, lots = _plan(data, config, {
        "OP1": [(1, 420, 200, 30)], "OP2": [(1, 570, 200, 30)],
    })
    absent = copy.deepcopy(data)
    absent.operator_blocked_intervals = [{
        "id": "a1", "start_day": 1, "end_day": 1, "start_min": absent_from, "end_min": 930,
        "group": "Grandes", "shift": "A", "count": config.operators[("Grandes", "A")],
    }]
    now = _at(1, 600)

    result = _replan(absent, config, baseline, now)
    assert _shape(result.segments, lots["OP1"].id) == [(1, 420, 570, 200, 30)]
    op2 = _shape(result.segments, lots["OP2"].id)
    assert sum(qty for *_, qty, _setup in op2) == 200
    assert all(start >= 600 for _day, start, *_ in op2)
    assert frozen.historical_schedule_changes(
        _snapshot(baseline, data), _snapshot(result, absent), now=now,
    ) == []


def test_operator_shortage_cuts_the_latest_running_segment_at_now():
    """Two machines of Grandes running at 10:00, one operator left from 10:00:
    the segment that started last stops at 10:00 with what it made."""
    from backend.config.types import MachineConfig

    config = _config()
    config.machines["M2"] = MachineConfig("M2", "Grandes")
    config.tools["T2"] = {"primary": "M2", "setup_hours": 0.5}
    data = _data(second_due=6)
    data.machines.append(MachineInfo("M2", "Grandes", 1020))
    data.ops[1].m = "M2"
    lots = {lot.op_id: lot for lot in create_lots(data, config)}
    first = _segment(lots["OP1"], 1, 480, 200, 30)    # 08:00-10:30
    second = _segment(lots["OP2"], 1, 510, 200, 30)   # 08:30-11:00
    second.machine_id = "M2"
    baseline = ScheduleResult(
        segments=[first, second], lots=list(lots.values()), score={}, time_ms=0,
        warnings=[], operator_alerts=[],
    )
    short = copy.deepcopy(data)
    short.operator_blocked_intervals = [{
        "id": "a1", "start_day": 1, "end_day": 1, "start_min": 600, "end_min": 930,
        "group": "Grandes", "shift": "A", "count": config.operators[("Grandes", "A")] - 1,
    }]
    now = _at(1, 600)

    protected = frozen._protected_plan(baseline, 1, short, config, now=now)
    assert _shape(protected.segments) == [(1, 480, 630, 200, 30), (1, 510, 600, 100, 30)]
    result = _replan(short, config, baseline, now)
    assert _shape(result.segments, lots["OP2"].id)[0] == (1, 510, 600, 100, 30)
    assert frozen.historical_schedule_changes(
        _snapshot(baseline, data), _snapshot(result, short), now=now,
    ) == []


def test_released_run_goes_on_after_its_started_part_without_setup():
    """Revision 128, 14/10 at 06:00 (PRM039): a run started yesterday after
    another tool goes on at 07:00; an outage of 07:00–09:00 releases that
    continuation. Its rest follows its own started part with the tool still
    mounted: the residual validation sees that part as the predecessor, not
    the tool before it (the job used to fail with a missing setup)."""
    config = _config()
    data = _data(second_due=6)
    baseline, lots = _plan(data, config, {
        "OP2": [(0, 600, 200, 30)],                       # T2, 10:00-12:30
        "OP1": [(0, 1290, 100, 30), (1, 420, 100, 0)],    # T1 from 21:30, on at 07:00
    })
    outage = _blocked(data, 420, 540)
    now = _at(1, 360)

    result = _replan(outage, config, baseline, now)
    rest = _shape(result.segments, lots["OP1"].id)
    assert rest[0] == (0, 1290, 1380, 100, 30)
    assert min((day, start) for day, start, *_ in rest[1:]) >= (1, 540)
    assert sum(setup for *_, setup in rest) == 30


def test_holiday_written_mid_day_keeps_the_morning():
    """A holiday on day 2, written at 11:00 of day 1 (a plan write: the clock
    is the write's own instant)."""
    from backend.transform.calendars import apply_calendars

    config = _config()
    data = _data()
    baseline, _lots = _plan(data, config, {"OP1": [(1, 420, 100, 30), (2, 420, 100, 0)]})
    config.holidays = [str(data.workdays[2])]
    apply_calendars(data, config)
    assert not factory_calendar.is_factory_workday(2, data, config)

    with factory_calendar.fixed_factory_clock(_at(1, 660)):
        result = frozen.optimize_preserving_started_lots(data, config, baseline, mode="quick")

    assert_plan_valid(
        result.segments, result_validation_data(data, result), config, lots=result.lots,
    )
    _assert_boundary(result, baseline, 660)
    assert not [s for s in result.segments if s.day_idx == 2]


def test_holiday_entered_today_stops_the_running_segment_at_now():
    """Today (day 1) becomes a holiday at 10:00: the morning already ran; the
    segment running since 09:00 stops at 10:00 with its 50 pieces."""
    from backend.transform.calendars import apply_calendars

    config = _config()
    data = _data()
    baseline, lots = _plan(data, config, {"OP1": [(1, 540, 200, 30)]})
    config.holidays = [str(data.workdays[1])]
    apply_calendars(data, config)
    now = _at(1, 600)

    protected = frozen._protected_plan(baseline, 1, data, config, now=now)
    assert _shape(protected.segments) == [(1, 540, 600, 50, 30)]
    result = _replan(data, config, baseline, now)
    later = _shape(result.segments, lots["OP1"].id)[1:]
    assert later and min((day, start) for day, start, *_ in later) >= (2, 0)
    assert frozen.historical_schedule_changes(
        _snapshot(baseline, data), _snapshot(result, data), now=now,
    ) == []


def test_recalculate_from_start_ignores_the_clock():
    """«Recalcular plano» plans from D0: no started production, nothing elapsed."""
    config = _config()
    data = _data()
    baseline, _lots = _plan(data, config, MORNING)
    now = _at(1, 600)

    _data_copy, _baseline, freeze_day, plan_now = frozen._recalculation_context(
        data, config, baseline, True, now,
    )
    assert freeze_day == 0 and plan_now == _at(0, 0)
    assert frozen.elapsed_on_planning_day(0, data, config, plan_now) == 0

    # Judged from D0 nothing is history: MORNING pauses the lot over free
    # shift time, two productions, so «Recalcular plano» rebuilds it as one
    # instead of compacting (review of 13/10/2026).
    assert stored_plan_needs_rebuild(data, baseline.segments, baseline.lots, config)
    rebuilt = [
        frozen.optimize_preserving_started_lots(
            data, config, copy.deepcopy(baseline), mode="quick",
            recalculate_from_start=True, now=when,
        )
        for when in (now, _at(1, 390))
    ]
    assert _rows(rebuilt[0].segments) == _rows(rebuilt[1].segments)
    for result in rebuilt:
        assert result.history_boundary == [0, 0]
        assert_plan_valid(
            result.segments, result_validation_data(data, result), config, lots=result.lots,
        )

    # A plan of one production per lot is compacted, the clock ignored too.
    single, _lots = _plan(data, config, {"OP1": [(1, 420, 200, 30)]})
    assert not stored_plan_needs_rebuild(data, single.segments, single.lots, config)
    late = frozen.compact_preserving_started_lots(
        data, config, copy.deepcopy(single), recalculate_from_start=True, now=now,
    )
    early = frozen.compact_preserving_started_lots(
        data, config, copy.deepcopy(single), recalculate_from_start=True, now=_at(1, 390),
    )
    assert _rows(late.segments) == _rows(early.segments)


def test_recalculate_after_an_outage_added_and_removed_rebuilds_the_cut_lot():
    """Review probe (13/10/2026): OP1 runs since 09:00; an outage of
    09:30–12:00 is entered at 10:00 and removed at 11:00. Both replans are
    valid at their own boundary, but from D0 the free time 10:00–11:00 is a
    pause: compaction would refuse the plan as a lot «partido», so
    «Recalcular plano» rebuilds it as one production."""
    from backend.scheduler.validation import PlanValidationError

    config = _config()
    data = _data()
    baseline, _lots = _plan(data, config, {"OP1": [(1, 540, 200, 30)]})
    outage = _replan(_blocked(data, 570, 720), config, baseline, _at(1, 600))
    assert _shape(outage.segments)[0] == (1, 540, 600, 50, 30)
    removed = _replan(data, config, outage, _at(1, 660))
    assert removed.history_boundary == [1, 660]
    assert [(day, start) for day, start, *_ in _shape(removed.segments)] == [(1, 540), (1, 660)]
    stored = copy.deepcopy(data)
    stored.history_boundary = removed.history_boundary

    assert stored_plan_needs_rebuild(stored, removed.segments, removed.lots, config)
    with pytest.raises(PlanValidationError) as refused:
        frozen.compact_preserving_started_lots(
            stored, config, copy.deepcopy(removed), recalculate_from_start=True,
            now=_at(1, 700),
        )
    assert [v["kind"] for v in refused.value.violations] == ["lot_split"]
    rebuilt = frozen.optimize_preserving_started_lots(
        stored, config, copy.deepcopy(removed), mode="quick", recalculate_from_start=True,
        now=_at(1, 700),
    )
    assert_plan_valid(
        rebuilt.segments, result_validation_data(stored, rebuilt), config, lots=rebuilt.lots,
    )
    assert len(rebuilt.segments) == 1


# ── Commit guard ────────────────────────────────────────────────────────


def _snapshot(result, data) -> dict:
    from dataclasses import asdict

    return {
        "dataset_info": {"id": "ds"},
        "engine_data": {
            "workdays": list(data.workdays),
            "holidays": list(data.holidays),
            "machine_blocked_days": {k: sorted(v) for k, v in data.machine_blocked_days.items()},
            "machine_blocked_intervals": copy.deepcopy(data.machine_blocked_intervals),
            "tool_blocked_days": {k: sorted(v) for k, v in data.tool_blocked_days.items()},
            "tool_blocked_intervals": copy.deepcopy(data.tool_blocked_intervals),
        },
        "config": {"timezone": "Europe/Lisbon"},
        "segments": [asdict(segment) for segment in result.segments],
        "lots": [asdict(lot) for lot in result.lots],
    }


def _moved(result, index, delta):
    moved = copy.deepcopy(result)
    moved.segments[index].start_min += delta
    moved.segments[index].end_min += delta
    return moved


def test_history_guard_reads_today_before_the_calculation_instant():
    config = _config()
    data = _data(second_due=6)
    baseline, lots = _plan(data, config, {
        "OP1": [(1, 480, 200, 30)],   # started at 08:00 today
        "OP2": [(1, 900, 200, 30)],   # 15:00 today
    })
    before = _snapshot(baseline, data)
    ten = _at(1, 600)

    # A segment that started at 08:00 changed: refused at 10:00.
    changed = _snapshot(_moved(baseline, 0, 20), data)
    assert frozen.historical_schedule_changes(before, changed, now=ten) == [lots["OP1"].id]
    # At 07:30 it had not started; the date rule alone sees nothing either.
    assert frozen.historical_schedule_changes(before, changed, now=_at(1, 450)) == []
    assert frozen.historical_schedule_changes(
        before, changed, today=str(data.workdays[1]),
    ) == []

    # New production placed in the elapsed morning: refused.
    early = _snapshot(_moved(baseline, 1, -360), data)  # 15:00 -> 09:00
    assert frozen.historical_schedule_changes(before, early, now=ten) == [lots["OP2"].id]
    # The same at 16:00 is history moving (15:00 had started).
    assert lots["OP2"].id in frozen.historical_schedule_changes(
        before, early, now=_at(1, 960),
    )

    # The early guard of a job reads the same instant.
    candidate = _moved(baseline, 1, -360)
    assert frozen.candidate_history_changes(
        before, candidate, data, config, freeze_day=1, now=ten,
    ) == [lots["OP2"].id]
    assert frozen.candidate_history_changes(
        before, _moved(baseline, 1, 60), data, config, freeze_day=1, now=ten,
    ) == []


def test_history_guard_accepts_exactly_a_cut_from_now():
    """The guard reads the release's own rule (``scheduler.history``): a
    segment running at 10:00 may stop at any minute from 10:00 with the
    pieces made by then; not earlier, not with other quantities, and it may
    disappear only if it made nothing before 10:00."""
    from backend.scheduler.history import cut_segment

    config = _config()
    data = _data(second_due=6)
    # Rows only (the guard reads rows, not machine physics).
    baseline, lots = _plan(data, config, {
        "OP1": [(1, 540, 200, 30)],   # 09:00-11:30, production from 09:30
        "OP2": [(1, 585, 200, 30)],   # 09:45-12:15, setup until 10:15
    })
    before = _snapshot(baseline, data)
    ten = _at(1, 600)

    def with_segments(*segments):
        plan = copy.deepcopy(baseline)
        plan.segments = [segment for segment in segments if segment is not None]
        return _snapshot(plan, data)

    op1, op2 = baseline.segments
    for stop in (600, 660, 689):
        assert frozen.historical_schedule_changes(
            before, with_segments(cut_segment(op1, stop), op2), now=ten,
        ) == []
    assert frozen.historical_schedule_changes(
        before, with_segments(cut_segment(op1, 590), op2), now=ten,
    ) == [lots["OP1"].id]
    wrong = cut_segment(op1, 660)
    wrong.qty -= 1
    assert frozen.historical_schedule_changes(
        before, with_segments(wrong, op2), now=ten,
    ) == [lots["OP1"].id]
    # OP1 made 50 pieces by 10:00: it cannot vanish. OP2 was still in setup.
    assert frozen.historical_schedule_changes(before, with_segments(op2), now=ten) == [
        lots["OP1"].id,
    ]
    assert frozen.historical_schedule_changes(before, with_segments(op1), now=ten) == []


def test_history_guard_keeps_the_size_of_a_lot_started_today():
    config = _config()
    data = _data()
    baseline, lots = _plan(data, config, {"OP1": [(1, 480, 100, 30), (3, 420, 100, 0)]})
    before = _snapshot(baseline, data)
    resized = copy.deepcopy(baseline)
    resized.lots[0].qty += 50
    assert frozen.historical_schedule_changes(
        before, _snapshot(resized, data), now=_at(1, 600),
    ) == [lots["OP1"].id]


# ── Manual moves ───────────────────────────────────────────────────────


def test_manual_move_at_eleven_respects_the_morning():
    from backend.plans.manual_move import ManualMoveError, move_lot

    config = _config()
    data = _data(second_due=6)
    baseline, lots = _plan(data, config, {
        "OP1": [(1, 480, 200, 30)],   # started at 08:00 today
        "OP2": [(3, 420, 200, 30)],
    })
    eleven = _at(1, 660)

    with pytest.raises(ManualMoveError, match="já iniciado"):
        move_lot(
            baseline.segments, baseline.lots, {}, data, config,
            lot_id=lots["OP1"].id, target_day=2, target_start_min=420, now=eleven,
        )
    with pytest.raises(ManualMoveError, match="já passou"):
        move_lot(
            baseline.segments, baseline.lots, {}, data, config,
            lot_id=lots["OP2"].id, target_day=1, target_start_min=630, now=eleven,
        )


# ── Real case: revision 126 → 127, outage removed at 15:39 on 13/10 ────

OUTAGE_ID = "u_af96c62f03b0"  # PRM043, 12/10 11:30 to 18/10
REST_LOT = "LOT_JTE001_PRM043_6800016767A.10_5"


def test_rev127_outage_removed_at_1539_places_nothing_before_now(monkeypatch):
    from backend.config.unavailability import remove_unavailability_entry
    from backend.plans.serialize import deserialize_snapshot
    from backend.plans.store import _assert_activatable_payload
    from backend.replan import jobs
    from backend.scheduler.improvement import order_service

    _manifest, payload = load_payload("rev126")
    freeze_day = load_payload("rev127")[0]["freeze_day"]
    removed_at = datetime(2026, 10, 13, 15, 39, tzinfo=LISBON)
    now_min = 15 * 60 + 39
    # The job captures the clock once; the whole job reads that instant.
    monkeypatch.setattr(factory_calendar, "factory_now",
                        lambda _config, *, now=None: (now or removed_at).astimezone(LISBON))
    restored = deserialize_snapshot(copy.deepcopy(payload))
    config, engine_data = restored["config"], restored["engine_data"]
    assert str(engine_data.workdays[freeze_day])[:10] == "2026-10-13"
    assert remove_unavailability_entry(config, OUTAGE_ID) is not None
    store = jobs.ReplanJobStore(":memory:")
    manager = jobs.ReplanJobManager(store)
    dataset = payload["dataset_info"]
    job = store.create("Indisponibilidades alteradas", dataset["id"], payload["plan_revision"])
    started = time.monotonic()
    try:
        manager._run(
            job["id"], engine_data, config, dataset["id"], payload["plan_revision"],
            "Indisponibilidades alteradas", dataset, baseline_snapshot=payload,
            reoptimize_relaxed_baseline=True,
        )
    finally:
        manager.executor.shutdown(wait=True)
    assert time.monotonic() - started < jobs.REPLAN_TOTAL_BUDGET_S

    final = store.get(job["id"])
    assert final["status"] == "ready", (final["message"], final.get("error"))
    assert final["result"]["planning_now"] == removed_at.isoformat()
    candidate = store.get_candidate(job["id"])
    _assert_activatable_payload(candidate)
    # The commit guard at the job's instant accepts it.
    assert frozen.historical_schedule_changes(payload, candidate, now=removed_at) == []
    before = {
        (s["lot_id"], s["machine_id"], s["start_min"], s["end_min"])
        for s in payload["segments"]
        if s["day_idx"] == freeze_day and s["start_min"] < now_min
        and s["end_min"] > s["start_min"]
    }
    today = {
        (s["lot_id"], s["machine_id"], s["start_min"], s["end_min"])
        for s in candidate["segments"]
        if s["day_idx"] == freeze_day and s["start_min"] < now_min
        and s["end_min"] > s["start_min"]
    }
    # This morning's production unchanged, nothing new before 15:39.
    assert today == before
    plan = deserialize_snapshot(copy.deepcopy(candidate))
    data, result = plan["engine_data"], plan["result"]
    rest = [s for s in result.segments if s.lot_id == REST_LOT and s.day_idx >= freeze_day]
    assert rest and min((s.day_idx, s.start_min) for s in rest) >= (freeze_day, now_min)
    # Started lots keep their size; the rest follows the economic lot as a
    # minimum (14/10/2026).
    from tests.test_eco_lot_minimum import assert_replan_sizes

    assert_replan_sizes(payload, candidate, freeze_day, now_min)
    # Honest physics: with the time left after 15:39 the deliveries are met.
    late = [
        key for key, service in order_service(result.segments, result.lots, data).items()
        if service.tardiness > 0 and key[0] in ("6800016767A.10", "CF589MMA1A02.20")
    ]
    assert late == []
