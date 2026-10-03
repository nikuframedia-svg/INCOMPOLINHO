"""Retained mounting must release setup time before candidate allocation."""

from __future__ import annotations

import copy
from dataclasses import replace
from threading import Event

import pytest

from backend.scheduler.alternative_repair import _resolve_runs, _schedule_run_earliest
from backend.planning_control import PlanningCancelled, planning_scope
from backend.scheduler.canonical import preserved_lot_proofs
from backend.scheduler.improvement import improve_plan, no_loss_verdict, physical_setups, plan_facts
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import ScheduleResult
from backend.scheduler.validation import validate_plan
from tests.test_transfer_consolidation import _config, _data, _lot, _only_consolidation, _op, _seg


def _retained_capacity_case(prefix="P"):
    op = _op(prefix, "T", {0: 30, 1: 30}, rate=60)
    other_op = _op(f"{prefix}-U", "U", {1: 950}, rate=60, alt=None)
    head = _lot(op, f"{prefix}-HEAD", qty=30, prod_min=30, due=0)
    incoming = _lot(op, f"{prefix}-INCOMING", qty=30, prod_min=30, due=1)
    incoming.machine_id, incoming.alt_machine_id = "M2", "M1"
    incoming.material_release_day = 1
    other = _lot(other_op, f"{prefix}-OTHER", qty=950, prod_min=950, due=1)
    other.material_release_day = 1
    segments = [
        _seg(head, "HEAD", "M1", 0, 420, 480, setup=30, prod=30, qty=30),
        _seg(other, "OTHER", "M1", 1, 450, 930, setup=30, prod=450, qty=450),
        _seg(other, "OTHER", "M1", 1, 930, 1430, setup=0, prod=500, qty=500),
        _seg(incoming, "INCOMING", "M2", 1, 480, 540, setup=30, prod=30, qty=30),
    ]
    lots = [head, incoming, other]
    data, config = _data([op, other_op]), _config()
    data.preserved_lot_proofs = preserved_lot_proofs([segments[0]], [head])
    return segments, lots, data, config


def _facts(segments, lots, data, config):
    return plan_facts(segments, lots, data, compute_score(segments, lots, data, config))


def _allocation(segments):
    return [(s.lot_id, s.machine_id, s.tool_id, s.day_idx, s.start_min, s.end_min,
             s.setup_min, s.prod_min, s.qty) for s in segments]


@pytest.mark.parametrize("prefix", ["P", "RENAMED"])
def test_complete_retained_mount_witness_is_legal_without_delivery_loss(prefix):
    segments, lots, data, config = _retained_capacity_case(prefix)
    witness_lots = [replace(lot, machine_id="M1", alt_machine_id="M2")
                    if lot.id.endswith("INCOMING") else lot for lot in lots]
    witness = [replace(segment, machine_id="M1", start_min=420, end_min=450, setup_min=0)
               if segment.run_id == "INCOMING" else segment for segment in segments]
    assert not validate_plan(segments, data, config, lots=lots)
    assert not validate_plan(witness, data, config, lots=witness_lots)
    assert no_loss_verdict(_facts(witness, witness_lots, data, config),
                           _facts(segments, lots, data, config)).admissible
    assert physical_setups(witness).count == physical_setups(segments).count - 1


def test_shared_earliest_allocator_reclaims_retained_setup_time_before_production():
    segments, lots, data, config = _retained_capacity_case()
    before = copy.deepcopy((segments, lots, data, config))
    run = _resolve_runs(segments, lots, None)["INCOMING"]
    scheduled = _schedule_run_earliest(run, "M1", segments[:1], data, config)
    assert scheduled is not None
    rebound, created = scheduled
    assert [(s.day_idx, s.start_min, s.end_min, s.setup_min, s.qty) for s in created] == [
        (1, 420, 450, 0, 30),
    ]
    assert rebound.setup_min == 30  # Nominal setup remains available for later moves.
    assert rebound.lots[0].setup_min == 30
    assert (segments, lots, data, config) == before


@pytest.mark.parametrize("prefix", ["P", "RENAMED"])
def test_transfer_comparison_preserves_deliveries_by_allocating_without_phantom_setup(prefix):
    segments, lots, data, config = _retained_capacity_case(prefix)
    before = copy.deepcopy((segments, lots, data, config))
    improved, improved_lots, report = improve_plan(
        segments, lots, data, config, generators=_only_consolidation(data, config),
    )
    assert report["moves_accepted"] >= 1, report
    assert [(s.machine_id, s.day_idx, s.start_min, s.end_min, s.setup_min)
            for s in improved if s.run_id == "INCOMING"] == [("M1", 1, 420, 450, 0)]
    assert _allocation([s for s in improved if s.run_id == "OTHER"]) == _allocation(segments[1:3])
    assert [s for s in improved if s.run_id == "HEAD"] == segments[:1]
    assert not validate_plan(improved, data, config, lots=improved_lots)
    assert no_loss_verdict(_facts(improved, improved_lots, data, config),
                           _facts(segments, lots, data, config)).admissible
    assert (segments, lots, data, config) == before
    again, again_lots, second = improve_plan(
        improved, improved_lots, data, config, generators=_only_consolidation(data, config),
    )
    assert second["moves_accepted"] == 0
    assert (again, again_lots) == (improved, improved_lots)


@pytest.mark.parametrize("break_mount", ["cold", "reference", "moved_tool", "incomplete_setup"])
def test_setup_is_not_removed_without_proof_of_the_same_mounted_adjustment(break_mount):
    segments, lots, data, config = _retained_capacity_case()
    fixed = segments[:1]
    if break_mount == "cold":
        fixed = []
    elif break_mount == "reference":
        fixed = [replace(fixed[0], sku="ANOTHER-ADJUSTMENT")]
    elif break_mount == "moved_tool":
        fixed = [*fixed, replace(fixed[0], machine_id="M2", start_min=510, end_min=570,
                                 run_id="TOOL-REMOUNTED")]
    else:
        fixed = [replace(fixed[0], end_min=435, setup_min=15, prod_min=0, qty=0)]
    run = _resolve_runs(segments, lots, None)["INCOMING"]
    scheduled = _schedule_run_earliest(run, "M1", fixed, data, config)
    assert scheduled is not None
    assert [(s.day_idx, s.start_min, s.production_start_min, s.setup_min)
            for s in scheduled[1]] == [(1, 420, 450, 30)]


@pytest.mark.parametrize("identity", ["family", "twins"])
def test_retention_uses_the_shared_family_and_twin_setup_identity(identity):
    segments, lots, data, config = _retained_capacity_case()
    if identity == "family":
        segments[0].sku = "COMPATIBLE-REFERENCE"
        segments[0].setup_family = lots[1].setup_family = "SHARED"
    else:
        outputs = [("A", "PART-A", 30), ("B", "PART-B", 60)]
        for op_id, sku, quantity in outputs:
            twin_op = _op(op_id, "T", {1: quantity}, rate=quantity * 2)
            twin_op.sku = sku
            data.ops.append(twin_op)
        segments[0].twin_outputs = outputs
        lots[1].twin_outputs = list(reversed(outputs))
        lots[1].is_twin = True
    run = _resolve_runs(segments, lots, None)["INCOMING"]
    scheduled = _schedule_run_earliest(run, "M1", segments[:1], data, config)
    assert scheduled is not None
    assert [(s.day_idx, s.start_min, s.end_min, s.setup_min)
            for s in scheduled[1]] == [(1, 420, 450, 0)]
    if identity == "twins":
        assert scheduled[1][0].twin_outputs == lots[1].twin_outputs


@pytest.mark.parametrize("blocker", ["crew", "operators", "machine", "tool"])
def test_retained_start_respects_actual_capacity_instead_of_setup_crew_availability(blocker):
    segments, lots, data, config = _retained_capacity_case()
    block = {"start_day": 1, "end_day": 1, "start_min": 420, "end_min": 500}
    if blocker == "crew":
        data.setup_crew_reservations = [{**block, "id": "RESERVED", "machine_id": "M2", "tool_id": "RESERVED",
                                        "group": "Grandes"}]
    elif blocker == "operators":
        config.operators[("Grandes", "A")] = 1
        data.operator_blocked_intervals = [{**block, "group": "Grandes", "shift": "A", "count": 1}]
    elif blocker == "machine":
        data.machine_blocked_intervals = {"M1": [block]}
    else:
        data.tool_blocked_intervals = {"T": [block]}
    before = copy.deepcopy((segments, lots, data, config))
    run = _resolve_runs(segments, lots, None)["INCOMING"]
    scheduled = _schedule_run_earliest(run, "M1", segments[:1], data, config)
    assert scheduled is not None
    expected_start = 420 if blocker == "crew" else 500
    assert [(s.day_idx, s.start_min, s.end_min, s.setup_min) for s in scheduled[1]] == [
        (1, expected_start, expected_start + 30, 0),
    ]
    assert (segments, lots, data, config) == before


@pytest.mark.parametrize("mounted", [False, True])
@pytest.mark.parametrize("blocked_until", [420, 437, 491])
def test_retained_allocator_matches_a_finite_legal_start_oracle(mounted, blocked_until):
    from backend.scheduler.gap_filling import evaluate_legal_interval

    segments, lots, data, config = _retained_capacity_case()
    fixed = segments[:1] if mounted else []
    incoming = lots[1]
    incoming.machine_id, incoming.alt_machine_id = "M1", "M2"
    config.operators[("Grandes", "A")] = 1
    data.operator_blocked_intervals = [{"start_day": 1, "end_day": 1, "start_min": 420,
                                       "end_min": blocked_until, "group": "Grandes",
                                       "shift": "A", "count": 1}]
    template = replace(segments[-1], machine_id="M1")
    setup = 0 if mounted else 30
    legal = [start for start in range(420, 600) if evaluate_legal_interval(
        fixed, template, data, config, 1, start, start + setup + 30,
        setup_min=setup, moving_lot=incoming, lots_by_id={lot.id: lot for lot in lots},
        ignored_lot_ids={incoming.id},
    ).allowed]
    assert legal
    run = _resolve_runs(segments, lots, None)["INCOMING"]
    scheduled = _schedule_run_earliest(run, "M1", fixed, data, config)
    assert scheduled is not None
    first = scheduled[1][0]
    assert (first.day_idx, first.start_min, first.setup_min) == (1, min(legal), setup)


def test_retained_search_does_not_bypass_cancellation():
    segments, lots, data, config = _retained_capacity_case()
    run = _resolve_runs(segments, lots, None)["INCOMING"]
    cancelled = Event()
    with planning_scope(cancel_event=cancelled):
        cancelled.set()
        with pytest.raises(PlanningCancelled):
            _schedule_run_earliest(run, "M1", segments[:1], data, config)
        cancelled.clear()


@pytest.mark.parametrize("prefix", ["P", "RENAMED"])
def test_protected_residual_boundary_keeps_the_mounting_context_for_transfer_search(prefix):
    from backend.plans.frozen import improve_preserving_protected_lots

    segments, lots, data, config = _retained_capacity_case(prefix)
    # INCOMING and OTHER share the due day; the transfer delays OTHER by its
    # setup. Under contract v2 (anticipation before setups) it is a gain only
    # when INCOMING ranks first commercially.
    for lot in lots:
        if lot.id.endswith("INCOMING"):
            lot.planning_priority = 1
    for segment in segments:
        if segment.run_id == "INCOMING":
            segment.planning_priority = 1
    # Protection comes from the coordinator, not an inferred past date or
    # a pre-existing proof on EngineData.
    data.preserved_lot_proofs = {}
    before = copy.deepcopy((segments, lots, data, config))
    result = ScheduleResult(copy.deepcopy(segments), copy.deepcopy(lots),
                            compute_score(segments, lots, data, config), 0, [], [])
    improved, report = improve_preserving_protected_lots(
        result, data, copy.deepcopy(data), config, copy.deepcopy(segments[:1]),
        copy.deepcopy(lots[:1]), 0, time_budget_s=5,
    )
    # Either machine-aware neighbourhood must see the retained mount across
    # the protected boundary; N1 now runs before the transfer search.
    accepted = report["accepted_by_scope"]
    assert accepted.get("tool_transfers", 0) + accepted.get("alternative_anticipation", 0) >= 1
    assert [s for s in improved.segments if s.run_id == "HEAD"] == segments[:1]
    assert [(s.machine_id, s.day_idx, s.start_min, s.end_min, s.setup_min)
            for s in improved.segments if s.run_id == "INCOMING"] == [("M1", 1, 420, 450, 0)]
    assert not validate_plan(improved.segments, data, config, lots=improved.lots)
    assert no_loss_verdict(_facts(improved.segments, improved.lots, data, config),
                           _facts(segments, lots, data, config)).admissible
    assert (segments, lots, data, config) == before


@pytest.mark.parametrize("scope", ["tool_transfers", "alternative_machine"])
@pytest.mark.parametrize("change", ["allocation", "quantity"])
def test_complete_context_projection_cannot_hide_a_change_to_protected_production(
    monkeypatch, scope, change,
):
    from backend.scheduler.improvement import Proposal, SkippedProposal, default_generators
    from backend.scheduler.alternative_repair import AlternativeRepairResult

    segments, lots, data, config = _retained_capacity_case()
    before = copy.deepcopy((segments, lots, data, config))

    def attempt(complete_segments, complete_lots, complete_data, *_args):
        assert "P-HEAD" in complete_data.preserved_lot_proofs
        assert complete_data.operator_blocked_intervals == []
        changed_segments, changed_lots = copy.deepcopy((complete_segments, complete_lots))
        if change == "allocation":
            next(s for s in changed_segments if s.run_id == "HEAD").start_min += 1
        else:
            next(lot for lot in changed_lots if lot.id == "P-HEAD").qty += 1
        if scope == "tool_transfers":
            return iter([Proposal(changed_segments, changed_lots, subject={"key": "unsafe"})])
        return AlternativeRepairResult(changed_segments, changed_lots, {}, {})

    target = ("backend.scheduler.transfer_consolidation.consolidation_proposals"
              if scope == "tool_transfers"
              else "backend.scheduler.alternative_repair.repair_alternative_machine_delivery")
    monkeypatch.setattr(target, attempt)

    def complete_context(residual_segments, residual_lots):
        return ([*copy.deepcopy(segments[:1]), *residual_segments],
                [*copy.deepcopy(lots[:1]), *residual_lots], data)

    generator = next(g for g in default_generators(data, config, evaluation_plan=complete_context)
                     if g.name == scope)
    proposed = list(generator.propose(copy.deepcopy(segments[1:]), copy.deepcopy(lots[1:])))
    assert len(proposed) == 1
    assert isinstance(proposed[0], SkippedProposal)
    assert proposed[0].reason == "protected_context_changed"
    assert (segments, lots, data, config) == before
