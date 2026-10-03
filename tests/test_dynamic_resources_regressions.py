"""Accepted dynamic-resource audit regressions, using detached synthetic plans."""

from __future__ import annotations

import copy
import random
from dataclasses import replace
from datetime import date, timedelta

import pytest

from backend.analytics.ctp import compute_ctp
from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.plans.manual_move import ManualMoveError, move_lot
from backend.scheduler.operators import compute_operator_alerts, operator_peaks
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.types import EngineData, EOp, MachineInfo


def _op(**changes) -> EOp:
    return replace(
        EOp(
            id="OP1",
            sku="SKU1",
            client="C",
            designation="Test",
            m="M1",
            t="T1",
            pH=100,
            sH=0.5,
            operators=1,
            eco_lot=0,
            alt=None,
            stk=0,
            backlog=0,
            d=[0, 0, 0, 100],
            oee=1,
            wip=0,
        ),
        **changes,
    )


def _config() -> FactoryConfig:
    return FactoryConfig(
        shifts=[ShiftConfig("A", 420, 540), ShiftConfig("B", 540, 660)],
        machines={mid: MachineConfig(mid, "Grandes") for mid in ("M1", "M2", "M3")},
        operators={("Grandes", "A"): 1, ("Grandes", "B"): 1},
        setup_crews_by_group={"Grandes": 1},
    )


def _engine(*ops: EOp, days: int = 1) -> EngineData:
    first = date(2026, 3, 16)
    return EngineData(
        ops=list(ops) or [_op()],
        machines=[MachineInfo(mid, "Grandes", 240) for mid in ("M1", "M2", "M3")],
        twin_groups=[],
        client_demands={},
        n_days=days,
        workdays=[(first + timedelta(days=day)).isoformat() for day in range(days)],
        holidays=[day for day in range(days) if (first + timedelta(days=day)).weekday() >= 5],
    )


def _segment(**changes) -> Segment:
    return replace(
        Segment(
            lot_id="LOT1",
            run_id="RUN1",
            machine_id="M1",
            tool_id="T1",
            day_idx=0,
            start_min=420,
            end_min=510,
            shift="A",
            qty=100,
            prod_min=60,
            setup_min=30,
            sku="SKU1",
            edd=3,
            lot_qty=100,
            run_qty=100,
            run_setup_min=30,
            run_lot_count=1,
        ),
        **changes,
    )


def _block(start: int, end: int, day: int = 0) -> dict:
    return {"start_day": day, "end_day": day, "start_min": start, "end_min": end}


def _only_shift_a(data: EngineData) -> None:
    data.machine_blocked_intervals = {"M1": [_block(540, 660)]}


@pytest.mark.parametrize("crews,feasible", [(1, False), (2, True)])
def test_ctp_setup_crew_must_be_free_with_machine_and_tool(crews, feasible):
    data, config = _engine(), _config()
    _only_shift_a(data)
    config.setup_crews_by_group["Grandes"] = crews
    busy_crew = _segment(
        machine_id="M2",
        tool_id="T2",
        start_min=420,
        end_min=540,
        setup_min=120,
        prod_min=0,
        qty=0,
    )
    assert compute_ctp("SKU1", 100, 0, [busy_crew], data, config).feasible is feasible


def test_ctp_setup_crews_are_group_scoped():
    data, config = _engine(), _config()
    _only_shift_a(data)
    config.machines["M2"].group = "Medias"
    busy_crew = _segment(
        machine_id="M2",
        tool_id="T2",
        end_min=540,
        setup_min=120,
        prod_min=0,
        qty=0,
    )
    assert compute_ctp("SKU1", 100, 0, [busy_crew], data, config).feasible


@pytest.mark.parametrize("a,b,feasible", [(0, 1, False), (1, 0, True)])
def test_ctp_operators_must_be_free_in_the_machine_window(a, b, feasible):
    data, config = _engine(), _config()
    _only_shift_a(data)
    config.operators = {("Grandes", "A"): a, ("Grandes", "B"): b}
    assert compute_ctp("SKU1", 100, 0, [], data, config).feasible is feasible


@pytest.mark.parametrize("capacity,feasible", [(1, False), (2, True)])
def test_ctp_requires_simultaneous_headcount_not_operator_minutes(capacity, feasible):
    data, config = _engine(_op(operators=2)), _config()
    config.operators = {("Grandes", shift): capacity for shift in ("A", "B")}
    assert compute_ctp("SKU1", 100, 0, [], data, config).feasible is feasible


@pytest.mark.parametrize("start,end,feasible", [(450, 540, False), (420, 450, True)])
def test_ctp_exact_absence_and_setup_before_production(start, end, feasible):
    data, config = _engine(), _config()
    _only_shift_a(data)
    data.operator_blocked_intervals = [
        {**_block(start, end), "group": "Grandes", "shift": "A", "count": 1}
    ]
    assert compute_ctp("SKU1", 50, 0, [], data, config).feasible is feasible


def test_ctp_overlapping_absences_reduce_simultaneous_headcount():
    data, config = _engine(_op(operators=2)), _config()
    _only_shift_a(data)
    config.operators[("Grandes", "A")] = 3
    data.operator_blocked_intervals = [
        {**_block(420, 540), "group": "Grandes", "shift": "A", "count": 1},
        {**_block(440, 540), "group": "Grandes", "shift": "A", "count": 1},
    ]
    assert not compute_ctp("SKU1", 50, 0, [], data, config).feasible


def test_ctp_setup_does_not_need_production_operators():
    data, config = _engine(), _config()
    _only_shift_a(data)
    existing = _segment(
        machine_id="M2",
        tool_id="T2",
        end_min=480,
        prod_min=60,
        setup_min=0,
    )
    result = compute_ctp("SKU1", 100, 0, [existing], data, config)
    assert result.feasible
    assert result.required_min == 90


@pytest.mark.parametrize("qty", [0, 1])
def test_ctp_counts_production_even_when_fragment_has_no_finished_pieces(qty):
    data, config = _engine(), _config()
    _only_shift_a(data)
    existing = _segment(
        machine_id="M2",
        tool_id="T2",
        end_min=540,
        setup_min=0,
        prod_min=120,
        qty=qty,
    )
    assert not compute_ctp("SKU1", 100, 0, [existing], data, config).feasible


@pytest.mark.parametrize("headcount,feasible", [(3, False), (4, True)])
def test_ctp_existing_twin_uses_max_operator_demand_once(headcount, feasible):
    data = _engine(
        _op(),
        _op(id="OP2", sku="SKU2", m="M2", t="T2", operators=2),
        _op(id="OP3", sku="SKU3", m="M2", t="T2", operators=3),
    )
    config = _config()
    config.operators[("Grandes", "A")] = headcount
    _only_shift_a(data)
    twin = _segment(
        machine_id="M2",
        tool_id="T2",
        sku="SKU2",
        end_min=540,
        setup_min=0,
        prod_min=120,
        qty=0,
        twin_outputs=[("OP2", "SKU2", 0), ("OP3", "SKU3", 0)],
    )
    assert compute_ctp("SKU1", 100, 0, [twin], data, config).feasible is feasible


def test_ctp_does_not_pool_disjoint_setup_fragments():
    data, config = _engine(), _config()
    _only_shift_a(data)
    crew = [
        _segment(
            machine_id="M2",
            tool_id="T2",
            start_min=start,
            end_min=end,
            setup_min=end - start,
            prod_min=0,
            qty=0,
        )
        for start, end in [(440, 450), (470, 480), (500, 510), (530, 540)]
    ]
    assert not compute_ctp("SKU1", 50, 0, crew, data, config).feasible


def test_ctp_setup_can_cross_adjacent_shift_boundary():
    data, config = _engine(), _config()
    data.machine_blocked_intervals = {"M1": [_block(420, 525)]}
    result = compute_ctp("SKU1", 100, 0, [], data, config)
    assert result.feasible
    assert result.required_min == 90


@pytest.mark.parametrize("budget,feasible", [(60, False), (90, True)])
def test_ctp_retains_machine_daily_capacity_ceiling(budget, feasible):
    data, config = _engine(), _config()
    config.machines["M1"].day_capacity_min = budget
    assert compute_ctp("SKU1", 100, 0, [], data, config).feasible is feasible


@pytest.mark.parametrize("setup_hours,feasible", [(0, True), (0.5, False)])
def test_ctp_zero_setup_does_not_require_a_crew(setup_hours, feasible):
    data, config = _engine(), _config()
    config.setup_crews_by_group["Grandes"] = 0
    config.setup_overrides = [{"sku": "SKU1", "machine": "M1", "hours": setup_hours}]
    assert compute_ctp("SKU1", 100, 0, [], data, config).feasible is feasible


def test_ctp_preserves_latest_start_then_earliest_completion_policy():
    data, config = _engine(days=3), _config()
    result = compute_ctp("SKU1", 400, 2, [], data, config)
    assert (result.latest_day, result.earliest_end_day) == (1, 2)
    assert (result.date_start, result.date_end) == ("2026-03-17", "2026-03-18")
    assert result.required_min == 270
    assert result.prod_days == 2


def test_ctp_cannot_use_production_time_before_setup_on_later_day():
    data, config = _engine(days=2), _config()
    crew = _segment(
        machine_id="M2",
        tool_id="T2",
        end_min=660,
        setup_min=240,
        prod_min=0,
        qty=0,
    )
    data.operator_blocked_intervals = [
        {**_block(420, 660, day=1), "group": "Grandes", "shift": shift, "count": 1}
        for shift in ("A", "B")
    ]
    assert not compute_ctp("SKU1", 100, 1, [crew], data, config).feasible


def test_ctp_setup_can_finish_at_daily_capacity_boundary_before_next_day_production():
    data, config = _engine(days=2), _config()
    config.machines["M1"].day_capacity_min = 60
    config.setup_overrides = [{"sku": "SKU1", "machine": "M1", "hours": 1}]
    result = compute_ctp("SKU1", 100, 1, [], data, config)
    assert result.feasible
    assert (result.latest_day, result.earliest_end_day) == (0, 1)


def test_ctp_interval_search_agrees_with_tiny_exhaustive_clock():
    rng = random.Random(712)
    outcomes = set()
    for _ in range(100):
        data, config = _engine(_op(pH=60, sH=2 / 60, operators=2)), _config()
        config.shifts = [ShiftConfig("A", 420, 426), ShiftConfig("B", 426, 432)]
        config.operators = {("Grandes", "A"): 2, ("Grandes", "B"): 2}
        machine = [rng.random() > 0.15 for _ in range(12)]
        tool = [rng.random() > 0.15 for _ in range(12)]
        crew = [rng.random() > 0.25 for _ in range(12)]
        staffed = [rng.random() > 0.3 for _ in range(12)]
        data.machine_blocked_intervals = {
            "M1": [
                _block(420 + minute, 421 + minute) for minute in range(12) if not machine[minute]
            ]
        }
        data.tool_blocked_intervals = {
            "T1": [_block(420 + minute, 421 + minute) for minute in range(12) if not tool[minute]]
        }
        data.operator_blocked_intervals = [
            {
                **_block(420 + minute, 421 + minute),
                "group": "Grandes",
                "shift": "A" if minute < 6 else "B",
                "count": 2,
            }
            for minute in range(12)
            if not staffed[minute]
        ]
        setups = [
            _segment(
                machine_id="M2",
                tool_id="T2",
                start_min=420 + minute,
                end_min=421 + minute,
                setup_min=1,
                prod_min=0,
                qty=0,
            )
            for minute in range(12)
            if not crew[minute]
        ]
        ready = [machine[i] and tool[i] and staffed[i] for i in range(12)]
        expected = any(
            all(machine[i] and tool[i] and crew[i] for i in range(start, start + 2))
            and ready[start + 2]
            and sum(ready[start + 2 :]) >= 4
            for start in range(10)
        )
        original = copy.deepcopy((data, config, setups))
        actual = compute_ctp("SKU1", 4, 0, setups, data, config)
        assert actual.feasible is expected
        assert (data, config, setups) == original
        outcomes.add(expected)
    assert outcomes == {False, True}


def test_ctp_preserves_primary_preference_and_rebinds_alternative_requirements():
    data, config = _engine(_op(alt="M2")), _config()
    config.machines["M2"].oee = 0.5
    config.setup_overrides = [{"sku": "SKU1", "machine": "M2", "hours": 1}]
    primary = compute_ctp("SKU1", 100, 0, [], data, config)
    assert (primary.machine, primary.required_min) == ("M1", 90)
    data.machine_blocked_days = {"M1": {0}}
    alternative = compute_ctp("SKU1", 100, 0, [], data, config)
    assert (alternative.machine, alternative.required_min) == ("M2", 180)


def test_ctp_preserves_subcontract_milestones_on_success_and_failure():
    data = _engine(_op(is_subcontracted=True, subcontract_lead_time_days=5), days=15)
    config = _config()
    result = compute_ctp("SKU1", 100, 14, [], data, config)
    assert result.feasible
    assert result.customer_delivery_day == 14
    assert result.production_due_day == result.subcontract_dispatch_day == 7
    assert result.material_reference_day == 7
    assert result.material_release_day == 0
    assert result.latest_day == result.earliest_end_day == 7
    assert result.customer_delivery_date == "2026-03-30"
    assert result.production_due_date == "2026-03-23"
    assert result.material_release_date == "2026-03-16"
    data.machine_blocked_days = {"M1": set(range(8))}
    failed = compute_ctp("SKU1", 100, 14, [], data, config)
    assert not failed.feasible
    assert failed.production_due_day == 7
    assert failed.material_release_day == 0


def test_ctp_does_not_borrow_capacity_before_material_release():
    data, config = _engine(days=15), _config()
    data.machine_blocked_days = {"M1": set(range(7, 15))}
    result = compute_ctp("SKU1", 100, 14, [], data, config)
    assert not result.feasible
    assert result.material_release_day == 7


@pytest.mark.parametrize("twin", [False, True])
def test_operator_peaks_include_zero_qty_fragments_but_not_setup(twin):
    data = _engine(
        _op(operators=2),
        _op(id="OP2", sku="SKU2", operators=3),
    )
    config = _config()
    segment = _segment(
        qty=0,
        twin_outputs=[("OP1", "SKU1", 0), ("OP2", "SKU2", 0)] if twin else None,
    )
    demand = 3 if twin else 2
    peak = operator_peaks([segment], data, config)[(0, "Grandes", "A")]
    assert (peak.required, peak.available, peak.deficit) == (demand, 1, demand - 1)
    assert len(compute_operator_alerts([segment], data, config)) == 1
    setup_only = replace(segment, prod_min=0, end_min=450)
    assert operator_peaks([setup_only], data, config) == {}


def test_operator_zero_qty_fragment_splits_at_actual_shift_not_label():
    data, config = _engine(_op(operators=2)), _config()
    segment = _segment(start_min=510, end_min=570, setup_min=0, prod_min=60, qty=0)
    peaks = operator_peaks([segment], data, config)
    assert {key[2] for key in peaks} == {"A", "B"}
    assert all(peak.required == 2 for peak in peaks.values())


def _manual_case(monkeypatch, *, twin=False):
    config = _config()
    config.shifts = FactoryConfig().shifts
    config.machines["M1"].oee = 1
    config.machines["M2"].oee = 0.5
    config.setup_overrides = [{"sku": "SKU1", "machine": "M2", "hours": 1}]
    data = _engine(_op(alt="M2"), days=4)
    lot = Lot(
        id="LOT1",
        op_id="OP1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id="M2",
        qty=100,
        prod_min=60,
        setup_min=30,
        edd=3,
        is_twin=twin,
        sku="SKU1",
        material_release_day=0,
        customer_delivery_day=3,
    )
    segment = _segment()
    if twin:
        data.ops.append(_op(id="OP2", sku="SKU2", alt="M2", pH=50))
        lot.twin_outputs = [("OP1", "SKU1", 100), ("OP2", "SKU2", 100)]
        lot.output_milestones = [{"op_id": "OP1", "customer_delivery_day": 3}]
        lot.prod_min = 120
        segment = replace(
            segment,
            prod_min=120,
            end_min=570,
            twin_outputs=list(lot.twin_outputs),
            output_milestones=copy.deepcopy(lot.output_milestones),
        )
        config.setup_overrides.append({"sku": "SKU2", "machine": "M2", "hours": 1.5})
    calls = []

    def optimize(candidate_data, **kwargs):
        calls.append(candidate_data)
        return ScheduleResult(
            segments=[copy.deepcopy(segment)],
            lots=[copy.deepcopy(lot)],
            score={},
            time_ms=0,
            warnings=[],
            operator_alerts=[],
            gate_report={"physical_gate_passed": True},
        )

    monkeypatch.setattr("backend.plans.manual_move._allocate_existing_lots", optimize)
    return data, config, lot, segment, calls


def _move(data, config, lot, segment, **changes):
    request = {"lot_id": lot.id, "target_day": 1, "target_machine": "M2", "target_start_min": 600}
    request.update(changes)
    return move_lot([segment], [lot], {}, data, config, **request)


@pytest.mark.parametrize("twin,production,setup", [(False, 120, 60), (True, 240, 90)])
def test_manual_fallback_rebinds_target_lot_run_and_segments(monkeypatch, twin, production, setup):
    data, config, lot, segment, calls = _manual_case(monkeypatch, twin=twin)
    original = copy.deepcopy((data, config, lot, segment))
    candidate = _move(data, config, lot, segment)
    moved = candidate.segments
    rebound = candidate.lots[0]
    assert not calls
    assert (rebound.prod_min, rebound.setup_min) == (production, setup)
    assert sum(item.prod_min for item in moved) == production
    assert sum(item.setup_min for item in moved) == setup
    assert {item.run_setup_min for item in moved} == {setup}
    assert {item.machine_id for item in moved} == {"M2"}
    assert min(item.start_min + item.setup_min for item in moved) == 600
    assert sum(item.qty for item in moved) == 100
    assert rebound.planning_source == "manual"
    assert rebound.customer_delivery_day == 3
    assert rebound.material_release_day == 0
    assert (rebound.machine_id, rebound.alt_machine_id) == ("M1", "M2")
    assert candidate.gate_report["physical_gate_passed"]
    if twin:
        assert rebound.twin_outputs == lot.twin_outputs
        assert rebound.output_milestones == lot.output_milestones
        assert moved[0].twin_outputs == lot.twin_outputs
    assert (data, config, lot, segment) == original


def test_manual_fallback_rebinding_is_absolute_when_returning_to_primary(monkeypatch):
    data, config, lot, segment, _ = _manual_case(monkeypatch)
    lot.prod_min, lot.setup_min = 120, 60
    segment.machine_id = "M2"
    segment.prod_min, segment.setup_min, segment.run_setup_min = 120, 60, 60
    segment.end_min = 600
    candidate = _move(data, config, lot, segment, target_machine="M1")
    assert (candidate.lots[0].prod_min, candidate.lots[0].setup_min) == (60, 30)
    assert sum(item.prod_min for item in candidate.segments) == 60
    assert sum(item.setup_min for item in candidate.segments) == 30
    assert {item.run_setup_min for item in candidate.segments} == {30}


def test_manual_fallback_preserves_whatif_oee_precedence(monkeypatch):
    data, config, lot, segment, _ = _manual_case(monkeypatch)
    data.ops[0].oee, data.ops[0].oee_source = 0.75, "whatif"
    candidate = _move(data, config, lot, segment)
    assert candidate.lots[0].prod_min == 80
    assert sum(item.prod_min for item in candidate.segments) == 80


@pytest.mark.parametrize("twin,production", [(False, 120), (True, 240)])
def test_manual_rebound_fragments_preserve_quantities(monkeypatch, twin, production):
    data, config, lot, segment, _ = _manual_case(monkeypatch, twin=twin)
    data.machine_blocked_intervals = {"M2": [_block(630, 720, day=1)]}
    candidate = _move(data, config, lot, segment)
    assert len(candidate.segments) == 2
    assert sum(item.prod_min for item in candidate.segments) == production
    assert sum(item.qty for item in candidate.segments) == lot.qty
    assert candidate.segments[1].start_min == 720
    assert candidate.segments[1].setup_min == 0
    if twin:
        for op_id, _sku, qty in lot.twin_outputs:
            assert (
                sum(
                    output_qty
                    for item in candidate.segments
                    for output_id, _, output_qty in item.twin_outputs
                    if output_id == op_id
                )
                == qty
            )


@pytest.mark.parametrize("day,start", [(0, 450), (3, 1380)])
def test_manual_fallback_rejects_when_rebound_setup_or_production_does_not_fit(
    monkeypatch,
    day,
    start,
):
    data, config, lot, segment, _ = _manual_case(monkeypatch)
    original = copy.deepcopy((data, lot, segment))
    with pytest.raises(ManualMoveError, match="exatamente"):
        _move(data, config, lot, segment, target_day=day, target_start_min=start)
    assert (data, lot, segment) == original


def test_manual_rebound_setup_can_start_on_previous_workday(monkeypatch):
    data, config, lot, segment, _ = _manual_case(monkeypatch)
    candidate = _move(data, config, lot, segment, target_day=1, target_start_min=450)
    setup = [(item.day_idx, item.start_min, item.setup_min) for item in candidate.segments
             if item.setup_min > 0]
    assert setup == [(0, config.shift_b_end - 30, 30), (1, config.shift_a_start, 30)]
    assert candidate.gate_report["physical_gate_passed"]


@pytest.mark.parametrize("twin", [False, True])
@pytest.mark.parametrize("setup_only", [False, True])
def test_manual_rejects_whole_frozen_started_lot_before_optimization(monkeypatch, twin, setup_only):
    data, config, lot, segment, calls = _manual_case(monkeypatch, twin=twin)
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: 2)
    if setup_only:
        segment.prod_min, segment.qty, segment.end_min = 0, 0, 450
    continuation = replace(
        segment,
        day_idx=2,
        start_min=420,
        setup_min=0,
        end_min=480,
        prod_min=60,
        is_continuation=True,
    )
    original = copy.deepcopy((data, lot, segment, continuation))
    with pytest.raises(ManualMoveError, match="congelado"):
        move_lot(
            [segment, continuation],
            [lot],
            {},
            data,
            config,
            lot_id=lot.id,
            target_day=3,
            target_machine="M2",
            target_start_min=600,
        )
    assert not calls
    assert (data, lot, segment, continuation) == original


def test_manual_allows_lot_first_started_on_current_planning_day(monkeypatch):
    data, config, lot, segment, calls = _manual_case(monkeypatch)
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: 2)
    segment.day_idx = 2
    candidate = _move(data, config, lot, segment, target_day=3)
    assert not calls
    assert candidate.target_day == 3
