"""A failed bounded search is not proof of global movement infeasibility."""

import copy

import pytest

from backend.plans.frozen import NoValidCandidateError
from backend.plans.manual_move import ManualMoveError, move_lot
from backend.scheduler.validation import coverage_violations, validate_plan
from backend.types import EOp, PlanAnchor
from tests.test_manual_move import _baseline, _config, _engine, _lot, _segment


def conflicted_case(tool="T1", lot_id="LOT1"):
    data, config = _engine(), _config()
    data.ops[0].t = tool
    config.tools = {
        tool: {"primary": "M1", "alt": "M2", "setup_hours": 0.5},
        "T2": {"primary": "M2", "alt": None, "setup_hours": 0.5},
    }
    data.ops.append(EOp(
        id="OP2", sku="SKU2", client="CLIENTE", designation="Other part",
        m="M2", t="T2", pH=100, sH=0.5, operators=1, eco_lot=0,
        alt=None, stk=0, backlog=0, d=[0, 0, 100, 0], oee=1.0, wip=0,
    ))
    source = _segment(lot_id, tool=tool)
    lot = _lot(lot_id)
    lot.sku, lot.tool_id = "SKU1", tool
    other = _segment("OTHER", machine="M2", tool="T2", day=1,
                     start=570, run_id="OTHER-R")
    other.sku = "SKU2"
    other_lot = _lot("OTHER", op_id="OP2")
    other_lot.sku, other_lot.tool_id = "SKU2", "T2"
    other_lot.machine_id, other_lot.alt_machine_id = "M2", None
    segments, lots = [source, other], [lot, other_lot]
    return data, config, segments, lots


@pytest.mark.parametrize("tool,lot_id", [("T1", "LOT1"), ("MOULD-X", "EXTERNAL")])
def test_bounded_failure_with_valid_reorganization_is_inconclusive(monkeypatch, tool, lot_id):
    data, config, segments, lots = conflicted_case(tool, lot_id)
    original = copy.deepcopy((data, config, segments, lots))
    witness = copy.deepcopy(segments)
    witness[0].machine_id, witness[0].day_idx = "M2", 1
    witness[0].start_min, witness[0].end_min = 570, 660
    witness[1].start_min, witness[1].end_min = 700, 790
    assert validate_plan(witness, data, config, lots=lots) == []
    assert coverage_violations(witness, lots) == []

    def no_candidate(*_args, **_kwargs):
        raise NoValidCandidateError("bounded search found no complete candidate")

    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: 0)
    monkeypatch.setattr("backend.plans.manual_move._allocate_existing_lots", no_candidate)
    with pytest.raises(ManualMoveError) as caught:
        move_lot(segments, lots, _baseline(data, config, segments, lots), data, config,
                 lot_id=lot_id, target_day=1, target_machine="M2", target_start_min=600)
    assert type(caught.value).__name__ == "ManualMoveInconclusive"
    assert "Não foi demonstrada a impossibilidade" in str(caught.value)
    assert "Não há capacidade física" not in str(caught.value)
    assert caught.value.gate_report is None
    assert (data, config, segments, lots) == original


@pytest.mark.parametrize("resource", ["machine", "tool", "operators", "protected"])
def test_immutable_block_is_proven_before_search(monkeypatch, resource):
    data, config, segments, lots = conflicted_case()
    minute = 700
    interval = {"start_day": 1, "start_min": 700, "end_min": 730}
    expected = "M2"
    if resource == "machine":
        data.machine_blocked_intervals = {"M2": [interval]}
    elif resource == "tool":
        data.tool_blocked_intervals = {"T1": [interval]}
        expected = "T1"
    elif resource == "operators":
        config.operators[("Grandes", "A")] = 1
        data.operator_blocked_intervals = [dict(interval, group="Grandes", shift="A", count=1)]
        expected = "Grandes"
    else:
        data.plan_anchors = [PlanAnchor(
            lot_id="OTHER", machine_id="M2", start_at="2026-03-18T10:00:00+00:00",
        )]
        minute, expected = 600, "OTHER"
    assert validate_plan(segments, data, config, lots=lots) == []
    original = copy.deepcopy((data, config, segments, lots))

    def unexpected_search(*_args, **_kwargs):
        pytest.fail("A proven immutable conflict must not start an optimizer")

    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: 0)
    monkeypatch.setattr("backend.plans.manual_move._allocate_existing_lots", unexpected_search)
    with pytest.raises(ManualMoveError) as caught:
        move_lot(segments, lots, _baseline(data, config, segments, lots), data, config,
                 lot_id="LOT1", target_day=1, target_machine="M2", target_start_min=minute)
    assert type(caught.value).__name__ == "ManualMoveError"
    assert expected in str(caught.value)
    assert "2026-03-18" in str(caught.value)
    assert "inconclusiva" not in str(caught.value)
    assert (data, config, segments, lots) == original
