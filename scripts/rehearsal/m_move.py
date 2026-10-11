"""Diagnose one manual move on a stored plan revision (read-only).

Loads the revision from a copy of ``plans.db`` (opened ``mode=ro``), wraps
the manual-move paths to print how long each took and what it returned, and
runs ``move_lot`` directly (no app, nothing persisted).

Usage::

  python -B m_move.py --code <code_root> --db <copy of plans.db> --revision 124 \
      --lot LOT_ID --day 19 [--machine PRM039] [--start 930]
"""

import argparse
import json
import logging
import sqlite3
import sys
import time

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--code", required=True)
parser.add_argument("--db", required=True, help="a copy of plans.db (never the live one)")
parser.add_argument("--revision", type=int, required=True)
parser.add_argument("--lot", required=True)
parser.add_argument("--day", type=int, required=True)
parser.add_argument("--machine", default=None)
parser.add_argument("--start", type=int, default=420)
args = parser.parse_args()

sys.path.insert(0, args.code)
logging.basicConfig(
    level=logging.WARNING, format="%(relativeCreated)d %(levelname)s %(name)s %(message)s"
)

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
result = restored.get("result") or restored
segments = result["segments"] if isinstance(result, dict) else result.segments
lots = result["lots"] if isinstance(result, dict) else result.lots
score = (result.get("score") if isinstance(result, dict) else result.score) or {}

TRACED = (
    "_fixed_positions_move",
    "_allocate_existing_lots",
    "_replan_around_fixed_lot",
    "_finalize_move_candidate",
    "_preserves_production",
)


def _traced(name, original):
    def wrapper(*call_args, **call_kwargs):
        started = time.monotonic()
        try:
            output = original(*call_args, **call_kwargs)
        except BaseException as exc:
            print(f"CALL {name} RAISED {type(exc).__name__}: {str(exc)[:600]} "
                  f"{time.monotonic() - started:.2f}s")
            raise
        extra = ""
        if output is not None and hasattr(output, "gate_report"):
            gate = output.gate_report or {}
            violations = [str(item)[:200] for item in (gate.get("violations") or [])[:3]]
            extra = f" phys={gate.get('physical_gate_passed')} viol={violations}"
        kind = output if isinstance(output, bool) else type(output).__name__
        print(f"CALL {name} -> {kind} {time.monotonic() - started:.2f}s{extra}")
        return output

    return wrapper


for traced_name in TRACED:
    if hasattr(mm, traced_name):
        setattr(mm, traced_name, _traced(traced_name, getattr(mm, traced_name)))

lot = next(item for item in lots if item.id == args.lot)
first_segments = sorted(
    (s.day_idx, s.start_min, s.machine_id) for s in segments if s.lot_id == args.lot
)[:4]
print("lot", args.lot, "machine", lot.machine_id, "alt", lot.alt_machine_id,
      "edd", lot.edd, "segs", first_segments)
started = time.monotonic()
try:
    out = mm.move_lot(
        segments, lots, score, restored["engine_data"], restored["config"],
        lot_id=args.lot, target_day=args.day, target_machine=args.machine or lot.machine_id,
        target_start_min=args.start, reason="diag", author="diag",
    )
    print("OK", round(time.monotonic() - started, 2), out.requires_confirmation,
          out.gate_report.get("approval_reasons"), out.delta)
except Exception as exc:  # noqa: BLE001 - diagnostic script reports every refusal
    print("FAIL", round(time.monotonic() - started, 2), type(exc).__name__, str(exc)[:500])
