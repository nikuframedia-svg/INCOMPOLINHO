"""C14: projection cost must not normalize the full input per entry."""

from unittest.mock import patch
import copy

from backend.config.types import FactoryConfig
from backend.transform import calendars
from tests.test_plans import _engine


def test_calendar_normalization_is_linear():
    data = _engine()
    config = FactoryConfig()
    config.machine_unavailability = [
        {"id": str(i), "resource": "M1", "start_at": "2026-03-17T08:00", "end_at": "2026-03-17T09:00"}
        for i in range(30)
    ]
    with patch.object(calendars, "_canonical_entry", wraps=calendars._canonical_entry) as normalize:
        calendars.apply_calendars(data, config)
    assert normalize.call_count <= 2 * len(config.machine_unavailability)


def test_future_outage_does_not_materialize_intervening_empty_days():
    data = _engine()
    entry = {"resource": "M1", "start_at": "2036-03-17T08:00", "end_at": "2036-03-17T09:00"}
    days = calendars._timeline_days([entry], data, "Europe/Lisbon", operators=False, kind="machine")
    assert len(days) <= len(data.workdays) + 2


def test_long_outage_is_projected_lazily_and_extension_keeps_overlays():
    from backend.calendar import available_machine_capacity

    data = _engine()
    config = FactoryConfig(machine_unavailability=[{"resource": "M1", "start_at": "2026-03-20T08:00", "end_at": "2036-03-17T09:00"}])
    calendars.apply_calendars(data, config)
    before = copy.deepcopy(data)
    assert len(data.machine_blocked_intervals["M1"]) < 12
    data.machine_blocked_days.setdefault("OTHER", set()).add(3)
    extended = calendars.calendar_window(data, config, 15)
    assert 3 in extended.machine_blocked_days["OTHER"]
    assert 12 in extended.machine_blocked_days["M1"]
    assert available_machine_capacity("M1", 12, data, config) == 0
    assert data.machine_blocked_intervals == before.machine_blocked_intervals


def test_operator_extension_does_not_duplicate_boundary_absences():
    from backend.scheduler.operators import operator_peaks

    data = _engine()
    config = FactoryConfig(operator_unavailability=[{"id": "absent", "group": "Grandes", "shift": "A", "count": 3,
                                                   "start_at": "2026-03-20T00:00", "end_at": "2026-04-01T23:59"}])
    calendars.apply_calendars(data, config)
    extended = calendars.calendar_window(data, config, 15)
    again = calendars.calendar_window(extended, config, 18)
    peak = operator_peaks([], again, config, include_keys={(4, "Grandes", "A")})[(4, "Grandes", "A")]
    assert peak.available == config.operators[("Grandes", "A")] - 3


def test_buffered_horizon_projects_dates_on_original_calendar():
    from backend.calendar import available_machine_capacity, is_factory_workday
    from backend.scheduler.scheduler import _shift_engine_data

    data = _engine()
    data.workdays = ["2026-09-21", "2026-09-22", "2026-09-23"]
    data.n_days, data.holidays = 3, []
    config = FactoryConfig(machine_unavailability=[
        {"resource": "M1", "start_at": "2026-09-24T00:00", "end_at": "2026-10-08T00:00"},
    ])
    calendars.apply_calendars(data, config)
    shifted = _shift_engine_data(data, 2)
    # Oct 7 is day 16 in the original timeline, day 18 while buffered.
    assert available_machine_capacity("M1", 18, shifted, config) == 0
    assert not is_factory_workday(7, shifted, config)  # Sep 26, Saturday.
    restored = _shift_engine_data(shifted, -2)
    assert available_machine_capacity("M1", 16, restored, config) == 0
    assert data.calendar_projection_end == 2
