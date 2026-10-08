"""No-loss decisions must use actual protected output dates, not reservations."""

import copy
from dataclasses import replace

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.plans.frozen import improve_preserving_protected_lots
from backend.scheduler import improvement
from backend.scheduler.improvement import Generator, Proposal, no_loss_verdict, plan_facts
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.scheduler.validation import validate_plan
from backend.types import ClientDemandEntry, EngineData, EOp, MachineInfo, PlanAnchor


@pytest.fixture
def plan():
    config = FactoryConfig(
        machines={mid: MachineConfig(mid, "Grandes", oee=1.0) for mid in ("M1", "M2")},
        oee_default=1.0,
    )
    workdays = [f"2026-10-{day:02d}" for day in (5, 6, 7, 8, 9, 12, 13, 14, 15)]
    demand_a = [0] * 9
    demand_a[5] = demand_a[8] = 100
    demand_b = [0] * 9
    demand_b[5] = 100
    data = EngineData(
        ops=[
            EOp("A", "SKU-A", "C", "Part A", "M1", "TA", 100, .5, 1, 0, "M2",
                0, 0, demand_a, 1.0, 0),
            EOp("B", "SKU-B", "C", "Part B", "M2", "TB", 100, .5, 1, 0, None,
                0, 0, demand_b, 1.0, 0),
        ],
        machines=[MachineInfo(mid, "Grandes", 1020) for mid in ("M1", "M2")],
        twin_groups=[],
        client_demands={
            "SKU-A": [ClientDemandEntry("C", "SKU-A", day, "", 100, -100) for day in (5, 8)],
            "SKU-B": [ClientDemandEntry("C", "SKU-B", 5, "", 100, -100)],
        },
        workdays=workdays, n_days=9,
        plan_anchors=[PlanAnchor("PROTECTED", "M1", f"{workdays[6]}T07:30")],
    )
    lots = [
        Lot("PROTECTED", "A", "TA", "M1", "M2", 100, 60, 30, 8, False, sku="SKU-A"),
        Lot("FUTURE-A", "A", "TA", "M2", "M1", 100, 60, 30, 5, False, sku="SKU-A"),
        Lot("FUTURE-B", "B", "TB", "M2", None, 100, 60, 30, 5, False, sku="SKU-B"),
    ]
    segments = [
        Segment(lot.id, f"R-{lot.id}", lot.machine_id, lot.tool_id, day, 420, 510,
                "A", 100, 60, 30, edd=lot.edd, sku=lot.sku)
        for lot, day in zip(lots, (6, 4, 7), strict=True)
    ]
    assert not validate_plan(segments, data, config, lots=lots)
    result = ScheduleResult(segments, lots, compute_score(segments, lots, data, config),
                            0, [], [])
    return data, config, result


def test_residual_improvement_cannot_hide_order_loss_with_protected_supply(plan, monkeypatch):
    data, config, before = plan
    initial = copy.deepcopy((data, before))
    real_improve = improvement.improve_plan

    def swap(segments, lots):
        return Proposal([
            replace(segment, day_idx=7 if segment.lot_id == "FUTURE-A" else 4)
            for segment in segments
        ], lots)

    def scoped(*args, **kwargs):
        return real_improve(*args, **kwargs, generators=[Generator("swap", swap)])

    monkeypatch.setattr(improvement, "improve_plan", scoped)
    after, report = improve_preserving_protected_lots(
        copy.deepcopy(before), data, copy.deepcopy(data), config,
        copy.deepcopy(before.segments[:1]), copy.deepcopy(before.lots[:1]),
        3, time_budget_s=10,
    )
    verdict = no_loss_verdict(
        plan_facts(after.segments, after.lots, data, after.score),
        plan_facts(before.segments, before.lots, data, before.score),
    )
    assert verdict.admissible, verdict.reasons
    assert report["moves_accepted"] == 0
    assert (data, before) == initial


def test_full_plan_context_still_accepts_a_genuine_delivery_improvement(plan, monkeypatch):
    data, config, before = plan
    real_improve = improvement.improve_plan

    def earlier(segments, lots):
        return Proposal([
            replace(segment, day_idx=3) if segment.lot_id == "FUTURE-B" else segment
            for segment in segments
        ], lots)

    def scoped(*args, **kwargs):
        return real_improve(*args, **kwargs, generators=[Generator("earlier", earlier)])

    monkeypatch.setattr(improvement, "improve_plan", scoped)
    after, report = improve_preserving_protected_lots(
        copy.deepcopy(before), data, copy.deepcopy(data), config,
        copy.deepcopy(before.segments[:1]), copy.deepcopy(before.lots[:1]),
        3, time_budget_s=10,
    )
    assert report["moves_accepted"] == 1
    assert next(s.day_idx for s in after.segments if s.lot_id == "FUTURE-B") == 3
    assert next(s for s in after.segments if s.lot_id == "PROTECTED") == before.segments[0]


def test_capacity_release_uses_the_complete_plan_contract(plan, monkeypatch):
    from backend.plans.frozen import compact_preserving_started_lots

    data, config, before = plan
    original = copy.deepcopy((data, before))
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: 3)
    after = compact_preserving_started_lots(data, config, before)
    assert no_loss_verdict(
        plan_facts(after.segments, after.lots, data, after.score),
        plan_facts(before.segments, before.lots, data, before.score),
    ).admissible
    assert after.improvement_report["reference"]["otd"] == before.score["otd"]
    assert next(s for s in after.segments if s.lot_id == "PROTECTED") == before.segments[0]
    assert (data, before) == original


@pytest.mark.parametrize("boundary", ["validation", "gates"])
def test_rejected_merged_plan_clears_accepted_summary(plan, monkeypatch, boundary):
    from backend.scheduler.improvement import physical_signature

    data, config, before = plan
    real_improve = improvement.improve_plan

    def earlier(segments, lots):
        return Proposal([
            replace(segment, day_idx=3) if segment.lot_id == "FUTURE-B" else segment
            for segment in segments
        ], lots, subject={"key": "accepted-then-rolled-back"})

    monkeypatch.setattr(improvement, "improve_plan", lambda *args, **kwargs: real_improve(
        *args, **kwargs, generators=[Generator("earlier", earlier)],
    ))
    if boundary == "validation":
        monkeypatch.setattr("backend.scheduler.validation.validate_plan", lambda segments, *a, **k: (
            [{"kind": "injected_merged_failure"}]
            if any(s.lot_id == "PROTECTED" for s in segments) else []
        ))
    else:
        monkeypatch.setattr("backend.scheduler.gates.build_gate_report", lambda *a, **k: {
            "physical_gate_passed": False, "coverage_gate_passed": False,
        })

    after, report = improve_preserving_protected_lots(
        copy.deepcopy(before), data, copy.deepcopy(data), config,
        copy.deepcopy(before.segments[:1]), copy.deepcopy(before.lots[:1]),
        3, time_budget_s=10,
    )
    assert after == before
    assert report["moves_accepted"] == 0
    assert report["accepted_by_scope"] == {}
    assert report["final"] == report["reference"]
    assert report["final_signature"] == physical_signature(before.segments, before.lots)
    assert report["rolled_back_moves"] == 1
    assert not any(entry["outcome"] == "accepted" for entry in report["proposal_log"].values())
