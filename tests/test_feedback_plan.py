"""Acceptance-level regressions for the July 2026 industrial feedback."""

from __future__ import annotations

import copy
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.api.copilot import app
from backend.config.planning import effective_internal_deadline_for_op
from backend.config.types import FactoryConfig, MachineConfig
from backend.copilot.state import CopilotState, state
from backend.current_state import (
    all_machines_free,
    apply_current_states,
    validate_current_states,
)
from backend.plans.serialize import deserialize_snapshot, serialize_snapshot
from backend.plans.store import PlansStore
from backend.replan.jobs import ReplanJobManager, ReplanJobStore
from backend.scheduler.gates import build_gate_report
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.operators import compute_operator_alerts
from backend.scheduler.scheduler import (
    _accept_setup_parallelization,
    _parallelize_independent_setup_starts,
    _repair_hard_constraints,
    _serialize_crew_setups,
    schedule_all,
)
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.scheduler.validation import PlanValidationError, assert_plan_valid, validate_plan
from backend.transform.calendars import apply_calendars
from backend.types import CurrentMachineState, EOp, EngineData, MachineInfo
from backend.simulator.simulator import DeltaReport


def _op(
    *,
    op_id: str = "T1_M1_SKU1",
    sku: str = "SKU1",
    machine: str = "M1",
    tool: str = "T1",
    operators: int = 1,
    demand: list[int] | None = None,
    oee: float = 0.5,
    setup_hours: float = 0.5,
) -> EOp:
    return EOp(
        id=op_id,
        sku=sku,
        client="Cliente",
        designation="Peça",
        m=machine,
        t=tool,
        pH=100.0,
        sH=setup_hours,
        operators=operators,
        eco_lot=0,
        alt=None,
        stk=0,
        backlog=0,
        d=demand or [0, 100, 0],
        oee=oee,
        wip=0,
    )


def _engine(ops: list[EOp] | None = None, machines: list[MachineInfo] | None = None):
    return EngineData(
        ops=ops or [_op()],
        machines=machines or [MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[],
        client_demands={},
        workdays=["2026-07-23", "2026-07-24", "2026-07-27"],
        n_days=3,
        holidays=[],
    )


def _segment(
    *,
    lot_id: str,
    machine: str,
    tool: str,
    start: int = 420,
    end: int = 480,
    setup: float = 30,
    qty: int = 100,
    sku: str = "SKU1",
    twin_outputs=None,
) -> Segment:
    return Segment(
        lot_id=lot_id,
        run_id=f"run-{lot_id}",
        machine_id=machine,
        tool_id=tool,
        day_idx=0,
        start_min=start,
        end_min=end,
        shift="A",
        qty=qty,
        prod_min=float(end - start - setup),
        setup_min=setup,
        edd=1,
        sku=sku,
        twin_outputs=twin_outputs,
    )


def test_manual_state_requires_every_active_machine():
    data = _engine(
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Medias", day_capacity=1020),
        ]
    )
    try:
        validate_current_states([{"machine_id": "M1", "status": "livre"}], data, FactoryConfig())
    except ValueError as exc:
        assert "M2" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("A missing active machine must be rejected")


@pytest.mark.parametrize("raw_states", [{"M1": "idle"}, ["idle"]])
def test_manual_state_rejects_malformed_payloads(raw_states):
    with pytest.raises(ValueError, match="lista|posição"):
        validate_current_states(raw_states, _engine(), FactoryConfig())


def test_manual_state_rejects_one_physical_tool_on_two_machines():
    data = _engine(
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Grandes", day_capacity=1020),
        ]
    )
    with pytest.raises(ValueError, match="T1.*M1.*M2"):
        validate_current_states(
            [
                {
                    "machine_id": "M1",
                    "status": "setup",
                    "tool": "T1",
                    "expected_end": "2026-07-23T09:00:00+01:00",
                },
                {
                    "machine_id": "M2",
                    "status": "ensaio",
                    "tool": "T1",
                    "expected_end": "2026-07-23T10:00:00+01:00",
                },
            ],
            data,
            FactoryConfig(),
        )


def test_current_production_remains_demand_until_its_eta():
    data = _engine(ops=[_op(demand=[0, 100, 0])])
    states, warnings = validate_current_states(
        [
            {
                "machine_id": "M1",
                "status": "a produzir",
                "sku": "SKU1",
                "tool": "T1",
                "remaining_qty": 60,
                "expected_end": "2026-07-23T09:00:00+01:00",
            }
        ],
        data,
        FactoryConfig(),
    )
    apply_current_states(data, states)
    assert data.ops[0].d == [0, 100, 0]
    assert len(data.committed_supplies) == 1
    assert data.committed_supplies[0].qty == 60
    assert data.committed_supplies[0].available_day == 0
    lots = create_lots(data, FactoryConfig())
    assert sum(lot.qty for lot in lots) == 40
    assert data.current_machine_states[0].status == "producing"
    assert warnings  # informed ETA intentionally differs from pH/OEE duration

    apply_calendars(data, FactoryConfig())
    assert data.machine_blocked_intervals["M1"]
    assert data.tool_blocked_intervals["T1"]


def test_current_production_after_demand_deadline_is_not_credited_early():
    data = _engine(ops=[_op(demand=[100, 0, 0])])
    states, _warnings = validate_current_states(
        [
            {
                "machine_id": "M1",
                "status": "a produzir",
                "sku": "SKU1",
                "tool": "T1",
                "remaining_qty": 60,
                "expected_end": "2026-07-27T09:00:00+01:00",
            }
        ],
        data,
        FactoryConfig(),
    )
    apply_current_states(data, states)

    assert data.committed_supplies[0].available_day == 2
    assert sum(lot.qty for lot in create_lots(data, FactoryConfig())) == 100


def test_current_state_rejects_eta_before_horizon_start():
    data = _engine()
    with pytest.raises(ValueError, match="posterior ao início do horizonte"):
        validate_current_states(
            [
                {
                    "machine_id": "M1",
                    "status": "a produzir",
                    "sku": "SKU1",
                    "tool": "T1",
                    "remaining_qty": 60,
                    "expected_end": "2026-07-23T06:59:00+01:00",
                }
            ],
            data,
            FactoryConfig(),
        )


def test_explicit_all_free_covers_every_machine():
    data = _engine(
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Medias", day_capacity=1020),
        ]
    )
    assert [(item.machine_id, item.status) for item in all_machines_free(data)] == [
        ("M1", "idle"),
        ("M2", "idle"),
    ]


def test_open_machine_breakdown_blocks_to_end_of_horizon():
    data = _engine()
    data.current_machine_states = [
        CurrentMachineState(machine_id="M1", status="down", note="Sem previsão")
    ]
    apply_calendars(data, FactoryConfig())
    intervals = data.machine_blocked_intervals["M1"]
    assert {item["start_day"] for item in intervals} == {0, 1, 2}
    assert intervals[-1]["end_min"] == 1440


def test_exact_unavailability_only_blocks_the_overlapping_hours():
    data = _engine()
    data.machine_blocked_intervals = {"M1": [{"start_day": 0, "start_min": 600, "end_min": 720}]}
    before = _segment(lot_id="before", machine="M1", tool="T1", start=540, end=600, setup=0)
    during = _segment(lot_id="during", machine="M1", tool="T2", start=660, end=720, setup=0)
    assert not [item for item in validate_plan([before], data) if item["kind"] == "machine_down"]
    assert [item for item in validate_plan([during], data) if item["kind"] == "machine_down"]


def test_setup_crews_are_independent_between_grandes_and_medias():
    config = FactoryConfig()
    config.machines = {
        "PRM031": MachineConfig(id="PRM031", group="Grandes"),
        "PRM039": MachineConfig(id="PRM039", group="Grandes"),
        "PRM042": MachineConfig(id="PRM042", group="Medias"),
    }
    grande = _segment(lot_id="g1", machine="PRM031", tool="TG")
    media = _segment(lot_id="m1", machine="PRM042", tool="TM")
    second_grande = _segment(lot_id="g2", machine="PRM039", tool="TG2")

    cross_group = validate_plan([grande, media], config=config)
    same_group = validate_plan([grande, second_grande], config=config)
    assert not [item for item in cross_group if item["kind"] == "setup_crew_overlap"]
    assert len([item for item in same_group if item["kind"] == "setup_crew_overlap"]) == 1


def test_setup_crew_sweep_line_supports_capacity_above_one():
    config = FactoryConfig()
    config.machines = {
        machine_id: MachineConfig(id=machine_id, group="Grandes")
        for machine_id in ("M1", "M2", "M3")
    }
    config.setup_crews_by_group["Grandes"] = 2
    first = _segment(lot_id="s1", machine="M1", tool="T1")
    second = _segment(lot_id="s2", machine="M2", tool="T2")
    third = _segment(lot_id="s3", machine="M3", tool="T3")

    assert not [
        item
        for item in validate_plan([first, second], config=config)
        if item["kind"] == "setup_crew_overlap"
    ]
    violations = [
        item
        for item in validate_plan([first, second, third], config=config)
        if item["kind"] == "setup_crew_overlap"
    ]
    assert len(violations) == 1
    assert violations[0]["setup_capacity"] == 2
    assert violations[0]["setup_demand"] == 3


def test_setup_parallelization_pulls_first_day_block_when_run_continues_later():
    config = FactoryConfig()
    config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
    first = _segment(
        lot_id="l1",
        machine="M1",
        tool="T1",
        start=431,
        end=930,
        setup=60,
    )
    same_day_continuation = _segment(
        lot_id="l1",
        machine="M1",
        tool="T1",
        start=930,
        end=1440,
        setup=0,
    )
    later_continuation = _segment(
        lot_id="l2",
        machine="M1",
        tool="T1",
        start=420,
        end=930,
        setup=0,
    )
    for segment in (first, same_day_continuation, later_continuation):
        segment.run_id = "run1"
    later_continuation.day_idx = 1

    result = _parallelize_independent_setup_starts(
        [first, same_day_continuation, later_continuation],
        config,
    )

    assert result[0].start_min == 420
    assert result[0].end_min == 919
    assert result[1].start_min == 919
    assert result[1].end_min == 1429
    assert result[2].day_idx == 1
    assert result[2].start_min == 420
    assert result[2].end_min == 930


def test_setup_parallelization_uses_earliest_crew_slot_after_blocker():
    config = FactoryConfig()
    config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes"),
        "M2": MachineConfig(id="M2", group="Grandes"),
    }
    blocker = _segment(
        lot_id="blocker",
        machine="M1",
        tool="T1",
        start=420,
        end=930,
        setup=60,
    )
    target = _segment(
        lot_id="target",
        machine="M2",
        tool="T2",
        start=491,
        end=930,
        setup=30,
    )
    continuation = _segment(
        lot_id="target",
        machine="M2",
        tool="T2",
        start=930,
        end=1103,
        setup=0,
    )
    target.run_id = "target-run"
    continuation.run_id = "target-run"

    result = _parallelize_independent_setup_starts(
        [blocker, target, continuation],
        config,
    )

    assert result[1].start_min == 480
    assert result[1].end_min == 919
    assert result[2].start_min == 919
    assert result[2].end_min == 1092


def test_setup_repair_respects_group_capacity_above_one():
    config = FactoryConfig()
    config.machines = {
        machine_id: MachineConfig(id=machine_id, group="Grandes")
        for machine_id in ("M1", "M2", "M3")
    }
    config.setup_crews_by_group["Grandes"] = 2
    segments = [
        _segment(lot_id="s1", machine="M1", tool="T1"),
        _segment(lot_id="s2", machine="M2", tool="T2"),
        _segment(lot_id="s3", machine="M3", tool="T3"),
    ]

    repaired = _serialize_crew_setups(segments, config=config, holidays=set())
    violations = [
        item
        for item in validate_plan(repaired, config=config)
        if item["kind"] == "setup_crew_overlap"
    ]

    assert violations == []
    assert sum(1 for item in repaired if item.start_min == 420) == 2


def test_final_hard_repair_respects_setup_capacity_above_one():
    config = FactoryConfig()
    config.machines = {
        machine_id: MachineConfig(id=machine_id, group="Grandes")
        for machine_id in ("M1", "M2", "M3")
    }
    config.setup_crews_by_group["Grandes"] = 2
    data = _engine(
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Grandes", day_capacity=1020),
            MachineInfo(id="M3", group="Grandes", day_capacity=1020),
        ]
    )
    segments = [
        _segment(lot_id="s1", machine="M1", tool="T1"),
        _segment(lot_id="s2", machine="M2", tool="T2"),
        _segment(lot_id="s3", machine="M3", tool="T3"),
    ]

    repaired = _repair_hard_constraints(segments, data, config, set())
    violations = [
        item
        for item in validate_plan(repaired, data, config)
        if item["kind"] == "setup_crew_overlap"
    ]

    assert violations == []
    assert sum(1 for item in repaired if item.start_min == 420) == 2


def test_setup_parallelization_pulls_independent_group_into_idle_gap():
    config = FactoryConfig()
    config.machines = {
        "G1": MachineConfig(id="G1", group="Grandes"),
        "M1": MachineConfig(id="M1", group="Medias"),
    }
    grande = _segment(lot_id="g1", machine="G1", tool="TG", start=420, end=600, setup=60)
    media = _segment(lot_id="m1", machine="M1", tool="TM", start=480, end=660, setup=60)

    repaired = _parallelize_independent_setup_starts([grande, media], config=config)

    assert repaired[1].start_min == 420
    assert repaired[1].end_min == 600
    assert not validate_plan(repaired, config=config)


def test_setup_parallelization_accepts_earlier_legal_production():
    """Earlier work inside the material window is an operational improvement."""

    before = {
        "tardy_count": 0,
        "hard_violations": 0,
        "early_window_violations": 0,
        "latest_start_gap_avg_min": 20,
    }
    after = {
        **before,
        # Pulling the setup earlier increases the distance to the latest
        # permissible start, but does not violate the material-release rule.
        "latest_start_gap_avg_min": 80,
    }

    assert _accept_setup_parallelization(
        before,
        after,
        before_tool_conflicts=0,
        after_tool_conflicts=0,
    )


def test_zero_slack_repair_accepts_earlier_legal_production():
    from backend.scheduler.scheduler import _accept_zero_slack_repair

    before = {
        "hard_violations": 0,
        "early_window_violations": 0,
        "setup_crew_overlaps": 0,
        "setups": 5,
        "setup_time_min": 150,
        "latest_start_gap_avg_min": 120,
    }
    after = {
        **before,
        # The legal earlier start has a larger gap to its last legal start.
        "latest_start_gap_avg_min": 420,
    }

    assert _accept_zero_slack_repair(before, after)


def test_setup_parallelization_respects_machine_occupancy():
    config = FactoryConfig()
    config.machines = {"M1": MachineConfig(id="M1", group="Medias")}
    current = _segment(lot_id="busy", machine="M1", tool="T0", start=420, end=480, setup=0)
    setup = _segment(lot_id="next", machine="M1", tool="T1", start=540, end=660, setup=30)

    repaired = _parallelize_independent_setup_starts([current, setup], config=config)

    assert repaired[1].start_min == 480
    assert repaired[1].end_min == 600
    assert not validate_plan(repaired, config=config)


def test_setup_parallelization_does_not_create_shared_tool_conflict():
    config = FactoryConfig()
    config.machines = {
        "G1": MachineConfig(id="G1", group="Grandes"),
        "M1": MachineConfig(id="M1", group="Medias"),
    }
    tool_in_use = _segment(
        lot_id="tool-in-use",
        machine="G1",
        tool="T_SHARED",
        start=420,
        end=540,
        setup=0,
    )
    setup = _segment(
        lot_id="target",
        machine="M1",
        tool="T_SHARED",
        start=600,
        end=780,
        setup=60,
    )

    repaired = _parallelize_independent_setup_starts([tool_in_use, setup], config=config)

    assert repaired[1].start_min == 600
    assert not validate_plan(repaired, config=config)


def test_partial_operator_unavailability_is_checked_only_during_overlap():
    op = _op(operators=2)
    data = _engine(ops=[op])
    config = FactoryConfig()
    config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
    config.operators[("Grandes", "A")] = 2
    production = _segment(
        lot_id="operators",
        machine="M1",
        tool="T1",
        start=420,
        end=600,
        setup=0,
    )
    data.operator_blocked_intervals = [
        {
            "id": "absence",
            "group": "Grandes",
            "shift": "A",
            "start_day": 0,
            "start_min": 500,
            "end_min": 550,
            "count": 1,
        }
    ]

    alerts = compute_operator_alerts([production], data, config)
    assert len(alerts) == 1
    assert (alerts[0].required, alerts[0].available) == (2, 1)

    data.operator_blocked_intervals[0].update(start_min=600, end_min=650)
    assert compute_operator_alerts([production], data, config) == []


def test_operator_shortage_blocks_plan_application():
    op = _op(operators=2, oee=1 / 3, setup_hours=0)
    data = _engine(ops=[op])
    config = FactoryConfig()
    config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
    config.operators[("Grandes", "A")] = 1
    production = _segment(
        lot_id="operators",
        machine="M1",
        tool="T1",
        start=420,
        end=600,
        setup=0,
    )
    lot = Lot(
        id="operators",
        op_id=op.id,
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=180,
        setup_min=0,
        edd=1,
        is_twin=False,
    )

    assert [
        item
        for item in validate_plan([production], data, config)
        if item["kind"] == "operator_capacity"
    ]
    report = build_gate_report(
        [production],
        [lot],
        {
            "otd": 100,
            "otd_d": 100,
            "tardy_count": 0,
            "otd_d_failures": 0,
            "early_window_violations": 0,
        },
        data,
        config,
    )

    assert report["metrics"]["operator_capacity_violations"] == 1
    assert report["physical_gate_passed"] is False
    assert report["operator_capacity_gate_passed"] is False
    assert "operator_capacity_shortage" in report["approval_reasons"]
    assert report["apply_decision"] == "blocked"
    assert report["status"] == "invalid_physics"

    with pytest.raises(PlanValidationError):
        assert_plan_valid([production], data, config, lots=[lot])

    score = compute_score([production], [lot], data, config)
    assert score["operator_capacity_violations"] == 1
    assert score["hard_violations"] == 1


def test_setup_minutes_do_not_consume_production_operator_capacity():
    op = _op(operators=2)
    data = _engine(ops=[op])
    config = FactoryConfig()
    config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes"),
        "M2": MachineConfig(id="M2", group="Grandes"),
    }
    config.machine_groups.update({"M1": "Grandes", "M2": "Grandes"})
    config.operators[("Grandes", "A")] = 2
    setup_then_production = _segment(
        lot_id="setup_then_production",
        machine="M1",
        tool="T1",
        start=420,
        end=600,
        setup=60,
    )
    simultaneous_production = _segment(
        lot_id="simultaneous_production",
        machine="M2",
        tool="T2",
        start=420,
        end=480,
        setup=0,
    )

    alerts = compute_operator_alerts(
        [setup_then_production, simultaneous_production],
        data,
        config,
    )

    assert alerts == []


def test_inactive_machine_segments_remain_hard_blockers():
    data = _engine()
    config = FactoryConfig()
    config.machines = {"M1": MachineConfig(id="M1", group="Grandes", active=False)}
    production = _segment(
        lot_id="inactive",
        machine="M1",
        tool="T1",
        start=420,
        end=600,
        setup=0,
    )

    violations = validate_plan([production], data, config)

    assert [item for item in violations if item["kind"] == "machine_down"]


def test_twin_operator_demand_uses_maximum_then_sums_simultaneous_work():
    ops = [
        _op(op_id="OP1", machine="M1", tool="T1", operators=2),
        _op(op_id="OP2", sku="SKU2", machine="M1", tool="T1", operators=3),
        _op(op_id="OP3", sku="SKU3", machine="M2", tool="T2", operators=2),
    ]
    data = _engine(
        ops=ops,
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Grandes", day_capacity=1020),
        ],
    )
    config = FactoryConfig()
    config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes"),
        "M2": MachineConfig(id="M2", group="Grandes"),
    }
    config.operators[("Grandes", "A")] = 3
    twin = _segment(
        lot_id="twin",
        machine="M1",
        tool="T1",
        setup=0,
        twin_outputs=[("OP1", "SKU1", 100), ("OP2", "SKU2", 100)],
    )
    assert compute_operator_alerts([twin], data, config) == []

    simultaneous = _segment(lot_id="solo", machine="M2", tool="T2", setup=0, sku="SKU3")
    alerts = compute_operator_alerts([twin, simultaneous], data, config)
    assert len(alerts) == 1
    assert (alerts[0].required, alerts[0].available) == (5, 3)


def test_subcontract_lead_time_counts_workdays_and_holidays():
    op = SimpleNamespace(
        finish_buffer_days=0,
        subcontract_lead_time_days=5,
        subcontract_buffer_days=0,
    )
    # From D10: D9,D8,D7,D4,D3 are the five working days when D5/D6 are weekend.
    assert effective_internal_deadline_for_op(op, 10, {5, 6}) == 3
    # A holiday on D4 pushes the internal need one more day earlier.
    assert effective_internal_deadline_for_op(op, 10, {4, 5, 6}) == 2


def test_five_day_run_is_best_effort_not_invalid_physics():
    data = _engine(ops=[_op(oee=1, setup_hours=0)])
    data.ops[0].d = [0] * 10 + [500]
    lot = Lot(
        id="LONG",
        op_id="T1_M1_SKU1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=500,
        prod_min=300,
        setup_min=0,
        edd=10,
        is_twin=False,
    )
    segments = []
    for day in range(5):
        segment = _segment(
            lot_id="LONG",
            machine="M1",
            tool="T1",
            setup=0,
            qty=100,
        )
        segment.day_idx = day
        segment.edd = 10
        segments.append(segment)
    report = build_gate_report(
        segments,
        [lot],
        {
            "otd": 100,
            "otd_d": 100,
            "tardy_count": 0,
            "otd_d_failures": 0,
            "early_window_violations": 0,
        },
        data,
        FactoryConfig(max_run_days=4),
    )
    assert report["physical_gate_passed"] is True
    assert report["status"] == "best_effort"
    assert report["apply_decision"] == "approval_required"
    assert report["metrics"]["long_productions"] == 1


def test_non_consecutive_five_day_run_does_not_trigger_four_day_rule():
    data = _engine()
    data.ops[0].d = [0] * 10 + [500]
    lot = Lot(
        id="LONG",
        op_id="T1_M1_SKU1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=500,
        prod_min=300,
        setup_min=0,
        edd=10,
        is_twin=False,
    )
    segments = []
    for day in [0, 1, 2, 3, 5]:
        segment = _segment(
            lot_id="LONG",
            machine="M1",
            tool="T1",
            setup=0,
            qty=100,
        )
        segment.day_idx = day
        segment.edd = 10
        segments.append(segment)

    report = build_gate_report(
        segments,
        [lot],
        {
            "otd": 100,
            "otd_d": 100,
            "tardy_count": 0,
            "otd_d_failures": 0,
            "early_window_violations": 0,
        },
        data,
        FactoryConfig(max_run_days=4),
    )

    assert report["metrics"]["long_productions"] == 0
    assert report["long_production_detail"] == []


def test_replan_job_rejects_result_from_replaced_dataset(monkeypatch):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
    }
    store = ReplanJobStore(":memory:")
    manager = ReplanJobManager(store)
    try:
        data = _engine()
        config = FactoryConfig()
        state.engine_data = data
        state.config = config
        state.dataset_info = {"id": "new-dataset"}
        result = schedule_all(data, config=config)
        monkeypatch.setattr("backend.cpo.optimize", lambda *_args, **_kwargs: result)
        monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
        job = store.create("teste", "old-dataset")
        manager._run(
            job["id"],
            data,
            config,
            "old-dataset",
            0,
            "teste",
            {"id": "old-dataset"},
        )
        finished = store.get(job["id"])
        assert finished["status"] == "ready"
        with pytest.raises(ValueError, match="ISOP mudou"):
            manager.apply(job["id"], expected_revision=state.plan_revision)
    finally:
        manager.executor.shutdown(wait=True)
        store.conn.close()
        for key, value in previous.items():
            setattr(state, key, value)


def test_replan_keeps_comparable_baseline_when_optimizer_regresses_delivery(monkeypatch):
    source = CopilotState(engine_data=_engine(ops=[_op(oee=1, setup_hours=0)]), config=FactoryConfig())
    source.config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes"),
        "M_UNUSED": MachineConfig(id="M_UNUSED", group="Grandes"),
    }
    source.dataset_info = {
        "id": "dataset-floor",
        "filename": "isop.xlsx",
        "n_ops": 1,
    }
    lot = Lot(
        id="LOT1",
        op_id="T1_M1_SKU1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=0,
        edd=1,
        is_twin=False,
        delivery_day=1,
    )
    segment = _segment(lot_id="LOT1", machine="M1", tool="T1", setup=0)
    baseline = ScheduleResult(
        segments=[segment],
        lots=[lot],
        score={
            "otd": 100.0,
            "otd_d": 100.0,
            "tardy_count": 0,
            "otd_d_failures": 0,
            "early_window_violations": 0,
        },
        time_ms=1,
        warnings=[],
        operator_alerts=[],
    )
    source.update_schedule(baseline)
    regressed = copy.deepcopy(baseline)
    regressed.score = {
        **baseline.score,
        "otd": 90.0,
        "otd_d": 95.0,
        "tardy_count": 1,
    }
    regressed.gate_report = {
        "physical_gate_passed": True,
        "coverage_gate_passed": True,
    }
    store = ReplanJobStore(":memory:")
    manager = ReplanJobManager(store)
    try:
        monkeypatch.setattr("backend.cpo.optimize", lambda *_args, **_kwargs: regressed)
        job = store.create("recalcular", "dataset-floor", source.plan_revision)
        candidate_data = copy.deepcopy(source.engine_data)
        candidate_data.machines.append(MachineInfo("M_UNUSED", "Grandes", 1020))
        manager._run(
            job["id"],
            candidate_data,
            copy.deepcopy(source.config),
            "dataset-floor",
            source.plan_revision,
            "recalcular",
            copy.deepcopy(source.dataset_info),
            baseline_snapshot=serialize_snapshot(source),
        )

        finished = store.get(job["id"])
        assert finished["status"] == "ready"
        assert finished["result"]["baseline_comparable"] is True
        assert finished["result"]["selected_source"] == ("normalized_baseline_delivery_floor")
        assert finished["result"]["score"]["otd"] == 100.0
        assert finished["result"]["score"]["tardy_count"] == 0
    finally:
        manager.executor.shutdown(wait=True)
        store.conn.close()


def test_replan_does_not_restore_delivery_floor_that_is_physically_invalid(monkeypatch):
    source = CopilotState(engine_data=_engine(ops=[_op(operators=2, oee=1, setup_hours=0)]), config=FactoryConfig())
    source.config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
    source.config.operators[("Grandes", "A")] = 2
    source.config.operator_unavailability = [
        {
            "id": "operator-floor",
            "start_at": "2026-07-23T07:00+01:00",
            "end_at": "2026-07-23T15:30+01:00",
            "group": "Grandes",
            "shift": "A",
            "count": 1,
            "category": "Outra",
            "reason": "Teste",
        }
    ]
    apply_calendars(source.engine_data, source.config)
    source.dataset_info = {"id": "dataset-invalid-floor", "filename": "isop.xlsx"}
    lot = Lot(
        id="LOT1",
        op_id="T1_M1_SKU1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=0,
        edd=1,
        is_twin=False,
        delivery_day=1,
    )
    baseline_segment = _segment(lot_id="LOT1", machine="M1", tool="T1", setup=0)
    baseline = ScheduleResult(
        segments=[baseline_segment],
        lots=[lot],
        score={"otd": 100.0, "otd_d": 100.0, "tardy_count": 0},
        time_ms=1,
        warnings=[],
        operator_alerts=[],
    )
    source.update_schedule(baseline)
    candidate = copy.deepcopy(baseline)
    candidate.segments[0].day_idx = 1
    candidate.score = {"otd": 90.0, "otd_d": 90.0, "tardy_count": 1}
    candidate.gate_report = {
        "physical_gate_passed": True,
        "coverage_gate_passed": True,
        "apply_decision": "approval_required",
    }
    store = ReplanJobStore(":memory:")
    manager = ReplanJobManager(store)
    try:
        monkeypatch.setattr("backend.cpo.optimize", lambda *_args, **_kwargs: candidate)
        job = store.create("recalcular", "dataset-invalid-floor", source.plan_revision)
        manager._run(
            job["id"],
            copy.deepcopy(source.engine_data),
            copy.deepcopy(source.config),
            "dataset-invalid-floor",
            source.plan_revision,
            "recalcular",
            copy.deepcopy(source.dataset_info),
            baseline_snapshot=serialize_snapshot(source),
        )

        finished = store.get(job["id"])
        assert finished["status"] == "ready", finished
        assert finished["result"]["selected_source"] == "optimized"
        restored = deserialize_snapshot(store.get_candidate(job["id"]))
        result = restored["result"]
        assert validate_plan(
            baseline.segments, source.engine_data, source.config, lots=baseline.lots,
        )
        assert not validate_plan(
            result.segments, restored["engine_data"], restored["config"], lots=result.lots,
        )
        actual_score = compute_score(
            result.segments, result.lots, restored["engine_data"], restored["config"],
        )
        assert finished["result"]["score"]["otd"] == actual_score["otd"]
        assert result.segments != baseline.segments
        assert any(
            "deixou de ser uma referência válida" in warning
            for warning in finished["warnings"]
        )
    finally:
        manager.executor.shutdown(wait=True)
        store.conn.close()


def test_calendar_only_replan_reuses_valid_schedule_without_optimizer(monkeypatch):
    source = CopilotState(engine_data=_engine(ops=[_op(oee=1, setup_hours=0)]), config=FactoryConfig())
    source.config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes"),
    }
    source.config.machine_unavailability = [
        {
            "id": "expired-stop",
            "resource": "M1",
            "start_at": "2026-07-01T08:00+01:00",
            "end_at": "2026-07-01T10:00+01:00",
            "category": "Manutenção",
            "reason": "Fora do horizonte",
        }
    ]
    source.dataset_info = {
        "id": "dataset-calendar-fast-path",
        "filename": "isop.xlsx",
        "n_ops": 1,
    }
    lot = Lot(
        id="LOT1",
        op_id="T1_M1_SKU1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=0,
        edd=1,
        is_twin=False,
        delivery_day=1,
    )
    baseline = ScheduleResult(
        segments=[_segment(lot_id="LOT1", machine="M1", tool="T1", setup=0)],
        lots=[lot],
        score={"otd": 100.0, "otd_d": 100.0, "tardy_count": 0},
        time_ms=1,
        warnings=[],
        operator_alerts=[],
    )
    source.update_schedule(baseline)
    candidate_config = copy.deepcopy(source.config)
    candidate_config.machine_unavailability = []
    store = ReplanJobStore(":memory:")
    manager = ReplanJobManager(store)
    try:

        def fail_optimize(*_args, **_kwargs):
            raise AssertionError("calendar fast path must not invoke optimize")

        monkeypatch.setattr("backend.cpo.optimize", fail_optimize)
        job = store.create(
            "calendário",
            "dataset-calendar-fast-path",
            source.plan_revision,
        )
        manager._run(
            job["id"],
            copy.deepcopy(source.engine_data),
            candidate_config,
            "dataset-calendar-fast-path",
            source.plan_revision,
            "calendário",
            copy.deepcopy(source.dataset_info),
            baseline_snapshot=serialize_snapshot(source),
            prefer_unchanged_baseline=True,
            allow_unchanged_baseline_apply=True,
        )

        finished = store.get(job["id"])
        assert finished["status"] == "ready", finished
        assert finished["result"]["selected_source"] == ("unchanged_baseline_calendar_compatible")
        assert finished["result"]["n_segments"] == 1
        assert finished["result"]["unchanged_resource_relaxation"] is True
        assert finished["result"]["gate_report"]["apply_decision"] == "auto_applicable"
        assert finished["result"]["gate_report"]["configuration_only_relaxation"] is True
    finally:
        manager.executor.shutdown(wait=True)
        store.conn.close()


def test_calendar_only_replan_repairs_resource_downtime_without_optimizer(monkeypatch):
    source = CopilotState(engine_data=_engine(ops=[_op(oee=1, setup_hours=0)]), config=FactoryConfig())
    source.config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes"),
    }
    source.dataset_info = {
        "id": "dataset-calendar-fallback",
        "filename": "isop.xlsx",
        "n_ops": 1,
    }
    lot = Lot(
        id="LOT1",
        op_id="T1_M1_SKU1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=0,
        edd=1,
        is_twin=False,
        delivery_day=1,
    )
    active_segment = _segment(lot_id="LOT1", machine="M1", tool="T1", setup=0)
    baseline = ScheduleResult(
        segments=[active_segment],
        lots=[lot],
        score={"otd": 100.0, "otd_d": 100.0, "tardy_count": 0},
        time_ms=1,
        warnings=[],
        operator_alerts=[],
    )
    source.update_schedule(baseline)
    candidate_config = copy.deepcopy(source.config)
    candidate_config.machine_unavailability = [
        {
            "id": "active-stop",
            "resource": "M1",
            "start_at": "2026-07-23T07:00+01:00",
            "end_at": "2026-07-23T09:00+01:00",
            "category": "Manutenção",
            "reason": "Colide com produção",
        }
    ]
    store = ReplanJobStore(":memory:")
    manager = ReplanJobManager(store)
    try:

        def fail_optimize(*_args, **_kwargs):
            raise AssertionError("local calendar repair must not invoke optimize")

        monkeypatch.setattr("backend.cpo.optimize", fail_optimize)
        job = store.create(
            "calendário",
            "dataset-calendar-fallback",
            source.plan_revision,
        )
        manager._run(
            job["id"],
            copy.deepcopy(source.engine_data),
            candidate_config,
            "dataset-calendar-fallback",
            source.plan_revision,
            "calendário",
            copy.deepcopy(source.dataset_info),
            baseline_snapshot=serialize_snapshot(source),
            prefer_unchanged_baseline=True,
        )

        finished = store.get(job["id"])
        assert finished["status"] == "ready", finished
        assert finished["result"]["selected_source"] == ("repaired_baseline_calendar")
    finally:
        manager.executor.shutdown(wait=True)
        store.conn.close()


def test_calendar_only_replan_falls_back_when_local_repair_worsens_delivery(monkeypatch):
    source = CopilotState(engine_data=_engine(ops=[_op(oee=1, setup_hours=0)]), config=FactoryConfig())
    source.config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes"),
    }
    source.dataset_info = {
        "id": "dataset-calendar-delivery-fallback",
        "filename": "isop.xlsx",
        "n_ops": 1,
    }
    lot = Lot(
        id="LOT1",
        op_id="T1_M1_SKU1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=0,
        edd=1,
        is_twin=False,
        delivery_day=1,
    )
    baseline = ScheduleResult(
        segments=[_segment(lot_id="LOT1", machine="M1", tool="T1", setup=0)],
        lots=[lot],
        score={"otd": 100.0, "otd_d": 100.0, "tardy_count": 0},
        time_ms=1,
        warnings=[],
        operator_alerts=[],
    )
    source.update_schedule(baseline)
    candidate_config = copy.deepcopy(source.config)
    candidate_config.machine_unavailability = [
        {
            "id": "long-stop",
            "resource": "M1",
            "start_at": "2026-07-23T07:00+01:00",
            "end_at": "2026-07-28T23:00+01:00",
            "category": "Manutenção",
            "reason": "Paragem prolongada",
        }
    ]
    optimized = copy.deepcopy(baseline)
    optimized.segments[0].day_idx = 10
    store = ReplanJobStore(":memory:")
    manager = ReplanJobManager(store)
    optimize_called = False
    try:

        def fake_optimize(candidate_data, **kwargs):
            nonlocal optimize_called
            optimize_called = True
            result = copy.deepcopy(optimized)
            result.score = compute_score(
                result.segments,
                result.lots,
                candidate_data,
                config=kwargs["config"],
            )
            return result

        monkeypatch.setattr("backend.cpo.optimize", fake_optimize)
        job = store.create(
            "calendário",
            "dataset-calendar-delivery-fallback",
            source.plan_revision,
        )
        manager._run(
            job["id"],
            copy.deepcopy(source.engine_data),
            candidate_config,
            "dataset-calendar-delivery-fallback",
            source.plan_revision,
            "calendário",
            copy.deepcopy(source.dataset_info),
            baseline_snapshot=serialize_snapshot(source),
            prefer_unchanged_baseline=True,
        )

        finished = store.get(job["id"])
        assert optimize_called is True
        assert finished["status"] == "ready", finished
        assert finished["result"]["selected_source"] == "optimized"
    finally:
        manager.executor.shutdown(wait=True)
        store.conn.close()


def test_replan_preserves_started_historical_lots_exactly(monkeypatch):
    data = _engine(
        ops=[
            _op(op_id="OP_PAST", sku="PAST", demand=[100, 0, 0]),
            _op(op_id="OP_FUTURE", sku="FUTURE", demand=[0, 0, 100]),
        ]
    )
    for op in data.ops:
        op.pH = 400
    config = FactoryConfig()
    config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
    past_lot = Lot(
        id="LOT_PAST",
        op_id="OP_PAST",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=30,
        setup_min=30,
        edd=0,
        is_twin=False,
        sku="PAST",
    )
    future_lot = copy.deepcopy(past_lot)
    future_lot.id = "LOT_FUTURE"
    future_lot.op_id = "OP_FUTURE"
    future_lot.sku = "FUTURE"
    future_lot.edd = 2
    past_segment = _segment(lot_id="LOT_PAST", machine="M1", tool="T1", sku="PAST")
    future_segment = _segment(
        lot_id="LOT_FUTURE",
        machine="M1",
        tool="T1",
        sku="FUTURE",
    )
    future_segment.day_idx = 2
    baseline_segments = [past_segment, future_segment]
    baseline_lots = [past_lot, future_lot]
    source = CopilotState(engine_data=data, config=config)
    source.dataset_info = {
        "id": "dataset-history",
        "filename": "isop.xlsx",
        "n_ops": 2,
    }
    source.update_schedule(
        ScheduleResult(
            segments=baseline_segments,
            lots=baseline_lots,
            score=compute_score(baseline_segments, baseline_lots, data, config=config),
            time_ms=1,
            warnings=[],
            operator_alerts=[],
        )
    )
    changed_config = copy.deepcopy(config)
    changed_config.jit_threshold += 1
    changed_past = copy.deepcopy(past_segment)
    changed_past.day_idx = 1
    changed_past.start_min = 600
    changed_past.end_min = 660
    changed_future = copy.deepcopy(future_segment)
    changed_future.day_idx = 1
    candidate = ScheduleResult(
        segments=[changed_past, changed_future],
        lots=copy.deepcopy(baseline_lots),
        score={},
        time_ms=1,
        warnings=[],
        operator_alerts=[],
    )
    store = ReplanJobStore(":memory:")
    manager = ReplanJobManager(store)
    try:
        monkeypatch.setattr("backend.replan.jobs._current_planning_day", lambda *_args: 1)
        monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_args: 1)

        def fake_optimize(candidate_data, **_kwargs):
            assert 0 not in candidate_data.holidays
            assert 0 in candidate_data.machine_blocked_days["M1"]
            assert any(
                supply.op_id == "OP_PAST" and supply.qty == 100
                for supply in candidate_data.committed_supplies
            )
            return copy.deepcopy(candidate)

        monkeypatch.setattr("backend.cpo.optimize", fake_optimize)
        job = store.create("alteração futura", "dataset-history", source.plan_revision)
        manager._run(
            job["id"],
            copy.deepcopy(data),
            changed_config,
            "dataset-history",
            source.plan_revision,
            "alteração futura",
            copy.deepcopy(source.dataset_info),
            baseline_snapshot=serialize_snapshot(source),
        )

        finished = store.get(job["id"])
        assert finished["status"] == "ready", finished
        restored = deserialize_snapshot(store.get_candidate(job["id"]))
        preserved = [
            segment for segment in restored["result"].segments if segment.lot_id == "LOT_PAST"
        ]
        assert preserved == [past_segment]
        assert restored["engine_data"].committed_supplies == []
        assert restored["engine_data"].holidays == []
    finally:
        manager.executor.shutdown(wait=True)
        store.conn.close()


def test_replan_job_can_be_cancelled_before_application():
    store = ReplanJobStore(":memory:")
    manager = ReplanJobManager(store)
    try:
        job = store.create("teste cancelamento", "dataset-cancel")

        cancelled = manager.cancel(job["id"])

        assert cancelled["status"] == "cancelled"
        assert cancelled["message"] == "Replaneamento cancelado pelo utilizador"

        repeated = manager.cancel(job["id"])
        assert repeated == cancelled

        for status in ("running", "ready", "failed"):
            store.update(job["id"], status=status, phase=status, message=status)
            assert store.get(job["id"]) == cancelled
    finally:
        manager.executor.shutdown(wait=True)
        store.conn.close()


def test_replan_job_cancelled_during_optimize_stays_cancelled(monkeypatch):
    data = _engine()
    config = FactoryConfig()
    result = schedule_all(data, config=config)
    optimize_started = threading.Event()
    release_optimize = threading.Event()
    store = ReplanJobStore(":memory:")
    manager = ReplanJobManager(store)
    try:

        def slow_optimize(*_args, **_kwargs):
            optimize_started.set()
            assert release_optimize.wait(timeout=5)
            return copy.deepcopy(result)

        monkeypatch.setattr("backend.cpo.optimize", slow_optimize)
        job = manager.start(
            engine_data=data,
            config=config,
            dataset_id="dataset-cancel-running",
            base_revision=0,
            reason="teste cancelamento durante optimize",
        )
        assert optimize_started.wait(timeout=5)

        cancelled = manager.cancel(job["id"])
        release_optimize.set()
        manager.executor.shutdown(wait=True)

        assert cancelled["status"] == "cancelled"
        assert store.get(job["id"])["status"] == "cancelled"
    finally:
        release_optimize.set()
        manager.executor.shutdown(wait=True)
        store.conn.close()


def test_cancelled_queued_replan_never_calls_optimize(monkeypatch):
    data = _engine()
    config = FactoryConfig()
    result = schedule_all(data, config=config)
    first_optimize_started = threading.Event()
    release_first_optimize = threading.Event()
    optimize_calls = 0
    store = ReplanJobStore(":memory:")
    manager = ReplanJobManager(store)
    try:

        def blocking_optimize(*_args, **_kwargs):
            nonlocal optimize_calls
            optimize_calls += 1
            if optimize_calls > 1:
                raise AssertionError("cancelled queued job must not call optimize")
            first_optimize_started.set()
            assert release_first_optimize.wait(timeout=5)
            return copy.deepcopy(result)

        monkeypatch.setattr("backend.cpo.optimize", blocking_optimize)
        manager.start(
            engine_data=data,
            config=config,
            dataset_id="dataset-worker-a",
            base_revision=0,
            reason="job A ocupa o worker",
        )
        assert first_optimize_started.wait(timeout=5)
        job_b = manager.start(
            engine_data=data,
            config=config,
            dataset_id="dataset-worker-b",
            base_revision=0,
            reason="job B fica em fila",
        )

        manager.cancel(job_b["id"])
        release_first_optimize.set()
        manager.executor.shutdown(wait=True)

        assert optimize_calls == 1
        assert store.get(job_b["id"])["status"] == "cancelled"
    finally:
        release_first_optimize.set()
        manager.executor.shutdown(wait=True)
        store.conn.close()


def test_replan_job_rejects_jit_blocked_candidate_on_apply(monkeypatch):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
        "segments": state.segments,
        "lots": state.lots,
        "score": state.score,
        "warnings": state.warnings,
        "plan_revision": state.plan_revision,
    }
    store = ReplanJobStore(":memory:")
    manager = ReplanJobManager(store)
    try:
        data = _engine()
        config = FactoryConfig()
        config.machines = {
            "M1": MachineConfig(
                id="M1",
                group="Grandes",
                day_capacity_min=config.day_capacity_min,
            )
        }
        state.engine_data = copy.deepcopy(data)
        state.config = copy.deepcopy(config)
        data.ops[0].oee, data.ops[0].sH = 1.0, 0.0
        state.engine_data = copy.deepcopy(data)
        state.dataset_info = {"id": "dataset-jit"}
        state.plan_revision = 0
        segment = _segment(lot_id="jit", machine="M1", tool="T1", setup=0)
        lot = Lot(
            id="jit",
            op_id="T1_M1_SKU1",
            tool_id="T1",
            machine_id="M1",
            alt_machine_id=None,
            qty=100,
            prod_min=60,
            setup_min=0,
            edd=7,
            is_twin=False,
        )
        result = SimpleNamespace(
            gate_report={
                "status": "jit_window_blocked",
                "apply_decision": "blocked",
                "requires_approval": False,
                "approval_reasons": ["jit_window_blocked"],
                "physical_gate_passed": True,
                "coverage_gate_passed": True,
                "jit_window_gate_passed": False,
                "metrics": {"early_window_violations": 1},
            },
            warnings=[],
            segments=[segment],
            lots=[lot],
            score={
                "otd": 100,
                "otd_d": 100,
                "tardy_count": 0,
                "otd_d_failures": 0,
                "early_window_violations": 1,
            },
            operator_alerts=[],
            journal=None,
            solver_status="strict_feasible",
            feasibility={},
            preserved_lot_proofs=None,
            time_ms=1,
        )
        monkeypatch.setattr("backend.cpo.optimize", lambda *_args, **_kwargs: result)
        monkeypatch.setattr("backend.config.loader.save_config", lambda *_args, **_kwargs: None)
        from backend.plans.serialize import serialize_snapshot
        from backend.replan.jobs import replan_base_fingerprints

        job = store.create(
            "teste", "dataset-jit",
            base_input_fingerprints=replan_base_fingerprints(serialize_snapshot(state)),
        )
        manager._run(
            job["id"],
            copy.deepcopy(data),
            copy.deepcopy(config),
            "dataset-jit",
            0,
            "teste",
            {"id": "dataset-jit"},
        )

        finished = store.get(job["id"])
        assert finished["status"] == "ready"
        assert finished["result"]["gate_report"]["status"] == "jit_window_blocked"
        assert "antecipada" in finished["message"]
        assert "pronto para aplicar" not in finished["message"].lower()
        with pytest.raises(ValueError, match="antecipada"):
            manager.apply(
                job["id"],
                expected_revision=state.plan_revision,
                approve_exceptions=True,
                approval_reason="Tentativa de confirmação de um plano JIT inválido",
            )
        assert state.plan_revision == 0
    finally:
        manager.executor.shutdown(wait=True)
        store.conn.close()
        for key, value in previous.items():
            setattr(state, key, value)


def test_replan_api_returns_a_job_immediately(monkeypatch):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
    }
    captured = {}
    try:
        config = FactoryConfig()
        config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
        state.engine_data = _engine()
        state.config = config
        state.dataset_info = {"id": "dataset-1"}

        def fake_start(**kwargs):
            captured.update(kwargs)
            return {"id": "job-1", "status": "queued", "progress": 0}

        monkeypatch.setattr("backend.api.replan.manager.start", fake_start)
        response = TestClient(app).post(
            "/api/data/replan-jobs",
            json={
                "expected_revision": state.plan_revision,
                "reason": "OEE revisto",
                "config_updates": {
                    "machine_oee": {"M1": 0.72},
                    "machine_groups": {"M1": "Medias"},
                    "shifts": [
                        {"id": "A", "label": "Manhã", "start_min": 420, "end_min": 900},
                        {"id": "B", "label": "Tarde", "start_min": 900, "end_min": 0},
                    ],
                    "setup_crews_by_group": {"Grandes": 1, "Medias": 1},
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["job"]["status"] == "queued"
        assert captured["config"].machines["M1"].oee == 0.72
        assert captured["config"].machines["M1"].group == "Medias"
        assert captured["config"].shifts[0].end_min == 900
        assert captured["config"].shifts[1].end_min == 1440
        assert captured["config"].day_capacity_min == 1020
        assert captured["config"].machines["M1"].day_capacity_min is None
        assert captured["dataset_id"] == "dataset-1"
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


def test_replan_api_stages_machine_activity_and_tool_edits_atomically(monkeypatch):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
    }
    captured = {}
    try:
        config = FactoryConfig()
        config.machines = {
            "M1": MachineConfig(id="M1", group="Grandes"),
            "M2": MachineConfig(id="M2", group="Grandes"),
        }
        config.tools = {
            "T1": {"primary": "M1", "alt": None, "setup_hours": 0.5},
        }
        state.engine_data = _engine()
        state.config = config
        state.dataset_info = {"id": "dataset-staged-master-data"}

        def fake_start(**kwargs):
            captured.update(kwargs)
            return {"id": "job-staged", "status": "queued", "progress": 0}

        monkeypatch.setattr("backend.api.replan.manager.start", fake_start)
        response = TestClient(app).post(
            "/api/data/replan-jobs",
            json={
                "expected_revision": state.plan_revision,
                "config_updates": {
                    "machine_additions": [
                        {"id": "M3", "group": "Medias", "active": True},
                    ],
                    "tool_additions": [
                        {
                            "id": "TNEW",
                            "primary": "M3",
                            "alt": None,
                            "setup_hours": 0.5,
                        }
                    ],
                    "machine_active": {"M1": False},
                    "tool_updates": {
                        "T1": {"alt": "M2", "setup_hours": 0.75},
                    },
                },
            },
        )

        assert response.status_code == 200, response.text
        assert captured["config"].machines["M3"].active is True
        assert captured["config"].tools["TNEW"]["primary"] == "M3"
        assert captured["config"].machines["M1"].active is False
        assert captured["config"].tools["T1"]["alt"] == "M2"
        assert captured["config"].tools["T1"]["setup_hours"] == 0.75
        assert any(machine.id == "M1" for machine in captured["engine_data"].machines)
        assert any(machine.id == "M3" for machine in captured["engine_data"].machines)
        assert captured["engine_data"].ops[0].m == "M2"
        assert captured["engine_data"].ops[0].alt is None
        assert captured["engine_data"].ops[0].sH == 0.75
        assert state.config.machines["M1"].active is True
        assert state.engine_data.ops[0].sH == 0.5
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


def test_replan_api_stages_unavailability_changes_atomically(monkeypatch):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
    }
    captured = {}
    try:
        config = FactoryConfig()
        config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
        config.machine_unavailability = [
            {
                "id": "old-stop",
                "resource": "M1",
                "start_at": "2026-07-01T08:00+01:00",
                "end_at": "2026-07-01T10:00+01:00",
                "category": "Manutenção",
                "reason": "Antiga",
            }
        ]
        state.engine_data = _engine()
        state.config = config
        state.dataset_info = {"id": "dataset-calendar-stage"}

        def fake_start(**kwargs):
            captured.update(kwargs)
            return {"id": "job-calendar", "status": "queued", "progress": 0}

        monkeypatch.setattr("backend.api.replan.manager.start", fake_start)
        response = TestClient(app).post(
            "/api/data/replan-jobs",
            json={
                "expected_revision": state.plan_revision,
                "reason": "Atualizar indisponibilidades",
                "config_updates": {
                    "unavailability_removals": ["old-stop"],
                    "unavailability_additions": [
                        {
                            "kind": "machine",
                            "resource": "M1",
                            "start_at": "2026-07-24T08:00",
                            "end_at": "2026-07-24T10:00",
                            "category": "Manutenção",
                            "reason": "Nova",
                        }
                    ],
                },
            },
        )

        assert response.status_code == 200, response.text
        entries = captured["config"].machine_unavailability
        assert len(entries) == 1
        assert entries[0]["id"].startswith("u_")
        assert entries[0]["resource"] == "M1"
        assert captured["prefer_unchanged_baseline"] is False
        assert captured["allow_unchanged_baseline_apply"] is False
        assert captured["reoptimize_relaxed_baseline"] is True
        assert state.config.machine_unavailability[0]["id"] == "old-stop"
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


def test_replan_api_stages_unavailability_edits_atomically(monkeypatch):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
    }
    captured = {}
    try:
        config = FactoryConfig()
        config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
        config.machine_unavailability = [{
            "id": "stop-1",
            "resource": "M1",
            "start_at": "2026-07-01T08:00+01:00",
            "end_at": "2026-07-01T10:00+01:00",
            "category": "Manutenção",
            "reason": "Antiga",
        }]
        state.engine_data = _engine()
        state.config = config
        state.dataset_info = {"id": "dataset-calendar-edit"}

        def fake_start(**kwargs):
            captured.update(kwargs)
            return {"id": "job-calendar-edit", "status": "queued", "progress": 0}

        monkeypatch.setattr("backend.api.replan.manager.start", fake_start)
        response = TestClient(app).post(
            "/api/data/replan-jobs",
            json={
                "expected_revision": state.plan_revision,
                "reason": "Editar indisponibilidades",
                "config_updates": {
                    "unavailability_updates": [{
                        "id": "stop-1",
                        "kind": "machine",
                        "resource": "M1",
                        "start_at": "2026-07-02T09:00",
                        "end_at": "2026-07-02T12:00",
                        "category": "Avaria",
                        "reason": "Corrigida",
                    }],
                },
            },
        )

        assert response.status_code == 200, response.text
        assert captured["prefer_unchanged_baseline"] is True
        assert captured["allow_unchanged_baseline_apply"] is False
        assert captured["config"].machine_unavailability == [{
            "id": "stop-1",
            "start_at": "2026-07-02T09:00+01:00",
            "end_at": "2026-07-02T12:00+01:00",
            "category": "Avaria",
            "reason": "Corrigida",
            "resource": "M1",
        }]
        assert state.config.machine_unavailability[0]["reason"] == "Antiga"
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


def test_replan_api_rejects_duplicate_unavailability_mutations(monkeypatch):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
    }
    try:
        config = FactoryConfig()
        config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
        config.machine_unavailability = [{
            "id": "stop-1",
            "resource": "M1",
            "start_at": "2026-07-01T08:00+01:00",
            "end_at": "2026-07-01T10:00+01:00",
            "category": "Manutenção",
            "reason": "Antiga",
        }]
        state.engine_data = _engine()
        state.config = config
        state.dataset_info = {"id": "dataset-calendar-duplicate"}
        monkeypatch.setattr(
            "backend.api.replan.manager.start",
            lambda **_kwargs: pytest.fail("não deve iniciar replaneamento"),
        )

        response = TestClient(app).post(
            "/api/data/replan-jobs",
            json={
                "expected_revision": state.plan_revision,
                "config_updates": {
                    "unavailability_removals": ["stop-1"],
                    "unavailability_updates": [{"id": "stop-1", "kind": "machine"}],
                },
            },
        )

        assert response.status_code == 400, response.text
        assert "só pode ser alterada uma vez" in response.text
        assert state.config.machine_unavailability[0]["id"] == "stop-1"
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


def test_replan_api_forces_full_plan_when_operator_capacity_changes(monkeypatch):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
    }
    captured = {}
    try:
        config = FactoryConfig()
        config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
        config.operators[("Grandes", "A")] = 6
        state.engine_data = _engine()
        state.config = config
        state.dataset_info = {"id": "dataset-operator-capacity"}

        def fake_start(**kwargs):
            captured.update(kwargs)
            return {"id": "job-operators", "status": "queued", "progress": 0}

        monkeypatch.setattr("backend.api.replan.manager.start", fake_start)
        response = TestClient(app).post(
            "/api/data/replan-jobs",
            json={
                "expected_revision": state.plan_revision,
                "reason": "Registar ausência de operadores",
                "config_updates": {
                    "unavailability_additions": [
                        {
                            "kind": "operator",
                            "group": "Grandes",
                            "shift": "A",
                            "count": 3,
                            "start_at": "2026-07-23T07:00",
                            "end_at": "2026-07-24T15:30",
                            "category": "Outra",
                            "reason": "Doença",
                        }
                    ]
                },
            },
        )

        assert response.status_code == 200, response.text
        assert captured["prefer_unchanged_baseline"] is False
        assert captured["allow_unchanged_baseline_apply"] is False
        assert captured["reoptimize_relaxed_baseline"] is False
        assert captured["config"].operator_unavailability[0]["count"] == 3
        assert state.config.operator_unavailability == []
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


def test_replan_api_reoptimizes_when_operator_absence_is_removed(monkeypatch):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
    }
    captured = {}
    try:
        config = FactoryConfig()
        config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
        config.operator_unavailability = [{
            "id": "absence-a",
            "group": "Grandes",
            "shift": "A",
            "count": 3,
            "start_at": "2026-07-23T07:00+01:00",
            "end_at": "2026-07-24T15:30+01:00",
            "category": "Outra",
            "reason": "Doença",
        }]
        state.engine_data = _engine()
        state.config = config
        state.dataset_info = {"id": "dataset-operator-relaxation"}

        def fake_start(**kwargs):
            captured.update(kwargs)
            return {"id": "job-operator-relaxation", "status": "queued", "progress": 0}

        monkeypatch.setattr("backend.api.replan.manager.start", fake_start)
        response = TestClient(app).post(
            "/api/data/replan-jobs",
            json={
                "expected_revision": state.plan_revision,
                "reason": "Retirar ausência",
                "config_updates": {"unavailability_removals": ["absence-a"]},
            },
        )

        assert response.status_code == 200, response.text
        assert captured["prefer_unchanged_baseline"] is False
        assert captured["allow_unchanged_baseline_apply"] is False
        assert captured["reoptimize_relaxed_baseline"] is True
        assert captured["config"].operator_unavailability == []
        assert state.config.operator_unavailability[0]["id"] == "absence-a"
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


def test_replan_keeps_demand_without_an_active_machine(monkeypatch):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
    }
    captured = {}
    try:
        config = FactoryConfig()
        config.machines = {
            "M1": MachineConfig(id="M1", group="Grandes"),
            "M2": MachineConfig(id="M2", group="Grandes"),
        }
        config.tools = {"T1": {"primary": "M1", "alt": None, "setup_hours": 0.5}}
        state.engine_data = _engine()
        state.config = config
        state.dataset_info = {"id": "dataset-unschedulable-demand"}

        def fake_start(**kwargs):
            captured.update(kwargs)
            return {"id": "job-unschedulable", "status": "queued", "progress": 0}

        monkeypatch.setattr("backend.api.replan.manager.start", fake_start)
        response = TestClient(app).post(
            "/api/data/replan-jobs",
            json={
                "expected_revision": state.plan_revision,
                "config_updates": {"machine_active": {"M1": False}},
            },
        )

        assert response.status_code == 200, response.text
        assert len(captured["engine_data"].ops) == 1
        assert sum(captured["engine_data"].ops[0].d) == 100
        assert any(machine.id == "M1" for machine in captured["engine_data"].machines)
        assert "procura não planeada" in captured["preparation_warnings"][0]
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


def test_catalog_explains_isop_and_persistent_configuration_sources():
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
    }
    try:
        config = FactoryConfig()
        config.machines = {
            "M1": MachineConfig(id="M1", group="Grandes"),
            "HIST": MachineConfig(id="HIST", group="Medias", active=False),
        }
        config.tools = {
            "T1": {"primary": "M1", "alt": None, "setup_hours": 0.75},
            "OLD": {"primary": "HIST", "alt": None, "setup_hours": 0.5},
        }
        state.engine_data = _engine()
        state.config = config

        response = TestClient(app).get("/api/data/catalog")

        assert response.status_code == 200, response.text
        payload = response.json()
        machines = {item["id"]: item for item in payload["machines"]}
        tools = {item["id"]: item for item in payload["tools"]}
        references = {item["id"]: item for item in payload["references"]}
        assert machines["M1"]["source"] == "both"
        assert machines["HIST"]["source"] == "config"
        assert tools["T1"]["source"] == "both"
        assert tools["OLD"]["source"] == "config"
        assert references["SKU1"]["source"] == "isop"
        assert "O ISOP define" in payload["source_policy"]["active"]
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


def test_catalog_resolves_missing_tool_primary_without_hiding_route_conflicts():
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
    }
    try:
        config = FactoryConfig()
        config.machines = {
            "M1": MachineConfig(id="M1", group="Grandes"),
            "M2": MachineConfig(id="M2", group="Grandes"),
        }
        config.tools = {
            "HAN002": {"setup_hours": 0.5},
            "CONFLICT": {"primary": "", "setup_hours": 0.5},
            "HIST": {"setup_hours": 0.5},
        }
        state.engine_data = _engine(
            ops=[
                _op(op_id="HAN002_M1_SKU1", tool="HAN002", machine="M1"),
                _op(op_id="CONFLICT_M1_SKU2", sku="SKU2", tool="CONFLICT", machine="M1"),
                _op(op_id="CONFLICT_M2_SKU3", sku="SKU3", tool="CONFLICT", machine="M2"),
            ],
            machines=[
                MachineInfo(id="M1", group="Grandes", day_capacity=1020),
                MachineInfo(id="M2", group="Grandes", day_capacity=1020),
            ],
        )
        state.config = config

        response = TestClient(app).get("/api/data/catalog")

        assert response.status_code == 200, response.text
        tools = {item["id"]: item for item in response.json()["tools"]}
        assert tools["HAN002"]["primary"] == "M1"
        assert tools["HAN002"]["primary_source"] == "isop"
        assert tools["HAN002"]["observed_machines"] == ["M1"]
        assert tools["CONFLICT"]["primary"] == ""
        assert tools["CONFLICT"]["primary_source"] == "conflict"
        assert tools["CONFLICT"]["observed_machines"] == ["M1", "M2"]
        assert tools["HIST"]["primary_source"] == "missing"
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


def test_creation_endpoints_queue_reviewable_candidates_without_mutating_state(monkeypatch):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
    }
    captured = []
    try:
        config = FactoryConfig()
        config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
        config.tools = {"T1": {"primary": "M1", "alt": None, "setup_hours": 0.5}}
        state.engine_data = _engine()
        state.config = config
        state.dataset_info = {"id": "dataset-create-review"}

        def fake_start(**kwargs):
            captured.append(kwargs)
            return {
                "id": f"job-{len(captured)}",
                "status": "queued",
                "progress": 0,
            }

        monkeypatch.setattr("backend.api.replan.manager.start", fake_start)
        client = TestClient(app)
        machine = client.post(
            "/api/data/machines",
            json={
                "expected_revision": state.plan_revision,
                "id": "M2",
                "group": "Medias",
            },
        )
        tool = client.post(
            "/api/data/tools",
            json={
                "expected_revision": state.plan_revision,
                "id": "T2",
                "primary": "M1",
                "setup_hours": 0.75,
            },
        )

        assert machine.status_code == 200, machine.text
        assert tool.status_code == 200, tool.text
        assert machine.json()["status"] == "queued"
        assert tool.json()["status"] == "queued"
        assert captured[0]["config"].machines["M2"].group == "Medias"
        assert captured[1]["config"].tools["T2"]["setup_hours"] == 0.75
        assert "M2" not in state.config.machines
        assert "T2" not in state.config.tools
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


@pytest.mark.parametrize(
    ("config_updates", "message"),
    [
        ({"machine_oee": {"M1": "não-é-número"}}, "OEE inválido"),
        ({"machine_oee": []}, "machine_oee deve ser um objeto"),
        ({"machine_groups": []}, "machine_groups deve ser um objeto"),
        ({"machine_active": []}, "machine_active deve ser um objeto"),
        ({"machine_active": {"M1": "não"}}, "Estado inválido"),
        ({"machine_additions": {}}, "machine_additions deve ser uma lista"),
        ({"tool_additions": {}}, "tool_additions deve ser uma lista"),
        ({"tool_updates": []}, "tool_updates deve ser um objeto"),
        ({"unavailability_additions": {}}, "unavailability_additions deve ser uma lista"),
        ({"unavailability_removals": {}}, "unavailability_removals deve ser uma lista"),
        ({"unavailability_updates": {}}, "unavailability_updates deve ser uma lista"),
        ({"shifts": {}}, "shifts deve ser uma lista"),
        ({"global_jit_enabled": False}, "Parâmetro desconhecido"),
        (
            {"setup_crews_by_group": {"Grandes": "muitas"}},
            "equipas de setup devem ser números inteiros",
        ),
    ],
)
def test_replan_api_rejects_malformed_config_updates(
    monkeypatch,
    config_updates,
    message,
):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
    }
    try:
        config = FactoryConfig()
        config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
        state.engine_data = _engine()
        state.config = config
        state.dataset_info = {"id": "dataset-invalid-replan"}
        start_called = False

        def fake_start(**_kwargs):
            nonlocal start_called
            start_called = True

        monkeypatch.setattr("backend.api.replan.manager.start", fake_start)
        response = TestClient(app).post(
            "/api/data/replan-jobs",
            json={
                "expected_revision": state.plan_revision,
                "config_updates": config_updates,
            },
        )

        assert response.status_code == 400
        assert message in response.json()["detail"]
        assert start_called is False
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


@pytest.mark.parametrize(
    "current_machine_states",
    [
        [
            {
                "machine_id": "M1",
                "status": "producing",
                "sku": "SKU1",
                "tool_id": "T1",
                "remaining_qty": 50,
                "expected_end": "2026-07-23T08:00",
                "note": "Produção confirmada",
            }
        ],
        [{"machine_id": "M1", "status": "idle"}],
    ],
)
def test_replan_api_rejects_current_machine_states_payload(
    monkeypatch,
    current_machine_states,
):
    previous = {
        "engine_data": state.engine_data,
        "config": state.config,
        "dataset_info": state.dataset_info,
    }
    try:
        config = FactoryConfig()
        config.machines = {
            "M1": MachineConfig(id="M1", group="Grandes"),
            "M2": MachineConfig(id="M2", group="Grandes"),
        }
        state.engine_data = _engine(
            machines=[
                MachineInfo(id="M1", group="Grandes", day_capacity=1020),
                MachineInfo(id="M2", group="Grandes", day_capacity=1020),
            ]
        )
        state.config = config
        state.dataset_info = {"id": "dataset-legacy-current-state"}
        start_called = False

        def fake_start(**_kwargs):
            nonlocal start_called
            start_called = True

        monkeypatch.setattr("backend.api.replan.manager.start", fake_start)
        response = TestClient(app).post(
            "/api/data/replan-jobs",
            json={
                "expected_revision": state.plan_revision,
                "reason": "Estado inicial legado",
                "current_machine_states": current_machine_states,
            },
        )

        assert response.status_code == 400
        assert "current_machine_states" in response.json()["detail"]
        assert start_called is False
        assert state.engine_data.current_machine_states == []
    finally:
        for key, value in previous.items():
            setattr(state, key, value)


def test_named_scenario_is_saved_without_changing_true_plan(monkeypatch):
    fields = (
        "engine_data",
        "config",
        "default_config",
        "segments",
        "lots",
        "score",
        "gate_report",
        "dataset_info",
        "plans_store",
        "active_mutations",
        "manual_edits",
        "saved_schedule",
        "saved_mutations",
        "saved_manual_edits",
        "saved_engine_data",
        "saved_config",
        "plan_revision",
        "approvals",
    )
    previous = {key: getattr(state, key) for key in fields}
    store = PlansStore(":memory:")
    try:
        data = _engine()
        config = FactoryConfig()
        segment = _segment(
            lot_id="LOT1",
            machine="M1",
            tool="T1",
            setup=0,
        )
        lot = Lot(
            id="LOT1",
            op_id="T1_M1_SKU1",
            tool_id="T1",
            machine_id="M1",
            alt_machine_id=None,
            qty=100,
            prod_min=60,
            setup_min=0,
            edd=1,
            is_twin=False,
        )
        score = {
            "otd": 100.0,
            "otd_d": 100.0,
            "tardy_count": 0,
            "otd_d_failures": 0,
            "early_window_violations": 0,
            "setups": 0,
        }
        gate = build_gate_report([segment], [lot], score, data, config)
        state.engine_data = data
        state.config = config
        state.default_config = copy.deepcopy(config)
        state.segments = [segment]
        state.lots = [lot]
        state.score = score
        state.gate_report = gate
        state.dataset_info = {"id": "dataset-1", "filename": "isop.xlsx"}
        state.plans_store = store
        state.active_mutations = [
            {
                "type": "machine_down",
                "params": {"machine_id": "M1", "start": 2, "end": 2},
            }
        ]
        state.manual_edits = []
        state.approvals = [{"author": "outro planeador", "reason": "outro plano"}]

        simulated = SimpleNamespace(
            segments=copy.deepcopy(state.segments),
            lots=copy.deepcopy(state.lots),
            score={**score, "otd": 90.0, "tardy_count": 1},
            delta=DeltaReport(100, 90, 100, 90, 0, 0, 0, 0, 0, 1),
            time_ms=1.0,
            summary=["Avaria testada"],
            gate_report={
                **gate,
                "status": "best_effort",
                "delivery_gate_passed": False,
            },
            mutated_data=copy.deepcopy(data),
            mutated_config=copy.deepcopy(config),
            warnings=["aviso do cenário"],
            operator_alerts=["alerta do cenário"],
        )
        captured_mutations = []

        def fake_simulate(_data, _score, mutations, config=None, **_kwargs):
            captured_mutations.extend(mutation.type for mutation in mutations)
            return simulated

        monkeypatch.setattr("backend.simulator.simulator.simulate", fake_simulate)

        baseline_score = dict(state.score)
        from backend.plans.candidates import previews
        from backend.simulator.mutations import normalize_mutation_params

        pending = [{"type": "operator_shortage", "params": normalize_mutation_params(
            "operator_shortage", {"group": "Grandes", "shift": "A", "start": 0,
                                  "end": 0, "count": 1, "note": "teste"},
        )}]
        preview = previews.put("simulation", state, {"mutations": pending}, simulated)
        client = TestClient(app)
        saved = client.post(
            "/api/data/scenarios",
            json={
                "name": "Avaria de teste",
                "candidate_id": preview.id,
                "mutations": [
                    {
                        "type": "operator_shortage",
                        "params": {
                            "group": "Grandes",
                            "shift": "A",
                            "start": 0,
                            "end": 0,
                            "count": 1,
                            "note": "teste",
                        },
                    }
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["scenario"]["source"] == "scenario"
        assert captured_mutations == []
        stored = store.get(saved.json()["scenario"]["id"])
        assert [item["type"] for item in stored["payload"]["active_mutations"]] == [
            "machine_down",
            "operator_shortage",
        ]
        assert stored["payload"]["approvals"] == []
        assert stored["payload"]["warnings"] == ["aviso do cenário"]
        assert stored["payload"]["operator_alerts"] == ["alerta do cenário"]
        assert stored["payload"]["dataset_info"]["id"] == "dataset-1"
        assert state.score == baseline_score
        assert state.segments[0].day_idx == 0

        state.plan_revision += 1
        stale = client.post(
            f"/api/data/scenarios/{stored['id']}/apply",
            json={"expected_revision": state.plan_revision},
        )
        assert stale.status_code == 409
        assert "plano mudou" in stale.json()["detail"].lower()

        state.plan_revision -= 1
        state.dataset_info = {"id": "dataset-2", "filename": "outro.xlsx"}
        wrong_dataset = client.post(
            f"/api/data/scenarios/{stored['id']}/apply",
            json={"expected_revision": state.plan_revision},
        )
        assert wrong_dataset.status_code == 409
        assert "outro isop" in wrong_dataset.json()["detail"].lower()

        listed = client.get("/api/data/scenarios")
        assert [item["name"] for item in listed.json()["scenarios"]] == ["Avaria de teste"]
    finally:
        store.close()
        for key, value in previous.items():
            setattr(state, key, value)
