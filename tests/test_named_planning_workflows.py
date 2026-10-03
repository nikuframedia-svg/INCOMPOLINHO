"""Canonical, versioned reproductions through the complete improvement paths.

These small fixtures expose the named behaviours; they are not private ISOP
extracts and do not authorize changing the historical production plan.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import asdict, fields
from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.planning_control import planning_scope
from backend.plans.frozen import compact_preserving_started_lots
from backend.plans.serialize import deserialize_snapshot, serialize_result_snapshot
from backend.scheduler.canonical import production_lot_obligations
from backend.scheduler.gates import build_gate_report
from backend.scheduler.improvement import contract_verdict, improve_plan, physical_setups, tool_transfers
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.resources import rebind_runs_to_machines
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import ScheduleResult, Segment, ToolRun
from backend.scheduler.validation import coverage_violations, validate_plan
from backend.transform.calendars import apply_calendars
from backend.types import ClientDemandEntry, EOp, EngineData, MachineInfo, TwinGroup

FIXTURE = Path(__file__).parent / "fixtures/planning_opportunities_2026-09-17.json"
CASES = ("bfp112_previous_day", "bfp082_initial_priority", "bfp079_equivalent_machines")


def named_planning_case(name, *, renamed=False):
    fixture = json.loads(FIXTURE.read_text())
    case = copy.deepcopy(fixture["cases"][name])
    first = date.fromisoformat(fixture["first_day"])
    dates = [(first + timedelta(days=i)).isoformat() for i in range(fixture["n_days"])]
    # Rename every identifier, not just the visible tool, to catch special cases.
    identifiers = sorted({value for row in case["ops"]
                          for key in ("sku", "tool", "machine", "alt")
                          if (value := row.get(key))} | set(case["machines"]))
    mapping = {value: f"RESOURCE-{i}" if renamed else value
               for i, value in enumerate(identifiers)}
    config = FactoryConfig(
        machines={mapping[mid]: MachineConfig(mapping[mid], "Grandes", oee=oee)
                  for mid, oee in case["machines"].items()},
        oee_default=1.0,
        operators={("Grandes", shift): count for shift, count in case["operators"].items()},
        operator_unavailability=case.get("operator_unavailability", []),
    )
    ops, demands = [], {}
    for row in case["ops"]:
        sku, tool, mid = (mapping[row[key]] for key in ("sku", "tool", "machine"))
        op = EOp(
            id=f"{tool}_{mid}_{sku}", sku=sku, client="TEST", designation=sku,
            m=mid, t=tool, pH=100, sH=.5, operators=1, eco_lot=0,
            alt=mapping.get(row.get("alt")), stk=0, backlog=0, oee=1, wip=0,
            d=[row["demand"].get(str(day), 0) for day in range(fixture["n_days"])],
        )
        ops.append(op)
        config.tools[tool] = {"primary": mid, "alt": op.alt, "setup_hours": .5}
        demands[sku] = [ClientDemandEntry("TEST", sku, int(day), dates[int(day)], qty, -qty)
                        for day, qty in row["demand"].items()]
    twins = []
    for pair in case.get("twins", []):
        a, b = (next(op for op in ops if op.sku == mapping[sku]) for sku in pair)
        twins.append(TwinGroup(a.t, a.m, a.id, b.id, a.sku, b.sku, 0, 0))
        config.twins[a.t] = [a.sku, b.sku]
    data = EngineData(
        ops=ops, machines=[MachineInfo(mid, "Grandes", config.day_capacity_min)
                           for mid in config.machines], twin_groups=twins,
        client_demands=demands, workdays=dates, n_days=len(dates),
        holidays=[i for i, value in enumerate(dates) if date.fromisoformat(value).weekday() >= 5],
    )
    apply_calendars(data, config)
    data.setup_crew_reservations = case.get("crew_reservations", [])
    lots = create_lots(data, config)
    segment_fields = {field.name for field in fields(Segment)}
    segments = []
    for row in case["segments"]:
        lot = next(lot for lot in lots
                   if mapping[row["sku"]] in {sku for _, sku, _ in lot.twin_outputs or
                                               [(lot.op_id, lot.sku, lot.qty)]}
                   and lot.customer_delivery_day == row["due"])
        mid = mapping[row["machine"]] if "machine" in row else lot.machine_id
        run = ToolRun(f"RUN-{lot.id}", lot.tool_id, mid, lot.alt_machine_id,
                      [lot], lot.setup_min, lot.prod_min, lot.prod_min + lot.setup_min, lot.edd)
        rebind_runs_to_machines({mid: [run]}, data, config)
        prod = lot.prod_min * row["qty"] / lot.qty
        metadata = {key: value for key, value in asdict(lot).items() if key in segment_fields}
        metadata.update(lot_id=lot.id, run_id=run.id, machine_id=mid, day_idx=row["day"],
                        start_min=row["start"], end_min=math.ceil(row["start"] + row["setup"] + prod),
                        shift="A" if row["start"] < config.shift_a_end else "B",
                        qty=row["qty"], prod_min=prod, setup_min=row["setup"],
                        is_continuation=row["setup"] == 0, lot_qty=lot.qty, run_qty=lot.qty,
                        run_setup_min=lot.setup_min, run_lot_count=1)
        if lot.twin_outputs:
            metadata["twin_outputs"] = [(op_id, sku, row["qty"]) for op_id, sku, _ in lot.twin_outputs]
        segments.append(Segment(**metadata))
    result = ScheduleResult(segments, lots, compute_score(segments, lots, data, config), 0, [], [])
    result.gate_report = build_gate_report(segments, lots, result.score, data, config)
    case["expected"] = {key: mapping.get(value, value) if key == "sku" else value
                        for key, value in case["expected"].items()}
    return fixture, case, data, config, result


def assert_expected(case, result):
    expected = case["expected"]
    if "sku" in expected:
        rows = [s for s in result.segments if s.prod_min > 0 and s.sku == expected["sku"]]
        first = min(rows, key=lambda s: (s.day_idx, s.production_start_min))
        assert (first.day_idx, first.production_start_min) == (
            expected["first_day"], expected["production_start"])
        if "complete_day" in expected:
            assert max(s.day_idx for s in rows) == expected["complete_day"]
            ordered = sorted(rows, key=lambda s: (s.day_idx, s.start_min))
            assert all(b.start_min == a.end_min for a, b in zip(ordered, ordered[1:]))
    else:
        assert tool_transfers(result.segments) == expected["transfers"]
        assert physical_setups(result.segments).count <= expected["max_setups"]


@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("renamed", [False, True])
@pytest.mark.parametrize("path", ["cycle", "active_compaction", "api_compaction", "full_recompute"])
def test_named_opportunities_are_materialized_and_restart_exactly(monkeypatch, name, renamed, path):
    fixture, case, data, config, baseline = named_planning_case(name, renamed=renamed)
    original = copy.deepcopy((data, config, baseline))
    assert not validate_plan(baseline.segments, data, config, lots=baseline.lots)
    assert not coverage_violations(baseline.segments, baseline.lots)
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: 0)
    with planning_scope(timeout_s=60):
        if path == "cycle":
            segments, lots, report = improve_plan(
                baseline.segments, baseline.lots, data, config, time_budget_s=10)
            result = ScheduleResult(segments, lots, compute_score(segments, lots, data, config),
                                    0, [], [], improvement_report=report)
        elif path == "active_compaction":
            result = compact_preserving_started_lots(data, config, baseline)
        elif path == "api_compaction":
            from backend.api import data as data_api
            from backend.copilot.state import CopilotState

            target = CopilotState(engine_data=copy.deepcopy(data), config=copy.deepcopy(config),
                                  segments=copy.deepcopy(baseline.segments), lots=copy.deepcopy(baseline.lots),
                                  score=copy.deepcopy(baseline.score), gate_report=copy.deepcopy(baseline.gate_report))
            monkeypatch.setattr(data_api, "state", target)
            result = data_api._compact_active_schedule(target.config)
        else:
            from backend.plans.frozen import optimize_preserving_started_lots

            result = optimize_preserving_started_lots(copy.deepcopy(data), copy.deepcopy(config), baseline)
    assert_expected(case, result)
    assert not validate_plan(result.segments, data, config, lots=result.lots)
    assert not coverage_violations(result.segments, result.lots)
    assert production_lot_obligations(result.lots) == production_lot_obligations(baseline.lots)
    assert contract_verdict(result.segments, baseline.segments, data,
                            candidate_lots=result.lots, reference_lots=baseline.lots).admissible
    payload = serialize_result_snapshot(data, config, result, plan_revision=2,
        dataset_info={"id": name, "filename": "reduced-regression.xlsx", "clock": fixture["clock"]})
    restarted = deserialize_snapshot(copy.deepcopy(payload))
    assert restarted["result"].segments == result.segments
    assert restarted["result"].lots == result.lots
    assert_expected(case, restarted["result"])
    assert (data, config, baseline) == original
