"""Robustness is informational only (owner decision, 07/10/2026).

It never ranks or selects a plan, never asks for approval, never enters the
learning reward and is never computed inside planning (AGENTS.md §1 order:
physics > no per-order delivery loss > anticipation > setups/transfers).
"""

from __future__ import annotations

import pytest

from backend.config.types import FactoryConfig
from backend.cpo.optimizer import _is_better_candidate, optimize
from backend.learning.reward import compute_reward
from backend.scheduler.gates import build_gate_report
from tests.test_cpo import _make_engine_data, _make_eop, _tiny_result

_CLEAN = {
    "otd": 100.0,
    "otd_d": 100.0,
    "tardy_count": 0,
    "otd_d_failures": 0,
    "hard_violations": 0,
    "setups": 1,
    "setup_time_min": 30.0,
    "earliness_avg_days": 1.0,
    "planning_penalty": 0.0,
}
_FAILED = {
    "robustness_evaluated_samples": 100,
    "robustness_success_probability_pct": 40.0,
    "robustness_threshold_pct": 95.0,
    "robustness_gate_passed": False,
}
_PASSED = {
    "robustness_evaluated_samples": 100,
    "robustness_success_probability_pct": 100.0,
    "robustness_threshold_pct": 95.0,
    "robustness_gate_passed": True,
}
_NOT_EVALUATED = {"robustness_evaluated_samples": 0}


@pytest.mark.parametrize("robustness", [_FAILED, _NOT_EVALUATED, {}])
def test_earlier_plan_wins_whatever_robustness_says(robustness):
    earlier = _tiny_result(score={
        **_CLEAN, **robustness,
        "latest_start_gap_avg_min": 480.0, "start_anticipation_avg_workdays": 2.0,
    })
    later = _tiny_result(score={
        **_CLEAN, **_PASSED,
        "latest_start_gap_avg_min": 60.0, "start_anticipation_avg_workdays": 1.0,
    })

    assert _is_better_candidate(earlier, later)
    assert not _is_better_candidate(later, earlier)


def test_fewer_setups_win_over_higher_robustness():
    fewer_setups = _tiny_result(score={**_CLEAN, **_FAILED})
    more_robust = _tiny_result(score={
        **_CLEAN, **_PASSED, "setups": 3, "setup_time_min": 90.0,
    })

    assert _is_better_candidate(fewer_setups, more_robust)
    assert not _is_better_candidate(more_robust, fewer_setups)


@pytest.mark.parametrize("mode", ["quick", "normal"])
def test_optimize_never_runs_the_robustness_battery(monkeypatch, mode):
    def battery(*_args, **_kwargs):
        raise AssertionError("robustness runs only in the background after commit")

    monkeypatch.setattr("backend.risk.robustness.run_robustness_battery", battery)
    data = _make_engine_data(ops=[_make_eop(d=[0, 0, 100, 0, 0])], n_days=5)

    result = optimize(data, mode=mode, seed=42)

    assert result.gate_report["physical_gate_passed"]
    assert not any(key.startswith("robustness_") for key in result.score)
    trace = result.gate_report.get("solver_trace") or {}
    assert trace.get("final_source") != "baseline_after_robustness_timeout"


@pytest.fixture(scope="module")
def clean_plan():
    data = _make_engine_data(ops=[_make_eop(d=[0, 0, 100, 0, 0])], n_days=5)
    config = FactoryConfig()
    result = optimize(data, mode="quick", config=config, seed=42)
    report = build_gate_report(result.segments, result.lots, result.score, data, config)
    assert report["apply_decision"] == "auto_applicable", report["approval_reasons"]
    return data, config, result


@pytest.mark.parametrize("robustness", [_NOT_EVALUATED, _FAILED])
def test_clean_plan_applies_without_robustness_approval(clean_plan, robustness):
    data, config, result = clean_plan

    report = build_gate_report(
        result.segments, result.lots, {**result.score, **robustness}, data, config,
    )

    assert report["apply_decision"] == "auto_applicable"
    assert report["requires_approval"] is False
    assert not any(reason.startswith("robustness") for reason in report["approval_reasons"])
    assert report["robustness_gate_passed"] is None


@pytest.mark.parametrize("robustness", [_FAILED, _PASSED, _NOT_EVALUATED, {}])
def test_reward_prefers_on_time_plan_regardless_of_robustness(robustness):
    on_time = {**_CLEAN, **robustness}
    late = {**_CLEAN, **_PASSED, "otd": 99.0, "tardy_count": 1, "otd_d_failures": 1}

    assert compute_reward(on_time) > compute_reward(late)
    assert compute_reward(on_time) == compute_reward(_CLEAN)
