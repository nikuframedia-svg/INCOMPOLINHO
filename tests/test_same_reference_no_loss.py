"""Same-reference normalisation must not trade individual dispatch promises."""

import copy

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.planning_control import PlanningCancelled, PlanningTimeout, planning_scope
from backend.scheduler.canonical import production_lot_obligations
from backend.scheduler.improvement import (
    contract_verdict,
    subcontract_lateness,
)
from backend.scheduler.priority_normalization import repair_same_reference_interruptions
from backend.scheduler.scheduler import normalize_earliest_legal_plan
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import assert_plan_valid, coverage_violations
from backend.types import ClientDemandEntry, EngineData, EOp, MachineInfo


def _case(*, twin, prefix):
    machine, tool = prefix + "machine", prefix + "tool"
    config = FactoryConfig(machines={machine: MachineConfig(machine, "Grandes")})
    outputs = [(prefix + "op-a", prefix + "sku-a")]
    if twin:
        outputs.append((prefix + "op-b", prefix + "sku-b"))
    dates = [f"2026-09-{day:02d}" for day in range(14, 20)]
    data = EngineData(
        ops=[EOp(
            id=op_id, sku=sku, client="CLI", designation=sku, m=machine, t=tool,
            pH=60 / config.oee_default, sH=0.5, operators=1, eco_lot=0,
            alt=None, stk=0, backlog=0, d=[0, 0, 0, 0, 125, 90],
            oee=config.oee_default, wip=0, is_subcontracted=True,
            subcontract_lead_time_days=1, subcontract_buffer_days=3,
        ) for op_id, sku in outputs],
        machines=[MachineInfo(machine, "Grandes", config.day_capacity_min)],
        twin_groups=[],
        client_demands={sku: [
            ClientDemandEntry("CLI", sku, day, dates[day], qty, -qty)
            for day, qty in [(4, 125), (5, 90)]
        ] for _, sku in outputs},
        workdays=dates, n_days=6, holidays=[5],
    )
    lots = [Lot(
        id=prefix + name, op_id=outputs[0][0], tool_id=tool, machine_id=machine,
        alt_machine_id=None, qty=qty, prod_min=float(qty), setup_min=30,
        edd=due, original_edd=due + 4, customer_delivery_day=due + 4,
        production_due_day=due, is_twin=twin, sku=outputs[0][1],
        material_release_day=0, is_subcontracted=True,
        subcontract_lead_time_days=1, subcontract_buffer_days=3,
        twin_outputs=[(op_id, sku, qty) for op_id, sku in outputs] if twin else None,
    ) for name, qty, due in [("urgent", 125, 0), ("later", 90, 1)]]
    segments = []
    for lot_index, day, start, duration, setup in [
        (0, 0, 420, 60, 30),
        (1, 2, 420, 90, 0),
        (0, 2, 510, 5, 0),
        (0, 3, 420, 90, 0),
    ]:
        lot = lots[lot_index]
        qty = duration - setup
        segments.append(Segment(
            lot_id=lot.id, run_id=prefix + f"run-{lot_index}", machine_id=machine,
            tool_id=tool, day_idx=day, start_min=start, end_min=start + duration,
            shift="A", qty=qty, prod_min=float(qty), setup_min=setup,
            is_continuation=lot_index == 0 and day > 0, run_setup_min=30,
            sku=lot.sku, edd=lot.edd, original_edd=lot.original_edd,
            production_due_day=lot.production_due_day,
            customer_delivery_day=lot.customer_delivery_day, material_release_day=0,
            is_subcontracted=True, subcontract_lead_time_days=1,
            subcontract_buffer_days=3,
            twin_outputs=[(op_id, sku, qty) for op_id, sku in outputs] if twin else None,
        ))
    return segments, lots, data, config


@pytest.mark.parametrize("twin", [False, True])
@pytest.mark.parametrize("prefix", ["", "renamed-"])
@pytest.mark.parametrize("reverse", [False, True])
def test_same_reference_repair_cannot_exchange_dispatch_lateness(twin, prefix, reverse):
    segments, lots, data, config = _case(twin=twin, prefix=prefix)
    assert_plan_valid(segments, data, config, lots=lots)
    assert coverage_violations(segments, lots) == []
    original = copy.deepcopy((segments, lots, data, config))
    if reverse:
        segments = list(reversed(segments))
        lots = list(reversed(lots))

    result = repair_same_reference_interruptions(segments, lots, data, config)

    assert_plan_valid(result, data, config, lots=lots)
    assert coverage_violations(result, lots) == []
    verdict = contract_verdict(result, segments, data, candidate_lots=lots)
    assert verdict.admissible, verdict.reasons
    assert subcontract_lateness(result, lots) == subcontract_lateness(segments, lots)
    assert production_lot_obligations(lots) == production_lot_obligations(original[1])
    assert (sorted(segments, key=lambda s: (s.day_idx, s.start_min)),
            sorted(lots, key=lambda lot: lot.id), data, config) == (
        sorted(original[0], key=lambda s: (s.day_idx, s.start_min)),
        sorted(original[1], key=lambda lot: lot.id), original[2], original[3],
    )
    assert repair_same_reference_interruptions(result, lots, data, config) == result
    before = compute_score(segments, lots, data, config=config, include_operational_audit=False)
    after = compute_score(result, lots, data, config=config, include_operational_audit=False)
    assert before["otd"] == after["otd"] == 100
    assert before["otd_d"] == after["otd_d"] == 100
    assert before["subcontract_dispatch_misses"] == after["subcontract_dispatch_misses"] == (4 if twin else 2)
    assert before["subcontract_dispatch_late_workdays"] == after["subcontract_dispatch_late_workdays"]


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_same_reference_repair_checks_budget_inside_rebinding(monkeypatch, stop):
    from backend import planning_control
    from backend.scheduler import priority_normalization

    segments, lots, data, config = _case(twin=True, prefix="")
    original = copy.deepcopy((segments, lots, data, config))
    checks = 0
    clock = [0.0]
    cancelled = [False]

    def checkpoint():
        nonlocal checks
        checks += 1
        if checks == 3:
            if stop == "cancel":
                cancelled[0] = True
            else:
                clock[0] = 2.0
        planning_control.planning_checkpoint()

    monkeypatch.setattr(priority_normalization, "planning_checkpoint", checkpoint)
    with planning_scope(timeout_s=1, clock=lambda: clock[0], cancelled=lambda: cancelled[0]):
        with pytest.raises(PlanningCancelled if stop == "cancel" else PlanningTimeout):
            repair_same_reference_interruptions(segments, lots, data, config)
        clock[0] = 0.0
        cancelled[0] = False
    assert checks == 3
    assert (segments, lots, data, config) == original


@pytest.mark.parametrize("twin", [False, True])
def test_common_normalizer_can_still_improve_both_dispatches(twin):
    segments, lots, data, config = _case(twin=twin, prefix="")
    original = copy.deepcopy((segments, lots, data, config))

    with planning_scope(timeout_s=60):
        result = normalize_earliest_legal_plan(segments, lots, data, config, annotate=False)

    assert_plan_valid(result, data, config, lots=lots)
    assert coverage_violations(result, lots) == []
    assert contract_verdict(result, segments, data, candidate_lots=lots).admissible
    assert set(subcontract_lateness(result, lots).values()) == {0.0}
    assert {segment.day_idx for segment in result} == {0}
    assert sum(segment.setup_min for segment in result) == 30
    assert normalize_earliest_legal_plan(result, lots, data, config, annotate=False) == result
    assert (segments, lots, data, config) == original
