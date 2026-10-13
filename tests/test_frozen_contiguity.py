"""Rule 4: a running run continues only while no free working time interrupts it.

Decided by Luís on 13/10/2026 (AGENTS §2, rule 4). Real case: revision 127.
An outage of PRM043 (12/10 11:30 to 18/10) was added and then removed. The
started lot of JTE001 ran until the outage and went on, without setup, on
19/10; that later block stayed frozen as "the run going on" and its days were
reserved, so PRM043 stayed idle on 13-18/10 while two orders were late.
Nights, weekends, holidays and unavailabilities do not interrupt a run; free
shift time on the current calendar does, and the rest of the lot is replanned
as the same lot, without a new setup while its tool is still mounted.
"""

from __future__ import annotations

import copy
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend import calendar as factory_calendar
from backend.config.types import FactoryConfig, MachineConfig
from backend.plans import frozen
from backend.scheduler.canonical import result_validation_data
from backend.scheduler.improvement import _segment_physical_row, physical_setups
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.types import ScheduleResult, Segment
from backend.scheduler.validation import assert_plan_valid
from backend.types import EngineData, EOp, MachineInfo
from tests.snapshot_fixture import load_payload

START = date(2026, 3, 2)  # a Monday: days 5 and 6 are a weekend
LISBON = ZoneInfo("Europe/Lisbon")


def _at(day: int, minute: int) -> datetime:
    """Factory time ``minute`` of plan day ``day``."""
    when = START + timedelta(days=day)
    return datetime(when.year, when.month, when.day, minute // 60, minute % 60, tzinfo=LISBON)


def _clock(monkeypatch, day: int, minute: int) -> None:
    """Pin the factory clock read by every rule-4 check."""
    fixed = _at(day, minute)
    monkeypatch.setattr(factory_calendar, "factory_now",
                        lambda _config, *, now=None: (now or fixed).astimezone(LISBON))


def _config() -> FactoryConfig:
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    config.tools = {"T1": {"primary": "M1", "setup_hours": 0.5}}
    return config


def _data(due_day: int = 4) -> EngineData:
    days = [(START + timedelta(days=i)).isoformat() for i in range(14)]
    demand = [0] * len(days)
    demand[due_day] = 200
    op = EOp(
        id="OP1", sku="SKU1", client="C", designation="Peça", m="M1", t="T1", pH=100,
        sH=0.5, operators=1, eco_lot=200, alt=None, stk=0, backlog=0, d=demand,
        oee=1.0, wip=0,
    )
    return EngineData(
        ops=[op], machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[],
        client_demands={}, workdays=days, n_days=len(days),
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )


def _plan(data, config, blocks):
    """``blocks``: (day, start, qty, setup) of the one lot, a single run."""
    (lot,) = create_lots(data, config)
    assert lot.qty == 200
    segments = []
    for day, start, qty, setup in blocks:
        prod = lot.prod_min * qty / lot.qty
        segments.append(Segment(
            lot.id, f"quantity:{lot.id}:0", "M1", "T1", day, start, start + int(setup + prod),
            "A" if start < 930 else "B", qty, prod, setup, sku=lot.sku, lot_qty=lot.qty,
            output_milestones=copy.deepcopy(lot.output_milestones),
        ))
    return ScheduleResult(segments=segments, lots=[lot], score={}, time_ms=0, warnings=[],
                          operator_alerts=[]), lot


def _frozen_rows(protected):
    return [(s.day_idx, s.start_min) for s in protected.segments]


# Started on day 0, going on without setup on day 3: days 1 and 2 between.
AFTER_GAP = [(0, 420, 100, 30), (3, 420, 100, 0)]


def test_outage_in_the_gap_keeps_the_run_and_its_removal_releases_the_rest():
    config = _config()
    data = _data()
    baseline, lot = _plan(data, config, AFTER_GAP)
    outage = copy.deepcopy(data)
    outage.machine_blocked_days = {"M1": {1, 2}}
    assert_plan_valid(baseline.segments, outage, config, lots=baseline.lots)

    # With the outage there is no working time between: the run goes on.
    protected = frozen._protected_plan(baseline, 1, outage, config)
    assert _frozen_rows(protected) == [(0, 420), (3, 420)]
    assert [item.id for item in protected.lots] == [lot.id] and protected.partial == []

    # Outage removed: days 1 and 2 are free shift time, the run stops there.
    protected = frozen._protected_plan(baseline, 1, data, config)
    assert _frozen_rows(protected) == [(0, 420)]
    (original, rest), = protected.partial
    assert original.id == rest.id == lot.id
    assert (rest.qty, rest.machine_id) == (100, "M1")


def test_released_rest_goes_right_after_the_boundary_without_a_new_setup(monkeypatch):
    config = _config()
    data = _data()
    baseline, lot = _plan(data, config, AFTER_GAP)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_args, **_kw: 1)
    # The replan runs before the first shift of the planning day: 07:00 is
    # still ahead, so it is the first free minute.
    _clock(monkeypatch, 1, 6 * 60 + 30)

    result = frozen.compact_preserving_started_lots(data, config, copy.deepcopy(baseline))

    assert_plan_valid(
        result.segments, result_validation_data(data, result), config, lots=result.lots,
    )
    # What started is unchanged; the rest follows on the first free shift
    # minute with the tool still mounted: no second setup.
    assert _segment_physical_row(baseline.segments[0]) in {
        _segment_physical_row(s) for s in result.segments
    }
    rest = sorted(
        (s for s in result.segments if s.day_idx >= 1),
        key=lambda s: (s.day_idx, s.start_min),
    )
    assert (rest[0].day_idx, rest[0].start_min) == (1, 420)
    assert all(s.setup_min == 0 for s in rest)
    assert sum(s.qty for s in result.segments) == lot.qty
    assert physical_setups(result.segments).count == 1


def test_constructor_places_the_rest_on_the_mounted_tool_without_setup(monkeypatch):
    config = _config()
    data = _data()
    baseline, lot = _plan(data, config, AFTER_GAP)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_args, **_kw: 1)
    _clock(monkeypatch, 1, 6 * 60 + 30)

    result = frozen.optimize_preserving_started_lots(data, config, baseline, mode="quick")

    assert_plan_valid(
        result.segments, result_validation_data(data, result), config, lots=result.lots,
    )
    rest = [s for s in result.segments if s.day_idx >= 1]
    assert min((s.day_idx, s.start_min) for s in rest) == (1, 420)
    assert all(s.setup_min == 0 for s in rest)
    assert sum(s.qty for s in result.segments) == lot.qty


@pytest.mark.parametrize(
    ("blocks", "freeze_day", "due_day"),
    [
        # Shift B until midnight, then shift A the next morning.
        ([(0, 1350, 100, 30), (1, 420, 100, 0)], 1, 4),
        # Friday evening, then Monday morning (weekend not yet elapsed).
        ([(4, 1350, 100, 30), (7, 420, 100, 0)], 5, 11),
    ],
    ids=["night", "weekend"],
)
def test_run_across_closed_time_stays_frozen(blocks, freeze_day, due_day):
    config = _config()
    data = _data(due_day)
    baseline, lot = _plan(data, config, blocks)

    protected = frozen._protected_plan(baseline, freeze_day, data, config)

    assert _frozen_rows(protected) == [(day, start) for day, start, _qty, _setup in blocks]
    assert [item.id for item in protected.lots] == [lot.id]


def test_holiday_and_shift_without_operators_do_not_interrupt():
    config = _config()
    data = _data()
    # Day 1 at 600: shift A of day 1 is free, so the run stops...
    baseline, _lot = _plan(data, config, [(0, 420, 100, 30), (1, 600, 100, 0)])
    assert _frozen_rows(frozen._protected_plan(baseline, 1, data, config)) == [(0, 420)]
    # ...unless that shift has no operators of the machine's group.
    config.operators[("Grandes", "A")] = 0
    config.operators[("Grandes", "B")] = 2
    baseline, _lot = _plan(data, config, [(0, 930, 100, 30), (1, 930, 100, 0)])
    assert _frozen_rows(frozen._protected_plan(baseline, 1, data, config)) == [(0, 930), (1, 930)]

    config = _config()
    holiday = _data()
    holiday.holidays = sorted({*holiday.holidays, 1})
    baseline, _lot = _plan(holiday, config, [(0, 420, 100, 30), (2, 420, 100, 0)])
    assert _frozen_rows(frozen._protected_plan(baseline, 1, holiday, config)) == [
        (0, 420), (2, 420),
    ]
    # The same gap on a working day is free time.
    baseline, _lot = _plan(_data(), config, [(0, 420, 100, 30), (2, 420, 100, 0)])
    assert _frozen_rows(frozen._protected_plan(baseline, 1, _data(), config)) == [(0, 420)]


def test_free_working_time_between_reads_the_current_calendar():
    config = _config()
    data = _data()
    replayed = _at(10, 600)  # another date: no minute of the plan has elapsed

    def free(start, end, freeze_day=1, view=data, now=replayed):
        return frozen.free_working_time_between(
            "M1", "T1", start, end, freeze_day, view, config, now=now,
        )

    assert not free((0, 510), (1, 420))  # elapsed day, then the night
    # Less than MIN_FREE_INTERVAL_MIN (30 min) is a gap, not working time.
    assert not free((0, 510), (1, 449))
    assert free((0, 510), (1, 450))
    assert not free((1, 600), (1, 600.5))
    assert not free((4, 1440), (7, 420), freeze_day=5)  # weekend
    assert not free((4, 1430), (7, 420), freeze_day=4)  # Friday's last ten minutes
    assert free((4, 1410), (7, 420), freeze_day=4)  # Friday's last half hour
    blocked = copy.deepcopy(data)
    blocked.machine_blocked_intervals = {"M1": [
        {"start_day": 1, "start_min": 420, "end_day": 1, "end_min": 1440},
    ]}
    assert not free((0, 510), (2, 420), view=blocked)
    tool = copy.deepcopy(data)
    tool.tool_blocked_intervals = {"T1": [
        {"start_day": 1, "start_min": 420, "end_day": 1, "end_min": 900},
    ]}
    assert free((0, 510), (2, 420), view=tool)  # 900-1440 of day 1 is free
    tool.tool_blocked_intervals["T1"][0]["end_min"] = 1440
    assert not free((0, 510), (2, 420), view=tool)


def test_elapsed_time_of_today_is_not_free():
    """Today before the current factory minute has gone by: it is not idle time."""
    config = _config()
    data = _data()

    def free(now):
        return frozen.free_working_time_between(
            "M1", "T1", (0, 1020), (2, 420), 1, data, config, now=now,
        )

    assert free(_at(1, 6 * 60))  # before the shifts: the whole of day 1 is ahead
    assert free(_at(1, 15 * 60))  # 15:00-24:00 is still free
    assert not free(_at(1, 23 * 60 + 45))  # only 15 minutes left today
    # The clock is read in the factory's time zone (UTC 23:50 is 00:50 in
    # Lisbon in summer time, but March is winter time: 23:50 there too).
    assert not free(datetime(2026, 3, 3, 23, 50, tzinfo=ZoneInfo("UTC")))


def test_outage_removed_after_the_run_resumed_keeps_the_run(monkeypatch):
    """Review scenario: outage today 07:00-13:00, the run resumed at 13:00, the
    outage is removed at 15:00. The morning has gone by: the run continues
    and stays frozen; the plan never claims production while it was down."""
    config = _config()
    data = _data()  # the outage is no longer in the inputs
    baseline, lot = _plan(data, config, [(0, 930, 100, 30), (1, 780, 100, 0)])

    protected = frozen._protected_plan(baseline, 1, data, config, now=_at(1, 15 * 60))
    assert _frozen_rows(protected) == [(0, 930), (1, 780)]
    assert [item.id for item in protected.lots] == [lot.id] and protected.partial == []

    # Removed before the shift started: the morning was free, the run stops.
    protected = frozen._protected_plan(baseline, 1, data, config, now=_at(1, 6 * 60))
    assert _frozen_rows(protected) == [(0, 930)]

    # Compaction at 15:00 leaves the resumed run where it is.
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_args, **_kw: 1)
    _clock(monkeypatch, 1, 15 * 60)
    result = frozen.compact_preserving_started_lots(data, config, copy.deepcopy(baseline))
    assert {(s.day_idx, s.start_min) for s in result.segments if s.day_idx >= 1} == {(1, 780)}


def _two_machine_config(operators: int) -> FactoryConfig:
    config = FactoryConfig(machines={
        "M1": MachineConfig("M1", "Grandes"), "M2": MachineConfig("M2", "Grandes"),
    })
    config.tools = {"T1": {"primary": "M1", "setup_hours": 0.5}}
    config.operators[("Grandes", "A")] = operators
    config.operators[("Grandes", "B")] = operators
    return config


def _other_machine(day: int, start: int, end: int) -> Segment:
    return Segment("LOT_OTHER", "run:other", "M2", "T9", day, start, end, "A", 10,
                   float(end - start), 0.0, sku="OTHER")


@pytest.mark.parametrize(
    ("other", "frozen_rows"),
    [
        # 07:00-08:00 is free and staffed: the run stops.
        (None, [(0, 930)]),
        # The only operator is on M2 until 07:40: 20 free minutes, a sliver.
        ((420, 460), [(0, 930), (1, 480)]),
        # On M2 until 07:20 only: 40 staffed minutes are free time.
        ((420, 440), [(0, 930)]),
    ],
    ids=["free-hour", "operator-sliver", "operator-leaves-time"],
)
def test_operator_slivers_do_not_interrupt_the_run(other, frozen_rows):
    config = _two_machine_config(operators=1)
    data = _data()
    data.machines.append(MachineInfo("M2", "Grandes", 1020))
    baseline, _lot = _plan(data, config, [(0, 930, 100, 30), (1, 480, 100, 0)])
    if other is not None:
        baseline.segments.append(_other_machine(1, *other))

    protected = frozen._protected_plan(baseline, 1, data, config, now=_at(10, 600))

    assert sorted(
        (s.day_idx, s.start_min) for s in protected.segments if s.machine_id == "M1"
    ) == frozen_rows


def test_eight_minute_gap_keeps_the_run():
    """Revision 124, day 4: PRM019 (VUL184) stops at 15:30 and goes on without
    setup at 15:38; the eight minutes are lost to operator concurrency. A gap
    shorter than MIN_FREE_INTERVAL_MIN is no idle time: the run goes on."""
    config = _config()
    data = _data()
    blocks = [(0, 1380, 50, 30), (1, 420, 50, 0), (1, 458, 100, 0)]
    baseline, lot = _plan(data, config, blocks)
    assert baseline.segments[1].end_min == 450

    protected = frozen._protected_plan(baseline, 1, data, config, now=_at(10, 600))

    assert _frozen_rows(protected) == [(day, start) for day, start, _qty, _setup in blocks]
    assert [item.id for item in protected.lots] == [lot.id]


def test_new_outage_on_the_continuation_still_stops_the_run():
    config = _config()
    data = _data()
    baseline, _lot = _plan(data, config, [(0, 1350, 100, 30), (1, 420, 100, 0)])
    blocked = copy.deepcopy(data)
    blocked.machine_blocked_intervals = {"M1": [
        {"start_day": 1, "start_min": 420, "end_day": 1, "end_min": 600},
    ]}

    protected = frozen._protected_plan(baseline, 1, blocked, config)

    assert _frozen_rows(protected) == [(0, 1350)]
    (_original, rest), = protected.partial
    assert rest.qty == 100


# ── Real case: revision 126 → 127 (13/10/2026) ──────────────────────────

OUTAGE_ID = "u_af96c62f03b0"  # PRM043, 12/10 11:30 to 18/10, removed on 13/10
LATE_IN_REV127 = ("6800016767A.10", "CF589MMA1A02.20")


def test_rev127_run_after_the_removed_outage_is_not_frozen():
    from backend.plans.serialize import deserialize_snapshot

    manifest, payload = load_payload("rev127")
    restored = deserialize_snapshot(copy.deepcopy(payload))
    data, config, result = restored["engine_data"], restored["config"], restored["result"]

    # The day rule (06:00 of the planning day): independent of the hour of the run.
    day = str(data.workdays[manifest["freeze_day"]])[:10]
    protected = frozen._protected_plan(
        result, manifest["freeze_day"], data, config,
        now=datetime.fromisoformat(f"{day}T06:00").replace(tzinfo=LISBON),
    )

    # Before: PRM043's blocks of 19/10 were frozen and 13-18/10 reserved.
    assert not [
        s for s in protected.segments
        if s.machine_id == "PRM043" and s.day_idx >= manifest["freeze_day"]
    ]
    rests = {rest.id: rest for _original, rest in protected.partial}
    started_on_prm043 = {
        s.lot_id for s in result.segments
        if s.machine_id == "PRM043" and s.day_idx < manifest["freeze_day"]
        and s.tool_id == "JTE001"
    }
    assert started_on_prm043 and started_on_prm043 <= set(rests)


def test_rev127_capacity_release_replan_has_no_late_order(monkeypatch):
    from backend.config.unavailability import remove_unavailability_entry
    from backend.plans.serialize import deserialize_snapshot
    from backend.plans.store import _assert_activatable_payload
    from backend.replan import jobs
    from backend.scheduler.idle_capacity import late_with_idle_capacity
    from backend.scheduler.improvement import order_service, subcontract_lateness

    manifest, payload = load_payload("rev126")
    freeze_day = load_payload("rev127")[0]["freeze_day"]
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_args, **_kw: freeze_day)
    monkeypatch.setattr(jobs, "_current_planning_day", lambda *_args, **_kw: freeze_day)
    # The outage was removed on 13/10 at 15:39 (revision 127).
    removed_at = datetime(2026, 10, 13, 15, 39, tzinfo=LISBON)
    monkeypatch.setattr(factory_calendar, "factory_now",
                        lambda _config, *, now=None: (now or removed_at).astimezone(LISBON))
    restored = deserialize_snapshot(copy.deepcopy(payload))
    config, engine_data = restored["config"], restored["engine_data"]
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
    elapsed = time.monotonic() - started

    final = store.get(job["id"])
    assert final["status"] == "ready", (final["message"], final.get("error"))
    assert elapsed < jobs.REPLAN_TOTAL_BUDGET_S
    candidate = store.get_candidate(job["id"])
    _assert_activatable_payload(candidate)
    assert frozen.historical_schedule_changes(
        payload, candidate, today=engine_data.workdays[freeze_day][:10],
    ) == []
    assert {lot["id"]: lot["qty"] for lot in candidate["lots"]} == {
        lot["id"]: lot["qty"] for lot in payload["lots"]
    }
    plan = deserialize_snapshot(copy.deepcopy(candidate))
    data, result = plan["engine_data"], plan["result"]
    late = [
        key for key, service in order_service(result.segments, result.lots, data).items()
        if service.tardiness > 0 and key[0] in LATE_IN_REV127
    ]
    assert late == []
    assert not [
        key for key, days in subcontract_lateness(result.segments, result.lots, data).items()
        if days > 0
    ]
    assert late_with_idle_capacity(
        result.segments, result.lots, data, plan["config"], planning_day=freeze_day,
        now=removed_at,
    ) == []
    # PRM043 goes back to work after the removal (never in the hours of 13/10
    # already gone, AGENTS §2 rule 4 since 13/10/2026) and the started JTE001
    # lot goes on without a new setup.
    first = min(
        (s for s in result.segments if s.machine_id == "PRM043" and s.day_idx >= freeze_day),
        key=lambda s: (s.day_idx, s.start_min),
    )
    assert (first.day_idx, first.start_min) >= (freeze_day, 15 * 60 + 39)
    assert first.tool_id == "JTE001" and first.setup_min == 0
    # The note of the outage's rebuild is not carried over.
    assert not any(w.startswith("A alteração afeta") for w in final["warnings"])
