"""Whole-started-lot planning and temporary resource reservations."""

import copy
import threading
from datetime import datetime, timezone

import pytest

# Modules that bind ``compute_score`` at import must be loaded before a test
# monkeypatches ``backend.scheduler.scoring.compute_score``; otherwise they keep
# the fake for the rest of the session.
import backend.scheduler.transfer_consolidation  # noqa: F401
from backend.config.types import FactoryConfig, MachineConfig
from backend.plans import frozen
from backend.plans.explanations import plan_view_explanations
from backend.planning_control import PlanningCancelled, PlanningTimeout, current_planning_control
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.types import EOp, EngineData, MachineInfo, PlanAnchor


@pytest.fixture
def frozen_plan():
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    data = EngineData(
        ops=[EOp(
            id="OP1", sku="SKU1", client="C", designation="Part", m="M1", t="T1",
            pH=100, sH=.5, operators=2, eco_lot=0, alt=None, stk=0, backlog=0,
            d=[100, 0, 0], oee=.66, wip=0,
        )],
        machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[], client_demands={},
        workdays=["2026-09-16", "2026-09-17", "2026-09-18"], n_days=3, holidays=[],
    )
    lot = Lot("L1", "OP1", "T1", "M1", None, 100, 600, 30, 2, False, sku="SKU1")
    segments = [
        Segment("L1", "R1", "M1", "T1", 0, 420, 510, "A", 10, 60, 30, sku="SKU1"),
        Segment("L1", "R1", "M1", "T1", 1, 420, 990, "A", 90, 540, 30, sku="SKU1"),
    ]
    result = ScheduleResult(segments=segments, lots=[lot], score={}, time_ms=0,
                            warnings=[], operator_alerts=[])
    return data, config, result


def test_current_day_preserves_historical_future_and_day_boundary_semantics(frozen_plan):
    data, config, _ = frozen_plan
    for day, expected in ((15, 0), (16, 0), (17, 1), (18, 2), (19, 0)):
        now = datetime(2026, 9, day, 12, tzinfo=timezone.utc)
        assert frozen._current_planning_day(data, config, now=now) == expected


def test_started_lot_includes_all_future_segments_but_not_unstarted_lots(frozen_plan):
    _, _, baseline = frozen_plan
    future = copy.deepcopy(baseline.lots[0])
    future.id = "L2"
    baseline.lots.append(future)
    future_segment = copy.deepcopy(baseline.segments[-1])
    future_segment.lot_id = "L2"
    baseline.segments.append(future_segment)
    segments, lots = frozen._frozen_started_lots(baseline, 1)
    assert [s.day_idx for s in segments] == [0, 1]
    assert [lot.id for lot in lots] == ["L1"]
    segments[0].qty = 999
    assert baseline.segments[0].qty == 10


def test_historical_guard_keeps_future_continuations_but_allows_metadata(frozen_plan):
    from dataclasses import asdict

    data, config, result = frozen_plan
    before = {
        "dataset_info": {"id": "same-isop"},
        "config": asdict(config),
        "engine_data": asdict(data),
        "segments": [asdict(item) for item in result.segments],
        "lots": [asdict(item) for item in result.lots],
    }
    after = copy.deepcopy(before)
    after["segments"][1]["left_shift_blockers"] = ["new explanation"]
    assert frozen.historical_schedule_changes(before, after, today="2026-09-17") == []
    after["segments"][1]["start_min"] += 10
    assert frozen.historical_schedule_changes(before, after, today="2026-09-17") == ["L1"]
    after["dataset_info"]["id"] = "new-isop"
    assert frozen.historical_schedule_changes(before, after, today="2026-09-17") == []


def test_historical_guard_catches_calendar_remapping_and_expired_horizon(frozen_plan):
    from dataclasses import asdict

    data, config, result = frozen_plan
    before = {
        "dataset_info": {"id": "same-isop"},
        "config": asdict(config),
        "engine_data": asdict(data),
        "segments": [asdict(item) for item in result.segments],
        "lots": [asdict(item) for item in result.lots],
    }
    after = copy.deepcopy(before)
    after["engine_data"]["workdays"][0] = "2026-09-15"
    assert frozen.historical_schedule_changes(before, after, today="2026-09-17") == ["L1"]

    after = copy.deepcopy(before)
    after["segments"][0]["start_min"] += 10
    assert frozen.historical_schedule_changes(before, after, today="2026-09-19") == ["L1"]


def test_historical_guard_rejects_new_production_in_the_past(frozen_plan):
    from dataclasses import asdict

    data, config, result = frozen_plan
    before = {
        "dataset_info": {"id": "same-isop"},
        "config": asdict(config),
        "engine_data": asdict(data),
        "segments": [],
        "lots": [],
    }
    after = copy.deepcopy(before)
    after["segments"] = [asdict(result.segments[0])]
    after["lots"] = [asdict(result.lots[0])]
    assert frozen.historical_schedule_changes(before, after, today="2026-09-17") == ["L1"]
    assert frozen.historical_schedule_changes(before, after, today="2026-09-16") == []


def test_plan_view_does_not_reuse_historical_blockers_or_hide_manual_anchor(
    frozen_plan, monkeypatch,
):
    data, config, result = frozen_plan
    result.segments[0].left_shift_blockers = ["blocked_by_setup_crew|obsolete"]
    data.plan_anchors = [PlanAnchor("L1", "M1", "2026-09-17T07:30", "teste", "utilizador")]
    monkeypatch.setattr("backend.plans.explanations._current_planning_day", lambda *_: 1)

    segments, placement = plan_view_explanations(result.segments, result.lots, data, config)

    assert segments[0]["left_shift_blockers"] == []
    assert result.segments[0].left_shift_blockers == ["blocked_by_setup_crew|obsolete"]
    assert placement["L1"] == {
        "kind": "manual", "machine_id": "M1", "start_at": "2026-09-17T07:30",
        "reason": "teste", "historical": True,
    }


def test_splice_namespaces_residual_run_ids_that_collide_with_history(frozen_plan):
    _, _, baseline = frozen_plan
    future_lot = copy.deepcopy(baseline.lots[0])
    future_lot.id = "L2"
    future_segment = copy.deepcopy(baseline.segments[0])
    future_segment.lot_id = "L2"
    future_segment.day_idx = 2
    result = ScheduleResult(
        segments=[future_segment], lots=[future_lot], score={}, time_ms=0,
        warnings=[], operator_alerts=[],
    )

    merged = frozen._splice_frozen_started_lots(
        result,
        copy.deepcopy(baseline.segments),
        copy.deepcopy(baseline.lots),
    )

    historical_ids = {segment.run_id for segment in merged.segments if segment.lot_id == "L1"}
    residual_ids = {segment.run_id for segment in merged.segments if segment.lot_id == "L2"}
    assert historical_ids == {"R1"}
    assert residual_ids == {"R1__replanned_1"}
    assert historical_ids.isdisjoint(residual_ids)


def test_operator_reservations_cover_production_only_and_split_shifts(frozen_plan):
    data, config, baseline = frozen_plan
    before = copy.deepcopy(data)
    snapshot = frozen._install_frozen_reservations(data, baseline.segments, baseline.lots, 1, config)
    assert data.holidays == before.holidays
    assert 0 in data.machine_blocked_days["M1"]
    assert data.committed_supplies[0].qty == 100
    assert data.committed_supplies[0].available_day == 0
    assert data.machine_blocked_intervals["M1"][0]["start_min"] == 420
    assert [(b["shift"], b["start_min"], b["end_min"], b["count"])
            for b in data.operator_blocked_intervals] == [("A", 450, 930, 2), ("B", 930, 990, 2)]
    frozen._restore_frozen_reservations(data, snapshot)
    assert data == before


def test_twin_reservations_use_peak_headcount_and_preserve_each_output(frozen_plan):
    data, config, baseline = frozen_plan
    second = copy.deepcopy(data.ops[0])
    second.id, second.sku, second.operators = "OP2", "SKU2", 3
    data.ops.append(second)
    outputs = [("OP1", "SKU1", 100), ("OP2", "SKU2", 200)]
    baseline.lots[0].twin_outputs = outputs
    for segment in baseline.segments:
        segment.twin_outputs = outputs
    frozen._install_frozen_reservations(data, baseline.segments, baseline.lots, 1, config)
    assert {block["count"] for block in data.operator_blocked_intervals} == {3}
    assert [(s.op_id, s.qty) for s in data.committed_supplies] == [("OP1", 100), ("OP2", 200)]


def test_setup_only_segments_do_not_reserve_production_operators(frozen_plan):
    data, config, baseline = frozen_plan
    baseline.segments[-1].prod_min = 0
    baseline.segments[-1].qty = 0
    frozen._install_frozen_reservations(data, baseline.segments, baseline.lots, 1, config)
    assert data.machine_blocked_intervals and data.tool_blocked_intervals
    assert data.operator_blocked_intervals == []


def test_frozen_setup_reserves_crew_and_advances_new_setup_start(frozen_plan):
    from backend.scheduler.global_jit import _find_preemptive_setup_slot

    data, config, baseline = frozen_plan
    config.machines["M2"] = MachineConfig("M2", "Grandes")
    data.machines.append(MachineInfo("M2", "Grandes", 1020))
    before = copy.deepcopy(data)
    snapshot = frozen._install_frozen_reservations(data, baseline.segments, baseline.lots, 1, config)
    assert [(r["start_day"], r["start_min"], r["end_min"])
            for r in data.setup_crew_reservations] == [(1, 420, 450)]
    slot = _find_preemptive_setup_slot([], data, config, "M2", "T2", 1, 30, 1440 + 420, 1, set())
    assert slot == (1, 450, 480)
    frozen._restore_frozen_reservations(data, snapshot)
    assert data == before


def test_zero_output_production_fragment_still_reserves_operators(frozen_plan):
    data, config, baseline = frozen_plan
    baseline.segments[-1].qty = 0
    assert baseline.segments[-1].prod_min > 0
    frozen._install_frozen_reservations(data, baseline.segments, baseline.lots, 1, config)
    assert [(block["start_min"], block["end_min"], block["count"])
            for block in data.operator_blocked_intervals] == [(450, 930, 2), (930, 990, 2)]


@pytest.mark.parametrize("outcome", ["error", "cancel_before", "cancel_after"])
def test_temporary_reservations_are_restored_on_failure_or_cancellation(
    frozen_plan, monkeypatch, outcome,
):
    data, config, baseline = frozen_plan
    before = copy.deepcopy(data)
    cancel = threading.Event()
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)
    if outcome == "cancel_before":
        cancel.set()

    def optimize(*args, **kwargs):
        assert outcome != "cancel_before"
        assert data.operator_blocked_intervals
        if outcome == "error":
            raise ValueError("solver failure")
        cancel.set()
        return copy.deepcopy(baseline)

    monkeypatch.setattr("backend.cpo.optimize", optimize)
    with pytest.raises(ValueError if outcome == "error" else PlanningCancelled):
        frozen.optimize_preserving_started_lots(data, config, baseline, cancel_event=cancel)
    assert data == before


def test_optimizer_splices_exact_whole_lot_then_rescores_without_reservations(
    frozen_plan, monkeypatch,
):
    data, config, baseline = frozen_plan
    before = copy.deepcopy((data, baseline))
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)
    calls = []

    def optimize(engine, **kwargs):
        assert engine.operator_blocked_intervals and engine.committed_supplies
        # The improvement cycle is deferred to the residual plan (plan-melhoria §6.2).
        assert kwargs == {"mode": "quick", "audit": True, "config": config, "cancel_event": None,
                          "improve": False}
        return ScheduleResult(segments=[], lots=[], score={"otd": 100.0}, time_ms=1,
                              warnings=[], operator_alerts=[])

    def score(segments, lots, engine, **kwargs):
        assert not engine.operator_blocked_intervals and not engine.committed_supplies
        assert segments == baseline.segments and lots == baseline.lots
        calls.append("score")
        return {"rescored": True}

    monkeypatch.setattr("backend.cpo.optimize", optimize)

    def robustness(*_args, **_kwargs):
        raise AssertionError("robustness is informational and never runs in planning")

    monkeypatch.setattr("backend.risk.robustness.run_robustness_battery", robustness)
    monkeypatch.setattr("backend.scheduler.scoring.compute_score", score)
    monkeypatch.setattr("backend.scheduler.validation.assert_plan_valid", lambda *a, **k: calls.append("valid"))
    monkeypatch.setattr("backend.scheduler.gates.build_gate_report", lambda *a: {
        "status": "applicable", "physical_gate_passed": True, "coverage_gate_passed": True,
    })
    result = frozen.optimize_preserving_started_lots(data, config, baseline, mode="quick", audit=True)
    assert result.score == {"rescored": True}
    assert calls == ["score", "valid"]
    assert (data, baseline) == before
    assert result.segments == baseline.segments


@pytest.mark.parametrize("stage", ["score", "validation", "gates"])
def test_final_merged_plan_checks_share_total_deadline(frozen_plan, monkeypatch, stage):
    from backend.planning_control import planning_checkpoint, planning_scope

    data, config, baseline = frozen_plan
    before = copy.deepcopy(data)
    clock = [0.0]
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)

    def step(name, result):
        def call(*args, **kwargs):
            assert current_planning_control() is not None
            if stage == name:
                clock[0] = 10.0
            planning_checkpoint()
            return result
        return call

    monkeypatch.setattr("backend.scheduler.scoring.compute_score", step("score", {}))
    monkeypatch.setattr("backend.scheduler.validation.assert_plan_valid", step("validation", None))
    monkeypatch.setattr("backend.scheduler.gates.build_gate_report", step("gates", {}))
    event = threading.Event()

    def adapter(engine, **kwargs):
        assert kwargs["cancel_event"] is event
        assert current_planning_control() is not None
        return copy.deepcopy(baseline)

    with pytest.raises(PlanningTimeout), planning_scope(timeout_s=5, clock=lambda: clock[0]):
        frozen.optimize_preserving_started_lots(
            data, config, baseline, cancel_event=event, optimizer=adapter,
        )
    assert data == before


def test_cooperative_cancel_from_optimizer_restores_reservations(frozen_plan, monkeypatch):
    from backend.planning_control import planning_checkpoint

    data, config, baseline = frozen_plan
    before = copy.deepcopy(data)
    event = threading.Event()
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)

    def adapter(engine, **kwargs):
        assert kwargs["cancel_event"] is event
        event.set()
        planning_checkpoint()

    with pytest.raises(PlanningCancelled):
        frozen.optimize_preserving_started_lots(
            data, config, baseline, cancel_event=event, optimizer=adapter,
        )
    assert data == before
