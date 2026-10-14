"""A started lot under a calendar edit (AGENTS §2, rule 4; §5).

Production regressions of 11/10/2026 on the active plan (revision 124):

* Adding a holiday was refused with "Plano inválido: 5 conflitos". The rest of
  a started lot is replanned as the same lot, but the lot kept the delivery
  dates it was sized with; a holiday inside a delivery's five-workday window
  (or on the delivery day) moves its material release ``R`` (and ``U``), so
  the lot no longer matched the lots sized from the current inputs. The lot
  keeps its size and deliveries; its dates follow the current calendar.
* A small outage (PRM031, one shift): the quick local repair worked on the
  whole plan and merged two segments of a started lot before today; applying
  it failed with HTTP 500 (``historical_plan_protected``). The repair now only
  touches movable work, and no candidate that changes started production is
  ever offered.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.plans import frozen
from backend.plans.serialize import serialize_snapshot
from backend.scheduler.canonical import result_validation_data, source_contract_violations
from backend.scheduler.improvement import _segment_physical_row
from backend.scheduler.lot_sizing import create_lots, redate_lot_outputs
from backend.scheduler.types import ScheduleResult, Segment
from backend.scheduler.validation import assert_plan_valid
from backend.transform.calendars import apply_calendars
from backend.types import EngineData, EOp, MachineInfo, TwinGroup

START = date(2026, 3, 2)  # a Monday: days 5-6, 12-13 and 19-20 are weekends
N_DAYS = 21
# Tuesday 10/03 (day 8) and Wednesday 11/03 (day 9, a delivery day).
NEW_HOLIDAYS = ["2026-03-10", "2026-03-11"]


def _config(holidays=()) -> FactoryConfig:
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    config.tools = {"T1": {"primary": "M1", "setup_hours": 0.5},
                    "T2": {"primary": "M1", "setup_hours": 0.5}}
    config.holidays = list(holidays)
    return config


def _op(op_id, sku, tool, demand, eco_lot, **extra):
    return EOp(
        id=op_id, sku=sku, client="C", designation="Peça", m="M1", t=tool, pH=100,
        sH=0.5, operators=1, eco_lot=eco_lot, alt=None, stk=0, backlog=0, d=demand,
        oee=1.0, wip=0, **extra,
    )


def _days():
    return [(START + timedelta(days=i)).isoformat() for i in range(N_DAYS)]


def _weekends(days):
    return [i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5]


def _data(config) -> EngineData:
    """OP1 (eco lot 200): L covers days 3 and 9, M covers day 11 (+100 surplus).

    OP2 (another tool) needs 100 on day 2.
    """
    days = _days()
    main = [0] * N_DAYS
    main[3] = main[9] = main[11] = 100
    other = [0] * N_DAYS
    other[2] = 100
    data = EngineData(
        ops=[_op("OP1", "SKU1", "T1", main, 200), _op("OP2", "SKU2", "T2", other, 0)],
        machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[], client_demands={},
        workdays=days, n_days=N_DAYS, holidays=_weekends(days),
    )
    apply_calendars(data, config)
    return data


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
    L's two deliveries were separate productions; replans take it over as
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


# L's first 100 pieces on day 0 (its day-3 delivery), the other tool, then M's
# setup and L's last 100 pieces (day-9 delivery) continuing M's tool on day 4.
SUPPLIED = [(0, 0, 420, 100, 30, 0), (2, 0, 510, 100, 30, 2),
            (1, 4, 420, 200, 30, 1), (0, 4, 570, 100, 0, 1)]
# The same, with L's day-0 production in two contiguous blocks of one run
# (one per delivery): a full-plan repair would merge them.
SPLIT_START = [(0, 0, 420, 50, 30, 0), (0, 0, 480, 50, 0, 0), (2, 0, 510, 100, 30, 2),
               (1, 4, 420, 200, 30, 1), (0, 4, 570, 100, 0, 1)]


def _unmarked(lot):
    """The lot without the version-upgrade marks (``UPGRADED_MATERIAL_KEY``
    and the productions it had, ``UPGRADED_PRODUCTIONS_KEY``)."""
    from backend.scheduler.lot_sizing import UPGRADED_MATERIAL_KEY, UPGRADED_PRODUCTIONS_KEY

    clean = copy.deepcopy(lot)
    for output in clean.output_milestones:
        output.pop(UPGRADED_MATERIAL_KEY, None)
        output.pop(UPGRADED_PRODUCTIONS_KEY, None)
    return clean


def _delivery(lot, customer_day):
    return next(o for o in lot.output_milestones if o["customer_delivery_day"] == customer_day)


# ── the dates of a sized lot follow the current calendar ──────────────────


def _twin_data(a_demand, b_demand, holidays):
    days = [(date(2026, 10, 12) + timedelta(days=i)).isoformat() for i in range(40)]

    def op(op_id, sku, demand_by_day):
        demand = [0] * 40
        for day, qty in demand_by_day.items():
            demand[day] = qty
        return EOp(id=op_id, sku=sku, client="C", designation=sku, m="M1", t="TT",
                   pH=1500, sH=0.5, operators=1, eco_lot=3000, alt=None, stk=0, backlog=0,
                   d=demand, oee=1.0, wip=0)

    return EngineData(
        ops=[op("TT_M1_A", "A", a_demand), op("TT_M1_B", "B", b_demand)],
        machines=[MachineInfo("M1", "Grandes", 1020)],
        twin_groups=[TwinGroup("TT", "M1", "TT_M1_A", "TT_M1_B", "A", "B", 3000, 3000)],
        client_demands={}, workdays=days, n_days=40,
        holidays=sorted(set(_weekends(days)) | set(holidays)),
    )


def _solo_data(holidays):
    days = _days()
    main = [0] * N_DAYS
    main[3] = main[9] = main[11] = 100
    subcontracted = [0] * N_DAYS
    subcontracted[10] = subcontracted[16] = 80
    return EngineData(
        ops=[_op("OP1", "SKU1", "T1", main, 200),
             _op("OP3", "SKU3", "T2", subcontracted, 200, subcontract_company_id="SUB",
                 subcontract_lead_time_days=2, subcontract_buffer_days=1)],
        machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[], client_demands={},
        workdays=days, n_days=N_DAYS, holidays=sorted(set(_weekends(days)) | set(holidays)),
    )


CASES = {
    # Carry-forward over three deliveries, economic surplus, subcontracting.
    "solo": (_solo_data, (), (8, 9)),
    # Twin cycle per delivery: paired outputs share R_ciclo; carried deliveries
    # keep their own R; economic surplus on both sides.
    "twin_carry_forward": (
        lambda holidays: _twin_data({14: 1000, 28: 1500}, {15: 2500, 30: 400}, holidays),
        (), (10, 28),
    ),
    # A side without nearby demand: co-produced stock dated by the other side.
    "twin_coproduced": (
        lambda holidays: _twin_data({14: 1000, 28: 1500}, {}, holidays), (), (10, 14),
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_redated_lot_is_the_lot_sized_with_the_current_calendar(case):
    build, before, after = CASES[case]
    old, new = build(before), build(after)
    config = FactoryConfig()
    sized_now = {lot.id: lot for lot in create_lots(new, config)}
    changed = 0
    for lot in create_lots(old, config):
        # The same calendar: nothing changes.
        assert redate_lot_outputs(lot, old) == lot
        redated = redate_lot_outputs(lot, new)
        # Independent of the started lot's history: exactly what lot sizing
        # derives today for the same deliveries and quantities.
        assert redated == sized_now[lot.id]
        assert [(o["op_id"], o["qty"], o["customer_delivery_day"]) for o in redated.output_milestones] == [
            (o["op_id"], o["qty"], o["customer_delivery_day"]) for o in lot.output_milestones
        ]
        changed += redated.output_milestones != lot.output_milestones
    assert changed, "the holidays must move at least one delivery date"


def test_redating_keeps_a_lot_whose_operation_left_the_scenario():
    config = FactoryConfig()
    data = _solo_data(())
    lot = create_lots(data, config)[0]
    data.ops = data.ops[1:]
    assert redate_lot_outputs(lot, data) is lot


# ── a holiday added after a lot started (production bug of 11/10/2026) ───


def test_started_lot_rest_is_planned_with_the_new_material_windows():
    config = _config()
    baseline, (lot_l, _lot_m, lot_x) = _baseline(_data(config), config, SUPPLIED)
    config = _config(NEW_HOLIDAYS)
    data = _data(config)
    before = _delivery(lot_l, 9)
    assert (before["material_release_day"], before["production_due_day"]) == (2, 9)

    protected = frozen._protected_plan(baseline, 1, data, config)

    (original, rest), = protected.partial
    # Never re-sized: same lot, same deliveries and quantities ...
    assert (original.id, original.qty) == (lot_l.id, lot_l.qty)
    assert [(o["qty"], o["customer_delivery_day"]) for o in original.output_milestones] == [
        (o["qty"], o["customer_delivery_day"]) for o in lot_l.output_milestones
    ]
    # ... taken over as version 3 and dated by the current calendar: the
    # delivery's own R moves back over the new holiday, U to the workday
    # before the delivery holiday; the whole lot keeps the lot R.
    # (Version 3, the rounded sizing of its time: never the current one.)
    assert _unmarked(original) == {
        lot.id: lot for lot in create_lots(data, config, quantity_material=3)
    }[lot_l.id]
    current = _delivery(original, 9)
    assert (current["delivery_material_release_day"], current["production_due_day"]) == (1, 7)
    assert current["material_release_day"] == original.material_release_day < 1
    assert [(o["qty"], o["material_release_day"], o["production_due_day"])
            for o in rest.output_milestones] == [(100, original.material_release_day, 7)]
    assert rest.edd == 7
    # The started production itself is unchanged.
    assert [(s.lot_id, s.day_idx) for s in protected.segments] == [
        (lot_l.id, 0), (lot_x.id, 0),
    ]


def test_holiday_added_after_a_lot_started_gives_a_valid_plan(monkeypatch):
    """Before the fix: PlanValidationError (``source_contract`` on the
    deliveries of the started lot), i.e. HTTP 400 «Plano inválido»."""
    config = _config()
    baseline, (lot_l, lot_m, lot_x) = _baseline(_data(config), config, SUPPLIED)
    config = _config(NEW_HOLIDAYS)
    data = _data(config)
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_: 1)

    result = frozen.optimize_preserving_started_lots(data, config, baseline, mode="quick")

    view = result_validation_data(data, result)
    assert_plan_valid(result.segments, view, config, lots=result.lots)
    assert source_contract_violations(result.segments, result.lots, view, config) == []
    sized_now = {lot.id: lot for lot in create_lots(data, config, quantity_material=3)}
    by_id = {lot.id: lot for lot in result.lots}
    # Lot sizing ran once and nothing was re-sized (needs below the economic
    # lot: the same sizes under both rules); the started lot, taken over as
    # version 3, carries the dates of the current calendar.
    assert {lot_id: lot.qty for lot_id, lot in by_id.items()} == {
        lot.id: lot.qty for lot in baseline.lots
    }
    assert _unmarked(by_id[lot_l.id]) == sized_now[lot_l.id]
    # The started production is exactly as before; nothing runs on a holiday.
    rows = {_segment_physical_row(s) for s in result.segments}
    assert {_segment_physical_row(baseline.segments[i]) for i in (0, 1)} <= rows
    assert all(s.day_idx not in (8, 9) for s in result.segments)
    produced = {lot_id: sum(s.qty for s in result.segments if s.lot_id == lot_id)
                for lot_id in by_id}
    assert produced == {lot_l.id: 200, lot_m.id: 200, lot_x.id: 100}
    # Every segment of the started lot shows the lot's current dates.
    assert all(s.edd == by_id[lot_l.id].edd
               and s.output_milestones == by_id[lot_l.id].output_milestones
               for s in result.segments if s.lot_id == lot_l.id)


# ── the quick repair of a small outage (production bug of 11/10/2026) ─────


def _outage_job(monkeypatch, baseline, config, data, *, constructor=None, repair=None,
                outage_day="2026-03-06", prefer_unchanged_baseline=True):
    """A replan job for an outage of M1, shift A, on ``outage_day``
    (default: Friday 06/03, day 4, which has production)."""
    from backend.replan import jobs

    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_a, **_k: 1)
    monkeypatch.setattr(jobs, "_current_planning_day", lambda *_a, **_k: 1)
    if constructor is not None:
        monkeypatch.setattr(jobs, "optimize_preserving_started_lots", constructor)
    if repair is not None:
        monkeypatch.setattr(jobs.ReplanJobManager, "_local_calendar_repair",
                            staticmethod(repair))
    from backend.copilot.state import CopilotState

    monkeypatch.setattr(CopilotState, "_refresh_analytics", lambda _self: None)
    source = CopilotState(engine_data=copy.deepcopy(data), config=copy.deepcopy(config),
                          dataset_info={"id": "dataset", "filename": "isop.xlsx"})
    source.update_schedule(baseline)
    snapshot = serialize_snapshot(source)
    outage = copy.deepcopy(config)
    outage.machine_unavailability = [{
        "id": "stop", "resource": "M1", "start_at": f"{outage_day}T07:00",
        "end_at": f"{outage_day}T15:30", "category": "Avaria", "reason": "Teste",
    }]
    store = jobs.ReplanJobStore(":memory:")
    manager = jobs.ReplanJobManager(store)
    job = store.create("Indisponibilidades alteradas", "dataset", 0)
    try:
        manager._run(
            job["id"], copy.deepcopy(data), outage, "dataset", 0,
            "Indisponibilidades alteradas", {"id": "dataset", "filename": "isop.xlsx"},
            baseline_snapshot=snapshot, prefer_unchanged_baseline=prefer_unchanged_baseline,
        )
    finally:
        manager.executor.shutdown(wait=True)
    return store.get(job["id"]), store.get_candidate(job["id"]), snapshot


def _started_rows(segments, lot_ids):
    return sorted(_segment_physical_row(s) for s in segments
                  if s.lot_id in lot_ids and s.day_idx < 1)


def test_quick_repair_never_changes_started_production(monkeypatch):
    """Day 4 (a Friday here) loses its shift A. The quick repair moves the
    work of day 4 and leaves L's two day-0 blocks exactly as they are; the
    old full-plan repair merged them (history changed: HTTP 500 on apply)."""
    from backend.plans.serialize import deserialize_snapshot

    config = _config()
    data = _data(config)
    baseline, (lot_l, _lot_m, lot_x) = _baseline(data, config, SPLIT_START)

    def no_constructor(*_args, **_kwargs):
        raise AssertionError("the quick repair must give this plan")

    job, candidate, snapshot = _outage_job(
        monkeypatch, baseline, config, data, constructor=no_constructor,
    )

    assert job["status"] == "ready", (job["message"], job.get("error"))
    assert job["result"]["selected_source"] == "repaired_baseline_calendar"
    assert frozen.historical_schedule_changes(snapshot, candidate, today=data.workdays[1]) == []
    repaired = deserialize_snapshot(candidate)["result"]
    started = {lot_l.id, lot_x.id}
    assert _started_rows(repaired.segments, started) == _started_rows(baseline.segments, started)
    assert {lot.id: lot.qty for lot in repaired.lots} == {lot.id: lot.qty for lot in baseline.lots}
    assert all(not (s.day_idx == 4 and s.start_min < 930) for s in repaired.segments
               if s.end_min > s.start_min)


def test_quick_repair_changing_started_production_falls_back_to_the_constructor(monkeypatch):
    """A repair candidate the commit would refuse is never offered: the
    complete constructor plans instead."""
    from backend.replan import jobs

    config = _config()
    data = _data(config)
    baseline, (lot_l, _lot_m, _lot_x) = _baseline(data, config, SPLIT_START)
    real_repair = jobs.ReplanJobManager._local_calendar_repair
    calls = []

    def merging_repair(*args):
        candidate, moves = real_repair(*args)
        first, second = sorted(
            (s for s in candidate.segments if s.lot_id == lot_l.id and s.day_idx == 0),
            key=lambda s: s.start_min,
        )
        # Physically the same work, valid, but the started blocks are merged.
        first.end_min, first.qty, first.prod_min = (
            second.end_min, first.qty + second.qty, first.prod_min + second.prod_min,
        )
        candidate.segments.remove(second)
        # Judged with its history boundary: L's started part is history.
        assert_plan_valid(candidate.segments, result_validation_data(data, candidate), config,
                          lots=candidate.lots)
        calls.append("repair")
        return candidate, moves

    def constructor(*args, **kwargs):
        calls.append("constructor")
        return frozen.optimize_preserving_started_lots(*args, **kwargs)

    job, candidate, snapshot = _outage_job(
        monkeypatch, baseline, config, data, constructor=constructor, repair=merging_repair,
    )

    assert calls == ["repair", "constructor"]
    assert job["status"] == "ready", (job["message"], job.get("error"))
    assert job["result"]["selected_source"] == "optimized"
    assert frozen.historical_schedule_changes(snapshot, candidate, today=data.workdays[1]) == []


def _priority_data(config) -> EngineData:
    """L (OP1, eco lot 250): 100 due on day 3, 150 on day 11.

    K (OP2, another tool, eco lot 200): 100 due on day 4, 100 on day 11.
    The two deliveries of day 11 are released on day 4.
    """
    days = _days()
    first, second = [0] * N_DAYS, [0] * N_DAYS
    first[3], first[11] = 100, 150
    second[4], second[11] = 100, 100
    data = EngineData(
        ops=[_op("OP1", "SKU1", "T1", first, 250), _op("OP2", "SKU2", "T2", second, 200)],
        machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[], client_demands={},
        workdays=days, n_days=N_DAYS, holidays=_weekends(days),
    )
    apply_calendars(data, config)
    return data


def test_quick_repair_keeps_the_rest_of_a_started_lot_where_the_plan_ranks_it(monkeypatch):
    """Golden F3_outage_small (revision 124, PRM019 day 40), reduced.

    On day 4, L's run makes its delivery of day 11 (150 pieces), then K's run
    makes K's delivery of day 11 (100 pieces): per delivery L's is the more
    urgent (same day, larger quantity, AGENTS §1.3), as the builder placed
    it. The rest of the started lot L is due on day 11 at lot level (its
    first remaining delivery) and K on day 4 (a delivery made on day 1), so
    a lot-level reordering of the residual put K's run first and L's 90 min
    later; the complete plan ranks L (due on day 3) first. An outage
    elsewhere (shift A of day 1) must not re-sequence them.
    """
    from backend.plans.serialize import deserialize_snapshot
    from backend.scheduler.policy import anticipation_order

    config = _config()
    data = _priority_data(config)
    # Saved under the per-delivery contract (version 2): L is two productions.
    lots = {lot.op_id: lot for lot in create_lots(data, config, quantity_material=2)}
    lot_l, lot_k = lots["OP1"], lots["OP2"]
    assert (lot_l.qty, lot_k.qty) == (250, 200)
    blocks = [  # lot, run, day, start, qty, setup
        (lot_l, 0, 0, 420, 100, 30), (lot_k, 0, 1, 420, 100, 30),
        (lot_l, 1, 4, 420, 150, 30), (lot_k, 1, 4, 540, 100, 30),
    ]
    baseline = ScheduleResult(
        segments=[_segment(lot, day, start, qty, setup, f"quantity:{lot.id}:{run}")
                  for lot, run, day, start, qty, setup in blocks],
        lots=list(lots.values()), score={}, time_ms=0, warnings=[], operator_alerts=[],
    )
    assert_plan_valid(baseline.segments, data, config, lots=baseline.lots)
    # Per delivery, L's day-11 delivery ranks before K's.
    order = [element for element, _lot in anticipation_order(baseline.lots).elements]
    assert order.index(f"{lot_l.id}#1") < order.index(f"{lot_k.id}#1")
    # The rest of L, alone, is ranked by its first remaining delivery.
    (_original, rest), = frozen._protected_plan(baseline, 1, data, config).partial
    assert (rest.edd, lot_l.edd, lot_k.edd) == (11, 3, 4)

    def no_constructor(*_args, **_kwargs):
        raise AssertionError("the quick repair must give this plan")

    job, candidate, snapshot = _outage_job(
        monkeypatch, baseline, config, data, constructor=no_constructor,
        outage_day="2026-03-03",
    )

    assert job["status"] == "ready", (job["message"], job.get("error"))
    assert job["result"]["selected_source"] == "repaired_baseline_calendar"
    assert frozen.historical_schedule_changes(snapshot, candidate, today=data.workdays[1]) == []
    repaired = deserialize_snapshot(candidate)["result"]
    produced = sorted((s.day_idx, s.start_min, s.lot_id) for s in repaired.segments
                      if s.prod_min > 0)
    # K's run of day 1 left shift A; day 4 keeps L's run before K's.
    assert [(day, lot_id) for day, start, lot_id in produced if day == 1] == [(1, lot_k.id)]
    assert all(start >= 930 for day, start, _lot in produced if day == 1)
    assert [(start, lot_id) for day, start, lot_id in produced if day == 4] == [
        (420, lot_l.id), (540, lot_k.id),
    ]


def test_no_candidate_that_changes_started_production_is_offered(monkeypatch):
    """Last line of defence: a complete candidate that changes started
    production fails the job with a plain message instead of being offered
    (the commit would refuse it)."""
    from backend.replan import jobs

    config = _config()
    data = _data(config)
    baseline, (_lot_l, _lot_m, lot_x) = _baseline(data, config, SPLIT_START)

    def history_changing_constructor(engine_data, config, history, **_kwargs):
        candidate = copy.deepcopy(history)
        started = next(s for s in candidate.segments if s.lot_id == lot_x.id)
        started.start_min += 1  # still valid, but started production moved
        started.end_min += 1
        return candidate

    # An outage on a day without production: the constructor replans.
    job, candidate, _snapshot = _outage_job(
        monkeypatch, baseline, config, data, constructor=history_changing_constructor,
        outage_day="2026-03-12", prefer_unchanged_baseline=False,
    )

    assert job["status"] == "failed"
    # Its own code, not "blocked" (physical conflicts): the screen must not
    # say the plan has conflicts.
    assert job["code"] == "history_protected"
    assert job["message"] == jobs.FAILURE_TEXTS["history_protected"][0]
    assert job["error"] == jobs.PROTECTED_HISTORY_TEXT
    assert "não foram alterados" in job["error"]
    assert "conflitos" not in job["message"] + job["error"]
    assert candidate is None


# ── revision 124 (private fixture): the production cases ─────────────────


@pytest.mark.needs_private
@pytest.mark.parametrize("holiday", ["2026-10-23", "2026-11-20"])
def test_rev124_started_lots_match_the_lots_sized_after_a_new_holiday(holiday):
    """The deliveries of every started lot whose rest is replanned agree with
    the lots sized from the inputs with the new holiday (5 lots for 23/10,
    1 for 20/11 failed before the fix, twins and single lots alike)."""
    from backend.plans.serialize import deserialize_snapshot
    from tests.snapshot_fixture import load_payload

    manifest, payload = load_payload("rev124")
    restored = deserialize_snapshot(copy.deepcopy(payload))
    config, data, baseline = restored["config"], restored["engine_data"], restored["result"]
    config.holidays = sorted({*config.holidays, holiday})
    apply_calendars(data, config)

    protected = frozen._protected_plan(baseline, manifest["freeze_day"], data, config)
    assert protected.partial
    complete = copy.deepcopy(baseline)
    residual_segments, residual_lots = frozen._residual_of(complete, protected)
    complete.segments, complete.lots = residual_segments, residual_lots
    complete = frozen._splice_frozen_started_lots(
        complete, protected.segments, protected.lots, protected.partial,
    )
    partial_ids = {original.id for original, _rest in protected.partial}
    view = result_validation_data(data, complete)
    violations = [
        violation for violation in source_contract_violations(
            complete.segments, complete.lots, view, config,
        )
        if violation["lot_id"] in partial_ids
    ]
    assert violations == []
    moved = [original for original, _rest in protected.partial
             if original != next(lot for lot in baseline.lots if lot.id == original.id)]
    assert moved, "the holiday must move a delivery date of a started lot"
    assert all(original.qty == next(lot.qty for lot in baseline.lots if lot.id == original.id)
               for original, _rest in protected.partial)


@pytest.mark.needs_private
@pytest.mark.slow
def test_rev124_holiday_write_gives_an_activatable_plan(monkeypatch):
    """The holiday of 23/10 on revision 124 (the refused production write),
    end to end on the recalculation path: valid, activatable, history kept."""
    from backend.plans.serialize import deserialize_snapshot
    from backend.plans.store import _assert_activatable_payload
    from backend.replan.jobs import _result_snapshot
    from backend.scheduler.canonical import result_validation_data as validation_view
    from tests.snapshot_fixture import load_payload, pin_factory_clock
    from tests.test_eco_lot_minimum import assert_replan_sizes

    manifest, payload = load_payload("rev124")
    freeze_day = manifest["freeze_day"]
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_a, **_k: freeze_day)
    pin_factory_clock(monkeypatch, payload["engine_data"]["workdays"][freeze_day])
    restored = deserialize_snapshot(copy.deepcopy(payload))
    config, data, baseline = restored["config"], restored["engine_data"], restored["result"]
    config.holidays = sorted({*config.holidays, "2026-10-23"})
    apply_calendars(data, config)

    result = frozen.optimize_preserving_started_lots(data, config, baseline, mode="quick")

    assert_plan_valid(result.segments, validation_view(data, result), config, lots=result.lots)
    candidate = _result_snapshot(
        data, config, result, plan_revision=payload["plan_revision"] + 1,
        dataset_info=payload["dataset_info"], mutations=[],
    )
    _assert_activatable_payload(candidate)
    assert frozen.historical_schedule_changes(payload, candidate, today=manifest["as_of"]) == []
    assert_replan_sizes(payload, candidate, freeze_day)
    holiday_day = data.workdays.index("2026-10-23")
    assert not any(s.day_idx == holiday_day and s.end_min > s.start_min
                   for s in result.segments)


@pytest.mark.needs_private
@pytest.mark.slow
def test_rev124_small_outage_quick_repair_keeps_started_production(monkeypatch):
    """PRM031 down on 19/10, shift A, with time for the quick repair to
    finish: the candidate is ready, activatable and keeps started history."""
    from backend.config.unavailability import add_unavailability_entry
    from backend.plans.store import _assert_activatable_payload
    from backend.replan import jobs
    from tests.snapshot_fixture import load_payload, pin_factory_clock
    from backend.plans.serialize import deserialize_snapshot

    manifest, payload = load_payload("rev124")
    freeze_day = manifest["freeze_day"]
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_a, **_k: freeze_day)
    monkeypatch.setattr(jobs, "_current_planning_day", lambda *_a, **_k: freeze_day)
    pin_factory_clock(monkeypatch, payload["engine_data"]["workdays"][freeze_day])
    # A generous budget: the quick repair always finishes (the outcome that
    # failed in production when the machine was not busy).
    monkeypatch.setattr(jobs, "REPLAN_TOTAL_BUDGET_S", 600.0)
    restored = deserialize_snapshot(copy.deepcopy(payload))
    config, engine_data = restored["config"], restored["engine_data"]
    add_unavailability_entry(config, engine_data, {
        "kind": "machine", "resource": "PRM031", "start_at": "2026-10-19T07:00",
        "end_at": "2026-10-19T15:30", "category": "Avaria", "reason": "Regressão rev124",
    })

    def no_constructor(*_args, **_kwargs):
        raise AssertionError("the quick repair must finish with this budget")

    monkeypatch.setattr(jobs, "optimize_preserving_started_lots", no_constructor)
    store = jobs.ReplanJobStore(":memory:")
    manager = jobs.ReplanJobManager(store)
    dataset = payload["dataset_info"]
    job = store.create("Indisponibilidades alteradas", dataset["id"], payload["plan_revision"])
    try:
        manager._run(
            job["id"], engine_data, config, dataset["id"], payload["plan_revision"],
            "Indisponibilidades alteradas", dataset, baseline_snapshot=payload,
            prefer_unchanged_baseline=True,
        )
    finally:
        manager.executor.shutdown(wait=True)

    final = store.get(job["id"])
    assert final["status"] == "ready", (final["message"], final.get("error"))
    assert final["result"]["selected_source"] == "repaired_baseline_calendar"
    candidate = store.get_candidate(job["id"])
    _assert_activatable_payload(candidate)
    assert frozen.historical_schedule_changes(
        payload, candidate, today=manifest["as_of"],
    ) == []
    assert {lot["id"]: lot["qty"] for lot in candidate["lots"]} == {
        lot["id"]: lot["qty"] for lot in payload["lots"]
    }
    day = engine_data.workdays.index("2026-10-19")
    assert not any(
        s.machine_id == "PRM031" and s.day_idx == day and s.start_min < 930
        and s.end_min > s.start_min
        for s in deserialize_snapshot(candidate)["result"].segments
    )
