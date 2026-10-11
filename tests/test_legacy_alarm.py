"""Alarm on the legacy engine (plan of 11/10/2026, Passo 1d).

Every entry into the legacy planner logs ``motor antigo usado: <site>`` on
the ``backend.legacy`` logger. It is Python logging only, never the plan
journal or ``ScheduleResult.warnings``, so plans are unchanged. Deleting the
legacy engine (Passo 6) needs zero such warnings over seven days of real use;
these tests prove each site raises the alarm and that the per-delivery path,
the one real ISOPs take, raises none.
"""

from __future__ import annotations

import copy
import logging
from datetime import date, timedelta

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.cpo import optimizer
from backend.cpo.optimizer import optimize
from backend.plans import manual_move
from backend.plans.manual_move import ManualMoveError, move_lot
from backend.scheduler.global_jit import solve_global_jit
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.quantity_dispatch import has_quantity_releases
from backend.scheduler.scheduler import schedule_all
from backend.types import EngineData, EOp, MachineInfo

LEGACY = "backend.legacy"
N_DAYS = 30


def _op(op_id, tool, demand_by_day, *, eco_lot=0):
    demand = [0] * N_DAYS
    for day, qty in demand_by_day.items():
        demand[day] = qty
    return EOp(
        id=op_id, sku=op_id, client="CLIENT", designation=op_id, m="M1", t=tool,
        pH=60, sH=1.0, operators=1, eco_lot=eco_lot, alt=None, stk=0, backlog=0,
        d=demand, oee=1.0, wip=0,
    )


def _data(ops):
    # Day 0 = Wednesday 07/10/2026; weekends are holidays.
    days = [(date(2026, 10, 7) + timedelta(days=i)).isoformat() for i in range(N_DAYS)]
    return EngineData(
        ops=list(ops),
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[],
        client_demands={},
        workdays=days,
        n_days=N_DAYS,
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )


def _config():
    return FactoryConfig(machines={"M1": MachineConfig(id="M1", group="Grandes")})


def legacy_case():
    """One delivery per lot: no material released by quantity."""
    data = _data([_op("A", "TA", {13: 100}), _op("B", "TB", {14: 80})])
    assert not has_quantity_releases(create_lots(data, _config()))
    return data


def per_delivery_case():
    """A lot whose deliveries release material on different days (AGENTS §2)."""
    data = _data([_op("A", "TA", {13: 100, 20: 50}, eco_lot=150), _op("B", "TB", {14: 80})])
    assert has_quantity_releases(create_lots(data, _config()))
    return data


@pytest.fixture
def alarms(caplog):
    caplog.set_level(logging.WARNING, logger=LEGACY)

    def sites():
        records = [record for record in caplog.records if record.name == LEGACY]
        assert all(record.levelno == logging.WARNING for record in records)
        assert all(record.msg == "motor antigo usado: %s" for record in records)
        return [record.args[0] for record in records]

    sites.clear = caplog.clear
    return sites


@pytest.fixture(autouse=True)
def planning_day(monkeypatch):
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_a, **_k: 0)


def _no_alarm_in_outputs(result):
    text = repr((result.warnings, result.journal))
    assert "motor antigo" not in text


# ── each legacy site raises the alarm ────────────────────────────────────


def test_schedule_all_legacy_branch_raises_the_alarm(alarms):
    result = schedule_all(legacy_case(), config=_config())
    assert result.segments
    assert "scheduler.schedule_all" in alarms()
    _no_alarm_in_outputs(result)


def test_solve_global_jit_entry_raises_the_alarm(alarms):
    assert solve_global_jit([], legacy_case(), _config()) is None
    assert alarms() == ["global_jit.solve_global_jit"]


def test_manual_reallocation_without_quantity_releases_raises_the_alarm(alarms):
    data = legacy_case()
    result = manual_move._allocate_existing_lots(
        data, source_lots=create_lots(data, _config()), config=_config(), time_budget_s=10.0,
    )
    assert result is not None and result.segments
    assert alarms()[:2] == [
        "manual_move._allocate_existing_lots", "global_jit.solve_global_jit",
    ]


def _forced_reallocation(data, monkeypatch, alarms):
    """A move whose fixed-position attempt fails, so the whole-plan
    reallocation branch decides; every planner behind it is stubbed."""
    config = _config()
    baseline = schedule_all(copy.deepcopy(data), config=config)
    alarms.clear()

    def no_fixed_positions(*_args, **_kwargs):
        raise ManualMoveError("forced by the test")

    reallocated = []
    monkeypatch.setattr(manual_move, "_fixed_positions_move", no_fixed_positions)
    monkeypatch.setattr(
        manual_move, "_allocate_existing_lots", lambda *a, **k: reallocated.append(1),
    )
    monkeypatch.setattr(manual_move, "_replan_around_fixed_lot", lambda *a, **k: None)
    lot = next(lot for lot in baseline.lots if lot.op_id == "B")
    day = min(s.day_idx for s in baseline.segments if s.lot_id == lot.id)
    with pytest.raises(ManualMoveError):
        move_lot(baseline.segments, baseline.lots, baseline.score, data, config,
                 lot_id=lot.id, target_day=day)
    return reallocated


def test_manual_move_reallocation_branch_raises_the_alarm(monkeypatch, alarms):
    assert _forced_reallocation(legacy_case(), monkeypatch, alarms) == [1]
    assert alarms() == ["manual_move._move_lot"]


def test_improve_baseline_raises_the_alarm(monkeypatch, alarms):
    # Small instances in normal mode still run the legacy candidate search;
    # its search and polish are switched off here, the entry still runs.
    monkeypatch.setitem(optimizer.MODE_CONFIG["normal"], "candidate_search", False)
    monkeypatch.setitem(optimizer.MODE_CONFIG["normal"], "cp_sat", False)
    result = optimize(per_delivery_case(), mode="normal", config=_config(), improve=False)
    assert alarms() == ["optimizer._improve_baseline"]
    _no_alarm_in_outputs(result)


def test_smart_schedule_raises_the_alarm(tmp_path, alarms):
    from backend.learning import smart_schedule

    result = smart_schedule(
        per_delivery_case(), store_path=str(tmp_path / "learning.db"), config=_config(),
    )
    assert alarms() == ["learning.smart_schedule"]
    _no_alarm_in_outputs(result)


# ── the per-delivery path raises none ────────────────────────────────────


def test_per_delivery_schedule_and_quick_optimize_raise_no_alarm(alarms):
    data = per_delivery_case()
    result = schedule_all(copy.deepcopy(data), config=_config())
    assert result.segments
    assert optimize(copy.deepcopy(data), mode="quick", config=_config()).segments
    assert alarms() == []


def test_per_delivery_normal_run_raises_no_alarm(monkeypatch, alarms):
    # Real ISOPs have 50 or more operations, so normal mode skips the legacy
    # candidate search (``advisory_search_max_ops``); this small instance is
    # given the same size gate.
    monkeypatch.setitem(optimizer.MODE_CONFIG["normal"], "advisory_search_max_ops", 1)
    result = optimize(per_delivery_case(), mode="normal", config=_config())
    assert result.segments
    assert result.improvement_report
    assert alarms() == []


def test_per_delivery_manual_reallocation_raises_no_alarm(monkeypatch, alarms):
    data = per_delivery_case()
    assert manual_move._allocate_existing_lots(
        data, source_lots=create_lots(data, _config()), config=_config(), time_budget_s=10.0,
    ).segments
    assert _forced_reallocation(data, monkeypatch, alarms) == []
    assert alarms() == []


@pytest.mark.needs_private
@pytest.mark.slow
def test_real_plan_normal_run_raises_no_alarm(alarms):
    """Revision 124 (11/10/2026): normal mode on the real ISOP, then a few
    evaluations of the improvement cycle (bounded by count, not time)."""
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.improvement import improve_plan
    from tests.snapshot_fixture import load_snapshot

    snapshot = load_snapshot("rev124")
    result = optimize(
        copy.deepcopy(snapshot.data), mode="normal", config=copy.deepcopy(snapshot.config),
        improve=False,
    )
    assert result.segments
    assert result.gate_report["solver_trace"]["final_source"] == "baseline_search_skipped"
    view = result_validation_data(copy.deepcopy(snapshot.data), result)
    _segments, _lots, report = improve_plan(
        result.segments, result.lots, view, snapshot.config, max_evaluations=3,
    )
    assert report["candidates_evaluated"] >= 1
    assert alarms() == []
