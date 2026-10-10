"""An operational audit that did not finish is pending, never a pass (A3, T6).

The cheap metrics (left-shift gaps, campaign interruptions, shared-tool
inversions and the priority-anomaly count) are always computed; only the slow
classification of avoidable priority anomalies is bounded, by a work budget
(a count of anomalies), never by wall-clock time: the same plan always gets
the same status whatever the machine load. Campaign
interruptions are measured per physical run, so the per-delivery portions of
one economic lot are not "interrupted" by the work placed between them.
"""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import pytest

from backend.planning_control import PlanningTimeout, planning_checkpoint, planning_scope
from backend.scheduler import operational_audit
from backend.scheduler.gates import blocked_application_message, build_gate_report, gate_passed
from backend.scheduler.operational_audit import (
    _lower_priority_campaign_interruptions,
    build_operational_audit,
)
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData, MachineInfo

ROOT = Path(__file__).resolve().parents[1]
REV121 = ROOT / "tests" / "fixtures" / "private" / "rev121.json.gz"


def _lot(lot_id: str, rupture: int, tool: str = "T1") -> Lot:
    return Lot(
        id=lot_id, op_id=lot_id, tool_id=tool, machine_id="M1", alt_machine_id=None,
        qty=100, prod_min=60, setup_min=0, edd=rupture, is_twin=False,
        original_edd=rupture,
    )


def _segment(lot_id: str, day: int, start: int, *, run_id: str | None = None,
             tool: str = "T1") -> Segment:
    return Segment(
        lot_id=lot_id, run_id=run_id or f"RUN-{lot_id}", machine_id="M1", tool_id=tool,
        day_idx=day, start_min=start, end_min=start + 60, shift="A", qty=100, prod_min=60,
    )


def _data() -> EngineData:
    return EngineData(
        ops=[], machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[], client_demands={},
        workdays=[f"2026-09-{day:02d}" for day in range(1, 21)], n_days=20, holidays=[],
    )


def _slow_classification(*_args, **_kwargs):
    while True:
        planning_checkpoint()
        time.sleep(0.005)


def _unexpected_classification(*_args, **_kwargs):
    raise AssertionError("over the work budget the classification must not run")


def _interrupted_campaign():
    """URGENT's single run is interrupted by LATER; FIRST before SOON is an anomaly."""
    urgent, later = _lot("URGENT", 8), _lot("LATER", 12)
    first, soon = _lot("FIRST", 12), _lot("SOON", 8, tool="T2")
    segments = [
        _segment("FIRST", 1, 420),
        _segment("SOON", 2, 420, tool="T2"),
        _segment("URGENT", 3, 420),
        _segment("LATER", 4, 420),
        _segment("URGENT", 5, 420),
    ]
    return segments, [urgent, later, first, soon]


def _clean_plan_with_anomaly():
    """No gap, interruption or tool inversion; one priority anomaly to classify."""
    urgent, later = _lot("URGENT", 8, tool="T2"), _lot("LATER", 12)
    return [_segment("LATER", 3, 420), _segment("URGENT", 4, 420, tool="T2")], [urgent, later]


def _pending_audit(monkeypatch, segments, lots):
    monkeypatch.setattr(
        operational_audit, "classify_priority_order_anomalies", _unexpected_classification,
    )
    return build_operational_audit(segments, lots, _data(), classification_budget=0)


# ── T6: a pending audit is reported, never counted as approved ──────────────


def test_timed_out_classification_keeps_cheap_metrics_exact(monkeypatch):
    segments, lots = _interrupted_campaign()
    complete = build_operational_audit(segments, lots, _data(), classification_budget=None)
    assert complete["status"] == "evaluated"

    pending = _pending_audit(monkeypatch, segments, lots)

    assert pending["status"] == "not_evaluated"
    assert pending["stop_reason"] == "audit_budget"
    assert pending["unevaluated_metrics"] == ["avoidable_priority_order_anomalies"]
    # Cheap metrics are identical to the complete audit, not zeros.
    for key in (
        "left_shift_opportunities",
        "lower_priority_campaign_interruptions",
        "priority_order_anomalies",
        "released_tool_priority_inversions",
    ):
        assert pending[key] == complete[key], key
    assert pending["lower_priority_campaign_interruptions"] == 1


def test_pending_audit_is_never_a_pass_even_with_clean_cheap_metrics(monkeypatch):
    segments, lots = _clean_plan_with_anomaly()
    data = _data()
    audit = _pending_audit(monkeypatch, segments, lots)
    assert audit["status"] == "not_evaluated"
    assert audit["left_shift_opportunities"] == 0
    assert audit["lower_priority_campaign_interruptions"] == 0
    assert audit["released_tool_priority_inversions"] == 0
    # The anomaly is still counted; only its classification is pending.
    assert audit["priority_order_anomalies"] == 1
    assert audit["avoidable_priority_order_anomalies"] == 0
    assert [item["verification_status"] for item in audit["priority_order_detail"]] == [
        "not_evaluated"
    ]

    score = compute_score(segments, lots, data, operational_audit=audit)
    report = build_gate_report(segments, lots, score, data, None, operational_audit=audit)

    assert score["operational_audit_status"] == "not_evaluated"
    assert report["operational_audit_status"] == "not_evaluated"
    assert report["operational_gate_passed"] is False
    assert "operational_sequence_not_evaluated" in report["approval_reasons"]
    assert "operational_sequence_review" not in report["approval_reasons"]
    assert report["apply_decision"] != "auto_applicable"
    assert not gate_passed(report)
    message = blocked_application_message(report)
    assert "por avaliar" in message
    assert "0 intervalo" not in message


def test_complete_clean_audit_still_passes_the_operational_gate():
    segments = [_segment("ONLY", 3, 420)]
    lots = [_lot("ONLY", 8)]
    data = _data()
    audit = build_operational_audit(segments, lots, data)
    score = compute_score(segments, lots, data, operational_audit=audit)
    report = build_gate_report(segments, lots, score, data, None, operational_audit=audit)

    assert audit["status"] == "evaluated"
    assert score["operational_audit_status"] == "evaluated"
    assert report["operational_gate_passed"] is True
    assert not {
        "operational_sequence_review", "operational_sequence_not_evaluated",
    } & set(report["approval_reasons"])


def test_stored_audit_without_status_was_complete():
    segments = [_segment("ONLY", 3, 420)]
    lots = [_lot("ONLY", 8)]
    data = _data()
    legacy = {
        "left_shift_opportunities": 0,
        "lower_priority_campaign_interruptions": 0,
        "priority_order_anomalies": 0,
        "avoidable_priority_order_anomalies": 0,
        "released_tool_priority_inversions": 0,
    }
    score = compute_score(segments, lots, data, operational_audit=legacy)
    report = build_gate_report(segments, lots, score, data, None, operational_audit=legacy)
    assert report["operational_audit_status"] == "evaluated"
    assert report["operational_gate_passed"] is True


def test_dirty_and_pending_audit_reports_both_reasons(monkeypatch):
    segments, lots = _interrupted_campaign()
    data = _data()
    audit = _pending_audit(monkeypatch, segments, lots)
    score = compute_score(segments, lots, data, operational_audit=audit)
    report = build_gate_report(segments, lots, score, data, None, operational_audit=audit)
    assert {"operational_sequence_review", "operational_sequence_not_evaluated"} <= set(
        report["approval_reasons"]
    )
    # The toy plan has no setups; read the operational wording on its own.
    message = blocked_application_message(
        {**report, "physical_gate_passed": True, "coverage_gate_passed": True}
    )
    assert "por avaliar" in message and "1 interrupção" in message


def test_outer_deadline_still_wins_over_the_audit_budget(monkeypatch):
    segments, lots = _interrupted_campaign()
    monkeypatch.setattr(
        operational_audit, "classify_priority_order_anomalies", _slow_classification,
    )
    with pytest.raises(PlanningTimeout), planning_scope(timeout_s=0.05):
        build_operational_audit(segments, lots, _data(), classification_budget=30)


# ── Determinism: the status depends on the plan, never on the clock ─────────


def test_slow_classification_within_budget_is_still_evaluated(monkeypatch):
    """A loaded host makes the classification slow; it must not flip the status."""
    segments, lots = _clean_plan_with_anomaly()
    real = operational_audit.classify_priority_order_anomalies

    def slow_but_complete(*args, **kwargs):
        time.sleep(1.2)  # longer than the old 1 s wall-clock cap
        return real(*args, **kwargs)

    monkeypatch.setattr(operational_audit, "classify_priority_order_anomalies", slow_but_complete)
    audit = build_operational_audit(segments, lots, _data(), classification_budget=1)
    assert audit["status"] == "evaluated"
    assert audit["priority_order_detail"][0]["verification_status"] != "not_evaluated"


def test_over_budget_is_decided_by_count_not_time(monkeypatch):
    segments, lots = _clean_plan_with_anomaly()
    monkeypatch.setattr(
        operational_audit, "classify_priority_order_anomalies", _unexpected_classification,
    )
    first = build_operational_audit(segments, lots, _data(), classification_budget=0)
    second = build_operational_audit(segments, lots, _data(), classification_budget=0)
    assert first == second
    assert first["status"] == "not_evaluated"


def test_default_budget_is_a_count():
    assert isinstance(operational_audit.PRIORITY_CLASSIFICATION_MAX_ANOMALIES, int)
    assert not hasattr(operational_audit, "PRIORITY_CLASSIFICATION_BUDGET_S")


# ── Campaign interruptions per physical run ─────────────────────────────────


def test_work_between_two_delivery_runs_of_one_lot_is_not_an_interruption():
    """Each delivery portion is its own run; the gap is the material window."""
    urgent, later = _lot("URGENT", 8), _lot("LATER", 12)
    segments = [
        _segment("URGENT", 3, 420, run_id="URGENT#1"),
        _segment("LATER", 4, 420),
        _segment("URGENT", 5, 420, run_id="URGENT#2"),
    ]
    assert _lower_priority_campaign_interruptions(segments, [urgent, later]) == []


def test_interruption_inside_one_run_is_counted_once_per_lot_pair():
    urgent, later = _lot("URGENT", 8), _lot("LATER", 12)
    segments = [
        _segment("URGENT", 3, 420, run_id="URGENT#1"),
        _segment("LATER", 3, 480),
        _segment("URGENT", 3, 540, run_id="URGENT#1"),
        _segment("URGENT", 6, 420, run_id="URGENT#2"),
        _segment("LATER", 6, 480),
        _segment("URGENT", 6, 540, run_id="URGENT#2"),
    ]
    detail = _lower_priority_campaign_interruptions(segments, [urgent, later])
    assert [(item["urgent_lot_id"], item["blocking_lot_id"]) for item in detail] == [
        ("URGENT", "LATER")
    ]
    assert detail[0]["run_id"] == "URGENT#1"


def test_more_urgent_work_inside_a_run_is_not_reported():
    urgent, later = _lot("URGENT", 8), _lot("LATER", 12)
    segments = [
        _segment("LATER", 3, 420),
        _segment("URGENT", 3, 480),
        _segment("LATER", 3, 540),
    ]
    assert _lower_priority_campaign_interruptions(segments, [urgent, later]) == []


# ── Revision 121 (private fixture): bounded and honest ─────────────────────


@pytest.fixture(scope="module")
def rev121():
    if not REV121.exists():
        pytest.skip("private fixture rev121.json.gz absent")
    from backend.plans.serialize import assert_snapshot_integrity, deserialize_snapshot

    payload = json.loads(gzip.decompress(REV121.read_bytes()).decode("utf-8"))
    assert payload.get("plan_revision") == 121
    assert_snapshot_integrity(payload)
    restored = deserialize_snapshot(payload)
    return restored["engine_data"], restored["config"], restored["result"]


def test_rev121_audit_is_bounded_and_pending_not_passed(rev121):
    data, config, result = rev121
    segments, lots = result.segments, result.lots

    started = time.perf_counter()
    cheap = build_operational_audit(segments, lots, data, config, classification_budget=0)
    cheap_s = time.perf_counter() - started
    started = time.perf_counter()
    audit = build_operational_audit(segments, lots, data, config)
    bounded_s = time.perf_counter() - started

    # Measured ~0.3 s on one core for both; margin for a loaded host.
    assert cheap_s < 1.5, cheap_s
    assert bounded_s < 2.0, bounded_s
    # 3139 anomalies exceed the work budget: deterministic, not a race.
    assert audit["priority_order_anomalies"] > operational_audit.PRIORITY_CLASSIFICATION_MAX_ANOMALIES
    assert audit["status"] == "not_evaluated"
    # Real findings are visible instead of zeros.
    assert audit["priority_order_anomalies"] > 0
    assert audit["released_tool_priority_inversions"] > 0
    assert audit["left_shift_opportunities"] > 0
    # 795 per-lot "interruptions" were per-delivery runs; per run there are none.
    assert audit["lower_priority_campaign_interruptions"] == 0
    for key in (
        "left_shift_opportunities",
        "lower_priority_campaign_interruptions",
        "priority_order_anomalies",
        "released_tool_priority_inversions",
    ):
        assert cheap[key] == audit[key], key

    score = compute_score(segments, lots, data, config, operational_audit=audit)
    report = build_gate_report(segments, lots, score, data, config, operational_audit=audit)
    assert score["operational_audit_status"] == "not_evaluated"
    assert report["operational_gate_passed"] is False
    assert "operational_sequence_not_evaluated" in report["approval_reasons"]
    assert report["apply_decision"] != "auto_applicable"


def test_rev121_audit_is_identical_on_repeat_and_under_a_slow_classifier(rev121, monkeypatch):
    """Same plan, same answer: no wall-clock dependency anywhere in the status."""
    data, config, result = rev121
    first = build_operational_audit(result.segments, result.lots, data, config)
    monkeypatch.setattr(
        operational_audit, "classify_priority_order_anomalies", _unexpected_classification,
    )
    second = build_operational_audit(result.segments, result.lots, data, config)
    assert first == second
    assert first["status"] == "not_evaluated"
