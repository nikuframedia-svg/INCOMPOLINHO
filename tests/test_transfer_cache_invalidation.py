"""Transfer screening must see shared resources beyond its two machines."""

import copy
from dataclasses import replace

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.planning_control import planning_scope
from backend.scheduler.improvement import (
    Generator, Proposal, contract_verdict, improve_plan, physical_setups, tool_transfers,
)
from backend.scheduler.transfer_consolidation import consolidation_proposals
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import validate_plan
from backend.transform.calendars import apply_calendars
from backend.types import EOp, EngineData, MachineInfo


def _case(renamed=False, crew=False):
    tool = "BFP079" if not renamed else "OTHER"
    config = FactoryConfig(
        machines={mid: MachineConfig(mid, group, oee=1) for mid, group in (
            ("M1", "Grandes"), ("M2", "Medias"),
            ("M3", "Grandes"), ("M4", "Independent"),
        )},
        operators={(group, shift): 2 if crew else 1 for group in ("Grandes", "Medias", "Independent")
                   for shift in ("A", "B")},
        machine_unavailability=[{"id": mid, "resource": mid,
                                 "start_at": "2026-01-07T00:00:00", "end_at": None}
                                for mid in ("M1", "M2")],
    )
    shared_qty = 1 if crew else 1920
    ops = [EOp(
        id=name, sku=name, client="C", designation=name, m=mid, t=mould,
        pH=60, sH=.5, operators=1, eco_lot=0, alt=alt, stk=0, backlog=0,
        d=[0, qty, 0] if name != "C" or not crew else [0, 0, qty], oee=1, wip=0,
    ) for name, mid, alt, mould, qty in (
        ("P", "M1", "M2", tool, 120), ("C", "M3", "M4", "U", shared_qty),
    )]
    if crew:
        ops.append(replace(ops[0], id="Q", sku="Q", d=[0, 60, 0]))
        ops[0].d[1] = 60
        ops[1].sH = 32.5
    data = EngineData(
        ops=ops, machines=[MachineInfo(mid, machine.group, 1020)
                           for mid, machine in config.machines.items()],
        twin_groups=[], client_demands={},
        workdays=["2026-01-05", "2026-01-06", "2026-01-07"], n_days=3,
    )
    apply_calendars(data, config)
    lots = [Lot(
        id=name, op_id=op, sku=op, tool_id=mould, machine_id=mid,
        alt_machine_id=alt, qty=qty, prod_min=qty, setup_min=30, edd=1, is_twin=False,
        original_edd=1, production_due_day=1, customer_delivery_day=1,
        material_release_day=0,
    ) for name, op, mid, alt, mould, qty in (
        ("HEAD", "P", "M1", "M2", tool, 60),
        ("TAIL", "Q" if crew else "P", "M2", "M1", tool, 60),
        ("SHARED", "C", "M3", "M4", "U", shared_qty),
    )]
    if crew:
        lots[2] = replace(lots[2], setup_min=1950, edd=2, original_edd=2,
                          production_due_day=2, customer_delivery_day=2)
    rows = []
    for lot, day, start, end, setup, qty in (
        (lots[0], 0, 420, 510, 30, 60), (lots[1], 0, 600, 690, 30, 60),
        (lots[2], 0, 510, 930, 420 if crew else 30, 0 if crew else 390),
        (lots[2], 0, 930, 1440, 510 if crew else 0, 0 if crew else 510),
        (lots[2], 1, 420, 930, 510 if crew else 0, 0 if crew else 510),
        (lots[2], 1, 930, 1440, 510 if crew else 0, 0 if crew else 510),
    ):
        rows.append(Segment(
            lot_id=lot.id, run_id=f"R-{lot.id}", machine_id=lot.machine_id,
            tool_id=lot.tool_id, sku=lot.sku, day_idx=day, start_min=start,
            end_min=end, setup_min=setup, prod_min=qty, qty=qty, edd=lot.edd,
            shift="A" if start < 930 else "B", lot_qty=lot.qty, run_qty=lot.qty,
            run_setup_min=lot.setup_min, run_lot_count=1,
            production_due_day=lot.production_due_day, material_release_day=0,
        ))
    if crew:
        rows.append(replace(rows[-1], day_idx=2, start_min=420, end_min=421,
                            setup_min=0, prod_min=1, qty=1, shift="A"))
    return rows, lots, data, config


def _incoming(items):
    return [item for item in items if isinstance(item, Proposal)
            and item.subject["from_machine"] == "M2"
            and item.subject["to_machine"] == "M1"]


@pytest.mark.parametrize("renamed", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("crew", [False, True])
def test_released_shared_resources_invalidate_previous_transfer_screen(renamed, reverse, crew):
    rows, lots, data, config = _case(renamed, crew)
    if reverse:
        rows, lots = list(reversed(rows)), list(reversed(lots))
    original = copy.deepcopy((rows, lots, data, config))
    released = [replace(s, machine_id="M4") if s.lot_id == "SHARED" else s for s in rows]
    released_lots = [replace(lot, machine_id="M4", alt_machine_id="M3")
                     if lot.id == "SHARED" else lot for lot in lots]
    assert validate_plan(rows, data, config, lots=lots) == []
    assert validate_plan(released, data, config, lots=released_lots) == []

    with planning_scope(timeout_s=60):
        before = list(consolidation_proposals(rows, lots, data, config))
        after = list(consolidation_proposals(released, released_lots, data, config))
    with planning_scope(timeout_s=60):
        cold = list(consolidation_proposals(released, released_lots, data, config))

    assert not _incoming(before)
    assert _incoming(cold), "An executable, no-loss stay must exist after releasing the shared resource"
    assert _incoming(after), "A prior conclusion must not hide that stay after another machine releases operators"
    for proposal in _incoming(after):
        assert validate_plan(proposal.segments, data, config, lots=proposal.lots) == []
        assert contract_verdict(proposal.segments, released, data,
                                candidate_lots=proposal.lots, reference_lots=released_lots).admissible
        assert physical_setups(proposal.segments).count <= physical_setups(released).count
        assert tool_transfers(proposal.segments) < tool_transfers(released)
    assert (rows, lots, data, config) == original


@pytest.mark.parametrize("change", ["operators", "setup_crews", "machine_group", "absence"])
def test_changed_planning_inputs_invalidate_screen_without_moving_a_segment(change):
    rows, lots, data, config = _case(crew=change == "setup_crews")
    if change == "absence":
        config.operators[("Grandes", "A")] = 2
        config.operators[("Grandes", "B")] = 2
        config.operator_unavailability = [
            {"id": shift, "group": "Grandes", "shift": shift, "count": 1,
             "start_at": "2026-01-05T00:00:00", "end_at": "2026-01-07T00:00:00"}
            for shift in ("A", "B")
        ]
        apply_calendars(data, config)
    changed_config, changed_data = copy.deepcopy(config), copy.deepcopy(data)
    if change == "operators":
        changed_config.operators[("Grandes", "A")] = 2
        changed_config.operators[("Grandes", "B")] = 2
    elif change == "setup_crews":
        changed_config.setup_crews_by_group["Grandes"] = 2
    elif change == "machine_group":
        changed_config.machines["M3"].group = "Independent"
    else:
        changed_config.operator_unavailability = []
        apply_calendars(changed_data, changed_config)
    assert validate_plan(rows, data, config, lots=lots) == []
    assert validate_plan(rows, changed_data, changed_config, lots=lots) == []

    with planning_scope(timeout_s=60):
        before = list(consolidation_proposals(rows, lots, data, config))
        after = list(consolidation_proposals(rows, lots, changed_data, changed_config))
    with planning_scope(timeout_s=60):
        cold = list(consolidation_proposals(rows, lots, changed_data, changed_config))

    assert not _incoming(before)
    assert _incoming(cold)
    assert _incoming(after)
    for proposal in _incoming(after):
        assert validate_plan(proposal.segments, changed_data, changed_config, lots=proposal.lots) == []
        assert contract_verdict(proposal.segments, rows, changed_data,
                                candidate_lots=proposal.lots, reference_lots=lots).admissible


def test_unchanged_screen_reuses_work_but_never_crosses_execution(monkeypatch):
    import backend.scheduler.transfer_consolidation as module

    rows, lots, data, config = _case()
    rebuild, calls = module._rebuild, []

    def tracked(hop, *args, **kwargs):
        if hop.from_machine == "M2":
            calls.append(hop.key)
        return rebuild(hop, *args, **kwargs)

    monkeypatch.setattr(module, "_rebuild", tracked)
    with planning_scope(timeout_s=60):
        list(consolidation_proposals(rows, lots, data, config))
        count = len(calls)
        assert count > 0
        list(consolidation_proposals(list(reversed(rows)), lots, data, config))
        assert len(calls) == count
        annotated = [replace(s, left_shift_blockers=["diagnostic only"]) for s in rows]
        list(consolidation_proposals(annotated, lots, data, config))
        assert len(calls) == count
    with planning_scope(timeout_s=60):
        list(consolidation_proposals(rows, lots, data, config))
    assert len(calls) > count


@pytest.mark.parametrize("change", ["run_identity", "fractional_setup"])
def test_screen_identity_includes_exact_segment_planning_fields(monkeypatch, change):
    import backend.scheduler.transfer_consolidation as module

    rows, lots, data, config = _case()
    changed = [replace(s) for s in rows]
    if change == "run_identity":
        for segment in changed:
            if segment.lot_id == "SHARED":
                segment.run_id = "REGROUPED"
    else:
        segment = next(s for s in changed if s.lot_id == "SHARED")
        segment.setup_min += .0004
        segment.prod_min -= .0004
    assert validate_plan(changed, data, config, lots=lots) == []
    rebuild, calls = module._rebuild, []

    def tracked(hop, *args, **kwargs):
        if hop.from_machine == "M2":
            calls.append(hop.key)
        return rebuild(hop, *args, **kwargs)

    monkeypatch.setattr(module, "_rebuild", tracked)
    with planning_scope(timeout_s=60):
        list(consolidation_proposals(rows, lots, data, config))
        count = len(calls)
        assert count > 0
        list(consolidation_proposals(changed, lots, data, config))
    assert len(calls) > count, "Regrouping and exact setup boundaries are allocation inputs"


@pytest.mark.parametrize("renamed", [False, True])
def test_improvement_rechecks_transfer_after_another_machine_releases_resources(monkeypatch, renamed):
    import backend.scheduler.transfer_consolidation as module
    from backend.scheduler.alternative_repair import _resolve_runs, _schedule_run_earliest

    rows, lots, data, config = _case(renamed)
    config.machines["M3"].oee = .5
    data.ops[1].d[1] = 960
    lots = [replace(lot, qty=960) if lot.id == "SHARED" else lot for lot in lots]
    rows = [replace(s, qty=s.qty // 2, lot_qty=960, run_qty=960)
            if s.lot_id == "SHARED" else s for s in rows]
    assert validate_plan(rows, data, config, lots=lots) == []
    original = copy.deepcopy((rows, lots, data, config))
    run = _resolve_runs(rows, lots, None)["R-SHARED"]
    fixed = [s for s in rows if s.lot_id != "SHARED"]
    rebound, created = _schedule_run_earliest(run, "M4", fixed, data, config)
    freed = [*fixed, *created]
    freed_lots = [rebound.lots[0] if lot.id == "SHARED" else lot for lot in lots]
    assert validate_plan(freed, data, config, lots=freed_lots) == []
    enumerate_hops = module.enumerate_transfer_hops
    monkeypatch.setattr(module, "enumerate_transfer_hops", lambda *args: [
        hop for hop in enumerate_hops(*args) if hop.from_machine == "M2"
    ])
    generators = [
        Generator("compact", lambda segs, ls: Proposal(segs, ls)),
        Generator("transfer", lambda segs, ls: consolidation_proposals(segs, ls, data, config)),
        Generator("release", lambda *_: Proposal(copy.deepcopy(freed), copy.deepcopy(freed_lots))),
    ]

    with planning_scope(timeout_s=60):
        result, result_lots, report = improve_plan(rows, lots, data, config, generators=generators)

    assert report["status"] == "completed"
    assert report["accepted_by_scope"] == {"release": 1, "transfer": 1}
    assert tool_transfers(result) == 0
    assert validate_plan(result, data, config, lots=result_lots) == []
    assert contract_verdict(result, rows, data, candidate_lots=result_lots, reference_lots=lots).admissible
    again, again_lots, second = improve_plan(result, result_lots, data, config, generators=generators)
    assert second["moves_accepted"] == 0
    assert (again, again_lots) == (result, result_lots)
    assert (rows, lots, data, config) == original
