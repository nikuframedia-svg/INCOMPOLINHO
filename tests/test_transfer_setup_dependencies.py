"""A transfer must close the mounting dependencies it removes or inserts."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from backend.scheduler.canonical import preserved_lot_proofs
from backend.scheduler.improvement import (
    Generator,
    Proposal,
    SkippedProposal,
    improve_plan,
    no_loss_verdict,
    physical_setups,
    plan_facts,
    tool_transfers,
)
from backend.scheduler.scoring import compute_score
from backend.scheduler.transfer_consolidation import SCOPE, consolidation_proposals
from backend.scheduler.validation import validate_plan
from backend.types import PlanAnchor
from backend.config.types import MachineConfig
from backend.types import MachineInfo
from tests.test_transfer_consolidation import _config, _data, _lot, _op, _seg


def _source_successor_case(prefix="P"):
    t = _op(f"{prefix}-T", "T", {0: 30, 1: 495}, machine="M2", alt="M1", rate=60)
    u = _op(f"{prefix}-U", "U", {1: 60, 2: 60}, rate=120)
    head = _lot(t, f"{prefix}-HEAD", qty=30, prod_min=60, due=0)
    head.machine_id, head.alt_machine_id = "M1", "M2"
    incoming = _lot(t, f"{prefix}-INCOMING", qty=495, prod_min=495, due=1)
    u_head = _lot(u, f"{prefix}-U1", qty=60, prod_min=60, due=1)
    u_tail = _lot(u, f"{prefix}-U2", qty=60, prod_min=60, due=2)
    for lot in (incoming, u_head, u_tail):
        lot.material_release_day = 1
    u_tail.material_release_day = 2
    segments = [
        _seg(head, "HEAD", "M1", 0, 420, 510, setup=30, prod=60, qty=30),
        _seg(incoming, "INCOMING", "M2", 1, 480, 930, setup=30, prod=420, qty=420),
        _seg(incoming, "INCOMING", "M2", 1, 930, 1005, setup=0, prod=75, qty=75),
        _seg(u_head, "U1", "M1", 1, 600, 690, setup=30, prod=60, qty=60),
        _seg(u_tail, "U2", "M1", 2, 420, 480, setup=0, prod=60, qty=60),
    ]
    lots = [head, incoming, u_head, u_tail]
    data, config = _data([t, u]), _config(oee_m1=0.5)
    data.preserved_lot_proofs = preserved_lot_proofs(segments[:1], lots[:1])
    return segments, lots, data, config


def _source_successor_witness(segments, lots):
    head, incoming, u_head, u_tail = lots
    rebound = [
        copy.deepcopy(head),
        replace(incoming, machine_id="M1", alt_machine_id="M2", prod_min=990),
        replace(u_head, machine_id="M2", alt_machine_id="M1", prod_min=30),
        replace(u_tail, machine_id="M2", alt_machine_id="M1", prod_min=30),
    ]
    result = [copy.deepcopy(segments[0])]
    result.extend([
        _seg(rebound[1], "INCOMING", "M1", 1, 420, 930, setup=0, prod=510, qty=255),
        _seg(rebound[1], "INCOMING", "M1", 1, 930, 1410, setup=0, prod=480, qty=240),
        _seg(rebound[2], "U1", "M2", 1, 420, 480, setup=30, prod=30, qty=60),
        _seg(rebound[3], "U2", "M2", 2, 420, 450, setup=0, prod=30, qty=60),
    ])
    return result, rebound


@pytest.mark.parametrize("prefix", ["P", "UNRELATED"])
def test_source_successor_case_has_a_complete_legal_no_loss_witness(prefix):
    segments, lots, data, config = _source_successor_case(prefix)
    candidate, candidate_lots = _source_successor_witness(segments, lots)
    assert not validate_plan(segments, data, config, lots=lots)
    assert not validate_plan(candidate, data, config, lots=candidate_lots)
    before = plan_facts(segments, lots, data, compute_score(segments, lots, data, config))
    after = plan_facts(candidate, candidate_lots, data,
                       compute_score(candidate, candidate_lots, data, config))
    assert no_loss_verdict(after, before).admissible
    assert physical_setups(candidate).count == 2 < physical_setups(segments).count
    assert tool_transfers(candidate) == 0 < tool_transfers(segments)


@pytest.mark.parametrize("prefix", ["P", "UNRELATED"])
def test_transfer_rebuild_includes_setup_free_successor_of_displaced_run(prefix):
    segments, lots, data, config = _source_successor_case(prefix)
    original = copy.deepcopy((segments, lots, data, config))
    proposals = [item for item in consolidation_proposals(segments, lots, data, config)
                 if isinstance(item, Proposal)]
    legal = [item for item in proposals
             if not validate_plan(item.segments, data, config, lots=item.lots)
             and max(s.day_idx for s in item.segments if s.run_id == "INCOMING") == 1]
    assert legal, "A complete witness exists, but the retained U2 dependency was omitted"
    assert any({s.machine_id for s in item.segments if s.tool_id == "T"} == {"M1"}
               and physical_setups(item.segments).count == 2 for item in legal)
    assert (segments, lots, data, config) == original


def test_complete_improvement_accepts_transfer_without_sacrificing_successor_delivery():
    segments, lots, data, config = _source_successor_case()
    generator = Generator(SCOPE, lambda rows, items: consolidation_proposals(rows, items, data, config))
    improved, improved_lots, report = improve_plan(
        segments, lots, data, config, generators=[generator], time_budget_s=10,
    )
    assert report["moves_accepted"] >= 1, report
    assert tool_transfers(improved) == 0
    assert physical_setups(improved).count == 2
    assert not validate_plan(improved, data, config, lots=improved_lots)
    assert max(s.day_idx for s in improved if s.run_id == "INCOMING") == 1
    assert [s for s in improved if s.run_id == "HEAD"] == segments[:1]
    assert {lot.id: lot.qty for lot in improved_lots} == {lot.id: lot.qty for lot in lots}


def _inserted_successor_case(prefix="P"):
    t = _op(f"{prefix}-T", "T", {0: 30, 1: 60}, machine="M2", alt="M1", rate=60)
    u = _op(f"{prefix}-U", "U", {0: 60, 1: 60}, rate=60)
    head = _lot(t, f"{prefix}-HEAD", qty=30, prod_min=30, due=0)
    head.machine_id, head.alt_machine_id = "M1", "M2"
    incoming = _lot(t, f"{prefix}-INCOMING", qty=60, prod_min=60, due=1)
    incoming.material_release_day = 1
    u_head = _lot(u, f"{prefix}-U1", qty=60, prod_min=60, due=0)
    u_tail = _lot(u, f"{prefix}-U2", qty=60, prod_min=60, due=1)
    u_tail.material_release_day = 1
    segments = [
        _seg(head, "HEAD", "M1", 0, 420, 480, setup=30, prod=30, qty=30),
        _seg(u_head, "U1", "M1", 0, 480, 570, setup=30, prod=60, qty=60),
        _seg(incoming, "INCOMING", "M2", 1, 420, 510, setup=30, prod=60, qty=60),
        _seg(u_tail, "U2", "M1", 1, 660, 720, setup=0, prod=60, qty=60),
    ]
    lots = [head, incoming, u_head, u_tail]
    data, config = _data([t, u]), _config()
    data.preserved_lot_proofs = preserved_lot_proofs(segments[:1], lots[:1])
    return segments, lots, data, config


@pytest.mark.parametrize("prefix", ["P", "UNRELATED"])
def test_inserted_campaign_rebuilds_the_mounting_chain_of_a_fixed_successor(prefix):
    segments, lots, data, config = _inserted_successor_case(prefix)
    original = copy.deepcopy((segments, lots, data, config))
    assert not validate_plan(segments, data, config, lots=lots)
    generator = Generator(SCOPE, lambda rows, items: consolidation_proposals(rows, items, data, config))
    improved, improved_lots, report = improve_plan(
        segments, lots, data, config, generators=[generator], time_budget_s=10,
    )
    assert report["moves_accepted"] >= 1, report
    assert tool_transfers(improved) == 0
    assert physical_setups(improved).count == 2
    assert not validate_plan(improved, data, config, lots=improved_lots)
    assert max(s.day_idx for s in improved) == 1
    assert [s for s in improved if s.run_id == "HEAD"] == segments[:1]
    assert {s.machine_id for s in improved if s.tool_id == "U"} == {"M2"}
    assert (segments, lots, data, config) == original
    again, again_lots, second = improve_plan(
        improved, improved_lots, data, config, generators=[generator], time_budget_s=10,
    )
    assert second["moves_accepted"] == 0
    assert again == improved and again_lots == improved_lots


@pytest.mark.parametrize("kind", ["proof", "anchor"])
def test_mounting_closure_never_releases_a_protected_successor(kind):
    segments, lots, data, config = _inserted_successor_case()
    if kind == "proof":
        data.preserved_lot_proofs.update(preserved_lot_proofs(segments[-1:], lots[-1:]))
    else:
        data.plan_anchors = [PlanAnchor(lots[-1].id, "M1", "2026-09-15T11:00:00+01:00")]
    original = copy.deepcopy((segments, lots, data, config))
    generator = Generator(SCOPE, lambda rows, items: consolidation_proposals(rows, items, data, config))
    improved, improved_lots, report = improve_plan(
        segments, lots, data, config, generators=[generator], time_budget_s=10,
    )
    assert improved == segments and improved_lots == lots
    assert report["moves_accepted"] == 0
    assert (segments, lots, data, config) == original


def test_dependency_group_limit_is_reported_as_incomplete_not_impossible():
    segments, lots, data, config = _source_successor_case()
    for index in range(3, 8):
        tail = replace(lots[-1], id=f"P-U{index}")
        start = 420 + (index - 2) * 60
        segments.append(_seg(tail, f"U{index}", "M1", 2, start, start + 60,
                             setup=0, prod=60, qty=60))
        lots.append(tail)
        data.ops[-1].d[2] += 60
    assert not validate_plan(segments, data, config, lots=lots)
    proposed = list(consolidation_proposals(segments, lots, data, config))
    assert any(isinstance(item, SkippedProposal) and item.scope_limited
               and "setup_dependency_group_size" in item.details for item in proposed)
    generator = Generator(SCOPE, lambda rows, items: consolidation_proposals(rows, items, data, config))
    _, _, report = improve_plan(segments, lots, data, config, generators=[generator])
    assert report["status"] != "completed", report


def test_cancellation_interrupts_dependency_rebuild_without_mutating_source(monkeypatch):
    from threading import Event

    from backend.planning_control import PlanningCancelled, planning_scope
    import backend.scheduler.transfer_consolidation as module

    segments, lots, data, config = _source_successor_case()
    original = copy.deepcopy((segments, lots, data, config))
    cancel = Event()
    allocate = module._schedule_run_earliest

    def once(*args, **kwargs):
        result = allocate(*args, **kwargs)
        cancel.set()
        return result

    monkeypatch.setattr(module, "_schedule_run_earliest", once)
    with pytest.raises(PlanningCancelled), planning_scope(timeout_s=10, cancel_event=cancel):
        list(consolidation_proposals(segments, lots, data, config))
    assert (segments, lots, data, config) == original


def test_dependency_keeps_its_eligible_third_machine_option():
    segments, lots, data, config = _source_successor_case()
    data.ops[-1].alt = "M3"
    for lot in lots[-2:]:
        lot.alt_machine_id = "M3"
    data.machines.append(MachineInfo("M3", "Grandes", 1020))
    config.machines["M3"] = MachineConfig(id="M3", group="Grandes", oee=1)
    assert not validate_plan(segments, data, config, lots=lots)
    generator = Generator(SCOPE, lambda rows, items: consolidation_proposals(rows, items, data, config))
    improved, improved_lots, report = improve_plan(segments, lots, data, config, generators=[generator])
    assert report["moves_accepted"] >= 1, report
    assert {s.machine_id for s in improved if s.tool_id == "U"} == {"M3"}
    assert {s.machine_id for s in improved if s.tool_id == "T"} == {"M1"}
    assert physical_setups(improved).count == 2
    assert not validate_plan(improved, data, config, lots=improved_lots)


@pytest.mark.parametrize("prefix", ["P", "OTHER"])
def test_dependency_rebuild_preserves_both_outputs_of_twin_production(prefix):
    segments, lots, data, config = _source_successor_case(prefix)
    twin = replace(data.ops[0], id=f"{prefix}-TWIN", sku=f"SKU-{prefix}-TWIN",
                   d=list(data.ops[0].d))
    data.ops.append(twin)
    for lot in lots[:2]:
        lot.is_twin = True
        lot.twin_outputs = [(lot.op_id, lot.sku, lot.qty), (twin.id, twin.sku, lot.qty)]
    for segment in segments[:3]:
        segment.twin_outputs = [(lots[0].op_id, lots[0].sku, segment.qty),
                                (twin.id, twin.sku, segment.qty)]
    data.preserved_lot_proofs = preserved_lot_proofs(segments[:1], lots[:1])
    assert not validate_plan(segments, data, config, lots=lots)
    generator = Generator(SCOPE, lambda rows, items: consolidation_proposals(rows, items, data, config))
    improved, improved_lots, report = improve_plan(segments, lots, data, config, generators=[generator])
    assert report["moves_accepted"] >= 1, report
    assert not validate_plan(improved, data, config, lots=improved_lots)
    for lot in lots[:2]:
        output = next(item for item in improved_lots if item.id == lot.id)
        assert output.twin_outputs == lot.twin_outputs
        for op_id, _sku, quantity in lot.twin_outputs:
            assert sum(qty for item in improved if item.lot_id == lot.id
                       for op, _reference, qty in item.twin_outputs or [] if op == op_id) == quantity


def test_transfer_search_version_preserves_exact_snapshot_restore(monkeypatch):
    from backend.plans.restore import restore_plan_into_state
    from backend.plans.serialize import deserialize_snapshot, serialize_snapshot
    import backend.scheduler.transfer_consolidation as module
    from tests.test_plans import _loaded_state

    source, target = _loaded_state(), _loaded_state()
    payload = serialize_snapshot(source)
    expected = deserialize_snapshot(copy.deepcopy(payload))["result"]
    monkeypatch.setattr(module, "TRANSFER_SEARCH_VERSION", module.TRANSFER_SEARCH_VERSION + 1)

    def forbid_recalculation(*_args, **_kwargs):
        pytest.fail("A search correction must not reconstruct the historical snapshot")

    monkeypatch.setattr("backend.cpo.optimizer.optimize", forbid_recalculation)
    restore_plan_into_state(
        {"id": "exact", "name": "Exact", "origin": "isop.xlsx", "payload": payload},
        target, preserve_exact=True, recover_existing=True, approve_exceptions=True,
        prefer_current_config=True,
    )
    assert target.segments == expected.segments and target.lots == expected.lots
