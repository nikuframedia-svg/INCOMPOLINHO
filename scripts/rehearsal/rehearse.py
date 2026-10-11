"""Publication rehearsal in an isolated runtime (TestClient on the real app).

Real timings, real budgets: the measurement the plan asks for before each
publication of the engine (recalculate, PRM031 breakdown, small breakdown,
Gantt move). Unlike ``scripts/golden`` it does not make the run repeatable.

Usage (``run.sh`` prepares the runtime copy and the environment)::

  PP1_DATA_DIR=<rt>/data PP1_CONFIG_PATH=<rt>/config/factory.yaml \
    python -B rehearse.py --code <code_root> --oracle-dir <code_root>/tests \
      --out out.json --actions recalc,outage31 [--move LOT,DAY,START] \
      [--stock-sku SKU ...] [--raise]

Actions: none, recalc, outage31 (PRM031 19/10-09/11: full rebuild), outage19,
outagesunday (PRM031 on Sunday 18/10), outageshift (PRM031 shift A on 19/10:
the small breakdown of the golden master, F3_outage_small, which runs the
local repair), move, legacymove. ``outagesmall`` was the old name of
``outagesunday`` and is refused, because "small" meant the Sunday case here
and the shift case in the golden master.
``PP1_DATA_DIR``/``PP1_CONFIG_PATH`` must be an isolated copy: never the
running application's ``data/`` or ``config/``.
"""
import argparse
import json
import logging
import os
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path

LIVE_TREE = Path(os.environ.get("PP1_LIVE_TREE", "/home/luis/projects/INCOMPOLINHO")).resolve()

_parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
_parser.add_argument("--code", required=True, help="code tree to import backend from")
_parser.add_argument("--oracle-dir", required=True, help="directory with oracle_delivery.py")
_parser.add_argument("--out", required=True)
_parser.add_argument("--actions", default="none")
_parser.add_argument("--move", default="", help="forced Gantt move: LOT_ID,TARGET_DAY,START_MIN")
_parser.add_argument("--stock-sku", action="append", default=[],
                     help="SKU whose stock projection is reported (repeatable)")
_parser.add_argument("--raise", dest="raise_errors", action="store_true",
                     help="let server exceptions propagate (default: record the 500)")
ARGS = _parser.parse_args()
CODE, ORACLE_DIR, OUT, ACTIONS = ARGS.code, ARGS.oracle_dir, ARGS.out, ARGS.actions
MOVE = ARGS.move
if "outagesmall" in ACTIONS.split(","):
    raise SystemExit("ação outagesmall foi renomeada: usar outagesunday (domingo 18/10) ou"
                     " outageshift (turno A 19/10, a avaria pequena do golden master)")
for name in ("PP1_DATA_DIR", "PP1_CONFIG_PATH"):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} must point to an isolated runtime copy")
    resolved = Path(value).resolve()
    if resolved == LIVE_TREE or LIVE_TREE in resolved.parents:
        raise SystemExit(f"{name}={value} is inside the running application's tree")
os.chdir(os.path.dirname(os.environ["PP1_DATA_DIR"]))
sys.path.insert(0, CODE)
sys.path.insert(0, ORACLE_DIR)

LOGS = []


class Grab(logging.Handler):
    def emit(self, record):
        try:
            LOGS.append((round(time.monotonic() - T0, 2), record.levelname, record.name, record.getMessage()[:600]))
        except Exception:  # noqa: BLE001
            pass


T0 = time.monotonic()
root = logging.getLogger()
root.setLevel(logging.INFO)
root.addHandler(Grab(level=logging.INFO))

from fastapi.testclient import TestClient  # noqa: E402
from backend.api.copilot import app  # noqa: E402
from backend.copilot.state import state  # noqa: E402
import oracle_delivery as oracle  # noqa: E402

out = {"code": CODE, "actions": ACTIONS}


def db_rows():
    import sqlite3
    c = sqlite3.connect(f"file:{os.path.join(os.environ['PP1_DATA_DIR'], 'plans.db')}?mode=ro", uri=True)
    active = c.execute("select plan_revision, snapshot_id from plan_runtime").fetchall()
    rows = c.execute(
        "select id, json_extract(payload_json,'$.plan_revision'), created_at, name, source, origin, note, gate_status "
        "from plans order by rowid desc limit 3").fetchall()
    n = c.execute("select count(*) from plans").fetchone()[0]
    c.close()
    return {"active": active, "n_plans": n, "latest": [[str(x)[:200] for x in r] for r in rows]}


def snapshot_checks(tag):
    res = {}
    try:
        from backend.scheduler.validation import validate_plan
        v = validate_plan(state.segments, state.engine_data, state.config, lots=state.lots)
        res["validate_plan_n"] = len(v)
        res["validate_plan_first"] = [str(x)[:200] for x in v[:5]]
    except Exception as exc:  # noqa: BLE001
        res["validate_plan"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    try:
        from backend.plans.serialize import serialize_snapshot
        from backend.plans.store import _assert_activatable_payload
        payload = serialize_snapshot(state)
        try:
            _assert_activatable_payload(json.loads(json.dumps(payload, default=str)))
            res["activatable"] = "yes"
        except Exception as exc:  # noqa: BLE001
            res["activatable"] = f"no: {type(exc).__name__} code={getattr(exc, 'code', None)}: {str(exc)[:400]}"
    except Exception as exc:  # noqa: BLE001
        res["activatable"] = f"error: {type(exc).__name__}: {str(exc)[:300]}"
    try:
        from backend.scheduler.canonical import quantity_material_version
        res["material_version"] = quantity_material_version(state.lots)
    except Exception as exc:  # noqa: BLE001
        res["material_version"] = f"n/a {type(exc).__name__}"
    return res


def views(client, tag):
    v = {}

    def get(path):
        r = client.get(path)
        if r.status_code != 200:
            return {"_status": r.status_code, "_body": r.text[:400]}
        return r.json()

    t = time.monotonic()
    pv = get("/api/data/plan-view")
    if "_status" in pv:
        v["plan_view"] = pv
        return v
    v["revision"] = pv.get("plan_revision")
    v["plan_notices"] = pv.get("plan_notices", "MISSING")
    score = pv.get("score") or {}
    gate = pv.get("gate_report") or {}
    keys = ["otd", "otd_d", "tardy_count", "otd_d_failures", "setups", "subcontract_dispatch_misses",
            "production_due_misses", "orders_late", "early_window_violations", "hard_violations",
            "missing_lots", "missing_qty", "total_segments", "total_lots"]
    v["score"] = {k: score.get(k) for k in keys}
    v["gate"] = {k: gate.get(k) for k in ("approval_reasons", "apply_decision", "requires_approval",
                                          "physical_gate_passed", "coverage_gate_passed",
                                          "operational_gate_passed", "operational_audit_status")}
    v["gate"]["metrics"] = {k: (gate.get("metrics") or {}).get(k) for k in
                            ("orders_total", "orders_late", "order_otd", "tardy_count", "otd_d_failures")}
    v["plan_view_warnings"] = (pv.get("warnings") or [])[:15]
    v["n_plan_view_warnings"] = len(pv.get("warnings") or [])

    today = get("/api/data/today")
    v["today"] = today
    tidx = max(0, int(today.get("today_idx", 0))) if isinstance(today, dict) and "today_idx" in today else 0

    orders = get("/api/data/orders")
    if isinstance(orders, dict) and "_status" in orders:
        v["orders"] = orders
        flat = []
    else:
        flat = [o for c in orders for o in c["orders"]]
    v["orders_total"] = len(flat)
    v["orders_status"] = dict(sorted({s: sum(1 for o in flat if o["status"] == s)
                                      for s in {o["status"] for o in flat}}.items()))
    v["orders_late_set"] = sorted((o["sku"], o["client"], o["delivery_day"]) for o in flat
                                  if o["ready_day"] is None or o["ready_day"] > o["delivery_day"])
    v["orders_status_late_set"] = sorted((o["sku"], o["client"], o["delivery_day"]) for o in flat
                                         if o["status"] == "late")
    orders_by_key = {f'{o["sku"]}|{o["client"]}|{o["delivery_day"]}|{o["order_qty"]}': o["ready_day"] for o in flat}

    stock = get("/api/data/stock")
    projections = stock if isinstance(stock, list) else (stock.get("projections") or stock.get("skus") or [])
    ruptures = {}
    for p in projections if isinstance(projections, list) else []:
        if p.get("stockout_day") is not None:
            ruptures[p.get("sku") or p.get("op_id")] = p["stockout_day"]
    v["stock_ruptures"] = ruptures
    for sku in ARGS.stock_sku:
        d = get(f"/api/data/stock/{sku}")
        v[f"stock_{sku}"] = d.get("stockout_day", d) if isinstance(d, dict) else d

    late = get("/api/data/late")
    v["late"] = late if "_status" in late else {"tardy_count": late.get("tardy_count"),
                                                "lots": sorted({a["lot_id"] for a in late.get("analyses", [])})}
    risk = get("/api/data/risk")
    if "_status" in risk:
        v["risk"] = risk
    else:
        lr = risk.get("lot_risks", [])
        v["risk"] = {"n": len(lr), "late_lots": sorted(r["lot_id"] for r in lr if r.get("status") == "late"),
                     "levels": dict(sorted({lv: sum(1 for r in lr if r.get("status") == lv)
                                            for lv in {r.get("status") for r in lr}}.items()))}
    console = get(f"/api/console?day_idx={tidx}")
    if isinstance(console, dict) and "_status" in console:
        v["console"] = console
    else:
        v["console"] = {"day_idx": tidx, "keys": sorted(console)[:30]}
        txt = json.dumps(console, default=str)
        v["console"]["mentions_late"] = txt.count('"late"')
        for k in ("summary", "alerts", "risks", "kpis", "headline"):
            if k in console:
                v["console"][k] = json.dumps(console[k], default=str, ensure_ascii=False)[:800]
    exp = get("/api/data/expedition")
    if "_status" in exp:
        v["expedition"] = exp
    else:
        entries = [e for d in exp["days"] for e in d["entries"]]
        v["expedition"] = {
            "entries": len(entries),
            "status": dict(sorted({s: sum(1 for e in entries if e["status"] == s)
                                   for s in {e["status"] for e in entries}}.items())),
            "late_set": sorted((e["sku"], e["client"], e["day_idx"]) for e in entries
                               if e.get("ready_day") is None or e["ready_day"] > e["day_idx"]),
            "fill_rate": exp.get("fill_rate"), "at_risk_count": exp.get("at_risk_count"),
        }
    v["views_s"] = round(time.monotonic() - t, 2)

    # Independent oracle
    o = oracle.oracle_orders(state.segments, state.lots, state.engine_data)
    oracle_late = sorted((x.sku, x.client, x.due_day) for x in o if x.late)
    oracle_by_key = {f"{x.sku}|{x.client}|{x.due_day}|{x.qty}": x.ready_day for x in o}
    mism = [(k, orders_by_key.get(k), r) for k, r in oracle_by_key.items() if orders_by_key.get(k, "MISSING") != r]
    v["oracle"] = {
        "orders": len(o), "late_set": oracle_late,
        "otd_d_failures": oracle.oracle_otd_d_failures(state.segments, state.lots, state.engine_data),
        "ruptures": {k: r for k, r in oracle.oracle_first_rupture(
            state.segments, state.lots, state.engine_data).items() if r is not None},
        "orders_view_vs_oracle_mismatch_n": len(mism),
        "orders_view_vs_oracle_mismatch": mism[:10],
    }
    try:
        wv = oracle.oracle_window_violations(state.segments, state.lots, state.engine_data)
        v["oracle"]["window_violations_n"] = len(wv)
        v["oracle"]["window_violations_first"] = [str(x)[:300] for x in wv[:8]]
        twin_ids = {lot.id for lot in state.lots if getattr(lot, "is_twin", False)}
        v["oracle"]["window_violations_twin_n"] = sum(1 for x in wv if getattr(x, "lot_id", None) in twin_ids)
    except Exception as exc:  # noqa: BLE001
        v["oracle"]["window_violations"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    v["consistency"] = {
        "orders_eq_oracle": v["orders_late_set"] == oracle_late,
        "expedition_eq_oracle": (v["expedition"].get("late_set") if isinstance(v["expedition"], dict) else None) == oracle_late,
        "late_view_n": (v["late"].get("tardy_count") if isinstance(v["late"], dict) else None),
        "risk_late_lots": len(v["risk"].get("late_lots", [])) if isinstance(v["risk"], dict) else None,
        "false_stock_ruptures": sorted(set(ruptures) - set(v["oracle"]["ruptures"])),
        "missed_stock_ruptures": sorted(set(v["oracle"]["ruptures"]) - set(ruptures)),
    }
    v["checks"] = snapshot_checks(tag)
    return v


def log_slice(start):
    return [x for x in LOGS[start:] if x[1] in ("WARNING", "ERROR", "CRITICAL")
            or "restor" in x[3].lower() or "recalc" in x[3].lower()]


def do_recalc(client):
    res = {}
    rid = str(uuid.uuid4())
    body = {"compact_active_plan": True, "approve_exceptions": False, "approval_reason": "",
            "approval_author": "", "expected_revision": state.plan_revision, "request_id": rid}
    t = time.monotonic()
    r = client.post("/api/data/recalculate", json=body)
    res["first_status"] = r.status_code
    res["first_s"] = round(time.monotonic() - t, 2)
    data = r.json()
    if r.status_code == 409:
        detail = data.get("detail", data)
        res["first_detail"] = json.dumps(detail, default=str, ensure_ascii=False)[:2500]
        gr = detail.get("gate_report") if isinstance(detail, dict) else None
        if isinstance(detail, dict) and detail.get("candidate_id") and (gr or {}).get("requires_approval"):
            body2 = dict(body, candidate_id=detail["candidate_id"], approve_exceptions=True,
                         approval_reason="Ensaio de publicação: aprovação do planeador",
                         approval_author="planeador")
            t2 = time.monotonic()
            r2 = client.post("/api/data/recalculate", json=body2)
            res["second_status"] = r2.status_code
            res["second_s"] = round(time.monotonic() - t2, 2)
            data = r2.json()
            if r2.status_code != 200:
                res["second_detail"] = json.dumps(data, default=str, ensure_ascii=False)[:2500]
    elif r.status_code != 200:
        res["first_detail"] = json.dumps(data, default=str, ensure_ascii=False)[:2500]
    if isinstance(data, dict) and data.get("status") == "ok":
        res["time_ms"] = data.get("time_ms")
        res["plan_revision"] = data.get("plan_revision")
        res["warnings"] = data.get("warnings")
        g = data.get("gate_report") or {}
        res["gate"] = {k: g.get(k) for k in ("approval_reasons", "apply_decision", "requires_approval")}
    res["total_s"] = round(time.monotonic() - t, 2)
    return res


OUTAGES = {"outage31": ("PRM031", "2026-10-19T00:01", "2026-11-09T23:59"),
           "outage19": ("PRM019", "2026-10-19T00:01", "2026-10-23T23:59"),
           "outagesunday": ("PRM031", "2026-10-18T00:01", "2026-10-18T23:59"),
           "outageshift": ("PRM031", "2026-10-19T07:00", "2026-10-19T15:30")}



def do_outage(client, kind="outage31"):
    res = {}
    resource, st, en = OUTAGES[kind]
    res["outage"] = [resource, st, en]
    body = {"reason": "Indisponibilidades alteradas",
            "config_updates": {"unavailability_additions": [{
                "kind": "machine", "resource": resource, "start_at": st,
                "end_at": en, "category": "Avaria", "reason": "Ensaio de publicação"}]},
            "expected_revision": state.plan_revision, "request_id": str(uuid.uuid4())}
    t = time.monotonic()
    r = client.post("/api/data/replan-jobs", json=body)
    res["start_status"] = r.status_code
    if r.status_code not in (200, 202):
        res["start_detail"] = r.text[:2000]
        return res
    job = r.json()["job"]
    jid = job["id"]
    phases = []
    while job["status"] not in ("ready", "completed", "failed", "cancelled", "blocked"):
        time.sleep(0.5)
        job = client.get(f"/api/data/replan-jobs/{jid}").json()["job"]
        ph = (job.get("phase"), job.get("message"))
        if not phases or phases[-1][1:] != ph:
            phases.append((round(time.monotonic() - t, 1),) + ph)
        if time.monotonic() - t > 600:
            res["timeout"] = True
            break
    res["job_s"] = round(time.monotonic() - t, 2)
    res["phases"] = phases
    res["status"] = job["status"]
    res["message"] = job.get("message")
    res["error"] = job.get("error")
    res["code"] = job.get("code")
    res["warnings"] = (job.get("warnings") or [])[:20]
    result = job.get("result") or {}
    sc = result.get("score") or {}
    res["score"] = {k: sc.get(k) for k in ("otd", "otd_d", "tardy_count", "setups", "orders_late",
                                           "early_window_violations", "hard_violations")}
    g = result.get("gate_report") or {}
    res["gate"] = {k: g.get(k) for k in ("approval_reasons", "apply_decision", "requires_approval",
                                         "physical_gate_passed", "coverage_gate_passed")}
    res["gate_metrics"] = {k: (g.get("metrics") or {}).get(k) for k in ("orders_total", "orders_late", "order_otd")}
    res["selected_source"] = result.get("selected_source")
    if job["status"] == "ready":
        ab = {"expected_revision": job.get("base_revision", state.plan_revision),
              "approve_exceptions": bool(g.get("requires_approval")),
              "approval_reason": "Ensaio de publicação: avaria PRM031" if g.get("requires_approval") else "",
              "approval_author": "planeador" if g.get("requires_approval") else "",
              "request_id": str(uuid.uuid4())}
        t2 = time.monotonic()
        a = client.post(f"/api/data/replan-jobs/{jid}/apply", json=ab)
        res["apply_status"] = a.status_code
        res["apply_s"] = round(time.monotonic() - t2, 2)
        if a.status_code != 200:
            res["apply_detail"] = a.text[:2000]
        else:
            aj = a.json()
            res["apply_message"] = aj["job"].get("message")
            res["plan_revision"] = aj.get("plan_revision")
    res["total_s"] = round(time.monotonic() - t, 2)
    return res


def do_legacymove(client):
    res = {"rev": state.plan_revision}
    lot = next(item for item in state.lots
               if any(s.lot_id == item.id and s.day_idx > 20 for s in state.segments))
    seg = min((s for s in state.segments if s.lot_id == lot.id), key=lambda s: (s.day_idx, s.start_min))
    req = {"lot_id": lot.id, "target_day": seg.day_idx + 1, "target_machine": seg.machine_id,
           "target_start_min": 420, "reason": "Ensaio", "author": "planeador"}
    res["req"] = req
    for name, path, extra in (("job", "/api/data/plan/move-preview-jobs", {}),
                              ("preview", "/api/data/plan/move-preview", {}),
                              ("apply", "/api/data/plan/move-apply",
                               {"expected_revision": state.plan_revision, "request_id": str(uuid.uuid4())})):
        t = time.monotonic()
        r = client.post(path, json={**req, **extra})
        res[name] = {"status": r.status_code, "s": round(time.monotonic() - t, 3), "body": r.text[:1500]}
    res["rev_after"] = state.plan_revision
    return res


def do_move(client):
    """Gantt move as MoveLotModal does: preview job, poll, apply with preview_job_id."""
    res = {"attempts": []}
    tidx = int(client.get("/api/data/today").json().get("today_idx", 0))
    started = {seg.lot_id for seg in state.segments if seg.day_idx <= tidx + 1}
    by_lot = defaultdict(list)
    for seg in state.segments:
        by_lot[seg.lot_id].append(seg)
    cands = []
    for lot in state.lots:
        segs = by_lot.get(lot.id) or []
        if not segs or lot.id in started:
            continue
        first = min(s.day_idx for s in segs)
        if first < tidx + 6 or getattr(lot, "is_twin", False):
            continue
        edd = getattr(lot, "edd", None)
        cands.append((first, lot.id, segs[0].machine_id, edd))
    cands.sort()
    # move a mid-horizon lot one working day later on the same machine, at shift start
    pick = cands[len(cands) // 3: len(cands) // 3 + 6]
    if MOVE:
        lid, day, smin = MOVE.split(",")
        segs = by_lot[lid]
        pick = [(int(day) - 1, lid, segs[0].machine_id, None)]
        res["forced"] = MOVE
    for first, lot_id, machine, edd in pick:
        att = {"lot_id": lot_id, "machine": machine, "from_day": first, "edd": edd}
        req = {"lot_id": lot_id, "target_day": first + 1, "target_machine": machine,
               "target_start_min": int(MOVE.split(",")[2]) if MOVE else 420, "reason": "Ensaio de publicação", "author": "planeador"}
        t = time.monotonic()
        r = client.post("/api/data/plan/move-preview-jobs", json=req)
        att["start_status"] = r.status_code
        if r.status_code != 200:
            att["start_detail"] = r.text[:800]
            res["attempts"].append(att)
            continue
        job = r.json()["job"]
        while job["status"] in ("queued", "running"):
            time.sleep(0.5)
            job = client.get(f"/api/data/plan/move-preview-jobs/{job['id']}").json()["job"]
            if time.monotonic() - t > 300:
                att["timeout"] = True
                break
        att["preview_s"] = round(time.monotonic() - t, 2)
        att["status"] = job["status"]
        att["message"] = job.get("message")
        att["error"] = job.get("error")
        att["code"] = job.get("code")
        result = job.get("result") or {}
        if job["status"] != "ready" or not result:
            res["attempts"].append(att)
            continue
        att["requires_confirmation"] = result.get("requires_confirmation")
        att["delivery_warnings"] = (result.get("delivery_warnings") or [])[:5]
        att["delta"] = result.get("delta")
        att["score"] = {k: (result.get("score") or {}).get(k) for k in ("otd", "otd_d", "tardy_count", "setups")}
        g = result.get("gate_report") or {}
        att["gate"] = {k: g.get(k) for k in ("approval_reasons", "apply_decision", "requires_approval")}
        need = bool(result.get("requires_confirmation") or g.get("requires_approval"))
        body = {**req, "preview_job_id": job["id"], "expected_revision": job.get("base_revision"),
                "approve_exceptions": need, "approval_reason": "Ensaio de publicação: movimento" if need else "",
                "approval_author": "planeador", "confirm_delivery_risk": need, "request_id": str(uuid.uuid4())}
        t2 = time.monotonic()
        a = client.post("/api/data/plan/move-apply", json=body)
        att["apply_status"] = a.status_code
        att["apply_s"] = round(time.monotonic() - t2, 2)
        if a.status_code != 200:
            att["apply_detail"] = a.text[:1500]
        else:
            att["plan_revision"] = state.plan_revision
        att["total_s"] = round(time.monotonic() - t, 2)
        res["attempts"].append(att)
        if a.status_code == 200:
            break
    return res


try:
    with TestClient(app, raise_server_exceptions=ARGS.raise_errors) as client:
        out["startup_s"] = round(time.monotonic() - T0, 2)
        out["startup_state"] = {
            "plan_revision": state.plan_revision,
            "warnings": list(state.warnings or [])[:20],
            "gate_report": {k: (state.gate_report or {}).get(k) for k in
                            ("approval_reasons", "apply_decision", "requires_approval",
                             "physical_gate_passed", "coverage_gate_passed")},
        }
        out["startup_db"] = db_rows()
        out["startup_logs"] = log_slice(0)
        out["views_startup"] = views(client, "startup")
        for action in [a for a in ACTIONS.split(",") if a and a != "none"]:
            mark = len(LOGS)
            rev_before = state.plan_revision
            if action == "recalc":
                res = do_recalc(client)
            elif action in OUTAGES:
                res = do_outage(client, action)
            elif action == "legacymove":
                res = do_legacymove(client)
            elif action == "move":
                res = do_move(client)
            else:
                raise SystemExit(f"unknown action {action}")
            res["rev_before"] = rev_before
            res["rev_after"] = state.plan_revision
            res["logs"] = log_slice(mark)[:40]
            res["db"] = db_rows()
            res["views"] = views(client, action)
            key = action
            while key in out:
                key += "_2"
            out[key] = res
except BaseException as exc:  # noqa: BLE001
    import traceback
    out["FATAL"] = f"{type(exc).__name__}: {str(exc)[:1500]}"
    out["FATAL_tb"] = traceback.format_exc()[-4000:]
    out["logs_tail"] = LOGS[-40:]

with open(OUT, "w") as fh:
    json.dump(out, fh, indent=1, default=str, ensure_ascii=False)
print("DONE", OUT, "FATAL" in out)
