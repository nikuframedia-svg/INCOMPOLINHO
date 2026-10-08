"""A solver timeout must not fall back to a horizon-truncated production."""

import copy

import pytest

from backend.scheduler import global_jit
from backend.scheduler.validation import assert_plan_valid
from tests.test_global_jit import _config, _engine, _op, _run
from tests.test_scheduler import TestToolContention as _ToolContention


@pytest.mark.parametrize("status", [global_jit.cp_model.UNKNOWN, global_jit.cp_model.INFEASIBLE])
def test_complete_fallback_without_resource_stops_preserves_demand_and_solver_evidence(
    monkeypatch, status
):
    config = _config("M1")
    config.oee_default = 1.0
    data = _engine([_op("OP1", "M1", "T1", demand=[3000])], ["M1"], n_days=1)
    run = _run("OP1", "M1", "T1", qty=3000, prod_min=1800, internal_deadline=0, delivery_day=0)
    before = copy.deepcopy((data, config, run))
    monkeypatch.setattr(global_jit, "_solve", lambda *_args, **_kwargs: (None, status))
    result = global_jit.solve_global_jit([run], data, config, time_limit_s=0.4)
    assert result.candidate_found
    assert sum(segment.qty for segment in result.segments) == 3000
    assert max(segment.day_idx for segment in result.segments) >= data.n_days
    assert_plan_valid(result.segments, data, config, lots=result.lots)
    assert result.feasibility["strict_solver_status"] == global_jit._status_name(status)
    expected = (
        "timeout_with_candidate"
        if status == global_jit.cp_model.UNKNOWN
        else "strict_infeasible_best_effort"
    )
    assert result.solver_status == expected
    if status == global_jit.cp_model.UNKNOWN:
        assert not any("nao cabem" in warning for warning in result.warnings)
    assert (data, config, run) == before


def test_five_machine_shared_tool_plan_stays_complete_after_solver_timeout(monkeypatch):
    monkeypatch.setattr(
        global_jit, "_solve", lambda *_args, **_kwargs: (None, global_jit.cp_model.UNKNOWN)
    )
    _ToolContention().test_full_factory_no_tool_on_two_machines()
