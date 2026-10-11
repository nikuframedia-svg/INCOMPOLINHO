"""Scan manual moves on a stored plan revision (read-only, no app).

For every fourth lot (from ``--offset``) that starts on day 6 or later and is
not a twin, tries the targets -1/+1/+2/-2/+3 days (shift A or B start) with
``move_lot`` until ``--max-trials``. Prints the refusal categories, the
moves that produced a preview and, with ``--show-refusals``, the first
attempts of each refusal category (used to pick the golden-master F4 refusal).

Usage::

  python -B m_scan.py --code <code_root> --db <copy of plans.db> --revision 124 \
      --max-trials 80 [--offset 0] [--show-refusals 3]
"""

import argparse
import collections
import json
import logging
import sqlite3
import sys
import time

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--code", required=True)
parser.add_argument("--db", required=True, help="a copy of plans.db (never the live one)")
parser.add_argument("--revision", type=int, required=True)
parser.add_argument("--max-trials", type=int, default=80)
parser.add_argument("--offset", type=int, default=0)
parser.add_argument("--show-refusals", type=int, default=0,
                    help="print the first N attempts of each refusal category")
args = parser.parse_args()

sys.path.insert(0, args.code)
logging.disable(logging.WARNING)

import backend.plans.manual_move as mm  # noqa: E402
from backend.plans.serialize import deserialize_snapshot  # noqa: E402

connection = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
row = connection.execute(
    "select payload_json from plans where json_extract(payload_json,'$.plan_revision')=? "
    "order by rowid desc limit 1",
    (args.revision,),
).fetchone()
connection.close()
if row is None:
    raise SystemExit(f"revision {args.revision} not found in {args.db}")
restored = deserialize_snapshot(json.loads(row[0]))
result = restored["result"]
segments, lots, score = result.segments, result.lots, result.score or {}
data, config = restored["engine_data"], restored["config"]

by_lot = collections.defaultdict(list)
for segment in segments:
    by_lot[segment.lot_id].append(segment)
candidates = sorted(
    (min(s.day_idx for s in by_lot[lot.id]), lot.id)
    for lot in lots
    if by_lot.get(lot.id) and min(s.day_idx for s in by_lot[lot.id]) >= 6 and not lot.is_twin
)

CATEGORIES = (
    ("calendário", "calendario"),
    ("capacidade", "capacidade"),
    ("equipa", "equipa"),
    ("inconclusiva", "inconclusiva"),
    ("afinação", "afinacao"),
    ("material", "material"),
)


def category(exc: Exception) -> str:
    message = str(exc)
    label = next((name for needle, name in CATEGORIES if needle in message), message[:60])
    return f"{type(exc).__name__}:{label}"


stats = collections.Counter()
refusals = collections.defaultdict(list)
accepted = []
trials = 0
for first_day, lot_id in candidates[args.offset::4]:
    for delta, start_min in ((-1, 420), (1, 420), (2, 930), (-2, 930), (3, 420)):
        if trials >= args.max_trials:
            break
        trials += 1
        started = time.monotonic()
        try:
            out = mm.move_lot(
                segments, lots, score, data, config, lot_id=lot_id,
                target_day=first_day + delta, target_start_min=start_min,
                reason="scan", author="scan",
            )
        except Exception as exc:  # noqa: BLE001 - every refusal is counted
            key = category(exc)
            stats[key] += 1
            if len(refusals[key]) < args.show_refusals:
                refusals[key].append((lot_id, first_day, first_day + delta, start_min,
                                      round(time.monotonic() - started, 2), str(exc)[:300]))
            continue
        stats["ok"] += 1
        accepted.append((lot_id, first_day, first_day + delta, start_min,
                         round(time.monotonic() - started, 2), out.requires_confirmation,
                         out.gate_report.get("approval_reasons")))

print("TRIALS", trials, dict(stats))
for item in accepted:
    print("OK", item)
for key, items in sorted(refusals.items()):
    for item in items:
        print("REFUSED", key, item)
