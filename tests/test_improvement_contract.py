"""No-loss automatic improvement contract (plano-melhoria-automatica §4)."""

from __future__ import annotations

import dataclasses

from backend.scheduler.improvement import (
    improvement_key,
    lot_changes,
    no_loss_verdict,
    order_service,
    physical_setups,
    physical_signature,
    plan_facts,
    subcontract_lateness,
    tool_transfers,
)
from backend.scheduler.types import Lot, Segment
from backend.types import ClientDemandEntry, EngineData, EOp, MachineInfo

COMPLETE_SCORE = {"otd": 100.0, "otd_d": 100.0}


def _op(op_id: str, sku: str, demand: dict[int, int], n_days: int = 10, stk: int = 0) -> EOp:
    d = [0] * n_days
    for day, qty in demand.items():
        d[day] = qty
    return EOp(
        id=op_id, sku=sku, client="CLI", designation=sku, m="M1", t="T1",
        pH=100.0, sH=0.5, operators=1, eco_lot=0, alt=None, stk=stk,
        backlog=0, d=d, oee=0.66, wip=0,
    )


def _data(ops: list[EOp], demands: dict[str, list[ClientDemandEntry]] | None = None) -> EngineData:
    return EngineData(
        ops=ops,
        machines=[MachineInfo("M1", "Grandes", 1020), MachineInfo("M2", "Grandes", 1020)],
        twin_groups=[],
        client_demands=demands or {},
        workdays=[f"2026-10-{day + 1:02d}" for day in range(10)],
        n_days=10,
    )


def _entry(sku: str, client: str, day: int, qty: int) -> ClientDemandEntry:
    return ClientDemandEntry(client=client, sku=sku, day_idx=day, date="", order_qty=qty, np_value=-qty)


def _lot(lot_id: str, op_id: str, sku: str, qty: int, edd: int, **extra) -> Lot:
    return Lot(
        id=lot_id, op_id=op_id, tool_id="T1", machine_id="M1", alt_machine_id=None,
        qty=qty, prod_min=60.0, setup_min=30.0, edd=edd, is_twin=False, sku=sku, **extra,
    )


def _seg(lot_id: str, day: int, qty: int, *, machine: str = "M1", start: int = 420,
         end: int = 510, setup: float = 0.0, prod: float = 60.0, run: str | None = None,
         sku: str = "A", tool: str = "T1", twins=None) -> Segment:
    return Segment(
        lot_id=lot_id, run_id=run or f"R-{lot_id}", machine_id=machine, tool_id=tool,
        day_idx=day, start_min=start, end_min=end, shift="A", qty=qty,
        prod_min=prod, setup_min=setup, sku=sku, twin_outputs=twins,
    )


def _facts(segments, lots, data, score=COMPLETE_SCORE):
    return plan_facts(segments, lots, data, score)


# ── Order service ────────────────────────────────────────────────────────


def test_better_aggregate_cannot_hide_individual_order_loss() -> None:
    """Two orders of 100; candidate serves B later although totals rise."""

    data = _data(
        [_op("OP-A", "A", {2: 100, 5: 100})],
        {"A": [_entry("A", "X", 2, 100), _entry("A", "Y", 5, 100)]},
    )
    lot = _lot("L1", "OP-A", "A", 200, 2)
    reference = [_seg("L1", 1, 100, setup=30), _seg("L1", 5, 100)]
    candidate = [_seg("L1", 1, 100, setup=30), _seg("L1", 6, 100)]
    verdict = no_loss_verdict(_facts(candidate, [lot], data), _facts(reference, [lot], data))
    assert not verdict.admissible
    assert any("A/Y dia 5" in reason for reason in verdict.reasons)


def test_earlier_production_is_admissible() -> None:
    data = _data([_op("OP-A", "A", {5: 100})], {"A": [_entry("A", "X", 5, 100)]})
    lot = _lot("L1", "OP-A", "A", 100, 5)
    reference = [_seg("L1", 5, 100, setup=30)]
    candidate = [_seg("L1", 3, 100, setup=30)]
    verdict = no_loss_verdict(_facts(candidate, [lot], data), _facts(reference, [lot], data))
    assert verdict.admissible, verdict.reasons


def test_duplicate_entries_keep_separate_stable_identity() -> None:
    duplicate = [_entry("A", "X", 3, 50), _entry("A", "X", 3, 50)]
    data = _data([_op("OP-A", "A", {3: 100})], {"A": duplicate})
    lot = _lot("L1", "OP-A", "A", 50, 3)
    service = order_service([_seg("L1", 2, 50)], [lot], data)
    keys = sorted(service)
    assert keys == [("A", "X", 3, 50, -50, 0), ("A", "X", 3, 50, -50, 1)]
    assert service[keys[0]].covered_qty == 50
    assert service[keys[1]].covered_qty == 0


def test_demand_without_client_detail_uses_canonical_milestones() -> None:
    data = _data([_op("OP-A", "A", {4: 80})], {})
    lot = _lot("L1", "OP-A", "A", 80, 4)
    on_time = order_service([_seg("L1", 3, 80)], [lot], data)
    late = order_service([_seg("L1", 6, 80)], [lot], data)
    assert list(on_time) == [("A", "CLI", 4, 80, -80, 0)]
    assert on_time[("A", "CLI", 4, 80, -80, 0)].tardiness == 0
    assert late[("A", "CLI", 4, 80, -80, 0)].tardiness == 2
    verdict = no_loss_verdict(
        _facts([_seg("L1", 6, 80)], [lot], data),
        _facts([_seg("L1", 3, 80)], [lot], data),
    )
    assert not verdict.admissible


def test_twin_outputs_serve_each_reference() -> None:
    data = _data(
        [_op("OP-A", "A", {4: 40}), _op("OP-B", "B", {4: 60})],
        {"A": [_entry("A", "X", 4, 40)], "B": [_entry("B", "X", 4, 60)]},
    )
    twins = [("OP-A", "A", 40), ("OP-B", "B", 60)]
    lot = _lot("L1", "OP-A", "A", 60, 4, twin_outputs=twins)
    service = order_service([_seg("L1", 3, 60, twins=twins)], [lot], data)
    assert {key[0]: value.covered_qty for key, value in service.items()} == {"A": 40, "B": 60}


def test_subcontract_dispatch_milestone_checked_separately() -> None:
    data = _data([_op("OP-A", "A", {8: 100})], {"A": [_entry("A", "X", 8, 100)]})
    lot = _lot(
        "L1", "OP-A", "A", 100, 8, is_subcontracted=True,
        latest_subcontract_dispatch_day=4, production_due_day=4, subcontract_lead_time_days=3,
    )
    on_time = [_seg("L1", 3, 100)]
    slipped = [_seg("L1", 5, 100)]
    assert subcontract_lateness(on_time, [lot]) == {("L1", "OP-A"): 0.0}
    assert subcontract_lateness(slipped, [lot]) == {("L1", "OP-A"): 1.0}
    verdict = no_loss_verdict(_facts(slipped, [lot], data), _facts(on_time, [lot], data))
    assert any("subcontratacao" in reason for reason in verdict.reasons)


# ── Physical setups ──────────────────────────────────────────────────────


def test_setup_fragments_across_shift_boundary_count_once() -> None:
    fragments = [
        _seg("L1", 1, 0, start=900, end=930, setup=20, prod=0),
        _seg("L1", 1, 50, start=930, end=990, setup=10, prod=50),
    ]
    assert physical_setups(fragments).count == 1
    assert physical_setups(fragments).minutes == 30.0


def test_reinstallation_on_another_machine_counts() -> None:
    segments = [
        _seg("L1", 1, 50, setup=30, run="R1"),
        _seg("L2", 2, 50, setup=30, machine="M2", run="R2"),
        _seg("L3", 3, 50, setup=30, run="R3"),
    ]
    assert physical_setups(segments).count == 3
    assert tool_transfers(segments) == 2


def test_extra_setup_is_not_a_veto_when_every_order_is_kept() -> None:
    """Decision of 02/10/2026: an earlier plan may add a setup (AGENTS.md §1.5)."""

    data = _data([_op("OP-A", "A", {5: 100})], {"A": [_entry("A", "X", 5, 100)]})
    lot = _lot("L1", "OP-A", "A", 100, 5)
    reference = [_seg("L1", 4, 100, setup=30)]
    candidate = [
        _seg("L1", 2, 50, setup=30, run="R1"),
        _seg("L1", 3, 50, setup=30, machine="M2", run="R2"),
    ]
    after, before = _facts(candidate, [lot], data), _facts(reference, [lot], data)
    assert after.setups.count > before.setups.count
    assert no_loss_verdict(after, before).admissible
    assert _key(after) < _key(before)


def test_extra_setup_still_breaks_an_anticipation_tie() -> None:
    data = _data([_op("OP-A", "A", {5: 100})], {"A": [_entry("A", "X", 5, 100)]})
    lot = _lot("L1", "OP-A", "A", 100, 5)
    one = _facts([_seg("L1", 2, 100, setup=30, end=540)], [lot], data)
    two = _facts([
        _seg("L1", 2, 0, setup=15, prod=0, end=435, run="R1"),
        _seg("L1", 2, 100, setup=15, start=435, end=540, run="R2"),
    ], [lot], data)
    assert one.anticipation == two.anticipation
    assert _key(one) < _key(two)


def test_setup_minutes_use_canonical_precision() -> None:
    assert physical_setups([_seg("L1", 1, 1, setup=30.04)]).minutes == 30.0


# ── Signature and tie-break ──────────────────────────────────────────────


def test_physical_signature_ignores_non_physical_metadata() -> None:
    lot = _lot("L1", "OP-A", "A", 100, 3)
    base = _seg("L1", 2, 100, setup=30)
    explained = dataclasses.replace(base, left_shift_blockers=["maquina ocupada"], edd=9)
    moved = dataclasses.replace(base, start_min=450)
    assert physical_signature([base], [lot]) == physical_signature([explained], [lot])
    assert physical_signature([base], [lot]) != physical_signature([moved], [lot])


def _key(facts, **overrides):
    values = {"transfers": 0, "changed_lots": 0, "displacement_min": 0.0} | overrides
    return improvement_key(facts, **values)


def test_tie_break_order_is_fixed() -> None:
    data = _data([_op("OP-A", "A", {3: 100})], {"A": [_entry("A", "X", 3, 100)]})
    lot = _lot("L1", "OP-A", "A", 100, 3)
    facts = _facts([_seg("L1", 2, 100, setup=30)], [lot], data)
    assert _key(facts, transfers=0, changed_lots=9) < _key(facts, transfers=1, changed_lots=0)
    assert _key(facts, changed_lots=1, displacement_min=999) < _key(
        facts, changed_lots=2, displacement_min=0)


def test_earlier_start_beats_fewer_setups_and_transfers() -> None:
    data = _data([_op("OP-A", "A", {5: 100})], {"A": [_entry("A", "X", 5, 100)]})
    lot = _lot("L1", "OP-A", "A", 100, 5)
    early = _facts([_seg("L1", 2, 100, setup=30)], [lot], data)
    late = _facts([_seg("L1", 3, 100)], [lot], data)
    assert _key(early, transfers=3) < _key(late, transfers=0)


def test_anticipation_ignores_machine_speed_counterexample() -> None:
    """Plan §3: A starts at 100 for 60 min, B at 150 for 30 min.

    The old ``p*S + p^2/2`` proxy scored B lower (4 950 < 7 800) although B
    starts and ends later. The canonical vector prefers A.
    """

    data = _data([_op("OP-A", "A", {5: 100})], {"A": [_entry("A", "X", 5, 100)]})
    lot = _lot("L1", "OP-A", "A", 100, 5)
    a = _facts([_seg("L1", 2, 100, start=520, end=580, prod=60)], [lot], data)
    b = _facts([_seg("L1", 2, 100, machine="M2", start=570, end=600, prod=30)], [lot], data)
    assert _key(a) < _key(b)


def test_more_urgent_lot_is_never_traded_for_a_less_urgent_one() -> None:
    data = _data(
        [_op("OP-A", "A", {3: 100}), _op("OP-B", "B", {8: 100})],
        {"A": [_entry("A", "X", 3, 100)], "B": [_entry("B", "X", 8, 100)]},
    )
    urgent = _lot("L1", "OP-A", "A", 100, 3)
    later = _lot("L2", "OP-B", "B", 100, 8)
    lots = [later, urgent]
    reference = _facts([_seg("L1", 1, 100), _seg("L2", 6, 100, machine="M2", sku="B")],
                       lots, data)
    # L2 gains five days, L1 loses one minute: the urgent lot decides.
    candidate = _facts([_seg("L1", 1, 100, start=421, end=511),
                        _seg("L2", 1, 100, machine="M2", sku="B")], lots, data)
    assert _key(reference) < _key(candidate)


def test_lot_changes_counts_and_displacement() -> None:
    reference = [_seg("L1", 2, 100), _seg("L2", 3, 100)]
    candidate = [_seg("L1", 1, 100), _seg("L2", 3, 100)]
    assert lot_changes(candidate, reference) == (1, 1440.0)


# ── Verified search scopes (replaces warning-text inference) ─────────────


def test_verified_scope_is_bound_to_the_physical_state() -> None:
    from backend.scheduler.improvement import is_verified, record_verified

    lot = _lot("L1", "OP-A", "A", 100, 3)
    segments = [_seg("L1", 2, 100, setup=30)]
    report = record_verified(None, "alternative_machine", segments, [lot])

    assert is_verified(report, "alternative_machine", segments, [lot])
    assert not is_verified(report, "campaign_tail", segments, [lot])
    moved = [dataclasses.replace(segments[0], day_idx=1)]
    assert not is_verified(report, "alternative_machine", moved, [lot])
    assert not is_verified(None, "alternative_machine", segments, [lot])
    # Warning text plays no role.
    assert not is_verified({"warnings": ["Máquinas alternativas: 1"]},
                           "alternative_machine", segments, [lot])


def test_closeout_reruns_alternative_search_only_for_unverified_state(monkeypatch) -> None:
    from backend.config.types import FactoryConfig
    from backend.cpo import optimizer as optimizer_module
    from backend.scheduler import alternative_repair as alternative_module
    from backend.scheduler.alternative_repair import AlternativeRepairResult
    from backend.scheduler.improvement import record_verified
    from backend.scheduler.types import ScheduleResult

    data = _data([_op("OP-A", "A", {5: 100})], {"A": [_entry("A", "X", 5, 100)]})
    config = FactoryConfig()
    lot = _lot("L1", "OP-A", "A", 100, 5)
    segments = [_seg("L1", 3, 100, setup=30)]
    calls: list[int] = []

    def fake_repair(segs, lots, *_args, **_kwargs):
        calls.append(1)
        return AlternativeRepairResult(segments=segs, lots=lots)

    monkeypatch.setattr(alternative_module, "repair_alternative_machine_delivery", fake_repair)
    monkeypatch.setattr(optimizer_module, "normalize_earliest_legal_plan",
                        lambda segs, *_a, **_k: segs)

    def run(report, warnings):
        result = ScheduleResult(segments=list(segments), lots=[lot], score={}, time_ms=0,
                                warnings=list(warnings), operator_alerts=[],
                                improvement_report=report)
        try:
            optimizer_module._normalize_operational_result(result, data, config)
        except Exception:  # noqa: BLE001 - only the repair decision matters here
            pass
        return len(calls)

    verified = record_verified(None, "alternative_machine", segments, [lot])
    assert run(verified, []) == 0
    # A warning claiming a repair does not skip the search any more.
    assert run(None, ["Máquinas alternativas: 1 reparação(ões) de entrega validada(s)."]) == 1


# ── Anticipation tolerance (decision of 05/10/2026) ──────────────────────


def _two_lots(urgent_start: int, next_start: int):
    data = _data(
        [_op("OP-A", "A", {3: 100}), _op("OP-B", "B", {8: 100})],
        {"A": [_entry("A", "X", 3, 100)], "B": [_entry("B", "X", 8, 100)]},
    )
    urgent, later = _lot("L1", "OP-A", "A", 100, 3), _lot("L2", "OP-B", "B", 100, 8)
    day, minute = divmod(next_start, 1440)
    return _facts([
        _seg("L1", 1, 100, start=urgent_start, end=urgent_start + 90),
        _seg("L2", day, 100, machine="M2", sku="B", start=minute, end=minute + 90),
    ], [later, urgent], data)


def test_thirty_minutes_for_an_urgent_lot_do_not_buy_two_days_of_the_next():
    from backend.scheduler.improvement import improvement_better

    reference = _key(_two_lots(480, 2 * 1440 + 420))
    candidate = _key(_two_lots(450, 4 * 1440 + 420))
    assert not improvement_better(candidate, reference)
    assert improvement_better(reference, candidate)


def test_an_hour_for_an_urgent_lot_decides_before_the_next():
    from backend.scheduler.improvement import improvement_better

    reference = _key(_two_lots(540, 2 * 1440 + 420))
    candidate = _key(_two_lots(480, 4 * 1440 + 420))
    assert improvement_better(candidate, reference)


def test_small_gains_still_count_when_nothing_larger_is_at_stake():
    from backend.scheduler.improvement import improvement_better

    reference = _key(_two_lots(480, 2 * 1440 + 420))
    candidate = _key(_two_lots(460, 2 * 1440 + 440))
    assert improvement_better(candidate, reference)


def test_a_chain_of_tolerated_moves_cannot_drift_from_its_reference():
    from backend.scheduler.improvement import improvement_better, regresses_reference

    reference = _key(_two_lots(480, 2 * 1440 + 420))
    step_one = _key(_two_lots(470, 2 * 1440 + 470))
    step_two = _key(_two_lots(460, 2 * 1440 + 520))
    assert improvement_better(step_one, reference)
    assert improvement_better(step_two, step_one)
    assert regresses_reference(step_two, reference)
