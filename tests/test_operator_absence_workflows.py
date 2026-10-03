"""Versioned example and independent interval oracle for the absence workflow."""

from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.plans.serialize import deserialize_snapshot, serialize_result_snapshot
from backend.scheduler.operators import operator_peaks
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.validation import validate_plan
from backend.transform.calendars import apply_calendars
from backend.types import EOp, EngineData, MachineInfo

FIXTURE = Path(__file__).parent / "fixtures/operator_absence_2026-09-21.json"


def operator_absence_case(*, with_absences=False, renamed=False):
    case = json.loads(FIXTURE.read_text())
    machines = [f"RENAMED-{i}" for i in range(4)] if renamed else case["machines"]
    first = date.fromisoformat(case["first_day"])
    dates = [first + timedelta(days=i) for i in range(case["n_days"])]
    config = FactoryConfig(
        machines={mid: MachineConfig(mid, "Grandes") for mid in machines},
        oee_default=case["oee"],
        operators={("Grandes", shift): count for shift, count in case["operators"].items()},
        setup_crews_by_group={"Grandes": case["setup_crews"]},
        operator_unavailability=[
            {"id": f"absence-{shift}", "group": "Grandes", "shift": shift,
             **case["absence"], "category": "Outra", "reason": "Regressao de operadores"}
            for shift in ("A", "B")
        ] if with_absences else [],
    )
    demand = case["demand"]
    data = EngineData(
        ops=[EOp(id=f"OP-{i}", sku=f"SKU-{i}", client="C", designation="Absence fixture",
                 m=mid, t=f"TOOL-{i}", pH=demand["pieces_per_hour"], sH=.5, operators=1,
                 eco_lot=0, eco_lot_isop=0, eco_lot_effective=0,
                 alt=None, stk=0, backlog=0, oee=case["oee"], wip=0,
                 d=[demand["qty_per_machine"] if day == demand["day"] else 0
                    for day in range(case["n_days"])]) for i, mid in enumerate(machines)],
        machines=[MachineInfo(mid, "Grandes", config.day_capacity_min) for mid in machines],
        twin_groups=[], client_demands={}, n_days=case["n_days"],
        holidays=[i for i, day in enumerate(dates) if day.weekday() >= 5],
        workdays=[day.isoformat() for day in dates],
    )
    apply_calendars(data, config)
    return case, data, config


def simultaneous_machines(segments, config):
    """Sweep exact physical boundaries, independent of operator_peaks."""
    peaks = {}
    for shift in config.shifts:
        for day in {s.day_idx for s in segments}:
            events = {}
            for segment in segments:
                if segment.day_idx != day or segment.prod_min <= 0:
                    continue
                start = max(segment.production_start_min, shift.start_min)
                end = min(segment.end_min, shift.end_min)
                if start >= end:
                    continue
                events.setdefault(start, []).append((segment.machine_id, 1))
                events.setdefault(end, []).append((segment.machine_id, -1))
            counts = {}
            peak = 0
            for minute in sorted(events):
                for mid, delta in events[minute]:
                    counts[mid] = counts.get(mid, 0) + delta
                peak = max(peak, sum(count > 0 for count in counts.values()))
            peaks[day, shift.id] = peak
    return peaks


@pytest.mark.parametrize("renamed", [False, True])
def test_versioned_operator_absences_survive_restart_and_release_both_shifts(renamed):
    case, data, config = operator_absence_case(with_absences=True, renamed=renamed)
    original = copy.deepcopy((data, config))
    restricted = schedule_all(data, config=config)
    assert not validate_plan(restricted.segments, data, config, lots=restricted.lots)
    actual = simultaneous_machines(restricted.segments, config)
    for (day, shift), peak in actual.items():
        if 4 <= day <= 10:
            assert peak <= case["expected"]["restricted"][shift]
    assert max(v for (day, shift), v in actual.items() if 4 <= day <= 8 and shift == "A") == 3
    assert max(v for (day, shift), v in actual.items() if 4 <= day <= 8 and shift == "B") == 2
    model = operator_peaks(restricted.segments, data, config)
    assert all(peak.deficit == 0 for peak in model.values())
    assert (data, config) == original

    restored = deserialize_snapshot(serialize_result_snapshot(data, config, restricted, plan_revision=1))
    data, config = restored["engine_data"], restored["config"]
    config.operator_unavailability = []
    apply_calendars(data, config)
    released = schedule_all(data, config=config)
    assert not validate_plan(released.segments, data, config, lots=released.lots)
    assert not data.operator_blocked_intervals
    assert sum(s.qty for s in released.segments) == 4 * case["demand"]["qty_per_machine"]
    actual = simultaneous_machines(released.segments, config)
    assert max(actual.values()) == case["expected"]["released"]

    restarted = deserialize_snapshot(serialize_result_snapshot(data, config, released, plan_revision=2))
    apply_calendars(restarted["engine_data"], restarted["config"])
    assert not restarted["engine_data"].operator_blocked_intervals
    assert simultaneous_machines(restarted["result"].segments, restarted["config"]) == actual
