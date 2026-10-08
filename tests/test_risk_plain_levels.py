"""Plain risk levels for planners: status, proven cause and the 7-day window.

Owner decisions (08/10/2026): late (slack < 0), at the limit (slack == 0),
short slack (1-2 days); everything else is ok and never a top risk. A cause is
shown only when the plan analysis proves it. ``risk_level``, ``risk_score`` and
``health_score`` keep their meaning (they feed the surrogate model).
"""

from __future__ import annotations

from backend.risk import compute_risk
from backend.risk.slack_analytics import compute_lot_risks, select_top_risks
from backend.risk.types import LotRisk, risk_status
from tests.test_risk import _engine, _eop, _lot, _seg


def _risk(lot_id: str, edd: int, completion: int, *, score: float = 0.5, binding="none"):
    slack = edd - completion
    return LotRisk(
        lot_id, f"SKU_{lot_id}", "M1", edd, completion, slack, slack * 1020.0,
        score, "critical", binding,
    )


def _fixture():
    """Six lots, one per weekday, with slack -2, 0, 1, 2, 4 and 10 days."""
    ops = [_eop(op_id=f"T{i}_M1_SKU{i}", sku=f"SKU{i}", tool=f"T{i}") for i in range(6)]
    engine = _engine(ops=ops, n_days=5)
    engine.workdays = [f"2026-03-{day:02d}" for day in range(2, 22)]
    engine.n_days = 20
    spec = [(0, 0, 2), (1, 1, 1), (2, 2, 3), (3, 3, 1), (4, 4, 14), (5, 7, 11)]
    lots = [
        _lot(
            lot_id=f"L{i}",
            op_id=f"T{i}_M1_SKU{i}",
            tool=f"T{i}",
            edd=edd,
            prod_min=200.0 + 10 * i,
        )
        for i, _completion, edd in spec
    ]
    segments = [
        _seg(lot_id=f"L{i}", tool=f"T{i}", sku=f"SKU{i}", day=completion)
        for i, completion, _edd in spec
    ]
    return segments, lots, engine


def test_status_thresholds():
    assert risk_status(-1) == "late"
    assert risk_status(0) == "at_limit"
    assert risk_status(1) == "short_slack"
    assert risk_status(2) == "short_slack"
    assert risk_status(3) == "ok"


def test_zero_slack_is_at_limit_not_late():
    engine = _engine()
    risks = compute_lot_risks([_seg(day=2)], [_lot(edd=2)], engine)

    assert risks[0].slack_days == 0
    assert risks[0].status == "at_limit"


def test_risk_level_score_and_health_unchanged_on_fixture():
    """Pinned values from before the plain levels were added."""
    segments, lots, engine = _fixture()
    result = compute_risk(segments, lots, engine)

    by_id = {risk.lot_id: risk for risk in result.lot_risks}
    assert {lot_id: risk.slack_days for lot_id, risk in by_id.items()} == {
        "L0": 2, "L1": 0, "L2": 1, "L3": -2, "L4": 10, "L5": 4,
    }
    assert {lot_id: risk.risk_level for lot_id, risk in by_id.items()} == {
        "L0": "medium", "L1": "critical", "L2": "high",
        "L3": "critical", "L4": "low", "L5": "low",
    }
    assert {lot_id: risk.risk_score for lot_id, risk in by_id.items()} == {
        "L0": 0.0, "L1": 1.0, "L2": 0.0, "L3": 1.0, "L4": 0.0, "L5": 0.0,
    }
    assert result.health_score == 45
    assert result.critical_count == 2
    assert {lot_id: risk.status for lot_id, risk in by_id.items()} == {
        "L0": "short_slack", "L1": "at_limit", "L2": "short_slack",
        "L3": "late", "L4": "ok", "L5": "ok",
    }


def test_crew_or_capacity_never_appear_without_proof():
    segments, lots, engine = _fixture()
    risks = compute_lot_risks(segments, lots, engine)

    assert {risk.binding_constraint for risk in risks} <= {
        "none", "jit_exception", "long_run", "operator", "setup", "calendar",
    }
    for risk in risks:
        assert risk.binding_constraint not in {"crew", "capacity"}
        assert risk.cause not in {"crew", "capacity"}
        if risk.binding_constraint == "none":
            assert risk.cause is None
        else:
            assert risk.cause == risk.binding_constraint


def test_top_risks_never_include_lots_with_room():
    segments, lots, engine = _fixture()
    result = compute_risk(segments, lots, engine)

    assert result.top_risks
    assert all(risk.status != "ok" for risk in result.top_risks)
    assert all(risk.risk_level != "low" for risk in result.top_risks)
    assert {"L4", "L5"}.isdisjoint(risk.lot_id for risk in result.top_risks)


def test_top_risks_order_late_then_limit_then_short_slack():
    risks = [
        _risk("short_early", 1, 0, score=0.9),
        _risk("limit", 3, 3),
        _risk("late", 4, 6),
        _risk("short_late_score", 2, 1, score=0.1),
        _risk("short_high_score", 2, 1, score=0.8),
    ]

    top = select_top_risks(risks, 0, limit=None)

    assert [risk.lot_id for risk in top] == [
        "late", "limit", "short_early", "short_high_score", "short_late_score",
    ]


def test_top_risks_window_is_seven_calendar_days_from_today():
    risks = [
        _risk("due_today", 10, 10),
        _risk("due_last_day", 16, 15),
        _risk("due_after_window", 17, 17),
        _risk("due_yesterday_done", 9, 9),
        _risk("late_still_running", 8, 12),
        _risk("late_finished_before_today", 5, 8),
    ]

    top = select_top_risks(risks, 10, limit=None)

    assert {risk.lot_id for risk in top} == {
        "due_today", "due_last_day", "late_still_running",
    }


def test_top_risks_truncate_after_ranking():
    risks = [_risk(f"short{i}", 2, 1) for i in range(6)] + [_risk("late", 6, 7)]

    top = select_top_risks(risks, 0)

    assert len(top) == 5
    assert top[0].lot_id == "late"


def test_top_risks_exclude_lots_already_produced_before_today():
    """A lot finished before today is history, whatever its status."""
    risks = [
        _risk("short_done_yesterday", 11, 9),
        _risk("limit_done_yesterday", 9, 9),
        _risk("late_done_yesterday", 7, 9),
        _risk("short_finishing_today", 12, 10),
        _risk("limit_finishing_today", 10, 10),
    ]

    top = select_top_risks(risks, 10, limit=None)

    assert [risk.lot_id for risk in top] == ["limit_finishing_today", "short_finishing_today"]


def test_risk_endpoint_applies_todays_window_at_request_time(monkeypatch):
    """/api/data/risk re-selects top_risks with today's index on every request."""
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.api.data import router
    except ImportError:
        import pytest

        pytest.skip("fastapi not installed")

    import backend.risk.plan_identity as plan_identity
    from backend.copilot.state import state
    from backend.risk.types import RiskResult
    from tests.test_console import _schedule

    engine, config, result = _schedule()
    state.engine_data = engine
    state.config = config
    state.update_schedule(result)
    lot_risks = [
        _risk("due_day2", 2, 1),
        _risk("due_day9", 9, 9),
        _risk("ok_far", 30, 5),
    ]
    stale_top = [lot_risks[0]]  # what was selected when computed on day 0
    state.risk_result = RiskResult(
        health_score=50,
        lot_risks=lot_risks,
        machine_risks=[],
        heatmap=[],
        critical_count=2,
        top_risks=stale_top,
        bottleneck="M1",
        surrogate_otd_prob=None,
        surrogate_confidence=None,
        mc_otd_p50=None,
        mc_otd_p80=None,
        mc_otd_p95=None,
        mc_tardy_expected=None,
        mc_runs=None,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    monkeypatch.setattr(plan_identity, "planning_anchor_day", lambda *_args: 0)
    day0 = client.get("/api/data/risk").json()
    monkeypatch.setattr(plan_identity, "planning_anchor_day", lambda *_args: 3)
    day3 = client.get("/api/data/risk").json()

    assert [risk["lot_id"] for risk in day0["top_risks"]] == ["due_day2"]
    assert [risk["lot_id"] for risk in day3["top_risks"]] == ["due_day9"]
    assert day3["top_risks"][0]["status"] == "at_limit"
    assert len(day3["lot_risks"]) == 3
    # The stored result is not mutated by the request.
    assert [risk.lot_id for risk in state.risk_result.top_risks] == ["due_day2"]
