"""Close-out of the quantity builder on the frozen path (plan of 10/10, B1a).

A frozen recalculation keeps the protected lots outside the plan segments and
records them in ``data.protected_mounting_segments``. The close-out that drops
redundant retained-tool setups must treat that work as physical evidence: a
protected job of another tool between two runs of a tool is a tool change,
so the second run keeps its setup.
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

import pytest

from backend.scheduler.scheduler import _remove_redundant_retained_tool_setups
from backend.scheduler.types import Segment

REV121 = Path(__file__).parent / "fixtures" / "private" / "rev121.json.gz"


def _segment(lot, run, tool, start, end, *, setup=0.0, qty=10, prod=None):
    return Segment(
        lot_id=lot, run_id=run, machine_id="M1", tool_id=tool, day_idx=1,
        start_min=start, end_min=end, shift="A", qty=qty,
        prod_min=float(end - start - setup) if prod is None else prod,
        setup_min=float(setup), sku=lot, run_setup_min=float(setup),
    )


def _two_runs_of_one_tool():
    return [
        _segment("A", "run-1", "TA", 420, 540, setup=60),
        _segment("A", "run-2", "TA", 700, 820, setup=60),
    ]


def test_closeout_removes_a_setup_when_the_tool_is_still_mounted():
    segments = _two_runs_of_one_tool()
    _remove_redundant_retained_tool_setups(segments)
    assert [segment.setup_min for segment in segments] == [60.0, 0.0]


def test_closeout_keeps_the_setup_after_a_protected_job_of_another_tool():
    segments = _two_runs_of_one_tool()
    protected = [_segment("B", "frozen", "TB", 560, 660, setup=0)]
    _remove_redundant_retained_tool_setups(segments, fixed_segments=protected)
    assert [segment.setup_min for segment in segments] == [60.0, 60.0]
    # The protected evidence is never changed.
    assert (protected[0].start_min, protected[0].setup_min) == (560, 0.0)


def test_closeout_ignores_protected_work_on_another_machine():
    segments = _two_runs_of_one_tool()
    elsewhere = _segment("B", "frozen", "TB", 560, 660)
    elsewhere.machine_id = "M2"
    _remove_redundant_retained_tool_setups(segments, fixed_segments=[elsewhere])
    assert [segment.setup_min for segment in segments] == [60.0, 0.0]


@pytest.fixture(scope="module")
def rev121():
    if not REV121.exists():
        pytest.skip("private fixture rev121.json.gz absent")
    from backend.plans.serialize import deserialize_snapshot

    payload = json.loads(gzip.decompress(REV121.read_bytes()).decode("utf-8"))
    restored = deserialize_snapshot(payload)
    return restored["engine_data"], restored["config"], restored["result"]


@pytest.mark.parametrize("freeze_day", [1, 3])
def test_rev121_frozen_recalculation_keeps_tool_changes_after_protected_jobs(
    rev121, monkeypatch, freeze_day,
):
    """Regression: BFP080 re-entered PRM019 after a protected VUL038 job with
    0 of 75 setup minutes, and "Recalcular" failed (freeze day 1 and 3)."""

    import backend.plans.frozen as frozen
    import backend.scheduler.scheduler as scheduler_module
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.validation import validate_plan

    data, config, stored = rev121
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_a, **_k: freeze_day)
    evidence: list[int] = []
    closeout = scheduler_module._remove_redundant_retained_tool_setups

    def spy(segments, **kwargs):
        evidence.append(len(kwargs.get("fixed_segments") or ()))
        return closeout(segments, **kwargs)

    monkeypatch.setattr(scheduler_module, "_remove_redundant_retained_tool_setups", spy)
    result = frozen.optimize_preserving_started_lots(
        copy.deepcopy(data), copy.deepcopy(config), copy.deepcopy(stored), mode="quick",
    )
    assert result.segments
    # The quantity close-out ran with the protected mountings as evidence.
    assert evidence and evidence[0] > 0
    view = result_validation_data(copy.deepcopy(data), result)
    assert not [
        violation for violation in validate_plan(result.segments, view, config, lots=result.lots)
        if violation["kind"] == "missing_tool_change_setup"
    ]


def test_a_rejected_closeout_keeps_the_builder_plan(monkeypatch):
    """The close-out is an optional clean-up: if its result does not validate,
    the builder's valid plan is kept instead of failing the recalculation."""

    import backend.scheduler.scheduler as scheduler_module
    from backend.scheduler.scheduler import schedule_all
    from backend.scheduler.validation import validate_plan
    from tests.test_quantity_campaigns import _config, _data, _op

    data = _data([
        _op("A", "TA", {13: 1000, 14: 60}, eco_lot=1060),
        _op("B", "TB", {13: 100}),
    ])
    config = _config()
    reference = schedule_all(copy.deepcopy(data), config=config)

    def broken(segments, **_kwargs):
        for segment in segments:
            segment.setup_min = 0.0  # drops every tool change: invalid
        return segments

    monkeypatch.setattr(scheduler_module, "_remove_redundant_retained_tool_setups", broken)
    result = schedule_all(copy.deepcopy(data), config=config)
    assert not validate_plan(result.segments, data, config, lots=result.lots)
    assert [
        (s.lot_id, s.day_idx, s.start_min, s.end_min, s.setup_min) for s in result.segments
    ] == [
        (s.lot_id, s.day_idx, s.start_min, s.end_min, s.setup_min) for s in reference.segments
    ]
    # The planner is told with the plan, in plain Portuguese, not only in a log.
    # First, so the API's first-ten cut never hides it.
    assert result.warnings[0] == scheduler_module.CLOSEOUT_REJECTED_WARNING
    assert scheduler_module.CLOSEOUT_REJECTED_WARNING not in reference.warnings
