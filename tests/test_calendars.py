"""Tests for backend/transform/calendars.py — Fase 1.5 persistent calendars."""

from __future__ import annotations

import copy

import pytest

from backend.config.types import FactoryConfig, ShiftConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.jit_policy import calendar_holidays
from backend.calendar import available_machine_capacity, available_operator_capacity, available_tool_capacity
from backend.scheduler.operators import compute_operator_alerts
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.types import Segment
from backend.transform.calendars import apply_calendars
from backend.simulator import Mutation, simulate
from backend.simulator.mutations import apply_mutation
from backend.types import EngineData, EOp, MachineInfo

# 2026-03-02 is a Monday; index 5 = Saturday 2026-03-07, 6 = Sunday 2026-03-08
WORKDAYS = [f"2026-03-{i + 2:02d}" for i in range(14)]


def _eop(d: list[int] | None = None) -> EOp:
    return EOp(
        id="T1_M1_SKU1",
        sku="SKU1",
        client="CLIENT",
        designation="Test",
        m="M1",
        t="T1",
        pH=100.0,
        sH=0.5,
        operators=1,
        eco_lot=0,
        alt=None,
        stk=0,
        backlog=0,
        d=d or [0] * 14,
        oee=0.66,
        wip=0,
    )


def _engine(d: list[int] | None = None, holidays: list[int] | None = None) -> EngineData:
    return EngineData(
        ops=[_eop(d)],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
        twin_groups=[],
        client_demands={},
        workdays=WORKDAYS,
        n_days=len(WORKDAYS),
        holidays=holidays if holidays is not None else [5, 6, 12, 13],  # weekends
    )


class TestHolidayUnion:
    def test_factory_holidays_added(self):
        """Regression: runtime holidays saved to factory.yaml must reach the engine."""
        engine = _engine()
        config = FactoryConfig(holidays=["2026-03-04"])  # Wednesday, idx 2
        apply_calendars(engine, config)
        assert 2 in engine.holidays
        assert 5 in engine.holidays  # weekends preserved

    def test_future_date_is_retained(self):
        engine = _engine()
        config = FactoryConfig(holidays=["2030-01-01"])
        apply_calendars(engine, config)
        assert engine.holidays == [5, 6, 12, 13, 1401]

    def test_none_config_noop(self):
        engine = _engine()
        assert apply_calendars(engine, None) is engine
        assert engine.holidays == [5, 6, 12, 13]

    def test_runtime_holiday_removal_restores_baseline(self):
        engine = _engine()
        config = FactoryConfig(holidays=["2026-03-04"])
        apply_calendars(engine, config)
        assert 2 in engine.holidays

        config.holidays = []
        apply_calendars(engine, config)
        assert 2 not in engine.holidays
        assert engine.holidays == [5, 6, 12, 13]

    def test_factory_holiday_after_imported_horizon_is_retained(self):
        engine = _engine()
        engine.workdays = ["2026-03-02"]
        engine.n_days = 1
        engine.holidays = []
        config = FactoryConfig(holidays=["2026-03-03"])

        apply_calendars(engine, config)

        assert 1 in engine.holidays
        assert 1 in calendar_holidays(engine, 0, 3)


class TestExtraWorkdays:
    def test_saturday_reopened(self):
        engine = _engine()
        config = FactoryConfig(extra_workdays=["2026-03-07"])  # Saturday, idx 5
        apply_calendars(engine, config)
        assert 5 not in engine.holidays
        assert 6 in engine.holidays

    def test_explicit_holiday_wins_over_extra_workday(self):
        engine = _engine()
        config = FactoryConfig(holidays=["2026-03-07"], extra_workdays=["2026-03-07"])
        apply_calendars(engine, config)
        assert 5 in engine.holidays

    def test_weekday_not_reopenable(self):
        """extra_workdays only reopens auto-weekend days."""
        engine = _engine(holidays=[2, 5, 6])
        config = FactoryConfig(extra_workdays=["2026-03-04"])  # Wednesday
        apply_calendars(engine, config)
        assert 2 in engine.holidays

    def test_removing_extra_workday_recloses_saturday(self):
        engine = _engine()
        config = FactoryConfig(extra_workdays=["2026-03-07"])
        apply_calendars(engine, config)
        assert 5 not in engine.holidays

        config.extra_workdays = []
        apply_calendars(engine, config)
        assert 5 in engine.holidays

    def test_master_explicit_weekend_cannot_be_reopened(self):
        engine = _engine()
        engine.calendar_base_holidays = [5, 6, 12, 13]
        engine.calendar_explicit_holidays = [5]
        config = FactoryConfig(extra_workdays=["2026-03-07"])
        apply_calendars(engine, config)
        assert 5 in engine.holidays

    def test_future_weekend_can_be_reopened_after_imported_horizon(self):
        engine = _engine()
        engine.workdays = ["2026-03-02"]
        engine.n_days = 1
        engine.holidays = []
        config = FactoryConfig(extra_workdays=["2026-03-07"])

        apply_calendars(engine, config)

        assert 5 not in calendar_holidays(engine, 0, 7)


class TestBlockedDays:
    def test_machine_range_mapped(self):
        engine = _engine()
        config = FactoryConfig(
            machine_unavailability=[
                {"id": "u1", "resource": "M1", "from": "2026-03-04", "to": "2026-03-06"}
            ]
        )
        apply_calendars(engine, config)
        assert engine.machine_blocked_days == {"M1": {2, 3, 4}}

    def test_tool_single_day(self):
        engine = _engine()
        config = FactoryConfig(
            tool_unavailability=[{"id": "u1", "resource": "T1", "from": "2026-03-05", "to": ""}]
        )
        apply_calendars(engine, config)
        # invalid 'to' → empty range
        assert engine.tool_blocked_days == {}
        config.tool_unavailability = [
            {"id": "u1", "resource": "T1", "from": "2026-03-05", "to": "2026-03-05"}
        ]
        apply_calendars(engine, config)
        assert engine.tool_blocked_days == {"T1": {3}}

    def test_rebuild_is_removal_safe(self):
        """Removing a calendar entry and re-applying clears the block."""
        engine = _engine()
        config = FactoryConfig(
            machine_unavailability=[
                {"id": "u1", "resource": "M1", "from": "2026-03-04", "to": "2026-03-04"}
            ]
        )
        apply_calendars(engine, config)
        assert engine.machine_blocked_days
        config.machine_unavailability = []
        apply_calendars(engine, config)
        assert engine.machine_blocked_days == {}

    def test_idempotent(self):
        engine = _engine()
        config = FactoryConfig(
            machine_unavailability=[
                {"id": "u1", "resource": "M1", "from": "2026-03-04", "to": "2026-03-05"}
            ]
        )
        apply_calendars(engine, config)
        first = {k: set(v) for k, v in engine.machine_blocked_days.items()}
        apply_calendars(engine, config)
        assert engine.machine_blocked_days == first

    def test_finite_machine_range_after_imported_horizon_is_projected(self):
        engine = _engine()
        engine.workdays = ["2026-03-02"]
        engine.n_days = 1
        engine.holidays = []
        config = FactoryConfig(
            machine_unavailability=[
                {
                    "id": "future",
                    "resource": "M1",
                    "start_at": "2026-03-03T00:00:00+00:00",
                    "end_at": "2026-03-04T00:00:00+00:00",
                }
            ]
        )

        apply_calendars(engine, config)

        assert engine.machine_blocked_days == {"M1": {1}}
        assert available_machine_capacity("M1", 1, engine, config) == 0


class TestSchedulerAvoidance:
    def test_dispatch_avoids_config_blocked_machine_days(self):
        """Config-sourced blocked days are avoided like holidays."""
        demand = [0] * 14
        demand[10] = 500  # EDD day 10 (Thursday week 2)
        engine = _engine(d=demand)
        config = FactoryConfig(
            machine_unavailability=[
                # Block Mon-Wed of week 2 (idx 7, 8, 9)
                {"id": "u1", "resource": "M1", "from": "2026-03-09", "to": "2026-03-11"}
            ]
        )
        apply_calendars(engine, config)
        result = schedule_all(engine, config=config)
        assert result.score["otd"] == 100.0
        prod_days = {s.day_idx for s in result.segments}
        assert prod_days.isdisjoint({7, 8, 9})


class TestOperatorUnavailability:
    def test_absence_reduces_advisory_capacity(self):
        engine = _engine()
        config = FactoryConfig(
            operator_unavailability=[
                {
                    "id": "u1",
                    "group": "Grandes",
                    "shift": "A",
                    "from": "2026-03-04",
                    "to": "2026-03-04",
                    "count": 1,
                }
            ]
        )
        config.operators[("Grandes", "A")] = 1
        apply_calendars(engine, config)
        segment = Segment(
            lot_id="L1",
            run_id="R1",
            machine_id="M1",
            tool_id="T1",
            day_idx=2,
            start_min=420,
            end_min=480,
            shift="A",
            qty=100,
            prod_min=60,
        )

        alerts = compute_operator_alerts([segment], engine, config)

        assert len(alerts) == 1
        assert alerts[0].available == 0
        assert alerts[0].deficit == 1

    def test_finite_operator_absence_after_imported_horizon_is_projected(self):
        engine = _engine()
        engine.workdays = ["2026-03-02"]
        engine.n_days = 1
        engine.holidays = []
        config = FactoryConfig(
            operator_unavailability=[
                {
                    "id": "future",
                    "group": "Grandes",
                    "shift": "A",
                    "start_at": "2026-03-03T07:00:00+00:00",
                    "end_at": "2026-03-03T15:30:00+00:00",
                    "count": 1,
                }
            ]
        )

        apply_calendars(engine, config)

        assert [(item["start_day"], item["start_min"], item["end_min"]) for item in engine.operator_blocked_intervals] == [
            (1, 420, 930)
        ]


def test_partial_multi_day_interval_only_marks_fully_covered_slices():
    engine = _engine()
    config = FactoryConfig(
        machine_unavailability=[
            {
                "id": "m1",
                "resource": "M1",
                "start_at": "2026-03-02T10:00+00:00",
                "end_at": "2026-03-03T10:00+00:00",
            }
        ]
    )
    apply_calendars(engine, config)
    assert engine.machine_blocked_days == {}
    assert [(item["start_day"], item["start_min"], item["end_min"]) for item in engine.machine_blocked_intervals["M1"]] == [
        (0, 600, 1440),
        (1, 420, 600),
    ]


def test_overlapping_resource_intervals_are_unioned_before_consumption():
    engine = _engine()
    config = FactoryConfig(
        machine_unavailability=[
            {
                "id": "m1",
                "resource": "M1",
                "start_at": "2026-03-02T09:00+00:00",
                "end_at": "2026-03-02T11:00+00:00",
            },
            {
                "id": "m2",
                "resource": "M1",
                "start_at": "2026-03-02T10:00+00:00",
                "end_at": "2026-03-02T12:00+00:00",
            },
        ]
    )
    apply_calendars(engine, config)
    assert [(item["start_min"], item["end_min"]) for item in engine.machine_blocked_intervals["M1"]] == [
        (540, 720)
    ]
    assert available_machine_capacity("M1", 0, engine, config) == DAY_CAP - 180


def test_downtime_inside_a_closed_shift_gap_consumes_no_capacity():
    engine = _engine()
    config = FactoryConfig(
        shifts=[
            ShiftConfig("A", 420, 720),
            ShiftConfig("B", 780, 1020),
        ],
        machine_unavailability=[
            {
                "id": "m1",
                "resource": "M1",
                "start_at": "2026-03-02T12:00+00:00",
                "end_at": "2026-03-02T13:00+00:00",
            }
        ],
    )
    apply_calendars(engine, config)
    assert engine.machine_blocked_intervals == {}
    assert available_machine_capacity("M1", 0, engine, config) == 540


def test_open_breakdown_marks_future_imported_days_but_not_earlier_minutes():
    engine = _engine()
    config = FactoryConfig(
        machine_unavailability=[
            {
                "id": "m1",
                "resource": "M1",
                "start_at": "2026-03-02T10:00+00:00",
                "end_at": "",
                "category": "Avaria",
            }
        ]
    )
    apply_calendars(engine, config)
    assert 0 not in engine.machine_blocked_days["M1"]
    assert set(range(1, len(WORKDAYS))) <= engine.machine_blocked_days["M1"]
    assert engine.machine_blocked_intervals["M1"][0]["start_min"] == 600


@pytest.mark.parametrize("kind,resource", [("machine", "M1"), ("tool", "T1")])
@pytest.mark.parametrize("start_at,first_blocked", [
    ("2026-03-02T17:00+00:00", 1),
    ("2026-03-02T18:00+00:00", 1),
    ("2026-03-06T18:00+00:00", 5),
])
def test_open_outage_after_final_shift_retains_future_block(kind, resource, start_at, first_blocked):
    from backend.scheduler.global_jit import _preemptive_resource_windows

    engine = _engine()
    engine.workdays = ["2026-03-02"]
    engine.n_days = 1
    engine.holidays = []
    config = FactoryConfig(shifts=[ShiftConfig("A", 480, 1020)])
    setattr(config, f"{kind}_unavailability", [{
        "id": "open", "resource": resource, "start_at": start_at,
        "end_at": "", "category": "Avaria",
    }])
    before = copy.deepcopy(config)
    apply_calendars(engine, config)
    entries = getattr(engine, f"{kind}_blocked_intervals")[resource]
    assert entries[0]["start_day"] == first_blocked
    assert entries[0]["open_end"]
    windows = list(_preemptive_resource_windows(engine, config, "M1", "T1", 0, 10, set()))
    assert windows
    assert all(day < first_blocked for day, *_rest in windows)
    assert config == before
    first_projection = copy.deepcopy(engine)
    apply_calendars(engine, config)
    assert engine == first_projection


@pytest.mark.parametrize("kind,resource", [("machine", "M1"), ("tool", "T1"), ("operator", None)])
def test_overtime_reprojects_persistent_resource_and_operator_intervals(kind, resource):
    engine = _engine()
    config = FactoryConfig(shifts=[ShiftConfig("A", 480, 720), ShiftConfig("B", 780, 1020)])
    entry = {
        "id": "late", "start_at": "2026-03-02T16:00+00:00",
        "end_at": "2026-03-02T19:00+00:00",
    }
    entry.update({"group": "Grandes", "shift": "B", "count": 1} if kind == "operator" else {"resource": resource})
    setattr(config, f"{kind}_unavailability", [entry])
    apply_calendars(engine, config)
    apply_mutation(engine, "machine_down", {"machine_id": "M1", "day_idx": 2}, config)
    apply_mutation(engine, "tool_down", {"tool_id": "T1", "day_idx": 3}, config)
    apply_mutation(engine, "operator_shortage", {"group": "Grandes", "shift": "A", "count": 1, "day_idx": 4}, config)
    apply_mutation(engine, "add_holiday", {"day_idx": 1}, config)
    apply_mutation(engine, "remove_holiday", {"day_idx": 5}, config)
    apply_mutation(engine, "overtime", {"extra_min": 60}, config)
    intervals = engine.operator_blocked_intervals if kind == "operator" else getattr(engine, f"{kind}_blocked_intervals")[resource]
    persistent = [item for item in intervals if item["id"] == "late"]
    assert [(item["start_min"], item["end_min"]) for item in persistent] == [(960, 1080)]
    assert 2 in engine.machine_blocked_days["M1"]
    assert 3 in engine.tool_blocked_days["T1"]
    assert len([item for item in engine.operator_blocked_intervals if item["start_day"] == 4]) == 1
    assert 1 in engine.holidays and 5 not in engine.holidays
    if kind == "operator":
        assert available_operator_capacity("Grandes", "B", 0, engine, config) == config.operators[("Grandes", "B")] * 300 - 120
    else:
        capacity = available_machine_capacity if kind == "machine" else available_tool_capacity
        assert capacity(resource, 0, engine, config) == 420


@pytest.mark.parametrize("active_as_dicts", [True, False])
@pytest.mark.parametrize("overtime_first", [True, False])
def test_simulator_rebuild_preserves_active_and_combined_calendar_overlays(active_as_dicts, overtime_first):
    engine = _engine()
    config = FactoryConfig(
        shifts=[ShiftConfig("A", 480, 720), ShiftConfig("B", 780, 1020)],
        machine_unavailability=[{
            "id": "full", "resource": "M1", "start_at": "2026-03-04T08:00+00:00", "end_at": "2026-03-04T17:00+00:00",
        }],
    )
    active = [
        Mutation("machine_down", {"machine_id": "M1", "start_day": 2, "end_day": 2}),
        Mutation("tool_down", {"tool_id": "T1", "day_idx": 3}),
        Mutation("add_holiday", {"day_idx": 1}),
        Mutation("remove_holiday", {"day_idx": 5}),
        Mutation("operator_shortage", {"group": "Grandes", "shift": "B", "count": 1, "day_idx": 4}),
    ]
    apply_calendars(engine, config)
    for mutation in active:
        apply_mutation(engine, mutation.type, mutation.params, config)
    active_arg = [{"type": m.type, "params": m.params} for m in active] if active_as_dicts else active
    overtime = Mutation("overtime", {"extra_min": 60})
    stop = Mutation("machine_down", {"machine_id": "M1", "day_idx": 0})
    before = copy.deepcopy((engine, config, active_arg))
    result = simulate(engine, {}, [overtime, stop] if overtime_first else [stop, overtime], config, active_mutations=active_arg)
    changed = result.mutated_data
    assert {0, 2} <= changed.machine_blocked_days["M1"]
    assert 3 in changed.tool_blocked_days["T1"]
    assert 1 in changed.holidays and 5 not in changed.holidays
    operator_blocks = [item for item in changed.operator_blocked_intervals if item["start_day"] == 4]
    assert len(operator_blocks) == 1
    assert (operator_blocks[0]["start_min"], operator_blocks[0]["end_min"]) == (780, 1080)
    assert (engine, config, active_arg) == before


def test_overtime_opens_time_after_a_finite_full_day_stop():
    engine = _engine()
    config = FactoryConfig(
        shifts=[ShiftConfig("A", 480, 1020)],
        machine_unavailability=[{
            "id": "finite", "resource": "M1", "start_at": "2026-03-02T08:00+00:00", "end_at": "2026-03-02T17:00+00:00",
        }],
    )
    apply_calendars(engine, config)
    assert available_machine_capacity("M1", 0, engine, config) == 0
    apply_mutation(engine, "overtime", {"extra_min": 60}, config)
    assert 0 not in engine.machine_blocked_days.get("M1", set())
    assert available_machine_capacity("M1", 0, engine, config) == 60


@pytest.mark.parametrize("explicit_minutes", [True, False])
@pytest.mark.parametrize("overtime_first", [True, False])
def test_operator_overlay_minutes_and_counts_survive_overtime(explicit_minutes, overtime_first):
    engine = _engine()
    config = FactoryConfig(shifts=[ShiftConfig("A", 480, 720), ShiftConfig("B", 780, 1020)])
    params = {"group": "Grandes", "shift": "B", "count": 1, "day_idx": 2}
    if explicit_minutes:
        params.update(start_min=780, end_min=1020)
    shortage = Mutation("operator_shortage", params)
    overtime = Mutation("overtime", {"extra_min": 60})
    mutations = [overtime, shortage] if overtime_first else [shortage, overtime]
    mutations.append(Mutation("rush_order", {"sku": "SKU1", "qty": 1, "deadline_day": 16}))
    result = simulate(engine, {}, mutations, config)
    assert [(b["count"], b["start_min"], b["end_min"]) for b in result.mutated_data.operator_blocked_intervals] == [(1, 780, 1020 if explicit_minutes else 1080)]


def test_overtime_revalidates_whole_shift_absence_against_new_persistent_overlap():
    engine = _engine()
    config = FactoryConfig(
        shifts=[ShiftConfig("A", 480, 720), ShiftConfig("B", 780, 1020)],
        operators={("Grandes", "A"): 3, ("Grandes", "B"): 3},
        operator_unavailability=[{
            "id": "late", "group": "Grandes", "shift": "B", "count": 1,
            "start_at": "2026-03-02T17:00+00:00", "end_at": "2026-03-02T18:00+00:00",
        }],
    )
    apply_calendars(engine, config)
    before = copy.deepcopy((engine, config))
    with pytest.raises(ValueError, match="excedem equipa"):
        simulate(engine, {}, [
            Mutation("operator_shortage", {"group": "Grandes", "shift": "B", "count": 3, "day_idx": 0}),
            Mutation("overtime", {"extra_min": 60}),
        ], config)
    assert (engine, config) == before


def test_first_whatif_holiday_does_not_become_the_persistent_calendar_baseline():
    engine = _engine()
    config = FactoryConfig(shifts=[ShiftConfig("A", 480, 1020)])
    original_holidays = list(engine.holidays)
    apply_mutation(engine, "add_holiday", {"day_idx": 1}, config)
    apply_mutation(engine, "overtime", {"extra_min": 60}, config)
    assert 1 in engine.holidays
    assert engine.calendar_base_holidays == original_holidays
    apply_calendars(engine, config)
    assert engine.holidays == original_holidays
