"""Manual edits = their pins, and «Recalcular» erases them (decisão de 15/10/2026).

Incompol, 15/10/2026: eight manual moves (revisions 149-156) left eight
records but five pins; «Desfazer» and «Recalcular» then cleared the records
and kept the pins, so the plan stayed bent around five invisible positions
(revision 158 had the same schedule as 157). Now the visible list is always
the pins, one per lot, «Soltar» releases a pin with its record, and
«Recalcular» erases every manual edit and calculates from scratch.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from backend.api.copilot import app
from backend.copilot.state import state
from backend.plans.manual_edits import (
    release_manual_anchors,
    sync_manual_edits,
    synced_manual_edits,
)
from backend.types import PlanAnchor
from tests.snapshot_fixture import load_payload
from tests.test_manual_move import manual_api_state  # noqa: F401 - fixture

LISBON = ZoneInfo("Europe/Lisbon")


def _data(*anchors):
    return SimpleNamespace(
        plan_anchors=list(anchors), workdays=["2026-12-02", "2026-12-03", "2026-12-04"],
    )


def test_list_is_one_record_per_pin_latest_wins_and_lost_records_come_back():
    data = _data(
        PlanAnchor("A", "PRM043", "2026-12-03T08:45"),
        PlanAnchor("B", "PRM042", "2026-12-02T08:00", "teste", "planeador"),
    )
    edits = [
        {"lot_id": "A", "id": "1", "target_day": 0},
        {"lot_id": "A", "id": "2", "target_day": 1},
        {"lot_id": "GONE", "id": "3"},
    ]
    synced = synced_manual_edits(edits, data)
    assert [item["lot_id"] for item in synced] == ["A", "B"]
    assert synced[0]["id"] == "2"
    assert (synced[1]["target_day"], synced[1]["target_start_min"]) == (0, 480)
    assert synced[1]["target_machine"] == "PRM042"


def test_release_takes_the_pin_and_its_record_together():
    holder = SimpleNamespace(
        engine_data=_data(
            PlanAnchor("A", "PRM043", "2026-12-03T08:45"),
            PlanAnchor("B", "PRM042", "2026-12-02T08:00"),
        ),
        manual_edits=[{"lot_id": "A"}, {"lot_id": "B"}],
    )
    assert release_manual_anchors(holder, ["A"]) == ["A"]
    assert [a.lot_id for a in holder.engine_data.plan_anchors] == ["B"]
    assert [e["lot_id"] for e in holder.manual_edits] == ["B"]
    assert release_manual_anchors(holder, None) == ["B"]
    assert holder.engine_data.plan_anchors == [] and holder.manual_edits == []


def test_soltar_releases_the_pin_and_replans(manual_api_state):  # noqa: F811
    start = next(s for s in state.segments if s.lot_id == "LOT1")
    day = str(state.engine_data.workdays[start.day_idx])[:10]
    minute = int(start.start_min + start.setup_min)
    state.engine_data.plan_anchors = [
        PlanAnchor("LOT1", start.machine_id, f"{day}T{minute // 60:02d}:{minute % 60:02d}"),
    ]
    sync_manual_edits(state)
    assert [item["lot_id"] for item in state.manual_edits] == ["LOT1"]
    client = TestClient(app)

    unknown = client.post("/api/data/manual-edits/release", json={
        "lot_ids": ["NOPE"], "expected_revision": state.plan_revision,
    })
    assert unknown.status_code == 400

    released = client.post("/api/data/manual-edits/release", json={
        "lot_ids": ["LOT1"], "expected_revision": state.plan_revision,
    })
    assert released.status_code == 200, released.text
    assert released.json()["released"] == ["LOT1"]
    assert state.engine_data.plan_anchors == []
    assert state.manual_edits == []

    nothing = client.post("/api/data/manual-edits/release", json={
        "expected_revision": state.plan_revision,
    })
    assert nothing.status_code == 400


def test_incompol_revision_157_shows_every_pin_and_recalculate_releases_them():
    """Revision 157: seven records for five pins. The list shows the five pins;
    «Recalcular» (from D0, no pins) gives a valid plan without late orders."""
    from backend.plans.frozen import optimize_preserving_started_lots
    from backend.plans.serialize import deserialize_snapshot

    _, payload = load_payload("rev157")
    restored = deserialize_snapshot(payload)
    data, config, result = restored["engine_data"], restored["config"], restored["result"]
    assert len(restored["manual_edits"]) == 7 and len(data.plan_anchors) == 5
    synced = synced_manual_edits(restored["manual_edits"], data)
    assert sorted(item["lot_id"] for item in synced) == sorted(a.lot_id for a in data.plan_anchors)

    holder = SimpleNamespace(engine_data=data, manual_edits=restored["manual_edits"])
    release_manual_anchors(holder, None)
    rebuilt = optimize_preserving_started_lots(
        data, config, result, audit=True, recalculate_from_start=True,
        now=datetime(2026, 10, 15, 13, 33, tzinfo=LISBON),
    )
    assert rebuilt.gate_report["physical_gate_passed"]
    assert rebuilt.score["tardy_count"] == 0
    assert not rebuilt.gate_report["metrics"].get("plan_anchor_violations")
