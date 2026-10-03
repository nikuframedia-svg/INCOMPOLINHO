"""Enumerated witnesses for setup/production boundaries in automatic repair."""

import copy
import math
from dataclasses import replace

import pytest

from backend.scheduler.gap_filling import (
    candidate_setup_starts,
    evaluate_legal_interval,
    find_opening_gap_opportunities,
)
from backend.scheduler.improvement import improve_plan
from backend.scheduler.scheduler import normalize_earliest_legal_plan
from backend.scheduler.validation import coverage_violations, validate_plan
from backend.types import EOp
from tests.test_manual_move import _config, _engine, _lot, _segment


def operator_boundary_case(tool="T1", release=510, setup=30):
    data, config = _engine(), _config()
    config.operators[("Grandes", "A")] = 1
    config.operators[("Grandes", "B")] = 1
    data.ops[0].t, data.ops[0].alt = tool, None
    data.ops[0].sH = setup / 60
    config.tools = {
        tool: {"primary": "M1", "alt": None, "setup_hours": setup / 60},
        "OTHER-TOOL": {"primary": "M2", "alt": None, "setup_hours": 0},
    }
    data.ops.append(
        EOp(
            id="OP2",
            sku="SKU2",
            client="CLIENTE",
            designation="Other production",
            m="M2",
            t="OTHER-TOOL",
            pH=6000 / (release - 420),
            sH=0,
            operators=1,
            eco_lot=0,
            alt=None,
            stk=0,
            backlog=0,
            d=[100, 0, 0, 0],
            oee=1,
            wip=0,
        )
    )
    target = _segment(tool=tool, day=1, start=600, setup=setup)
    target.end_min = math.ceil(target.start_min + target.setup_min + target.prod_min)
    target.run_setup_min = setup
    lot = _lot()
    lot.sku, lot.tool_id, lot.alt_machine_id = "SKU1", tool, None
    lot.setup_min = setup
    other = _segment(
        "OTHER", machine="M2", tool="OTHER-TOOL", day=0, start=420, setup=0, run_id="OTHER-R", edd=0
    )
    other.prod_min, other.end_min = release - 420, release
    other.sku, other.run_setup_min = "SKU2", 0
    other_lot = _lot("OTHER", edd=0, op_id="OP2")
    other_lot.sku, other_lot.tool_id = "SKU2", "OTHER-TOOL"
    other_lot.machine_id, other_lot.alt_machine_id = "M2", None
    other_lot.prod_min, other_lot.setup_min = release - 420, 0
    return data, config, [target, other], [lot, other_lot]


@pytest.mark.parametrize("tool,release,setup", [("T1", 510, 30), ("MOULD-X", 552, 42)])
@pytest.mark.parametrize("path", ["detector", "normalizer", "cycle"])
def test_preparation_can_finish_at_operator_release(tool, release, setup, path):
    data, config, segments, lots = operator_boundary_case(tool, release, setup)
    before = copy.deepcopy((data, config, segments, lots))
    witness = [
        replace(segments[0], day_idx=0, start_min=release - setup, end_min=release + 60),
        segments[1],
    ]
    assert validate_plan(segments, data, config, lots=lots) == []
    assert validate_plan(witness, data, config, lots=lots) == []
    assert coverage_violations(witness, lots) == []
    if path == "detector":
        found = find_opening_gap_opportunities(segments, lots, data, config)
        target = next(item for item in found if item.lot_id == "LOT1")
        assert target.gap_day == 0
        assert target.gap_start_min == release - setup
    else:
        if path == "normalizer":
            candidate = normalize_earliest_legal_plan(segments, lots, data, config)
        else:
            candidate, _lots, report = improve_plan(segments, lots, data, config)
            assert report["status"] == "completed"
        first = min(
            (s for s in candidate if s.lot_id == "LOT1" and s.prod_min > 0),
            key=lambda s: (s.day_idx, s.start_min),
        )
        assert (first.day_idx, first.start_min + first.setup_min) == (0, release)
        assert validate_plan(candidate, data, config, lots=lots) == []
        assert coverage_violations(candidate, lots) == []
    assert (data, config, segments, lots) == before


@pytest.mark.parametrize("setup", [0, 30, 42])
@pytest.mark.parametrize("blocker", ["production", "absence", "machine", "tool", "crew"])
def test_event_search_matches_exhaustive_fixed_resource_starts(setup, blocker):
    data, config, segments, lots = operator_boundary_case(setup=setup)
    if blocker == "absence":
        segments, lots, data.ops = segments[:1], lots[:1], data.ops[:1]
        data.operator_blocked_intervals = [
            {
                "start_day": 0,
                "start_min": 420,
                "end_day": 0,
                "end_min": 510,
                "group": "Grandes",
                "shift": "A",
                "count": 1,
            }
        ]
    elif blocker in {"machine", "tool"}:
        block = {"start_day": 0, "start_min": 420, "end_day": 0, "end_min": 495}
        if blocker == "machine":
            data.machine_blocked_intervals = {"M1": [block]}
        else:
            data.tool_blocked_intervals = {"T1": [block]}
    elif blocker == "crew":
        data.setup_crew_reservations = [
            {
                "id": "history-setup",
                "start_day": 0,
                "start_min": 420,
                "end_day": 0,
                "end_min": 490,
                "machine_id": "M2",
                "tool_id": "RESERVED",
                "group": "Grandes",
            }
        ]
    before = copy.deepcopy((data, config, segments, lots))
    source = segments[0]
    assert not validate_plan(segments, data, config, lots=lots)
    # The finite minute enumeration is a test oracle, not the production search.
    legal = [
        start
        for start in range(config.shift_a_start, config.shift_a_end)
        if evaluate_legal_interval(
            segments,
            source,
            data,
            config,
            0,
            start,
            start + math.ceil(setup + source.prod_min),
            setup_min=setup,
            moving_lot=lots[0],
            lots_by_id={lot.id: lot for lot in lots},
            ignored_lot_ids={source.lot_id},
        ).allowed
    ]
    assert legal
    found = find_opening_gap_opportunities(
        segments,
        lots,
        data,
        config,
        allow_setup_free=True,
    )
    opportunity = next(item for item in found if item.lot_id == "LOT1")
    assert (opportunity.gap_day, opportunity.gap_start_min) == (0, min(legal))
    candidate, candidate_lots, report = improve_plan(segments, lots, data, config)
    assert report["status"] == "completed"
    first = min(
        (s for s in candidate if s.lot_id == "LOT1" and s.prod_min > 0),
        key=lambda s: (s.day_idx, s.start_min),
    )
    assert (first.day_idx, first.start_min) == (0, min(legal))
    assert not validate_plan(candidate, data, config, lots=candidate_lots)
    assert not coverage_violations(candidate, candidate_lots)
    assert (data, config, segments, lots) == before


def test_offsets_stay_finite_clipped_and_round_up():
    assert candidate_setup_starts([420, 510, 930], 42.5, 420, 929) == [420, 468, 510, 888]
    assert candidate_setup_starts([420, 510, 930], 0, 420, 929) == [420, 510]
    assert candidate_setup_starts([420, 510], 30, 550, 500) == []
    assert len(candidate_setup_starts(list(range(420, 930, 30)), 42.5, 420, 929)) <= 34


def test_complete_cycle_is_idempotent_and_independent_of_input_order():
    data, config, segments, lots = operator_boundary_case()

    def physical(items):
        return sorted(
            (
                s.lot_id,
                s.machine_id,
                s.day_idx,
                s.start_min,
                s.end_min,
                s.setup_min,
                s.prod_min,
                s.qty,
            )
            for s in items
        )

    candidate, candidate_lots, report = improve_plan(segments, lots, data, config)
    again, _, repeated = improve_plan(candidate, candidate_lots, data, config)
    permuted, _, reversed_report = improve_plan(
        list(reversed(segments)), list(reversed(lots)), data, config
    )
    assert report["status"] == repeated["status"] == reversed_report["status"] == "completed"
    assert physical(candidate) == physical(again) == physical(permuted)
    assert physical([s for s in candidate if s.lot_id == "OTHER"]) == physical(segments[1:])
    assert {lot.id: lot.qty for lot in candidate_lots} == {lot.id: lot.qty for lot in lots}
