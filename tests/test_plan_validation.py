from __future__ import annotations

import pytest

from backend.config.types import FactoryConfig
from backend.scheduler.gates import (
    HARD_GATE_KEYS,
    authorize_application,
    blocked_application_message,
    build_gate_report,
    gate_passed,
)
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import (
    PlanValidationError,
    assert_plan_valid,
    hard_gate_metrics,
    coverage_metrics,
    validate_plan,
)
from backend.types import EOp, EngineData, MachineInfo


def _segment(
    lot_id: str,
    run_id: str,
    machine_id: str,
    tool_id: str,
    day_idx: int,
    start_min: int = 420,
    end_min: int = 520,
    setup_min: float = 0.0,
) -> Segment:
    return Segment(
        lot_id=lot_id,
        run_id=run_id,
        machine_id=machine_id,
        tool_id=tool_id,
        day_idx=day_idx,
        start_min=start_min,
        end_min=end_min,
        shift="A",
        qty=100,
        prod_min=max(0.0, end_min - start_min - setup_min),
        setup_min=setup_min,
        edd=10,
        sku=lot_id,
    )


def _data() -> EngineData:
    return EngineData(
        ops=[],
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Grandes", day_capacity=1020),
        ],
        twin_groups=[],
        client_demands={},
        workdays=[],
        n_days=20,
    )


def test_absolute_intervals_are_reused_only_within_one_validation(monkeypatch):
    from backend.scheduler import validation

    segments = [
        _segment("A", "run_a", "M1", "T1", 0, 420, 520),
        _segment("B", "run_b", "M2", "T1", 0, 480, 580),
    ]
    original = validation.segment_abs
    calls = []

    def counted(segment, config=None):
        calls.append(segment)
        return original(segment, config)

    monkeypatch.setattr(validation, "segment_abs", counted)
    assert any(v["kind"] == "tool_conflict" for v in validate_plan(segments, _data(), FactoryConfig()))
    assert len(calls) == 2
    segments[1].start_min, segments[1].end_min = 600, 700
    assert not any(v["kind"] == "tool_conflict" for v in validate_plan(segments, _data(), FactoryConfig()))
    assert len(calls) == 4


def test_reserved_setup_crew_is_validated_as_a_separate_segment():
    data = _data()
    data.setup_crew_reservations = [{
        "id": "protected-setup", "machine_id": "M1", "tool_id": "T1",
        "start_day": 0, "start_min": 420, "end_min": 450,
        "group": "Grandes",
    }]
    segment = _segment("B", "run_b", "M2", "T2", 0, 430, 520, setup_min=30)

    violations = validate_plan([segment], data, FactoryConfig())

    assert any(item["kind"] == "setup_crew_overlap" for item in violations)


def test_tool_conflict_on_two_machines_is_hard_violation():
    segments = [
        _segment("A", "run_a", "M1", "T1", 0, 420, 520),
        _segment("B", "run_b", "M2", "T1", 0, 480, 560),
    ]

    violations = validate_plan(segments, _data(), FactoryConfig())

    assert any(v["kind"] == "tool_conflict" for v in violations)
    with pytest.raises(PlanValidationError):
        assert_plan_valid(segments, _data(), FactoryConfig())


def _physical_contract() -> tuple[EngineData, Lot, Segment, FactoryConfig]:
    data = _data()
    data.ops = [
        EOp(
            id="OP1",
            sku="SKU1",
            client="C",
            designation="SKU1",
            m="M1",
            t="T1",
            pH=100,
            sH=0,
            operators=1,
            eco_lot=0,
            alt=None,
            stk=0,
            backlog=0,
            d=[100],
            oee=1,
            wip=0,
        )
    ]
    lot = Lot(
        id="LOT1",
        op_id="OP1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=0,
        edd=0,
        is_twin=False,
        sku="SKU1",
    )
    segment = _segment("LOT1", "RUN1", "M1", "T1", 0, 420, 480)
    segment.sku = "SKU1"
    config = FactoryConfig(tools={"T1": {"primary": "M1"}, "T2": {"primary": "M2"}})
    return data, lot, segment, config


def test_unknown_resources_are_hard_violations():
    data, lot, segment, config = _physical_contract()
    segment.machine_id = "M_FAKE"
    segment.tool_id = "T_FAKE"

    violations = validate_plan([segment], data, config, lots=[lot])

    assert {item["kind"] for item in violations} >= {"unknown_machine", "unknown_tool"}
    assert "unknown_machine_segments" in HARD_GATE_KEYS
    assert "unknown_tool_segments" in HARD_GATE_KEYS


def test_existing_but_ineligible_resources_are_hard_violations():
    data, lot, segment, config = _physical_contract()
    segment.machine_id = "M2"
    segment.tool_id = "T2"

    violations = validate_plan([segment], data, config, lots=[lot])

    assert {item["kind"] for item in violations} >= {
        "ineligible_machine",
        "ineligible_tool",
    }


def test_segment_minutes_must_reconcile_with_lot_minutes():
    data, lot, segment, config = _physical_contract()
    segment.end_min = 421
    segment.prod_min = 1

    violations = validate_plan([segment], data, config, lots=[lot])

    assert any(item["kind"] == "lot_production_minutes" for item in violations)
    assert "lot_production_minute_violations" in HARD_GATE_KEYS


def test_outside_shift_is_in_the_physical_hard_gate():
    assert "outside_shift_segments" in HARD_GATE_KEYS


def test_gate_reconciles_lots_against_engine_demand():
    data, _lot, _segment_value, config = _physical_contract()
    score = {
        "otd": 100,
        "otd_d": 100,
        "tardy_count": 0,
        "otd_d_failures": 0,
    }

    report = build_gate_report([], [], score, data, config)

    assert report["coverage_gate_passed"] is False
    assert report["metrics"]["source_missing_qty"] == 100
    assert report["apply_decision"] == "blocked"


def test_detached_setup_is_a_hard_violation():
    setup = Segment(
        lot_id="A",
        run_id="run_a",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=420,
        end_min=450,
        shift="A",
        qty=0,
        prod_min=0,
        setup_min=30,
        edd=5,
        sku="A",
    )
    production = _segment("A", "run_a", "M1", "T1", 1, 420, 480)

    violations = validate_plan([setup, production], _data(), FactoryConfig())
    metrics = hard_gate_metrics(violations)

    assert any(item["kind"] == "detached_setup" for item in violations)
    assert metrics["detached_setup_violations"] == 1
    with pytest.raises(PlanValidationError):
        assert_plan_valid([setup, production], _data(), FactoryConfig())


def test_setup_at_end_of_day_can_feed_next_workday_production():
    setup = Segment(
        lot_id="A",
        run_id="run_a",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=1410,
        end_min=1440,
        shift="B",
        qty=0,
        prod_min=0,
        setup_min=30,
        edd=5,
        sku="A",
    )
    production = _segment("A", "run_a", "M1", "T1", 1, 420, 480)

    violations = validate_plan([setup, production], _data(), FactoryConfig())

    assert not [item for item in violations if item["kind"] == "detached_setup"]


def test_setup_at_friday_close_can_feed_monday_opening_production():
    data = _data()
    data.workdays = [
        "2026-09-17",
        "2026-09-18",
        "2026-09-19",
        "2026-09-20",
        "2026-09-21",
    ]
    setup = Segment(
        lot_id="A",
        run_id="run_a",
        machine_id="M1",
        tool_id="T1",
        day_idx=1,
        start_min=1410,
        end_min=1440,
        shift="B",
        qty=0,
        prod_min=0,
        setup_min=30,
        edd=5,
        sku="A",
    )
    production = _segment("A", "run_a", "M1", "T1", 4, 420, 480)

    violations = validate_plan([setup, production], data, FactoryConfig())

    assert not [item for item in violations if item["kind"] == "detached_setup"]


def test_shift_break_does_not_overlap_next_factory_day():
    config = FactoryConfig()
    config.shifts[0].end_min = 900  # 15:00-15:30 is closed factory time.
    previous = _segment("A", "run_a", "M1", "T1", 0, 1390, 1440)
    following = _segment("B", "run_b", "M1", "T1", 1, 420, 480)

    violations = validate_plan([previous, following], _data(), config)

    assert not [item for item in violations if item["kind"] == "machine_overlap"]


def test_setup_before_material_release_is_a_hard_violation():
    data = _data()
    data.n_days = 12
    lot = Lot(
        id="A",
        op_id="OP-A",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=30,
        edd=8,
        is_twin=False,
        delivery_day=8,
    )
    setup = Segment(
        lot_id="A",
        run_id="run_a",
        machine_id="M1",
        tool_id="T1",
        day_idx=2,
        start_min=1410,
        end_min=1440,
        shift="B",
        qty=0,
        prod_min=0,
        setup_min=30,
        edd=8,
        sku="A",
    )
    production = _segment("A", "run_a", "M1", "T1", 3, 420, 480)

    violations = validate_plan(
        [setup, production],
        data,
        FactoryConfig(),
        lots=[lot],
    )

    assert [item for item in violations if item["kind"] == "setup_before_material"]
    with pytest.raises(PlanValidationError):
        assert_plan_valid(
            [setup, production],
            data,
            FactoryConfig(),
            lots=[lot],
        )


def test_short_but_immediate_production_after_setup_is_valid():
    opening = Segment(
        lot_id="A",
        run_id="run_a",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=420,
        end_min=496,
        shift="A",
        qty=1,
        prod_min=1,
        setup_min=75,
        edd=5,
        sku="A",
    )
    continuation = _segment("A", "run_a", "M1", "T1", 1, 420, 540)

    violations = validate_plan([opening, continuation], _data(), FactoryConfig())

    assert not [
        item
        for item in violations
        if item["kind"] in {"detached_setup", "setup_production_discontinuity"}
    ]


def test_contiguous_setup_fragments_across_shift_count_as_one_setup():
    setup_a = Segment(
        lot_id="A",
        run_id="run_a",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=918,
        end_min=930,
        shift="A",
        qty=0,
        prod_min=0,
        setup_min=12,
        edd=5,
        sku="A",
    )
    setup_b_and_production = Segment(
        lot_id="A",
        run_id="run_a",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=930,
        end_min=1008,
        shift="B",
        qty=100,
        prod_min=60,
        setup_min=18,
        edd=5,
        sku="A",
        is_continuation=True,
    )

    segments = [setup_a, setup_b_and_production]
    violations = validate_plan(segments, _data(), FactoryConfig())
    score = compute_score(segments, [], _data(), FactoryConfig())

    assert not [
        item
        for item in violations
        if item["kind"] in {"detached_setup", "run_setup_order"}
    ]
    assert score["setups"] == 1
    assert score["setup_time_min"] == 30


def test_tool_return_after_another_tool_requires_a_new_setup():
    first = _segment("A", "run_a", "M1", "T1", 0, 420, 510, setup_min=30)
    first.run_setup_min = 30
    blocker = _segment("B", "run_b", "M1", "T2", 0, 510, 600, setup_min=30)
    blocker.run_setup_min = 30
    returning = _segment("A", "run_a", "M1", "T1", 0, 620, 680)
    returning.run_setup_min = 30

    violations = validate_plan(
        [first, blocker, returning],
        _data(),
        FactoryConfig(),
    )
    metrics = hard_gate_metrics(violations)

    assert [
        item for item in violations if item["kind"] == "missing_tool_change_setup"
    ]
    assert metrics["missing_tool_change_setup_violations"] == 1


def test_tool_change_requires_the_complete_setup_duration():
    first = _segment("A", "run_a", "M1", "T1", 0, 420, 510, setup_min=30)
    first.run_setup_min = 30
    truncated = _segment("B", "run_b", "M1", "T2", 0, 510, 611, setup_min=1)
    truncated.run_setup_min = 60

    violations = validate_plan(
        [first, truncated],
        _data(),
        FactoryConfig(),
    )
    metrics = hard_gate_metrics(violations)
    detail = next(
        item
        for item in violations
        if item["kind"] == "insufficient_tool_change_setup"
    )

    assert detail["actual_setup_min"] == 1
    assert detail["required_setup_min"] == 60
    assert metrics["insufficient_tool_change_setup_violations"] == 1


def test_same_tool_reference_change_requires_a_new_setup():
    first = _segment("REF-A", "run_a", "M1", "T1", 0, 420, 510, setup_min=30)
    first.run_setup_min = 30
    second = _segment("REF-B", "run_b", "M1", "T1", 0, 510, 570)
    second.run_setup_min = 30

    violations = validate_plan([first, second], _data(), FactoryConfig())

    detail = next(
        item for item in violations if item["kind"] == "missing_tool_change_setup"
    )
    assert detail["transition"] == "machine_setup_change"
    assert detail["actual_setup_min"] == 0
    assert detail["required_setup_min"] == 30


def test_same_tool_reference_change_with_complete_setup_is_valid():
    first = _segment("REF-A", "run_a", "M1", "T1", 0, 420, 510, setup_min=30)
    first.run_setup_min = 30
    second = _segment("REF-B", "run_b", "M1", "T1", 0, 510, 600, setup_min=30)
    second.run_setup_min = 30

    violations = validate_plan([first, second], _data(), FactoryConfig())

    assert not [
        item
        for item in violations
        if item["kind"]
        in {"missing_tool_change_setup", "insufficient_tool_change_setup"}
    ]


def test_configured_setup_family_does_not_require_a_second_setup():
    first = _segment("REF-A", "run_a", "M1", "T1", 0, 420, 510, setup_min=30)
    first.run_setup_min = 30
    first.setup_family = "REF-A|REF-B"
    second = _segment("REF-B", "run_b", "M1", "T1", 0, 510, 570)
    second.run_setup_min = 30
    second.setup_family = "REF-A|REF-B"

    violations = validate_plan([first, second], _data(), FactoryConfig())

    assert not [
        item
        for item in violations
        if item["kind"]
        in {"missing_tool_change_setup", "insufficient_tool_change_setup"}
    ]


def test_true_twin_adjustment_is_retained_across_primary_sku_changes():
    first = _segment("TWIN-A", "run_a", "M1", "T1", 0, 420, 510, setup_min=30)
    first.run_setup_min = 30
    first.twin_outputs = [("OPA", "REF-A", 100), ("OPB", "REF-B", 100)]
    second = _segment("TWIN-B", "run_b", "M1", "T1", 0, 510, 570)
    second.run_setup_min = 30
    second.twin_outputs = [("OPA", "REF-A", 100), ("OPB", "REF-B", 100)]

    violations = validate_plan([first, second], _data(), FactoryConfig())

    assert not [
        item
        for item in violations
        if item["kind"]
        in {"missing_tool_change_setup", "insufficient_tool_change_setup"}
    ]


def test_complete_setup_split_at_shift_boundary_is_valid():
    first = _segment("A", "run_a", "M1", "T1", 0, 420, 900, setup_min=30)
    first.run_setup_min = 30
    setup_a = _segment("B", "run_b", "M1", "T2", 0, 900, 930, setup_min=30)
    setup_a.prod_min = 0
    setup_a.qty = 0
    setup_a.run_setup_min = 60
    setup_b = _segment("B", "run_b", "M1", "T2", 0, 930, 1020, setup_min=30)
    setup_b.prod_min = 60
    setup_b.run_setup_min = 60
    setup_b.shift = "B"

    violations = validate_plan(
        [first, setup_a, setup_b],
        _data(),
        FactoryConfig(),
    )

    assert not [
        item
        for item in violations
        if item["kind"]
        in {"missing_tool_change_setup", "insufficient_tool_change_setup"}
    ]


def test_final_validation_rejects_missing_lot_quantity_when_lots_are_provided():
    lot = Lot(
        id="A",
        op_id="OP-A",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=100,
        setup_min=0,
        edd=1,
        is_twin=False,
    )

    with pytest.raises(PlanValidationError) as exc:
        assert_plan_valid([], _data(), FactoryConfig(), lots=[lot])

    assert exc.value.violations[0]["kind"] == "missing_lots"


def test_machine_down_blocks_negative_buffer_days():
    data = _data()
    data.machine_blocked_days = {"M1": {-6, -5, -4, -3, -2, -1}}
    segments = [_segment("A", "run_a", "M1", "T1", -6)]

    violations = validate_plan(segments, data, FactoryConfig())

    assert [v["kind"] for v in violations] == ["machine_down"]


def test_run_cannot_produce_before_own_setup_finishes():
    segments = [
        _segment("setup", "run_a", "M1", "T1", 0, 500, 620, setup_min=90),
        _segment("prod", "run_a", "M1", "T1", 0, 540, 620),
    ]

    violations = validate_plan(segments, _data(), FactoryConfig())

    assert any(v["kind"] == "run_setup_order" for v in violations)


def test_single_setup_crew_overlap_is_hard_violation():
    segments = [
        _segment("A", "run_a", "M1", "T1", 0, 420, 560, setup_min=90),
        _segment("B", "run_b", "M2", "T2", 0, 450, 590, setup_min=90),
    ]

    violations = validate_plan(segments, _data(), FactoryConfig())
    metrics = hard_gate_metrics(violations)

    assert metrics["setup_crew_overlaps"] == 1
    assert any(v["kind"] == "setup_crew_overlap" for v in violations)
    with pytest.raises(PlanValidationError):
        assert_plan_valid(segments, _data(), FactoryConfig())


def test_gate_report_never_proposes_second_setup_crew():
    segments = [
        _segment("A", "run_a", "M1", "T1", 0, 420, 560, setup_min=90),
        _segment("B", "run_b", "M2", "T2", 0, 450, 590, setup_min=90),
    ]
    score = {"otd": 100.0, "otd_d": 100.0, "tardy_count": 0, "otd_d_failures": 0}

    report = build_gate_report(segments, [], score, _data(), FactoryConfig())
    proposal_text = " ".join(str(p) for p in report["proposals"]).lower()

    assert report["status"] == "invalid_physics"
    assert report["metrics"]["setup_crew_overlaps"] == 1
    assert "segunda equipa" not in proposal_text
    assert "second" not in proposal_text


def test_gate_report_proposals_include_before_after_targets():
    segments = [
        _segment("A", "run_a", "M1", "T1", 0, 420, 560, setup_min=90),
        _segment("B", "run_b", "M2", "T2", 0, 450, 590, setup_min=90),
    ]
    score = {"otd": 100.0, "otd_d": 100.0, "tardy_count": 0, "otd_d_failures": 0}

    report = build_gate_report(segments, [], score, _data(), FactoryConfig())
    proposal = report["proposals"][0]

    assert proposal["before"]["setup_crew_overlaps"] == 1
    assert proposal["after_target"]["setup_crew_overlaps"] == 0
    assert proposal["requires_validation"] is True
    assert "cria atraso" in proposal["rejection_reasons"]


def test_missing_lot_is_a_hard_coverage_gate():
    lot = Lot(
        id="L1",
        op_id="OP1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=30,
        edd=5,
        is_twin=False,
    )
    score = {"otd": 0.0, "otd_d": 0.0, "tardy_count": 1, "otd_d_failures": 1}

    report = build_gate_report([], [lot], score, _data(), FactoryConfig())

    assert report["coverage_gate_passed"] is False
    assert report["physical_gate_passed"] is False
    assert report["metrics"]["missing_lots"] == 1
    assert report["metrics"]["missing_qty"] == 100


def test_non_physical_exception_requires_explicit_audited_approval():
    report = {
        "apply_decision": "approval_required",
        "requires_approval": True,
        "approval_reasons": ["jit_window_exception"],
        "physical_gate_passed": True,
        "coverage_gate_passed": True,
    }

    assert gate_passed(report) is False
    with pytest.raises(ValueError, match="aprovação explícita"):
        authorize_application(report)
    with pytest.raises(ValueError, match="motivo e autor"):
        authorize_application(report, approve_exceptions=True)

    approval = authorize_application(
        report,
        approve_exceptions=True,
        approval_reason="Proteger a entrega contratual",
        approval_author="planeador",
    )
    assert approval["author"] == "planeador"
    assert approval["approval_reasons"] == ["jit_window_exception"]


def test_jit_window_violation_blocks_application():
    data = _data()
    lot = Lot(
        id="L1",
        op_id="OP1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=0,
        edd=10,
        is_twin=False,
    )
    lot.delivery_day = 10
    segment = _segment("L1", "R1", "M1", "T1", 0, 420, 480)
    score = compute_score([segment], [lot], data, FactoryConfig())

    report = build_gate_report([segment], [lot], score, data, FactoryConfig())

    assert report["jit_window_gate_passed"] is False
    assert report["status"] == "jit_window_blocked"
    assert report["apply_decision"] == "blocked"
    assert gate_passed(report) is False


def test_jit_window_blocked_message_names_operational_cause():
    # An old saved report may still carry robustness reasons; robustness is
    # informational only and never explains a blocked application.
    report = {
        "status": "jit_window_blocked",
        "apply_decision": "blocked",
        "requires_approval": False,
        "approval_reasons": ["jit_window_blocked", "robustness_below_threshold"],
        "physical_gate_passed": True,
        "coverage_gate_passed": True,
        "jit_window_gate_passed": False,
        "robustness_gate_passed": False,
        "metrics": {
            "early_window_violations": 17,
            "robustness_success_probability_pct": 0.0,
            "robustness_threshold_pct": 95.0,
        },
    }

    message = blocked_application_message(report)

    assert "17 produção(ões) antecipada(s)" in message
    assert "janela JIT dos 5 dias úteis" in message
    assert "robustez" not in message
    assert "conflitos físicos" not in message


def test_physical_conflict_is_blocked_even_with_approval():
    report = {
        "apply_decision": "blocked",
        "requires_approval": False,
        "approval_reasons": [],
        "physical_gate_passed": False,
        "coverage_gate_passed": True,
    }
    with pytest.raises(ValueError, match="conflitos físicos"):
        authorize_application(
            report,
            approve_exceptions=True,
            approval_reason="Não deve ultrapassar física",
            approval_author="planeador",
        )


def test_twin_outputs_are_quantity_conserved():
    lot = Lot(
        id="TWIN",
        op_id="OPA",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=0,
        edd=5,
        is_twin=True,
        twin_outputs=[("OPA", "A", 100), ("OPB", "B", 100)],
    )
    segment = _segment("TWIN", "run", "M1", "T1", 1, 420, 480)
    segment.qty = 100
    segment.twin_outputs = [("OPA", "A", 100), ("OPB", "B", 100)]

    metrics = coverage_metrics([segment], [lot])

    assert metrics["missing_qty"] == 0
    assert metrics["overproduced_qty"] == 0
    assert metrics["twin_output_mismatches"] == 0


def test_unequal_twin_outputs_are_a_hard_coverage_failure():
    lot = Lot(
        id="TWIN",
        op_id="OPA",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=0,
        edd=5,
        is_twin=True,
        twin_outputs=[("OPA", "A", 100), ("OPB", "B", 80)],
    )
    segment = _segment("TWIN", "run", "M1", "T1", 1, 420, 480)
    segment.twin_outputs = [("OPA", "A", 100), ("OPB", "B", 80)]

    metrics = coverage_metrics([segment], [lot])

    assert metrics["twin_output_mismatches"] > 0


def test_repeated_twin_obligation_is_a_hard_coverage_failure():
    milestone = {
        "op_id": "OPB",
        "sku": "B",
        "qty": 100,
        "customer_delivery_day": 5,
        "production_due_day": 3,
        "material_release_day": 0,
    }
    lots = [
        Lot(
            id=lot_id,
            op_id="OPB",
            tool_id="T1",
            machine_id="M1",
            alt_machine_id=None,
            qty=100,
            prod_min=60,
            setup_min=0,
            edd=3,
            is_twin=True,
            sku="B",
            twin_outputs=[("OPA", "A", 0), ("OPB", "B", 100)],
            output_milestones=[dict(milestone)],
        )
        for lot_id in ("TWIN-B", "TWIN-MERGED")
    ]
    segments = [
        _segment("TWIN-B", "run-b", "M1", "T1", 1, 420, 480),
        _segment("TWIN-MERGED", "run-m", "M1", "T1", 1, 480, 540),
    ]
    for segment in segments:
        segment.qty = 100
        segment.twin_outputs = [("OPA", "A", 0), ("OPB", "B", 100)]

    metrics = coverage_metrics(segments, lots)

    assert metrics["overproduced_qty"] == 0
    assert metrics["duplicate_twin_output_qty"] == 100
    assert metrics["duplicate_production_qty"] == 100
    assert "duplicate_twin_output_qty" in HARD_GATE_KEYS


def test_otd_d_percentage_is_bounded_when_many_checkpoints_fail():
    data = _data()
    data.n_days = 12
    data.ops = [
        EOp(
            id="OP1",
            sku="A",
            client="C",
            designation="A",
            m="M1",
            t="T1",
            pH=100,
            sH=0.5,
            operators=1,
            eco_lot=0,
            alt=None,
            stk=0,
            backlog=0,
            d=[100] * 12,
            oee=0.66,
            wip=0,
        )
    ]

    score = compute_score([], [], data, FactoryConfig())

    assert score["otd_d"] == 0.0
    assert score["otd_d_checkpoints"] == 12
    assert score["otd_d_failures"] == 12
