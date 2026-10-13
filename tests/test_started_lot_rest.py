"""A started lot: only what started is frozen (AGENTS §2, rule 4).

Scenario (blocker of the rehearsal of 11/10/2026, reduced): lot L starts on
day 0, a different tool runs after it, and L's second portion later continues
without setup on the tool mounted by lot M of the same reference. Freezing
the whole started lot kept that continuation but not its mount supplier;
an outage that moved M left the continuation without its tool.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.plans import frozen
from backend.scheduler.canonical import result_validation_data
from backend.scheduler.improvement import _segment_physical_row
from backend.scheduler.lot_sizing import create_lots, upgrade_lot_material
from backend.scheduler.types import ScheduleResult, Segment
from backend.scheduler.validation import assert_plan_valid
from backend.types import EngineData, EOp, MachineInfo, PlanAnchor

START = date(2026, 3, 2)  # a Monday


def _config() -> FactoryConfig:
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    config.tools = {"T1": {"primary": "M1", "setup_hours": 0.5},
                    "T2": {"primary": "M1", "setup_hours": 0.5}}
    return config


def _op(op_id, sku, tool, demand, eco_lot):
    return EOp(
        id=op_id, sku=sku, client="C", designation="Peça", m="M1", t=tool, pH=100,
        sH=0.5, operators=1, eco_lot=eco_lot, alt=None, stk=0, backlog=0, d=demand,
        oee=1.0, wip=0,
    )


def _data(later=((9, 100),)) -> EngineData:
    """``later``: L's deliveries after day 3 (L = 200 pieces with day 3)."""
    days = [(START + timedelta(days=i)).isoformat() for i in range(14)]
    main = [0] * len(days)
    main[3], main[11] = 100, 100
    for day, qty in later:
        main[day] = qty
    other = [0] * len(days)
    other[2] = 100
    return EngineData(
        ops=[_op("OP1", "SKU1", "T1", main, 200), _op("OP2", "SKU2", "T2", other, 0)],
        machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[], client_demands={},
        workdays=days, n_days=len(days),
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )


def _segment(lot, day, start, qty, setup, run_id):
    prod = lot.prod_min * qty / lot.qty
    return Segment(
        lot.id, run_id, "M1", lot.tool_id, day, start, start + int(setup + prod), "A", qty,
        prod, setup, sku=lot.sku, lot_qty=lot.qty,
        output_milestones=copy.deepcopy(lot.output_milestones),
    )


def _baseline(data, config, blocks):
    """``blocks``: (lot index, day, start, qty, setup, run lot index).

    A plan saved under the per-delivery contract (material version 2), where
    L's portions were separate productions; replans take it over as
    version 3 (``frozen.with_current_material``).
    """
    lots = create_lots(data, config, quantity_material=2)
    assert [(lot.op_id, lot.qty) for lot in lots] == [("OP1", 200), ("OP1", 200), ("OP2", 100)]
    segments = [
        _segment(lots[index], day, start, qty, setup, f"quantity:{lots[run].id}:0")
        for index, day, start, qty, setup, run in blocks
    ]
    assert_plan_valid(segments, data, config, lots=lots)
    return ScheduleResult(segments=segments, lots=lots, score={}, time_ms=0, warnings=[],
                          operator_alerts=[]), lots


# L's first portion, the other tool, then M's setup and L's second portion
# continuing M's mounted tool (the pattern of LOT_HAN002_..._7/_14).
SUPPLIED = [(0, 0, 420, 100, 30, 0), (2, 0, 510, 100, 30, 2),
            (1, 4, 420, 200, 30, 1), (0, 4, 570, 100, 0, 1)]
# L's first portion on day 0 and its run going on, without setup, on day 2.
RUNNING = [(0, 0, 420, 100, 30, 0), (0, 2, 420, 100, 0, 0),
           (2, 2, 480, 100, 30, 2), (1, 4, 420, 200, 30, 1)]


def test_only_started_portion_is_frozen_and_rest_keeps_the_lot():
    data, config = _data(), _config()
    baseline, (lot_l, lot_m, lot_x) = _baseline(data, config, SUPPLIED)

    protected = frozen._protected_plan(baseline, 1, data, config)

    assert [(s.lot_id, s.day_idx) for s in protected.segments] == [
        (lot_l.id, 0), (lot_x.id, 0),
    ]
    assert [lot.id for lot in protected.lots] == [lot_x.id]  # all of it started
    assert protected.started == {lot_l.id, lot_x.id}
    (original, rest), = protected.partial
    # Taken over as version 3: same lot, released whole at the lot R.
    assert original == upgrade_lot_material(lot_l, data)
    assert rest.material_release_day == original.material_release_day
    # The rest of the same economic lot: never re-sized, same machine.
    assert (rest.id, rest.qty, rest.machine_id, rest.alt_machine_id) == (lot_l.id, 100, "M1", None)
    assert [(o["qty"], o["customer_delivery_day"]) for o in rest.output_milestones] == [(100, 9)]
    assert rest.edd == rest.production_due_day == lot_l.output_milestones[1]["production_due_day"]
    assert rest.prod_min == pytest.approx(lot_l.prod_min / 2)
    assert rest.setup_min == lot_l.setup_min
    # M has not started: nothing of it is frozen.
    assert all(s.lot_id != lot_m.id for s in protected.segments)


def test_outage_moving_the_mount_supplier_gives_a_valid_plan(monkeypatch):
    data, config = _data(), _config()
    baseline, (lot_l, lot_m, lot_x) = _baseline(data, config, SUPPLIED)
    outage = copy.deepcopy(data)
    outage.machine_blocked_days = {"M1": {4}}
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)

    result = frozen.optimize_preserving_started_lots(outage, config, baseline, mode="quick")

    assert_plan_valid(
        result.segments, result_validation_data(outage, result), config, lots=result.lots,
    )
    by_id = {lot.id: lot for lot in result.lots}
    # Lot sizing ran once: the same lots, the started one unchanged.
    assert sorted(by_id) == sorted(lot.id for lot in baseline.lots)
    assert by_id[lot_l.id] == upgrade_lot_material(lot_l, outage)
    produced = {lot_id: sum(s.qty for s in result.segments if s.lot_id == lot_id)
                for lot_id in by_id}
    assert produced == {lot_l.id: 200, lot_m.id: 200, lot_x.id: 100}
    # What started is exactly as before; nothing runs on the blocked day.
    rows = {_segment_physical_row(s) for s in result.segments}
    assert {_segment_physical_row(baseline.segments[i]) for i in (0, 1)} <= rows
    assert all(s.day_idx != 4 for s in result.segments)
    assert result.preserved_lot_proofs == frozen._splice_frozen_started_lots(
        ScheduleResult([], [], {}, 0, [], []), baseline.segments[:2],
        [upgrade_lot_material(lot_x, outage)],
    ).preserved_lot_proofs
    assert any("produção já iniciada mantém-se" in w for w in result.warnings)


def test_running_run_is_frozen_until_the_new_inputs_stop_it():
    data, config = _data(), _config()
    baseline, (lot_l, _lot_m, _lot_x) = _baseline(data, config, RUNNING)

    protected = frozen._protected_plan(baseline, 2, data, config)
    # The mounted run continues on day 2 without setup: it is what started.
    assert [(s.lot_id, s.day_idx) for s in protected.segments] == [(lot_l.id, 0), (lot_l.id, 2)]
    assert [lot.id for lot in protected.lots] == [lot_l.id]
    assert protected.partial == []

    blocked = copy.deepcopy(data)
    blocked.machine_blocked_days = {"M1": {2}}
    protected = frozen._protected_plan(baseline, 2, blocked, config)
    # A breakdown stops the run: its continuation is replanned.
    assert [(s.lot_id, s.day_idx) for s in protected.segments] == [(lot_l.id, 0)]
    (_original, rest), = protected.partial
    assert rest.qty == 100


def test_frozen_continuation_keeps_its_mount_supplier():
    """Rule (b): a frozen setup-free continuation never loses its supplier."""
    data, config = _data(), _config()
    baseline, (lot_l, lot_m, lot_x) = _baseline(data, config, SUPPLIED)
    data.plan_anchors = [PlanAnchor(lot_l.id, "M1", "2026-03-02T07:30", "manual", "planeador")]

    protected = frozen._protected_plan(baseline, 0, data, config)

    # L is anchored (kept whole) and continues on M's mounting: M is kept too.
    assert sorted(lot.id for lot in protected.lots) == sorted([lot_l.id, lot_m.id])
    assert all(s.lot_id != lot_x.id for s in protected.segments)

    _segments, lots, _anchored = frozen._protected_lots(
        baseline, 1, data, config, mount_suppliers=True,
    )
    assert {lot.id for lot in lots} == {lot_l.id, lot_m.id, lot_x.id}
    _segments, lots, _anchored = frozen._protected_lots(baseline, 1, data, config)
    assert {lot.id for lot in lots} == {lot_l.id, lot_x.id}


def test_residual_lot_sizing_returns_the_rest_without_sizing_it_again():
    data, config = _data(), _config()
    baseline, (lot_l, lot_m, lot_x) = _baseline(data, config, SUPPLIED)
    protected = frozen._protected_plan(baseline, 1, data, config)
    residual = copy.deepcopy(data)

    snapshot = frozen._install_frozen_reservations(
        residual, protected.segments, protected.lots, 1, config, protected.partial,
    )
    lots = create_lots(residual, config)
    assert [(lot.id, lot.qty) for lot in lots] == [(lot_m.id, 200), (lot_l.id, 100)]
    frozen._restore_frozen_reservations(residual, snapshot)
    assert residual == data


def test_rest_of_a_started_lot_never_reuses_a_frozen_run_id():
    """The rest keeps the lot id: a new run of it must not take the frozen
    run's id, or the frozen setup and the new one would join one run."""
    from backend.scheduler.scheduler import schedule_all

    # The rest has two material portions (days 9 and 10): the campaign builder.
    data, config = _data(later=((9, 50), (10, 50))), _config()
    baseline, (lot_l, _lot_m, _lot_x) = _baseline(data, config, SUPPLIED)
    residual = copy.deepcopy(data)
    residual.machine_blocked_days = {"M1": {4}}
    protected = frozen._protected_plan(baseline, 1, residual, config)
    frozen._install_frozen_reservations(
        residual, protected.segments, protected.lots, 1, config, protected.partial,
    )

    built = schedule_all(residual, config=config)

    rest = [s for s in built.segments if s.lot_id == lot_l.id]
    assert sum(s.qty for s in rest) == 100
    frozen_runs = {s.run_id for s in protected.segments}
    assert all(s.run_id not in frozen_runs for s in rest if s.setup_min > 0)
    assert not any("campanhas" in w for w in built.warnings)


def test_compaction_moves_only_the_rest_of_a_started_lot(monkeypatch):
    """Capacity released: the rest of L may move earlier, its start never."""
    data, config = _data(), _config()
    baseline, (lot_l, lot_m, _lot_x) = _baseline(data, config, SUPPLIED)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)

    result = frozen.compact_preserving_started_lots(data, config, copy.deepcopy(baseline))

    assert_plan_valid(
        result.segments, result_validation_data(data, result), config, lots=result.lots,
    )
    assert {_segment_physical_row(baseline.segments[i]) for i in (0, 1)} <= {
        _segment_physical_row(s) for s in result.segments
    }
    assert {lot.id: lot.qty for lot in result.lots} == {lot.id: lot.qty for lot in baseline.lots}
    assert sum(s.qty for s in result.segments if s.lot_id == lot_l.id) == lot_l.qty
    assert sum(s.qty for s in result.segments if s.lot_id == lot_m.id) == lot_m.qty
    assert result.improvement_report.get("stop_reason") != "reference_invalid"
