"""Load private, frozen plan snapshots for regression tests.

The payload holds client data and lives in ``tests/fixtures/private`` (git
ignored); the committed manifest in ``tests/fixtures/snapshots`` identifies
it by hash. Tests skip when the private payload is absent.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from backend.plans.frozen import _protected_lots
from backend.plans.serialize import assert_snapshot_integrity, deserialize_snapshot
from backend.scheduler.canonical import preserved_lot_proofs, result_validation_data

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass
class FrozenSnapshot:
    manifest: dict
    data: object
    config: object
    result: object
    freeze_day: int
    protected_segments: list
    protected_lots: list

    def complete_context(self):
        """Validation data seen by the improvement generators: the complete
        plan with protected lots proven, plus the replanning boundary."""
        view = copy.copy(result_validation_data(self.data, self.result))
        view.preserved_lot_proofs = {
            **(view.preserved_lot_proofs or {}),
            **preserved_lot_proofs(self.protected_segments, self.protected_lots),
        }
        return view, self.freeze_day * 1440


def load_snapshot(name: str, *, clock: str | None = None) -> FrozenSnapshot:
    """Load a frozen snapshot, protected as of the manifest date.

    ``clock`` replays the plan as it stood at an earlier date: protection
    proofs recorded later are dropped from this detached copy and recomputed
    for that date (plan §8.1: history is never released in the real plan).
    """
    manifest = json.loads((FIXTURES / "snapshots" / f"{name}.json").read_text())
    path = FIXTURES.parent.parent / manifest["private_fixture"]
    if not path.exists():
        pytest.skip(f"private fixture {path.name} absent; see scripts/freeze_snapshot_fixture.py")
    raw = gzip.decompress(path.read_bytes()).decode("utf-8")
    assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == manifest["payload_sha256"]
    payload = json.loads(raw)
    assert_snapshot_integrity(payload)
    restored = deserialize_snapshot(payload)
    data, config, result = restored["engine_data"], restored["config"], restored["result"]
    freeze_day = manifest["freeze_day"]
    if clock is not None:
        data.preserved_lot_proofs, result.preserved_lot_proofs = {}, None
        freeze_day = data.workdays.index(clock)
    protected_segments, protected_lots, _ = _protected_lots(result, freeze_day, data, config)
    return FrozenSnapshot(manifest, data, config, result, freeze_day,
                          protected_segments, protected_lots)


def rename_lots_and_runs(snapshot: FrozenSnapshot) -> tuple[FrozenSnapshot, dict, dict]:
    """Order-preserving renaming of every lot and run identifier.

    The commercial priority uses the lot id as its final, stable tie-break,
    so the new names keep the original lexicographic order: any behaviour
    change is then a dependency on a name, never a legitimate tie-break.
    """

    renamed = copy.deepcopy(snapshot)
    lot_map = {old: f"LOT{index:05d}" for index, old in
               enumerate(sorted({lot.id for lot in renamed.result.lots}))}
    run_map = {old: f"RUN{index:05d}" for index, old in
               enumerate(sorted({segment.run_id for segment in renamed.result.segments}))}
    for lot in [*renamed.result.lots, *renamed.protected_lots]:
        lot.id = lot_map[lot.id]
    for segment in [*renamed.result.segments, *renamed.protected_segments]:
        segment.lot_id = lot_map[segment.lot_id]
        segment.run_id = run_map[segment.run_id]
    renamed.result.preserved_lot_proofs = None
    renamed.data.preserved_lot_proofs = {}
    for anchor in renamed.data.plan_anchors or []:
        anchor.lot_id = lot_map.get(anchor.lot_id, anchor.lot_id)
    return renamed, lot_map, run_map
