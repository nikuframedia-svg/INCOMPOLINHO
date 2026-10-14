"""Late deliveries with idle capacity before their deadline (read-only check).

Real case: revision 127 (13/10/2026). PRM043 stood idle from 13 to 18/10
while one order (due 14/10) and one subcontract dispatch (16/10) were late.
The check never changes or blocks a plan; it is reported in the gate report
and as a plain notice. A real capacity shortage (PRM042 in revision 90, no
alternative machine) is never reported.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.config.planning import apply_effective_planning_config
from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler import idle_capacity
from backend.scheduler.gates import build_gate_report
from backend.scheduler.idle_capacity import idle_capacity_notice, late_with_idle_capacity
from backend.scheduler.improvement import order_service
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.types import Segment
from backend.types import ClientDemandEntry, EngineData, EOp, MachineInfo, TwinGroup
from tests.snapshot_fixture import load_snapshot

START = date(2026, 3, 2)  # a Monday: days 5 and 6 are a weekend
DAY_MIN = 1020  # default shifts A 07:00-15:30 and B 15:30-00:00
LISBON = ZoneInfo("Europe/Lisbon")


def _at(day: int, minute: int, start: date = START) -> datetime:
    """Factory time ``minute`` of plan day ``day``."""
    when = start + timedelta(days=day)
    return datetime(when.year, when.month, when.day, minute // 60, minute % 60, tzinfo=LISBON)


def _op(op_id, tool, *, machine="M1", alt=None, due_day=4, qty=200, sku=None):
    demand = [0] * 14
    demand[due_day] = qty
    return EOp(
        id=op_id, sku=sku or op_id, client="C", designation="Peça", m=machine, t=tool,
        pH=100, sH=0.5, operators=1, eco_lot=qty, alt=alt, stk=0, backlog=0, d=demand,
        oee=1.0, wip=0,
    )


def _config(*machines) -> FactoryConfig:
    return FactoryConfig(machines={m: MachineConfig(m, "Grandes") for m in machines or ("M1",)})


def _data(*ops) -> EngineData:
    days = [(START + timedelta(days=i)).isoformat() for i in range(14)]
    machines = sorted({op.m for op in ops} | {op.alt for op in ops if op.alt})
    return EngineData(
        ops=list(ops), machines=[MachineInfo(m, "Grandes", DAY_MIN) for m in machines],
        twin_groups=[], client_demands={}, workdays=days, n_days=len(days),
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )


def _segments(lot, blocks, machine=None):
    """``blocks``: (day, start, qty, setup) of one lot."""
    segments = []
    for day, start, qty, setup in blocks:
        prod = lot.prod_min * qty / lot.qty
        segments.append(Segment(
            lot.id, f"run:{lot.id}", machine or lot.machine_id, lot.tool_id, day, start,
            start + int(setup + prod), "A" if start < 930 else "B", qty, prod, setup,
            sku=lot.sku, lot_qty=lot.qty, output_milestones=copy.deepcopy(lot.output_milestones),
        ))
    return segments


def _filler(machine, tool, days, sku="FILL"):
    """Production of another operation on every shift minute of ``days``."""
    return [
        Segment(f"LOT_{sku}_{machine}", f"run:{sku}", machine, tool, day, 420, 1440, "A",
                1020, 1020.0, sku=sku)
        for day in days
    ]


def _lots(data, config):
    return {lot.op_id: lot for lot in create_lots(data, config)}


def _late_plan(*, alt=None):
    """200 pieces (120 min) due on day 4, produced on day 7: three days late."""
    data = _data(_op("OP1", "T1", alt=alt))
    config = _config("M1", *([alt] if alt else []))
    lot = _lots(data, config)["OP1"]
    return data, config, lot, _segments(lot, [(7, 420, 200, 30)])


def test_late_delivery_with_idle_machine_is_reported():
    data, config, lot, segments = _late_plan()
    assert order_service(segments, [lot], data)  # the order is known and late

    (case,) = late_with_idle_capacity(segments, [lot], data, config, planning_day=0)

    assert case["sku"] == "OP1" and case["machine_id"] == "M1"
    assert (case["customer_delivery_day"], case["production_due_day"]) == (4, 4)
    assert case["window_start_day"] == 0 and case["shortfall_qty"] == 200
    # 120 min of production and one setup (nothing mounted before) ...
    assert case["needed_min"] == pytest.approx(120 + lot.setup_min)
    # ... against days 0-4 free (the late production is on day 7).
    assert case["free_min"] == 5 * DAY_MIN


def test_late_delivery_without_free_capacity_is_not_reported():
    data, config, lot, segments = _late_plan()
    busy = _filler("M1", "T9", range(0, 5))

    assert late_with_idle_capacity(segments + busy, [lot], data, config, planning_day=0) == []
    # A sliver of free time is no capacity either.
    sliver = [replace_end(segment, 1440 - 25) for segment in busy]
    assert late_with_idle_capacity(segments + sliver, [lot], data, config, planning_day=0) == []
    # Free minutes below what the delivery needs are not enough.
    short = [replace_end(segment, 1440 - 20) for segment in busy[:-1]] + busy[-1:]
    short[0] = replace_end(busy[0], 1440 - 100)
    assert late_with_idle_capacity(segments + short, [lot], data, config, planning_day=0) == []


def replace_end(segment, end_min):
    shorter = copy.copy(segment)
    shorter.end_min = end_min
    shorter.prod_min = float(end_min - segment.start_min)
    return shorter


def replace_start(segment, start_min):
    shorter = copy.copy(segment)
    shorter.start_min = start_min
    shorter.prod_min = float(segment.end_min - start_min)
    return shorter


def test_outage_tool_elsewhere_and_missing_operators_are_not_free_time():
    data, config, lot, segments = _late_plan()

    outage = copy.deepcopy(data)
    outage.machine_blocked_days = {"M1": set(range(0, 5))}
    assert late_with_idle_capacity(segments, [lot], outage, config, planning_day=0) == []

    partial = copy.deepcopy(data)
    partial.machine_blocked_intervals = {"M1": [
        {"start_day": day, "start_min": 420, "end_min": 1440} for day in range(0, 5)
    ]}
    assert late_with_idle_capacity(segments, [lot], partial, config, planning_day=0) == []

    tool_away = _filler("M2", lot.tool_id, range(0, 5))
    assert late_with_idle_capacity(segments + tool_away, [lot], data, config,
                                   planning_day=0) == []

    no_crew = copy.deepcopy(config)
    no_crew.operators = {**config.operators, ("Grandes", "A"): 0, ("Grandes", "B"): 0}
    assert late_with_idle_capacity(segments, [lot], data, no_crew, planning_day=0) == []


def test_window_starts_at_the_planning_day_and_material_release():
    data, config, lot, segments = _late_plan()
    # From day 4 only the deadline day itself is left, still enough.
    (case,) = late_with_idle_capacity(segments, [lot], data, config, planning_day=4)
    assert case["window_start_day"] == 4 and case["free_min"] == DAY_MIN
    # Past the deadline nothing can be done: no case.
    assert late_with_idle_capacity(segments, [lot], data, config, planning_day=5) == []
    # Material released on the deadline day: only that day counts.
    late_release = copy.deepcopy(lot)
    for output in late_release.output_milestones:
        output["material_release_day"] = 4
    busy = _filler("M1", "T9", [4])
    assert late_with_idle_capacity(segments + busy, [late_release], data, config,
                                   planning_day=0) == []


def test_alternative_machine_counts_unless_the_lot_has_started():
    data, config, lot, segments = _late_plan(alt="M2")
    busy = _filler("M1", "T9", range(0, 5))

    (case,) = late_with_idle_capacity(segments + busy, [lot], data, config, planning_day=0)
    assert case["machine_id"] == "M2"

    # Started before the planning day on M1: the rest stays on M1 (rule 4).
    started = _segments(lot, [(0, 420, 50, 30), (7, 420, 150, 0)])
    assert late_with_idle_capacity(
        started + _filler("M1", "T9", range(1, 5)), [lot], data, config, planning_day=1,
    ) == []
    # Production on the planning day itself has started too.
    today = _segments(lot, [(1, 420, 50, 30), (7, 420, 150, 0)])
    rest_of_today = [replace_start(segment, today[0].end_min) for segment in _filler("M1", "T9", [1])]
    assert late_with_idle_capacity(
        today + rest_of_today + _filler("M1", "T9", [2, 3, 4]), [lot], data, config,
        planning_day=1,
    ) == []


def test_alternative_machine_needs_the_whole_lot():
    """Rule 3: a lot changes machine as a whole, never only its missing pieces."""
    data = _data(_op("OP1", "T1", alt="M2", qty=1000))
    config = _config("M1", "M2")
    lot = _lots(data, config)["OP1"]
    assert lot.prod_min == pytest.approx(600)
    # 900 pieces by day 2, the last 100 on day 7: 100 missing on day 4.
    segments = _segments(lot, [(2, 420, 900, 30), (7, 420, 100, 0)])
    m1_busy = [*_filler("M1", "T9", [0, 1, 3, 4]),
               *[replace_start(segment, 990) for segment in _filler("M1", "T9", [2])]]
    # M2 is free for 200 minutes on day 0 only: enough for 100 pieces (60 min
    # and a setup), not for the whole lot (600 min and a setup).
    m2_busy = [replace_start(segment, 420 + 200) for segment in _filler("M2", "T8", [0])]
    m2_busy += _filler("M2", "T8", [1, 2, 3, 4])
    plan = segments + m1_busy + m2_busy
    assert late_with_idle_capacity(plan, [lot], data, config, planning_day=0) == []

    roomy = segments + m1_busy + _filler("M2", "T8", [1, 2, 3, 4])
    (case,) = late_with_idle_capacity(roomy, [lot], data, config, planning_day=0)
    assert case["machine_id"] == "M2" and case["whole_lot"]
    assert case["needed_min"] == pytest.approx(600 + lot.setup_min)
    assert case["shortfall_qty"] == 100


def test_pieces_available_at_the_lot_end_need_the_whole_rest():
    """Cycle rule (legacy lots): idle time helps only if the rest of the lot fits."""
    data = _data(_op("OP1", "T1", qty=1000))
    data.ops[0].d[4] = 100
    data.ops[0].d[11] = 900
    config = _config("M1")
    lot = _lots(data, config)["OP1"]
    assert lot.qty == 1000
    segments = _segments(lot, [(7, 420, 1000, 30)])
    # M1 has 200 free minutes before day 4: 100 pieces (60 min) would fit.
    busy = [replace_start(segment, 420 + 200) for segment in _filler("M1", "T9", [0])]
    busy += _filler("M1", "T9", [1, 2, 3, 4])
    (case,) = late_with_idle_capacity(segments + busy, [lot], data, config, planning_day=0)
    assert not case["whole_lot"] and case["shortfall_qty"] == 100

    legacy = copy.deepcopy(lot)
    for output in legacy.output_milestones:
        output["quantity_material_version"] = 0
    legacy_segments = _segments(legacy, [(7, 420, 1000, 30)])
    assert late_with_idle_capacity(legacy_segments + busy, [legacy], data, config,
                                   planning_day=0) == []
    # With the whole day free the whole lot fits, and that is what it needs.
    (case,) = late_with_idle_capacity(legacy_segments + busy[1:], [legacy], data, config,
                                      planning_day=0)
    assert case["whole_lot"]
    assert case["needed_min"] == pytest.approx(lot.prod_min + lot.setup_min)


def test_today_counts_only_after_the_current_minute():
    data, config, lot, segments = _late_plan()
    # Planning day 4 is the deadline: 120 min and a setup are needed.
    (case,) = late_with_idle_capacity(segments, [lot], data, config, planning_day=4,
                                      now=_at(4, 15 * 60))
    assert case["free_min"] == 1440 - 15 * 60
    assert late_with_idle_capacity(segments, [lot], data, config, planning_day=4,
                                   now=_at(4, 22 * 60 + 30)) == []
    # Replayed on another date, the whole planning day counts.
    (case,) = late_with_idle_capacity(segments, [lot], data, config, planning_day=4,
                                      now=_at(40, 22 * 60))
    assert case["free_min"] == DAY_MIN


TWIN_START = date(2026, 10, 12)  # a Monday


def _twin_plan(b_due: int = 14):
    """Twin cycle A (1000 on day 14) + B (2500 on ``b_due``), 3000 cycles in 120 min."""
    days = [(TWIN_START + timedelta(days=i)).isoformat() for i in range(30)]
    ops = []
    for op_id, sku, due, qty in (("TA", "A", 14, 1000), ("TB", "B", b_due, 2500)):
        demand = [0] * len(days)
        demand[due] = qty
        ops.append(EOp(
            id=op_id, sku=sku, client="C", designation=sku, m="M1", t="TT", pH=1500, sH=0.5,
            operators=1, eco_lot=3000, alt=None, stk=0, backlog=0, d=demand, oee=1.0, wip=0,
        ))
    data = EngineData(
        ops=ops, machines=[MachineInfo("M1", "Grandes", DAY_MIN)],
        twin_groups=[TwinGroup("TT", "M1", "TA", "TB", "A", "B", 3000, 3000)],
        client_demands={
            op.sku: [ClientDemandEntry("C", op.sku, day, days[day], qty, -qty)
                     for day, qty in enumerate(op.d) if qty]
            for op in ops
        },
        workdays=days, n_days=len(days),
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )
    config = _config("M1")
    (lot,) = create_lots(data, config)
    assert lot.is_twin
    segment = Segment(
        lot.id, f"run:{lot.id}", "M1", "TT", 20, 420, 420 + 30 + 120, "A", 3000, 120.0, 30.0,
        sku="A", lot_qty=3000, twin_outputs=list(lot.twin_outputs),
        output_milestones=copy.deepcopy(lot.output_milestones),
    )
    return data, config, lot, [segment]


def test_twin_sides_are_one_case():
    data, config, lot, segments = _twin_plan()

    (case,) = late_with_idle_capacity(segments, [lot], data, config, planning_day=7,
                                      now=_at(40, 600, TWIN_START))

    assert case["lot_id"] == lot.id and case["skus"] == ["A", "B"]
    assert [item["customer_delivery_day"] for item in case["deliveries"]] == [14, 14]
    # The larger side (B, 2500 pieces) sets the cycles; A's 1000 come with them.
    assert case["shortfall_qty"] == 2500
    assert case["needed_min"] == pytest.approx(2500 * 120 / 3000 + lot.setup_min)
    assert idle_capacity_notice([case], data) == (
        "Possível melhoria: A e B (entrega 26/10) estão atrasadas e a M1 tem "
        "tempo livre suficiente antes do prazo."
    )

    # Sides due on different days: still one lot, listed once.
    data, config, lot, segments = _twin_plan(b_due=15)
    (case,) = late_with_idle_capacity(segments, [lot], data, config, planning_day=7,
                                      now=_at(40, 600, TWIN_START))
    assert case["lot_id"] == lot.id


def test_a_later_delivery_needs_the_earlier_ones_of_its_lot():
    """Pieces go first-in-first-out: recovering the delivery of day 4 alone is
    not enough when the delivery of day 2 of the same lot is late too."""
    data = _data(_op("OP1", "T1", qty=1000))
    data.ops[0].d[4] = 0
    data.ops[0].d[2] = 500
    data.ops[0].d[4] = 500
    config = _config("M1")
    lot = _lots(data, config)["OP1"]
    segments = _segments(lot, [(7, 420, 1000, 30)])
    # M1: busy on days 0-2; 400 free minutes over days 3 and 4.
    busy = _filler("M1", "T9", [0, 1, 2])
    busy += [replace_start(segment, 420 + 200) for segment in _filler("M1", "T9", [3, 4])]
    # Day 2 cannot be recovered; day 4 needs both deliveries: 600 min + setup.
    assert late_with_idle_capacity(segments + busy, [lot], data, config, planning_day=0) == []
    # With days 3 and 4 free (2040 min) both fit by day 4: one case for the lot.
    (case,) = late_with_idle_capacity(segments + busy[:3], [lot], data, config,
                                      planning_day=0)
    assert case["production_due_day"] == 4 and case["shortfall_qty"] == 1000
    assert [item["customer_delivery_day"] for item in case["deliveries"]] == [2, 4]


def test_mounted_tool_needs_no_setup():
    data, config, lot, _segments_unused = _late_plan()
    started = _segments(lot, [(0, 420, 100, 30), (7, 420, 100, 0)])

    (case,) = late_with_idle_capacity(started, [lot], data, config, planning_day=1)

    assert case["setup_min"] == 0 and case["shortfall_qty"] == 100
    assert case["needed_min"] == pytest.approx(lot.prod_min * 100 / lot.qty)


def test_two_late_deliveries_do_not_count_the_same_idle_time():
    first, second = _op("OP1", "T1", due_day=1, qty=1000), _op("OP2", "T2", due_day=1, qty=1000)
    data, config = _data(first, second), _config("M1")
    lots = _lots(data, config)
    segments = [
        *_segments(lots["OP1"], [(7, 420, 1000, 30)]),
        *_segments(lots["OP2"], [(8, 420, 1000, 30)]),
    ]
    # Day 1 has 1020 free minutes; each delivery needs 600 + setup.
    cases = late_with_idle_capacity(segments, list(lots.values()), data, config,
                                    planning_day=1)
    assert [case["sku"] for case in cases] == ["OP1"]


def test_subcontracted_delivery_is_judged_on_the_stock_by_its_customer_day():
    data = _data(_op("OP1", "T1", due_day=11))
    config = _config("M1")
    config.subcontract_companies = [{"id": "SUP", "name": "Sup", "lead_time_workdays": 5}]
    config.sku_subcontracts = {
        "OP1": {"enabled": True, "company_id": "SUP", "lead_time_workdays": 5, "buffer_days": 1},
    }
    apply_effective_planning_config(data, config)
    lot = _lots(data, config)["OP1"]
    assert lot.is_subcontracted and lot.latest_subcontract_dispatch_day == 4
    assert lot.subcontract_dispatch_day == 3  # the planned dispatch keeps a buffer day
    # 50 pieces on day 2, the rest on day 7: the dispatch (latest day 4) is
    # missed, but the stock covers the delivery on day 11 (Luís, 14/10/2026).
    missed_dispatch = _segments(lot, [(2, 420, 50, 30), (7, 420, 150, 30)])
    assert late_with_idle_capacity(missed_dispatch, [lot], data, config, planning_day=0) == []
    # The replan job still aims at the dispatch (``dispatch_targets``): the
    # lot goes out whole when it ends (13/10/2026), so the rest of the lot
    # (150 pieces) must be made by day 4.
    (aim,) = late_with_idle_capacity(missed_dispatch, [lot], data, config, planning_day=0,
                                     dispatch_targets=True)
    assert aim["production_due_day"] == 4 and aim["shortfall_qty"] == 200
    assert aim["lot_end_rule"]
    assert aim["needed_min"] == pytest.approx(aim["setup_min"] + lot.prod_min * 150 / 200)
    on_time = _segments(lot, [(4, 420, 200, 30)])
    assert late_with_idle_capacity(on_time, [lot], data, config, planning_day=0,
                                   dispatch_targets=True) == []

    # The rest on day 12: the stock is short on day 11, a late delivery whose
    # 150 missing pieces fit in the idle time before it.
    segments = _segments(lot, [(2, 420, 50, 30), (12, 420, 150, 30)])
    (case,) = late_with_idle_capacity(segments, [lot], data, config, planning_day=0)
    assert case["production_due_day"] == case["customer_delivery_day"] == 11
    assert case["shortfall_qty"] == 150 and not case["lot_end_rule"]
    assert case["needed_min"] == pytest.approx(case["setup_min"] + lot.prod_min * 150 / 200)
    notice = idle_capacity_notice([case], data)
    assert "entrega" in notice and "subcontrata" not in notice


def test_gate_report_lists_the_cases_and_never_blocks(monkeypatch):
    data, config, lot, segments = _late_plan()
    monkeypatch.setattr(idle_capacity, "current_factory_day", lambda *_args, **_kw: 0)

    report = build_gate_report(segments, [lot], {}, data, config)

    (case,) = report["idle_capacity_late"]
    assert case["machine_id"] == "M1" and case["customer_delivery_date"] == "2026-03-06"
    assert "idle_capacity" not in " ".join(report["approval_reasons"])
    on_time = _segments(lot, [(0, 420, 200, 30)])
    assert build_gate_report(on_time, [lot], {}, data, config)["idle_capacity_late"] == []


def test_a_failing_check_gives_no_cases(monkeypatch):
    data, config, lot, segments = _late_plan()

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(idle_capacity, "late_with_idle_capacity", broken)
    assert build_gate_report(segments, [lot], {}, data, config)["idle_capacity_late"] == []


def test_notice_lists_at_most_three_lots_in_plain_words():
    data = _data(_op("OP1", "T1"))
    case = {"sku": "A1", "customer_delivery_day": 4, "production_due_day": 4,
            "machine_id": "M1"}
    assert idle_capacity_notice([], data) is None
    assert idle_capacity_notice([case], data) == (
        "Possível melhoria: A1 (entrega 06/03) está atrasada e a M1 tem tempo livre "
        "suficiente antes do prazo."
    )
    many = [{**case, "sku": f"A{index}"} for index in range(1, 6)]
    assert idle_capacity_notice(many, data) == (
        "Possíveis melhorias: A1 (entrega 06/03), A2 (entrega 06/03), A3 (entrega 06/03) "
        "e mais 2 estão atrasadas e a M1 tem tempo livre suficiente antes dos prazos."
    )
    mixed = [case, {**case, "sku": "B1", "machine_id": "M2"}]
    assert idle_capacity_notice(mixed, data) == (
        "Possíveis melhorias: A1 (entrega 06/03) na M1 e B1 (entrega 06/03) na M2 estão "
        "atrasadas e essas máquinas têm tempo livre suficiente antes dos prazos."
    )
    # It says what is possible, never which button to press.
    assert all("Recalcular" not in idle_capacity_notice(cases, data)
               for cases in ([case], many, mixed))


def test_plan_notices_show_the_idle_capacity_note(monkeypatch):
    from backend.api.data import _plan_notices

    data, config, lot, segments = _late_plan()
    monkeypatch.setattr(idle_capacity, "current_factory_day", lambda *_args, **_kw: 0)
    notes = _plan_notices(segments, [lot], data, config)
    assert any(note.startswith("Possível melhoria: OP1") for note in notes)


# ── Real cases (private fixtures) ─────────────────────────────────────────


@pytest.mark.parametrize("name", ["rev90", "rev121", "rev124"])
def test_real_plans_have_no_late_delivery_with_idle_capacity(name):
    """Revision 90's late orders are a real PRM042 shortage: never reported."""
    snapshot = load_snapshot(name)
    result = snapshot.result
    cases = late_with_idle_capacity(result.segments, result.lots, snapshot.data,
                                    snapshot.config, planning_day=snapshot.freeze_day)
    assert cases == []


def test_rev90_late_orders_are_a_real_shortage():
    snapshot = load_snapshot("rev90")
    result = snapshot.result
    late = [key for key, item in order_service(result.segments, result.lots,
                                               snapshot.data).items() if item.tardiness > 0]
    assert late  # the check sees late orders and still reports none
    assert late_with_idle_capacity(result.segments, result.lots, snapshot.data,
                                   snapshot.config, planning_day=snapshot.freeze_day) == []


def _replan_time(snapshot, hour: int, minute: int) -> datetime:
    """``hour:minute`` of the snapshot's planning day, in the factory's time."""
    day = date.fromisoformat(str(snapshot.data.workdays[snapshot.freeze_day])[:10])
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=LISBON)


def test_rev127_stored_plan_reports_the_late_delivery_on_prm043():
    snapshot = load_snapshot("rev127")
    result = snapshot.result
    # Revision 127 was calculated on 13/10 at 15:39: the morning had gone by.
    cases = late_with_idle_capacity(result.segments, result.lots, snapshot.data,
                                    snapshot.config, planning_day=snapshot.freeze_day,
                                    now=_replan_time(snapshot, 15, 39))
    # CF589MMA1A02.20 only missed its subcontract dispatch: the stock covers
    # its delivery, so it is not late (Luís, 14/10/2026).
    assert [(case["sku"], case["machine_id"]) for case in cases] == [
        ("6800016767A.10", "PRM043"),
    ]
    assert all(case["free_min"] >= case["needed_min"] for case in cases)
    # The started JTE001 run is still mounted on PRM043: no setup needed.
    assert cases[0]["setup_min"] == 0


def test_rev126_outage_is_no_idle_capacity():
    """With the outage of PRM043 in place, the same lateness is legitimate."""
    snapshot = load_snapshot("rev126")
    result = snapshot.result
    assert late_with_idle_capacity(result.segments, result.lots, snapshot.data,
                                   snapshot.config, planning_day=snapshot.freeze_day) == []


PRM043_OUTAGE = {
    "kind": "machine", "resource": "PRM043", "start_at": "2026-10-12T11:30",
    "end_at": "2026-10-18T23:59", "category": "Avaria", "reason": "Teste",
    "id": "u_f3b000000001",
}


def _late_deliveries(payload):
    from backend.plans.serialize import deserialize_snapshot
    from backend.scheduler.improvement import subcontract_lateness

    restored = deserialize_snapshot(copy.deepcopy(payload))
    result, data = restored["result"], restored["engine_data"]
    orders = [key for key, item in order_service(result.segments, result.lots, data).items()
              if item.tardiness > 0]
    dispatches = [key for key, days in subcontract_lateness(
        result.segments, result.lots, data).items() if days > 0]
    return orders, dispatches, restored


def _calendar_replan(monkeypatch, baseline, planning_day, change, *, relaxed, now):
    from backend import calendar as factory_calendar
    from backend.plans import frozen
    from backend.plans.serialize import deserialize_snapshot
    from backend.replan import jobs

    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_args, **_kw: planning_day)
    monkeypatch.setattr(jobs, "_current_planning_day", lambda *_args, **_kw: planning_day)
    monkeypatch.setattr(factory_calendar, "factory_now",
                        lambda _config, *, now=None, fixed=now: (now or fixed).astimezone(LISBON))
    restored = deserialize_snapshot(copy.deepcopy(baseline))
    config, data = restored["config"], restored["engine_data"]
    change(config, data)
    store = jobs.ReplanJobStore(":memory:")
    manager = jobs.ReplanJobManager(store)
    dataset = baseline["dataset_info"]
    job = store.create("Indisponibilidades alteradas", dataset["id"], baseline["plan_revision"])
    try:
        manager._run(
            job["id"], data, config, dataset["id"], baseline["plan_revision"],
            "Indisponibilidades alteradas", dataset, baseline_snapshot=baseline,
            prefer_unchanged_baseline=not relaxed, reoptimize_relaxed_baseline=relaxed,
        )
    finally:
        manager.executor.shutdown(wait=True)
    final = store.get(job["id"])
    assert final["status"] == "ready", (final["message"], final.get("error"))
    return store.get_candidate(job["id"])


@pytest.mark.slow
@pytest.mark.acceptance
def test_outage_added_then_removed_leaves_no_idle_capacity(monkeypatch):
    """Golden flow F3b on revision 124: the sequence of revisions 126 and 127.

    PRM043 breaks down on 12/10 (planning day 3) and is repaired on 13/10
    (planning day 4), each change through the replan job. With the outage two
    deliveries are late for lack of PRM043; once it is removed, none is late
    with idle capacity and no more deliveries are late than before it.
    """
    from backend.config.unavailability import (
        add_unavailability_entry,
        remove_unavailability_entry,
    )
    from tests.snapshot_fixture import load_payload

    _manifest, payload = load_payload("rev124")
    before_orders, before_dispatches, _restored = _late_deliveries(payload)

    # The clock of golden flow F3b: added on 12/10 at 12:00, removed on 13/10 at 15:39.
    added_at = datetime(2026, 10, 12, 12, 0, tzinfo=LISBON)
    removed_at = datetime(2026, 10, 13, 15, 39, tzinfo=LISBON)
    with_outage = _calendar_replan(
        monkeypatch, payload, 3,
        lambda config, data: add_unavailability_entry(config, data, dict(PRM043_OUTAGE)),
        relaxed=False, now=added_at,
    )
    outage_orders, _dispatches, restored = _late_deliveries(with_outage)
    result = restored["result"]
    assert len(outage_orders) > len(before_orders)
    assert late_with_idle_capacity(result.segments, result.lots, restored["engine_data"],
                                   restored["config"], planning_day=3, now=added_at) == []

    repaired = _calendar_replan(
        monkeypatch, with_outage, 4,
        lambda config, _data: remove_unavailability_entry(config, PRM043_OUTAGE["id"]),
        relaxed=True, now=removed_at,
    )
    orders, dispatches, restored = _late_deliveries(repaired)
    result = restored["result"]
    assert late_with_idle_capacity(result.segments, result.lots, restored["engine_data"],
                                   restored["config"], planning_day=4, now=removed_at) == []
    assert len(orders) <= len(before_orders)
    assert len(dispatches) <= len(before_dispatches)
