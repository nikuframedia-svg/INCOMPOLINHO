"""A moved lot must fit in one production, checked before any reorganisation.

Decision of 15/10/2026 (Luís, after moving JTE001 to 03/12 08:45 at
Incompol): when setup + production cannot run in a row from the requested
start before the next work that stays where it is, the move is refused at
once, in plain words, with the first start where the lot does fit. Nights,
weekends, holidays and unavailabilities may interrupt the lot; free shift
time and other work may not (AGENTS §2, «Lote económico = uma produção»).
"""

from __future__ import annotations

import copy
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.plans.manual_move import ManualMoveError, _production_start, move_lot
from backend.plans.move_fit import DAY_MIN, MachineTimeline, earliest_fit, hours_text
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import ScheduleResult, Segment
from backend.scheduler.validation import assert_plan_valid
from backend.types import EngineData, EOp, MachineInfo, PlanAnchor
from tests.snapshot_fixture import load_payload

LISBON = ZoneInfo("Europe/Lisbon")
START = date(2026, 3, 2)  # a Monday
SETUP = 30
LONG_PROD = 900  # 1500 pieces at 100/h


# ── synthetic plan ──────────────────────────────────────────────────────────


def _config() -> FactoryConfig:
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    config.tools = {tool: {"primary": "M1", "setup_hours": 0.5} for tool in ("T1", "T2", "T3")}
    return config


def _op(op_id, sku, tool, demand):
    return EOp(
        id=op_id, sku=sku, client="C", designation="Peça", m="M1", t=tool, pH=100,
        sH=0.5, operators=1, eco_lot=0, alt=None, stk=0, backlog=0, d=demand,
        oee=1.0, wip=0,
    )


def _data(holidays=()) -> EngineData:
    days = [(START + timedelta(days=i)).isoformat() for i in range(28)]
    long_demand, short_demand, free_demand = ([0] * len(days) for _ in range(3))
    long_demand[18], short_demand[16], free_demand[18] = 1500, 100, 100
    return EngineData(
        ops=[_op("OP1", "SKU1", "T1", long_demand), _op("OP2", "SKU2", "T2", short_demand),
             _op("OP3", "SKU3", "T3", free_demand)],
        machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[], client_demands={},
        workdays=days, n_days=len(days),
        holidays=[
            i for i, day in enumerate(days)
            if date.fromisoformat(day).weekday() >= 5 or i in holidays
        ],
    )


def _workday(data, day):
    return day not in set(data.holidays)


def _run(lot, data, day, start, setup, run_id):
    """Segments of ``lot`` from ``day``/``start``, through shifts and workdays."""
    segments, remaining, setup_left, used = [], lot.prod_min, setup, 0
    while remaining > 0.01:
        if _workday(data, day):
            for shift, low, high in (("A", 420, 930), ("B", 930, 1440)):
                if start >= high or remaining <= 0.01:
                    continue
                begin = max(start, low)
                prod = min(remaining, high - begin - setup_left)
                last = remaining - prod <= 0.01
                qty = lot.qty - used if last else round(lot.qty * prod / lot.prod_min)
                segments.append(Segment(
                    lot.id, run_id, "M1", lot.tool_id, day, begin,
                    begin + int(setup_left + prod), shift, qty, prod, setup_left,
                    sku=lot.sku, lot_qty=lot.qty, is_continuation=bool(segments),
                    output_milestones=copy.deepcopy(lot.output_milestones),
                ))
                remaining, used, setup_left = remaining - prod, used + qty, 0
        day, start = day + 1, 0
    return segments


def _scenario():
    """Lot P (tool T2) pinned by hand at ``day`` 12:00, lot F (tool T3, free to
    move) right after it and lot L (15 h) on the next working day."""
    data, config = _data(), _config()
    lots = {lot.op_id: lot for lot in create_lots(data, config)}
    long_lot, short_lot, free_lot = lots["OP1"], lots["OP2"], lots["OP3"]
    assert round(long_lot.prod_min) == LONG_PROD and round(short_lot.prod_min) == 60
    day = max(long_lot.material_release_day, short_lot.material_release_day)
    while not _workday(data, day):
        day += 1
    pinned_day, later_day = day, day + 1
    while not _workday(data, later_day):
        later_day += 1
    segments = [
        *_run(short_lot, data, pinned_day, 690, SETUP, "RUN_P"),
        *_run(free_lot, data, pinned_day, 780, SETUP, "RUN_F"),
        *_run(long_lot, data, later_day, 420, SETUP, "RUN_L"),
    ]
    data.plan_anchors = [PlanAnchor(
        short_lot.id, "M1", f"{data.workdays[pinned_day]}T12:00", reason="teste",
    )]
    all_lots = [long_lot, short_lot, free_lot]
    assert_plan_valid(segments, data, config, lots=all_lots)
    baseline = ScheduleResult(
        segments=segments, lots=all_lots,
        score=compute_score(segments, all_lots, data, config), time_ms=0, warnings=[],
        operator_alerts=[],
    )
    now = datetime.combine(START, datetime.min.time()).replace(hour=6, tzinfo=LISBON)
    return data, config, baseline, long_lot, short_lot, pinned_day, now


def _move(baseline, data, config, lot_id, day, minute, now):
    return move_lot(
        baseline.segments, baseline.lots, baseline.score, data, config,
        lot_id=lot_id, target_day=day, target_machine="M1", target_start_min=minute, now=now,
    )


def test_lot_running_into_a_pinned_lot_is_refused_at_once_with_a_suggestion():
    data, config, baseline, long_lot, _short, day, now = _scenario()

    started = time.perf_counter()
    with pytest.raises(ManualMoveError) as refused:
        _move(baseline, data, config, long_lot.id, day, 480, now)
    assert time.perf_counter() - started < 5

    message = str(refused.value)
    assert "15,5 h seguidas (30 min de afinação antes das 08:00 + 15 h de produção)" in message
    assert "só há 3,5 h livres" in message  # 08:00 → 11:30, the pinned lot's setup
    assert "começa a afinação da Referência SKU2 (M1), fixada à mão para" in message
    assert "LOT_" not in message and "OP2_" not in message
    assert any("choca com a alteração manual da Referência SKU2" in cause
               for cause in refused.value.causes)
    # The first start after the pinned lot: its end (13:00) plus the setup.
    assert refused.value.suggestion == {
        "day": day, "start_min": 810, "machine": "M1",
        "label": f"{data.workdays[day][8:10]}/{data.workdays[day][5:7]} às 13:30 (M1)",
    }


def test_the_suggested_start_is_accepted_whole():
    """Lot F, free to move, is in the way: the move reorganises around L."""
    data, config, baseline, long_lot, short_lot, day, now = _scenario()
    with pytest.raises(ManualMoveError) as refused:
        _move(baseline, data, config, long_lot.id, day, 480, now)
    suggestion = refused.value.suggestion

    moved = _move(baseline, data, config, long_lot.id, suggestion["day"],
                  suggestion["start_min"], now)

    assert _production_start(moved.segments, long_lot.id) == (day, 810.0, "M1")
    assert moved.gate_report["metrics"]["lot_split_violations"] == 0
    assert moved.delta.tardy_after <= moved.delta.tardy_before
    pinned = sorted((s.day_idx, s.start_min, s.end_min) for s in moved.segments
                    if s.lot_id == short_lot.id)
    assert pinned == [(day, 690, 780)]
    free_id = next(lot.id for lot in baseline.lots if lot.op_id == "OP3")
    assert sorted((s.day_idx, s.start_min) for s in moved.segments if s.lot_id == free_id) != [
        (day, 780),
    ]


def test_a_move_that_fits_is_not_affected():
    data, config, baseline, long_lot, _short, day, now = _scenario()
    moved = _move(baseline, data, config, long_lot.id, day, 900, now)
    assert _production_start(moved.segments, long_lot.id) == (day, 900.0, "M1")


# ── the check itself: what may and may not interrupt a lot ─────────────────


def _timeline(data, config, segments, lot, template, *, now_min=0):
    return MachineTimeline(
        data, config, segments, lot, template, "M1", freeze_day=0, now_min=now_min,
    )


def _check(data, config, obstacles, lot, start_day, start_min, prod):
    template = Segment(lot.id, "R", "M1", lot.tool_id, start_day, start_min,
                       start_min + 1, "A", 1, 1.0, 0.0, sku=lot.sku)
    timeline = _timeline(data, config, obstacles, lot, template)
    return timeline, timeline.check(start_day * DAY_MIN + start_min, SETUP, prod)


def _obstacle(lot, day, start, end, setup=SETUP):
    return Segment(lot.id, "RUN_P", "M1", lot.tool_id, day, start, end,
                   "A" if start < 930 else "B", 10, end - start - setup, setup, sku=lot.sku)


def _lots(data=None, config=None):
    data, config = data or _data(), config or _config()
    lots = {lot.op_id: lot for lot in create_lots(data, config)}
    return data, config, lots["OP1"], lots["OP2"]


def test_night_may_interrupt_the_lot():
    data, config, long_lot, short_lot = _lots()
    # Monday 15:30 → 00:00 (510 min), Tuesday 07:00 → 13:00 (360 min): 870 min.
    _timeline_, verdict = _check(
        data, config, [_obstacle(short_lot, 1, 780, 900)], long_lot, 0, 930, 850,
    )
    assert verdict.fits
    _timeline_, verdict = _check(
        data, config, [_obstacle(short_lot, 1, 780, 900)], long_lot, 0, 930, 880,
    )
    assert not verdict.fits and verdict.free_min == pytest.approx(870)


def test_weekend_and_holiday_may_interrupt_the_lot():
    data, config, long_lot, short_lot = _lots(_data(holidays=(7,)))
    # Friday (day 4) 15:30 → 00:00, Saturday, Sunday and the Monday holiday
    # (day 7) skipped, Tuesday (day 8) 07:00 → 09:00: 510 + 120 min.
    obstacles = [_obstacle(short_lot, 8, 540, 660)]
    assert _check(data, config, obstacles, long_lot, 4, 930, 630)[1].fits
    verdict = _check(data, config, obstacles, long_lot, 4, 930, 640)[1]
    assert not verdict.fits and verdict.free_min == pytest.approx(630)
    assert not verdict.excusable


def test_machine_stop_may_interrupt_the_lot_and_excuses_the_break():
    data, config, long_lot, short_lot = _lots()
    data.machine_blocked_intervals["M1"] = [
        {"start_day": 1, "start_min": 420, "end_min": 600, "reason": "avaria"},
    ]
    obstacles = [_obstacle(short_lot, 1, 780, 900)]
    # Tuesday 07:00–10:00 is a stop: only 10:00 → 13:00 counts after the night.
    _timeline_, verdict = _check(data, config, obstacles, long_lot, 0, 930, 680)
    assert verdict.fits
    _timeline_, verdict = _check(data, config, obstacles, long_lot, 0, 930, 800)
    assert not verdict.fits and verdict.free_min == pytest.approx(690)
    # A stop over working time between the parts excuses another lot in
    # between (``validation._BreakFinder``): not certain, so never refused here.
    assert verdict.excusable


def test_free_shift_time_cannot_be_skipped():
    data, config, long_lot, short_lot = _lots()
    obstacles = [_obstacle(short_lot, 0, 690, 780)]
    timeline, verdict = _check(data, config, obstacles, long_lot, 0, 480, 600)
    assert not verdict.fits and verdict.free_min == pytest.approx(210)
    assert verdict.obstacle.segment.lot_id == short_lot.id
    # The first start after it: 13:00 + 30 min of setup, the same day.
    assert earliest_fit(timeline, SETUP, 600, 480) == 810


def test_after_a_later_refusal_only_the_next_stretch_is_offered():
    """The requested start fitted in a row and failed for another reason: the
    same stretch of free time (even its afternoon shift) would fail alike."""
    data, config, long_lot, short_lot = _lots()
    obstacles = [_obstacle(short_lot, 1, 690, 780)]
    timeline, verdict = _check(data, config, obstacles, long_lot, 0, 450, 100)
    assert verdict.fits
    found = earliest_fit(timeline, SETUP, 100, 450, after=True)
    assert divmod(found, DAY_MIN) == (1, 810)
    assert earliest_fit(timeline, SETUP, 100, DAY_MIN + 810, after=True) is None


def test_setup_inside_the_obstacle_is_refused():
    data, config, long_lot, short_lot = _lots()
    obstacles = [_obstacle(short_lot, 0, 690, 780)]
    _timeline_, verdict = _check(data, config, obstacles, long_lot, 0, 795, 60)
    assert not verdict.fits and verdict.setup_blocked


def test_suggestion_skips_windows_too_short_to_produce():
    data, config, long_lot, short_lot = _lots()
    # Friday 15:30–23:40 taken, 20 min of production left before the weekend.
    obstacles = [_obstacle(short_lot, 4, 930, 1390)]
    template = Segment(long_lot.id, "R", "M1", "T1", 4, 420, 421, "A", 1, 1.0, 0.0)
    timeline = _timeline(data, config, obstacles, long_lot, template)
    found = earliest_fit(timeline, SETUP, 600, 4 * DAY_MIN + 960)
    assert divmod(found, DAY_MIN) == (7, 450)  # Monday 07:00 + setup


def test_hours_text():
    assert hours_text(465) == "7,8 h"
    assert hours_text(60) == "1 h"
    assert hours_text(30) == "30 min"
    assert hours_text(1342.66) == "22,4 h"


# ── the real case (Incompol, revision 154, 15/10/2026) ──────────────────────

INCOMPOL_LOT = "LOT_JTE001_PRM043_6800016767A.10_57"
INCOMPOL_NOW = datetime(2026, 10, 15, 13, 29, tzinfo=LISBON)


def _rev154():
    from backend.plans.serialize import deserialize_snapshot

    _, payload = load_payload("rev154")
    restored = deserialize_snapshot(payload)
    return restored["engine_data"], restored["config"], restored["result"]


def test_incompol_jte001_on_03_12_is_refused_at_once_naming_the_pinned_jte003():
    data, config, result = _rev154()
    started = time.perf_counter()
    with pytest.raises(ManualMoveError) as refused:
        move_lot(
            result.segments, result.lots, result.score, data, config,
            lot_id=INCOMPOL_LOT, target_day=51, target_machine="PRM043",
            target_start_min=525, now=INCOMPOL_NOW,
        )
    elapsed = time.perf_counter() - started
    assert elapsed < 5, elapsed
    message = str(refused.value)
    assert (
        "o lote precisa de 23,4 h seguidas (1 h de afinação antes das 08:45 + "
        "22,4 h de produção); a partir de 03/12 às 08:45 só há 7,8 h livres até "
        "03/12 às 16:30, quando começa a afinação da Referência 6800017267C.30 "
        "(PRM043), fixada à mão para 03/12 17:30."
    ) in message
    assert "LOT_" not in message and not any("LOT_" in cause for cause in refused.value.causes)
    # After the two JTE003 lots and the BFP125 twin pinned on 04/12, then the
    # weekend and nothing else in the way: Monday 07/12, 07:00 + 1 h setup.
    assert refused.value.suggestion == {
        "day": 55, "start_min": 480, "machine": "PRM043", "label": "07/12 às 08:00 (PRM043)",
    }


def test_incompol_move_that_fits_is_not_affected():
    data, config, result = _rev154()
    moved = move_lot(
        result.segments, result.lots, result.score, data, config,
        lot_id=INCOMPOL_LOT, target_day=50, target_machine="PRM043",
        target_start_min=420, now=INCOMPOL_NOW,
    )
    assert _production_start(moved.segments, INCOMPOL_LOT) == (50, 420.0, "PRM043")


@pytest.mark.xfail(
    reason=(
        "Defeito anterior, fora desta alteração: na reorganização de um movimento, "
        "os lotes fixados à mão entram na proteção e são creditados como stock no "
        "dia 0 (frozen._install_frozen_reservations); os outros lotes das mesmas "
        "operações deixam de coincidir com o ISOP (source_contract). Na revisão 154 "
        "todo o movimento que precisa de reorganizar é recusado assim."
    ),
    strict=False,
)
def test_incompol_suggested_start_is_accepted():
    data, config, result = _rev154()
    moved = move_lot(
        result.segments, result.lots, result.score, data, config,
        lot_id=INCOMPOL_LOT, target_day=55, target_machine="PRM043",
        target_start_min=480, now=INCOMPOL_NOW,
    )
    assert moved.gate_report["metrics"]["lot_split_violations"] == 0
    assert moved.delta.tardy_after <= moved.delta.tardy_before


def test_the_preview_job_returns_the_suggestion(monkeypatch):
    import threading

    from backend.plans import manual_move_jobs

    suggestion = {"day": 55, "start_min": 480, "machine": "PRM043",
                  "label": "07/12 às 08:00 (PRM043)"}

    def refuse(*_args, **_kwargs):
        raise ManualMoveError("Não cabe.", causes=["Porque não."], suggestion=suggestion)

    monkeypatch.setattr(manual_move_jobs, "move_lot", refuse)
    manager = manual_move_jobs.ManualMoveJobManager()
    try:
        manager.jobs["J"] = {"id": "J", "status": "queued",
                             "created_at": "2026-10-15T00:00:00+00:00"}
        manager._run("J", threading.Event(), [], [], {}, None, None,
                     "LOT", 51, "PRM043", 525, "", "planeador")
        job = manager.get("J")
    finally:
        manager.executor.shutdown(wait=True)
    assert job["status"] == "failed" and job["code"] == "blocked"
    assert job["causes"] == ["Porque não."]
    assert job["suggestion"] == suggestion
