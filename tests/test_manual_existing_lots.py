"""Movement changes allocation, never reconstructs demand into new lots."""

import copy
from dataclasses import replace

import pytest

from backend.plans.manual_move import _fixed_positions_move, _production_start, move_lot
from backend.scheduler.canonical import production_lot_obligations
from backend.scheduler.validation import coverage_violations, validate_plan
from backend.types import PlanAnchor
from tests.test_manual_move import _baseline, _config, _engine, _lot, _segment
from tests.test_manual_move_verdict import conflicted_case


@pytest.fixture(autouse=True)
def planning_day(monkeypatch):
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: 0)


def campaign(tool="T1", head="PREVIOUS"):
    data, config = _engine(), _config()
    data.ops[0].t = tool
    data.ops[0].d[2] = 200
    config.tools = {tool: {"primary": "M1", "alt": "M2", "setup_hours": 0.5}}
    lots = [replace(_lot(head), sku="SKU1", tool_id=tool),
            replace(_lot("FOLLOWING"), sku="SKU1", tool_id=tool)]
    segments = [_segment(head, tool=tool),
                _segment("FOLLOWING", tool=tool, day=1, setup=0)]
    assert validate_plan(segments, data, config, lots=lots) == []
    return data, config, segments, lots


@pytest.mark.parametrize("tool,head", [("T1", "PREVIOUS"), ("MOULD-X", "HEAD-X")])
@pytest.mark.parametrize("minute", [450, 480])
def test_campaign_head_can_stay_or_move_before_its_continuation(tool, head, minute):
    data, config, segments, lots = campaign(tool, head)
    before = copy.deepcopy((segments, lots, data, config))
    candidate_data = copy.deepcopy(data)
    candidate_data.plan_anchors = [PlanAnchor(
        head, "M1", f"{data.workdays[0]}T{minute // 60:02d}:{minute % 60:02d}",
    )]
    fixed = _fixed_positions_move(segments, lots, head, 0, "M1", minute,
                                 data, config, candidate_data, {})
    assert next(item for item in fixed.segments if item.lot_id == "FOLLOWING") == segments[1]
    result = move_lot(segments, lots, _baseline(data, config, segments, lots), data, config,
                      lot_id=head, target_day=0, target_machine="M1", target_start_min=minute)
    assert _production_start(result.segments, head) == (0, minute, "M1")
    following = next(item for item in result.segments if item.lot_id == "FOLLOWING")
    assert (following.day_idx, following.start_min, following.end_min) == (0, minute + 60, minute + 120)
    assert following.setup_min == 0
    assert sum(item.setup_min for item in result.segments) == 30
    assert production_lot_obligations(result.lots) == production_lot_obligations(lots)
    assert result.gate_report["physical_gate_passed"]
    assert result.gate_report["coverage_gate_passed"]
    assert (segments, lots, data, config) == before


def test_exact_request_reuses_a_valid_plan_without_demand_sizing(monkeypatch):
    data, config, segments, lots = campaign()

    def unexpected(*_args, **_kwargs):
        pytest.fail("An allocation-only movement must never size demand into new lots")

    monkeypatch.setattr("backend.cpo.optimize", unexpected)
    monkeypatch.setattr("backend.plans.manual_move._allocate_existing_lots", unexpected)
    result = move_lot(segments, lots, _baseline(data, config, segments, lots), data, config,
                      lot_id="PREVIOUS", target_day=0, target_start_min=450)
    assert result.gate_report["physical_gate_passed"]


@pytest.mark.parametrize("tool", ["T1", "MOULD-X"])
def test_reorganization_preserves_multiple_lots_of_the_same_operation(tool):
    data, config, segments, lots = conflicted_case(tool=tool)
    data.ops[1].d[2] = 200
    second = replace(lots[1], id="OTHER-B")
    segments.append(replace(segments[1], lot_id=second.id, start_min=660, end_min=720,
                            setup_min=0, is_continuation=True))
    lots.append(second)
    assert validate_plan(segments, data, config, lots=lots) == []
    before = copy.deepcopy((segments, lots, data, config))
    witness = copy.deepcopy(segments)
    witness[0].machine_id, witness[0].day_idx = "M2", 1
    witness[0].start_min, witness[0].end_min = 570, 660
    witness[1].day_idx, witness[1].start_min, witness[1].end_min = 0, 420, 510
    witness[2].day_idx, witness[2].start_min, witness[2].end_min = 0, 510, 570
    assert validate_plan(witness, data, config, lots=lots) == []
    assert coverage_violations(witness, lots) == []
    result = move_lot(segments, lots, _baseline(data, config, segments, lots), data, config,
                      lot_id="LOT1", target_day=1, target_machine="M2", target_start_min=600)
    assert _production_start(result.segments, "LOT1") == (1, 600, "M2")
    assert production_lot_obligations(result.lots) == production_lot_obligations(lots)
    assert validate_plan(result.segments, data, config, lots=result.lots) == []
    assert coverage_violations(result.segments, result.lots) == []
    assert (segments, lots, data, config) == before


def test_default_time_comes_from_production_not_a_parked_setup():
    data, config = _engine(), _config()
    end = config.shifts[-1].end_min
    setup = replace(_segment(start=end - 30), qty=0, prod_min=0, end_min=end,
                    shift=config.shifts[-1].id)
    production = _segment(day=1, setup=0)
    segments, lots = [setup, production], [_lot()]
    assert validate_plan(segments, data, config, lots=lots) == []
    result = move_lot(segments, lots, _baseline(data, config, segments, lots), data, config,
                      lot_id="LOT1", target_day=2)
    assert _production_start(result.segments, "LOT1") == (2, 420, "M1")


def test_complete_normalization_reuses_mounting_from_a_protected_lot():
    from backend.plans.frozen import improve_preserving_protected_lots
    from backend.scheduler.types import ScheduleResult

    data, config, segments, lots = campaign()
    segments[1] = replace(segments[1], day_idx=0, start_min=510, end_min=600,
                          setup_min=30, run_id="NEW-RUN")
    data.plan_anchors = [PlanAnchor("PREVIOUS", "M1", f"{data.workdays[0]}T07:30")]
    assert validate_plan(segments, data, config, lots=lots) == []
    before = copy.deepcopy((data, config, segments, lots))
    result = ScheduleResult(copy.deepcopy(segments), copy.deepcopy(lots),
                            _baseline(data, config, segments, lots), 0, [], [])
    repaired, report = improve_preserving_protected_lots(
        result, data, copy.deepcopy(data), config,
        copy.deepcopy(segments[:1]), copy.deepcopy(lots[:1]), 0, time_budget_s=5,
    )
    assert next(item for item in repaired.segments if item.lot_id == "PREVIOUS") == segments[0]
    following = next(item for item in repaired.segments if item.lot_id == "FOLLOWING")
    assert (following.start_min, following.end_min, following.setup_min) == (510, 570, 0)
    assert report["moves_accepted"] > 0
    assert validate_plan(repaired.segments, data, config, lots=repaired.lots) == []
    assert (data, config, segments, lots) == before
