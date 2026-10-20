"""Real case (Incompol, 20/10/2026 11:49): JTE001 ran on PRM043 from 08:00.

Revision 178 (ISOP of 20/10) had CF589 on PRM043 from 07:00 to 15:50 and
JTE001 from 18:35. The production manager ran JTE001 in the morning; at
11:49 the planner moved it to 08:00 and was refused («esse momento já
passou»). Recording what ran (decisão do Luís, 20/10/2026) now accepts it:
JTE001's setup 07:00–08:00, production from 08:00; CF589 did not run and is
replanned after 11:49; every other row of the morning stays as it was.
"""

from __future__ import annotations

import copy
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.plans import frozen
from backend.plans.manual_edits import EXECUTED
from backend.plans.manual_move import MANUAL_MOVE_BUDGET_S, move_lot
from backend.plans.serialize import _finalize_snapshot, deserialize_snapshot
from backend.plans.store import _assert_activatable_payload
from tests.snapshot_fixture import load_payload

LISBON = ZoneInfo("Europe/Lisbon")
JTE001 = "LOT_JTE001_PRM043_6800016767A.10_1"
CF589 = "LOT_HAN002_PRM043_CF589MMA1A02.20_3"
NOW = datetime(2026, 10, 20, 11, 49, tzinfo=LISBON)
NOW_MIN = 11 * 60 + 49


def _morning(segments):
    return sorted(
        (s["machine_id"], s["lot_id"], s["start_min"], s["end_min"], s["qty"])
        for s in segments
        if s["day_idx"] == 0 and s["start_min"] < NOW_MIN and s["end_min"] > s["start_min"]
    )


def test_rev178_jte001_recorded_from_0800_on_prm043():
    _manifest, payload = load_payload("rev178")
    restored = deserialize_snapshot(copy.deepcopy(payload))
    data, config, plan = restored["engine_data"], restored["config"], restored["result"]
    assert str(data.workdays[0])[:10] == "2026-10-20" and not data.plan_anchors

    move = move_lot(
        plan.segments, plan.lots, plan.score, data, config, lot_id=JTE001, target_day=0,
        target_machine="PRM043", target_start_min=480, now=NOW,
    )

    assert move.executed and move.history_boundary == [0, NOW_MIN]
    assert move.time_ms < MANUAL_MOVE_BUDGET_S * 1000
    jte = sorted((s.day_idx, s.start_min, s.setup_min) for s in move.segments if s.lot_id == JTE001)
    assert jte[0] == (0, 420, 60)  # setup 07:00–08:00, production from 08:00
    cf589 = sorted((s.day_idx, s.start_min) for s in move.segments if s.lot_id == CF589)
    assert cf589 and cf589[0] >= (0, NOW_MIN)
    assert "CF589MMA1A02.20 · HAN002 (PRM043) fica por fazer" in move.notice

    after = copy.deepcopy(payload)
    after["segments"] = [asdict(segment) for segment in move.segments]
    after["lots"] = [asdict(lot) for lot in move.lots]
    after["engine_data"]["plan_anchors"] = [{
        "lot_id": JTE001, "machine_id": "PRM043", "start_at": "2026-10-20T08:00",
        "reason": "", "author": "planeador", "kind": EXECUTED,
    }]
    after["engine_data"]["history_boundary"] = list(move.history_boundary)
    _finalize_snapshot(after)
    # Every other row of the morning is as it was.
    untouched = [row for row in _morning(payload["segments"]) if row[0] != "PRM043"]
    assert [row for row in _morning(after["segments"]) if row[0] != "PRM043"] == untouched
    assert [row[1] for row in _morning(after["segments"]) if row[0] == "PRM043"] == [JTE001]
    # The commit accepts it: validation (crew and operators before 11:49 not
    # judged) and the history guard at the move's instant.
    _assert_activatable_payload(after)
    assert frozen.historical_schedule_changes(payload, after, now=NOW) == []
    # Without the record kind the same plan would change the morning.
    ordinary = copy.deepcopy(after)
    ordinary["engine_data"]["plan_anchors"][0]["kind"] = ""
    _finalize_snapshot(ordinary)
    assert set(frozen.historical_schedule_changes(payload, ordinary, now=NOW)) == {JTE001, CF589}
