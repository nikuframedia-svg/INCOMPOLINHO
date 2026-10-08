"""Direct lot move preview/apply tests."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
import threading
import time

import pytest
from fastapi.testclient import TestClient

from backend.api.copilot import app
from backend.api import manual_plan as manual_plan_api
from backend.config.types import FactoryConfig, MachineConfig
from backend.copilot.state import state
from backend.plans.manual_move import (
    ManualMoveError,
    ManualMoveInconclusive,
    _crew_available,
    _delta,
    _free_gaps,
    _materialize_target,
    _operator_free_gaps,
    _production_start,
    move_lot,
)
from backend.plans.frozen import NoValidCandidateError
from backend.plans.store import PlansStore
from backend.scheduler.gates import build_gate_report
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.types import EngineData, EOp, MachineInfo, PlanAnchor


def _config() -> FactoryConfig:
    config = FactoryConfig()
    config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes"),
        "M2": MachineConfig(id="M2", group="Grandes"),
    }
    config.tools = {"T1": {"primary": "M1", "alt": "M2", "setup_hours": 0.5}}
    config.earliness_policy = "jit"
    return config


def _engine(demand_day: int = 2) -> EngineData:
    demand = [0, 0, 0, 0]
    demand[demand_day] = 100
    return EngineData(
        ops=[
            EOp(
                id="OP1",
                sku="SKU1",
                client="CLIENTE",
                designation="Peça",
                m="M1",
                t="T1",
                pH=100,
                sH=0.5,
                operators=1,
                eco_lot=0,
                alt="M2",
                stk=0,
                backlog=0,
                d=demand,
                oee=1.0,
                wip=0,
            )
        ],
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Grandes", day_capacity=1020),
        ],
        twin_groups=[],
        client_demands={},
        workdays=["2026-03-17", "2026-03-18", "2026-03-19", "2026-03-20"],
        n_days=4,
    )


def _lot(lot_id: str = "LOT1", *, edd: int = 2, op_id: str = "OP1") -> Lot:
    return Lot(
        id=lot_id,
        op_id=op_id,
        tool_id="T1",
        machine_id="M1",
        alt_machine_id="M2",
        qty=100,
        prod_min=60,
        setup_min=30,
        edd=edd,
        is_twin=False,
    )


def _segment(
    lot_id: str = "LOT1",
    *,
    machine: str = "M1",
    tool: str = "T1",
    day: int = 0,
    start: int = 420,
    setup: float = 30,
    run_id: str = "RUN1",
    edd: int = 2,
) -> Segment:
    return Segment(
        lot_id=lot_id,
        run_id=run_id,
        machine_id=machine,
        tool_id=tool,
        day_idx=day,
        start_min=start,
        end_min=start + 60 + int(setup),
        shift="A",
        qty=100,
        prod_min=60,
        setup_min=setup,
        edd=edd,
        sku="SKU1",
        lot_qty=100,
        run_qty=100,
        run_setup_min=30,
        run_lot_count=1,
    )


def _baseline(data: EngineData, config: FactoryConfig, segments: list[Segment], lots: list[Lot]):
    return compute_score(segments, lots, data, config)


def _require_reorganization(monkeypatch):
    def no_fixed_candidate(*_args, **_kwargs):
        raise ManualMoveError("No candidate with the other positions fixed")

    monkeypatch.setattr("backend.plans.manual_move._fixed_positions_move", no_fixed_candidate)


def test_manual_gap_preserves_mounted_tool_until_continuation():
    data = _engine()
    previous = _segment(day=0, run_id="RUN-OLD")
    following = _segment(day=2, setup=0, run_id="RUN-OLD")

    assert _free_gaps(
        [previous, following], data, day=1, shift_start=420, shift_end=930,
        machine_id="M1", tool_id="T2",
    ) == []
    assert _free_gaps(
        [previous, following], data, day=1, shift_start=420, shift_end=930,
        machine_id="M1", tool_id="T1",
    ) == [(420, 930)]


def test_gate_rejects_solver_candidate_that_drops_saved_manual_position():
    data = _engine()
    config = _config()
    data.plan_anchors = [PlanAnchor(
        lot_id="LOT1", machine_id="M2",
        start_at="2026-03-18T10:00:00+00:00",
    )]
    lot = _lot()
    misplaced = _segment(day=0)
    report = build_gate_report(
        [misplaced], [lot], _baseline(data, config, [misplaced], [lot]),
        data, config,
    )
    assert report["apply_decision"] == "blocked"
    assert report["metrics"]["plan_anchor_violations"] == 1
    assert any(item["kind"] == "plan_anchor" for item in report["violations"])

    placed = _segment(machine="M2", day=1, start=570)
    report = build_gate_report(
        [placed], [lot], _baseline(data, config, [placed], [lot]),
        data, config,
    )
    assert report["metrics"]["plan_anchor_violations"] == 0


def test_production_start_skips_setup_only_fragment():
    setup = _segment(day=0, start=900)
    setup.prod_min = 0
    setup.qty = 0
    setup.end_min = 930
    production = _segment(day=1, start=420, setup=0)

    assert _production_start([setup, production], "LOT1") == (1, 420.0, "M1")


@pytest.mark.parametrize("tool", ["T1", "MOULD-X"])
def test_materialize_retained_setup_does_not_require_time_before_exact_start(tool):
    data, config = _engine(), _config()
    previous = _segment("PREVIOUS", tool=tool, start=420)
    lot, template = _lot(), _segment(tool=tool)
    lot.tool_id = tool
    original = copy.deepcopy(previous)

    created = _materialize_target(
        [previous], lot, template, data, config, 0, "M1", previous.end_min,
    )

    assert _production_start(created, lot.id) == (0, previous.end_min, "M1")
    assert sum(item.setup_min for item in created) == 0
    assert sum(item.prod_min for item in created) == lot.prod_min
    assert sum(item.qty for item in created) == lot.qty
    assert previous == original


def test_move_reuses_retained_setup_at_busy_boundary(monkeypatch):
    data, config = _engine(), _config()
    data.ops[0].d[2] = 200
    previous = _segment("PREVIOUS", start=420)
    source = _segment(day=1, setup=0)
    previous_lot, lot = _lot("PREVIOUS"), _lot()
    previous_lot.sku = lot.sku = "SKU1"
    segments, lots = [previous, source], [previous_lot, lot]
    before = copy.deepcopy((segments, lots, data))
    score = _baseline(data, config, segments, lots)
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_args: 0)
    monkeypatch.setattr("backend.cpo.optimize", lambda *_args, **_kwargs: ScheduleResult(
        segments=segments, lots=lots, score=score, time_ms=0,
        warnings=[], operator_alerts=[], gate_report={"physical_gate_passed": False},
    ))

    preview = move_lot(
        segments, lots, score, data, config,
        lot_id=lot.id, target_day=0, target_machine="M1",
        target_start_min=previous.end_min,
    )

    moved = [item for item in preview.segments if item.lot_id == lot.id]
    assert _production_start(moved, lot.id) == (0, previous.end_min, "M1")
    assert sum(item.setup_min for item in moved) == 0
    assert preview.gate_report["physical_gate_passed"]
    assert preview.gate_report["coverage_gate_passed"]
    assert (segments, lots, data) == before


@pytest.mark.parametrize("interruption", ["reference", "other_tool", "other_machine", "unfinished_setup"])
def test_materialize_retained_setup_requires_actual_physical_continuity(interruption):
    data, config = _engine(), _config()
    lot, template = _lot(), _segment()
    previous = _segment("PREVIOUS")
    occupied = [previous]
    if interruption == "reference":
        previous.sku = "DIFFERENT-REF"
    elif interruption == "other_tool":
        other = _segment("OTHER", tool="T2", start=520, setup=0, run_id="OTHER")
        occupied.append(other)
    elif interruption == "other_machine":
        other = _segment("OTHER", machine="M2", start=520, setup=0, run_id="OTHER")
        occupied.append(other)
    else:
        previous.start_min, previous.end_min = 500, 530
        previous.prod_min = previous.qty = 0
        previous.run_setup_min = 60

    created = _materialize_target(occupied, lot, template, data, config, 0, "M1", 700)

    assert _production_start(created, lot.id) == (0, 700, "M1")
    assert sum(item.setup_min for item in created) == 30
    assert sum(item.qty for item in created) == lot.qty


@pytest.mark.parametrize("identity", ["family", "twins", "completed_setup"])
def test_materialize_reuses_completed_compatible_setup(identity):
    data, config = _engine(), _config()
    lot, template = _lot(), _segment()
    previous = _segment("PREVIOUS")
    if identity == "family":
        previous.sku = "REF-A"
        template.sku = "REF-B"
        previous.setup_family = template.setup_family = "REF-A|REF-B"
    elif identity == "twins":
        previous.twin_outputs = [("OP2", "SKU2", 100), ("OP1", "SKU1", 100)]
        lot.is_twin = True
        lot.twin_outputs = [("OP1", "SKU1", 100), ("OP2", "SKU2", 100)]
    else:
        previous.end_min = 450
        previous.prod_min = previous.qty = 0

    created = _materialize_target(
        [previous], lot, template, data, config, 0, "M1", previous.end_min,
    )

    assert sum(item.setup_min for item in created) == 0
    assert _production_start(created, lot.id) == (0, previous.end_min, "M1")
    assert sum(item.qty for item in created) == lot.qty
    if lot.twin_outputs:
        assert created[0].twin_outputs == lot.twin_outputs


def test_move_delta_reports_actual_utilization_and_material_counts():
    delta = _delta(
        {"work_time_min": 100, "available_capacity_min": 200, "early_window_violations": 2},
        {"work_time_min": 80, "available_capacity_min": 200, "early_window_violations": 1},
    )
    assert delta.utilization_before == 50
    assert delta.utilization_after == 40
    assert delta.early_window_before == 2
    assert delta.early_window_after == 1


@pytest.mark.parametrize("change", ["rename", "resize"])
def test_move_does_not_accept_resized_or_renamed_other_lots(monkeypatch, change):
    data, config = _engine(), _config()
    data.ops[0].d[2] = 200
    segments = [_segment(), _segment("LOT2", start=600, setup=0)]
    lots = [_lot(), _lot("LOT2")]
    before_segments, before_lots = copy.deepcopy(segments), copy.deepcopy(lots)

    def reoptimized(candidate_data, **_kwargs):
        other_id = "RECREATED" if change == "rename" else "LOT2"
        proposed_segments = [
            _segment(machine="M2", day=1, start=570, run_id="MOVED"),
            _segment(other_id, start=600, run_id="RECREATED_RUN"),
        ]
        proposed_lots = [_lot(), _lot(other_id)]
        if change == "resize":
            for segment, lot, quantity in zip(proposed_segments, proposed_lots, [50, 150]):
                segment.qty = segment.lot_qty = segment.run_qty = lot.qty = quantity
                segment.prod_min = lot.prod_min = quantity * 0.6
                segment.end_min = int(segment.start_min + segment.setup_min + segment.prod_min)
        score = _baseline(candidate_data, config, proposed_segments, proposed_lots)
        gate = build_gate_report(
            proposed_segments, proposed_lots, score, candidate_data, config,
        )
        assert gate["physical_gate_passed"] is True, gate["violations"]
        assert gate["coverage_gate_passed"] is True
        return ScheduleResult(
            segments=proposed_segments, lots=proposed_lots, score=score,
            time_ms=0, warnings=[], operator_alerts=[], gate_report=gate,
        )

    _require_reorganization(monkeypatch)
    monkeypatch.setattr("backend.plans.manual_move._allocate_existing_lots", reoptimized)
    monkeypatch.setattr(
        "backend.plans.manual_move._replan_around_fixed_lot", lambda *_args: None,
    )
    with pytest.raises(ManualMoveInconclusive):
        move_lot(
            segments, lots, _baseline(data, config, segments, lots), data, config,
            lot_id="LOT1", target_day=1, target_machine="M2", target_start_min=600,
        )
    assert segments == before_segments
    assert lots == before_lots


def test_move_timeout_cannot_escape_into_unbounded_fallback(monkeypatch):
    from backend import planning_control
    from backend.planning_control import PlanningTimeout

    data, config = _engine(), _config()
    segments, lots = [_segment()], [_lot()]
    clock = [0.0]

    def timed_out(*_args, **_kwargs):
        clock[0] = 61.0
        raise PlanningTimeout("search timed out")

    _require_reorganization(monkeypatch)
    monkeypatch.setattr("backend.plans.manual_move._allocate_existing_lots", timed_out)
    monkeypatch.setattr(planning_control.time, "monotonic", lambda: clock[0])
    with pytest.raises(PlanningTimeout):
        move_lot(
            segments, lots, _baseline(data, config, segments, lots), data, config,
            lot_id="LOT1", target_day=1, target_machine="M2", target_start_min=600,
        )


@pytest.mark.parametrize("other_id", ["OTHER", "RENAMED"])
def test_manual_fallback_compacts_released_capacity_with_the_complete_contract(monkeypatch, other_id):
    from dataclasses import replace
    from backend.scheduler.canonical import production_lot_obligations

    data, config = _engine(), _config()
    config.oee_default = 1.0
    config.tools["T2"] = {"primary": "M1", "setup_hours": 0.5}
    other_op = replace(data.ops[0], id="OP2", sku="SKU2", t="T2", alt=None)
    data.ops.append(other_op)
    other_lot = replace(_lot(other_id, op_id="OP2"), tool_id="T2", alt_machine_id=None, sku="SKU2")
    other_segment = replace(_segment(other_id, tool="T2", day=3, run_id="R-OTHER"), sku="SKU2")
    segments, lots = [_segment()], [_lot()]
    segments.append(other_segment)
    lots.append(other_lot)
    before = copy.deepcopy((segments, lots, data, config))

    def unavailable(*_args, **_kwargs):
        raise NoValidCandidateError("No optimizer candidate")

    monkeypatch.setattr("backend.cpo.optimize", unavailable)
    monkeypatch.setattr("backend.plans.manual_move._replan_around_fixed_lot", lambda *_: None)
    preview = move_lot(
        segments, lots, _baseline(data, config, segments, lots), data, config,
        lot_id="LOT1", target_day=1, target_machine="M2", target_start_min=600,
    )
    assert _production_start(preview.segments, "LOT1") == (1, 600.0, "M2")
    assert min(s.day_idx for s in preview.segments if s.lot_id == other_id) < 3
    assert preview.gate_report["improvement"]["moves_accepted"] > 0
    assert preview.gate_report["physical_gate_passed"]
    assert preview.gate_report["coverage_gate_passed"]
    assert production_lot_obligations(preview.lots) == production_lot_obligations(lots)
    assert (segments, lots, data, config) == before


def test_manual_move_reuses_a_report_verified_on_the_exact_complete_candidate(monkeypatch):
    from backend.scheduler.improvement import physical_signature

    data, config = _engine(), _config()
    segments, lots = [_segment()], [_lot()]
    planned = [_segment(machine="M2", day=1, start=570)]
    report = {"contract_version": 1, "status": "partial", "stop_reason": "budget",
              "moves_accepted": 0, "accepted_by_scope": {},
              "final_signature": physical_signature(planned, lots)}
    result = ScheduleResult(planned, copy.deepcopy(lots), _baseline(data, config, planned, lots),
                            0, [], [], improvement_report=report)
    _require_reorganization(monkeypatch)
    monkeypatch.setattr("backend.plans.manual_move._allocate_existing_lots", lambda *_a, **_k: result)

    def unexpected(*_args, **_kwargs):
        pytest.fail("The unchanged complete candidate must not repeat its improvement cycle")

    monkeypatch.setattr("backend.plans.frozen.improve_preserving_protected_lots", unexpected)
    preview = move_lot(
        segments, lots, _baseline(data, config, segments, lots), data, config,
        lot_id="LOT1", target_day=1, target_machine="M2", target_start_min=600,
    )
    assert preview.gate_report["improvement"]["status"] == "partial"
    assert preview.gate_report["improvement"]["stop_reason"] == "budget"


def test_fixed_lot_replan_defers_improvement_until_the_complete_candidate_exists(monkeypatch):
    from backend.plans.manual_move import _replan_around_fixed_lot

    data, config = _engine(), _config()
    calls = []

    def residual(candidate_data, **kwargs):
        calls.append(kwargs["source_lots"])
        return ScheduleResult([], [], {}, 0, [], [])

    monkeypatch.setattr("backend.plans.manual_move._allocate_existing_lots", residual)
    monkeypatch.setattr("backend.plans.frozen.improve_preserving_protected_lots",
                        lambda *_a, **_k: pytest.fail("Only the complete candidate may be improved"))
    result = _replan_around_fixed_lot(
        data, config, [_lot()], [], [], {}, _lot(), _segment(),
        1, "M2", 600, "quick", None, 10,
    )
    assert result is not None
    assert calls == [[]]


def test_manual_move_does_not_reuse_a_report_from_another_plan_state(monkeypatch):
    from backend.plans.manual_move import _finalize_move_candidate
    from backend.plans import frozen
    from backend.scheduler.improvement import physical_signature

    data, config = _engine(), _config()
    segments, lots = [_segment(machine="M2", day=1, start=570)], [_lot()]
    data.plan_anchors = [PlanAnchor("LOT1", "M2", "2026-03-18T10:00:00+00:00")]
    result = ScheduleResult(segments, lots, _baseline(data, config, segments, lots),
                            0, [], [], improvement_report={
                                "status": "completed", "final_signature": "old-state",
                            })
    real_improve = frozen.improve_preserving_protected_lots
    calls = []

    def complete_cycle(candidate, *_args, **kwargs):
        calls.append(physical_signature(candidate.segments, candidate.lots))
        return real_improve(candidate, *_args, **kwargs)

    monkeypatch.setattr(frozen, "improve_preserving_protected_lots", complete_cycle)
    finalized = _finalize_move_candidate(result, data, config, lots)
    assert calls == [physical_signature(segments, lots)]
    assert finalized.gate_report["improvement"]["stop_reason"] == "nothing_to_improve"
    assert _production_start(finalized.segments, "LOT1") == (1, 600.0, "M2")


def test_manual_move_with_no_phase_budget_reports_not_evaluated(monkeypatch):
    from backend.planning_control import planning_scope
    from backend import planning_control
    from backend.plans.manual_move import _finalize_move_candidate

    data, config = _engine(), _config()
    segments, lots = [_segment()], [_lot()]
    result = ScheduleResult(segments, lots, _baseline(data, config, segments, lots),
                            0, [], [], improvement_report={
                                "status": "completed", "final_signature": "old-state",
                            })
    clock = [0.0]
    monkeypatch.setattr(planning_control.time, "monotonic", lambda: clock[0])

    def unexpected(*_args, **_kwargs):
        pytest.fail("Closing reserve cannot be spent on another search")

    monkeypatch.setattr("backend.plans.frozen.improve_preserving_protected_lots", unexpected)
    with planning_scope(timeout_s=60):
        clock[0] = 56.0
        finalized = _finalize_move_candidate(result, data, config, lots)
    assert finalized.gate_report["improvement"]["status"] == "not_evaluated"
    assert finalized.gate_report["improvement"]["stop_reason"] == "no_time_left"


def test_move_cancelled_after_calculation_cannot_return_preview(monkeypatch):
    from backend.planning_control import PlanningCancelled

    data, config = _engine(), _config()
    segments, lots = [_segment()], [_lot()]
    score = _baseline(data, config, segments, lots)
    event = threading.Event()

    def completed(*_args, **_kwargs):
        event.set()
        return ScheduleResult(
            segments=segments, lots=lots, score=score, time_ms=0,
            warnings=[], operator_alerts=[],
            gate_report={"physical_gate_passed": True, "metrics": {}},
        )

    _require_reorganization(monkeypatch)
    monkeypatch.setattr("backend.plans.manual_move._allocate_existing_lots", completed)
    with pytest.raises(PlanningCancelled):
        move_lot(
            segments, lots, score, data, config, lot_id="LOT1",
            target_day=0, target_machine="M1", target_start_min=450,
            cancel_event=event,
        )


def test_move_replaces_old_anchor_in_fallback_validation(monkeypatch):
    data = _engine()
    config = _config()
    original = _segment()
    lot = _lot()
    data.plan_anchors = [PlanAnchor(
        lot_id="LOT1", machine_id="M1", start_at="2026-03-17T07:30:00+00:00",
    )]
    score = _baseline(data, config, [original], [lot])
    monkeypatch.setattr("backend.cpo.optimize", lambda *_args, **_kwargs: ScheduleResult(
        segments=[original], lots=[lot], score=score, time_ms=0,
        warnings=[], operator_alerts=[],
        gate_report={"physical_gate_passed": False},
    ))

    moved = move_lot(
        [original], [lot], score, data, config,
        lot_id="LOT1", target_day=1, target_machine="M2", target_start_min=600,
    )

    assert moved.gate_report["metrics"]["plan_anchor_violations"] == 0
    assert moved.gate_report["physical_gate_passed"] is True


@pytest.mark.parametrize("optimizer_unavailable", [False, True])
def test_fallback_keeps_started_lot_unchanged(monkeypatch, optimizer_unavailable):
    data = _engine()
    config = _config()
    config.tools["T2"] = {"primary": "M1", "alt": None, "setup_hours": 0.5}
    data.ops.append(EOp(
        id="OP2", sku="SKU2", client="CLIENTE", designation="Peça 2",
        m="M1", t="T2", pH=100, sH=0.5, operators=1, eco_lot=0,
        alt=None, stk=0, backlog=0, d=[0, 0, 100, 0], oee=1.0, wip=0,
    ))
    frozen = _segment("FROZEN", tool="T2", run_id="FROZEN_RUN")
    frozen.sku = "SKU2"
    future = _segment(day=1)
    frozen_lot = _lot("FROZEN", op_id="OP2")
    frozen_lot.tool_id = "T2"
    frozen_lot.alt_machine_id = None
    lot = _lot()
    segments, lots = [frozen, future], [frozen_lot, lot]
    score = _baseline(data, config, segments, lots)
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_args: 1)
    def optimize_stub(*_args, **_kwargs):
        if optimizer_unavailable:
            raise NoValidCandidateError("Nenhum candidato completo")
        return ScheduleResult(
            segments=segments, lots=lots, score=score, time_ms=0,
            warnings=[], operator_alerts=[], gate_report={"physical_gate_passed": False},
        )

    monkeypatch.setattr("backend.plans.frozen.optimize_preserving_started_lots", optimize_stub)

    moved = move_lot(
        segments, lots, score, data, config,
        lot_id="LOT1", target_day=2, target_machine="M2", target_start_min=600,
    )

    assert [item for item in moved.segments if item.lot_id == "FROZEN"] == [frozen]
    assert moved.gate_report["physical_gate_passed"] is True


def test_manual_operator_gaps_use_exact_absence_and_concurrent_work():
    data = _engine()
    data.operator_blocked_intervals = [{
        "start_day": 1, "start_min": 420, "end_min": 930,
        "group": "Grandes", "shift": "A", "count": 1,
    }]
    config = _config()
    config.operators[("Grandes", "A")] = 3
    running = [_segment(lot_id="A", day=1, setup=0, machine="M1"),
               _segment(lot_id="B", day=1, setup=0, machine="M2")]

    assert _operator_free_gaps(
        running, data, config, day=1, shift="A", shift_start=420,
        shift_end=930, machine_id="M1", required=1,
    ) == [(480, 930)]


def test_existing_delivery_shortfall_is_not_reported_as_new_decline(monkeypatch):
    data, config = _engine(demand_day=0), _config()
    segment, lot = _segment(day=1), _lot(edd=0)
    score = _baseline(data, config, [segment], [lot])
    result = ScheduleResult(
        segments=[segment], lots=[lot], score=score, time_ms=0,
        warnings=[], operator_alerts=[],
        gate_report={"physical_gate_passed": True, "metrics": {}, "requires_approval": True},
    )
    monkeypatch.setattr("backend.cpo.optimize", lambda *_args, **_kwargs: result)

    preview = move_lot(
        [segment], [lot], score, data, config,
        lot_id="LOT1", target_day=1, target_machine="M1", target_start_min=450,
    )

    assert preview.requires_confirmation is True
    assert not any("OTD-D desce" in warning for warning in preview.delivery_warnings)


def test_move_lot_places_exact_production_on_requested_alternative():
    data = _engine()
    config = _config()
    segments = [_segment()]
    lots = [_lot()]

    candidate = move_lot(
        segments,
        lots,
        _baseline(data, config, segments, lots),
        data,
        config,
        lot_id="LOT1",
        target_day=1,
        target_machine="M2",
        target_start_min=600,
    )

    moved = [segment for segment in candidate.segments if segment.lot_id == "LOT1"]
    assert {segment.day_idx for segment in moved} == {1}
    assert {segment.machine_id for segment in moved} == {"M2"}
    assert sum(segment.qty for segment in moved) == 100
    assert sum(segment.prod_min for segment in moved) == 60
    first = min(moved, key=lambda segment: (segment.day_idx, segment.start_min))
    assert first.start_min + first.setup_min == 600
    assert candidate.gate_report["hard_gate_passed"] is True
    # The gap before the manual position is explained by the anchor, not an
    # actionable left shift (plan-melhoria §6.4). With a clean gate the move
    # applies without confirmation: robustness is information only and never
    # asks for approval (decisão do responsável, 07/10/2026).
    assert candidate.gate_report["operational_gate_passed"] is True
    assert [
        item["protection"]
        for item in candidate.gate_report["operational_audit"]["protected_left_shift_detail"]
    ] == ["manual_anchor"]
    assert candidate.gate_report["apply_decision"] == "auto_applicable"
    assert candidate.gate_report["approval_reasons"] == []
    assert candidate.requires_confirmation is False
    assert candidate.delivery_warnings == []
    assert candidate.time_ms < 250


def test_move_lot_with_real_gate_reason_requires_confirmation():
    data = _engine()
    config = _config()
    segments = [_segment()]
    lots = [_lot()]

    # Day 3 is after the day-2 delivery: the delivery gate, not robustness,
    # asks for confirmation.
    candidate = move_lot(
        segments,
        lots,
        _baseline(data, config, segments, lots),
        data,
        config,
        lot_id="LOT1",
        target_day=3,
        target_machine="M1",
        target_start_min=450,
    )

    assert candidate.gate_report["hard_gate_passed"] is True
    assert candidate.gate_report["apply_decision"] == "approval_required"
    assert "delivery_risk" in candidate.gate_report["approval_reasons"]
    assert "robustness_not_evaluated" not in candidate.gate_report["approval_reasons"]
    assert candidate.requires_confirmation is True


def test_move_lot_rejects_when_setup_cannot_finish_at_exact_start():
    data = _engine()
    config = _config()
    segments = [_segment()]
    lots = [_lot()]

    with pytest.raises(ManualMoveError, match="exatamente"):
        move_lot(
            segments,
            lots,
            _baseline(data, config, segments, lots),
            data,
            config,
            lot_id="LOT1",
            target_day=0,
            target_machine="M2",
            target_start_min=430,
        )


@pytest.mark.parametrize(
    ("start_min", "setup_fragments"),
    [
        (930, [("A", 870, 930, 60)]),
        (960, [("A", 900, 930, 30), ("B", 930, 960, 30)]),
    ],
)
def test_move_setup_can_cross_adjacent_shift_boundary(
    monkeypatch, start_min, setup_fragments,
):
    data, config = _engine(), _config()
    data.ops[0].sH = 1.0
    config.tools["T1"]["setup_hours"] = 1.0
    source, lot = _segment(setup=60), _lot()
    lot.setup_min = 60
    source.run_setup_min = 60
    score = _baseline(data, config, [source], [lot])
    monkeypatch.setattr("backend.cpo.optimize", lambda *_args, **_kwargs: ScheduleResult(
        segments=[source], lots=[lot], score=score, time_ms=0,
        warnings=[], operator_alerts=[], gate_report={"physical_gate_passed": False},
    ))

    try:
        preview = move_lot(
            [source], [lot], score, data, config,
            lot_id="LOT1", target_day=1, target_machine="M2",
            target_start_min=start_min,
        )
    except ManualMoveError as exc:
        pytest.fail(f"{exc}: {exc.gate_report}")

    moved = sorted(
        (segment for segment in preview.segments if segment.lot_id == "LOT1"),
        key=lambda segment: (segment.day_idx, segment.start_min),
    )
    actual_setup = [
        (segment.shift, segment.start_min, segment.start_min + segment.setup_min, segment.setup_min)
        for segment in moved if segment.setup_min > 0
    ]
    assert actual_setup == setup_fragments
    assert sum(segment.prod_min for segment in moved) == 60
    assert sum(segment.qty for segment in moved) == 100
    assert _production_start(moved, "LOT1") == (1, start_min, "M2")
    assert preview.gate_report["physical_gate_passed"] is True


@pytest.mark.parametrize("target_day", [1, 3])
def test_move_setup_can_finish_on_previous_factory_workday(monkeypatch, target_day):
    data, config = _engine(), _config()
    if target_day == 3:
        data.workdays = ["2026-03-20", "2026-03-21", "2026-03-22", "2026-03-23"]
    data.ops[0].sH = 1.0
    config.tools["T1"]["setup_hours"] = 1.0
    source, lot = _segment(setup=60), _lot()
    lot.setup_min = 60
    source.run_setup_min = 60
    score = _baseline(data, config, [source], [lot])
    monkeypatch.setattr("backend.cpo.optimize", lambda *_args, **_kwargs: ScheduleResult(
        segments=[source], lots=[lot], score=score, time_ms=0,
        warnings=[], operator_alerts=[], gate_report={"physical_gate_passed": False},
    ))

    preview = move_lot(
        [source], [lot], score, data, config,
        lot_id="LOT1", target_day=target_day, target_machine="M2", target_start_min=420,
    )

    moved = sorted(
        (segment for segment in preview.segments if segment.lot_id == "LOT1"),
        key=lambda segment: (segment.day_idx, segment.start_min),
    )
    assert [(item.day_idx, item.start_min, item.end_min, item.setup_min, item.prod_min)
            for item in moved] == [
        (target_day - (3 if target_day == 3 else 1),
         config.shift_b_end - 60, config.shift_b_end, 60, 0),
        (target_day, 420, 480, 0, 60),
    ]
    assert preview.gate_report["physical_gate_passed"] is True


def test_move_rejects_previous_workday_setup_when_crew_is_busy():
    data, config = _engine(), _config()
    source, lot = _segment(setup=60), _lot()
    lot.setup_min = 60
    source.run_setup_min = 60
    other_setup = _segment(
        "OTHER", machine="M1", tool="T2", day=0,
        start=1380, setup=30, run_id="OTHER_RUN",
    )
    other_setup.end_min = 1410
    other_setup.prod_min = 0
    other_setup.qty = 0

    with pytest.raises(ManualMoveError, match="M1/T2"):
        _materialize_target([other_setup], lot, source, data, config, 1, "M2", 420)


def test_move_replans_other_setup_around_fixed_previous_day_anchor(monkeypatch):
    data, config = _engine(), _config()
    data.ops[0].sH = 1.0
    config.tools["T1"]["setup_hours"] = 1.0
    config.tools["T2"] = {"primary": "M1", "alt": None, "setup_hours": 1.0}
    data.ops.append(EOp(
        id="OP2", sku="SKU2", client="CLIENTE", designation="Peça 2",
        m="M1", t="T2", pH=100, sH=1.0, operators=1,
        eco_lot=0, alt=None, stk=0, backlog=0, d=[0, 0, 100, 0],
        oee=1.0, wip=0,
    ))
    source, lot = _segment(setup=60), _lot()
    source.run_setup_min = lot.setup_min = 60
    other_lot = _lot("OTHER", op_id="OP2")
    other_lot.tool_id = "T2"
    other_lot.alt_machine_id = None
    other_lot.setup_min = 60
    other_setup = _segment("OTHER", tool="T2", day=0, start=1380,
                           setup=60, run_id="OTHER_RUN")
    other_setup.end_min = 1440
    other_setup.prod_min = 0
    other_setup.qty = 0
    other_setup.run_setup_min = 60
    other_setup.sku = "SKU2"
    other_prod = _segment("OTHER", tool="T2", day=1, start=420,
                          setup=0, run_id="OTHER_RUN")
    other_prod.end_min = 480
    other_prod.run_setup_min = 60
    other_prod.sku = "SKU2"
    other_prod.is_continuation = True
    segments, lots = [source, other_setup, other_prod], [lot, other_lot]
    score = _baseline(data, config, segments, lots)
    original = copy.deepcopy((segments, lots, data))
    relocated = _segment("OTHER", tool="T2", day=1, start=960,
                         setup=60, run_id="OTHER_RUN")
    relocated.shift = "B"
    relocated.run_setup_min = 60
    relocated.sku = "SKU2"
    calls = []

    def optimize_stub(candidate_data, **_kwargs):
        calls.append(candidate_data)
        if not candidate_data.setup_crew_reservations:
            return ScheduleResult(
                segments=segments, lots=lots, score=score, time_ms=0,
                warnings=[], operator_alerts=[],
                gate_report={"physical_gate_passed": False},
            )
        assert any(block["tool_id"] == "T1" and block["start_day"] == 0
                   for block in candidate_data.setup_crew_reservations)
        assert not any(anchor.lot_id == "LOT1" for anchor in candidate_data.plan_anchors)
        return ScheduleResult(
            segments=[relocated], lots=[other_lot], score={}, time_ms=0,
            warnings=[], operator_alerts=[],
        )

    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_args: 0)
    monkeypatch.setattr("backend.plans.manual_move._allocate_existing_lots", optimize_stub)

    preview = move_lot(
        segments, lots, score, data, config,
        lot_id="LOT1", target_day=1, target_machine="M2", target_start_min=420,
    )

    assert len(calls) == 2
    assert _production_start(preview.segments, "LOT1") == (1, 420.0, "M2")
    assert preview.gate_report["physical_gate_passed"]
    assert sum(segment.qty for segment in preview.segments if segment.lot_id == "OTHER") == 100
    assert (segments, lots, data) == original


@pytest.mark.parametrize("resource", ["machine", "tool"])
def test_move_rejects_previous_workday_setup_when_resource_is_blocked(resource):
    data, config = _engine(), _config()
    source, lot = _segment(setup=60), _lot()
    lot.setup_min = 60
    source.run_setup_min = 60
    interval = {"start_day": 0, "start_min": 1380, "end_day": 0, "end_min": 1410}
    if resource == "machine":
        data.machine_blocked_intervals = {"M2": [interval]}
    else:
        data.tool_blocked_intervals = {"T1": [interval]}

    with pytest.raises(ManualMoveError, match="máquina ou ferramenta"):
        _materialize_target([], lot, source, data, config, 1, "M2", 420)


def test_move_rejects_setup_boundary_when_previous_shift_is_blocked(monkeypatch):
    data, config = _engine(), _config()
    data.ops[0].sH = 1.0
    config.tools["T1"]["setup_hours"] = 1.0
    data.machine_blocked_intervals = {"M2": [{
        "start_day": 1, "start_min": 870, "end_day": 1, "end_min": 930,
    }]}
    source, lot = _segment(setup=60), _lot()
    lot.setup_min = 60
    source.run_setup_min = 60
    score = _baseline(data, config, [source], [lot])
    monkeypatch.setattr("backend.cpo.optimize", lambda *_args, **_kwargs: ScheduleResult(
        segments=[source], lots=[lot], score=score, time_ms=0,
        warnings=[], operator_alerts=[], gate_report={"physical_gate_passed": False},
    ))

    with pytest.raises(ManualMoveError):
        move_lot(
            [source], [lot], score, data, config,
            lot_id="LOT1", target_day=1, target_machine="M2",
            target_start_min=930,
        )


def test_move_rejects_setup_boundary_when_crew_is_busy():
    data, config = _engine(), _config()
    source, lot = _segment(setup=60), _lot()
    lot.setup_min = 60
    source.run_setup_min = 60
    other_setup = _segment(
        "OTHER", machine="M1", tool="T2", day=1,
        start=870, setup=60, run_id="OTHER_RUN",
    )
    other_setup.end_min = 930
    other_setup.prod_min = 0
    other_setup.qty = 0

    with pytest.raises(ManualMoveError, match="equipa de setup"):
        _materialize_target(
            [other_setup], lot, source, data, config,
            1, "M2", 930,
        )


def test_move_rejects_persistent_machine_block_on_exact_day():
    data = _engine()
    data.machine_blocked_days = {"M2": {1}}
    config = _config()
    segments = [_segment()]
    lots = [_lot()]

    with pytest.raises(ManualMoveError, match="exatamente no dia 1"):
        move_lot(
            segments,
            lots,
            _baseline(data, config, segments, lots),
            data,
            config,
            lot_id="LOT1",
            target_day=1,
            target_machine="M2",
        )


def test_move_splits_production_around_exact_machine_stop():
    data = _engine()
    data.machine_blocked_intervals = {
        "M2": [
            {
                "id": "stop",
                "start_day": 1,
                "start_min": 600,
                "end_day": 1,
                "end_min": 720,
            }
        ]
    }
    config = _config()
    lot = _lot()
    lot.prod_min = 300
    data.ops[0].pH = 20
    source = _segment()
    source.prod_min = 300
    source.end_min = 750

    candidate = move_lot(
        [source],
        [lot],
        _baseline(data, config, [source], [lot]),
        data,
        config,
        lot_id="LOT1",
        target_day=1,
        target_machine="M2",
        target_start_min=450,
    )

    moved = sorted(candidate.segments, key=lambda item: item.start_min)
    assert [(item.start_min, item.end_min) for item in moved] == [
        (420, 600),
        (720, 870),
    ]
    assert sum(item.prod_min for item in moved) == 300
    assert sum(item.qty for item in moved) == 100
    assert candidate.gate_report["hard_gate_passed"] is True


def test_move_repairs_setup_on_remaining_source_run():
    data = _engine()
    data.ops.append(
        EOp(
            id="OP2",
            sku="SKU2",
            client="CLIENTE",
            designation="Peça 2",
            m="M1",
            t="T1",
            pH=100,
            sH=0.5,
            operators=1,
            eco_lot=0,
            alt="M2",
            stk=0,
            backlog=0,
            d=[0, 0, 100, 0],
            oee=1.0,
            wip=0,
        )
    )
    config = _config()
    lots = [_lot("LOT1"), _lot("LOT2", op_id="OP2")]
    first = _segment("LOT1", run_id="SHARED")
    second = _segment("LOT2", start=510, setup=0, run_id="SHARED")
    second.run_qty = 200
    second.run_lot_count = 2
    segments = [first, second]

    candidate = move_lot(
        segments,
        lots,
        _baseline(data, config, segments, lots),
        data,
        config,
        lot_id="LOT1",
        target_day=1,
    )

    repaired = next(segment for segment in candidate.segments if segment.lot_id == "LOT2")
    assert repaired.setup_min == 30
    assert repaired.start_min == 420
    assert repaired.run_lot_count == 1
    assert candidate.gate_report["hard_gate_passed"] is True


def test_manual_move_setup_probe_is_group_scoped():
    config = _config()
    config.machines["M2"].group = "Medias"
    grande_setup = _segment("GRANDE", machine="M1", tool="TG", setup=30)
    media_setup = _segment("MEDIA", machine="M2", tool="TM", setup=30)

    assert _crew_available(
        [grande_setup],
        config=config,
        machine_id="M2",
        day=0,
        start=420,
        setup_min=30,
    )
    assert not _crew_available(
        [media_setup],
        config=config,
        machine_id="M2",
        day=0,
        start=420,
        setup_min=30,
    )

    config.setup_crews_by_group["Medias"] = 2
    assert _crew_available(
        [media_setup],
        config=config,
        machine_id="M2",
        day=0,
        start=420,
        setup_min=30,
    )


def test_move_rejects_machine_outside_primary_and_alternative():
    data = _engine()
    data.machines.append(MachineInfo(id="M3", group="Grandes", day_capacity=1020))
    config = _config()

    with pytest.raises(ManualMoveError, match="não é primária nem alternativa"):
        move_lot(
            [_segment()],
            [_lot()],
            {},
            data,
            config,
            lot_id="LOT1",
            target_day=1,
            target_machine="M3",
        )


@pytest.fixture
def manual_api_state(tmp_path: Path):
    previous = {key: getattr(state, key) for key in state.__dataclass_fields__}
    temp_store = PlansStore(tmp_path / "manual-api.db")
    data = _engine(demand_day=0)
    config = _config()
    lots = [_lot(edd=0)]
    segments = [_segment(edd=0)]
    score = _baseline(data, config, segments, lots)
    result = ScheduleResult(
        segments=segments,
        lots=lots,
        score=score,
        time_ms=1,
        warnings=[],
        operator_alerts=[],
        gate_report=build_gate_report(segments, lots, score, data, config),
    )
    state.engine_data = data
    state.config = config
    state.default_config = config
    state.dataset_info = None
    state.active_mutations = []
    state.manual_edits = []
    state.saved_schedule = None
    state.saved_mutations = None
    state.saved_manual_edits = None
    state.plans_store = temp_store
    state.update_schedule(result)
    yield
    temp_store.close()
    for key, value in previous.items():
        setattr(state, key, value)


def test_manual_move_api_previews_and_blocks_avoidable_delivery_regression(
    manual_api_state,
):
    client = TestClient(app)
    body = {"lot_id": "LOT1", "target_day": 1, "target_machine": "M2"}

    preview = client.post("/api/data/plan/move-preview", json=body)
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["contract_version"] == 2
    assert payload["requires_confirmation"] is True
    assert payload["delivery_warnings"]
    assert payload["gate_report"]["apply_decision"] == "approval_required"
    for field in (
        "jit_window_detail",
        "setup_overlap_detail",
        "proposals",
        "violations",
    ):
        assert isinstance(payload["gate_report"][field], list)

    apply_body = {
        **body,
        "candidate_id": payload["candidate_id"],
        "expected_revision": state.plan_revision,
    }
    blocked = client.post(
        "/api/data/plan/move-apply",
        json=apply_body,
    )
    assert blocked.status_code == 409
    assert state.manual_edits == []
    assert {segment.day_idx for segment in state.segments if segment.lot_id == "LOT1"} == {0}

    approved = client.post(
        "/api/data/plan/move-apply",
        json={
            **apply_body,
            "confirm_delivery_risk": True,
            "reason": "Teste de impacto",
            "author": "pytest",
        },
    )
    assert approved.status_code == 200, approved.text
    assert state.manual_edits
    assert {segment.day_idx for segment in state.segments if segment.lot_id == "LOT1"} == {1}


def test_legacy_manual_move_preview_keeps_event_loop_responsive(
    manual_api_state,
    monkeypatch,
):
    original_candidate = manual_plan_api._candidate
    release = threading.Event()

    def slow_candidate(body):
        release.wait(timeout=1)
        return original_candidate(body)

    monkeypatch.setattr(manual_plan_api, "_candidate", slow_candidate)

    async def exercise() -> dict:
        timer = threading.Timer(0.2, release.set)
        timer.start()
        started = time.perf_counter()
        try:
            task = asyncio.create_task(
                manual_plan_api.preview_move(
                    {"lot_id": "LOT1", "target_day": 1, "target_machine": "M2"}
                )
            )
            await asyncio.sleep(0.05)
            assert time.perf_counter() - started < 0.15
            release.set()
            return await task
        finally:
            release.set()
            timer.cancel()

    payload = asyncio.run(exercise())
    assert payload["contract_version"] == 2


def test_manual_move_background_approval_preview_is_reused_on_apply(
    manual_api_state,
    monkeypatch,
):
    client = TestClient(app)
    body = {"lot_id": "LOT1", "target_day": 1, "target_machine": "M2"}

    started = client.post("/api/data/plan/move-preview-jobs", json=body)
    assert started.status_code == 200, started.text
    job = started.json()["job"]
    for _ in range(200):
        if job["status"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
        response = client.get(f"/api/data/plan/move-preview-jobs/{job['id']}")
        assert response.status_code == 200, response.text
        job = response.json()["job"]

    assert job["status"] == "ready", job
    assert job["phase"] == "ready"
    assert job["result"]["contract_version"] == 2
    assert job["result"]["target_machine"] == "M2"
    expected_report = copy.deepcopy(job["result"]["improvement_report"])
    assert expected_report is not None

    monkeypatch.setattr(
        "backend.api.manual_plan._candidate",
        lambda _body: pytest.fail("apply recalculated an already verified candidate"),
    )
    applied = client.post(
        "/api/data/plan/move-apply",
        json={
            **body,
            "target_start_min": job["result"]["target_start_min"],
            "expected_revision": state.plan_revision,
            "preview_job_id": job["id"],
            "approve_exceptions": True,
            "approval_reason": "Movimento validado em background",
            "approval_author": "pytest",
            "reason": "Movimento validado em background",
            "author": "pytest",
        },
    )

    assert applied.status_code == 200, applied.text
    assert applied.json()["improvement_report"] == expected_report
    assert state.improvement_report == expected_report
    active = state.get_plans_store().active()["payload"]
    assert active["improvement_report"] == expected_report
    assert state.manual_edits
    assert {segment.machine_id for segment in state.segments if segment.lot_id == "LOT1"} == {"M2"}


def test_manual_move_apply_rejects_form_that_changed_after_preview(
    manual_api_state,
):
    client = TestClient(app)
    body = {
        "lot_id": "LOT1",
        "target_day": 1,
        "target_machine": "M2",
        "target_start_min": 600,
    }
    started = client.post("/api/data/plan/move-preview-jobs", json=body)
    job = started.json()["job"]
    for _ in range(200):
        if job["status"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
        job = client.get(
            f"/api/data/plan/move-preview-jobs/{job['id']}"
        ).json()["job"]

    assert job["status"] == "ready", job
    rejected = client.post(
        "/api/data/plan/move-apply",
        json={
            **body,
            "target_start_min": 615,
            "expected_revision": state.plan_revision,
            "preview_job_id": job["id"],
            "approve_exceptions": True,
            "approval_reason": "Teste",
            "approval_author": "pytest",
        },
    )
    assert rejected.status_code == 409
    assert state.manual_edits == []


def test_manual_move_preview_can_be_cancelled(
    manual_api_state,
    monkeypatch,
):
    client = TestClient(app)
    entered = threading.Event()
    release = threading.Event()

    def slow_move(*_args, progress=None, **_kwargs):
        assert progress is not None
        progress("scheduling", 35, "A reorganizar o plano")
        entered.set()
        release.wait(timeout=2)
        progress("validating", 80, "A validar recursos e riscos")
        raise AssertionError("A job cancelada não deve continuar")

    monkeypatch.setattr(
        "backend.plans.manual_move_jobs.move_lot",
        slow_move,
    )
    started = client.post(
        "/api/data/plan/move-preview-jobs",
        json={"lot_id": "LOT1", "target_day": 1, "target_machine": "M2"},
    )
    job_id = started.json()["job"]["id"]
    assert entered.wait(timeout=1)

    cancelled = client.post(
        f"/api/data/plan/move-preview-jobs/{job_id}/cancel",
        json={},
    )
    release.set()

    assert cancelled.status_code == 200
    assert cancelled.json()["job"]["status"] == "cancelled"
    assert cancelled.json()["job"]["phase"] == "cancelled"
    repeated = client.post(
        f"/api/data/plan/move-preview-jobs/{job_id}/cancel",
        json={},
    )
    assert repeated.status_code == 200
    assert repeated.json()["job"]["status"] == "cancelled"


def test_failed_move_job_returns_physical_violations(manual_api_state, monkeypatch):
    def reject(*_args, **_kwargs):
        raise ManualMoveError(
            "O movimento cria um conflito físico.",
            gate_report={"violations": [{
                "kind": "operator_capacity",
                "message": "Grandes turno B: 3 operadores para 2 disponíveis.",
            }]},
        )

    monkeypatch.setattr("backend.plans.manual_move_jobs.move_lot", reject)
    client = TestClient(app)
    started = client.post(
        "/api/data/plan/move-preview-jobs",
        json={"lot_id": "LOT1", "target_day": 1, "target_machine": "M2"},
    )
    job_id = started.json()["job"]["id"]
    for _ in range(100):
        job = client.get(f"/api/data/plan/move-preview-jobs/{job_id}").json()["job"]
        if job["status"] == "failed":
            break
        time.sleep(0.01)

    assert job["status"] == "failed"
    assert "3 operadores para 2" in job["error"]
    assert job["gate_report"]["violations"][0]["kind"] == "operator_capacity"


def test_move_job_timeout_is_inconclusive_and_preserves_plan(manual_api_state, monkeypatch):
    from backend.planning_control import PlanningTimeout

    previous = copy.deepcopy((state.segments, state.lots, state.plan_revision))

    def timed_out(*_args, **_kwargs):
        raise PlanningTimeout("deadline")

    monkeypatch.setattr("backend.plans.manual_move_jobs.move_lot", timed_out)
    client = TestClient(app)
    started = client.post(
        "/api/data/plan/move-preview-jobs",
        json={"lot_id": "LOT1", "target_day": 1, "target_machine": "M2"},
    )
    job_id = started.json()["job"]["id"]
    for _ in range(100):
        job = client.get(f"/api/data/plan/move-preview-jobs/{job_id}").json()["job"]
        if job["status"] == "failed":
            break
        time.sleep(0.01)

    assert job["status"] == "failed"
    assert job["message"] == "Verificação inconclusiva"
    assert "Não foi demonstrada a impossibilidade" in job["error"]
    assert job["result"] is None
    assert not job.get("gate_report")
    assert (state.segments, state.lots, state.plan_revision) == previous


def test_legacy_move_timeout_returns_explicit_error(manual_api_state, monkeypatch):
    from backend.planning_control import PlanningTimeout

    previous = copy.deepcopy((state.segments, state.lots, state.plan_revision))

    def timed_out(*_args, **_kwargs):
        raise PlanningTimeout("deadline")

    monkeypatch.setattr("backend.api.manual_plan.move_lot", timed_out)
    response = TestClient(app).post(
        "/api/data/plan/move-preview",
        json={"lot_id": "LOT1", "target_day": 1, "target_machine": "M2"},
    )
    assert response.status_code == 504
    assert response.json()["detail"]["code"] == "planning_timeout"
    assert (state.segments, state.lots, state.plan_revision) == previous


@pytest.mark.parametrize("as_job", [False, True])
def test_move_search_without_candidate_is_inconclusive_in_both_apis(
    manual_api_state, monkeypatch, as_job,
):
    previous = copy.deepcopy((state.segments, state.lots, state.plan_revision))

    def no_candidate(*_args, **_kwargs):
        raise ManualMoveInconclusive(
            "Verificação inconclusiva. Não foi demonstrada a impossibilidade "
            "do movimento; o plano não foi alterado."
        )

    module = "backend.plans.manual_move_jobs" if as_job else "backend.api.manual_plan"
    monkeypatch.setattr(f"{module}.move_lot", no_candidate)
    client = TestClient(app)
    url = "/api/data/plan/move-preview-jobs" if as_job else "/api/data/plan/move-preview"
    response = client.post(url, json={"lot_id": "LOT1", "target_day": 1, "target_machine": "M2"})
    if as_job:
        job_id = response.json()["job"]["id"]
        for _ in range(100):
            job = client.get(f"{url}/{job_id}").json()["job"]
            if job["status"] == "failed":
                break
            time.sleep(0.01)
        assert job["status"] == "failed"
        assert job["message"] == "Verificação inconclusiva"
        assert "Não foi demonstrada a impossibilidade" in job["error"]
        assert job["result"] is None
        assert not job.get("gate_report")
    else:
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "verification_inconclusive"
        assert "Não foi demonstrada a impossibilidade" in detail["message"]
        assert not detail.get("gate_report")
    assert (state.segments, state.lots, state.plan_revision) == previous
