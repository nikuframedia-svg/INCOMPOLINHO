"""An operational audit that did not finish is pending, never a pass (A3, T6).

The cheap metrics (left-shift gaps, campaign interruptions, shared-tool
inversions and the priority-anomaly count) are always computed; only the slow
classification of avoidable priority anomalies is bounded, by a work budget
(a count of anomalies), never by wall-clock time: the same plan always gets
the same status whatever the machine load. Over the budget the most urgent
anomalies are still classified (proven findings first, B4.4) and the rest
stay pending, so the audit stays "por avaliar" (AGENTS §6). Pairs with a
protected lot are explained before the budget is spent. Campaign
interruptions are measured per physical run, so the per-delivery portions of
one economic lot are not "interrupted" by the work placed between them.

Priority-order anomalies are counted per delivery: a run is ranked by the
most urgent delivery it makes, released by that delivery's own material.
Ranked by its whole lot, every later delivery run of a lot looked urgent and
blocked (3139 anomalies on revision 121, none of them real).
"""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import pytest

from backend.config.types import FactoryConfig
from backend.planning_control import PlanningTimeout, planning_checkpoint, planning_scope
from backend.scheduler import operational_audit
from backend.scheduler.gates import blocked_application_message, build_gate_report, gate_passed
from backend.scheduler.jit_policy import calendar_holidays
from backend.scheduler.operational_audit import (
    _lower_priority_campaign_interruptions,
    _run_units,
    build_operational_audit,
    classify_priority_order_anomalies,
    find_output_priority_anomalies,
)
from backend.scheduler.priority_normalization import find_priority_order_anomalies
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
    # 32 covers the 14-20 anomalies left on the real cases (review b3r2 #3).
    assert operational_audit.PRIORITY_CLASSIFICATION_MAX_ANOMALIES == 32


# ── Avoidable means: the improvement loop would accept the rotation ────────


def _spy(monkeypatch, module, name, replacement=None):
    real = getattr(module, name)
    calls = []

    def wrapper(*args, **kwargs):
        result = (replacement or real)(*args, **kwargs)
        calls.append(result)
        return result

    monkeypatch.setattr(module, name, wrapper)
    return calls


def test_avoidable_rotation_is_one_the_loop_accepts(monkeypatch):
    """Per-order no loss, then the shared comparator: ``improvement_better``."""
    from backend.scheduler import improvement

    segments, lots = _clean_plan_with_anomaly()
    no_loss = _spy(monkeypatch, improvement, "no_loss_verdict")
    better = _spy(monkeypatch, improvement, "improvement_better")
    (item,) = classify_priority_order_anomalies(segments, lots, _data(), FactoryConfig())
    assert item["verification_status"] == "permutable"
    assert no_loss and all(verdict.admissible for verdict in no_loss)
    assert better[-1] is True


def test_a_rotation_the_comparator_rejects_is_not_avoidable(monkeypatch):
    """Review b3r2 #3: the audit called avoidable rotations the loop refuses
    (later under ``anticipation_compare``)."""
    from backend.scheduler import improvement

    segments, lots = _clean_plan_with_anomaly()
    _spy(monkeypatch, improvement, "improvement_better", lambda *_args: False)
    (item,) = classify_priority_order_anomalies(segments, lots, _data(), FactoryConfig())
    assert item["verification_status"] == "counterfactual_required"
    assert item["blocking_reasons"] == ["counterfactual_not_earlier"]


def test_a_rotation_losing_an_order_is_not_avoidable_whatever_the_aggregate(monkeypatch):
    """Per-order loss decides; the aggregate ``delivery_not_worse`` is not read."""
    from backend.scheduler import improvement, priority_normalization
    from backend.scheduler.improvement import ContractVerdict

    def aggregate(*_args, **_kwargs):
        raise AssertionError("the audit must use the loop's per-order contract")

    monkeypatch.setattr(priority_normalization, "delivery_not_worse", aggregate)
    _spy(
        monkeypatch, improvement, "no_loss_verdict",
        lambda *_args: ContractVerdict(False, ["encomenda X/- dia 8: atraso aumenta"]),
    )
    segments, lots = _clean_plan_with_anomaly()
    (item,) = classify_priority_order_anomalies(segments, lots, _data(), FactoryConfig())
    assert item["verification_status"] == "delivery_blocked"
    assert item["blocking_reasons"] == ["encomenda X/- dia 8: atraso aumenta"]


def _surplus_plan(*, mixed: bool):
    """A: 100 pcs due day 13, 50 due day 20 and an economic surplus of 150;
    B: one delivery due day 25, material released on day 10."""
    from dataclasses import replace

    from backend.scheduler.lot_sizing import create_lots
    from tests.test_output_anticipation import _segment as segment
    from tests.test_quantity_campaigns import _data as data_of
    from tests.test_quantity_campaigns import _op

    data = data_of([_op("A", "TA", {13: 100, 20: 50}, eco_lot=300), _op("B", "TB", {25: 80})])
    lot_a, lot_b = sorted(create_lots(data), key=lambda lot: lot.op_id)
    assert any(output.get("is_economic_surplus") for output in lot_a.output_milestones)
    lot_b = replace(
        lot_b, material_release_day=10,
        output_milestones=[{**lot_b.output_milestones[0], "material_release_day": 10}],
    )
    plan = [segment(lot_a, 6, 420, 520, 100)]
    if mixed:  # the last delivery and the surplus in one run
        plan.append(segment(lot_a, 14, 420, 620, 200))
    else:  # the last delivery, then a run of surplus only
        plan += [segment(lot_a, 13, 420, 470, 50), segment(lot_a, 14, 420, 570, 150)]
    plan.append(segment(lot_b, 15, 420, 500, 80))
    return plan, [lot_a, lot_b], data


def test_a_surplus_only_run_belongs_to_no_delivery():
    """Same rule as ``policy._delivery_windows``: making the surplus later
    delays nothing, so a run of surplus only ranks after every delivery and
    blocks released work placed after it (review b3r2 #4). Ranked as A's last
    delivery (due day 20) it hid this inversion."""
    plan, lots, data = _surplus_plan(mixed=False)
    lot_a, lot_b = lots
    holidays = calendar_holidays(data, -7, data.n_days + 7)
    units = _run_units(plan, {lot.id: lot for lot in lots}, holidays)
    surplus_run = units[("M1", plan[2].run_id)]
    assert [unit[3] for unit in surplus_run] == ["surplus"]
    assert surplus_run[0][0] > max(
        unit[0] for key, run in units.items() if key != ("M1", plan[2].run_id) for unit in run
    )
    detail = find_output_priority_anomalies(plan, lots, data)
    assert [
        (item["urgent_lot_id"], item["blocking_lot_id"], item["blocking_output"])
        for item in detail
    ] == [(lot_b.id, lot_a.id, "surplus")]
    assert detail[0]["blocking_rupture_day"] is None
    assert detail[0]["urgent_release_day"] == 10


def test_a_run_making_a_delivery_is_ranked_by_it_not_by_its_surplus():
    plan, lots, data = _surplus_plan(mixed=True)
    lot_a, _lot_b = lots
    holidays = calendar_holidays(data, -7, data.n_days + 7)
    units = _run_units(plan, {lot.id: lot for lot in lots}, holidays)
    assert [unit[3] for unit in units[("M1", plan[1].run_id)]] == [1]
    assert find_output_priority_anomalies(plan, lots, data) == []


# ── B4.4: the most urgent anomalies are classified, the rest stay pending ──


def test_max_classifications_classifies_the_most_urgent_first():
    segments, lots = _interrupted_campaign()
    data, config = _data(), FactoryConfig()
    anomalies = find_output_priority_anomalies(segments, lots, data)
    assert len(anomalies) == 2
    full = classify_priority_order_anomalies(segments, lots, data, config)
    assert classify_priority_order_anomalies(
        segments, lots, data, config, max_classifications=None,
    ) == full
    partial = classify_priority_order_anomalies(
        segments, lots, data, config, max_classifications=1,
    )
    # Same anomalies, same (priority) order; only the first is classified.
    assert [_pair(item) for item in partial] == [_pair(item) for item in anomalies]
    assert partial[0] == full[0]
    assert partial[0]["verification_status"] != "not_evaluated"
    assert partial[1]["verification_status"] == "not_evaluated"
    assert partial[1]["blocking_reasons"] == ["audit_budget"]
    none = classify_priority_order_anomalies(
        segments, lots, data, config, max_classifications=0,
    )
    assert {item["verification_status"] for item in none} == {"not_evaluated"}


def _pair(item):
    return item["urgent_run_id"], item["blocking_run_id"]


def test_over_budget_audit_classifies_the_budget_and_stays_pending():
    segments, lots = _interrupted_campaign()
    data = _data()
    complete = build_operational_audit(segments, lots, data, classification_budget=None)
    audit = build_operational_audit(segments, lots, data, classification_budget=1)

    assert audit["status"] == "not_evaluated"
    assert audit["unevaluated_priority_order_anomalies"] == 1
    detail = audit["priority_order_detail"]
    assert detail[0] == complete["priority_order_detail"][0]
    assert detail[1]["verification_status"] == "not_evaluated"
    # A lower bound of what the complete audit proves, never more.
    assert audit["avoidable_priority_order_anomalies"] <= complete[
        "avoidable_priority_order_anomalies"
    ]
    score = compute_score(segments, lots, data, operational_audit=audit)
    report = build_gate_report(segments, lots, score, data, None, operational_audit=audit)
    assert report["operational_gate_passed"] is False
    assert "operational_sequence_not_evaluated" in report["approval_reasons"]
    assert not gate_passed(report)


def test_pending_pairs_explained_by_protection_are_not_pending():
    """A historical lot is never moved, so its pairs need no classification."""
    segments, lots = _interrupted_campaign()
    data = _data()
    data.preserved_lot_proofs = {"FIRST": "proof"}
    audit = build_operational_audit(segments, lots, data, classification_budget=0)
    assert {item["verification_status"] for item in audit["priority_order_detail"]} == {
        "historical_locked"
    }
    assert audit["status"] == "evaluated"


def test_protected_pairs_are_explained_before_the_budget_is_spent():
    """The budget goes to pairs a recalculation could change (review F6).

    X and Y are blocked by the historical lot P (explained, never moved); Y is
    also blocked by Q. With a budget of one, the only movable pair (Y, Q) is
    classified although two protected pairs are more urgent.
    """
    lots = [
        _lot("P", 12), _lot("X", 8, tool="T2"), _lot("Q", 12, tool="T3"),
        _lot("Y", 9, tool="T4"),
    ]
    segments = [
        _segment("P", 1, 420), _segment("X", 2, 420, tool="T2"),
        _segment("Q", 3, 420, tool="T3"), _segment("Y", 4, 420, tool="T4"),
    ]
    data = _data()
    data.preserved_lot_proofs = {"P": "proof"}
    audit = build_operational_audit(segments, lots, data, classification_budget=1)
    statuses = {
        (item["urgent_lot_id"], item["blocking_lot_id"]): item["verification_status"]
        for item in audit["priority_order_detail"]
    }
    assert statuses.keys() == {("X", "P"), ("Y", "P"), ("Y", "Q")}
    assert statuses[("X", "P")] == statuses[("Y", "P")] == "historical_locked"
    assert statuses[("Y", "Q")] not in {"not_evaluated", "historical_locked"}
    assert audit["status"] == "evaluated"
    # Order of the detail is the anomaly order, protected or not.
    assert [item["urgent_lot_id"] for item in audit["priority_order_detail"]] == ["X", "Y", "Y"]


def test_plans_without_per_delivery_lots_keep_the_lot_anomalies():
    for segments, lots in (_interrupted_campaign(), _clean_plan_with_anomaly()):
        data = _data()
        per_delivery = find_output_priority_anomalies(segments, lots, data)
        assert {item.pop("urgent_output") for item in per_delivery} <= {None}
        assert {item.pop("blocking_output") for item in per_delivery} <= {None}
        assert per_delivery == find_priority_order_anomalies(segments, lots, data)


def _two_delivery_plan(*, b_first: bool):
    """A: 100 pcs due day 13 (R 6) and 50 due day 20 (R 13); B: 80 due day 15
    (R 8). A's second delivery runs after B, as its material allows."""
    from tests.test_output_anticipation import _segment as segment
    from tests.test_output_anticipation import _two_deliveries

    data, lot_a, lot_b = _two_deliveries()
    if b_first:  # B before A's first, more urgent, delivery: a real inversion
        plan = [segment(lot_b, 8, 420, 500, 80), segment(lot_a, 9, 420, 520, 100)]
    else:
        plan = [segment(lot_a, 6, 420, 520, 100), segment(lot_b, 9, 420, 500, 80)]
    plan.append(segment(lot_a, 14, 420, 470, 50))
    return plan, [lot_a, lot_b], data


def test_a_later_delivery_run_is_not_an_urgent_run_blocked():
    plan, lots, data = _two_delivery_plan(b_first=False)
    # Ranked by its whole lot (first delivery, first release), A's second run
    # looked more urgent than B and released before it.
    op = {lot.id: lot.op_id for lot in lots}
    assert [(op[item["urgent_lot_id"]], op[item["blocking_lot_id"]])
            for item in find_priority_order_anomalies(plan, lots, data)] == [("A", "B")]
    assert find_output_priority_anomalies(plan, lots, data) == []
    audit = build_operational_audit(plan, lots, data, classification_budget=0)
    assert audit["priority_order_anomalies"] == 0
    assert audit["status"] == "evaluated"


def test_a_delivery_placed_after_less_urgent_work_is_still_reported():
    plan, lots, data = _two_delivery_plan(b_first=True)
    op = {lot.id: lot.op_id for lot in lots}
    detail = find_output_priority_anomalies(plan, lots, data)
    assert [(op[item["urgent_lot_id"]], item["urgent_output"], op[item["blocking_lot_id"]])
            for item in detail] == [("A", 0, "B")]
    assert detail[0]["urgent_rupture_day"] == 13
    assert detail[0]["urgent_release_day"] == 6


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


def _explained_by_own_deliveries(segments, lots, data):
    """A lot-view pair whose urgent run, ranked by its own deliveries, is not
    more urgent than the blocking run, or is released after it."""
    holidays = calendar_holidays(
        data, min(segment.day_idx for segment in segments) - 7, data.n_days + 7,
    )
    units = _run_units(segments, {lot.id: lot for lot in lots}, holidays)

    def explained(item):
        urgent = units[(item["machine_id"], item["urgent_run_id"])]
        blocking = units[(item["machine_id"], item["blocking_run_id"])]
        return (
            min(unit[0] for unit in urgent)[:5] >= min(unit[0] for unit in blocking)[:5]
            or min(unit[1] for unit in urgent) > min(unit[1] for unit in blocking)
        )

    return explained


def test_rev121_audit_counts_per_delivery_and_is_evaluated(rev121):
    data, config, result = rev121
    segments, lots = result.segments, result.lots
    budget = operational_audit.PRIORITY_CLASSIFICATION_MAX_ANOMALIES

    per_lot = find_priority_order_anomalies(segments, lots, data)
    per_delivery = find_output_priority_anomalies(segments, lots, data)
    # 3139 lot-view anomalies: each is a later delivery run ranked by its
    # lot's first delivery. Per delivery, the only ones left on the stored
    # plan (built before policy v3) are 70 released runs placed after a run
    # of economic surplus only, which belongs to no delivery (review b3r2 #4).
    assert len(per_lot) == 3139
    assert len(per_delivery) == 70
    assert {item["blocking_output"] for item in per_delivery} == {"surplus"}
    assert {item["blocking_rupture_day"] for item in per_delivery} == {None}
    kept = {_pair(item) for item in per_delivery}
    explained = _explained_by_own_deliveries(segments, lots, data)
    assert all(explained(item) for item in per_lot if _pair(item) not in kept)

    started = time.perf_counter()
    audit = build_operational_audit(segments, lots, data, config)
    elapsed = time.perf_counter() - started
    # ~1.8 s on one core with 32 classifications (11/10/2026); margin for a
    # loaded host.
    assert elapsed < 5.0, elapsed
    assert audit["priority_order_anomalies"] == len(per_delivery) > budget
    # Over the work budget: the 32 most urgent are classified by the loop's
    # own contract, the rest stay pending; the plan is "por avaliar".
    assert audit["status"] == "not_evaluated"
    assert audit["unevaluated_priority_order_anomalies"] == len(per_delivery) - budget
    # Rotations the improvement loop would accept: real, avoidable findings.
    assert audit["avoidable_priority_order_anomalies"] == 4
    # Real findings are visible instead of zeros.
    assert audit["released_tool_priority_inversions"] > 0
    assert audit["left_shift_opportunities"] > 0
    # 795 per-lot "interruptions" were per-delivery runs; per run there are none.
    assert audit["lower_priority_campaign_interruptions"] == 0
    cheap = build_operational_audit(segments, lots, data, config, classification_budget=0)
    for key in (
        "left_shift_opportunities",
        "lower_priority_campaign_interruptions",
        "priority_order_anomalies",
        "released_tool_priority_inversions",
    ):
        assert cheap[key] == audit[key], key


def test_rev121_audit_is_identical_on_repeat_and_under_a_slow_classifier(rev121, monkeypatch):
    """Same plan, same answer: no wall-clock dependency anywhere in the status."""
    data, config, result = rev121
    first = build_operational_audit(result.segments, result.lots, data, config)
    real = operational_audit.classify_priority_order_anomalies

    def slow_but_complete(*args, **kwargs):
        time.sleep(1.2)
        return real(*args, **kwargs)

    monkeypatch.setattr(operational_audit, "classify_priority_order_anomalies", slow_but_complete)
    second = build_operational_audit(result.segments, result.lots, data, config)
    assert first == second
    assert first["status"] == "not_evaluated"
    assert first["stop_reason"] == "audit_budget"
