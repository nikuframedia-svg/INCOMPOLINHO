"""Setup close-out respects frozen productions and real shift boundaries."""

import copy
from dataclasses import replace

import pytest

from backend.plans.frozen import improve_preserving_protected_lots
from backend.scheduler.canonical import preserved_lot_proofs
from backend.scheduler.gap_filling import apply_partial_gap_move, find_gap_opportunities
from backend.scheduler.scheduler import (
    _merge_detached_setup_segments,
    _repair_interrupted_tool_campaigns,
    normalize_earliest_legal_plan,
)
from backend.scheduler.types import ScheduleResult
from backend.scheduler.validation import validate_plan
from backend.types import PlanAnchor
from tests.test_manual_move import _baseline, _config, _engine, _lot, _segment


def protected_setup_case(head="PROTECTED", movable="MOVABLE"):
    data, config = _engine(), _config()
    data.ops.append(replace(data.ops[0], id="OP2", sku="SKU2", t="T2", m="M2", alt="M1"))
    config.tools["T2"] = {"primary": "M2", "alt": "M1", "setup_hours": 0.5}
    lots = [replace(_lot(head), sku="SKU1"),
            replace(_lot(movable, op_id="OP2"), tool_id="T2", machine_id="M2",
                    alt_machine_id="M1", sku="SKU2")]
    setup = replace(_segment(head), end_min=450, prod_min=0, qty=0)
    production = _segment(head, start=450, setup=0)
    other = replace(_segment(movable, machine="M2", tool="T2", day=2,
                             run_id="RUN2"), sku="SKU2")
    segments = [setup, production, other]
    assert validate_plan(segments, data, config, lots=lots) == []
    return data, config, segments, lots


@pytest.mark.parametrize("protection", ["explicit", "proof", "anchor"])
def test_normalizer_preserves_all_fragments_of_a_protected_setup(protection):
    data, config, segments, lots = protected_setup_case()
    if protection == "proof":
        data.preserved_lot_proofs = preserved_lot_proofs(segments[:2], lots[:1])
    elif protection == "anchor":
        data.plan_anchors = [PlanAnchor("PROTECTED", "M1", data.workdays[0] + "T07:30:00")]
    before = copy.deepcopy((data, config, segments, lots))
    repaired = normalize_earliest_legal_plan(
        segments, lots, data, config, annotate=False,
        protected_lot_ids={"PROTECTED"} if protection == "explicit" else None,
    )
    assert [s for s in repaired if s.lot_id == "PROTECTED"] == segments[:2]
    assert next(s for s in repaired if s.lot_id == "MOVABLE").day_idx == 0
    assert validate_plan(repaired, data, config, lots=lots) == []
    assert normalize_earliest_legal_plan(
        repaired, lots, data, config, annotate=False,
        protected_lot_ids={"PROTECTED"} if protection == "explicit" else None,
    ) == repaired
    assert (data, config, segments, lots) == before


def test_partial_gap_move_cannot_move_a_protected_source():
    data, config, segments, lots = protected_setup_case()
    opportunity = next(item for item in find_gap_opportunities(segments, lots, data, config)
                       if item.lot_id == "MOVABLE")
    before = copy.deepcopy((data, config, segments, lots))
    assert apply_partial_gap_move(
        segments, opportunity, config, data, protected_lot_ids={"MOVABLE"},
    ) == segments
    assert (data, config, segments, lots) == before


@pytest.mark.parametrize("protected", [None, "PROTECTED", "MOVABLE"])
def test_interrupted_campaign_repair_respects_every_protected_member(protected):
    data, config, segments, lots = protected_setup_case()
    data.ops = []
    config.jit_enabled = config.global_jit_enabled = False
    lots[0] = replace(lots[0], qty=200, prod_min=120, edd=1)
    lots[1] = replace(lots[1], machine_id="M1", edd=2)
    first = replace(segments[1], start_min=420, setup_min=30, end_min=510)
    blocker = replace(segments[2], machine_id="M1", day_idx=0,
                      start_min=510, end_min=600)
    tail = replace(segments[1], start_min=620, end_min=680, is_continuation=True)
    rows = [first, blocker, tail]
    before = copy.deepcopy((data, config, rows, lots))
    assert "missing_tool_change_setup" in {v["kind"] for v in validate_plan(rows, data, config, lots=lots)}
    repaired = _repair_interrupted_tool_campaigns(
        rows, lots, data, config, protected_lot_ids={protected} if protected else None,
    )
    if protected:
        assert repaired == rows
    else:
        assert [(s.lot_id, s.start_min) for s in repaired] == [
            ("PROTECTED", 420), ("PROTECTED", 510), ("MOVABLE", 570),
        ]
        assert validate_plan(repaired, data, config, lots=lots) == []
    assert (data, config, rows, lots) == before


@pytest.mark.parametrize("head,movable", [("PROTECTED", "MOVABLE"), ("FIXED-X", "FREE-Y")])
def test_complete_cycle_does_not_discard_improvements_beside_a_split_protected_setup(head, movable):
    data, config, segments, lots = protected_setup_case(head, movable)
    before = copy.deepcopy((data, config, segments, lots))
    result = ScheduleResult(copy.deepcopy(segments), copy.deepcopy(lots),
                            _baseline(data, config, segments, lots), 0, [], [])
    repaired, report = improve_preserving_protected_lots(
        result, data, copy.deepcopy(data), config,
        copy.deepcopy(segments[:2]), copy.deepcopy(lots[:1]), 0, time_budget_s=5,
    )
    assert [s for s in repaired.segments if s.lot_id == head] == segments[:2]
    assert next(s for s in repaired.segments if s.lot_id == movable).day_idx == 0
    assert report["moves_accepted"] > 0
    assert validate_plan(repaired.segments, data, config, lots=repaired.lots) == []
    assert (data, config, segments, lots) == before


def test_attaching_opening_setup_splits_the_shifted_suffix_at_real_boundaries():
    config = _config()
    config.tools["T2"] = {"primary": "M1", "alt": "M2", "setup_hours": 0.5}
    first = replace(_lot("FIRST", edd=6), prod_min=414, qty=414, delivery_day=6)
    second = replace(_lot("SECOND", edd=6), tool_id="T2", prod_min=130, qty=130,
                     delivery_day=6)
    setup = replace(_segment("FIRST", start=700, edd=6), end_min=730, prod_min=0, qty=0)
    production = replace(_segment("FIRST", day=1, setup=0, edd=6),
                         end_min=834, prod_min=414, qty=414)
    following = replace(_segment("SECOND", tool="T2", day=1, start=834,
                                 run_id="RUN2", edd=6), end_min=930, prod_min=66, qty=66)
    continuation = replace(following, start_min=930, end_min=994, shift="B",
                           setup_min=0, prod_min=64, qty=64, is_continuation=True)
    segments = [setup, production, following, continuation]
    assert {v["kind"] for v in validate_plan(segments, None, config, lots=[first, second])} == {
        "detached_setup", "setup_before_material",
    }
    repaired = _merge_detached_setup_segments(segments, config, lots=[first, second])
    assert validate_plan(repaired, None, config, lots=[first, second]) == []
    assert sum(s.qty for s in repaired if s.lot_id == "SECOND") == 130
    assert sum(s.prod_min for s in repaired if s.lot_id == "SECOND") == 130
    assert sum(s.setup_min for s in repaired) == 60
    assert next(s for s in repaired if s.lot_id == "FIRST").start_min == 420
