"""Local check on the real active plan (skipped when data/plans.db is absent).

The database holds client data and is git-ignored: this test only runs on the
factory server. It opens the database read-only and never writes to it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.config.loader import load_config
from backend.config.planning import enforce_machine_scope
from backend.plans.serialize import deserialize_snapshot
from backend.scheduler.improvement import Generator, improve_plan, tool_transfers
from backend.scheduler.transfer_consolidation import (
    SCOPE,
    consolidation_proposals,
    explain_remaining_transfers,
)
from backend.scheduler.validation import validate_plan

DATABASE = Path(__file__).resolve().parents[1] / "data" / "plans.db"
CONFIG = Path(__file__).resolve().parents[1] / "config" / "factory.yaml"


def _active_plan():
    if not DATABASE.exists() or not CONFIG.exists():
        pytest.skip("real plan database not available on this machine")
    with sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT p.payload_json FROM plans p JOIN plan_runtime r ON r.snapshot_id = p.id"
        ).fetchone()
    if row is None:
        pytest.skip("no active plan in the database")
    restored = deserialize_snapshot(json.loads(row[0]))
    data, result = restored["engine_data"], restored["result"]
    config = load_config(str(CONFIG))
    enforce_machine_scope(config, data, result.segments)
    return result.segments, result.lots, data, config


def test_consolidation_on_the_real_plan_is_safe_and_explained():
    segments, lots, data, config = _active_plan()
    if validate_plan(segments, data, config, lots=lots):
        pytest.skip("stored plan is not valid under the current configuration")
    preserved = set(data.preserved_lot_proofs)
    generator = Generator(
        SCOPE, lambda segs, lot_list: consolidation_proposals(segs, lot_list, data, config),
    )

    improved, improved_lots, report = improve_plan(
        segments, lots, data, config, generators=[generator], max_evaluations=6,
    )

    assert validate_plan(improved, data, config, lots=improved_lots) == []
    assert tool_transfers(improved) <= tool_transfers(segments)
    rows = lambda items: sorted(  # noqa: E731
        (s.lot_id, s.machine_id, s.day_idx, s.start_min, s.end_min, s.qty)
        for s in items if s.lot_id in preserved
    )
    assert rows(improved) == rows(segments)
    explained = explain_remaining_transfers(improved, improved_lots, data, config, report)
    assert explained["remaining"] == tool_transfers(improved)
    assert all(item["summary"] for item in explained["items"])
