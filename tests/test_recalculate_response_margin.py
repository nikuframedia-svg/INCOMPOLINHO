"""«Recalcular plano» answers with a margin before the writer's 60 s deadline.

Measured 11/10/2026 on revisions 123/124 (1 core): ~53 s before, ~44 s after,
with plans at least as good under the canonical comparator.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import time

import pytest

from backend.planning_control import (
    CLOSING_WORK_S,
    closing_reserve,
    improvement_time_budget,
    planning_scope,
    response_margin,
    response_margin_active,
)
from backend.scheduler import improvement as improvement_module
from backend.scheduler.improvement import (
    Generator,
    Proposal,
    _exact_plan_key,
    _plain_copy,
    _working_copy,
    improve_plan,
)
from tests.test_improvement_cycle import _moved, plan  # noqa: F401  (fixture)


def test_closing_reserve_grows_only_inside_a_response_margin():
    assert closing_reserve(60.0) == 10.0
    assert not response_margin_active()
    with response_margin(15.0):
        assert response_margin_active()
        assert closing_reserve(60.0) == 15.0 + CLOSING_WORK_S
        # Never more than the budget itself.
        assert closing_reserve(5.0) == 5.0
    assert closing_reserve(60.0) == 10.0
    assert not response_margin_active()


def test_improvement_budget_leaves_the_margin_and_the_closing_work():
    with planning_scope(timeout_s=60.0):
        plain = improvement_time_budget(60.0)
        with response_margin(15.0):
            margin = improvement_time_budget(60.0)
    assert 49.0 < plain <= 50.0
    assert plain - margin == pytest.approx(15.0 + CLOSING_WORK_S - 10.0, abs=0.2)


def test_recalculate_runs_inside_the_response_margin(monkeypatch):
    from backend.api import data as data_api
    from backend.copilot.state import CopilotState

    target = CopilotState(engine_data=object(), plan_revision=7)
    monkeypatch.setattr(data_api, "state", target)
    seen = {}

    def recompute(_config, _body):
        seen["active"] = response_margin_active()
        seen["reserve"] = closing_reserve(60.0)

    monkeypatch.setattr(data_api, "_recompute_transactional", recompute)
    response = asyncio.run(data_api.recalculate.__wrapped__({"expected_revision": 7}))

    assert response["status"] == "ok"
    assert seen == {
        "active": True,
        "reserve": data_api.RECALCULATE_RESPONSE_MARGIN_S + CLOSING_WORK_S,
    }
    assert not response_margin_active()


def _clocked_search(plan, monkeypatch, clock):  # noqa: F811
    segments, lots, data, config = plan
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    compacted = []

    def compact(segs, candidate_lots):
        compacted.append(next(s.day_idx for s in segs if s.lot_id == "LB"))
        return Proposal(segs, candidate_lots)

    def earlier(segs, candidate_lots):
        clock["now"] += 4.0
        lb = next(s for s in segs if s.lot_id == "LB")
        return Proposal(_moved(segs, "LB", day_idx=lb.day_idx - 1, start_min=510, end_min=600),
                        candidate_lots)

    shifted = _moved(segments, "LB", day_idx=6)
    _, _, report = improve_plan(
        shifted, lots, data, config,
        generators=[Generator("compact", compact), Generator("earlier", earlier)],
        time_budget_s=20.0,
    )
    return report, compacted


def test_interactive_answer_gives_the_whole_phase_to_the_search(plan, monkeypatch):  # noqa: F811
    """No compaction pass inside a response margin: it never gained on the
    real plans measured and its reserve no longer fitted the shorter phase."""

    monkeypatch.setattr(improvement_module, "CLOSING_COMPACTION_SHARE", 0.5)
    report, compacted = _clocked_search(plan, monkeypatch, {"now": 0.0})
    assert compacted == [4]
    assert report["closing_compaction"] == "not_run"
    outside = report["accepted_by_scope"]["earlier"]

    with response_margin(15.0):
        report, compacted = _clocked_search(plan, monkeypatch, {"now": 0.0})
    assert compacted == []
    assert report["compactions"] == 0
    assert report["closing_compaction"] == "skipped"
    assert report["stop_reason"] == "budget"
    assert report["accepted_by_scope"]["earlier"] >= outside


def test_plain_copy_matches_deepcopy_and_keeps_shared_references(plan):  # noqa: F811
    segments, lots, _data, _config = plan
    shared = [{"qty": 1, "nested": [1, 2]}]
    value = {"lots": copy.deepcopy(lots), "a": shared, "b": shared}

    copied = _plain_copy(value)

    assert copied == copy.deepcopy(value)
    assert copied["a"] is copied["b"]
    assert copied["a"] is not shared
    assert _plain_copy(lambda: None) is not None  # falls back to deepcopy


def test_working_copy_is_independent_of_the_current_plan(plan):  # noqa: F811
    segments, lots, _data, _config = plan
    segments = [dataclasses.replace(s, output_milestones=[{"qty": 5}]) for s in segments]
    current = type("Evaluated", (), {"segments": segments, "lots": lots})()

    copies, copied_lots = _working_copy(current)
    copies[0].output_milestones[0]["qty"] = 9
    copied_lots[0].qty = 1

    assert copies[0].output_milestones == [{"qty": 9}]
    assert segments[0].output_milestones == [{"qty": 5}]
    assert lots[0].qty == 100


def test_exact_plan_key_separates_different_plans(plan):  # noqa: F811
    segments, lots, _data, _config = plan
    same = _exact_plan_key(copy.deepcopy(segments), copy.deepcopy(lots))
    assert _exact_plan_key(segments, lots) == same
    moved = _moved(segments, "LB", run_id="other")
    assert _exact_plan_key(moved, lots) != same
