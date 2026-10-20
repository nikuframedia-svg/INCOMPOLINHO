"""«Mover lote» to a time of today already gone records what ran (decisão do Luís, 20/10/2026).

Incompol, 20/10/2026: the plan had CF589 on PRM043 from 07:00 and JTE001
from 18:35; the production manager ran JTE001 in the morning. At 11:49 the
planner moved JTE001 to 08:00 and was refused («esse momento já passou»).
Now that same move means «this ran from 08:00»: what the plan had on the
machine since its setup did not run and is replanned after now; the record
survives «Recalcular plano» (only a new ISOP replaces it); «Desfazer» takes
it back the same day; earlier days, a setup on the day before, a time before
the material (R) or an unavailability are still refused. Crew and operators
are not judged before now: it happened.
"""

from __future__ import annotations

import copy
from dataclasses import asdict
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.plans import frozen
from backend.plans.manual_edits import EXECUTED, executed_lot_ids, release_manual_anchors
from backend.plans.manual_move import ManualMoveError, move_lot
from backend.scheduler.canonical import result_validation_data
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.types import ScheduleResult, Segment
from backend.scheduler.validation import assert_plan_valid
from backend.types import EngineData, EOp, MachineInfo, PlanAnchor
from tests.test_now_boundary import START, _at

TODAY = 1  # day 1 (03/03) is "today"; day 0 is yesterday


def _config(*, two_machines: bool = False) -> FactoryConfig:
    machines = {"M1": MachineConfig("M1", "Grandes")}
    if two_machines:
        machines["M2"] = MachineConfig("M2", "Grandes")
    config = FactoryConfig(machines=machines)
    config.tools = {
        tool: {"primary": "M1", "setup_hours": 0.5} for tool in ("T1", "T2", "T3")
    }
    config.tools["T4"] = {"primary": "M2", "setup_hours": 0.5}
    return config


def _op(op_id, tool, due_day, *, machine="M1", alt=None):
    demand = [0] * 14
    demand[due_day] = 200
    return EOp(
        id=op_id, sku=f"SKU_{op_id}", client="C", designation="Peça", m=machine, t=tool,
        pH=100, sH=0.5, operators=1, eco_lot=200, alt=alt, stk=0, backlog=0, d=demand,
        oee=1.0, wip=0,
    )


def _data(ops, *, two_machines=False) -> EngineData:
    days = [(START + timedelta(days=i)).isoformat() for i in range(14)]
    machines = [MachineInfo("M1", "Grandes", 1020)]
    if two_machines:
        machines.append(MachineInfo("M2", "Grandes", 1020))
    return EngineData(
        ops=ops, machines=machines, twin_groups=[], client_demands={}, workdays=days,
        n_days=len(days),
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )


def _plan(data, config, blocks_by_op):
    """``blocks_by_op``: op id -> [(day, start, qty, setup)], one run per lot."""
    lots = {lot.op_id: lot for lot in create_lots(data, config)}
    segments = []
    for op_id, blocks in blocks_by_op.items():
        lot = lots[op_id]
        for day, start, qty, setup in blocks:
            prod = lot.prod_min * qty / lot.qty
            segments.append(Segment(
                lot.id, f"quantity:{lot.id}:0", lot.machine_id, lot.tool_id, day, start,
                start + int(setup + prod), "A" if start < 930 else "B", qty, prod, setup,
                sku=lot.sku, lot_qty=lot.qty,
                output_milestones=copy.deepcopy(lot.output_milestones),
            ))
    return ScheduleResult(
        segments=segments, lots=list(lots.values()), score={}, time_ms=0, warnings=[],
        operator_alerts=[],
    ), lots


def _snapshot(segments, lots, data, *, anchors=(), boundary=None) -> dict:
    return {
        "dataset_info": {"id": "ds"},
        "engine_data": {
            "workdays": list(data.workdays),
            "plan_anchors": [asdict(anchor) for anchor in anchors],
            **({"history_boundary": list(boundary)} if boundary else {}),
        },
        "config": {"timezone": "Europe/Lisbon"},
        "segments": [asdict(segment) for segment in segments],
        "lots": [asdict(lot) for lot in lots],
    }


def _shape(segments, lot_id):
    return sorted(
        (s.day_idx, s.machine_id, s.start_min, s.end_min, s.qty, s.setup_min)
        for s in segments if s.lot_id == lot_id
    )


def _record(move, data):
    """The anchor ``move-apply`` writes for this move."""
    when = f"{data.workdays[move.target_day]}T{move.target_start_min // 60:02d}:" \
           f"{move.target_start_min % 60:02d}"
    return PlanAnchor(move.lot_id, move.target_machine, when, kind=EXECUTED)


def _move(baseline, data, config, lot_id, day, minute, now, machine=None):
    return move_lot(
        baseline.segments, baseline.lots, {}, data, config, lot_id=lot_id, target_day=day,
        target_machine=machine, target_start_min=minute, now=now,
    )


@pytest.fixture
def morning():
    """M1 today: OP1 08:00–10:30 (setup 30, 200 pieces), OP2 planned on day 3."""
    config = _config()
    data = _data([_op("OP1", "T1", 4), _op("OP2", "T2", 6)])
    baseline, lots = _plan(data, config, {
        "OP1": [(TODAY, 480, 200, 30)], "OP2": [(3, 420, 200, 30)],
    })
    return SimpleNamespace(config=config, data=data, baseline=baseline, lots=lots)


def test_record_cuts_the_displaced_lot_at_the_setup_and_replans_its_rest(morning):
    eleven = _at(TODAY, 660)
    op1, op2 = morning.lots["OP1"].id, morning.lots["OP2"].id

    move = _move(morning.baseline, morning.data, morning.config, op2, TODAY, 630, eleven)

    assert move.executed and move.history_boundary == [TODAY, 660]
    # OP2 ran from 10:30 with its setup from 10:00; OP1 ran until 10:00.
    assert _shape(move.segments, op2) == [(TODAY, "M1", 600.0, 750, 200, 30.0)]
    first, *rest = _shape(move.segments, op1)
    assert first == (TODAY, "M1", 480, 600, 150, 30)
    assert sum(item[4] for item in rest) == 50
    assert min((item[0], item[2]) for item in rest) >= (TODAY, 660)
    assert move.notice == (
        "Hora já passada: fica registado que a Referência SKU_OP2 · T2 (M1) correu desde "
        "as 10:30 (afinação desde as 10:00); a Referência SKU_OP1 · T1 (M1) fica feita até "
        "às 10:00 (150 peças) e o resto é replaneado a partir de agora (pronta a 03/03 às 13:30)."
    )
    view = result_validation_data(morning.data, SimpleNamespace(
        preserved_lot_proofs=None, history_boundary=move.history_boundary,
    ))
    assert_plan_valid(move.segments, view, morning.config, lots=move.lots)
    # The commit guard accepts exactly this record, at the move's instant.
    before = _snapshot(morning.baseline.segments, morning.baseline.lots, morning.data)
    after = _snapshot(
        move.segments, move.lots, morning.data,
        anchors=[_record(move, morning.data)], boundary=move.history_boundary,
    )
    assert frozen.historical_schedule_changes(before, after, now=eleven) == []


def test_record_over_a_lot_that_made_nothing_yet_replans_it_whole(morning):
    eleven = _at(TODAY, 660)
    op1, op2 = morning.lots["OP1"].id, morning.lots["OP2"].id

    move = _move(morning.baseline, morning.data, morning.config, op2, TODAY, 510, eleven)

    assert _shape(move.segments, op2)[0][2:4] == (480.0, 630)
    assert all((day, start) >= (TODAY, 660) for day, _m, start, *_ in _shape(move.segments, op1))
    assert sum(item[4] for item in _shape(move.segments, op1)) == 200
    assert "a Referência SKU_OP1 · T1 (M1) fica por fazer e é replaneada a partir de agora" in (
        move.notice
    )


def _guard_case(morning):
    eleven = _at(TODAY, 660)
    move = _move(
        morning.baseline, morning.data, morning.config, morning.lots["OP2"].id, TODAY, 630,
        eleven,
    )
    before = _snapshot(morning.baseline.segments, morning.baseline.lots, morning.data)
    return move, before, eleven


def test_guard_exception_is_only_the_record(morning):
    move, before, eleven = _guard_case(morning)
    op1, op2 = morning.lots["OP1"].id, morning.lots["OP2"].id
    record = _record(move, morning.data)

    def after(segments=None, anchors=(record,)):
        return _snapshot(
            segments if segments is not None else move.segments, move.lots, morning.data,
            anchors=anchors, boundary=move.history_boundary,
        )

    def changed(segments):
        return frozen.historical_schedule_changes(before, after(segments), now=eleven)

    # Without the record (an ordinary pin) the morning cannot change.
    assert set(frozen.historical_schedule_changes(
        before, after(anchors=(replace_kind(record, ""),)), now=eleven,
    )) == {op1, op2}
    # Two records at once: no exception.
    other = PlanAnchor(op1, "M1", f"{morning.data.workdays[TODAY]}T08:00", kind=EXECUTED)
    assert frozen.historical_schedule_changes(
        before, after(anchors=(record, other)), now=eleven,
    )
    # The displaced lot cut at another minute.
    wrong = copy.deepcopy(move.segments)
    cut = next(s for s in wrong if s.lot_id == op1 and s.day_idx == TODAY and s.start_min == 480)
    cut.end_min, cut.qty = 590, 140
    assert op1 in changed(wrong)
    # The recorded lot on another machine than its record.
    elsewhere = copy.deepcopy(move.segments)
    for segment in elsewhere:
        if segment.lot_id == op2:
            segment.machine_id = "M9"
    assert changed(elsewhere)
    # A record dated another day.
    yesterday = replace_start(record, f"{morning.data.workdays[0]}T10:30")
    assert frozen.historical_schedule_changes(before, after(anchors=(yesterday,)), now=eleven)


def replace_kind(anchor, kind):
    return PlanAnchor(anchor.lot_id, anchor.machine_id, anchor.start_at, kind=kind)


def replace_start(anchor, start_at):
    return PlanAnchor(anchor.lot_id, anchor.machine_id, start_at, kind=anchor.kind)


def test_guard_keeps_rows_the_record_did_not_displace():
    """OP3 ran 07:00–09:30 before the record's setup: it must stay as it was."""
    config = _config()
    data = _data([_op("OP1", "T1", 4), _op("OP2", "T2", 6), _op("OP3", "T3", 5)])
    baseline, lots = _plan(data, config, {
        "OP3": [(TODAY, 420, 200, 30)], "OP1": [(TODAY, 570, 200, 30)],
        "OP2": [(3, 420, 200, 30)],
    })
    eleven = _at(TODAY, 660)
    move = _move(baseline, data, config, lots["OP2"].id, TODAY, 630, eleven)
    assert _shape(move.segments, lots["OP3"].id) == [(TODAY, "M1", 420, 570, 200, 30)]
    before = _snapshot(baseline.segments, baseline.lots, data)
    anchors = [_record(move, data)]
    assert frozen.historical_schedule_changes(before, _snapshot(
        move.segments, move.lots, data, anchors=anchors, boundary=move.history_boundary,
    ), now=eleven) == []
    shifted = copy.deepcopy(move.segments)
    op3 = next(s for s in shifted if s.lot_id == lots["OP3"].id)
    op3.start_min, op3.end_min = 425, 575
    assert lots["OP3"].id in frozen.historical_schedule_changes(before, _snapshot(
        shifted, move.lots, data, anchors=anchors, boundary=move.history_boundary,
    ), now=eleven)


def test_record_over_two_lots():
    config = _config()
    data = _data([_op("OP1", "T1", 4), _op("OP2", "T2", 6), _op("OP3", "T3", 5)])
    baseline, lots = _plan(data, config, {
        "OP1": [(TODAY, 420, 200, 30)], "OP3": [(TODAY, 570, 200, 30)],
        "OP2": [(3, 420, 200, 30)],
    })
    eleven = _at(TODAY, 660)
    move = _move(baseline, data, config, lots["OP2"].id, TODAY, 540, eleven)
    # Setup from 08:30: OP1 ran until then (60 of 120 min: 100 pieces),
    # OP3 (from 09:30) did not run at all.
    assert _shape(move.segments, lots["OP1"].id)[0] == (TODAY, "M1", 420, 510, 100, 30)
    assert all(
        (day, start) >= (TODAY, 660) for day, _m, start, *_ in _shape(move.segments, lots["OP3"].id)
    )
    assert "SKU_OP1 · T1 (M1) fica feita até às 08:30 (100 peças)" in move.notice
    assert "SKU_OP3 · T3 (M1) fica por fazer" in move.notice
    before = _snapshot(baseline.segments, baseline.lots, data)
    assert frozen.historical_schedule_changes(before, _snapshot(
        move.segments, move.lots, data, anchors=[_record(move, data)],
        boundary=move.history_boundary,
    ), now=eleven) == []


def test_crew_and_operators_before_now_are_not_judged_on_the_alternative_machine():
    """OP2 may run on M2 (its alternative). Its setup (09:30) shares the
    Grandes crew with OP1's on M1, and the Grandes operators were short this
    morning: it ran, so neither is judged before now. OP4 on M2 (from 08:00)
    ran until the setup (100 pieces)."""
    config = _config(two_machines=True)
    data = _data(
        [_op("OP1", "T1", 4), _op("OP2", "T2", 6, alt="M2"), _op("OP4", "T4", 5, machine="M2")],
        two_machines=True,
    )
    baseline, lots = _plan(data, config, {
        "OP1": [(TODAY, 570, 200, 30)], "OP4": [(TODAY, 480, 200, 30)],
        "OP2": [(3, 420, 200, 30)],
    })
    data.operator_blocked_intervals = [{
        "id": "a1", "start_day": TODAY, "end_day": TODAY, "start_min": 420, "end_min": 660,
        "group": "Grandes", "shift": "A", "count": config.operators[("Grandes", "A")],
    }]
    eleven = _at(TODAY, 660)
    move = _move(baseline, data, config, lots["OP2"].id, TODAY, 600, eleven, machine="M2")
    assert _shape(move.segments, lots["OP2"].id)[0][:4] == (TODAY, "M2", 570.0, 720)
    assert _shape(move.segments, lots["OP4"].id)[0][:5] == (TODAY, "M2", 480, 570, 100)
    # OP1 on M1 kept its morning.
    assert _shape(move.segments, lots["OP1"].id)[0][:4] == (TODAY, "M1", 570, 720)


def test_unavailability_yesterday_setup_before_material_and_pins_are_refused(morning):
    eleven = _at(TODAY, 660)
    op1, op2 = morning.lots["OP1"].id, morning.lots["OP2"].id
    with pytest.raises(ManualMoveError, match="só se pode registar o que já correu hoje"):
        _move(morning.baseline, morning.data, morning.config, op2, 0, 600, eleven)
    with pytest.raises(ManualMoveError, match="começaria no dia anterior.*07:30 ou mais tarde"):
        _move(morning.baseline, morning.data, morning.config, op2, TODAY, 420, eleven)
    broken = copy.deepcopy(morning.data)
    broken.machine_blocked_intervals = {"M1": [{
        "id": "u1", "start_day": TODAY, "start_min": 540, "end_day": TODAY, "end_min": 615,
    }]}
    with pytest.raises(ManualMoveError):
        _move(morning.baseline, broken, morning.config, op2, TODAY, 630, eleven)
    pinned = copy.deepcopy(morning.data)
    pinned.plan_anchors = [PlanAnchor(op1, "M1", f"{pinned.workdays[TODAY]}T08:30")]
    with pytest.raises(ManualMoveError, match="fixada à mão.*solte-a primeiro"):
        _move(morning.baseline, pinned, morning.config, op2, TODAY, 630, eleven)


def test_record_before_the_material_is_refused():
    config = _config()
    data = _data([_op("OP1", "T1", 4), _op("OP2", "T2", 12)])
    baseline, lots = _plan(data, config, {
        "OP1": [(TODAY, 480, 200, 30)], "OP2": [(9, 420, 200, 30)],
    })
    with pytest.raises(ManualMoveError, match="material"):
        _move(baseline, data, config, lots["OP2"].id, TODAY, 630, _at(TODAY, 660))


def _recorded(morning):
    eleven = _at(TODAY, 660)
    move = _move(
        morning.baseline, morning.data, morning.config, morning.lots["OP2"].id, TODAY, 630,
        eleven,
    )
    data = copy.deepcopy(morning.data)
    data.plan_anchors = [_record(move, data)]
    data.history_boundary = list(move.history_boundary)
    plan = ScheduleResult(
        segments=move.segments, lots=move.lots, score=move.score, time_ms=0, warnings=[],
        operator_alerts=[], history_boundary=list(move.history_boundary),
    )
    return move, data, plan


def test_desfazer_the_same_day_takes_the_record_back(morning):
    move, data, plan = _recorded(morning)
    record = _snapshot(
        plan.segments, plan.lots, data, anchors=data.plan_anchors, boundary=plan.history_boundary,
    )
    previous = _snapshot(morning.baseline.segments, morning.baseline.lots, morning.data)
    later = _at(TODAY, 672)
    assert frozen.historical_schedule_changes(record, previous, now=later) == []
    # Anything else of the morning that differs is still refused.
    other = copy.deepcopy(morning.baseline)
    other.segments[0].start_min += 5
    other.segments[0].end_min += 5
    assert frozen.historical_schedule_changes(
        record, _snapshot(other.segments, other.lots, morning.data), now=later,
    )


def test_replan_after_a_record_cuts_it_and_keeps_the_record(morning):
    """An outage at 12:00 (entered at 12:00) over the recorded lot: the lot
    stops at 12:00 like any started lot; the record stays."""
    move, data, plan = _recorded(morning)
    op2 = morning.lots["OP2"].id
    outage = copy.deepcopy(data)
    outage.machine_blocked_intervals = {"M1": [{
        "id": "u1", "start_day": TODAY, "start_min": 720, "end_day": TODAY, "end_min": 780,
    }]}
    noon = _at(TODAY, 720)
    result = frozen.optimize_preserving_started_lots(
        outage, morning.config, copy.deepcopy(plan), mode="quick", now=noon,
    )
    assert executed_lot_ids(outage) == {op2}
    first = _shape(result.segments, op2)[0]
    assert first[:4] == (TODAY, "M1", 600.0, 720) and first[4] == 150
    assert sum(item[4] for item in _shape(result.segments, op2)) == 200
    assert_plan_valid(
        result.segments, result_validation_data(outage, result), morning.config, lots=result.lots,
    )
    before = _snapshot(
        plan.segments, plan.lots, data, anchors=data.plan_anchors, boundary=plan.history_boundary,
    )
    after = _snapshot(
        result.segments, result.lots, outage, anchors=outage.plan_anchors,
        boundary=result.history_boundary,
    )
    assert frozen.historical_schedule_changes(before, after, now=noon) == []


def test_recalculate_keeps_the_record_and_releases_the_other_pins(morning):
    move, data, plan = _recorded(morning)
    op1, op2 = morning.lots["OP1"].id, morning.lots["OP2"].id
    data.plan_anchors.append(PlanAnchor(op1, "M1", f"{data.workdays[3]}T07:30"))
    state = SimpleNamespace(engine_data=data, manual_edits=[
        {"lot_id": op1}, {"lot_id": op2, "kind": EXECUTED},
    ])
    assert release_manual_anchors(state, None, keep_executed=True) == [op1]
    assert [anchor.lot_id for anchor in data.plan_anchors] == [op2]
    assert [edit["lot_id"] for edit in state.manual_edits] == [op2]
    # From D0 the record pins the lot where it ran.
    result = frozen.optimize_preserving_started_lots(
        data, morning.config, copy.deepcopy(plan), mode="quick", now=_at(TODAY, 670),
        recalculate_from_start=True,
    )
    assert _shape(result.segments, op2)[0][:4] == (TODAY, "M1", 600.0, 750)
    # «Soltar» releases a record like any pin.
    assert release_manual_anchors(state, [op2]) == [op2]
    assert data.plan_anchors == [] and state.manual_edits == []


def test_ordinary_pins_keep_their_payload():
    from backend.plans.serialize import _jsonable

    data = EngineData(
        ops=[], machines=[], twin_groups=[], client_demands={}, workdays=[], n_days=0,
        plan_anchors=[PlanAnchor("A", "M1", "2026-03-03T08:00"),
                      PlanAnchor("B", "M1", "2026-03-03T09:00", kind=EXECUTED)],
    )
    anchors = _jsonable(data)["plan_anchors"]
    assert "kind" not in anchors[0] and anchors[1]["kind"] == EXECUTED
