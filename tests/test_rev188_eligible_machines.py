"""Real case (Incompol, 23/10/2026): BFP186 on PRM043 could not go to PRM039 (E13).

Revision 188 (ISOP of 23/10 14:00) has 26 lots that an earlier calculation
put on their alternative and that carry alternative/alternative, so the
primary was lost: e.g. LOT_TWIN_BFP186_11 on PRM043/PRM043 while its
operations say primary PRM039, alternative PRM043. Dragging it to PRM039 was
refused («não é primária nem alternativa») and every later calculation could
only keep it on PRM043. The machines of a lot now come from its operations.
"""

from __future__ import annotations

import copy
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.config.planning import lot_tool_machines
from backend.plans.frozen import optimize_preserving_started_lots
from backend.plans.manual_move import move_lot
from backend.plans.serialize import deserialize_snapshot
from tests.snapshot_fixture import load_payload

LISBON = ZoneInfo("Europe/Lisbon")
BFP186 = "LOT_TWIN_BFP186_11"
# Before the shifts of 23/10: nothing of the day has started yet.
NOW = datetime(2026, 10, 23, 6, 0, tzinfo=LISBON)


def _restored():
    _manifest, payload = load_payload("rev188")
    restored = deserialize_snapshot(copy.deepcopy(payload))
    return restored["engine_data"], restored["config"], restored["result"]


def _lost_primary(lots, data):
    return sorted(
        lot.id for lot in lots
        if lot.machine_id == lot.alt_machine_id and len(lot_tool_machines(lot, data)) == 2
    )


def test_rev188_has_26_lots_that_lost_their_primary():
    data, _config, plan = _restored()

    lost = _lost_primary(plan.lots, data)

    assert len(lost) == 26 and BFP186 in lost
    lot = next(lot for lot in plan.lots if lot.id == BFP186)
    assert (lot.machine_id, lot.alt_machine_id) == ("PRM043", "PRM043")
    assert lot_tool_machines(lot, data) == ["PRM039", "PRM043"]


def test_rev188_bfp186_moves_to_its_primary_prm039():
    data, config, plan = _restored()

    move = move_lot(
        plan.segments, plan.lots, plan.score, data, config, lot_id=BFP186, target_day=0,
        target_machine="PRM039", target_start_min=848, now=NOW,
    )

    moved = [segment for segment in move.segments if segment.lot_id == BFP186]
    assert moved and {segment.machine_id for segment in moved} == {"PRM039"}
    lot = next(lot for lot in move.lots if lot.id == BFP186)
    assert (lot.machine_id, lot.alt_machine_id) == ("PRM039", "PRM043")
    assert move.gate_report["hard_gate_passed"] is True
    assert move.score["tardy_count"] <= plan.score["tardy_count"]


def test_rev188_recalculate_keeps_both_machines_of_every_lot():
    data, config, plan = _restored()

    result = optimize_preserving_started_lots(
        data, config, plan, audit=True, recalculate_from_start=True, now=NOW,
    )

    assert _lost_primary(result.lots, data) == []
    assert result.score["tardy_count"] <= plan.score["tardy_count"]
