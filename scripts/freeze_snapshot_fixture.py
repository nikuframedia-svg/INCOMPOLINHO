"""Freeze one persisted plan snapshot as a private regression fixture.

Reads the plan database read-only and writes the exact payload, gzipped, to
``tests/fixtures/private/`` (git-ignored: it contains client data) plus a
committable manifest without client data (hashes, revision, counts, as-of
date). Never modifies the database or the active plan.

    .venv/bin/python scripts/freeze_snapshot_fixture.py \\
        --snapshot-id 046b5d08b9884672ba2f9cf7e0f024d7 --as-of 2026-10-02 --name rev90
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.plans.frozen import _protected_lots  # noqa: E402
from backend.plans.serialize import (  # noqa: E402
    assert_snapshot_integrity,
    deserialize_snapshot,
    planning_model_identity,
)

PRIVATE = ROOT / "tests" / "fixtures" / "private"
MANIFESTS = ROOT / "tests" / "fixtures" / "snapshots"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "plans.db")
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--as-of", required=True, help="Protection boundary, YYYY-MM-DD")
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT payload_json FROM plans WHERE id=?", (args.snapshot_id,),
        ).fetchone()
    if row is None:
        raise SystemExit(f"Snapshot {args.snapshot_id} not found")
    raw = row[0]
    payload = json.loads(raw)
    assert_snapshot_integrity(payload)
    restored = deserialize_snapshot(payload)
    data, config, result = restored["engine_data"], restored["config"], restored["result"]
    if args.as_of not in data.workdays:
        raise SystemExit("as-of must be a workday present in the snapshot")
    freeze_day = data.workdays.index(args.as_of)
    _, protected, anchored = _protected_lots(result, freeze_day, data, config)

    PRIVATE.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    fixture = PRIVATE / f"{args.name}.json.gz"
    fixture.write_bytes(gzip.compress(raw.encode("utf-8"), mtime=0))
    manifest = {
        "name": args.name,
        "snapshot_id": args.snapshot_id,
        "plan_revision": payload.get("plan_revision"),
        "payload_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "as_of": args.as_of,
        "freeze_day": freeze_day,
        "lots": len(result.lots),
        "segments": len(result.segments),
        "protected_lots": len(protected),
        "anchored_lots": len(anchored),
        "stored_model_version": payload.get("model_version"),
        "stored_planning_policy_version": payload.get("planning_policy_version"),
        "improvement_contract_in_stored_report": (payload.get("improvement_report") or {})
        .get("contract_version"),
        "frozen_with_model_identity": planning_model_identity(),
        "private_fixture": f"tests/fixtures/private/{args.name}.json.gz",
    }
    (MANIFESTS / f"{args.name}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
