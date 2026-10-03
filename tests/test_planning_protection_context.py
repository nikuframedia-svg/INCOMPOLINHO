"""Elapsed calendar dates cannot turn a new candidate into executed history."""

import copy
from dataclasses import replace

import pytest

from backend.scheduler.canonical import preserved_lot_proofs
from backend.scheduler.operational_audit import build_operational_audit
from backend.scheduler.priority_normalization import repair_same_reference_interruptions
from backend.scheduler.shift_exchange import repair_shift_capacity_exchange
from backend.scheduler.types import Segment
from backend.types import PlanAnchor
from tests.test_priority_campaign_rotation import _case as priority_case
from tests.test_same_reference_interruptions import _case as reference_case
from tests.test_shift_exchange import _fixture as shift_case


def test_unexecuted_priority_audit_is_independent_of_wall_calendar(monkeypatch):
    rows, lots, data, config = priority_case()
    baseline = copy.deepcopy((rows, lots, data, config))
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: 0)
    earlier = build_operational_audit(rows, lots, data, config)
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: 2)

    later = build_operational_audit(rows, lots, data, config)

    assert later == earlier
    assert later["avoidable_priority_order_anomalies"] == 1
    assert (rows, lots, data, config) == baseline


def test_unexecuted_gap_is_not_hidden_as_history(monkeypatch):
    rows, lots, data, config = reference_case()
    lot = replace(lots[0], qty=125, prod_min=125, setup_min=0)
    rows = [
        Segment(lot_id=lot.id, run_id="R", machine_id="M1", tool_id="T1", sku="SKU",
                day_idx=1, start_min=420, end_min=480, shift="A", qty=60, prod_min=60),
        Segment(lot_id=lot.id, run_id="R", machine_id="M1", tool_id="T1", sku="SKU",
                day_idx=1, start_min=540, end_min=605, shift="A", qty=65, prod_min=65,
                is_continuation=True),
    ]
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: 2)

    audit = build_operational_audit(rows, [lot], data, config)

    assert audit["left_shift_opportunities"] == 1
    assert audit["protected_left_shift_detail"] == []


@pytest.mark.parametrize("protected", ["URGENT", "LATER"])
@pytest.mark.parametrize("kind", ["proof", "anchor"])
def test_same_reference_repair_respects_explicit_whole_lot_protection(protected, kind):
    rows, lots, data, config = reference_case()
    if kind == "proof":
        data.preserved_lot_proofs = preserved_lot_proofs(
            [s for s in rows if s.lot_id == protected], [lot for lot in lots if lot.id == protected],
        )
    else:
        data.plan_anchors = [PlanAnchor(protected, "M1", "2026-09-15T07:00")]
    before = copy.deepcopy((rows, lots, data, config))

    result = repair_same_reference_interruptions(rows, lots, data, config)

    assert result == rows
    assert (rows, lots, data, config) == before


def test_unexecuted_shift_tradeoff_does_not_disappear_as_time_passes(monkeypatch):
    rows, lots, data, config = shift_case()
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: 3)
    tradeoffs = []

    result = repair_shift_capacity_exchange(rows, lots, data, config, tradeoffs=tradeoffs)

    assert result == rows
    assert [item["advanced_lot_id"] for item in tradeoffs] == ["NEXT"]
    assert tradeoffs[0]["applied"] is False


@pytest.mark.parametrize("protected", ["TAIL", "NEXT"])
@pytest.mark.parametrize("kind", ["proof", "anchor"])
def test_shift_exchange_never_proposes_moving_protected_lots(protected, kind):
    rows, lots, data, config = shift_case()
    if kind == "proof":
        data.preserved_lot_proofs = preserved_lot_proofs(
            [s for s in rows if s.lot_id == protected], [lot for lot in lots if lot.id == protected],
        )
    else:
        data.plan_anchors = [PlanAnchor(protected, "M1", "2026-10-06T07:00")]
    tradeoffs = []

    assert repair_shift_capacity_exchange(rows, lots, data, config, tradeoffs=tradeoffs) == rows
    assert tradeoffs == []
