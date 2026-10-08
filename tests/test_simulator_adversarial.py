"""Detached simulator regressions: no API managers, databases or live config."""

from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import asdict
from datetime import date, timedelta

import pytest

from backend.config.planning import apply_effective_planning_config
from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import ScheduleResult
from backend.simulator import Mutation, simulate
from backend.simulator.mutations import apply_mutation, normalize_mutation_params, validate_mutation
from backend.transform.calendars import apply_calendars
from backend.types import EOp, EngineData, MachineInfo, TwinGroup


@pytest.fixture(autouse=True)
def no_persistence(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Simulator regressions must not access persistent state")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr("backend.config.loader.save_config", forbidden)


def _fixture(profile="solo"):
    first = date(2026, 10, 5)
    workdays = [(first + timedelta(days=idx)).isoformat() for idx in range(21)]
    config = FactoryConfig(
        shifts=[ShiftConfig("A", 480, 720), ShiftConfig("B", 780, 1020)],
        machines={
            "M1": MachineConfig("M1", "Grandes", oee=1.0),
            "M2": MachineConfig("M2", "Grandes", oee=0.5),
        },
        tools={"T1": {"primary": "M1", "alt": "M2", "setup_hours": 0.25}},
        operators={("Grandes", "A"): 3, ("Grandes", "B"): 3},
        setup_overrides=[{"sku": "S1", "machine": "M2", "hours": 0.5}],
    )
    ops = []
    for sku, day, qty in [("S1", 7, 100), *([("S2", 10, 60)] if "twin" in profile else [])]:
        demand = [0] * 21
        demand[day] = qty
        ops.append(
            EOp(
                id=f"OP-{sku}",
                sku=sku,
                client="C",
                designation=sku,
                m="M1",
                t="T1",
                pH=100,
                sH=0.25,
                operators=1,
                eco_lot=0,
                alt="M2",
                stk=0,
                backlog=0,
                d=demand,
                oee=1.0,
                wip=0,
            )
        )
    twins = []
    if "twin" in profile:
        config.twins = {"T1": ["S1", "S2"]}
        twins = [TwinGroup("T1", "M1", "OP-S1", "OP-S2", "S1", "S2", 0, 0)]
    if "sub" in profile:
        config.subcontract_companies = [{"id": "V", "name": "Vendor", "lead_time_workdays": 2}]
        config.sku_subcontracts = {
            "S1": {"enabled": True, "company_id": "V", "lead_time_workdays": 2, "buffer_days": 1}
        }
    data = EngineData(
        ops=ops,
        machines=[MachineInfo("M1", "Grandes", 480), MachineInfo("M2", "Grandes", 480)],
        twin_groups=twins,
        client_demands={},
        workdays=workdays,
        n_days=21,
        holidays=[
            idx for idx, day in enumerate(workdays) if date.fromisoformat(day).weekday() >= 5
        ],
    )
    apply_effective_planning_config(data, config)
    apply_calendars(data, config)
    return data, config


PROFILES = ["solo", "sub", "twin", "twin_sub"]


def _simulate_unchanged(data, config, mutations, score=None, **kwargs):
    score = {} if score is None else score
    before = copy.deepcopy((data, vars(config), mutations, score, kwargs))
    try:
        return simulate(data, score, mutations, config, **kwargs)
    finally:
        assert (data, vars(config), mutations, score, kwargs) == before


INTEGER_FIELDS = [
    ("rush_order", {"sku": "S1", "qty": 1, "deadline_day": 9}, "qty"),
    ("rush_order", {"sku": "S1", "qty": 1, "deadline_day": 9}, "deadline_day"),
    ("advance_edd", {"sku": "S1", "days": 1}, "days"),
    ("delay_edd", {"sku": "S1", "days": 1}, "days"),
    ("change_eco_lot", {"sku": "S1", "new_eco_lot": 0}, "new_eco_lot"),
    ("cancel_order", {"sku": "S1", "from_day": 0, "to_day": 1}, "from_day"),
    ("cancel_order", {"sku": "S1", "from_day": 0, "to_day": 1}, "to_day"),
    ("machine_down", {"machine_id": "M1", "start": 0, "end": 1}, "start"),
    ("machine_down", {"machine_id": "M1", "start": 0, "end": 1}, "end"),
    ("tool_down", {"tool_id": "T1", "start": 0, "end": 1}, "start"),
    ("tool_down", {"tool_id": "T1", "start": 0, "end": 1}, "end"),
    ("add_holiday", {"day_idx": 0}, "day_idx"),
    ("remove_holiday", {"day_idx": 0}, "day_idx"),
    ("overtime", {"extra_min": 1}, "extra_min"),
    *[
        (
            "operator_shortage",
            {
                "group": "Grandes",
                "shift": "A",
                "count": 1,
                "start": 0,
                "end": 1,
                "start_min": 480,
                "end_min": 600,
            },
            field,
        )
        for field in ["count", "start", "end", "start_min", "end_min"]
    ],
]


@pytest.mark.parametrize(
    "bad",
    [True, False, 1.9, -0.1, float("inf"), float("-inf"), float("nan"), None, "", "1.9", {}, []],
)
@pytest.mark.parametrize("kind,params,field", INTEGER_FIELDS)
def test_invalid_integer_after_valid_mutations_is_rejected_without_input_changes(
    kind, params, field, bad
):
    data, config = _fixture()
    params = {**params, field: bad}
    mutations = [
        Mutation("rush_order", {"sku": "S1", "qty": 5, "deadline_day": 9}),
        Mutation("change_eco_lot", {"sku": "S1", "new_eco_lot": 20}),
        Mutation("overtime", {"extra_min": 15}),
        Mutation(kind, params),
    ]
    with pytest.raises(ValueError, match="inteiro"):
        _simulate_unchanged(data, config, mutations)


def test_json_exponent_overflow_is_a_validation_error():
    data, config = _fixture()
    params = json.loads('{"sku":"S1","qty":1e309,"deadline_day":9}')
    with pytest.raises(ValueError, match="qty"):
        _simulate_unchanged(data, config, [Mutation("rush_order", params)])


@pytest.mark.parametrize("value", [1, 1.0, "1", " 1 "])
def test_exact_integer_compatibility(value):
    data, config = _fixture()
    params = {"sku": " S1 ", "qty": value, "deadline_day": "9"}
    before = copy.deepcopy(params)
    normalized = validate_mutation(data, "rush_order", params, config)
    assert normalized == {"sku": "S1", "qty": 1, "deadline_day": 9}
    apply_mutation(data, "rush_order", params, config)
    assert data.ops[0].d[9] == 1
    assert params == before


@pytest.mark.parametrize(
    "kind,params,expected",
    [
        (
            "machine_down",
            {"machine_id": " M1 ", "day_idx": "2"},
            {"machine_id": "M1", "start": 2, "end": 2},
        ),
        (
            "tool_down",
            {"tool_id": " T1 ", "start_day": "2", "end_day": "3"},
            {"tool_id": "T1", "start": 2, "end": 3},
        ),
        (
            "operator_shortage",
            {"machine_group": " Grandes ", "shift_id": " A ", "operators": "1", "day_idx": "2"},
            {"group": "Grandes", "shift": "A", "count": 1, "start": 2, "end": 2},
        ),
        (
            "force_machine",
            {"tool_id": " UNKNOWN ", "to_machine": " UNKNOWN "},
            {"tool_id": "UNKNOWN", "to_machine": "UNKNOWN"},
        ),
        (
            "rush_order",
            {"sku": " UNKNOWN ", "qty": "-1", "deadline_day": "100000"},
            {"sku": "UNKNOWN", "qty": -1, "deadline_day": 100000},
        ),
    ],
)
def test_stateless_normalization_is_idempotent_and_has_no_domain_checks(kind, params, expected):
    before = copy.deepcopy(params)
    assert normalize_mutation_params(kind, params) == expected
    assert normalize_mutation_params(kind, expected) == expected
    assert params == before


@pytest.mark.parametrize(
    "kind,params,key",
    [
        ("oee_change", {"tool_id": "T1", "new_oee": 0.5}, "new_oee"),
        ("demand_change", {"sku": "S1", "factor": 2}, "factor"),
    ],
)
@pytest.mark.parametrize(
    "bad", [True, False, float("inf"), float("-inf"), float("nan"), None, {}, [], ""]
)
def test_invalid_float_parameters_preserve_inputs(kind, params, key, bad):
    data, config = _fixture()
    with pytest.raises(ValueError):
        _simulate_unchanged(
            data,
            config,
            [
                Mutation("overtime", {"extra_min": 15}),
                Mutation(kind, {**params, key: bad}),
            ],
        )


@pytest.mark.parametrize(
    "kind,key,target,attribute",
    [
        ("machine_down", "machine_id", "M1", "machine_blocked_days"),
        ("tool_down", "tool_id", "T1", "tool_blocked_days"),
    ],
)
@pytest.mark.parametrize(
    "days,expected",
    [
        ({"start_day": "2", "end_day": "3"}, {2, 3}),
        ({"day_idx": "2"}, {2}),
        ({"start": "2"}, {2}),
    ],
)
def test_day_aliases_and_trimmed_resources_reach_handlers(
    kind, key, target, attribute, days, expected
):
    data, config = _fixture()
    params = {key: f" {target} ", **days}
    before = copy.deepcopy(params)
    validate_mutation(data, kind, params, config)
    result = _simulate_unchanged(data, config, [Mutation(kind, params)])
    assert getattr(result.mutated_data, attribute) == {target: expected}
    assert params == before


@pytest.mark.parametrize(
    "kind,params",
    [
        ("rush_order", {"sku": "S1", "qty": "5", "deadline_day": "9"}),
        ("demand_change", {"sku": "S1", "factor": "2"}),
        ("cancel_order", {"sku": "S1", "from_day": "0", "to_day": "20"}),
        ("advance_edd", {"sku": "S1", "days": "1"}),
        ("delay_edd", {"sku": "S1", "days": "1"}),
        ("change_eco_lot", {"sku": "S1", "new_eco_lot": "20"}),
        ("oee_change", {"tool_id": "T1", "new_oee": "0.5"}),
        ("force_machine", {"tool_id": "T1", "to_machine": "M2"}),
        (
            "operator_shortage",
            {"group": "Grandes", "shift": "A", "count": "1", "start": "2", "end": "3"},
        ),
    ],
)
def test_trimmed_identifiers_are_equivalent_to_canonical_input(kind, params):
    data, config = _fixture()
    expected_data, expected_config = copy.deepcopy((data, config))
    padded = {
        key: f" {value} " if key in {"sku", "tool_id", "to_machine", "group", "shift"} else value
        for key, value in params.items()
    }
    apply_mutation(expected_data, kind, params, expected_config)
    apply_mutation(data, kind, padded, config)
    assert data == expected_data
    assert config == expected_config


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("force_first", [True, False])
def test_forced_alternate_survives_config_projection_and_mutation_order(profile, force_first):
    data, config = _fixture(profile)
    force = Mutation("force_machine", {"tool_id": " T1 ", "to_machine": " M2 "})
    rush = Mutation("rush_order", {"sku": " S1 ", "qty": 40, "deadline_day": 9})
    result = _simulate_unchanged(data, config, [force, rush] if force_first else [rush, force])
    assert result.segments
    assert {segment.machine_id for segment in result.segments} == {"M2"}
    assert result.mutated_config.tools["T1"] == {"primary": "M2", "alt": None, "setup_hours": 0.25}
    apply_effective_planning_config(result.mutated_data, result.mutated_config)
    assert all(op.m == "M2" and op.alt is None for op in result.mutated_data.ops)
    assert all(group.machine_id == "M2" for group in result.mutated_data.twin_groups)
    assert sum(seg.prod_min for seg in result.segments) == pytest.approx(
        sum(lot.qty for lot in result.lots) / 50 * 60,
        abs=1,
    )
    assert sum(seg.setup_min for seg in result.segments) >= 30
    assert result.gate_report["metrics"]["source_missing_qty"] == 0


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("deadline", [20, 21, 25])
def test_rush_horizon_boundaries_preserve_all_demand(profile, deadline):
    data, config = _fixture(profile)
    result = _simulate_unchanged(
        data, config, [Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": deadline})]
    )
    assert result.mutated_data.n_days == max(21, deadline + 1)
    assert len(result.mutated_data.workdays) == result.mutated_data.n_days
    assert all(len(op.d) == result.mutated_data.n_days for op in result.mutated_data.ops)
    assert sum(result.mutated_data.ops[0].d) == 140
    assert result.mutated_data.ops[0].d[deadline] == 40
    assert result.lots and result.segments
    assert result.gate_report["metrics"]["source_missing_qty"] == 0
    assert result.score["otd_d"] == 100.0


@pytest.mark.parametrize("profile", PROFILES)
def test_delay_beyond_horizon_does_not_disappear(profile):
    data, config = _fixture(profile)
    result = _simulate_unchanged(data, config, [Mutation("delay_edd", {"sku": "S1", "days": 21})])
    assert result.mutated_data.n_days == 42
    assert result.mutated_data.ops[0].d[28] == 100
    assert all(len(op.d) == 42 for op in result.mutated_data.ops)
    assert result.lots and result.segments
    assert result.gate_report["metrics"]["source_missing_qty"] == 0
    assert result.score["otd_d"] == 100.0


def test_horizon_extension_reprojects_persistent_calendars_and_keeps_overlays():
    data, config = _fixture()
    config.extra_workdays = ["2026-10-31"]  # new Saturday, index 26
    config.holidays = ["2026-10-27"]  # new Tuesday, index 22
    config.machine_unavailability = [
        {
            "id": "late-outage",
            "resource": "M1",
            "start_at": "2026-10-25T17:00",
            "end_at": "",
            "category": "Avaria",
        }
    ]
    apply_calendars(data, config)
    result = _simulate_unchanged(
        data,
        config,
        [
            Mutation("machine_down", {"machine_id": "M2", "start": 2, "end": 2}),
            Mutation("add_holiday", {"day_idx": 3}),
            Mutation("remove_holiday", {"day_idx": 5}),
            Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": 28}),
        ],
    )
    changed = result.mutated_data
    assert 26 not in changed.holidays
    assert {3, 22, 27} <= set(changed.holidays)
    assert 5 not in changed.holidays
    assert changed.machine_blocked_days["M2"] == {2}
    assert set(range(21, 29)) <= changed.machine_blocked_days["M1"]


@pytest.mark.parametrize("profile", PROFILES)
def test_cancel_all_has_standard_empty_score_and_no_false_delivery_risk(profile):
    data, config = _fixture(profile)
    baseline = _simulate_unchanged(data, config, [])
    result = _simulate_unchanged(
        data,
        config,
        [Mutation("cancel_order", {"sku": op.sku, "from_day": 0, "to_day": 20}) for op in data.ops],
        baseline.score,
    )
    assert result.lots == result.segments == []
    assert result.score == compute_score([], [], result.mutated_data, result.mutated_config)
    assert result.delta.otd_after == result.delta.otd_d_after == 100.0
    assert result.delta.utilization_before > 0
    assert result.delta.utilization_after == 0
    assert "delivery_risk" not in result.gate_report["approval_reasons"]


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize(
    "mutation",
    [
        Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": 9}),
        Mutation("demand_change", {"sku": "S1", "factor": 2}),
        Mutation("oee_change", {"tool_id": "T1", "new_oee": 0.5}),
    ],
)
def test_utilization_uses_real_capacity_and_work(profile, mutation):
    data, config = _fixture(profile)
    baseline = _simulate_unchanged(data, config, [])
    result = _simulate_unchanged(data, config, [mutation], baseline.score)
    for score, value in [
        (baseline.score, result.delta.utilization_before),
        (result.score, result.delta.utilization_after),
    ]:
        assert value == pytest.approx(
            100 * score["work_time_min"] / score["available_capacity_min"]
        )
    assert result.delta.utilization_after > result.delta.utilization_before > 0


@pytest.mark.parametrize("profile", PROFILES)
def test_combined_mutations_repeat_exactly_and_return_detached_state(profile):
    data, config = _fixture(profile)
    mutations = [
        Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": 9}),
        Mutation("force_machine", {"tool_id": "T1", "to_machine": "M2"}),
        Mutation("oee_change", {"tool_id": "T1", "new_oee": 0.8}),
        Mutation("overtime", {"extra_min": 30}),
        Mutation("delay_edd", {"sku": "S1", "days": 21}),
    ]
    results = [_simulate_unchanged(data, config, mutations) for _ in range(3)]

    def signature(result):
        return (
            [asdict(s) for s in result.segments],
            [asdict(lot) for lot in result.lots],
            result.score,
        )

    assert signature(results[0]) == signature(results[1]) == signature(results[2])
    before = copy.deepcopy((data, config))
    results[0].mutated_data.ops[0].d[0] += 99
    results[0].mutated_config.tools["T1"]["setup_hours"] = 99
    results[0].mutated_config.shifts[0].start_min = 0
    assert (data, config) == before


def test_optimizer_failure_after_successful_mutations_preserves_inputs(monkeypatch):
    data, config = _fixture()

    def fail(*args, **kwargs):
        raise RuntimeError("isolated optimizer failure")

    monkeypatch.setattr("backend.simulator.simulator.optimize", fail)
    with pytest.raises(RuntimeError, match="isolated"):
        _simulate_unchanged(
            data,
            config,
            [
                Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": 25}),
                Mutation("force_machine", {"tool_id": "T1", "to_machine": "M2"}),
                Mutation("overtime", {"extra_min": 30}),
            ],
        )


def test_empty_result_still_blocks_missing_source_demand(monkeypatch):
    data, config = _fixture()
    monkeypatch.setattr(
        "backend.simulator.simulator.optimize",
        lambda *args, **kwargs: ScheduleResult(
            segments=[],
            lots=[],
            score={},
            time_ms=0,
            warnings=[],
            operator_alerts=[],
        ),
    )
    result = _simulate_unchanged(data, config, [])
    assert result.gate_report["metrics"]["source_missing_qty"] == 100
    assert result.gate_report["coverage_gate_passed"] is False
    assert result.gate_report["status"] == "invalid_physics"


def test_zero_capacity_empty_result_has_zero_utilization():
    data, config = _fixture()
    data.ops = []
    data.machines = []
    config.machines = {}
    result = _simulate_unchanged(data, config, [])
    assert result.score["available_capacity_min"] == 0
    assert result.delta.utilization_before == result.delta.utilization_after == 0


def test_optional_baseline_preserves_whole_started_lot_during_overtime(monkeypatch):
    data, config = _fixture()
    data.ops[0].d[7] = 1000
    baseline = _simulate_unchanged(data, config, [])
    days = {seg.day_idx for seg in baseline.segments}
    assert len(days) > 1
    baseline_result = ScheduleResult(
        segments=baseline.segments,
        lots=baseline.lots,
        score=baseline.score,
        time_ms=baseline.time_ms,
        warnings=baseline.warnings,
        operator_alerts=baseline.operator_alerts,
    )
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: min(days) + 1)
    result = _simulate_unchanged(
        data,
        config,
        [Mutation("overtime", {"extra_min": 60})],
        baseline.score,
        baseline_result=baseline_result,
    )
    assert sorted(result.segments, key=lambda s: (s.day_idx, s.start_min)) == sorted(
        baseline.segments, key=lambda s: (s.day_idx, s.start_min)
    )
    assert result.lots == baseline.lots
    assert any("preservado" in warning for warning in result.warnings)
    assert result.mutated_data.operator_blocked_intervals == []
    assert result.mutated_data.committed_supplies == []


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize(
    "mutations,expected",
    [
        (
            [
                Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": 9}),
                Mutation("demand_change", {"sku": "S1", "factor": 2}),
            ],
            {7: 200, 9: 80},
        ),
        (
            [
                Mutation("demand_change", {"sku": "S1", "factor": 2}),
                Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": 9}),
            ],
            {7: 200, 9: 40},
        ),
        (
            [
                Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": 9}),
                Mutation("cancel_order", {"sku": "S1", "from_day": 9, "to_day": 9}),
            ],
            {7: 100},
        ),
        (
            [
                Mutation("cancel_order", {"sku": "S1", "from_day": 7, "to_day": 7}),
                Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": 7}),
            ],
            {7: 40},
        ),
        (
            [
                Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": 9}),
                Mutation("advance_edd", {"sku": "S1", "days": 2}),
            ],
            {5: 100, 7: 40},
        ),
        (
            [
                Mutation("advance_edd", {"sku": "S1", "days": 2}),
                Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": 9}),
            ],
            {5: 100, 9: 40},
        ),
        (
            [
                Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": 9}),
                Mutation("delay_edd", {"sku": "S1", "days": 21}),
            ],
            {28: 100, 30: 40},
        ),
    ],
)
def test_ordered_demand_composition_is_conserved(profile, mutations, expected):
    data, config = _fixture(profile)
    result = _simulate_unchanged(data, config, mutations)
    assert {idx: qty for idx, qty in enumerate(result.mutated_data.ops[0].d) if qty} == expected
    assert result.gate_report["metrics"]["source_missing_qty"] == 0
    assert result.gate_report["coverage_gate_passed"]
    assert result.gate_report["physical_gate_passed"]


@pytest.mark.parametrize("profile", ["twin", "twin_sub"])
def test_twin_domain_failure_after_mutations_preserves_inputs(profile):
    data, config = _fixture(profile)
    with pytest.raises(ValueError, match="eco-lotes"):
        _simulate_unchanged(
            data,
            config,
            [
                Mutation("rush_order", {"sku": "S1", "qty": 40, "deadline_day": 25}),
                Mutation("force_machine", {"tool_id": "T1", "to_machine": "M2"}),
                Mutation("change_eco_lot", {"sku": "S1", "new_eco_lot": 100}),
            ],
        )


@pytest.mark.parametrize("empty", [True, False])
@pytest.mark.parametrize("with_active", [True, False])
def test_no_pending_mutations_returns_exact_baseline_without_rebuilding(
    monkeypatch, empty, with_active
):
    data, config = _fixture()
    response = _simulate_unchanged(data, config, [])
    baseline = ScheduleResult(
        segments=[] if empty else response.segments,
        lots=[] if empty else response.lots,
        score={} if empty else response.score,
        time_ms=42,
        warnings=["baseline warning"],
        operator_alerts=response.operator_alerts,
        gate_report={
            **response.gate_report,
            "solver_status": "BASELINE",
            "feasibility": {"source": "baseline"},
            "solver_trace": {"untouched": True},
        },
        solver_status="BASELINE",
        feasibility={"source": "baseline"},
    )

    def forbidden(*args, **kwargs):
        pytest.fail("No-op simulation must not calculate or rebuild the baseline")

    monkeypatch.setattr("backend.simulator.simulator.optimize", forbidden)
    monkeypatch.setattr("backend.plans.frozen.optimize_preserving_started_lots", forbidden)
    monkeypatch.setattr("backend.simulator.simulator.apply_calendars", forbidden)
    monkeypatch.setattr("backend.simulator.simulator.compute_score", forbidden)
    monkeypatch.setattr("backend.simulator.simulator.build_gate_report", forbidden)
    result = _simulate_unchanged(
        data,
        config,
        [],
        baseline.score,
        baseline_result=baseline,
        active_mutations=[Mutation("add_holiday", {"day_idx": 2})] if with_active else None,
    )
    assert result.segments == baseline.segments
    assert result.lots == baseline.lots
    assert result.score == baseline.score
    assert result.gate_report == baseline.gate_report
    assert result.warnings == baseline.warnings
    assert result.operator_alerts == baseline.operator_alerts
    assert result.mutated_data == data and result.mutated_config == config
    delta = asdict(result.delta)
    assert all(
        value == delta[key.removesuffix("_before") + "_after"]
        for key, value in delta.items()
        if key.endswith("_before")
    )
    assert result.summary == ["Sem alterações significativas nos KPIs."]
    result.gate_report["solver_trace"]["untouched"] = False
    result.warnings.append("detached")
    assert baseline.gate_report["solver_trace"]["untouched"] is True
    assert baseline.warnings == ["baseline warning"]
