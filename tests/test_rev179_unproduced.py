"""Real case (Incompol, 21/10/2026 10:34): CF589 had not run on PRM043.

Revision 179 (ISOP of 21/10) had CF589 on PRM043 from 07:00 to 15:50 and
JTE001 from 15:50. At 10:34 the planner moved CF589 to 22/10 16:00 and was
refused («já iniciado está congelado»). A lot that, by the plan, only
started today moves freely: it was not produced (decisão do Luís,
21/10/2026). Its morning leaves the plan, nothing new enters before 10:34,
every other row of the morning stays and the commit guard accepts it only
with the server's signal. Swapping CF589 and JTE001 works in either order.
"""

from __future__ import annotations

import copy
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.plans import frozen
from backend.plans.manual_edits import EXECUTED
from backend.plans.manual_move import MANUAL_MOVE_BUDGET_S, move_lot
from backend.plans.serialize import _finalize_snapshot, deserialize_snapshot
from backend.plans.store import _assert_activatable_payload
from backend.scheduler.types import ScheduleResult
from tests.snapshot_fixture import load_payload

pytestmark = [pytest.mark.needs_private, pytest.mark.slow]

LISBON = ZoneInfo("Europe/Lisbon")
CF589 = "LOT_HAN002_PRM043_CF589MMA1A02.20_2"
JTE001 = "LOT_JTE001_PRM043_6800016767A.10_0"


def _at(hour, minute):
    return datetime(2026, 10, 21, hour, minute, tzinfo=LISBON)


def _morning(segments, now_min, *, without=()):
    return sorted(
        (s["machine_id"], s["lot_id"], s["start_min"], s["end_min"], s["qty"])
        for s in segments
        if s["day_idx"] == 0 and s["start_min"] < now_min and s["end_min"] > s["start_min"]
        and s["lot_id"] not in without
    )


def _applied(payload, move, anchors):
    after = copy.deepcopy(payload)
    after["segments"] = [asdict(segment) for segment in move.segments]
    after["lots"] = [asdict(lot) for lot in move.lots]
    after["engine_data"]["plan_anchors"] = anchors
    if move.history_boundary:
        after["engine_data"]["history_boundary"] = list(move.history_boundary)
    return _finalize_snapshot(after)


def _anchor(move, data, *, executed=False):
    minute = move.target_start_min
    return {
        "lot_id": move.lot_id, "machine_id": move.target_machine,
        "start_at": f"{data.workdays[move.target_day][:10]}T{minute // 60:02d}:{minute % 60:02d}",
        "reason": "", "author": "planeador", **({"kind": EXECUTED} if executed else {}),
    }


def _plan_of(payload):
    restored = deserialize_snapshot(copy.deepcopy(payload))
    return restored["engine_data"], restored["config"], restored["result"]


@pytest.fixture(scope="module")
def rev179():
    _manifest, payload = load_payload("rev179")
    data, config, plan = _plan_of(payload)
    assert str(data.workdays[0])[:10] == "2026-10-21" and not data.plan_anchors
    return payload, data, config, plan


@pytest.fixture(scope="module")
def cf589_moved(rev179):
    payload, data, config, plan = rev179
    move = move_lot(
        plan.segments, plan.lots, plan.score, data, config, lot_id=CF589, target_day=1,
        target_machine="PRM043", target_start_min=960, now=_at(10, 34),
    )
    return move, _applied(payload, move, [_anchor(move, data)])


def test_rev179_cf589_moves_to_2210_1600_as_not_produced(rev179, cf589_moved):
    payload, _data, _config, _plan = rev179
    move, after = cf589_moved
    now_min = 10 * 60 + 34
    assert move.unproduced_today == {
        "lot_id": CF589, "tool_id": "HAN002", "date": "2026-10-21",
        "start_min": 420, "since": now_min,
    }
    assert not move.executed and move.time_ms < MANUAL_MOVE_BUDGET_S * 1000
    assert move.notice == (
        "A Referência CF589MMA1A02.20 · HAN002 (PRM043) fica registada como não produzida "
        "hoje (estava na PRM043 das 07:00 às 15:50) e passa para 22/10 às 16:00."
    )
    cf = sorted(
        (s.day_idx, s.production_start_min) for s in move.segments if s.lot_id == CF589 and s.qty
    )
    assert cf[0] == (1, 960)
    # The morning is the plan's without CF589: nothing new before 10:34.
    assert _morning(after["segments"], now_min) == _morning(
        payload["segments"], now_min, without={CF589},
    )
    _assert_activatable_payload(after)
    now = _at(10, 34)
    assert frozen.historical_schedule_changes(
        payload, after, now=now, unproduced=("before", CF589),
    ) == []
    assert frozen.historical_schedule_changes(payload, after, now=now) == [CF589]
    # «Desfazer» a minute later.
    assert frozen.historical_schedule_changes(
        after, payload, now=_at(10, 35), undo=True, unproduced=("after", CF589),
    ) == []


def test_rev179_swap_yellow_first_then_green(rev179, cf589_moved):
    """After CF589 left, JTE001 recorded as run from 08:00 at 10:40 (the
    engine had replanned it for 23/10, so it is a record only; the case where
    it had started since is in ``test_manual_move_executed.py``)."""
    _payload, data, _config, _plan = rev179
    move, after = cf589_moved
    moved_data, config, plan = _plan_of(after)
    record = move_lot(
        plan.segments, plan.lots, plan.score, moved_data, config, lot_id=JTE001, target_day=0,
        target_machine="PRM043", target_start_min=480, now=_at(10, 40),
    )
    assert record.executed and not record.unproduced_today
    assert record.notice.startswith(
        "Vai ficar registado como já produzido desde 08:00 na PRM043",
    )
    jte = sorted((s.day_idx, s.start_min, s.setup_min) for s in record.segments
                 if s.lot_id == JTE001)
    assert jte[0] == (0, 420, 60)
    recorded = _applied(after, record, [
        _anchor(move, data), _anchor(record, data, executed=True),
    ])
    _assert_activatable_payload(recorded)
    now = _at(10, 40)
    assert frozen.historical_schedule_changes(after, recorded, now=now) == []
    assert frozen.historical_schedule_changes(recorded, after, now=_at(10, 42), undo=True) == []


def test_rev179_swap_green_first_then_yellow(rev179):
    """JTE001 recorded as run from 08:00 at 10:34 (CF589 made nothing, it is
    replanned from now, for 22/10); then CF589 moved to 22/10 16:00 at 10:40
    as any lot."""
    payload, data, config, plan = rev179
    record = move_lot(
        plan.segments, plan.lots, plan.score, data, config, lot_id=JTE001, target_day=0,
        target_machine="PRM043", target_start_min=480, now=_at(10, 34),
    )
    assert record.executed and not record.unproduced_today
    assert "CF589MMA1A02.20 · HAN002 (PRM043) fica por fazer" in record.notice
    recorded = _applied(payload, record, [_anchor(record, data, executed=True)])
    assert frozen.historical_schedule_changes(payload, recorded, now=_at(10, 34)) == []
    recorded_data, config, recorded_plan = _plan_of(recorded)
    move = move_lot(
        recorded_plan.segments, recorded_plan.lots, recorded_plan.score, recorded_data, config,
        lot_id=CF589, target_day=1, target_machine="PRM043", target_start_min=960,
        now=_at(10, 40),
    )
    assert not move.executed and not move.unproduced_today and move.notice is None
    cf = sorted(
        (s.day_idx, s.production_start_min) for s in move.segments if s.lot_id == CF589 and s.qty
    )
    assert cf[0] == (1, 960)
    after = _applied(recorded, move, [
        _anchor(record, data, executed=True), _anchor(move, data),
    ])
    _assert_activatable_payload(after)
    now = _at(10, 40)
    assert frozen.historical_schedule_changes(recorded, after, now=now) == []
    assert frozen.historical_schedule_changes(after, recorded, now=_at(10, 42), undo=True) == []
    # The record stays where it ran.
    assert sorted(
        (s.day_idx, s.start_min, s.end_min) for s in move.segments if s.lot_id == JTE001
    )[0] == (0, 420, sorted(
        (s.day_idx, s.start_min, s.end_min) for s in record.segments if s.lot_id == JTE001
    )[0][2])


def test_rev179_recalculate_does_not_put_cf589_back_in_the_morning(rev179, cf589_moved):
    """«Recalcular plano» at 10:50 releases the pin and plans from 00:00 of
    21/10; the HAN002 morning CF589 left stays free of it up to 10:50."""
    move, after = cf589_moved

    def early_han002(facts):
        data, config, plan = _plan_of(after)
        data.unproduced_today = facts
        data.plan_anchors = []
        result = frozen.optimize_preserving_started_lots(
            data, config, ScheduleResult(plan.segments, plan.lots, plan.score, 0, [], []),
            mode="quick", now=_at(10, 50), recalculate_from_start=True,
        )
        return [
            (s.lot_id, s.start_min) for s in result.segments
            if s.tool_id == "HAN002" and s.day_idx == 0 and s.start_min < 650
            and s.end_min > s.start_min
        ]

    assert early_han002([dict(move.unproduced_today)]) == []
    # Without the fact «Recalcular» puts CF589 back at 07:00.
    assert early_han002([]) == [(CF589, 420)]
