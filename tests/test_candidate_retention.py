"""C01/C12: a later timeout cannot discard an accepted complete scenario."""

from __future__ import annotations

import copy
from threading import Event

import pytest

from backend import planning_control as control
from backend.cpo import optimizer
from backend.plans.frozen import optimize_preserving_started_lots
from backend.scheduler.improvement import contract_verdict, improve_plan
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import ScheduleResult
from backend.scheduler.validation import assert_plan_valid
from tests.test_named_planning_workflows import CASES, named_planning_case


def opportunity(name, renamed=False):
    _, _, data, config, baseline = named_planning_case(name, renamed=renamed)
    segments, lots, report = improve_plan(
        baseline.segments, baseline.lots, data, config, time_budget_s=10,
    )
    assert report["moves_accepted"] > 0
    improved = ScheduleResult(
        segments, lots, compute_score(segments, lots, data, config), 0, [], [],
    )
    assert_plan_valid(improved.segments, data, config, lots=improved.lots)
    assert contract_verdict(
        improved.segments, baseline.segments, data,
        candidate_lots=improved.lots, reference_lots=baseline.lots,
    ).admissible
    assert optimizer._is_better_candidate(improved, baseline)
    return data, config, baseline, improved


def shadow_timeout(monkeypatch, baseline, improved, clock, event=None):
    calls = 0

    def construct(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return copy.deepcopy(baseline)
        if calls == 2:
            return copy.deepcopy(improved)
        # The next construction exhausts only the search child, not closing.
        clock[0] += control.remaining_time()
        if event is not None:
            event.set()
        control.planning_checkpoint()
        pytest.fail("Expired search unexpectedly continued")

    monkeypatch.setattr(optimizer, "_schedule_all_bounded", construct)
    monkeypatch.setattr(optimizer, "_candidate_configs", lambda config, *_a: [
        ("first-improvement", copy.deepcopy(config), {}, None),
        ("next-unfinished", copy.deepcopy(config), {}, None),
    ])


@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("renamed", [False, True])
@pytest.mark.parametrize("path", ["direct", "protected_coordinator"])
def test_timeout_keeps_last_accepted_real_candidate(monkeypatch, name, renamed, path):
    data, config, baseline, improved = opportunity(name, renamed)
    before = copy.deepcopy((data, config, baseline, improved))
    clock = [0.0]
    shadow_timeout(monkeypatch, baseline, improved, clock)
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: 0)
    seen = []
    entering_closeout = []
    from backend.plans import frozen

    closeout = frozen.improve_preserving_protected_lots

    def capture_closeout(candidate, *args, **kwargs):
        entering_closeout.append(copy.deepcopy(candidate))
        return closeout(candidate, *args, **kwargs)

    monkeypatch.setattr(frozen, "improve_preserving_protected_lots", capture_closeout)
    with control.candidate_observer(lambda r: seen.append(copy.deepcopy(r))):
        with control.planning_scope(timeout_s=60, clock=lambda: clock[0]):
            result = (optimizer.optimize(data, config=config, improve=False)
                      if path == "direct" else optimize_preserving_started_lots(
                          data, config, baseline,
                      ))
    assert result.segments == improved.segments
    assert result.lots == improved.lots
    assert_plan_valid(result.segments, data, config, lots=result.lots)
    assert (data, config, baseline, improved) == before
    if path == "direct":
        assert seen[-1].segments == improved.segments
        assert result.gate_report["solver_trace"]["final_source"] == "candidate_after_search_timeout"
    else:
        assert entering_closeout[0].segments == improved.segments
        assert result.gate_report["solver_trace"]["final_source"] == "candidate_after_search_timeout"


@pytest.mark.parametrize("mode", ["normal", "deep", "max"])
def test_polished_complete_candidate_survives_normalization_timeout(monkeypatch, mode):
    from backend.cpo import cpsat_polish

    data, config, baseline, improved = opportunity("bfp112_previous_day")
    clock = [0.0]
    before = copy.deepcopy((data, config, baseline, improved))

    def interrupted_normalization(*_args, **_kwargs):
        clock[0] += control.remaining_time()
        control.planning_checkpoint()

    monkeypatch.setattr(optimizer, "_schedule_all_bounded", lambda *_a, **_k: copy.deepcopy(baseline))
    monkeypatch.setattr(optimizer, "_candidate_configs", lambda *_a: [])
    monkeypatch.setattr(cpsat_polish, "cpsat_polish", lambda *_a, **_k: copy.deepcopy((
        improved.segments, improved.lots, improved.score,
    )))
    monkeypatch.setattr(optimizer, "_normalize_operational_result", interrupted_normalization)
    with control.planning_scope(
        timeout_s=optimizer.MODE_CONFIG[mode]["time_budget_s"], clock=lambda: clock[0],
    ):
        result = optimizer.optimize(data, mode=mode, config=config, improve=False)
    assert result.segments == improved.segments
    assert result.lots == improved.lots
    assert (data, config, baseline, improved) == before


@pytest.mark.parametrize("stop", ["cancel", "parent_timeout"])
def test_complete_improvement_never_hides_cancellation_or_parent_timeout(monkeypatch, stop):
    data, config, baseline, improved = opportunity("bfp082_initial_priority")
    clock, event = [0.0], Event()
    before = copy.deepcopy((data, config, baseline, improved))

    def search(*_args):
        control.candidate_completed(copy.deepcopy(improved))
        clock[0] = 61.0
        if stop == "cancel":
            event.set()
        control.planning_checkpoint()

    monkeypatch.setattr(optimizer, "_schedule_all_bounded", lambda *_a, **_k: copy.deepcopy(baseline))
    monkeypatch.setattr(optimizer, "_improve_baseline", search)
    error = control.PlanningCancelled if stop == "cancel" else control.PlanningTimeout
    with pytest.raises(error), control.planning_scope(
        timeout_s=60, clock=lambda: clock[0], cancel_event=event,
    ):
        optimizer.optimize(data, config=config, improve=False)
    assert (data, config, baseline, improved) == before


@pytest.mark.parametrize("invalid", ["quantity", "duration", "release", "deadline", "worse"])
def test_unusable_observed_candidate_does_not_replace_valid_baseline(monkeypatch, invalid):
    data, config, baseline, observed = opportunity("bfp112_previous_day")
    if invalid == "quantity":
        observed.segments[0].qty -= 1
    elif invalid == "duration":
        observed.lots[0].prod_min /= 2
    elif invalid == "release":
        observed.lots[0].material_release_day -= 1
    elif invalid == "deadline":
        observed.lots[0].customer_delivery_day += 1
    else:
        observed.segments[0].day_idx = 12
        observed.score = compute_score(observed.segments, observed.lots, data, config)
    clock = [0.0]

    def search(*_args):
        control.candidate_completed(observed)
        observed.segments.clear()
        clock[0] = 50.0
        control.planning_checkpoint()

    monkeypatch.setattr(optimizer, "_schedule_all_bounded", lambda *_a, **_k: copy.deepcopy(baseline))
    monkeypatch.setattr(optimizer, "_improve_baseline", search)
    with control.planning_scope(timeout_s=60, clock=lambda: clock[0]):
        result = optimizer.optimize(data, config=config, improve=False)
    assert result.segments == baseline.segments
    assert result.lots == baseline.lots
    assert result.gate_report["solver_trace"]["final_source"] == "baseline_after_search_timeout"


def test_observed_complete_candidate_is_detached_from_later_search(monkeypatch):
    data, config, baseline, improved = opportunity("bfp112_previous_day")
    expected = copy.deepcopy(improved)
    clock = [0.0]

    def search(*_args):
        control.candidate_completed(improved)
        improved.segments.clear()
        improved.score.clear()
        clock[0] = 50.0
        control.planning_checkpoint()

    monkeypatch.setattr(optimizer, "_schedule_all_bounded", lambda *_a, **_k: copy.deepcopy(baseline))
    monkeypatch.setattr(optimizer, "_improve_baseline", search)
    with control.planning_scope(timeout_s=60, clock=lambda: clock[0]):
        result = optimizer.optimize(data, config=config, improve=False)
    assert result.segments == expected.segments
    assert result.lots == expected.lots
    assert result.score["otd"] == expected.score["otd"]


def test_nested_observer_forwards_to_the_outer_owner():
    observed = []
    with control.candidate_observer(lambda r: observed.append(("outer", r))):
        with control.candidate_observer(lambda r: observed.append(("inner", r)), forward=True):
            control.candidate_completed("complete")
        control.candidate_completed("after")
    assert observed == [("inner", "complete"), ("outer", "complete"), ("outer", "after")]


def test_nested_observer_exception_restores_outer_callback():
    observed = []
    with control.candidate_observer(observed.append):
        with pytest.raises(ValueError, match="callback failed"):
            with control.candidate_observer(
                lambda _: (_ for _ in ()).throw(ValueError("callback failed")), forward=True,
            ):
                control.candidate_completed("failed")
        control.candidate_completed("after")
    assert observed == ["after"]


def test_rejected_candidate_is_not_forwarded_to_owner():
    observed = []
    with control.candidate_observer(observed.append):
        with control.candidate_observer(lambda _: False, forward=True):
            control.candidate_completed("invalid")
        control.candidate_completed("valid")
    assert observed == ["valid"]


@pytest.mark.parametrize("field", [
    "customer_delivery_day", "latest_subcontract_dispatch_day", "subcontract_dispatch_day",
    "production_due_day", "internal_target_day", "material_reference_day",
    "material_release_day", "original_edd", "delivery_day", "internal_deadline",
    "material_reference_kind", "is_subcontracted",
])
def test_scalar_milestone_cannot_disagree_with_canonical_outputs(field):
    from backend.scheduler.canonical import source_contract_violations

    data, config, _, result = opportunity("bfp112_previous_day")
    lot = result.lots[0]
    value = getattr(lot, field)
    setattr(lot, field, not value if isinstance(value, bool) else
            "mixed" if isinstance(value, str) else (value or 0) + 1)
    violations = source_contract_violations(result.segments, result.lots, data, config)
    assert any(v["kind"] == "source_contract" and v["field"] == field for v in violations)


def test_legacy_lot_cannot_disable_source_checks_of_current_lot():
    from backend.scheduler.canonical import source_contract_violations
    from backend.scheduler.lot_sizing import create_lots
    from tests.test_simulator import _engine, _eop

    data = _engine(ops=[
        _eop(op_id="OP1", sku="SKU1", d=[0, 0, 0, 300, 0, 0]),
        _eop(op_id="OP2", sku="SKU2", d=[0, 0, 0, 100, 0, 0]),
    ])
    from backend.config.types import FactoryConfig

    config = FactoryConfig()
    lots = create_lots(data, config)
    lots[0].output_milestones = None
    lots[1].output_milestones[0]["material_release_day"] -= 1
    lots[1].material_release_day -= 1
    violations = source_contract_violations([], lots, data, config)
    assert any(v["lot_id"] == lots[1].id and v["field"] == "output_milestones" for v in violations)


def test_timeout_preserves_history_and_improved_twin_continuation(monkeypatch):
    from backend.plans import frozen

    _, _, data, config, baseline = named_planning_case("bfp079_equivalent_machines")
    improved = copy.deepcopy(baseline)
    moved = next(s for s in improved.segments if s.day_idx == 4)
    moved.machine_id, moved.day_idx = "PRM039", 1
    moved.start_min, moved.end_min, moved.setup_min = 510, 570, 0
    moved.is_continuation = True
    lot = next(lot for lot in improved.lots if lot.id == moved.lot_id)
    lot.machine_id, lot.setup_min = "PRM039", 0
    improved.score = compute_score(improved.segments, improved.lots, data, config)
    assert_plan_valid(improved.segments, data, config, lots=improved.lots)
    history_ids = {s.lot_id for s in baseline.segments if s.day_idx == 0}

    def residual(result):
        result = copy.deepcopy(result)
        result.segments = [s for s in result.segments if s.lot_id not in history_ids]
        result.lots = [lot for lot in result.lots if lot.id not in history_ids]
        return result

    before = copy.deepcopy((data, config, baseline, improved))
    clock = [0.0]
    shadow_timeout(monkeypatch, residual(baseline), residual(improved), clock)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)
    entering_closeout = []
    closeout = frozen.improve_preserving_protected_lots

    def capture(candidate, *args, **kwargs):
        entering_closeout.append(copy.deepcopy(candidate))
        return closeout(candidate, *args, **kwargs)

    monkeypatch.setattr(frozen, "improve_preserving_protected_lots", capture)
    with control.planning_scope(timeout_s=60, clock=lambda: clock[0]):
        result = optimize_preserving_started_lots(data, config, baseline)
    for candidate in [entering_closeout[0], result]:
        assert next(s for s in candidate.segments if s.lot_id == moved.lot_id) == moved
        assert [s for s in candidate.segments if s.lot_id in history_ids] == [
            s for s in baseline.segments if s.lot_id in history_ids
        ]
        assert candidate.preserved_lot_proofs
    assert result.gate_report["solver_trace"]["final_source"] == "candidate_after_search_timeout"
    assert (data, config, baseline, improved) == before
