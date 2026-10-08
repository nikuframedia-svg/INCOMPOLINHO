"""Shared deadline and exact-context reuse, without live state or services."""

import copy
from dataclasses import replace
from threading import Event

import pytest

from backend import planning_control as control
from backend.cpo import optimizer
from backend.plans import frozen
from backend.scheduler import alternative_repair as repair
from tests.test_alternative_repair import _config, _data, _op, _run_and_segment
from tests.test_named_planning_workflows import named_planning_case


@pytest.mark.parametrize("path", ["direct", "protected", "compact"])
@pytest.mark.parametrize("elapsed", [0.0, 5.0, 48.0])
def test_improvement_uses_available_time_not_a_fixed_ten_seconds(monkeypatch, path, elapsed):
    _, _, data, config, baseline = named_planning_case("bfp082_initial_priority")
    now, budgets = [0.0], []
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 0)

    def improve(*args, time_budget_s, **_kwargs):
        budgets.append(time_budget_s)
        if path == "direct":
            return args[0], args[1], {"moves_accepted": 0}
        return args[0], {"moves_accepted": 0}

    monkeypatch.setattr("backend.scheduler.improvement.improve_plan", improve)
    monkeypatch.setattr(frozen, "improve_preserving_protected_lots", improve)
    with control.planning_scope(timeout_s=60, clock=lambda: now[0]):
        now[0] = elapsed
        if path == "direct":
            optimizer._apply_improvement_phase(baseline, data, config, mode="normal", seed=42)
        elif path == "protected":
            frozen.optimize_preserving_started_lots(
                data, config, baseline, optimizer=lambda *_a, **_k: copy.deepcopy(baseline),
            )
        else:
            frozen.compact_preserving_started_lots(data, config, baseline)
    assert budgets == [50.0 - elapsed]


@pytest.mark.parametrize("timeout", [12.0, 30.0])
def test_short_parent_deadline_is_not_extended(monkeypatch, timeout):
    _, _, data, config, baseline = named_planning_case("bfp082_initial_priority")
    budgets = []
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 0)

    def improve(result, *_args, time_budget_s):
        budgets.append(time_budget_s)
        return result, {"moves_accepted": 0}

    monkeypatch.setattr(frozen, "improve_preserving_protected_lots", improve)
    with control.planning_scope(timeout_s=timeout):
        frozen.compact_preserving_started_lots(data, config, baseline)
    assert 0 < budgets[0] <= timeout - 10


def test_legacy_search_reserves_time_after_a_complete_candidate_exists(monkeypatch):
    _, _, data, config, baseline = named_planning_case("bfp082_initial_priority")
    now, observed = [0.0], {}

    def construct(*_args, **_kwargs):
        observed["construction"] = control.remaining_time()
        now[0] = 15.0
        return copy.deepcopy(baseline)

    def search(*_args):
        observed["search"] = control.remaining_time()
        now[0] += observed["search"]
        control.planning_checkpoint()

    monkeypatch.setattr(optimizer, "_schedule_all_bounded", construct)
    monkeypatch.setattr(optimizer, "_improve_baseline", search)
    monkeypatch.setattr(optimizer, "_apply_improvement_phase", lambda *_a, **_k: None)
    with control.planning_scope(timeout_s=60, clock=lambda: now[0]):
        result = optimizer.optimize(data, config=config)
        observed["remaining"] = control.remaining_time()
    assert observed["construction"] == 60
    assert 0 < observed["search"] < 15
    assert observed["remaining"] >= 30
    assert result.segments == baseline.segments


def _placement_case():
    op = _op("A", demand_day=3)
    run, _lot, _segment = _run_and_segment(op, due=3)
    return run, _data([op]), _config()


def test_identical_allocation_is_reused_but_returned_as_a_detached_copy(monkeypatch):
    run, data, config = _placement_case()
    calls = []
    allocate = repair._schedule_run_earliest

    def counted(*args, **kwargs):
        calls.append(True)
        return allocate(*args, **kwargs)

    monkeypatch.setattr(repair, "_schedule_run_earliest", counted)
    with control.planning_scope(timeout_s=5):
        search = repair._PlacementSearch(data, config)
        first = search.place(run, "M1", [])
        expected = copy.deepcopy(first)
        first[1][0].qty = -1
        second = repair._PlacementSearch(copy.deepcopy(data), copy.deepcopy(config)).place(
            copy.deepcopy(run), "M1", [],
        )
    assert second == expected
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["oee", "operators", "calendar", "material", "mount", "floor"])
def test_cache_invalidates_every_changed_allocation_input(monkeypatch, change):
    run, data, config = _placement_case()
    calls = []
    allocate = repair._schedule_run_earliest
    monkeypatch.setattr(repair, "_schedule_run_earliest", lambda *a, **k: (
        calls.append(True) or allocate(*a, **k)))
    with control.planning_scope(timeout_s=5):
        repair._PlacementSearch(data, config).place(run, "M1", [])
        fixed, floor = [], None
        if change == "oee":
            config.machines["M1"].oee = 0.5
        elif change == "operators":
            config.operators[("Grandes", "A")] = 0
        elif change == "calendar":
            data.machine_blocked_days["M1"] = {0}
        elif change == "material":
            run.lots[0].material_release_day = 1
        elif change == "mount":
            _other, _lot, segment = _run_and_segment(_op("B", tool="T2", demand_day=3), due=3)
            fixed = [replace(segment, day_idx=0)]
        else:
            floor = 1440
        repair._PlacementSearch(data, config).place(run, "M1", fixed, not_before_abs=floor)
    assert len(calls) == 2


def test_cached_allocation_still_checks_cancellation():
    run, data, config = _placement_case()
    event = Event()
    with control.planning_scope(timeout_s=5, cancel_event=event):
        search = repair._PlacementSearch(data, config)
        search.place(run, "M1", [])
        event.set()
        with pytest.raises(control.PlanningCancelled):
            search.place(run, "M1", [])
        event.clear()


@pytest.mark.parametrize("day", [0, 2])
def test_incremental_reuse_only_ignores_work_after_the_completed_search(monkeypatch, day):
    run, data, config = _placement_case()
    _other, _lot, fixed = _run_and_segment(_op("B", tool="T2", demand_day=3), day=day, due=3)
    calls = []
    allocate = repair._schedule_run_earliest
    monkeypatch.setattr(repair, "_schedule_run_earliest", lambda *a, **k: (
        calls.append(True) or allocate(*a, **k)))
    with control.planning_scope(timeout_s=5):
        search = repair._PlacementSearch(data, config)
        search.place(run, "M2", [fixed])
        changed = replace(fixed, start_min=600, end_min=690)
        reused = search.place(run, "M2", [changed])
        cold = allocate(run, "M2", [changed], data, config)
    assert reused == cold
    assert len(calls) == (2 if day == 0 else 1)


@pytest.mark.parametrize("duration", [60, 600, 1600])
@pytest.mark.parametrize("machine", ["M1", "M2"])
@pytest.mark.parametrize("tool", ["T1", "T2"])
@pytest.mark.parametrize("day", [0, 1, 3])
def test_incremental_allocation_matches_a_cold_search(duration, machine, tool, day):
    run, data, config = _placement_case()
    run.lots[0].prod_min = run.total_prod_min = duration
    run.total_min = duration + run.setup_min
    _other, _lot, fixed = _run_and_segment(_op("B", tool=tool, demand_day=3), day=day, due=3)
    fixed = replace(fixed, machine_id=machine)
    config.operators[("Grandes", "A")] = 1
    config.operators[("Grandes", "B")] = 1
    with control.planning_scope(timeout_s=5):
        search = repair._PlacementSearch(data, config)
        search.place(run, "M1", [fixed])
        for changed in (replace(fixed, start_min=600, end_min=690),
                        replace(fixed, day_idx=(day + 1) % 4)):
            cached = search.place(run, "M1", [changed])
            cold = repair._schedule_run_earliest(run, "M1", [changed], data, config)
            assert cached == cold


def test_failed_allocations_keep_dependencies_on_the_entire_horizon(monkeypatch):
    run, data, config = _placement_case()
    _other, _lot, fixed = _run_and_segment(_op("B", demand_day=3), day=3, due=3)
    calls = []
    monkeypatch.setattr(repair, "_schedule_run_earliest", lambda *_a, **_k: calls.append(True))
    with control.planning_scope(timeout_s=5):
        search = repair._PlacementSearch(data, config)
        assert search.place(run, "M1", [fixed]) is None
        assert search.place(run, "M1", [fixed]) is None
        assert search.place(run, "M1", [replace(fixed, start_min=600)]) is None
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["none", "quantity", "time", "material", "setup", "metadata"])
def test_protected_digest_reuse_checks_every_field(monkeypatch, change):
    from backend.scheduler import canonical
    from backend.plans.serialize import schedule_fingerprint

    run, _data, _config = _placement_case()
    lot = run.lots[0]
    _run, _lot, segment = _run_and_segment(_op("A", demand_day=3), due=3)
    calls = []

    def fingerprint(*args):
        calls.append(True)
        return schedule_fingerprint(*args)

    monkeypatch.setattr(canonical, "schedule_fingerprint", fingerprint)
    with control.planning_scope(timeout_s=5):
        canonical.preserved_lot_proofs([segment], [lot])
        actual_lot, actual_segment = copy.deepcopy((lot, segment))
        if change == "quantity":
            actual_lot.qty += 1
        elif change == "time":
            actual_segment.start_min += 1
        elif change == "material":
            actual_lot.material_release_day = 2
        elif change == "setup":
            actual_segment.run_setup_min += 1
        elif change == "metadata":
            actual_segment.left_shift_blockers.append("changed")
        reused = canonical.preserved_lot_proofs([actual_segment], [actual_lot])
        assert reused[lot.id] == schedule_fingerprint([actual_segment], [actual_lot])
    assert len(calls) == (1 if change == "none" else 2)


def test_placement_cache_is_bounded_and_does_not_cross_executions(monkeypatch):
    run, data, config = _placement_case()
    calls = []
    monkeypatch.setattr(repair, "PLACEMENT_CACHE_LIMIT", 2)
    monkeypatch.setattr(repair, "_schedule_run_earliest", lambda *_a, **_k: calls.append(True))
    with control.planning_scope(timeout_s=5):
        search = repair._PlacementSearch(data, config)
        for floor in (None, 1440, 2880, None):
            search.place(run, "M1", [], not_before_abs=floor)
        assert len(search.entries) == 2
    with control.planning_scope(timeout_s=5):
        repair._PlacementSearch(data, config).place(run, "M1", [])
    assert len(calls) == 5


@pytest.mark.parametrize("size", [2, 3])
def test_group_reinsertion_reuses_prefixes_without_changing_proposals(monkeypatch, size):
    from backend.scheduler.improvement import Proposal, physical_signature

    ops = [_op(name, tool=name, demand_day=3) for name in ("A", "B", "C")]
    rows = [_run_and_segment(op, day=2, due=3) for op in ops]
    lots = [row[1] for row in rows]
    segments = [replace(row[2], start_min=420 + index * 90, end_min=510 + index * 90)
                for index, row in enumerate(rows)]
    data, config = _data(ops), _config()
    original = copy.deepcopy((segments, lots, data, config))

    def proposals():
        return list(repair.group_reinsertion_proposals(segments, lots, data, config, size=size))

    with control.planning_scope(timeout_s=5):
        cached = proposals()
        assert proposals() == cached
        stats = control.execution_cache("run_placement")["stats"]
        assert stats["hits"] > 0
    monkeypatch.setattr(repair, "PLACEMENT_CACHE_LIMIT", 0)
    with control.planning_scope(timeout_s=5):
        uncached = proposals()
        assert control.execution_cache("run_placement")["stats"]["hits"] == 0
    assert [physical_signature(p.segments, p.lots) if isinstance(p, Proposal) else p
            for p in cached] == [
        physical_signature(p.segments, p.lots) if isinstance(p, Proposal) else p for p in uncached
    ]
    assert (segments, lots, data, config) == original
