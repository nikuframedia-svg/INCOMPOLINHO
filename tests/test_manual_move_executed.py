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
    assert frozen.historical_schedule_changes(record, previous, now=_lisbon(11, 52)) == []
    assert frozen.historical_schedule_changes(record, previous, now=_lisbon(14, 0)) == ["CF"]


def test_desfazer_later_is_not_blocked_by_work_the_same_in_both_plans():
    """Y on M30 from 12:30 is identical in both plans; CF waits for 15:00."""
    same = [_row("Y", "M30", "T8", 750, 900, 100), _row("Z", "M20", "T9", 360, 1080, 800)]
    record = _state(_after_record(900) + same, recorded=True)
    previous = _state(_BEFORE_RECORD + same)
    assert frozen.historical_schedule_changes(record, previous, now=_lisbon(14, 0)) == []


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
    assert frozen.historical_schedule_changes(later, previous, now=_lisbon(15, 25)) == []
    assert frozen.historical_schedule_changes(later, previous, now=_lisbon(15, 40)) == []
    assert frozen.historical_schedule_changes(later, previous, now=_lisbon(13, 30)) == []
    started = _state(_after_record(720) + [_row("Y", "M44", "T5", 1320, 1400, 100)],
                     recorded=True)
    assert frozen.historical_schedule_changes(started, previous, now=_lisbon(15, 40)) == ["CF"]
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
    assert frozen.historical_schedule_changes(record, previous, now=_lisbon(14, 0)) == []
    # Once CF has started on M44 it is still refused.
    started = _state(_after_record(720), recorded=True)
    assert frozen.historical_schedule_changes(started, previous, now=_lisbon(14, 0)) == ["CF"]
    # A plan where the lot had started before the record's instant is not
    # the one it replaced: no exception.
    earlier = _state([
        _row("CF", "M43", "T1", 420, 950, 1000, setup=60),
        _row("JTE", "M30", "T2", 600, 1300, 500, setup=60),
    ])
    assert frozen.historical_schedule_changes(record, earlier, now=_lisbon(14, 0))


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
    assert frozen.historical_schedule_changes(record, undone, now=_lisbon(14, 0)) == []


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
        assert frozen.historical_schedule_changes(record, previous, now=now) == []
    changed = _state([
        _row("JTE", "M43", "T2", 420, 600, 500, setup=60),
        _row("Z", "M43", "T5", 720, 840, 100),
        _row("CF", "M44", "T1", 1300, 1380, 100, setup=60),
    ], recorded=True)
    assert frozen.historical_schedule_changes(changed, previous, now=_lisbon(15, 10)) == ["Z"]
