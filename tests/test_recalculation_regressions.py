"""Regressions for the active-plan recalculation (29/09/2026).

Two independent defects made ``POST /api/data/recalculate`` fail on the real
active plan with the served code:

* a manual anchor was only honoured inside the CP-SAT model; when that model
  timed out, every candidate violated the anchor and none was retained;
* the final hard-constraint repair pushed segments one by one and could move a
  segment past its machine successors, leaving tool changes without setup.
"""

from __future__ import annotations

import copy

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.plans import frozen
from backend.scheduler.scheduler import _repair_hard_constraints
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.scheduler.validation import validate_plan
from backend.types import EngineData, EOp, MachineInfo, PlanAnchor


def _op(op_id: str, sku: str, tool: str) -> EOp:
    return EOp(
        id=op_id, sku=sku, client="C", designation=sku, m="M1", t=tool,
        pH=100, sH=.5, operators=1, eco_lot=0, alt=None, stk=0, backlog=0,
        d=[0, 0, 0, 100], oee=.66, wip=0,
    )


@pytest.fixture
def anchored_plan():
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    data = EngineData(
        ops=[_op("OP1", "SKU1", "T1")],
        machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[], client_demands={},
        workdays=["2026-09-16", "2026-09-17", "2026-09-18", "2026-09-21"], n_days=4,
        holidays=[],
    )
    lot = Lot("L1", "OP1", "T1", "M1", None, 100, 60, 30, 3, False, sku="SKU1")
    segments = [Segment("L1", "R1", "M1", "T1", 1, 420, 510, "A", 100, 60, 30, sku="SKU1")]
    result = ScheduleResult(segments=segments, lots=[lot], score={}, time_ms=0,
                            warnings=[], operator_alerts=[])
    return data, config, result


def _anchor(start_at: str) -> PlanAnchor:
    return PlanAnchor(lot_id="L1", machine_id="M1", start_at=start_at,
                      reason="teste", author="utilizador")


def test_honoured_anchor_is_protected_like_history(anchored_plan):
    data, config, baseline = anchored_plan
    # Production (after the 30 min setup) starts at 07:30 on the second day.
    data.plan_anchors = [_anchor("2026-09-17T07:30")]

    segments, lots, anchored = frozen._protected_lots(baseline, 0, data, config)

    assert anchored == {"L1"}
    assert [lot.id for lot in lots] == ["L1"]
    assert [(s.day_idx, s.start_min) for s in segments] == [(1, 420)]
    segments[0].start_min = 999
    assert baseline.segments[0].start_min == 420


def test_anchor_not_met_by_baseline_is_left_to_the_solver(anchored_plan):
    data, config, baseline = anchored_plan
    data.plan_anchors = [_anchor("2026-09-18T07:30")]

    _segments, lots, anchored = frozen._protected_lots(baseline, 0, data, config)

    assert anchored == set()
    assert lots == []


def test_reservation_hides_protected_anchor_and_restores_it(anchored_plan):
    data, config, baseline = anchored_plan
    data.plan_anchors = [_anchor("2026-09-17T07:30")]
    before = copy.deepcopy(data)
    segments, lots, _anchored = frozen._protected_lots(baseline, 0, data, config)

    snapshot = frozen._install_frozen_reservations(data, segments, lots, 0, config)

    assert data.plan_anchors == []
    assert data.machine_blocked_intervals["M1"][0]["start_day"] == 1
    assert [(s.op_id, s.qty) for s in data.committed_supplies] == [("OP1", 100)]
    frozen._restore_frozen_reservations(data, snapshot)
    assert data == before


def test_hard_constraint_repair_never_reorders_a_machine():
    """Pushing the first run off a blocked day must push its successor too."""

    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    data = EngineData(
        ops=[_op("OP1", "SKU1", "T1"), _op("OP2", "SKU2", "T2")],
        machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[], client_demands={},
        workdays=["2026-09-16", "2026-09-17", "2026-09-18", "2026-09-21"], n_days=4,
        holidays=[],
    )
    data.machine_blocked_days = {"M1": {0}}
    lots = [
        Lot("L1", "OP1", "T1", "M1", None, 100, 60, 30, 3, False, sku="SKU1"),
        Lot("L2", "OP2", "T2", "M1", None, 100, 60, 30, 3, False, sku="SKU2"),
    ]
    # T1 is also unavailable until 07:30 on the next day, so L1 lands at 07:30
    # while its successor L2 already starts at 07:00. A time-only ordering
    # then pushes L1 behind L2 and reorders the machine.
    data.tool_blocked_intervals = {
        "T1": [{"start_day": 1, "start_min": 0, "end_day": 1, "end_min": 450}],
    }
    segments = [
        Segment("L1", "R1", "M1", "T1", 0, 420, 510, "A", 100, 60, 30, sku="SKU1"),
        Segment("L2", "R2", "M1", "T2", 1, 420, 510, "A", 100, 60, 30, sku="SKU2"),
    ]

    repaired = _repair_hard_constraints(segments, data, config, set())

    ordered = sorted(
        (s for s in repaired if s.end_min > s.start_min),
        key=lambda s: (s.day_idx, s.start_min),
    )
    assert [s.lot_id for s in ordered] == ["L1", "L2"]
    assert ordered[0].day_idx == 1
    kinds = {v["kind"] for v in validate_plan(repaired, data, config, lots=lots)}
    assert not kinds & {
        "machine_overlap", "missing_tool_change_setup", "insufficient_tool_change_setup",
    }


def test_production_ranked_before_its_setup_follows_the_setup_block():
    """Machine order and run order must not leapfrog the same run forever."""

    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    data = EngineData(
        ops=[_op("OP1", "SKU1", "T1")],
        machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[], client_demands={},
        workdays=["2026-09-16", "2026-09-17", "2026-09-18", "2026-09-21"], n_days=4,
        holidays=[],
    )
    lots = [Lot("L1", "OP1", "T1", "M1", None, 100, 180, 30, 3, False, sku="SKU1")]
    segments = [
        Segment("L1", "R1", "M1", "T1", 0, 420, 480, "A", 40, 60, 0.0,
                is_continuation=True, sku="SKU1"),
        Segment("L1", "R1", "M1", "T1", 0, 480, 630, "A", 60, 120, 30, sku="SKU1"),
    ]

    repaired = _repair_hard_constraints(segments, data, config, set())

    ordered = sorted(repaired, key=lambda s: (s.day_idx, s.start_min))
    assert [s.setup_min > 0 for s in ordered] == [True, False]
    assert ordered[1].start_min >= ordered[0].end_min
    assert max(s.day_idx for s in repaired) == 0
    kinds = {v["kind"] for v in validate_plan(repaired, data, config, lots=lots)}
    assert "machine_overlap" not in kinds
