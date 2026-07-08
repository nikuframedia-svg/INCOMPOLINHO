from __future__ import annotations

import pytest

from backend.config.types import FactoryConfig
from backend.scheduler.gates import build_gate_report
from backend.scheduler.types import Segment
from backend.scheduler.validation import (
    PlanValidationError,
    assert_plan_valid,
    hard_gate_metrics,
    validate_plan,
)
from backend.types import EngineData, MachineInfo


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


def test_tool_conflict_on_two_machines_is_hard_violation():
    segments = [
        _segment("A", "run_a", "M1", "T1", 0, 420, 520),
        _segment("B", "run_b", "M2", "T1", 0, 480, 560),
    ]

    violations = validate_plan(segments, _data(), FactoryConfig())

    assert any(v["kind"] == "tool_conflict" for v in violations)
    with pytest.raises(PlanValidationError):
        assert_plan_valid(segments, _data(), FactoryConfig())


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
