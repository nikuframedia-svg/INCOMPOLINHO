"""Normal mode skips the advisory search on real-size instances (08/10/2026).

On real ISOPs one alternative costs a full construction and none finished in
the advisory slice (0 of 47 at 60 s, none accepted at 180 s), so the search and
CP-SAT polish only took time from the no-loss improvement cycle. The gate is by
instance size, never by elapsed time, so the branch does not depend on load.
"""

from __future__ import annotations

import pytest

import backend.cpo.optimizer as optimizer
from backend.config.types import FactoryConfig
from backend.cpo.optimizer import MODE_CONFIG, optimize
from tests.test_cpo import _make_engine_data, _make_eop


def _data(n_ops: int):
    return _make_engine_data(ops=[
        _make_eop(sku=f"SKU_{i}", tool=f"T{i}", d=[0] * 10 + [200] + [0] * 69)
        for i in range(n_ops)
    ])


def _forbid_search(monkeypatch):
    def search(*_args, **_kwargs):
        pytest.fail("advisory search must be skipped on a real-size instance")

    monkeypatch.setattr(optimizer, "_improve_baseline", search)
    monkeypatch.setattr("backend.cpo.cpsat_polish.cpsat_polish", search, raising=False)


def test_only_normal_mode_has_the_size_gate():
    assert MODE_CONFIG["normal"]["advisory_search_max_ops"] == 50
    for mode in ("quick", "deep", "max"):
        assert "advisory_search_max_ops" not in MODE_CONFIG[mode]


def test_normal_large_instance_skips_search_but_still_improves(monkeypatch):
    monkeypatch.setitem(MODE_CONFIG["normal"], "advisory_search_max_ops", 3)
    _forbid_search(monkeypatch)
    improved = []
    real_improve = optimizer._apply_improvement_phase
    monkeypatch.setattr(optimizer, "_apply_improvement_phase", lambda *a, **k: (
        improved.append(True), real_improve(*a, **k),
    ))

    result = optimize(_data(3), mode="normal", config=FactoryConfig())

    trace = result.gate_report["solver_trace"]
    assert improved == [True]
    assert result.gate_report["physical_gate_passed"] is True
    assert not any("Tempo de melhoria esgotado" in w for w in result.warnings)
    assert trace["final_source"] == "baseline_search_skipped"
    assert trace["candidate_search"]["status"] == "skipped"
    assert trace["candidate_search"]["ops"] == 3


def test_normal_small_instance_still_searches(monkeypatch):
    monkeypatch.setitem(MODE_CONFIG["normal"], "advisory_search_max_ops", 4)
    calls = []
    real = optimizer._improve_baseline
    monkeypatch.setattr(optimizer, "_improve_baseline", lambda *a, **k: (
        calls.append(True) or real(*a, **k)
    ))

    optimize(_data(3), mode="normal", config=FactoryConfig())

    assert calls == [True]


class _SearchEntered(Exception):
    pass


@pytest.mark.parametrize("mode", ["deep", "max"])
def test_deep_and_max_keep_the_search(monkeypatch, mode):
    def search(*_args, **_kwargs):
        raise _SearchEntered

    # Even with the normal-mode gate tripping on this size, deep/max search.
    monkeypatch.setitem(MODE_CONFIG["normal"], "advisory_search_max_ops", 1)
    monkeypatch.setattr(optimizer, "_improve_baseline", search)

    with pytest.raises(_SearchEntered):
        optimize(_data(3), mode=mode, config=FactoryConfig())


def test_quick_mode_is_unchanged(monkeypatch):
    before = optimize(_data(3), mode="quick", config=FactoryConfig())
    monkeypatch.setitem(MODE_CONFIG["normal"], "advisory_search_max_ops", 1)
    _forbid_search(monkeypatch)

    quick = optimize(_data(3), mode="quick", config=FactoryConfig())

    assert quick.segments and quick.segments == before.segments
    assert quick.improvement_report["stop_reason"] == "quick_mode"


def test_skipped_search_reports_strict_feasibility(monkeypatch):
    monkeypatch.setitem(MODE_CONFIG["normal"], "advisory_search_max_ops", 1)
    _forbid_search(monkeypatch)

    result = optimize(_data(3), mode="normal", config=FactoryConfig())

    assert result.solver_status in {"strict_feasible", "strict_infeasible_best_effort"}
    assert result.gate_report["solver_status"] == result.solver_status


def test_frozen_recalculation_skips_search_and_improves_once(monkeypatch):
    from backend.plans import frozen

    data = _data(3)
    baseline = optimize(data, mode="quick", config=FactoryConfig())
    monkeypatch.setitem(MODE_CONFIG["normal"], "advisory_search_max_ops", 1)
    _forbid_search(monkeypatch)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 0)
    improved = []
    real = frozen.improve_preserving_protected_lots
    monkeypatch.setattr(frozen, "improve_preserving_protected_lots", lambda *a, **k: (
        improved.append(True) or real(*a, **k)
    ))

    result = frozen.optimize_preserving_started_lots(data, FactoryConfig(), baseline, mode="normal")

    assert improved == [True]
    assert result.gate_report["physical_gate_passed"] is True
    assert result.gate_report["solver_trace"]["final_source"] == "baseline_search_skipped"
    assert not any("Tempo de melhoria esgotado" in w for w in result.warnings)
