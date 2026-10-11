#!/usr/bin/env python3
"""Golden-master flows F1–F10 of the INCOMPOLINHO planner (plan Passo 1b).

One flow runs in its own process, against one code tree, on a fresh copy of
the pristine production state (``capture.py`` prepares the copy, the
environment and the core). The result is one canonical JSON whose sha256 says
whether two code trees plan the same.

Usage (normally through ``capture.py``)::

  python -B flows.py --code <tree> --flow F1_recalculate --run-dir <copy> \
      --pristine <golden>/pristine --out <dir>/F1_recalculate.json \
      --mode deterministic --calibration <golden>/calibration.json

Deterministic mode (``--mode deterministic``), so a run stops by evaluation
count and never by wall clock (AGENTS §6: a time cut is not deterministic):

* ``improve_plan`` gets ``max_evaluations`` = the number of candidates the
  same call evaluated in the calibration run, when that call stopped on its
  time budget (``stop_reason == "budget"``); calls that ended on their own
  keep no cap. A call the calibration never saw gets the flow's largest
  budget-stopped count, else ``DEFAULT_EVALUATION_CAP``;
* every planning budget is multiplied by ``SLOW_FACTOR``: ``time.monotonic``
  runs that many times slower for this process. That covers every budget
  constant at once (``MODE_CONFIG[...]["time_budget_s"]``,
  ``REPLAN_TOTAL_BUDGET_S``, ``LOCAL_REPAIR_OPTIMIZER_RESERVE_S``,
  ``MANUAL_MOVE_BUDGET_S``, ``RECALCULATE_RESPONSE_MARGIN_S``,
  ``planning_control.CLOSING_WORK_S`` and the literal 60 s scopes), whatever
  module they move to. asyncio keeps the real clock;
* CP-SAT's ``max_time_in_seconds`` T becomes ``max_deterministic_time`` T
  (one worker, fixed seed: repeatable), with T x ``SLOW_FACTOR`` of wall
  clock as a safety net.

So a branch that production takes only when time runs out is not the one
recorded here. Example: with the real budgets on one loaded core, the quick
calendar adjustment of F3_outage_small did not finish and the plan was
rebuilt ("O ajuste rápido não terminou a tempo"); the golden master records
the adjustment itself (``selected_source``: ``repaired_baseline_calendar``).
Real timings belong to the rehearsal (``scripts/rehearsal``).

Both modes:

* ``datetime.datetime.now/utcnow/today`` return the pristine capture instant
  (``MANIFEST.json`` ``clock_anchor``; fixture anchors for F2), frozen: the
  planning day, rule-4 freezing and every stamp are the same on every run;
* ``uuid.uuid4`` draws from a generator seeded with the flow name;
* ``.env`` files are not loaded (``PP1_LLM_BACKEND=none``: the LLM is
  bypassed);
* an audit hook refuses writes into the live tree, the code tree and the
  pristine inputs, SQLite connections outside the runtime copy, and TCP
  connections (no request reaches :8010).

The calibration run (``--mode calibrate``) uses the real budgets and clock to
record those evaluation counts (``capture.py --calibrate``).

Canonical output: dict keys sorted; keys in ``VOLATILE_KEYS`` and
``VOLATILE_CHILD_KEYS`` removed (wall-clock durations, hashes the application
takes over them, SQLite ``datetime('now')`` stamps, process ids); random
identifiers (32-hex uuids, ``manual_``/``edit_``/``u_`` ids, including inside
strings) replaced by ``<id-N>`` in order of first appearance. The sha256 is
taken over ``result``; ``meta`` (timings, versions) is not hashed.
``result.equivalence`` holds the coarse facts compared for flows that do
not reproduce byte for byte ("só equivalência").

Client data (lot ids, SKUs) never appears in this file: flow parameters live
in ``<golden>/pristine/flow_params.json`` (outside git).
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import copy
import dataclasses
import datetime as _datetime
import functools
import gzip
import hashlib
import importlib
import json
import logging
import math
import os
import random
import re
import socket
import sqlite3
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

LIVE_TREE = Path(os.environ.get("PP1_LIVE_TREE", "/home/luis/projects/INCOMPOLINHO"))
SLOW_FACTOR = 20.0
DEFAULT_EVALUATION_CAP = 200
JOB_TIMEOUT_S = 3600.0
POLL_S = 1.0
APPROVAL_REASON = "Golden master: aprovação do planeador"
APPROVAL_AUTHOR = "planeador"
FIXTURES = ("rev90", "rev121", "rev124")
# Planning day of each frozen fixture (its manifest ``as_of``; rev121 shares
# rev124's ISOP and day). 12:00 Lisbon (WEST, UTC+1) on that date.
FIXTURE_ANCHORS = {
    "rev90": "2026-10-02T12:00:00+01:00",
    "rev121": "2026-10-11T12:00:00+01:00",
    "rev124": "2026-10-11T12:00:00+01:00",
}
EXCLUDED_GET_ROUTES = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})

# ─── Canonical form ────────────────────────────────────────────────────

# Removed wherever they appear. Each entry is a measurement of the machine,
# not of the plan; anything else that differs between two runs of the same
# code makes the flow "equivalence-only" instead of joining this list.
VOLATILE_KEYS = frozenset({
    # wall-clock durations (vary with load; budgets are cut by evaluations)
    "time_ms",
    "duration_ms",
    "elapsed_ms",
    "compaction_s",
    # stamps written by SQLite ``datetime('now')`` (the plans table), which
    # the frozen Python clock cannot reach
    "created_at",
    # operating-system process ids of job workers
    "worker_pid",
    # hashes the application takes over the durations above (the candidate
    # payload holds ``time_ms`` and the improvement report's ``duration_ms``)
    "candidate_fingerprint",
})
# (parent key, key): removed only under that parent. ``fingerprints.plan`` of
# a stored plan hashes its improvement report, durations included.
VOLATILE_CHILD_KEYS = frozenset({("fingerprints", "plan")})
_HEX32 = r"[0-9a-f]{32}"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ID_PATTERN = re.compile(
    rf"(?<![0-9a-f]){_HEX32}(?![0-9a-f])|(?<![0-9a-f-]){_UUID}(?![0-9a-f-])"
    r"|(?<=manual_)[0-9a-f]{12}(?![0-9a-f])|(?<=edit_)[0-9a-f]{12}(?![0-9a-f])"
    r"|(?<=\bu_)[0-9a-f]{12}(?![0-9a-f])"
)


def jsonable(value):
    """Plain JSON types; dataclasses, sets and tuples included."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((jsonable(item) for item in value), key=lambda item: json.dumps(item))
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return repr(value)


def canonicalize(value):
    """Canonical form of a JSON value (see the module docstring)."""
    placeholders: dict[str, str] = {}

    def placeholder(match: re.Match) -> str:
        token = match.group(0)
        if token not in placeholders:
            placeholders[token] = f"<id-{len(placeholders) + 1}>"
        return placeholders[token]

    def text(item: str) -> str:
        return _ID_PATTERN.sub(placeholder, item)

    def walk(item, parent=None):
        if isinstance(item, dict):
            return {
                text(str(key)): walk(item[key], key)
                for key in sorted(item, key=str)
                if key not in VOLATILE_KEYS and (parent, key) not in VOLATILE_CHILD_KEYS
            }
        if isinstance(item, list):
            return [walk(element) for element in item]
        if isinstance(item, str):
            return text(item)
        return item

    return walk(jsonable(value))


def canonical_dumps(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value) -> str:
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()


# ─── Flow registry ─────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class Flow:
    name: str
    group: str
    function: str
    kwargs: tuple = ()
    fast: bool = False
    skip_reason: str = ""
    # Rough relative cost, used only to start the longest flows first.
    weight: int = 1


def _flows() -> dict[str, Flow]:
    flows = [
        Flow("F1_recalculate", "F1", "flow_recalculate", weight=3),
        Flow("F2_quick", "F2", "flow_optimize_quick", fast=True, weight=1),
    ]
    for fixture in FIXTURES:
        flows.append(Flow(f"F2_normal_{fixture}", "F2", "flow_optimize_normal",
                          (("fixture", fixture),), fast=fixture == "rev124", weight=3))
        flows.append(Flow(f"F2_preserve_{fixture}", "F2", "flow_optimize_preserving",
                          (("fixture", fixture),), weight=3))
    flows += [
        Flow("F3_outage_small", "F3", "flow_outage",
             (("resource", "PRM031"), ("start_at", "2026-10-19T07:00"),
              ("end_at", "2026-10-19T15:30")), fast=True, weight=3),
        Flow("F3_outage_big", "F3", "flow_outage",
             (("resource", "PRM031"), ("start_at", "2026-10-19T00:01"),
              ("end_at", "2026-11-09T23:59")), weight=3),
        Flow("F3_outage_sunday", "F3", "flow_outage",
             (("resource", "PRM031"), ("start_at", "2026-10-18T00:01"),
              ("end_at", "2026-10-18T23:59")), weight=3),
        Flow("F4_manual_move", "F4", "flow_manual_move", fast=True, weight=3),
        Flow("F5_simulate_scenarios", "F5", "flow_simulate_scenarios", weight=4),
        Flow("F5_ctp", "F5", "flow_ctp", weight=3),
        Flow("F6_copilot_quick", "F6", "flow_copilot", (("modo", "quick"),), weight=2),
        Flow("F6_copilot_normal", "F6", "flow_copilot", (("modo", "normal"),), weight=3),
        Flow("F7_holiday", "F7", "flow_holiday", weight=3),
        Flow("F7_sku_rule", "F7", "flow_sku_rule", weight=3),
        Flow("F7_config_oee", "F7", "flow_config_oee", weight=3),
        Flow("F8_startup_reads", "F8", "flow_startup_reads", weight=2),
        Flow("F9_isop_load", "F9", "", skip_reason=(
            "À espera de um ISOP real (decisão D19): o sistema não guarda o ficheiro "
            "carregado, por isso não há entrada para repetir o carregamento. Obrigatório "
            "antes de mexer no código de leitura do ISOP (Passo 8).")),
        Flow("F10_robustness", "F10", "flow_robustness", weight=1),
    ]
    return {flow.name: flow for flow in flows}


FLOWS = _flows()


# ─── Harness: clock, identifiers, CP-SAT, budgets, guard ───────────────

_REAL_DATETIME = _datetime.datetime
_REAL_MONOTONIC = time.monotonic
_ANCHOR: list[_datetime.datetime] = []


class _ClockMeta(type):
    """``isinstance(real_datetime, datetime)`` keeps working after the patch."""

    def __instancecheck__(cls, instance):
        return isinstance(instance, _REAL_DATETIME)

    def __subclasscheck__(cls, subclass):
        return issubclass(subclass, _REAL_DATETIME)


class FrozenDatetime(_REAL_DATETIME, metaclass=_ClockMeta):
    """``datetime.datetime`` whose ``now`` is the anchor; instances stay real."""

    def __new__(cls, *args, **kwargs):
        return _REAL_DATETIME(*args, **kwargs)

    @classmethod
    def now(cls, tz=None):
        anchor = _ANCHOR[0]
        if tz is None:
            return anchor.astimezone().replace(tzinfo=None)
        return anchor.astimezone(tz)

    @classmethod
    def utcnow(cls):
        return _ANCHOR[0].astimezone(_datetime.timezone.utc).replace(tzinfo=None)

    @classmethod
    def today(cls):
        return cls.now()


def parse_anchor(value: str) -> _datetime.datetime:
    anchor = _REAL_DATETIME.fromisoformat(value)
    if anchor.tzinfo is None:
        raise ValueError(f"clock anchor needs a UTC offset: {value}")
    return anchor


class Harness:
    def __init__(self, args):
        self.mode = args.mode
        self.flow = args.flow
        self.code = Path(args.code).resolve()
        self.run_dir = Path(args.run_dir).resolve()
        self.pristine = Path(args.pristine).resolve()
        self.out_dir = Path(args.out).resolve().parent
        self.calibration = {}
        if args.calibration:
            self.calibration = json.loads(Path(args.calibration).read_text())
        self.improvement_calls: list[dict] = []
        self.cpsat_solves = 0
        self.legacy_alarms: list[str] = []
        self._lock = threading.Lock()
        self._cpsat_limits: dict[int, tuple[float, float]] = {}
        self.protected = [LIVE_TREE.resolve(), self.code, self.pristine]
        self.set_anchor(args.anchor)

    # clock anchor -----------------------------------------------------
    def set_anchor(self, value: str) -> None:
        anchor = parse_anchor(value)
        if _ANCHOR:
            _ANCHOR[0] = anchor
        else:
            _ANCHOR.append(anchor)

    def real_monotonic(self) -> float:
        return _REAL_MONOTONIC()

    # installation -----------------------------------------------------
    def install(self) -> None:
        # Modules that keep a reference to the real monotonic clock (their
        # timeouts are not planning budgets) are imported first.
        import asyncio.base_events  # noqa: F401
        import concurrent.futures  # noqa: F401
        import queue  # noqa: F401
        import selectors  # noqa: F401

        # Libraries keep the real ``datetime`` class (encoders keyed by type).
        for library in ("pydantic", "fastapi", "fastapi.encoders", "fastapi.testclient",
                        "starlette.testclient", "httpx", "anyio", "yaml",
                        "ortools.sat.python.cp_model"):
            with contextlib.suppress(ImportError):
                importlib.import_module(library)
        sys.addaudithook(self._audit)
        # Alarm of the legacy engine (plan Passo 1d): counted in ``meta``
        # only, so a tree with the alarm and one without stay comparable.
        harness = self

        class _LegacyAlarm(logging.Handler):
            def emit(self, record):
                harness.legacy_alarms.append(record.getMessage())

        logging.getLogger("backend.legacy").addHandler(_LegacyAlarm())
        try:
            import dotenv
            import dotenv.main

            dotenv.load_dotenv = dotenv.main.load_dotenv = lambda *_a, **_k: False
        except ImportError:
            pass
        _datetime.datetime = FrozenDatetime
        rng = random.Random(f"golden-master:{self.flow}")
        uuid_lock = threading.Lock()

        def uuid4():
            with uuid_lock:
                bits = rng.getrandbits(128)
            return uuid.UUID(int=bits, version=4)

        uuid.uuid4 = uuid4
        if self.mode == "deterministic":
            self._slow_monotonic()
            self._deterministic_cpsat()

    def _slow_monotonic(self) -> None:
        import asyncio.base_events

        base = _REAL_MONOTONIC()

        def monotonic() -> float:
            return base + (_REAL_MONOTONIC() - base) / SLOW_FACTOR

        time.monotonic = monotonic
        asyncio.base_events.BaseEventLoop.time = lambda _loop: _REAL_MONOTONIC()

    def _deterministic_cpsat(self) -> None:
        from ortools.sat.python import cp_model

        original = cp_model.CpSolver.solve
        harness = self

        def solve(solver, model, solution_callback=None):
            params = solver.parameters
            limit = params.max_time_in_seconds
            previous = harness._cpsat_limits.get(id(solver))
            if previous is not None and limit == previous[1]:
                limit = previous[0]  # the same solver solved again unchanged
            if math.isfinite(limit):
                params.max_deterministic_time = limit
                params.max_time_in_seconds = limit * SLOW_FACTOR
                harness._cpsat_limits[id(solver)] = (limit, limit * SLOW_FACTOR)
            with harness._lock:
                harness.cpsat_solves += 1
            return original(solver, model, solution_callback)

        cp_model.CpSolver.solve = solve
        cp_model.CpSolver.Solve = lambda solver, model, callback=None: solve(
            solver, model, callback
        )

    # write guard --------------------------------------------------------
    def _resolve(self, path) -> Path | None:
        if isinstance(path, int) or path is None:
            return None
        try:
            text = os.fsdecode(path)
        except TypeError:
            return None
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return Path(os.path.realpath(candidate))

    def _check_write(self, path) -> None:
        resolved = self._resolve(path)
        if resolved is None:
            return
        for root in self.protected:
            if resolved == root or root in resolved.parents:
                raise PermissionError(f"golden master: escrita recusada em {resolved}")

    def _check_sqlite(self, database) -> None:
        text = os.fsdecode(database) if isinstance(database, (bytes, os.PathLike)) else database
        if not isinstance(text, str) or text in ("", ":memory:"):
            return
        if text.startswith("file:"):
            path, _, query = text[5:].partition("?")
            if "mode=memory" in query or path in ("", ":memory:"):
                return
            text = path
        resolved = self._resolve(text)
        if resolved is None:
            return
        if not (resolved == self.run_dir or self.run_dir in resolved.parents):
            raise PermissionError(f"golden master: SQLite fora da cópia: {resolved}")

    def _audit(self, event: str, args) -> None:
        if event == "open":
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(char in mode for char in "wax+")) or (
                mode is None and isinstance(flags, int)
                and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            )
            if writing:
                self._check_write(path)
        elif event in ("os.remove", "os.rmdir", "os.mkdir", "os.truncate", "shutil.rmtree"):
            self._check_write(args[0])
        elif event == "os.rename":
            self._check_write(args[0])
            self._check_write(args[1])
        elif event == "sqlite3.connect":
            self._check_sqlite(args[0])
        elif event == "socket.connect":
            sock = args[0]
            if getattr(sock, "family", None) in (socket.AF_INET, socket.AF_INET6):
                raise PermissionError("golden master: ligações de rede recusadas")

    # improvement budget -------------------------------------------------
    def evaluation_cap(self, index: int) -> tuple[int | None, str]:
        calls = ((self.calibration.get("flows") or {}).get(self.flow) or {}).get("calls") or []
        if index < len(calls):
            call = calls[index]
            if call.get("stop_reason") == "budget":
                return int(call.get("candidates_evaluated") or 0), f"calibration[{index}]"
            return None, f"calibration[{index}]:{call.get('stop_reason')}"
        budget = [int(c.get("candidates_evaluated") or 0) for c in calls
                  if c.get("stop_reason") == "budget"]
        if budget:
            return max(budget), "fallback:flow_max"
        return DEFAULT_EVALUATION_CAP, "fallback:default"

    def wrap_improvement(self) -> None:
        module = None
        for name in ("backend.scheduler.improvement", "backend.engine.improve"):
            try:
                module = importlib.import_module(name)
            except ImportError:
                continue
            if hasattr(module, "improve_plan"):
                break
        if module is None or not hasattr(module, "improve_plan"):
            raise RuntimeError("improve_plan not found: update scripts/golden/flows.py")
        original = module.improve_plan
        harness = self

        @functools.wraps(original)
        def improve_plan(*args, **kwargs):
            with harness._lock:
                record: dict = {"index": len(harness.improvement_calls)}
                harness.improvement_calls.append(record)
            if kwargs.get("max_evaluations") is not None:
                record.update(cap=kwargs["max_evaluations"], cap_source="caller")
            elif harness.mode == "deterministic":
                cap, source = harness.evaluation_cap(record["index"])
                record["cap_source"] = source
                if cap is not None:
                    kwargs["max_evaluations"] = cap
                    record["cap"] = cap
            else:
                record["cap_source"] = "calibration-run"
            try:
                segments, lots, report = original(*args, **kwargs)
            except BaseException as exc:
                record["raised"] = type(exc).__name__
                raise
            report_view = report or {}
            for key in ("candidates_evaluated", "stop_reason", "status", "moves_accepted",
                        "closing_compaction", "compactions", "final_signature",
                        "duration_ms"):
                record[key] = report_view.get(key)
            return segments, lots, report

        for loaded in list(sys.modules.values()):
            if getattr(loaded, "improve_plan", None) is original:
                loaded.improve_plan = improve_plan


# ─── Runner: app, HTTP, approvals, jobs, facts ─────────────────────────


def _import_first(*names: str):
    for name in names:
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    raise ImportError(f"none of {names} importable")


class Runner:
    def __init__(self, harness: Harness, params: dict):
        self.h = harness
        self.params = params
        self.steps: list[dict] = []
        self.timings: list[dict] = []
        self.client = None
        self.server_errors: list[dict] = []
        self._requests = 0

    # app and HTTP ------------------------------------------------------
    @contextlib.contextmanager
    def app(self):
        from fastapi.testclient import TestClient

        module = _import_first("backend.api.copilot", "backend.app.main")
        self.h.wrap_improvement()
        started = self.h.real_monotonic()
        with TestClient(module.app, raise_server_exceptions=True) as client:
            self.client = client
            self.timings.append({"label": "startup", "s": round(
                self.h.real_monotonic() - started, 2)})
            self.record_state("startup")
            try:
                yield client
            finally:
                self.client = None

    @property
    def state(self):
        return _import_first("backend.copilot.state", "backend.app.state").state

    def request_id(self, label: str) -> str:
        self._requests += 1
        return f"golden-{self.h.flow}-{self._requests}-{label}"

    def http(self, label, method, path, *, body=None, params=None, record=True):
        started = self.h.real_monotonic()
        try:
            response = self.client.request(method, path, json=body, params=params)
        except Exception as exc:  # noqa: BLE001 - an unhandled server error is a 500
            # The type and message are part of the behaviour; the traceback
            # (line numbers) goes to ``meta`` only.
            self.server_errors.append({"label": label, "traceback": traceback.format_exc()})
            status, payload = 500, {"_exception": f"{type(exc).__name__}: {exc}"}
        else:
            status = response.status_code
            try:
                payload = response.json()
            except ValueError:
                payload = {"_text": response.text[:4000]}
        self.timings.append({"label": label, "s": round(self.h.real_monotonic() - started, 2)})
        if record:
            entry = {"label": label, "method": method, "path": path,
                     "status": status, "body": payload}
            if params:
                entry["params"] = params
            self.steps.append(entry)
        return status, payload

    def write(self, label, method, path, body, *, approve=True):
        """A plan write as the screen does it: on a 409 that asks for
        approval, approve and send again with the same request id."""
        body = dict(body)
        body.setdefault("expected_revision", int(self.state.plan_revision))
        body.setdefault("request_id", self.request_id(label))
        status, response = self.http(f"{label}:first", method, path, body=body)
        detail = response.get("detail") if isinstance(response, dict) else None
        if status == 409 and approve and isinstance(detail, dict) and (
            (detail.get("gate_report") or {}).get("requires_approval") is True
        ) and detail.get("base_revision", body["expected_revision"]) == body["expected_revision"]:
            retry = {**body, "approve_exceptions": True, "approval_reason": APPROVAL_REASON,
                     "approval_author": APPROVAL_AUTHOR}
            if detail.get("candidate_id"):
                retry["candidate_id"] = detail["candidate_id"]
            status, response = self.http(f"{label}:approved", method, path, body=retry)
        return status, response

    def wait_job(self, label, path, *, active, key="job"):
        deadline = self.h.real_monotonic() + JOB_TIMEOUT_S
        started = self.h.real_monotonic()
        while True:
            status, payload = self.http(label, "GET", path, record=False)
            job = payload.get(key) if isinstance(payload, dict) else None
            if status != 200 or not isinstance(job, dict) or job.get("status") not in active:
                self.steps.append({"label": label, "method": "GET", "path": path,
                                   "status": status, "body": payload})
                self.timings.append({"label": f"{label}:wait", "s": round(
                    self.h.real_monotonic() - started, 2)})
                return job if isinstance(job, dict) else {}
            if self.h.real_monotonic() > deadline:
                raise TimeoutError(f"{label}: job still {job.get('status')}")
            time.sleep(POLL_S)

    # facts --------------------------------------------------------------
    def state_facts(self) -> dict:
        serialize = _import_first("backend.plans.serialize")
        improvement = _import_first("backend.scheduler.improvement", "backend.engine.improve")
        state = self.state
        segments, lots = list(state.segments or []), list(state.lots or [])
        config = state.config
        return {
            "plan_revision": int(state.plan_revision or 0),
            "schedule_fingerprint": serialize.schedule_fingerprint(segments, lots),
            "physical_signature": improvement.physical_signature(segments, lots),
            "segments": len(segments),
            "lots": len(lots),
            "lot_quantities": digest(sorted([lot.id, int(lot.qty)] for lot in lots)),
            "score": jsonable(state.score),
            "gate_report": jsonable(state.gate_report),
            "improvement_report": jsonable(state.improvement_report),
            "warnings": jsonable(state.warnings),
            "operator_alerts": jsonable(state.operator_alerts),
            "active_mutations": jsonable(state.active_mutations),
            "manual_edits": jsonable(state.manual_edits),
            "approvals": jsonable(state.approvals),
            "config_fingerprint": (
                serialize.value_fingerprint(serialize.serialize_config(config))
                if config is not None else None
            ),
            "dataset_id": (state.dataset_info or {}).get("id"),
        }

    def record_state(self, label: str) -> dict:
        facts = self.state_facts()
        self.steps.append({"label": f"state:{label}", "state": facts})
        return facts

    def db_facts(self) -> dict:
        path = self.h.run_dir / "data" / "plans.db"
        if not path.exists():
            return {}
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            facts = {
                "plan_runtime": [dict(row) for row in connection.execute(
                    "select * from plan_runtime")],
                "plans": connection.execute("select count(*) from plans").fetchone()[0],
                "latest": [dict(row) for row in connection.execute(
                    "select id, name, source, origin, note, is_auto, otd, otd_d, tardy_count, "
                    "setups, gate_status, json_extract(payload_json, '$.plan_revision') "
                    "as plan_revision from plans order by rowid desc limit 5")],
            }
            active = connection.execute(
                "select p.payload_json from plans p join plan_runtime r on r.snapshot_id = p.id"
            ).fetchone()
            if active is not None:
                payload = json.loads(active[0])
                serialize = _import_first("backend.plans.serialize")
                facts["active_payload"] = {
                    "plan_revision": payload.get("plan_revision"),
                    "fingerprints": payload.get("fingerprints"),
                    "schedule_fingerprint": serialize.schedule_fingerprint(
                        payload.get("segments"), payload.get("lots")),
                }
            columns = {row[1] for row in connection.execute("pragma table_info(plan_mutations)")}
            if "status" in columns:
                facts["plan_mutations"] = {row[0]: row[1] for row in connection.execute(
                    "select status, count(*) from plan_mutations group by status")}
            return facts
        finally:
            connection.close()

    def equivalence(self) -> dict:
        """Coarse facts for flows that do not reproduce byte for byte."""
        http = [[step["label"], step["status"]] for step in self.steps if "status" in step]
        plans = []
        for step in self.steps:
            facts = step.get("state") or step.get("plan")
            if facts is None:
                if "error" in step:
                    plans.append({"label": step["label"], "error": step["error"]})
                continue
            score = facts.get("score") or {}
            gate = facts.get("gate_report") or {}
            plans.append({
                "label": step["label"],
                "plan_revision": facts.get("plan_revision"),
                "segments_nonempty": bool(facts.get("segments")),
                "lot_quantities": facts.get("lot_quantities"),
                "physical_gate_passed": gate.get("physical_gate_passed"),
                "hard_violations": score.get("hard_violations"),
                "orders_late": (gate.get("metrics") or {}).get("orders_late"),
                "otd": score.get("otd"),
                "otd_d": score.get("otd_d"),
            })
        return {"http": http, "plans": plans}


def _result_facts(result) -> dict:
    serialize = _import_first("backend.plans.serialize")
    improvement = _import_first("backend.scheduler.improvement", "backend.engine.improve")
    segments, lots = list(result.segments or []), list(result.lots or [])
    return {
        "schedule_fingerprint": serialize.schedule_fingerprint(segments, lots),
        "physical_signature": improvement.physical_signature(segments, lots),
        "segments": len(segments),
        "lots": len(lots),
        "lot_quantities": digest(sorted([lot.id, int(lot.qty)] for lot in lots)),
        "score": jsonable(result.score),
        "gate_report": jsonable(getattr(result, "gate_report", None)),
        "improvement_report": jsonable(getattr(result, "improvement_report", None)),
        "warnings": jsonable(getattr(result, "warnings", None)),
        "solver_status": jsonable(getattr(result, "solver_status", None)),
        "feasibility": jsonable(getattr(result, "feasibility", None)),
    }


def _load_fixture(runner: Runner, name: str):
    serialize = _import_first("backend.plans.serialize")
    path = runner.h.pristine / "fixtures" / f"{name}.json.gz"
    payload = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    restored = serialize.deserialize_snapshot(payload)
    return restored["engine_data"], restored["config"], restored["result"]


def _planning_call(runner: Runner, label: str, call) -> None:
    started = runner.h.real_monotonic()
    try:
        result = call()
    except Exception as exc:  # noqa: BLE001 - a refusal is part of the behaviour
        runner.steps.append({"label": label, "error": f"{type(exc).__name__}: {exc}"})
    else:
        runner.steps.append({"label": label, "plan": _result_facts(result)})
    runner.timings.append({"label": label, "s": round(runner.h.real_monotonic() - started, 2)})


# ─── Flows ─────────────────────────────────────────────────────────────


def flow_recalculate(runner: Runner) -> None:
    """F1: «Recalcular plano» as the screen sends it: 409, approval, commit."""
    with runner.app():
        runner.write("recalculate", "POST", "/api/data/recalculate", {
            "compact_active_plan": True, "approve_exceptions": False,
            "approval_reason": "", "approval_author": "",
        })
        runner.record_state("after")


def flow_optimize_quick(runner: Runner) -> None:
    """F2: ``optimize(mode="quick")`` on rev90, rev121 and rev124."""
    runner.h.wrap_improvement()
    optimize = _import_first("backend.cpo").optimize
    for fixture in FIXTURES:
        runner.h.set_anchor(FIXTURE_ANCHORS[fixture])
        data, config, _stored = _load_fixture(runner, fixture)
        _planning_call(runner, f"{fixture}:quick", lambda d=data, c=config: optimize(
            copy.deepcopy(d), mode="quick", config=copy.deepcopy(c)))


def flow_optimize_normal(runner: Runner, fixture: str) -> None:
    """F2: ``optimize(mode="normal")`` on one fixture (full ISOP rebuild)."""
    runner.h.wrap_improvement()
    optimize = _import_first("backend.cpo").optimize
    runner.h.set_anchor(FIXTURE_ANCHORS[fixture])
    data, config, _stored = _load_fixture(runner, fixture)
    _planning_call(runner, f"{fixture}:normal", lambda: optimize(
        copy.deepcopy(data), mode="normal", config=copy.deepcopy(config)))


def flow_optimize_preserving(runner: Runner, fixture: str) -> None:
    """F2: ``optimize_preserving_started_lots`` (the recalculation path)."""
    runner.h.wrap_improvement()
    frozen = _import_first("backend.plans.frozen")
    runner.h.set_anchor(FIXTURE_ANCHORS[fixture])
    data, config, stored = _load_fixture(runner, fixture)
    _planning_call(runner, f"{fixture}:preserving", lambda: frozen.optimize_preserving_started_lots(
        copy.deepcopy(data), copy.deepcopy(config), copy.deepcopy(stored), mode="normal"))


def flow_outage(runner: Runner, resource: str, start_at: str, end_at: str) -> None:
    """F3: a machine outage through the replan job, then its application."""
    with runner.app():
        revision = int(runner.state.plan_revision)
        status, payload = runner.http("replan:start", "POST", "/api/data/replan-jobs", body={
            "reason": "Indisponibilidades alteradas",
            "config_updates": {"unavailability_additions": [{
                "kind": "machine", "resource": resource, "start_at": start_at,
                "end_at": end_at, "category": "Avaria", "reason": "Golden master",
            }]},
            "expected_revision": revision,
            "request_id": runner.request_id("replan"),
        })
        job = payload.get("job") if isinstance(payload, dict) else None
        if status in (200, 202) and isinstance(job, dict):
            job = runner.wait_job("replan:job", f"/api/data/replan-jobs/{job['id']}",
                                  active={"queued", "running"})
            if job.get("status") == "ready":
                gate = (job.get("result") or {}).get("gate_report") or {}
                needed = bool(gate.get("requires_approval"))
                runner.http("replan:apply", "POST", f"/api/data/replan-jobs/{job['id']}/apply",
                            body={
                                "expected_revision": job.get("base_revision", revision),
                                "approve_exceptions": needed,
                                "approval_reason": APPROVAL_REASON if needed else "",
                                "approval_author": APPROVAL_AUTHOR if needed else "",
                                "request_id": runner.request_id("replan-apply"),
                            })
        runner.record_state("after")


def _move(runner: Runner, label: str, move: dict) -> None:
    state = runner.state
    machine = move.get("target_machine") or next(
        (segment.machine_id for segment in sorted(
            state.segments, key=lambda s: (s.day_idx, s.start_min))
         if segment.lot_id == move["lot_id"]),
        None,
    )
    request = {"lot_id": move["lot_id"], "target_day": int(move["target_day"]),
               "target_machine": machine, "target_start_min": int(move["target_start_min"]),
               "reason": "Golden master", "author": APPROVAL_AUTHOR}
    status, payload = runner.http(f"{label}:preview", "POST",
                                  "/api/data/plan/move-preview-jobs", body=request)
    job = payload.get("job") if isinstance(payload, dict) else None
    if status != 200 or not isinstance(job, dict):
        return
    job = runner.wait_job(f"{label}:preview-job", f"/api/data/plan/move-preview-jobs/{job['id']}",
                          active={"queued", "running"})
    result = job.get("result") or {}
    if job.get("status") != "ready" or not result:
        return
    gate = result.get("gate_report") or {}
    needed = bool(result.get("requires_confirmation") or gate.get("requires_approval"))
    runner.http(f"{label}:apply", "POST", "/api/data/plan/move-apply", body={
        **request, "preview_job_id": job["id"], "expected_revision": job.get("base_revision"),
        "approve_exceptions": needed, "approval_reason": APPROVAL_REASON if needed else "",
        "approval_author": APPROVAL_AUTHOR, "confirm_delivery_risk": needed,
        "request_id": runner.request_id(f"{label}-apply"),
    })


def flow_manual_move(runner: Runner) -> None:
    """F4: a Gantt move that is refused, then one that is applied."""
    params = runner.params["F4_manual_move"]
    with runner.app():
        for index, move in enumerate(params["refused"]):
            _move(runner, f"refused-{index}", move)
        runner.record_state("after-refused")
        _move(runner, "applied", params["applied"])
        runner.record_state("after-applied")


def flow_simulate_scenarios(runner: Runner) -> None:
    """F5: simulator (machine down), save the scenario, list, apply it."""
    params = runner.params["F5_simulate_scenarios"]
    mutations = [{"type": "machine_down", "params": {
        "machine_id": params["machine_id"], "start": params["start"], "end": params["end"],
    }}]
    with runner.app():
        status, simulated = runner.http("simulate", "POST", "/api/data/simulate",
                                        body={"mutations": mutations})
        candidate = simulated.get("candidate_id") if isinstance(simulated, dict) else None
        status, saved = runner.http("scenario:save", "POST", "/api/data/scenarios", body={
            "name": "Golden master", "note": "", "mutations": mutations,
            "candidate_id": candidate,
        })
        runner.http("scenario:list", "GET", "/api/data/scenarios")
        scenario = (saved.get("scenario") or {}) if isinstance(saved, dict) else {}
        if status == 200 and scenario.get("id"):
            # The screen asks the planner and sends the approval with the
            # request (no prepared candidate on this route).
            status, _applied = runner.write(
                "scenario:apply", "POST", f"/api/data/scenarios/{scenario['id']}/apply",
                {"approve_exceptions": False, "approval_reason": "", "approval_author": ""})
            if status == 409:
                runner.write("scenario:apply-approved", "POST",
                             f"/api/data/scenarios/{scenario['id']}/apply",
                             {"approve_exceptions": True, "approval_reason": APPROVAL_REASON,
                              "approval_author": APPROVAL_AUTHOR})
        runner.record_state("after")


def flow_ctp(runner: Runner) -> None:
    """F5: capable-to-promise check, then its application."""
    params = runner.params["F5_ctp"]
    request = {"sku": params["sku"], "qty": params["qty"], "deadline": params["deadline"]}
    with runner.app():
        status, checked = runner.http("ctp", "POST", "/api/data/ctp", body=request)
        if status == 200 and isinstance(checked, dict) and checked.get("candidate_id"):
            identity = {key: checked.get(key) for key in (
                "candidate_id", "dataset_id", "base_revision", "input_fingerprint",
                "candidate_fingerprint")}
            runner.write("ctp:apply", "POST", "/api/data/ctp-apply", {
                **identity, **request, "request_id": f"apply-{checked['candidate_id']}",
                "expected_revision": checked.get("base_revision"),
                "approve_exceptions": False, "approval_reason": "", "approval_author": "",
            })
        runner.record_state("after")


COPILOT_QUERIES = (
    ("ver_score", {}),
    ("ver_alertas", {}),
    ("ver_encomendas", {}),
    ("ver_config", {}),
    ("explicar_logica", {"conceito": "scoring"}),
    ("explicar_logica", {"conceito": "jit"}),
)


def _tool(runner: Runner, name: str, args: dict) -> None:
    engine = _import_first("backend.copilot.engine", "backend.copilot.chat")
    started = runner.h.real_monotonic()
    output, widget = engine.execute_tool(name, json.dumps(args))
    runner.timings.append({"label": f"tool:{name}", "s": round(
        runner.h.real_monotonic() - started, 2)})
    try:
        parsed = json.loads(output)
    except (TypeError, ValueError):
        parsed = {"_text": str(output)[:4000]}
    runner.steps.append({"label": f"tool:{name}", "args": args, "widget": widget,
                         "result": parsed})


def flow_copilot(runner: Runner, modo: str) -> None:
    """F6: the Copilot executors called directly (the LLM is bypassed)."""
    with runner.app():
        if modo == "quick":
            for name, args in COPILOT_QUERIES:
                _tool(runner, name, args)
            _tool(runner, "recalcular_plano", {
                "modo": modo, "expected_revision": int(runner.state.plan_revision)})
            runner.record_state("after-unapproved")
        _tool(runner, "recalcular_plano", {
            "modo": modo, "expected_revision": int(runner.state.plan_revision),
            "approve_exceptions": True, "approval_reason": APPROVAL_REASON,
            "approval_author": APPROVAL_AUTHOR,
        })
        runner.record_state("after")


def flow_holiday(runner: Runner) -> None:
    """F7: add holidays in turn (approval when the gate asks for it)."""
    params = runner.params["F7_holiday"]
    with runner.app():
        for date in params["dates"]:
            runner.write(f"holiday:{date}", "POST", "/api/data/holidays", {"data": date})
            runner.record_state(f"after:{date}")


def flow_sku_rule(runner: Runner) -> None:
    """F7: change one SKU's planning rule."""
    params = runner.params["F7_sku_rule"]
    with runner.app():
        runner.write("sku-rule", "PUT", f"/api/data/skus/{params['sku']}/planning",
                     dict(params["rule"]))
        runner.record_state("after")


def flow_config_oee(runner: Runner) -> None:
    """F7: ``PUT /config`` with a new ``oee_default``."""
    params = runner.params["F7_config_oee"]
    with runner.app():
        runner.write("config", "PUT", "/api/data/config",
                     {"oee_default": params["oee_default"]})
        runner.http("config:read", "GET", "/api/data/config")
        runner.record_state("after")


def flow_startup_reads(runner: Runner) -> None:
    """F8: start-up restore and every GET route the app declares."""
    params = runner.params.get("F8_startup_reads") or {}
    with runner.app() as client:
        # The OpenAPI paths: FastAPI includes routers lazily, so app.routes
        # does not list them.
        paths = client.app.openapi()["paths"]
        routes = sorted(
            path for path, operations in paths.items()
            if "get" in operations and "{" not in path and path not in EXCLUDED_GET_ROUTES
        )
        runner.steps.append({"label": "get-routes", "routes": routes})
        for path in routes:
            runner.http(f"GET {path}", "GET", path)
        status, today = runner.http("today", "GET", "/api/data/today", record=False)
        day = int(today.get("today_idx", 0)) if isinstance(today, dict) else 0
        runner.http("console:today", "GET", "/api/console", params={"day_idx": day})
        for sku in params.get("stock_skus", []):
            runner.http(f"stock:{sku}", "GET", f"/api/data/stock/{sku}")
        runner.record_state("after")


def flow_robustness(runner: Runner) -> None:
    """F10: one robustness run with a fixed seed and a small sample."""
    with runner.app():
        status, payload = runner.http("robustness:start", "POST", "/api/data/robustness-runs",
                                      body={"profile": "standard", "samples": 20, "seed": 42,
                                            "expected_revision": int(runner.state.plan_revision)})
        job = payload.get("job") if isinstance(payload, dict) else None
        if not isinstance(job, dict) and isinstance(payload, dict):
            job = payload if payload.get("id") else None
        if status in (200, 202) and isinstance(job, dict) and job.get("id"):
            runner.wait_job("robustness:job", f"/api/data/robustness-runs/{job['id']}",
                            active={"queued", "running", "cancelling"})
        runner.record_state("after")


# ─── Entry point ───────────────────────────────────────────────────────


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=1, ensure_ascii=False) + "\n")


def run(args) -> int:
    flow = FLOWS[args.flow]
    harness = Harness(args)
    params = {}
    params_path = harness.pristine / "flow_params.json"
    if params_path.exists():
        params = json.loads(params_path.read_text())
    harness.install()
    sys.path.insert(0, str(harness.code))
    import backend

    location = Path(backend.__file__).resolve()
    if harness.code not in location.parents:
        raise SystemExit(f"backend imported from {location}, not from {harness.code}")

    runner = Runner(harness, params)
    started = harness.real_monotonic()
    error = error_trace = None
    try:
        getattr(sys.modules[__name__], flow.function)(runner, **dict(flow.kwargs))
    except Exception as exc:  # noqa: BLE001 - the failure is recorded in the result
        error = f"{type(exc).__name__}: {exc}"
        error_trace = traceback.format_exc()
    wall = round(harness.real_monotonic() - started, 2)
    db = {}
    try:
        db = runner.db_facts()
    except Exception as exc:  # noqa: BLE001
        db = {"error": f"{type(exc).__name__}: {exc}"}
    raw = {
        "flow": flow.name,
        "group": flow.group,
        "steps": runner.steps,
        "improvement_calls": harness.improvement_calls,
        "db": db,
        "error": error,
        "equivalence": runner.equivalence(),
    }
    result = canonicalize(raw)
    out = Path(args.out)
    with gzip.open(out.with_suffix(".raw.json.gz"), "wt", encoding="utf-8") as handle:
        json.dump(jsonable(raw), handle, sort_keys=True, ensure_ascii=False)
    _write_json(out, {
        "flow": flow.name,
        "group": flow.group,
        "sha256": digest(result),
        "result": result,
        "meta": {
            "mode": harness.mode,
            "code": str(harness.code),
            "anchor": _ANCHOR[0].isoformat(),
            "slow_factor": SLOW_FACTOR if harness.mode == "deterministic" else 1.0,
            "cpsat_solves": harness.cpsat_solves,
            "legacy_alarms": dict(collections.Counter(harness.legacy_alarms)),
            "wall_s": wall,
            "timings": runner.timings,
            "error_traceback": error_trace,
            "server_errors": runner.server_errors,
            "python": sys.version.split()[0],
            "pid": os.getpid(),
        },
    })
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run one golden-master flow.")
    parser.add_argument("--code", required=True)
    parser.add_argument("--flow", required=True, choices=sorted(FLOWS))
    parser.add_argument("--run-dir", required=True, help="runtime copy with data/ and config/")
    parser.add_argument("--pristine", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--anchor", required=True, help="frozen clock, ISO 8601 with offset")
    parser.add_argument("--mode", choices=("deterministic", "calibrate"), default="deterministic")
    parser.add_argument("--calibration", default="")
    args = parser.parse_args(argv)
    if args.mode == "deterministic" and not args.calibration:
        parser.error("--calibration is required in deterministic mode")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
