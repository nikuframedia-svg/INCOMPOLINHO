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
    # Said before it is applied: a time typed by mistake must not become
    # production unnoticed (revisão de 20/10/2026).
    assert move.notice == (
        "Vai ficar registado como já produzido desde 10:30 na M1: a Referência SKU_OP2 · T2 "
        "(M1), com afinação desde 10:00; a Referência SKU_OP1 · T1 (M1) fica feita até "
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
    recorded = copy.deepcopy(morning.data)
    recorded.plan_anchors = [PlanAnchor(
        op1, "M1", f"{recorded.workdays[TODAY]}T08:30", kind=EXECUTED,
    )]
    with pytest.raises(
        ManualMoveError,
        match="já está registada como feita nessa máquina desde 08:30; desfaça esse registo",
    ):
        _move(morning.baseline, recorded, morning.config, op2, TODAY, 630, eleven)


def test_an_empty_tool_never_matches_another_segment():
    from backend.scheduler.history import displaced_by

    declared = (TODAY, 600, 630, "M1", "")
    assert not displaced_by(TODAY, 540, 660, "M2", "", declared)
    assert displaced_by(TODAY, 540, 660, "M1", "", declared)
    assert displaced_by(TODAY, 540, 660, "M2", "T1", (TODAY, 600, 630, "M1", "T1"))


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
    assert frozen.historical_schedule_changes(record, previous, now=later, undo=True) == []
    # Anything else of the morning that differs is still refused.
    other = copy.deepcopy(morning.baseline)
    other.segments[0].start_min += 5
    other.segments[0].end_min += 5
    assert frozen.historical_schedule_changes(
        record, _snapshot(other.segments, other.lots, morning.data), now=later, undo=True,
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


# ── Later the same day: the guard compares everything but the record ────────
# Revisão 178 shape (PRM043, 20/10/2026): JTE recorded on M43 from 08:00 at
# 11:49; CF, which it displaced, replanned on M44 from 12:00.
_DAYS = ["2026-10-20", "2026-10-21", "2026-10-22"]


def _row(lot_id, machine, tool, start, end, qty, setup=0.0):
    return {
        "lot_id": lot_id, "run_id": lot_id, "machine_id": machine, "tool_id": tool,
        "day_idx": 0, "start_min": start, "end_min": end, "shift": "A", "qty": qty,
        "prod_min": end - start - setup, "setup_min": setup, "is_continuation": False,
        "twin_outputs": None,
    }


def _lot(lot_id, machine, tool, qty):
    return {
        "id": lot_id, "op_id": f"op{lot_id}", "tool_id": tool, "machine_id": machine,
        "qty": qty, "prod_min": 100, "setup_min": 60, "is_twin": False, "twin_outputs": None,
    }


def _state(rows, *, recorded=False):
    machines = {}
    for item in rows:
        machines.setdefault(item["lot_id"], (item["machine_id"], item["tool_id"], 0))
        machine, tool, qty = machines[item["lot_id"]]
        machines[item["lot_id"]] = (machine, tool, qty + item["qty"])
    engine = {"workdays": _DAYS, "plan_anchors": []}
    if recorded:
        engine["plan_anchors"] = [{
            "lot_id": "JTE", "machine_id": "M43", "start_at": "2026-10-20T08:00:00",
            "reason": "", "author": "u", "kind": EXECUTED,
        }]
        engine["history_boundary"] = [0, 709]
    return {
        "dataset_info": {"id": "ds"}, "engine_data": engine,
        "config": {"timezone": "Europe/Lisbon"}, "segments": rows,
        "lots": [_lot(lot_id, *values) for lot_id, values in machines.items()],
    }


def _lisbon(hour, minute):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime(2026, 10, 20, hour, minute, tzinfo=ZoneInfo("Europe/Lisbon"))


_BEFORE_RECORD = [
    _row("CF", "M43", "T1", 420, 950, 1000, setup=60),
    _row("JTE", "M43", "T2", 1115, 1300, 500, setup=60),
]


def _after_record(cf_start):
    return [
        _row("JTE", "M43", "T2", 420, 1300, 500, setup=60),
        _row("CF", "M44", "T1", cf_start, cf_start + 480, 1000, setup=60),
    ]


def test_desfazer_later_is_refused_once_the_replanned_work_started():
    """At 14:00 CF has run on M44 since 12:00: «Desfazer» would erase it."""
    record = _state(_after_record(720), recorded=True)
    previous = _state(_BEFORE_RECORD)
    assert frozen.historical_schedule_changes(record, previous, now=_lisbon(11, 52), undo=True) == []
    assert frozen.historical_schedule_changes(record, previous, now=_lisbon(14, 0), undo=True) == ["CF"]


def test_desfazer_later_is_not_blocked_by_work_the_same_in_both_plans():
    """Y on M30 from 12:30 is identical in both plans; CF waits for 15:00."""
    same = [_row("Y", "M30", "T8", 750, 900, 100), _row("Z", "M20", "T9", 360, 1080, 800)]
    record = _state(_after_record(900) + same, recorded=True)
    previous = _state(_BEFORE_RECORD + same)
    assert frozen.historical_schedule_changes(record, previous, now=_lisbon(14, 0), undo=True) == []


def test_repor_the_record_later_cannot_add_work_after_it():
    """Restoring the record version at 14:00 over the undo: CF on M44 from
    12:00 and any other row from 11:49 on would be production added in
    time already gone."""
    undone = _state(_BEFORE_RECORD)
    restored = _state(_after_record(720), recorded=True)
    assert frozen.historical_schedule_changes(undone, restored, now=_lisbon(14, 0)) == ["CF"]
    invented = _state(
        _after_record(900) + [_row("W", "M50", "T7", 730, 1000, 300)], recorded=True,
    )
    assert frozen.historical_schedule_changes(undone, invented, now=_lisbon(14, 0)) == ["W"]
    # The same restore while nothing else has started yet is the record alone.
    assert frozen.historical_schedule_changes(
        undone, _state(_after_record(900), recorded=True), now=_lisbon(14, 0),
    ) == []


# ── Revisão de 20/10/2026 (4 achados) ───────────────────────────────────────


def test_a_displaced_lot_that_made_pieces_keeps_its_machine_and_the_guard_accepts():
    """Achado 1 (não reproduz): OP1 on M1 07:00–12:30 may also run on M2.
    Recording OP2 from 09:00 at 10:00 cuts OP1 at 08:30 (100 pieces): it
    started, so its rest stays on M1 (rule 3, ``frozen._remainder_lot``) and
    the guard has no lot-level change to refuse."""
    config = _config(two_machines=True)
    long_op = _op("OP1", "T1", 4, alt="M2")
    long_op.d[4], long_op.eco_lot = 500, 500
    data = _data(
        [long_op, _op("OP2", "T2", 6), _op("OP3", "T3", 2)], two_machines=True,
    )
    baseline, lots = _plan(data, config, {
        "OP1": [(TODAY, 420, 500, 30)], "OP2": [(3, 420, 200, 30)],
        "OP3": [(TODAY, 750, 200, 30)],
    })
    ten = _at(TODAY, 600)
    op1 = lots["OP1"].id
    move = _move(baseline, data, config, lots["OP2"].id, TODAY, 540, ten)
    rows = _shape(move.segments, op1)
    assert rows[0][:5] == (TODAY, "M1", 420, 510, 100)
    assert {machine for _day, machine, *_ in rows} == {"M1"}
    assert next(lot for lot in move.lots if lot.id == op1).machine_id == "M1"
    before = _snapshot(baseline.segments, baseline.lots, data)
    assert frozen.historical_schedule_changes(before, _snapshot(
        move.segments, move.lots, data, anchors=[_record(move, data)],
        boundary=move.history_boundary,
    ), now=ten) == []


def _slow_record():
    """OP2 (2 min per piece) recorded at 11:00 as run from 10:59 on M1."""
    config = _config()
    slow = _op("OP2", "T2", 6)
    slow.pH = 30
    data = _data([_op("OP1", "T1", 4), slow])
    baseline, lots = _plan(data, config, {
        "OP1": [(TODAY, 480, 200, 30)], "OP2": [(5, 420, 200, 30)],
    })
    move = _move(baseline, data, config, lots["OP2"].id, TODAY, 659, _at(TODAY, 660))
    recorded = copy.deepcopy(data)
    recorded.plan_anchors = [_record(move, recorded)]
    recorded.history_boundary = list(move.history_boundary)
    plan = ScheduleResult(
        segments=move.segments, lots=move.lots, score=move.score, time_ms=0, warnings=[],
        operator_alerts=[], history_boundary=list(move.history_boundary),
    )
    return config, lots, recorded, plan


def test_an_outage_that_stops_a_record_before_its_first_piece_releases_the_record():
    """Achado 2: an outage from 10:30 entered at 11:00 stops OP2 at 11:00,
    before its first piece. Like any started lot it is released whole and
    replanned; its record goes with a notice, the replan never fails."""
    config, lots, recorded, plan = _slow_record()
    op2 = lots["OP2"].id
    outage = copy.deepcopy(recorded)
    outage.machine_blocked_intervals = {"M1": [{
        "id": "u1", "start_day": TODAY, "start_min": 630, "end_day": TODAY, "end_min": 720,
    }]}
    eleven = _at(TODAY, 660)
    result = frozen.optimize_preserving_started_lots(
        outage, config, copy.deepcopy(plan), mode="quick", now=eleven,
    )
    assert executed_lot_ids(outage) == set()
    assert min((day, start) for day, _m, start, *_ in _shape(result.segments, op2)) >= (
        TODAY, 720,
    )
    assert sum(item[4] for item in _shape(result.segments, op2)) == 200
    assert result.warnings[0] == (
        "Soltei a alteração manual da Referência SKU_OP2 · T2 (M1), fixada para 03/03 10:59: "
        "a alteração nova parou-a antes da primeira peça; deixa de estar registada como "
        "feita e é replaneada a partir de agora."
    )
    assert_plan_valid(
        result.segments, result_validation_data(outage, result), config, lots=result.lots,
    )
    before = _snapshot(
        plan.segments, plan.lots, recorded, anchors=recorded.plan_anchors,
        boundary=plan.history_boundary,
    )
    assert frozen.historical_schedule_changes(before, _snapshot(
        result.segments, result.lots, outage, boundary=result.history_boundary,
    ), now=eleven) == []


def test_an_outage_that_stops_a_record_after_a_piece_keeps_the_record():
    """The same outage a minute later: one piece made, the record stays."""
    config, lots, recorded, plan = _slow_record()
    outage = copy.deepcopy(recorded)
    outage.machine_blocked_intervals = {"M1": [{
        "id": "u1", "start_day": TODAY, "start_min": 600, "end_day": TODAY, "end_min": 720,
    }]}
    result = frozen.optimize_preserving_started_lots(
        outage, config, copy.deepcopy(plan), mode="quick", now=_at(TODAY, 661),
    )
    assert executed_lot_ids(outage) == {lots["OP2"].id}
    assert _shape(result.segments, lots["OP2"].id)[0][:5] == (TODAY, "M1", 629.0, 661, 1)


def test_desfazer_is_not_blocked_by_what_the_original_plan_had_after_the_record():
    """Revisão 2 do achado 3 (ensaio real, PRM043): CF's second row 15:30–15:50
    and Y at 13:00 on M43, in the plan without the record, sit in the time
    the record occupied; CF and Y were replanned for later. «Desfazer» at
    15:40 puts the plan back; once CF has started on M44 it is refused."""
    original = _BEFORE_RECORD[:1] + [
        _row("CF", "M43", "T1", 930, 950, 40),
        _row("Y", "M43", "T5", 780, 900, 100),
    ]
    previous = _state([dict(original[0], end_min=930, qty=960), *original[1:]])
    later = _state(_after_record(1300) + [_row("Y", "M44", "T5", 1320, 1400, 100)],
                   recorded=True)
    assert frozen.historical_schedule_changes(later, previous, now=_lisbon(15, 25), undo=True) == []
    assert frozen.historical_schedule_changes(later, previous, now=_lisbon(15, 40), undo=True) == []
    assert frozen.historical_schedule_changes(later, previous, now=_lisbon(13, 30), undo=True) == []
    started = _state(_after_record(720) + [_row("Y", "M44", "T5", 1320, 1400, 100)],
                     recorded=True)
    assert frozen.historical_schedule_changes(started, previous, now=_lisbon(15, 40), undo=True) == ["CF"]
    # Repor over the undo stays strict: Y on M43 from 13:00 there has run.
    assert frozen.historical_schedule_changes(previous, later, now=_lisbon(13, 30)) == ["Y"]


_PLANNED_AT_1200 = [
    _row("CF", "M43", "T1", 420, 950, 1000, setup=60),
    _row("JTE", "M50", "T2", 720, 1300, 500, setup=60),
]


def test_desfazer_works_once_the_original_time_of_the_recorded_lot_has_come():
    """Achado 3: JTE was planned on M50 from 12:00 and recorded at 11:49 as
    run from 08:00. At 14:00 the original position has started too, but CF,
    which the record replanned, waits for 15:00: «Desfazer» puts the plan back."""
    record = _state(_after_record(900), recorded=True)
    previous = _state(_PLANNED_AT_1200)
    assert frozen.historical_schedule_changes(record, previous, now=_lisbon(14, 0), undo=True) == []
    # Once CF has started on M44 it is still refused.
    started = _state(_after_record(720), recorded=True)
    assert frozen.historical_schedule_changes(started, previous, now=_lisbon(14, 0), undo=True) == ["CF"]
    # A plan where the lot had started before the record's instant is not
    # the one it replaced: no exception.
    earlier = _state([
        _row("CF", "M43", "T1", 420, 950, 1000, setup=60),
        _row("JTE", "M30", "T2", 600, 1300, 500, setup=60),
    ])
    assert frozen.historical_schedule_changes(record, earlier, now=_lisbon(14, 0), undo=True)


def test_desfazer_of_a_record_refused_says_why():
    from backend.plans.history import undo_refusal_message

    message = undo_refusal_message("Registado como feito: Referência X (M1) desde 20/10 08:00")
    assert "desde o registo já começou trabalho que ele replaneou" in message
    assert "«Soltar»" in message
    assert "o plano anterior mudaria" in undo_refusal_message("Movido Referência X (M1)")


def test_apply_refuses_a_record_its_check_did_not_show(morning):
    """Achado 4: a record is applied only as the check showed it."""
    from fastapi import HTTPException

    from backend.api.manual_plan import _require_executed_preview

    move = _move(
        morning.baseline, morning.data, morning.config, morning.lots["OP2"].id, TODAY, 630,
        _at(TODAY, 660),
    )
    _require_executed_preview(move)
    unseen = copy.copy(move)
    unseen.notice = None
    with pytest.raises(HTTPException) as refused:
        _require_executed_preview(unseen)
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "preview_required"
    ordinary = copy.copy(move)
    ordinary.executed, ordinary.notice = False, None
    _require_executed_preview(ordinary)


# ── 2.ª revisão de 20/10/2026 (B1, B2) ──────────────────────────────────────


def test_repor_stays_strict_once_the_original_time_of_the_recorded_lot_has_come():
    """B1: JTE recorded on M43 from 08:00 at 11:49, «Desfazer» at 11:55; the
    active plan has JTE on M50 from 12:00 and CF on M43 07:00–15:50. At
    14:00 «Repor» would erase JTE's run on M50 and CF's on M43: refused."""
    undone = _state(_PLANNED_AT_1200)
    record = _state(_after_record(900), recorded=True)
    assert frozen.historical_schedule_changes(undone, record, now=_lisbon(14, 0)) == [
        "CF", "JTE",
    ]
    # The «Desfazer» direction keeps the same-day exception (achado 3).
    assert frozen.historical_schedule_changes(record, undone, now=_lisbon(14, 0), undo=True) == []


def test_desfazer_is_not_blocked_by_work_the_same_in_both_plans_on_the_record_machine():
    """B2: Z on M43 13:00–15:00 is identical in both plans; the record took
    M43 from 07:00 and replanned CF on M44 for 21:40. «Desfazer» puts the
    plan back; a Z the record changed is still refused."""
    previous = _state([
        _row("CF", "M43", "T1", 420, 500, 100, setup=60),
        _row("Z", "M43", "T5", 780, 900, 100),
        _row("JTE", "M43", "T2", 1115, 1300, 500, setup=60),
    ])
    record = _state([
        _row("JTE", "M43", "T2", 420, 600, 500, setup=60),
        _row("Z", "M43", "T5", 780, 900, 100),
        _row("CF", "M44", "T1", 1300, 1380, 100, setup=60),
    ], recorded=True)
    for now in (_lisbon(14, 0), _lisbon(15, 10)):
        assert frozen.historical_schedule_changes(record, previous, now=now, undo=True) == []
    changed = _state([
        _row("JTE", "M43", "T2", 420, 600, 500, setup=60),
        _row("Z", "M43", "T5", 720, 840, 100),
        _row("CF", "M44", "T1", 1300, 1380, 100, setup=60),
    ], recorded=True)
    assert frozen.historical_schedule_changes(changed, previous, now=_lisbon(15, 10), undo=True) == ["Z"]


# ── 3.ª revisão de 20/10/2026 (B1: só o «Desfazer» tem a folga) ─────────────


def test_a_change_that_drops_the_record_other_than_desfazer_stays_strict():
    """A replan that releases the record (or an ISOP, a Recalcular) is not
    the version the record replaced: what it writes into the morning after
    the record's instant is refused, as without a record."""
    record = _state(_after_record(900), recorded=True)
    invented = _state(_BEFORE_RECORD + [_row("W", "M43", "T7", 720, 780, 50)])
    assert frozen.historical_schedule_changes(record, invented, now=_lisbon(14, 0)) == ["W"]
    moved = _state([
        _row("CF", "M43", "T1", 420, 950, 1000, setup=60),
        _row("JTE", "M50", "T2", 720, 1300, 500, setup=60),
    ])
    assert "JTE" in frozen.historical_schedule_changes(record, moved, now=_lisbon(14, 0))
    # The same version put back by «Desfazer» is accepted.
    assert frozen.historical_schedule_changes(
        record, moved, now=_lisbon(14, 0), undo=True,
    ) == []


def test_the_store_gives_the_leeway_only_to_the_version_the_record_replaced(
    tmp_path, monkeypatch,
):
    """``PlansStore``: «Desfazer» names the version the active plan replaced;
    any other id (or none) is judged strictly."""
    import json

    import backend.calendar as factory_calendar
    from backend.plans.store import PlansStore

    monkeypatch.setattr(factory_calendar, "wall_factory_now", lambda _zone: _lisbon(14, 0))
    store = PlansStore(tmp_path / "plans.db")
    previous = _state(_PLANNED_AT_1200)
    with store._conn:
        for plan_id, payload, undo_to in (
            ("antes", previous, None),
            ("registo", _state(_after_record(900), recorded=True), "antes"),
        ):
            store._conn.execute(
                "INSERT INTO plans(id,name,source,payload_json,undo_to) VALUES (?,?,?,?,?)",
                (plan_id, plan_id, "auto", json.dumps(payload), undo_to),
            )
        store._conn.execute("UPDATE plan_runtime SET snapshot_id='registo' WHERE singleton=1")
    now = _lisbon(14, 0)
    assert store.protected_changes(previous, now=now, undo_restores="antes") is None
    assert store.protected_changes(previous, now=now) is not None
    assert store.protected_changes(previous, now=now, undo_restores="registo") is not None


# ── Lote começado hoje (decisão do Luís, 21/10/2026) ────────────────────────
# Revisão 179 (PRM043): CF589 planned 07:00–15:50 and JTE001 from 15:50; at
# 10:34 moving CF589 to 22/10 16:00 was refused («já iniciado está
# congelado»). A lot that, by the plan, only started today moves freely: it
# was not produced. Its morning rows leave, nothing new enters before now,
# «Recalcular» does not put it back there and «Desfazer» works the same day.
# Started on an earlier day or recorded as run, it stays refused. The commit
# guard sets its morning aside only on the server's own signal.


def _unproduced(move, data):
    """``data`` and plan after ``move-apply`` of a lot moved as not produced."""
    applied = copy.deepcopy(data)
    applied.plan_anchors = [
        *(anchor for anchor in applied.plan_anchors if anchor.lot_id != move.lot_id),
        PlanAnchor(
            move.lot_id, move.target_machine,
            f"{data.workdays[move.target_day]}T{move.target_start_min // 60:02d}:"
            f"{move.target_start_min % 60:02d}",
        ),
    ]
    applied.unproduced_today = [dict(move.unproduced_today)]
    plan = ScheduleResult(
        segments=move.segments, lots=move.lots, score=move.score, time_ms=0, warnings=[],
        operator_alerts=[],
    )
    return applied, plan


def test_a_lot_started_today_moves_as_not_produced(morning):
    nine = _at(TODAY, 540)
    op1 = morning.lots["OP1"].id
    move = _move(morning.baseline, morning.data, morning.config, op1, 3, 420, nine)
    assert not move.executed
    assert move.unproduced_today == {
        "lot_id": op1, "tool_id": "T1", "date": morning.data.workdays[TODAY][:10],
        "start_min": 480, "since": 540,
    }
    assert move.notice == (
        "A Referência SKU_OP1 · T1 (M1) fica registada como não produzida hoje (estava na "
        "M1 das 08:00 às 10:30) e passa para 05/03 às 07:00."
    )
    assert "LOT_" not in move.notice
    assert min(
        (s.day_idx, s.production_start_min) for s in move.segments if s.lot_id == op1 and s.qty
    ) == (3, 420)
    assert not [
        s for s in move.segments
        if s.day_idx == TODAY and s.start_min < 540 and s.end_min > s.start_min
    ]
    before = _snapshot(morning.baseline.segments, morning.baseline.lots, morning.data)
    after = _snapshot(move.segments, move.lots, morning.data)
    assert frozen.historical_schedule_changes(
        before, after, now=nine, unproduced=("before", op1),
    ) == []
    assert frozen.historical_schedule_changes(before, after, now=nine) == [op1]
    # «Desfazer» the same day: only with the signal for the lot it moved.
    later = _at(TODAY, 560)
    assert frozen.historical_schedule_changes(
        after, before, now=later, undo=True, unproduced=("after", op1),
    ) == []
    assert frozen.historical_schedule_changes(after, before, now=later, undo=True) == [op1]
    # «Repor» the move over that «Desfazer» stays strict (OP2, replanned
    # from 09:00, is in the morning too).
    assert frozen.historical_schedule_changes(before, after, now=later) == sorted(
        [op1, morning.lots["OP2"].id],
    )


def test_a_lot_recorded_as_run_or_started_on_an_earlier_day_stays_refused(morning):
    nine = _at(TODAY, 540)
    op1 = morning.lots["OP1"].id
    recorded = copy.deepcopy(morning.data)
    recorded.plan_anchors = [
        PlanAnchor(op1, "M1", f"{recorded.workdays[TODAY]}T08:30", kind=EXECUTED),
    ]
    with pytest.raises(ManualMoveError) as refused:
        _move(morning.baseline, recorded, morning.config, op1, 3, 420, nine)
    assert str(refused.value) == (
        "A Referência SKU_OP1 · T1 (M1) está registada como feita desde 08:30; "
        "desfaça esse registo primeiro."
    )
    yesterday = copy.deepcopy(morning.baseline)
    yesterday.segments[0].day_idx = TODAY - 1
    with pytest.raises(ManualMoveError) as refused:
        _move(yesterday, morning.data, morning.config, op1, 3, 420, nine)
    assert str(refused.value) == (
        "Lote Referência SKU_OP1 · T1 (M1) começou em 02/03 e está congelado; "
        "não pode ser movido."
    )


def test_the_guard_ignores_a_signal_the_lot_does_not_meet():
    """Only the named lot, only if it started today alone and has no record."""
    previous = _state(_BEFORE_RECORD)
    moved = _state([_row("JTE", "M43", "T2", 1115, 1300, 500, setup=60)])
    ten = _lisbon(10, 0)
    assert frozen.historical_schedule_changes(
        previous, moved, now=ten, unproduced=("before", "CF"),
    ) == []
    assert frozen.historical_schedule_changes(
        previous, moved, now=ten, unproduced=("before", "JTE"),
    ) == ["CF"]
    assert frozen.historical_schedule_changes(
        previous, moved, now=ten, unproduced=("after", "CF"),
    ) == ["CF"]
    assert frozen.historical_schedule_changes(
        previous, moved, now=ten, unproduced=("other", "CF"),
    ) == ["CF"]
    # A row on an earlier day: the lot started before today.
    started = copy.deepcopy(previous)
    started["engine_data"]["workdays"] = ["2026-10-19", *_DAYS]
    for segment in started["segments"]:
        segment["day_idx"] += 1
    earlier = copy.deepcopy(started["segments"][0])
    earlier["day_idx"], earlier["setup_min"] = 0, 0.0
    started["segments"].append(earlier)
    stayed = copy.deepcopy(started)
    stayed["segments"] = [s for s in stayed["segments"] if s["lot_id"] != "CF" or s["day_idx"] == 0]
    assert frozen.historical_schedule_changes(
        started, stayed, now=ten, unproduced=("before", "CF"),
    ) == ["CF"]
    # A lot recorded as run on that side (and still recorded).
    record = [{
        "lot_id": "CF", "machine_id": "M43", "start_at": "2026-10-20T07:00", "kind": EXECUTED,
    }]
    recorded, still = copy.deepcopy(previous), copy.deepcopy(moved)
    recorded["engine_data"]["plan_anchors"] = still["engine_data"]["plan_anchors"] = record
    assert frozen.historical_schedule_changes(
        recorded, still, now=ten, unproduced=("before", "CF"),
    ) == ["CF"]
    # Anything else of the morning stays strict.
    other = _state([
        _row("JTE", "M43", "T2", 1115, 1300, 500, setup=60),
        _row("W", "M50", "T7", 500, 700, 50),
    ])
    assert frozen.historical_schedule_changes(
        previous, other, now=ten, unproduced=("before", "CF"),
    ) == ["W"]


def test_twin_lot_started_today_leaves_whole():
    twin = _row("TW", "M43", "T1", 420, 950, 1000, setup=60)
    twin["twin_outputs"] = [["opA", "A", 1000], ["opB", "B", 1000]]
    previous = _state([twin, _row("JTE", "M43", "T2", 1115, 1300, 500, setup=60)])
    later = copy.deepcopy(twin)
    later["day_idx"], later["start_min"], later["end_min"] = 1, 420, 950
    moved = _state([_row("JTE", "M43", "T2", 600, 785, 500, setup=60), later])
    ten = _lisbon(10, 0)
    assert frozen.historical_schedule_changes(
        previous, moved, now=ten, unproduced=("before", "TW"),
    ) == []
    assert frozen.historical_schedule_changes(previous, moved, now=ten) == ["TW"]


def test_a_lot_started_today_moves_to_its_alternative_machine():
    config = _config(two_machines=True)
    data = _data([_op("OP1", "T1", 4, alt="M2"), _op("OP2", "T2", 6)], two_machines=True)
    baseline, lots = _plan(data, config, {
        "OP1": [(TODAY, 480, 200, 30)], "OP2": [(3, 420, 200, 30)],
    })
    nine = _at(TODAY, 540)
    op1 = lots["OP1"].id
    move = _move(baseline, data, config, op1, 3, 420, nine, machine="M2")
    assert move.unproduced_today and move.notice.endswith("passa para 05/03 às 07:00 na M2.")
    assert {s.machine_id for s in move.segments if s.lot_id == op1} == {"M2"}
    before = _snapshot(baseline.segments, baseline.lots, data)
    after = _snapshot(move.segments, move.lots, data)
    assert frozen.historical_schedule_changes(
        before, after, now=nine, unproduced=("before", op1),
    ) == []


def _swap():
    """M1 today: Y (OP1) 07:00–15:30 by the plan, G (OP2) after it."""
    config = _config()
    data = _data([_op("OP1", "T1", 4), _op("OP2", "T2", 4)])
    data.ops[0].d[4] = 800
    baseline, lots = _plan(data, config, {
        "OP1": [(TODAY, 420, 800, 30)], "OP2": [(TODAY, 930, 200, 30)],
    })
    return config, data, baseline, lots["OP1"].id, lots["OP2"].id


def test_swap_green_first_then_yellow():
    """G recorded as run from 07:30 at 10:00 takes the morning; Y, which then
    made nothing, is replanned whole from now. At 10:10 its replanned start
    (10:00) has come too: it moves as not produced, like in the morning."""
    config, data, baseline, yellow, green = _swap()
    ten = _at(TODAY, 600)
    record = _move(baseline, data, config, green, TODAY, 450, ten)
    assert record.executed and not record.unproduced_today
    assert not [s for s in record.segments if s.lot_id == yellow and s.day_idx == TODAY
                and s.start_min < 600]
    recorded = copy.deepcopy(data)
    recorded.plan_anchors = [_record(record, recorded)]
    recorded.history_boundary = list(record.history_boundary)
    plan = ScheduleResult(record.segments, record.lots, record.score, 0, [], [],
                          history_boundary=list(record.history_boundary))
    moved = _move(plan, recorded, config, yellow, 3, 420, _at(TODAY, 610))
    assert not moved.executed and moved.unproduced_today["start_min"] == 600
    assert "fica registada como não produzida hoje (estava na M1 das 10:00" in moved.notice
    before = _snapshot(plan.segments, plan.lots, recorded, anchors=recorded.plan_anchors,
                       boundary=plan.history_boundary)
    after = _snapshot(moved.segments, moved.lots, recorded, anchors=recorded.plan_anchors,
                      boundary=plan.history_boundary)
    assert frozen.historical_schedule_changes(
        before, after, now=_at(TODAY, 610), unproduced=("before", yellow),
    ) == []
    # The record stays where it ran.
    assert _shape(moved.segments, green) == _shape(record.segments, green)
    # «Desfazer» of both, the same day.
    assert frozen.historical_schedule_changes(
        after, before, now=_at(TODAY, 612), undo=True, unproduced=("after", yellow),
    ) == []
    start = _snapshot(baseline.segments, baseline.lots, data)
    assert frozen.historical_schedule_changes(before, start, now=_at(TODAY, 613), undo=True) == []


def test_swap_yellow_first_then_green():
    """Y moved at 10:00 as not produced; G, replanned from 10:00, is then
    recorded as run from 07:30 at 10:10: both at once (not produced where
    the plan had it, run from 07:30). Each «Desfazer» works the same day."""
    config, data, baseline, yellow, green = _swap()
    ten = _at(TODAY, 600)
    first = _move(baseline, data, config, yellow, 3, 420, ten)
    assert first.unproduced_today and first.unproduced_today["since"] == 600
    applied, plan = _unproduced(first, data)
    # G replanned from now (the engine's choice); for the test, G at 10:00.
    plan.segments = [s for s in plan.segments if s.lot_id != green]
    g_rows = [s for s in baseline.segments if s.lot_id == green]
    for segment in g_rows:
        segment.start_min, segment.end_min = 600, 600 + (segment.end_min - segment.start_min)
    plan.segments.extend(copy.deepcopy(g_rows))
    start = _snapshot(baseline.segments, baseline.lots, data)
    after_first = _snapshot(plan.segments, plan.lots, applied, anchors=applied.plan_anchors)
    assert frozen.historical_schedule_changes(
        start, after_first, now=ten, unproduced=("before", yellow),
    ) == []

    ten_ten = _at(TODAY, 610)
    second = _move(plan, applied, config, green, TODAY, 450, ten_ten)
    assert second.executed and second.unproduced_today
    assert second.notice.startswith("Vai ficar registado como já produzido desde 07:30 na M1")
    assert second.notice.endswith(
        "Onde o plano a tinha hoje (estava na M1 das 10:00 às 12:30) fica como não produzida."
    )
    recorded = copy.deepcopy(applied)
    recorded.plan_anchors = [
        *(a for a in recorded.plan_anchors if a.lot_id != green), _record(second, recorded),
    ]
    after_second = _snapshot(
        second.segments, second.lots, recorded, anchors=recorded.plan_anchors,
        boundary=second.history_boundary,
    )
    assert frozen.historical_schedule_changes(
        after_first, after_second, now=ten_ten, unproduced=("before", green),
    ) == []
    assert frozen.historical_schedule_changes(after_first, after_second, now=ten_ten) == [green]
    # «Desfazer» of the record, then of the first move, the same day.
    later = _at(TODAY, 612)
    assert frozen.historical_schedule_changes(
        after_second, after_first, now=later, undo=True, unproduced=("after", green),
    ) == []
    assert frozen.historical_schedule_changes(
        after_second, after_first, now=later, undo=True,
    ) == [green]
    assert frozen.historical_schedule_changes(
        after_first, start, now=_at(TODAY, 613), undo=True, unproduced=("after", yellow),
    ) == []


def test_desfazer_is_refused_once_work_started_in_the_freed_time():
    """CF left the morning at 10:00; JTE was replanned on M43 from 10:00. At
    10:20 JTE has made pieces: «Desfazer» would erase them."""
    previous = _state(_BEFORE_RECORD)
    moved = _state([
        _row("JTE", "M43", "T2", 600, 785, 500, setup=10),
        {**_row("CF", "M43", "T1", 420, 950, 1000, setup=60), "day_idx": 1},
    ])
    assert frozen.historical_schedule_changes(
        moved, previous, now=_lisbon(10, 5), undo=True, unproduced=("after", "CF"),
    ) == []
    assert frozen.historical_schedule_changes(
        moved, previous, now=_lisbon(10, 20), undo=True, unproduced=("after", "CF"),
    ) == ["JTE"]


# «Desfazer» of a move as not produced when the move put another lot in the
# time it freed (decisão do Luís, 26/10/2026; rev 179: BFP204 on PRM043 from
# 10:34, «Desfazer» at 10:35). CF left M43 at 10:00; BFP, planned on M50
# after now, was put on M43 from 10:00 (setup 30).
_LEFT = {"lot_id": "CF", "tool_id": "T1", "date": "2026-10-20", "start_min": 420, "since": 600}


def _cf_out_bfp_in(start=600, machine="M43", tool="T3", *, left=True):
    previous = _state([*_BEFORE_RECORD, _row("BFP", "M50", "T3", 1040, 1300, 500, setup=30)])
    moved = _state([
        _row("BFP", machine, tool, start, start + 260, 500, setup=30),
        _row("JTE", "M43", "T2", 1115, 1300, 500, setup=60),
        {**_row("CF", "M43", "T1", 420, 950, 1000, setup=60), "day_idx": 1},
    ])
    if left:
        moved["engine_data"]["unproduced_today"] = [dict(_LEFT)]
    return previous, moved


def _undo(moved, previous, minute, **kwargs):
    return frozen.historical_schedule_changes(
        moved, previous, now=_lisbon(10, minute), undo=True, **kwargs,
    )


def test_desfazer_takes_back_a_lot_the_move_put_in_the_freed_time():
    previous, moved = _cf_out_bfp_in()
    assert _undo(moved, previous, 5, unproduced=("after", "CF")) == []
    # Only with the explicit signal, and the move's own entry (its instant).
    assert "BFP" in _undo(moved, previous, 5)
    _previous, unmarked = _cf_out_bfp_in(left=False)
    assert _undo(unmarked, previous, 5, unproduced=("after", "CF")) == ["BFP"]
    # Not a «Desfazer»: strict.
    assert frozen.historical_schedule_changes(
        moved, previous, now=_lisbon(10, 5), unproduced=("after", "CF"),
    ) == ["BFP"]


def test_desfazer_is_refused_once_the_lot_put_in_the_freed_time_made_pieces():
    previous, moved = _cf_out_bfp_in()
    assert _undo(moved, previous, 29, unproduced=("after", "CF")) == []
    assert _undo(moved, previous, 40, unproduced=("after", "CF")) == ["BFP"]


def test_desfazer_leeway_needs_the_lot_not_started_in_the_version_put_back():
    previous, moved = _cf_out_bfp_in()
    # By the version put back, BFP had started on M50 at 08:20.
    started = _state([*_BEFORE_RECORD, _row("BFP", "M50", "T3", 500, 760, 500, setup=30)])
    assert "BFP" in _undo(moved, started, 5, unproduced=("after", "CF"))
    # A record of what ran of it (kept by the «Desfazer»).
    recorded, kept = copy.deepcopy(moved), copy.deepcopy(previous)
    recorded["engine_data"]["plan_anchors"] = kept["engine_data"]["plan_anchors"] = [{
        "lot_id": "BFP", "machine_id": "M43", "start_at": "2026-10-20T10:00", "kind": EXECUTED,
    }]
    assert _undo(recorded, kept, 5, unproduced=("after", "CF")) == ["BFP"]


def test_desfazer_leeway_never_covers_a_lot_starting_before_the_move_or_elsewhere():
    previous, early = _cf_out_bfp_in(start=590)
    assert _undo(early, previous, 5, unproduced=("after", "CF")) == ["BFP"]
    # On a machine CF did not leave (BFP planned on M50 later).
    _previous, elsewhere = _cf_out_bfp_in(machine="M44")
    assert _undo(elsewhere, previous, 5, unproduced=("after", "CF")) == ["BFP"]


def test_repor_over_that_desfazer_stays_strict():
    previous, moved = _cf_out_bfp_in()
    later = _lisbon(10, 5)
    assert frozen.historical_schedule_changes(
        previous, moved, now=later, unproduced=("before", "CF"),
    ) == ["BFP"]
    assert frozen.historical_schedule_changes(
        previous, moved, now=later, undo=True, unproduced=("before", "CF"),
    ) == ["BFP"]


def _store_with(tmp_path, monkeypatch, versions, active):
    import json

    import backend.calendar as factory_calendar
    from backend.plans.store import PlansStore

    monkeypatch.setattr(factory_calendar, "wall_factory_now", lambda _zone: _lisbon(10, 5))
    store = PlansStore(tmp_path / "plans.db")
    with store._conn:
        for plan_id, payload, undo_to in versions:
            store._conn.execute(
                "INSERT INTO plans(id,name,source,payload_json,undo_to) VALUES (?,?,?,?,?)",
                (plan_id, plan_id, "auto", json.dumps(payload), undo_to),
            )
        store._conn.execute(
            "UPDATE plan_runtime SET snapshot_id=? WHERE singleton=1", (active,),
        )
    return store


def _moved_cf(previous_version_id):
    moved = _state([
        _row("JTE", "M43", "T2", 1115, 1300, 500, setup=60),
        {**_row("CF", "M43", "T1", 420, 950, 1000, setup=60), "day_idx": 1},
    ])
    moved["manual_edits"] = [{
        "lot_id": "CF", "previous_version_id": previous_version_id, "unproduced_today": True,
    }]
    return moved


def test_the_store_sets_the_morning_aside_only_for_the_move_it_records(tmp_path, monkeypatch):
    previous = _state(_BEFORE_RECORD)
    store = _store_with(tmp_path, monkeypatch, [("antes", previous, None)], "antes")
    now = _lisbon(10, 5)
    assert store.protected_changes(_moved_cf("antes"), now=now, unproduced="CF") is None
    # No signal, a signal for another lot, a payload that does not record
    # this move over the active version: strict.
    assert store.protected_changes(_moved_cf("antes"), now=now) is not None
    assert store.protected_changes(_moved_cf("antes"), now=now, unproduced="JTE") is not None
    assert store.protected_changes(_moved_cf("outra"), now=now, unproduced="CF") is not None
    unflagged = _moved_cf("antes")
    unflagged["manual_edits"][0].pop("unproduced_today")
    assert store.protected_changes(unflagged, now=now, unproduced="CF") is not None


def test_the_store_lets_desfazer_take_back_only_the_move_the_active_plan_made(
    tmp_path, monkeypatch,
):
    previous = _state(_BEFORE_RECORD)
    store = _store_with(tmp_path, monkeypatch, [
        ("antes", previous, None), ("movido", _moved_cf("antes"), "antes"),
    ], "movido")
    now = _lisbon(10, 5)
    assert store.protected_changes(previous, now=now, undo_restores="antes") is None
    assert store.protected_changes(previous, now=now) is not None
    assert store.protected_changes(previous, now=now, undo_restores="movido") is not None
    # A move recorded over another version gives no leeway.
    other = _store_with(tmp_path / "b", monkeypatch, [
        ("antes", previous, None), ("movido", _moved_cf("outra"), "antes"),
    ], "movido")
    assert other.protected_changes(previous, now=now, undo_restores="antes") is not None


def test_the_store_desfazer_takes_back_the_lot_the_move_put_in_the_freed_time(
    tmp_path, monkeypatch,
):
    previous, moved = _cf_out_bfp_in()
    moved["manual_edits"] = [{
        "lot_id": "CF", "previous_version_id": "antes", "unproduced_today": True,
    }]
    store = _store_with(tmp_path, monkeypatch, [
        ("antes", previous, None), ("movido", moved, "antes"),
    ], "movido")
    now = _lisbon(10, 5)
    assert store.protected_changes(previous, now=now, undo_restores="antes") is None
    assert store.protected_changes(previous, now=now) is not None


def test_apply_refuses_a_move_as_not_produced_its_check_did_not_show(morning):
    from fastapi import HTTPException

    from backend.api.manual_plan import _require_executed_preview

    move = _move(
        morning.baseline, morning.data, morning.config, morning.lots["OP1"].id, 3, 420,
        _at(TODAY, 540),
    )
    _require_executed_preview(move)
    unseen = copy.copy(move)
    unseen.notice = None
    with pytest.raises(HTTPException) as refused:
        _require_executed_preview(unseen)
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "preview_required"


def _big_morning():
    """Today is day 0 (D0): Y (1500 pieces, 15 h) 07:00–22:30 by the plan."""
    config = _config()
    data = _data([_op("OP1", "T1", 0), _op("OP2", "T2", 6)])
    data.ops[0].d[0] = 1500
    baseline, lots = _plan(data, config, {
        "OP1": [(0, 420, 1500, 30)], "OP2": [(3, 420, 200, 30)],
    })
    return config, data, baseline, lots


def test_recalculate_does_not_put_the_lot_back_in_the_morning():
    """«Recalcular plano» plans from D0 (00:00 today) and releases the pin;
    the morning the lot left stays free of it up to now."""
    config, data, baseline, lots = _big_morning()
    y = lots["OP1"].id
    ten = _at(0, 600)
    move = _move(baseline, data, config, y, 3, 420, ten)
    applied, plan = _unproduced(move, data)
    applied.plan_anchors = []  # «Recalcular» releases ordinary pins
    later = _at(0, 615)

    def first_today(engine):
        result = frozen.optimize_preserving_started_lots(
            engine, config, copy.deepcopy(plan), mode="quick", now=later,
            recalculate_from_start=True,
        )
        return min(
            (s.day_idx, s.start_min) for s in result.segments
            if s.lot_id in {lot.id for lot in result.lots if lot.op_id == "OP1"}
            and s.end_min > s.start_min
        )

    assert first_today(copy.deepcopy(applied)) >= (0, 615)
    # Without the fact (another day, or a new ISOP) it plans from D0 again.
    plain = copy.deepcopy(applied)
    plain.unproduced_today = []
    assert first_today(plain) < (0, 600)
    stale = copy.deepcopy(applied)
    stale.unproduced_today[0]["date"] = data.workdays[1][:10]
    assert first_today(stale) < (0, 600)


# ── Revisão de 23/10/2026 do lote começado hoje ─────────────────────────────


@pytest.mark.parametrize("start", [600, 720])
@pytest.mark.parametrize("qty", [200, 600])
def test_recalculate_keeps_a_lot_that_started_mid_morning_out_of_the_morning(start, qty):
    """By the plan the lot started at 10:00 (or 12:00), not at 07:00. The
    whole morning stays free of it: «Recalcular plano» neither puts it back
    at 07:00 (200 pieces) nor splits it around the block (600 pieces, which
    made the whole recalculation fail with «lot_split»)."""
    config = _config()
    data = _data([_op("OP1", "T1", 0), _op("OP2", "T2", 6)])
    data.ops[0].d[0] = qty
    baseline, lots = _plan(data, config, {
        "OP1": [(0, start, qty, 30)], "OP2": [(3, 420, 200, 30)],
    })
    move = _move(baseline, data, config, lots["OP1"].id, 3, 420, _at(0, start + 60))
    applied, plan = _unproduced(move, data)
    applied.plan_anchors = []  # «Recalcular» releases ordinary pins
    result = frozen.optimize_preserving_started_lots(
        applied, config, plan, mode="quick", now=_at(0, start + 65),
        recalculate_from_start=True,
    )
    ids = {lot.id for lot in result.lots if lot.op_id == "OP1"}
    rows = [s for s in result.segments if s.lot_id in ids and s.end_min > s.start_min]
    assert min((s.day_idx, s.start_min) for s in rows) >= (0, start + 65)


def _family_morning():
    """M1/T1 with setup family {SKU_OP1, SKU_OP3} (like JDE002): A (OP1)
    07:00–09:30 mounts T1, B (OP3) follows it from 09:30 without setup."""
    config = _config()
    config.setup_families = {"T1": [["SKU_OP1", "SKU_OP3"]]}
    data = _data([_op("OP1", "T1", 4), _op("OP3", "T1", 4), _op("OP2", "T2", 6)])
    lots = {lot.op_id: lot for lot in create_lots(data, config)}
    lots["OP3"].setup_min = 0.0

    def row(lot, day, start, setup):
        return Segment(
            lot.id, f"quantity:{lot.id}:0", lot.machine_id, lot.tool_id, day, start,
            start + int(setup + lot.prod_min), "A", lot.qty, lot.prod_min, setup,
            sku=lot.sku, lot_qty=lot.qty, output_milestones=copy.deepcopy(lot.output_milestones),
            setup_family=lot.setup_family,
        )

    baseline = ScheduleResult(
        segments=[
            row(lots["OP1"], TODAY, 420, 30), row(lots["OP3"], TODAY, 570, 0),
            row(lots["OP2"], 3, 700, 30),
        ],
        lots=list(lots.values()), score={}, time_ms=0, warnings=[], operator_alerts=[],
    )
    return config, data, baseline, lots


def test_a_lot_that_mounted_the_tool_for_a_started_continuation_stays():
    """At 10:00 B has run since 09:30 on the mount A made. Moving A as not
    produced would leave B in history with no setup and no mount (and every
    «Recalcular plano» invalid): refused, with what to do instead."""
    config, data, baseline, lots = _family_morning()
    assert_plan_valid(baseline.segments, data, config, lots=baseline.lots)
    ten = _at(TODAY, 600)
    with pytest.raises(ManualMoveError) as refused:
        _move(baseline, data, config, lots["OP1"].id, 3, 420, ten)
    assert str(refused.value) == (
        "A Referência SKU_OP1 · T1 (M1) não pode ser movida: a Referência SKU_OP3 · T1 "
        "(M1) das 09:30 já começou a seguir dela, sem afinação, com a ferramenta que ela "
        "montou. Mova primeiro a Referência SKU_OP3 · T1 (M1) das 09:30."
    )
    # B itself, only started today, moves as not produced.
    moved = _move(baseline, data, config, lots["OP3"].id, 3, 420, ten)
    assert moved.unproduced_today and moved.unproduced_today["lot_id"] == lots["OP3"].id


def test_a_lot_cut_by_another_lots_record_stays_frozen(morning):
    """At 11:00 OP2 is recorded as run from 10:30 on M1: OP1 «fica feita até
    às 10:00 (150 peças)». Moving OP1 at 11:10 as not produced would erase
    those 150 pieces: refused like a started lot, in the move and in the
    commit guard."""
    op1, op2 = morning.lots["OP1"].id, morning.lots["OP2"].id
    record = _move(
        morning.baseline, morning.data, morning.config, op2, TODAY, 630, _at(TODAY, 660),
    )
    recorded = copy.deepcopy(morning.data)
    recorded.plan_anchors = [_record(record, recorded)]
    recorded.history_boundary = list(record.history_boundary)
    plan = ScheduleResult(record.segments, record.lots, record.score, 0, [], [],
                          history_boundary=list(record.history_boundary))
    later = _at(TODAY, 670)
    with pytest.raises(ManualMoveError) as refused:
        _move(plan, recorded, morning.config, op1, 3, 700, later)
    assert str(refused.value) == (
        "A Referência SKU_OP1 · T1 (M1) fica feita até às 10:00 (150 peças) pelo registo "
        "do que correu da Referência SKU_OP2 · T2 (M1); está congelada e não pode ser movida."
    )
    moved = copy.deepcopy(plan.segments)
    for segment in moved:
        if segment.lot_id == op1:
            segment.day_idx, segment.start_min, segment.end_min = 3, 670, 820
    before = _snapshot(plan.segments, plan.lots, recorded, anchors=recorded.plan_anchors,
                       boundary=plan.history_boundary)
    after = _snapshot(moved, plan.lots, recorded, anchors=recorded.plan_anchors,
                      boundary=plan.history_boundary)
    assert frozen.historical_schedule_changes(
        before, after, now=later, unproduced=("before", op1),
    ) == [op1]


def test_the_fact_is_kept_only_when_present():
    from backend.plans.serialize import _jsonable, deserialize_engine_data

    data = EngineData(
        ops=[], machines=[], twin_groups=[], client_demands={}, workdays=[], n_days=0,
    )
    assert "unproduced_today" not in _jsonable(data)
    data.unproduced_today = [{"lot_id": "A", "tool_id": "T1", "date": "2026-10-21",
                              "start_min": 420, "since": 634}]
    raw = _jsonable(data)
    assert deserialize_engine_data(raw).unproduced_today == data.unproduced_today


@pytest.fixture
def morning_api(tmp_path, monkeypatch, morning):
    """The ``morning`` plan as the active version, the clock at 09:00 today."""
    from fastapi.testclient import TestClient

    import backend.calendar as factory_calendar
    from backend.api.copilot import app
    from backend.config import loader
    from backend.copilot.state import state
    from backend.plans.serialize import serialize_snapshot
    from backend.plans.store import PlansStore
    from backend.scheduler.gates import build_gate_report
    from backend.scheduler.scoring import compute_score

    clock = {"now": _at(TODAY, 540)}
    monkeypatch.setattr(factory_calendar, "_wall_clock", lambda zone: clock["now"])
    config_path = tmp_path / "factory.yaml"
    monkeypatch.setattr(loader, "DEFAULT_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(loader.save_config, "__defaults__", (str(config_path),))
    previous = {key: getattr(state, key) for key in state.__dataclass_fields__}
    store = PlansStore(tmp_path / "plans.db")
    data, config, plan = morning.data, copy.deepcopy(morning.config), copy.deepcopy(morning.baseline)
    config.tools.pop("T4")  # its machine M2 is not in this plan
    plan.score = compute_score(plan.segments, plan.lots, data, config=config)
    plan.gate_report = build_gate_report(plan.segments, plan.lots, plan.score, data, config)
    state.engine_data, state.config, state.default_config = data, config, config
    # A dataset id: the commit guard compares versions of the same dataset.
    state.dataset_info = {"id": "ds", "filename": "isop.xlsx"}
    state.active_mutations, state.manual_edits, state.approvals = [], [], []
    state.saved_schedule = state.saved_mutations = state.saved_manual_edits = None
    state.plans_store = store
    state.update_schedule(plan)
    loader.save_config(config, path=str(config_path))
    store.save(
        name="Plano da manhã", source="auto", origin="", note="", payload=serialize_snapshot(state),
        score=state.score, gate_report=state.gate_report, is_auto=True, activate=True,
    )
    yield SimpleNamespace(client=TestClient(app), store=store, state=state, clock=clock)
    store.close()
    for key, value in previous.items():
        setattr(state, key, value)


def _api_move(api, lot_id, day, minute, **extra):
    body = {"lot_id": lot_id, "target_day": day, "target_machine": "M1",
            "target_start_min": minute, **extra}
    preview = api.client.post("/api/data/plan/move-preview", json=body)
    assert preview.status_code == 200, preview.text
    applied = api.client.post("/api/data/plan/move-apply", json={
        **body, "candidate_id": preview.json()["candidate_id"],
        "expected_revision": api.state.plan_revision, "confirm_delivery_risk": True,
        "approve_exceptions": True, "approval_reason": "teste", "approval_author": "pytest",
        "reason": "teste", "author": "pytest",
    })
    return preview.json(), applied


def test_api_moves_a_lot_started_today_and_desfazer_takes_it_back(morning_api, morning):
    """The whole path: check, apply (the server's signal reaches the commit
    guard), the fact for «Recalcular», then «Desfazer» the same day. What the
    request says about it is never read."""
    api, op1 = morning_api, morning.lots["OP1"].id
    start = sorted((s.lot_id, s.day_idx, s.start_min) for s in api.state.segments)
    preview, applied = _api_move(api, op1, 3, 420, unproduced_today=False, unproduced=None)
    assert preview["unproduced_today"] is True and "não produzida hoje" in preview["notice"]
    assert applied.status_code == 200, applied.text
    assert applied.json()["edit"]["unproduced_today"] is True
    assert api.state.engine_data.unproduced_today == [{
        "lot_id": op1, "tool_id": "T1", "date": morning.data.workdays[TODAY][:10],
        "start_min": 480, "since": 540,
    }]
    assert not [s for s in api.state.segments
                if s.day_idx == TODAY and s.start_min < 540 and s.end_min > s.start_min]
    stored = api.store.active()["payload"]
    assert stored["engine_data"]["unproduced_today"][0]["lot_id"] == op1
    api.clock["now"] = _at(TODAY, 545)
    undone = api.client.post("/api/data/undo", json={
        "expected_revision": api.state.plan_revision, "approve_exceptions": True,
        "approval_reason": "teste", "approval_author": "pytest",
    })
    assert undone.status_code == 200, undone.text
    assert sorted((s.lot_id, s.day_idx, s.start_min) for s in api.state.segments) == start
    assert api.state.engine_data.unproduced_today == []


def test_api_ignores_what_the_request_says_about_not_produced(morning_api, morning):
    api, op2 = morning_api, morning.lots["OP2"].id
    preview, applied = _api_move(api, op2, 4, 420, unproduced_today=True, unproduced=op2)
    assert preview["unproduced_today"] is False and preview["notice"] is None
    assert applied.status_code == 200, applied.text
    assert "unproduced_today" not in applied.json()["edit"]
    assert api.state.engine_data.unproduced_today == []


def test_api_commit_refuses_the_move_without_the_servers_signal(morning_api, morning, monkeypatch):
    """The commit guard, not the check, decides: without the signal the
    same move is refused and the active plan stays."""
    from backend.plans import context

    original = context.set_change_label
    monkeypatch.setattr(
        context, "set_change_label",
        lambda label, **kwargs: original(label, **{**kwargs, "unproduced": None}),
    )
    api = morning_api
    revision = api.state.plan_revision
    _preview, applied = _api_move(api, morning.lots["OP1"].id, 3, 420)
    assert applied.status_code == 409, applied.text
    assert applied.json()["detail"]["code"] == "historical_plan_protected"
    assert api.state.plan_revision == revision
    assert api.state.engine_data.unproduced_today == []
