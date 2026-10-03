"""A priority rotation must carry a retained campaign, not strand its tail."""

import copy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.canonical import preserved_lot_proofs
from backend.scheduler.global_jit import materialise_fixed_run
from backend.scheduler.improvement import contract_verdict, physical_setups
from backend.scheduler.priority_normalization import (
    _build_priority_rotation_candidates,
    find_priority_order_anomalies,
    repair_priority_inversions,
)
from backend.scheduler.setup_identity import segment_setup_identity
from backend.scheduler.types import Lot, ToolRun
from backend.scheduler.validation import coverage_metrics, validate_plan
from backend.types import EOp, EngineData, MachineInfo, PlanAnchor, TwinGroup


def _case(*, twin=False, renamed=False, durations=(100, 100, 100)):
    later_minutes, urgent_minutes, tail_minutes = durations
    urgent_tool, later_tool = ("BFP082", "BFP080") if not renamed else ("X", "Y")
    config = FactoryConfig(
        machines={"M": MachineConfig("M", "Grandes", oee=1)},
        operators={("Grandes", "A"): 2, ("Grandes", "B"): 2},
        setup_crews_by_group={"Grandes": 1},
    )
    dates = [(date(2026, 1, 5) + timedelta(days=day)).isoformat() for day in range(12)]
    data = EngineData(
        ops=[EOp(
            id=op, sku=op, client="C", designation=op, m="M", t=tool,
            pH=60, sH=.5, operators=1, eco_lot=0, alt=None, stk=0, backlog=0,
            d=demand, oee=1, wip=0,
        ) for op, tool, demand in (
            ("U", urgent_tool, [urgent_minutes, 0, 0, 0, tail_minutes] + [0] * 7),
            ("L", later_tool, [0, 0, 0, 0, later_minutes] + [0] * 7),
        )],
        machines=[MachineInfo("M", "Grandes", 1020)], twin_groups=[],
        client_demands={}, workdays=dates, n_days=12, holidays=[5, 6],
    )
    lots = [Lot(
        id=name, op_id=op, sku=op, tool_id=tool, machine_id="M",
        alt_machine_id=None, qty=minutes, prod_min=minutes, setup_min=30, edd=due,
        original_edd=due, production_due_day=due, customer_delivery_day=due,
        material_release_day=release, is_twin=twin and op == "U",
        twin_outputs=[("U", "U", minutes), ("U2", "U2", minutes)] if twin and op == "U" else None,
    ) for name, op, tool, due, release, minutes in (
        ("LATER", "L", later_tool, 4, 0, later_minutes),
        ("URGENT", "U", urgent_tool, 0, 0, urgent_minutes),
        ("TAIL", "U", urgent_tool, 4, 1, tail_minutes),
    )]
    if twin:
        data.ops.append(replace(data.ops[0], id="U2", sku="U2"))
        data.twin_groups.append(TwinGroup(urgent_tool, "M", "U", "U2", "U", "U2", 0, 0))
    rows = []
    cursor = 1020
    for index, lot in enumerate(lots):
        setup = 30 if index < 2 else 0
        run = ToolRun(
            id=f"R-{lot.id}", tool_id=lot.tool_id, machine_id="M",
            alt_machine_id=None, lots=[lot], setup_min=setup,
            total_prod_min=lot.prod_min, total_min=lot.prod_min + setup, edd=lot.edd,
        )
        rows.extend(materialise_fixed_run(run, "M", cursor, [0, 1, 2, 3, 4, 7, 8, 9, 10, 11], config))
        cursor += lot.prod_min + setup
    assert validate_plan(rows, data, config, lots=lots) == []
    return rows, lots, data, config


@pytest.mark.parametrize("twin", [False, True])
@pytest.mark.parametrize("renamed", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("today", [0, 2])
def test_rotation_carries_setup_free_tail_and_releases_real_time(monkeypatch, twin, renamed, reverse, today):
    rows, lots, data, config = _case(twin=twin, renamed=renamed)
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: today)
    if reverse:
        rows, lots = list(reversed(rows)), list(reversed(lots))
    original = copy.deepcopy((rows, lots, data, config))

    result = repair_priority_inversions(rows, lots, data, config)

    ordered = sorted(result, key=lambda s: (s.day_idx, s.start_min))
    assert [s.lot_id for s in ordered] == ["URGENT", "TAIL", "LATER"]
    assert ordered[0].production_start_min == 450
    assert ordered[1].start_min == ordered[0].end_min
    assert ordered[1].setup_min == 0
    assert segment_setup_identity(ordered[0]) == segment_setup_identity(ordered[1])
    assert physical_setups(result) == physical_setups(rows)
    assert contract_verdict(result, rows, data, candidate_lots=lots).admissible
    assert validate_plan(result, data, config, lots=lots) == []
    assert not any(coverage_metrics(result, lots)[key] for key in (
        "missing_lots", "missing_qty", "overproduced_qty", "twin_output_mismatches",
    ))
    assert repair_priority_inversions(result, lots, data, config) == result
    assert (rows, lots, data, config) == original


@pytest.mark.parametrize("protected", ["URGENT", "TAIL", "LATER"])
@pytest.mark.parametrize("kind", ["proof", "anchor"])
def test_rotation_never_moves_any_protected_campaign_member(protected, kind):
    rows, lots, data, config = _case()
    if kind == "proof":
        data.preserved_lot_proofs = preserved_lot_proofs(
            [s for s in rows if s.lot_id == protected], [lot for lot in lots if lot.id == protected],
        )
    else:
        first = next(s for s in rows if s.lot_id == protected)
        minute = first.production_start_min
        data.plan_anchors = [PlanAnchor(
            protected, "M", f"2026-01-06T{int(minute) // 60:02d}:{int(minute) % 60:02d}",
        )]

    result = repair_priority_inversions(rows, lots, data, config)

    assert result == rows


def test_rotation_does_not_merge_different_adjustments_of_one_tool():
    rows, lots, data, config = _case()
    lots[-1] = replace(lots[-1], op_id="U2", sku="U2")
    data.ops.append(replace(data.ops[0], id="U2", sku="U2", d=[0, 0, 0, 0, 100] + [0] * 7))
    data.ops[0].d[4] = 0
    rows[-1] = replace(rows[-1], sku="U2", setup_min=30, prod_min=100,
                       end_min=rows[-1].end_min + 30, run_setup_min=30)
    assert validate_plan(rows, data, config, lots=lots) == []
    detail = next(item for item in find_priority_order_anomalies(rows, lots, data)
                  if item["urgent_lot_id"] == "URGENT")

    candidates = _build_priority_rotation_candidates(rows, lots, data, config, detail)

    assert candidates
    assert all(next(s for s in candidate if s.lot_id == "TAIL") == rows[-1]
               for candidate in candidates)


def test_rotation_waits_for_a_legal_setup_window_at_shift_close():
    rows, lots, data, config = _case(durations=(100, 700, 280))

    result = repair_priority_inversions(rows, lots, data, config)

    first = min(result, key=lambda s: (s.day_idx, s.start_min))
    assert first.lot_id == "URGENT"
    assert validate_plan(result, data, config, lots=lots) == []
    assert contract_verdict(result, rows, data, candidate_lots=lots).admissible
    assert physical_setups(result) == physical_setups(rows)
    later_first = min((s for s in result if s.lot_id == "LATER"),
                      key=lambda s: (s.day_idx, s.start_min))
    assert (later_first.day_idx, later_first.start_min) == (2, 420)
