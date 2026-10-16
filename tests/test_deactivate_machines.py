"""Deactivating a machine always works (decisão do Luís, 16/10/2026).

- The work of a deactivated machine moves to the other allowed active machine
  (primary or alternative), the rest of lots already started there included;
  what was already produced stays as history.
- Changing or removing a tool's alternative follows the same rule.
- An operation with no allowed active machine is unmet demand: left out of
  the plan (late on Entregas, never a physical violation) with the notice
  «Sem máquina ativa: …».
- A planning refusal in a replan job shows its own pt-PT text, never «erro
  interno».

Real case (16/10/2026, revision 164): MAE054, MAS191 and PRM042 deactivated
plus BFP080 without its alternative PRM039 failed with «Ocorreu um erro
interno» (``quantity_dispatch`` could not place a lot on MAE054) and, alone,
the alternative removal was refused because today's production on PRM039 was
judged by the new eligibility.
"""

from __future__ import annotations

import copy
import time
from datetime import datetime, timezone

import pytest

from backend.api.replan import _apply_change, _sync_active_machines
from backend.config.loader import validate_config
from backend.config.planning import (
    NO_ACTIVE_MACHINE_PREFIX,
    apply_effective_planning_config,
    no_active_machine_notice,
)
from backend.config.types import FactoryConfig, MachineConfig
from backend.cpo import optimize
from backend.plans import frozen
from backend.scheduler.validation import validate_plan
from backend.types import EngineData, EOp, MachineInfo

WORKDAYS = [
    "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21",
    "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28",
]
# 10:00 in Lisbon on day 1 (16/10): the morning of day 1 already ran.
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)


def _op(op_id, machine, tool, alt=None, *, qty=3000, day=5):
    return EOp(
        id=op_id, sku=f"SKU_{op_id}", client="C", designation=op_id, m=machine, t=tool,
        pH=100, sH=0.5, operators=1, eco_lot=0, alt=alt, stk=0, backlog=0,
        d=[qty if index == day else 0 for index in range(len(WORKDAYS))], oee=1.0, wip=0,
    )


def _scenario(ops, tools):
    machines = sorted({machine for op in ops for machine in (op.m, op.alt) if machine})
    config = FactoryConfig(machines={m: MachineConfig(m, "Grandes") for m in machines})
    config.tools = tools
    data = EngineData(
        ops=ops, machines=[MachineInfo(m, "Grandes", 1020) for m in machines],
        twin_groups=[], client_demands={}, workdays=list(WORKDAYS), n_days=len(WORKDAYS),
        holidays=[],
    )
    apply_effective_planning_config(data, config)
    baseline = optimize(copy.deepcopy(data), mode="quick", config=config)
    assert validate_plan(baseline.segments, data, config, lots=baseline.lots) == []
    return data, config, baseline


def _replan(data, config, baseline, updates):
    """What ``start_replan`` does with ``config_updates``, then the calculation."""
    config, data = copy.deepcopy(config), copy.deepcopy(data)
    for key, value in updates.items():
        _apply_change(key, value, config, data, config.day_capacity_min)
    apply_effective_planning_config(data, config)
    assert validate_config(config, data) == []
    warnings = _sync_active_machines(config, data)
    result = frozen.optimize_preserving_started_lots(
        data, config, copy.deepcopy(baseline), mode="quick", now=NOW,
    )
    return data, config, result, warnings


def _valid(result, data, config):
    from backend.scheduler.canonical import result_validation_data

    view = result_validation_data(data, result)
    return validate_plan(result.segments, view, config, lots=result.lots)


def _produced(result, op_id):
    lots = {lot.id: lot.op_id for lot in result.lots}
    return sum(int(s.qty) for s in result.segments if lots.get(s.lot_id) == op_id)


def _lot_op(result, lot_id):
    return next(lot.op_id for lot in result.lots if lot.id == lot_id)


# ── Synthetic ────────────────────────────────────────────────────────────────


def test_deactivated_machine_with_alternative_moves_its_work():
    data, config, baseline = _scenario(
        [_op("A", "M1", "T1", "M2", day=8)],
        {"T1": {"primary": "M1", "alt": "M2", "setup_hours": 0.5}},
    )
    assert {s.machine_id for s in baseline.segments} == {"M1"}
    data, config, result, warnings = _replan(
        data, config, baseline, {"machine_active": {"M1": False}},
    )
    assert _valid(result, data, config) == []
    assert {s.machine_id for s in result.segments} == {"M2"}
    assert _produced(result, "A") == 3000
    assert not any(w.startswith(NO_ACTIVE_MACHINE_PREFIX) for w in warnings)


def test_deactivated_machine_without_alternative_is_unmet_demand_not_an_error():
    data, config, baseline = _scenario(
        [_op("A", "M1", "T1", day=8), _op("B", "M2", "T2", day=8)],
        {"T1": {"primary": "M1"}, "T2": {"primary": "M2"}},
    )
    data, config, result, warnings = _replan(
        data, config, baseline, {"machine_active": {"M1": False}},
    )
    notice = (
        "Sem máquina ativa: SKU_A — ative uma máquina ou defina uma alternativa."
    )
    assert warnings == [notice]
    assert no_active_machine_notice(data, config) == notice
    assert _valid(result, data, config) == []
    assert not any(s.machine_id == "M1" for s in result.segments)
    assert all(lot.op_id != "A" for lot in result.lots)
    assert _produced(result, "B") == 3000
    # Unmet demand: late, never a hard violation.
    assert result.score["otd_d"] < 100
    assert result.score["hard_violations"] == 0
    metrics = result.gate_report["metrics"]
    assert metrics["orders_late"] == 1
    assert result.gate_report["coverage_gate_passed"]
    assert result.gate_report["requires_approval"]


def test_started_lot_on_deactivated_machine_keeps_its_history_rest_on_alternative():
    data, config, baseline = _scenario(
        [_op("A", "M1", "T1", "M2", day=5)],
        {"T1": {"primary": "M1", "alt": "M2", "setup_hours": 0.5}},
    )
    history = [s for s in baseline.segments if s.day_idx == 0]
    assert history and {s.machine_id for s in baseline.segments} == {"M1"}
    assert any(s.day_idx == 1 for s in baseline.segments)
    data, config, result, _warnings = _replan(
        data, config, baseline, {"machine_active": {"M1": False}},
    )
    assert _valid(result, data, config) == []
    for segment in history:  # what ran on day 0 stays exactly as it was
        assert segment in result.segments
    m1 = [s for s in result.segments if s.machine_id == "M1"]
    assert all((s.day_idx, s.end_min) <= (1, 600) for s in m1)
    m2 = [s for s in result.segments if s.machine_id == "M2"]
    assert m2 and m2[0].setup_min > 0
    assert _produced(result, "A") == 3000
    [lot] = result.lots
    assert lot.machine_id == "M2" and lot.qty == 3000
    baseline_snapshot, candidate = _snapshots(data, config, baseline, result)
    assert frozen.historical_schedule_changes(baseline_snapshot, candidate, now=NOW) == []


def test_started_lot_on_deactivated_machine_without_alternative_keeps_what_it_made():
    data, config, baseline = _scenario(
        [_op("A", "M1", "T1", day=5), _op("B", "M2", "T2", day=8)],
        {"T1": {"primary": "M1"}, "T2": {"primary": "M2"}},
    )
    data, config, result, warnings = _replan(
        data, config, baseline, {"machine_active": {"M1": False}},
    )
    assert warnings and warnings[0].startswith(NO_ACTIVE_MACHINE_PREFIX)
    assert _valid(result, data, config) == []
    made = [s for s in result.segments if s.machine_id == "M1"]
    assert made and all((s.day_idx, s.end_min) <= (1, 600) for s in made)
    [lot] = [lot for lot in result.lots if lot.op_id == "A"]
    assert lot.qty == sum(s.qty for s in made) < 3000
    assert result.score["otd_d"] < 100
    baseline_snapshot, candidate = _snapshots(data, config, baseline, result)
    assert frozen.historical_schedule_changes(baseline_snapshot, candidate, now=NOW) == []


def test_alternative_removed_while_lot_started_today_on_it_goes_on_on_the_primary():
    data, config, baseline = _scenario(
        [_op("A", "M1", "T1", "M2", day=5), _op("X", "M1", "TX", day=5, qty=6000)],
        {"T1": {"primary": "M1", "alt": "M2", "setup_hours": 0.5},
         "TX": {"primary": "M1", "setup_hours": 0.5}},
    )
    on_alt = [s for s in baseline.segments if _lot_op(baseline, s.lot_id) == "A"]
    assert {s.machine_id for s in on_alt} == {"M2"}, "fixture: A runs on its alternative"
    assert any(s.day_idx == 1 for s in on_alt)
    data, config, result, _warnings = _replan(
        data, config, baseline, {"tool_updates": {"T1": {"alt": None}}},
    )
    assert _valid(result, data, config) == []
    after = [s for s in result.segments if _lot_op(result, s.lot_id) == "A"]
    for segment in (s for s in on_alt if s.day_idx == 0):
        assert segment in result.segments
    assert all(
        (s.day_idx, s.end_min) <= (1, 600) for s in after if s.machine_id == "M2"
    )
    assert any(s.machine_id == "M1" for s in after)
    assert _produced(result, "A") == 3000


def _snapshots(data, config, baseline, result):
    from dataclasses import asdict

    def snapshot(plan):
        return {
            "dataset_info": {"id": "fixture"},
            "config": {"timezone": config.timezone},
            "engine_data": {"workdays": list(data.workdays)},
            "segments": [asdict(s) for s in plan.segments],
            "lots": [asdict(lot) for lot in plan.lots],
        }

    return snapshot(baseline), snapshot(result)


def test_a_portuguese_planning_refusal_is_its_own_cause_not_an_internal_error(monkeypatch):
    from backend.replan import jobs

    assert jobs.portuguese_text("Não foi possível alocar as quantidades libertadas da referência X")
    assert not jobs.portuguese_text("Planning deadline expired")
    assert not jobs.portuguese_text("")


# ── Real case: revision 164, 16/10/2026 09:54Z ──────────────────────────────


def test_live_revision_164_deactivations_and_alternative_removal_are_planned(monkeypatch):
    from backend import calendar as factory_calendar
    from backend.plans.serialize import deserialize_snapshot
    from backend.replan import jobs
    from tests.snapshot_fixture import load_payload

    _, payload = load_payload("rev_live1610")
    now = datetime.fromisoformat("2026-10-16T09:54:00+00:00")
    monkeypatch.setattr(factory_calendar, "_wall_clock", lambda zone: now.astimezone(zone))
    restored = deserialize_snapshot(copy.deepcopy(payload))
    config, data = copy.deepcopy(restored["config"]), copy.deepcopy(restored["engine_data"])
    _apply_change(
        "machine_active", {"MAE054": False, "MAS191": False, "PRM042": False},
        config, data, config.day_capacity_min,
    )
    _apply_change("tool_updates", {"BFP080": {"alt": None}}, config, data,
                  config.day_capacity_min)
    apply_effective_planning_config(data, config)
    assert validate_config(config, data) == []
    warnings = _sync_active_machines(config, data)
    [notice] = [w for w in warnings if w.startswith(NO_ACTIVE_MACHINE_PREFIX)]
    assert "8708103279" in notice and "e mais" in notice

    store = jobs.ReplanJobStore(":memory:")
    manager = jobs.ReplanJobManager(store)
    dataset = restored["dataset_info"]
    job = store.create("Máquinas ativas", str(dataset["id"]), payload["plan_revision"])
    started = time.monotonic()
    try:
        manager._run(
            job["id"], data, config, str(dataset["id"]), payload["plan_revision"],
            "Máquinas ativas", copy.deepcopy(dataset), warnings,
            copy.deepcopy(payload), False, False, False,
        )
    finally:
        manager.executor.shutdown(wait=True)
    final = store.get(job["id"])
    assert final.get("code") != "internal_error", final
    if final.get("code") == "planning_timeout":  # AGENTS §6: may stop by time
        pytest.skip("planning budget exhausted on this machine")
    assert final["status"] == "ready", final
    assert time.monotonic() - started < jobs.REPLAN_TOTAL_BUDGET_S + 15
    gate = final["result"]["gate_report"]
    assert gate["physical_gate_passed"] and gate["coverage_gate_passed"]
    assert gate["requires_approval"]  # the unmet demand is late

    candidate = store.get_candidate(job["id"])
    assert notice in candidate["warnings"]
    segments, lots = candidate["segments"], {lot["id"]: lot for lot in candidate["lots"]}
    inactive = {"MAE054", "MAS191", "PRM042"}
    today_from_now = 1, 10 * 60 + 54 + 1  # 10:54 in Lisbon
    for segment in segments:
        if segment["machine_id"] in inactive:  # only what already ran
            assert (segment["day_idx"], segment["end_min"]) <= today_from_now, segment
    # BFP080: started on PRM039 this morning, the rest goes on on PRM019.
    bfp080 = [s for s in segments if s["tool_id"] == "BFP080"]
    assert {s["machine_id"] for s in bfp080} == {"PRM039", "PRM019"}
    for segment in bfp080:
        if segment["machine_id"] == "PRM039":
            assert (segment["day_idx"], segment["end_min"]) <= today_from_now, segment
    assert lots["LOT_BFP080_PRM019_1065170X100_5"]["machine_id"] == "PRM019"
    # Started on MAE054 with no alternative: keeps only what it made.
    made = [s for s in segments if s["lot_id"] == "LOT__MAE054_8708103279_1"]
    assert made and lots["LOT__MAE054_8708103279_1"]["qty"] == sum(s["qty"] for s in made)
