"""A removed absence must not survive a replan or a persisted restart."""

from datetime import date, timedelta

from backend.config.types import FactoryConfig, MachineConfig
from backend.plans.serialize import deserialize_snapshot, serialize_result_snapshot
from backend.scheduler.operators import operator_peaks
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.validation import validate_plan
from backend.transform.calendars import apply_calendars
from backend.types import EOp, EngineData, MachineInfo


def test_grandes_three_two_limits_then_four_machines_after_removal_and_restart():
    machines = [f"M{i}" for i in range(4)]
    config = FactoryConfig(
        machines={mid: MachineConfig(mid, "Grandes") for mid in machines},
        oee_default=1,
        operators={("Grandes", "A"): 6, ("Grandes", "B"): 5},
        setup_crews_by_group={"Grandes": 4},
        operator_unavailability=[
            {"id": shift, "group": "Grandes", "shift": shift, "count": 3,
             "start_at": "2026-09-21T00:00:00+01:00",
             "end_at": "2026-09-27T23:59:00+01:00"}
            for shift in ("A", "B")
        ],
    )
    data = EngineData(
        ops=[EOp(id=f"OP{i}", sku=f"SKU{i}", client="C", designation="Test",
                 m=mid, t=f"T{i}", pH=60, sH=.5, operators=1, eco_lot=0,
                 alt=None, stk=0, backlog=0, d=[0, 0, 0, 0, 1500, 0, 0],
                 oee=1, wip=0) for i, mid in enumerate(machines)],
        machines=[MachineInfo(mid, "Grandes", 1020) for mid in machines],
        twin_groups=[], client_demands={}, n_days=7, holidays=[5, 6],
        workdays=[(date(2026, 9, 21) + timedelta(days=i)).isoformat() for i in range(7)],
    )
    apply_calendars(data, config)
    constrained = schedule_all(data, config=config)
    assert not validate_plan(constrained.segments, data, config, lots=constrained.lots)
    peaks = operator_peaks(constrained.segments, data, config)
    assert peaks
    for (day, _, shift), peak in peaks.items():
        if day < 7:
            assert peak.peak_required <= (3 if shift == "A" else 2)

    restored = deserialize_snapshot(serialize_result_snapshot(data, config, constrained, plan_revision=1))
    data, config = restored["engine_data"], restored["config"]
    config.operator_unavailability = []
    apply_calendars(data, config)
    assert not data.operator_blocked_intervals
    released = schedule_all(data, config=config)
    assert not validate_plan(released.segments, data, config, lots=released.lots)
    assert released.score["missing_qty"] == 0
    assert max(peak.peak_required for peak in operator_peaks(released.segments, data, config).values()) == 4

    restarted = deserialize_snapshot(serialize_result_snapshot(data, config, released, plan_revision=2))
    data, config = restarted["engine_data"], restarted["config"]
    apply_calendars(data, config)
    replanned = schedule_all(data, config=config)
    assert not config.operator_unavailability
    assert not data.operator_blocked_intervals
    assert max(peak.peak_required for peak in operator_peaks(replanned.segments, data, config).values()) == 4
    assert not validate_plan(replanned.segments, data, config, lots=replanned.lots)
