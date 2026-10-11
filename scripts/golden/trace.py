#!/usr/bin/env python3
"""Runtime trace of the golden-master flows and the deletion list (plan Passo 1c).

Safety rule 5 of the plan: never delete a function the trace saw run. The
deletion list is therefore "statically unreachable from the application
(with the real-data cuts below) AND absent from the live set".

Commands (``--golden`` defaults to ``~/incompolinho-private/golden``)::

  trace.py run --code <golden>/code-5a03230 --mode real           # real budgets
  trace.py run --code <golden>/code-5a03230 --mode deterministic  # golden limits
  trace.py merge --code <golden>/code-5a03230      # -> trace/live_set.json
  trace.py static --code <golden>/code-5a03230     # -> trace/static_reach.json
  trace.py reconcile --code <golden>/code-5a03230  # -> trace/deletion_list.json
  trace.py all --code <golden>/code-5a03230        # the five steps in order

Everything is written under ``<golden>/trace`` (chmod 700, outside git): the
flow outputs hold client data.

Trace (PEP 669, ``sys.monitoring``, Python 3.12). ``trace.py child`` installs
the monitor and then runs ``flows.main`` unchanged, so the harness of
``flows.py`` (frozen clock, evaluation caps, write guard, deterministic CP-SAT)
applies as in a capture. Events: PY_START for every code object under
``backend/`` and LINE for the files in ``LINE_FILES``. Every callback returns
DISABLE, so each location costs one callback per process. The events are
interpreter-wide, so the job threads (replan, move preview, robustness) are
seen. The job managers run in threads of the same process
(``worker_pid = os.getpid()``). Two things are not observable: a generator
that is created but never started, and a dataclass ``__init__`` (generated
code with no file). A class counts as run when one of its methods ran; its
body running at import does not count.

Modes. ``real`` runs ``flows.py --mode calibrate``: real budgets and real
clock, no evaluation cap. That is the branch production takes on this
machine under the load of the moment. ``deterministic`` runs
``flows.py --mode deterministic`` with the golden calibration: the golden
master's branch. A traced deterministic flow must reproduce the baseline
sha256, which shows the monitor changed nothing.

Probes (trace-only flows, kept apart from F1-F10 in every output):

* ``P4_manual_move_fallback``: Gantt move previews onto an occupied slot. F4
  only exercises ``_fixed_positions_move``; this probe makes ``_move_lot``
  fall back to ``_replan_around_fixed_lot`` -> ``_allocate_existing_lots``.
  Real data then evaluates both manual-move forks (C2, C3);
* ``P6_copilot_smart``: Copilot ``recalcular_plano`` with ``modo=smart``;
* ``P6_copilot_learning_tools``: ``ver_historico`` and
  ``visualizar_learning``.

The two P6 probes answer "is ``backend/learning`` reached only through
``smart``?". In deterministic mode each probe gets the evaluation cap of its
golden counterpart (``calibration-trace.json``).

Static analysis (``static``). The call graph comes from the AST of
``backend/``, starting at the module ``backend.api.copilot``, which is what
uvicorn loads in ``deploy/`` and ``docker/``. It over-approximates
reachability, so "unreachable" errs on the safe side:

* names resolve through module definitions, enclosing functions and imports,
  with re-exports followed;
* an attribute on a module resolves in that module. On any other object it
  reaches every method of that name in every class that is reached;
* an identifier string reaches every definition with that name
  (``getattr`` and dispatch tables). ``import_module("backend...")`` reaches
  that module;
* a reached class reaches its dunder methods and its backend base classes.
  A class with a base outside ``backend/`` (pydantic, logging, Exception,
  Enum) reaches all its methods;
* a decorator that registers (``@router.get``, ``@_register``,
  ``@plan_writer``, ...) reaches the function when its module is imported.
  ``NON_REGISTERING_DECORATORS`` do not.

Real-data cuts. References inside these statements do not count; each is
anchored on the AST, and the analysis stops if an anchor is not found.

* C1: ``schedule_all`` after ``if has_quantity_releases(lots): ... return``.
  Real ISOPs always release material per delivery.
* C2: ``manual_move._allocate_existing_lots``, the ``else`` of
  ``if has_quantity_releases(movable)`` and the body of ``if runs:``.
* C3: ``manual_move._move_lot``, the body of
  ``if result is None and not _reallocation_ignores_target(...)``.
* C4: ``optimizer._optimize`` after the size gate
  (``advisory_search_max_ops``). Real ISOPs have 50 or more operations,
  and production never asks for ``deep`` or ``max``.
"""

from __future__ import annotations

import argparse
import ast
import atexit
import collections
import dataclasses
import datetime
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DEFAULT_GOLDEN = Path(os.environ.get(
    "PP1_GOLDEN_DIR", str(Path.home() / "incompolinho-private" / "golden")))
LINE_FILES = (
    "backend/scheduler/scheduler.py",
    "backend/scheduler/global_jit.py",
    "backend/cpo/optimizer.py",
    "backend/plans/manual_move.py",
    "backend/scheduler/quantity_dispatch.py",
)
MODES = {"real": "calibrate", "deterministic": "deterministic"}
DEFAULT_CORES = {
    "real": "0,2,4,6,8,10",                    # P-cores, like the calibration
    "deterministic": "12,13,14,15,16,17,18,19",  # E-cores (load-independent)
}
FLOW_TIMEOUT_S = 2 * 3600
ROOT_MODULE = "backend.api.copilot"

# ─── Probe flows (trace only) ──────────────────────────────────────────

# The monitor of this process, for probes that stop once a function ran.
_ACTIVE_MONITOR: list = []
FALLBACK_PROBE_ATTEMPTS = 6


def probe_manual_move_fallback(runner) -> None:
    """Gantt move previews that the fixed-positions attempt cannot place.

    F4 only exercises ``_fixed_positions_move``. Moving a lot onto the start
    of the next lot on the same machine (a later, occupied slot: material is
    already released) makes that attempt fail, so ``_move_lot`` evaluates the
    fork ``_reallocation_ignores_target`` and falls back to
    ``_replan_around_fixed_lot`` -> ``_allocate_existing_lots``. Previews only,
    nothing is applied. It stops at the first preview that reached the
    fallback. The candidates are chosen from the plan at run time, so no lot id
    is written here.
    """
    with runner.app():
        state = runner.state
        _status, today = runner.http("today", "GET", "/api/data/today", record=False)
        today_idx = int(today.get("today_idx", 0)) if isinstance(today, dict) else 0
        first: dict[str, tuple[int, int, str]] = {}
        for segment in sorted(state.segments, key=lambda s: (s.day_idx, s.start_min)):
            if segment.prod_min > 0 and segment.lot_id not in first:
                first[segment.lot_id] = (segment.day_idx, segment.start_min, segment.machine_id)
        by_machine: dict[str, list] = collections.defaultdict(list)
        for lot_id, (day, start, machine) in first.items():
            by_machine[machine].append((day, start, lot_id))
        candidates = []
        for machine, items in sorted(by_machine.items()):
            items.sort()
            for (day, _start, lot_id), (next_day, next_start, _next) in zip(items, items[1:]):
                if day >= today_idx + 2 and next_day > day:
                    candidates.append((day, machine, lot_id, next_day, next_start))
                    break  # the earliest movable lot of each machine
        candidates.sort()
        runner.steps.append({"label": "fallback:candidates", "count": len(candidates)})

        def reached() -> bool:
            monitor = _ACTIVE_MONITOR[0] if _ACTIVE_MONITOR else None
            return monitor is not None and any(
                qualname == "_replan_around_fixed_lot" and file.endswith("manual_move.py")
                for file, qualname, _line in list(monitor.starts))

        for attempt, (_day, machine, lot_id, next_day, next_start) in enumerate(
                candidates[:FALLBACK_PROBE_ATTEMPTS]):
            request = {"lot_id": lot_id, "target_day": int(next_day),
                       "target_machine": machine, "target_start_min": int(next_start),
                       "reason": "Rastreio (sonda)", "author": "planeador"}
            status, payload = runner.http(f"fallback-{attempt}:preview", "POST",
                                          "/api/data/plan/move-preview-jobs", body=request)
            job = payload.get("job") if isinstance(payload, dict) else None
            if status == 200 and isinstance(job, dict):
                runner.wait_job(f"fallback-{attempt}:preview-job",
                                f"/api/data/plan/move-preview-jobs/{job['id']}",
                                active={"queued", "running"})
            if reached():
                runner.steps.append({"label": "fallback:reached", "attempt": attempt})
                break
        runner.record_state("after")


def probe_copilot_smart(runner) -> None:
    """Copilot «recalcular» in ``smart`` mode (learning/Optuna), approved."""
    import flows

    with runner.app():
        flows._tool(runner, "recalcular_plano", {
            "modo": "smart", "expected_revision": int(runner.state.plan_revision),
            "approve_exceptions": True, "approval_reason": flows.APPROVAL_REASON,
            "approval_author": flows.APPROVAL_AUTHOR,
        })
        runner.record_state("after")


def probe_copilot_learning_tools(runner) -> None:
    """The two read-only Copilot tools that open the learning store."""
    import flows

    with runner.app():
        flows._tool(runner, "ver_historico", {})
        flows._tool(runner, "visualizar_learning", {})


# name -> (function, implementation, weight, flow whose evaluation cap it gets)
PROBES = {
    "P4_manual_move_fallback": ("probe_manual_move_fallback", probe_manual_move_fallback, 4,
                                "F4_manual_move"),
    "P6_copilot_smart": ("probe_copilot_smart", probe_copilot_smart, 5, "F6_copilot_normal"),
    "P6_copilot_learning_tools": ("probe_copilot_learning_tools",
                                  probe_copilot_learning_tools, 1, "F6_copilot_normal"),
}


def register_probes(flows_module) -> None:
    for name, (function, implementation, weight, _cap) in PROBES.items():
        setattr(flows_module, function, implementation)
        flows_module.FLOWS[name] = flows_module.Flow(name, name[:2], function, weight=weight)


# ─── Monitor (runs inside the flow process) ────────────────────────────


class Monitor:
    """PY_START for ``backend/``; LINE for ``LINE_FILES``; DISABLE after a hit."""

    def __init__(self, code: Path):
        self.roots = sorted({str(code) + os.sep, str(code.resolve()) + os.sep}, key=len)
        self.prefixes = tuple(root + "backend" + os.sep for root in self.roots)
        self.line_files = {root + name for root in self.roots for name in LINE_FILES}
        self.starts: set[tuple[str, str, int]] = set()
        self.lines: dict[str, set[int]] = collections.defaultdict(set)
        self.tool = None

    def _relative(self, filename: str) -> str:
        for root in self.roots[::-1]:
            if filename.startswith(root):
                return filename[len(root):]
        return filename

    def _on_start(self, code, _offset):
        filename = code.co_filename
        if filename.startswith(self.prefixes):
            self.starts.add((self._relative(filename), code.co_qualname, code.co_firstlineno))
        return sys.monitoring.DISABLE

    def _on_line(self, code, line):
        filename = code.co_filename
        if filename in self.line_files:
            self.lines[self._relative(filename)].add(line)
        return sys.monitoring.DISABLE

    def install(self) -> None:
        monitoring = sys.monitoring
        for tool in (monitoring.COVERAGE_ID, 3, 4):
            try:
                monitoring.use_tool_id(tool, "pp1-golden-trace")
            except ValueError:
                continue
            self.tool = tool
            break
        if self.tool is None:
            raise SystemExit("sys.monitoring: no free tool id")
        events = monitoring.events
        monitoring.register_callback(self.tool, events.PY_START, self._on_start)
        monitoring.register_callback(self.tool, events.LINE, self._on_line)
        monitoring.set_events(self.tool, events.PY_START | events.LINE)

    def dump(self, path: Path, meta: dict) -> None:
        payload = {
            "meta": {**meta, "tool_id": self.tool, "python": sys.version.split()[0]},
            "functions": sorted([list(item) for item in self.starts]),
            "lines": {name: sorted(lines) for name, lines in sorted(self.lines.items())},
        }
        _write_json(path, payload, indent=None)


def child(argv: list[str]) -> int:
    if "--" not in argv:
        raise SystemExit("child: missing '--' before the flows.py arguments")
    split = argv.index("--")
    parser = argparse.ArgumentParser(prog="trace.py child")
    parser.add_argument("--trace-out", required=True)
    parser.add_argument("--code", required=True)
    own = parser.parse_args(argv[:split])
    monitor = Monitor(Path(own.code))
    monitor.install()
    _ACTIVE_MONITOR.append(monitor)
    import flows as golden_flows

    register_probes(golden_flows)
    out = Path(own.trace_out)
    meta = {"argv": argv[split + 1:], "started": _utc_now()}
    status = {"exit": None, "error": None}
    atexit.register(lambda: monitor.dump(out, {**meta, **status, "at": "atexit"}))
    try:
        status["exit"] = golden_flows.main(argv[split + 1:])
    except BaseException as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        monitor.dump(out, {**meta, **status, "at": "end"})
    return status["exit"]


# ─── Small helpers ─────────────────────────────────────────────────────


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, value, indent: int | None = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=indent, sort_keys=True, ensure_ascii=False)
                         + "\n")
    os.replace(temporary, path)
    path.chmod(0o600)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _commit_of(code: Path) -> str | None:
    marker = code / ".golden-commit"
    if marker.exists():
        return marker.read_text().strip()
    try:
        return subprocess.run(["git", "-C", str(code), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _ranges(lines) -> list[list[int]]:
    """[[first, last], ...] of consecutive integers."""
    out: list[list[int]] = []
    for line in sorted(set(lines)):
        if out and line == out[-1][1] + 1:
            out[-1][1] = line
        else:
            out.append([line, line])
    return out


def _runs_over(executable: list[int], chosen: set[int]) -> list[list[int]]:
    """Ranges of ``chosen`` lines, merged across lines with no code.

    ``executable`` is the sorted list of lines that carry bytecode. Two chosen
    lines join one range when no executable line between them is left out.
    """
    out: list[list[int]] = []
    previous_chosen = False
    for line in executable:
        if line in chosen:
            if previous_chosen:
                out[-1][1] = line
            else:
                out.append([line, line])
            previous_chosen = True
        else:
            previous_chosen = False
    return out


def executable_lines(path: Path) -> list[int]:
    code = compile(path.read_text(), str(path), "exec", dont_inherit=True)
    lines: set[int] = set()
    stack = [code]
    while stack:
        current = stack.pop()
        lines.update(line for _start, _end, line in current.co_lines() if line is not None)
        stack.extend(const for const in current.co_consts if hasattr(const, "co_lines"))
    lines.discard(0)
    return sorted(lines)


# ─── run: trace the flows of one code tree ─────────────────────────────


def _trace_calibration(golden: Path, trace_dir: Path) -> Path:
    """The golden calibration plus a cap for each probe (its source flow's)."""
    calibration = json.loads((golden / "calibration.json").read_text())
    for name, (_function, _implementation, _weight, source) in PROBES.items():
        calls = ((calibration.get("flows") or {}).get(source) or {}).get("calls") or []
        budget = [call for call in calls if call.get("stop_reason") == "budget"]
        if not budget:
            raise SystemExit(f"calibration: {source} has no budget-stopped call")
        calibration["flows"][name] = {"calls": [dict(budget[0], index=0)],
                                      "note": f"trace probe: cap of {source}"}
    target = trace_dir / "calibration-trace.json"
    _write_json(target, calibration)
    return target


def _trace_flow(flow, *, code, golden, out, mode, calibration, anchor, core, python):
    import capture

    run_dir = golden / "runs" / f"trace-{mode}" / flow.name
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)
    for parent in (golden / "runs", run_dir.parent):
        parent.chmod(0o700)
    pristine = golden / "pristine"
    shutil.copytree(pristine / "data", run_dir / "data")
    shutil.copytree(pristine / "config", run_dir / "config")
    capture._private_tree(run_dir)
    target = out / f"{flow.name}.json"
    trace_file = out / f"{flow.name}.trace.json"
    log = out / f"{flow.name}.log"
    command = [
        "taskset", "-c", str(core), python, "-B", str(HERE / "trace.py"), "child",
        "--trace-out", str(trace_file), "--code", str(code), "--",
        "--code", str(code), "--flow", flow.name, "--run-dir", str(run_dir),
        "--pristine", str(pristine), "--out", str(target), "--anchor", anchor,
        "--mode", MODES[mode],
    ]
    if calibration:
        command += ["--calibration", str(calibration)]
    started = time.monotonic()
    with log.open("w") as handle:
        try:
            exit_code = subprocess.run(command, cwd=run_dir, env=capture._environment(run_dir),
                                       stdout=handle, stderr=subprocess.STDOUT,
                                       timeout=FLOW_TIMEOUT_S, check=False).returncode
        except subprocess.TimeoutExpired:
            exit_code = "timeout"
    entry = {"core": core, "wall_s": round(time.monotonic() - started, 1),
             "exit_code": exit_code}
    if exit_code == 0 and target.exists() and trace_file.exists():
        written = json.loads(target.read_text())
        traced = json.loads(trace_file.read_text())
        entry.update(
            status="error" if written["result"].get("error") else "ok",
            sha256=written["sha256"],
            error=written["result"].get("error"),
            cpsat_solves=written["meta"].get("cpsat_solves"),
            legacy_alarms=written["meta"].get("legacy_alarms"),
            improvement_calls=[
                {key: call.get(key) for key in ("cap", "cap_source", "candidates_evaluated",
                                                "stop_reason")}
                for call in written["result"].get("improvement_calls") or []
            ],
            functions=len(traced["functions"]),
            lines={name: len(lines) for name, lines in traced["lines"].items()},
        )
    else:
        entry["status"] = "harness_failure"
        entry["log_tail"] = log.read_text()[-3000:] if log.exists() else ""
    shutil.rmtree(run_dir, ignore_errors=True)
    return entry


def run_traces(args) -> int:
    import capture
    import flows as golden_flows

    register_probes(golden_flows)
    golden = Path(args.golden).resolve()
    code = Path(args.code).resolve()
    if not (code / "backend" / "__init__.py").exists():
        raise SystemExit(f"{code} is not a code tree (no backend/)")
    trace_dir = _private_dir(golden / "trace")
    out = trace_dir / (f"runs-{args.mode}-{args.label}" if args.label else f"runs-{args.mode}")
    if out.exists() and any(out.iterdir()):
        if not args.force:
            raise SystemExit(f"{out} already exists (--force to replace it)")
        shutil.rmtree(out)
    _private_dir(out)
    manifest = capture.verify_pristine(golden / "pristine")
    calibration = _trace_calibration(golden, trace_dir) if args.mode == "deterministic" else None
    selected = [flow for flow in golden_flows.FLOWS.values() if not flow.skip_reason]
    if args.no_probes:
        selected = [flow for flow in selected if flow.name not in PROBES]
    if args.flows:
        wanted = set(args.flows.split(","))
        unknown = wanted - set(golden_flows.FLOWS)
        if unknown:
            raise SystemExit(f"unknown flows: {sorted(unknown)}")
        selected = [flow for flow in selected if flow.name in wanted]
    skipped = {flow.name: flow.skip_reason for flow in golden_flows.FLOWS.values()
               if flow.skip_reason}
    baseline = {}
    baseline_summary = golden / "baseline" / "SUMMARY.json"
    if baseline_summary.exists():
        baseline = json.loads(baseline_summary.read_text()).get("flows") or {}
    summary = {
        "code": str(code), "commit": _commit_of(code), "mode": args.mode,
        "flows_mode": MODES[args.mode], "started_at": _utc_now(),
        "calibration": str(calibration) if calibration else None,
        "calibration_sha256": _sha256_file(calibration) if calibration else None,
        "harness_sha256": {name: _sha256_file(HERE / name)
                           for name in ("flows.py", "capture.py", "trace.py")},
        "baseline": str(baseline_summary.resolve()) if baseline_summary.exists() else None,
        "skipped": skipped, "probes": sorted(PROBES), "flows": {},
    }
    work: queue.Queue = queue.Queue()
    for flow in sorted(selected, key=lambda item: (-item.weight, item.name)):
        work.put(flow)
    cores = [int(core) for core in (args.cores or DEFAULT_CORES[args.mode]).split(",")
             if core.strip()]
    lock = threading.Lock()
    started = time.monotonic()

    def worker(core: int) -> None:
        while True:
            try:
                flow = work.get_nowait()
            except queue.Empty:
                return
            entry = _trace_flow(flow, code=code, golden=golden, out=out, mode=args.mode,
                                calibration=calibration, anchor=manifest["clock_anchor"],
                                core=core, python=args.python)
            reference = (baseline.get(flow.name) or {}).get("sha256")
            if args.mode == "deterministic" and reference and "sha256" in entry:
                entry["baseline_sha256_match"] = entry["sha256"] == reference
            with lock:
                summary["flows"][flow.name] = entry
                print(f"  {flow.name:<28} {entry['status']:<16} {entry['wall_s']:>7.1f} s"
                      f"  core {core}"
                      + (f"  baseline {'=' if entry.get('baseline_sha256_match') else '≠'}"
                         if "baseline_sha256_match" in entry else ""), flush=True)

    threads = [threading.Thread(target=worker, args=(core,)) for core in cores]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    summary["wall_s"] = round(time.monotonic() - started, 1)
    summary["finished_at"] = _utc_now()
    summary["flows"] = dict(sorted(summary["flows"].items()))
    _write_json(out / "TRACE_SUMMARY.json", summary)
    for item in out.iterdir():
        item.chmod(0o600)
    with_runs = golden / "runs" / f"trace-{args.mode}"
    try:
        with_runs.rmdir()
    except OSError:
        pass
    failures = [name for name, entry in summary["flows"].items()
                if entry["status"] == "harness_failure"]
    print(f"rastreio {args.mode}: {len(summary['flows'])} fluxos em {summary['wall_s']} s "
          f"-> {out}")
    if failures:
        print(f"FALHA DO HARNESS: {', '.join(failures)}")
        return 1
    return 0


# ─── merge: live_set.json ──────────────────────────────────────────────


def merge(args) -> int:
    golden = Path(args.golden).resolve()
    code = Path(args.code).resolve()
    trace_dir = golden / "trace"
    functions: dict = collections.defaultdict(dict)
    lines_all: dict[str, dict[str, set[int]]] = collections.defaultdict(
        lambda: collections.defaultdict(set))
    lines_by_flow: dict = collections.defaultdict(dict)
    modes = {}
    for mode in MODES:
        out = trace_dir / f"runs-{mode}"
        summary_path = out / "TRACE_SUMMARY.json"
        if not summary_path.exists():
            raise SystemExit(f"{summary_path} missing: run 'trace.py run --mode {mode}' first")
        summary = json.loads(summary_path.read_text())
        if Path(summary["code"]).resolve() != code:
            raise SystemExit(f"{out} traced {summary['code']}, not {code}")
        modes[mode] = {key: summary.get(key) for key in (
            "commit", "started_at", "finished_at", "wall_s", "calibration_sha256",
            "harness_sha256", "skipped", "probes")}
        modes[mode]["flows"] = {
            name: {key: entry.get(key) for key in (
                "status", "wall_s", "core", "sha256", "baseline_sha256_match", "error",
                "cpsat_solves", "improvement_calls", "functions")}
            for name, entry in summary["flows"].items()}
        for name, entry in summary["flows"].items():
            if entry["status"] == "harness_failure":
                continue
            traced = json.loads((out / f"{name}.trace.json").read_text())
            group = "probes" if name in PROBES else "golden"
            for file, qualname, first_line in traced["functions"]:
                record = functions[file].setdefault(
                    qualname, {"first_lines": [], "golden": {}, "probes": {}})
                if first_line not in record["first_lines"]:
                    record["first_lines"].append(first_line)
                record[group].setdefault(mode, []).append(name)
            for file, lines in traced["lines"].items():
                lines_all[file][f"{group}:{mode}"].update(lines)
                lines_by_flow[file][f"{name}@{mode}"] = _ranges(lines)
    for records in functions.values():
        for record in records.values():
            record["first_lines"].sort()
            for group in ("golden", "probes"):
                record[group] = {mode: sorted(set(names))
                                 for mode, names in sorted(record[group].items())}
    lines = {}
    for file in LINE_FILES:
        executable = executable_lines(code / file)
        views = lines_all.get(file, {})
        executed_golden = set().union(*(views.get(f"golden:{mode}", set()) for mode in MODES))
        executed_any = set().union(executed_golden, *(views.get(f"probes:{mode}", set())
                                                      for mode in MODES))
        lines[file] = {
            "executable_lines": len(executable),
            "executed_lines": {"golden": len(executed_golden), "all": len(executed_any)},
            "executed": {
                "all": _runs_over(executable, executed_any),
                "golden": _runs_over(executable, executed_golden),
                **{f"golden:{mode}": _runs_over(executable, views.get(f"golden:{mode}", set()))
                   for mode in MODES},
                **{f"probes:{mode}": _runs_over(executable, views.get(f"probes:{mode}", set()))
                   for mode in MODES},
            },
            "never_executed": _runs_over(executable, set(executable) - executed_any),
        }
    live = {
        "generated_at": _utc_now(),
        "code": str(code),
        "commit": _commit_of(code),
        "line_files": list(LINE_FILES),
        "golden_flows_note": (
            "golden = fluxos F1-F10 do golden master (F9 à espera de um ISOP real); "
            "probes = fluxos só deste rastreio (P6_*), fora do golden master"),
        "modes": modes,
        "functions": {file: dict(sorted(records.items()))
                      for file, records in sorted(functions.items())},
        "lines": lines,
        "lines_by_flow": {file: dict(sorted(flows.items()))
                          for file, flows in sorted(lines_by_flow.items())},
    }
    _write_json(trace_dir / "live_set.json", live)
    count = sum(len(records) for records in functions.values())
    print(f"live_set: {count} funções executadas em {len(functions)} ficheiros "
          f"-> {trace_dir / 'live_set.json'}")
    return 0


# ─── static: reachability from the application ─────────────────────────

NON_REGISTERING_DECORATORS = frozenset({
    "dataclass", "property", "staticmethod", "classmethod", "contextmanager",
    "asynccontextmanager", "wraps", "measured", "abstractmethod", "lru_cache", "cache",
    "cached_property", "setter", "getter", "deleter", "total_ordering", "overload", "final",
    "override",
})
FUNCTION_KINDS = ("function", "method", "nested")
STATIC_METHOD_NOTE = (
    "Grafo de chamadas pelo AST de backend/ a partir de backend.api.copilot (o que o uvicorn "
    "carrega). Sobre-aproxima: nomes por módulo, funções envolventes e importações "
    "(re-exportações seguidas); atributo de módulo resolvido nesse módulo, atributo de outro "
    "objeto alcança todos os métodos com esse nome nas classes alcançadas; string "
    "identificador alcança todas as definições com esse nome; classe alcançada alcança os "
    "dunders e as bases; base fora de backend/ alcança todos os métodos; decorador que regista "
    "alcança a função ao importar o módulo. Referências dentro dos cortes C1-C4 não contam.")


@dataclasses.dataclass
class Node:
    key: str
    module: str
    file: str
    qualname: str
    kind: str  # module | function | method | class | nested
    name: str = ""
    line: int = 0
    first_line: int = 0
    end_line: int = 0
    parent: str | None = None
    registering: bool = False
    external_base: bool = False
    base_exprs: list = dataclasses.field(default_factory=list)
    base_keys: list = dataclasses.field(default_factory=list)
    refs: list = dataclasses.field(default_factory=list)      # (kind, value, cut)
    children: list = dataclasses.field(default_factory=list)  # (key, cut)


@dataclasses.dataclass
class Cut:
    id: str
    file: str
    function: str
    description: str
    spans: list  # [[first_line, last_line], ...] of the cut statements


def _call_name(node) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return ""


def _chain(node) -> tuple[str, ...] | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return tuple(reversed(parts))
    return None


def _calls_named(node, name: str) -> bool:
    return any(isinstance(sub, ast.Call) and _call_name(sub) == name for sub in ast.walk(node))


def _top_function(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise LookupError(f"function {name} not found")


def _span(statements) -> list[int]:
    return [min(getattr(s, "lineno", 0) for s in statements),
            max(getattr(s, "end_lineno", 0) for s in statements)]


def find_cuts(trees: dict[str, ast.Module]) -> tuple[list[Cut], dict[int, str]]:
    """Real-data cuts, anchored on the AST (see the module docstring)."""
    cuts: list[Cut] = []
    cut_of: dict[int, str] = {}

    def mark(cut_id, statements):
        for statement in statements:
            cut_of[id(statement)] = cut_id

    # C1: schedule_all after the per-delivery branch.
    tree = trees["backend/scheduler/scheduler.py"]
    function = _top_function(tree, "schedule_all")
    index = next(i for i, statement in enumerate(function.body)
                 if isinstance(statement, ast.If)
                 and _calls_named(statement.test, "has_quantity_releases"))
    if not isinstance(function.body[index].body[-1], ast.Return):
        raise SystemExit("C1: the per-delivery branch of schedule_all no longer returns")
    tail = function.body[index + 1:]
    mark("C1", tail)
    cuts.append(Cut("C1", "backend/scheduler/scheduler.py", "schedule_all",
                    "cauda do schedule_all depois de 'if has_quantity_releases(lots): return'",
                    [_span(tail)]))

    # C2: _allocate_existing_lots, legacy allocation.
    tree = trees["backend/plans/manual_move.py"]
    function = _top_function(tree, "_allocate_existing_lots")
    branch = next(node for node in ast.walk(function) if isinstance(node, ast.If)
                  and _calls_named(node.test, "has_quantity_releases"))
    runs = next(node for node in ast.walk(function) if isinstance(node, ast.If)
                and isinstance(node.test, ast.Name) and node.test.id == "runs")
    if not branch.orelse or not _calls_named(ast.Module(body=branch.orelse, type_ignores=[]),
                                             "create_tool_runs"):
        raise SystemExit("C2: the else of has_quantity_releases(movable) changed")
    if not _calls_named(ast.Module(body=runs.body, type_ignores=[]), "solve_global_jit"):
        raise SystemExit("C2: 'if runs:' no longer calls solve_global_jit")
    mark("C2", branch.orelse)
    mark("C2", runs.body)
    cuts.append(Cut("C2", "backend/plans/manual_move.py", "_allocate_existing_lots",
                    "garfo do movimento manual: create_tool_runs + solve_global_jit",
                    [_span(branch.orelse), _span(runs.body)]))

    # C3: _move_lot, the reallocation that the per-delivery builder ignores.
    function = _top_function(tree, "_move_lot")
    branch = next(node for node in ast.walk(function) if isinstance(node, ast.If)
                  and _calls_named(node.test, "_reallocation_ignores_target"))
    mark("C3", branch.body)
    cuts.append(Cut("C3", "backend/plans/manual_move.py", "_move_lot",
                    "garfo do movimento manual: realocação antiga (_allocate_existing_lots)",
                    [_span(branch.body)]))

    # C4: _optimize after the size gate.
    tree = trees["backend/cpo/optimizer.py"]
    function = _top_function(tree, "_optimize")
    index = next(i for i, statement in enumerate(function.body)
                 if isinstance(statement, ast.If)
                 and any(isinstance(sub, ast.Name) and sub.id == "max_ops"
                         for sub in ast.walk(statement.test))
                 and isinstance(statement.body[-1], ast.Return))
    tail = function.body[index + 1:]
    if not any(_calls_named(statement, "_improve_baseline") for statement in tail):
        raise SystemExit("C4: _improve_baseline is no longer after the size gate")
    mark("C4", tail)
    cuts.append(Cut("C4", "backend/cpo/optimizer.py", "_optimize",
                    "pesquisa de candidatos depois do corte por tamanho (>= 50 operações; "
                    "deep/max nunca pedidos)", [_span(tail)]))
    return cuts, cut_of


class StaticGraph:
    def __init__(self, code: Path):
        self.code = code
        self.nodes: dict[str, Node] = {}
        self.modules: dict[str, str] = {}  # module -> file
        self.packages: set[str] = set()
        self.trees: dict[str, ast.Module] = {}
        self.top: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
        self.top_by_name: dict[str, list[str]] = collections.defaultdict(list)
        self.nested: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
        self.methods_by_name: dict[str, list[str]] = collections.defaultdict(list)
        self.methods_of: dict[str, list[str]] = collections.defaultdict(list)
        self.bindings: dict[str, dict[str, list[tuple]]] = collections.defaultdict(
            lambda: collections.defaultdict(list))
        self.by_qualname: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
        self._resolved: dict = {}
        for path in sorted((code / "backend").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            file = str(path.relative_to(code))
            module = file[:-3].replace("/", ".")
            if module.endswith(".__init__"):
                module = module[: -len(".__init__")]
                self.packages.add(module)
            self.modules[module] = file
            self.trees[file] = ast.parse(path.read_text(), filename=file)
        self.cuts, self.cut_of = find_cuts(self.trees)
        for module, file in self.modules.items():
            self._collect_module(module, file)
        for node in self.nodes.values():
            if node.kind == "class":
                self._resolve_bases(node)

    # collection -----------------------------------------------------------
    def module_key(self, module: str) -> str:
        return f"{self.modules[module]}::<module>"

    def _add(self, node: Node) -> Node:
        key = node.key
        if key in self.nodes:
            key = node.key = f"{node.key}@{node.line}"
        self.nodes[key] = node
        self.by_qualname[(node.file, node.qualname)].append(key)
        return node

    def _relative(self, module: str, level: int, target: str | None) -> str:
        if not level:
            return target or ""
        base = module.split(".")
        if module not in self.packages:
            base = base[:-1]
        if level > 1:
            base = base[: len(base) - (level - 1)]
        return ".".join(base + ([target] if target else []))

    def _collect_module(self, module: str, file: str) -> None:
        tree = self.trees[file]
        root = self._add(Node(key=f"{file}::<module>", module=module, file=file,
                              qualname="<module>", kind="module", end_line=len(
                                  (self.code / file).read_text().splitlines())))
        for sub in ast.walk(tree):
            if isinstance(sub, ast.Import):
                for alias in sub.names:
                    if alias.asname:
                        self.bindings[module][alias.asname].append(("module", alias.name))
                    else:
                        head = alias.name.split(".")[0]
                        self.bindings[module][head].append(("module", head))
            elif isinstance(sub, ast.ImportFrom):
                base = self._relative(module, sub.level, sub.module)
                for alias in sub.names:
                    if alias.name == "*":
                        continue
                    self.bindings[module][alias.asname or alias.name].append(
                        ("from", base, alias.name))
        self._visit_body(tree.body, root, None, "", None)

    def _visit_body(self, statements, owner: Node, in_class: Node | None, prefix: str,
                    cut) -> None:
        for index, statement in enumerate(statements):
            if (index == 0 and isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)):
                continue  # docstring
            self._visit(statement, owner, in_class, prefix, self.cut_of.get(id(statement), cut))

    def _visit(self, node, owner: Node, in_class: Node | None, prefix: str, cut) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Decorators, defaults and annotations are read where the function
            # is defined (FastAPI and pydantic read annotations at run time).
            arguments = node.args
            annotations = [argument.annotation for argument in (
                arguments.posonlyargs + arguments.args + arguments.kwonlyargs
                + [item for item in (arguments.vararg, arguments.kwarg) if item is not None])]
            for expression in node.decorator_list + arguments.defaults + [
                    item for item in arguments.kw_defaults + annotations + [node.returns]
                    if item is not None]:
                self._expression(expression, owner, cut)
            if in_class is not None:
                kind, parent = "method", in_class.key
            elif owner.kind == "module":
                kind, parent = "function", None
            else:
                kind, parent = "nested", owner.key
            first = min([item.lineno for item in node.decorator_list] + [node.lineno])
            new = self._add(Node(
                key=f"{owner.file}::{prefix}{node.name}", module=owner.module, file=owner.file,
                qualname=f"{prefix}{node.name}", kind=kind, name=node.name, line=node.lineno,
                first_line=first, end_line=node.end_lineno, parent=parent,
                registering=any(_call_name(item) not in NON_REGISTERING_DECORATORS
                                for item in node.decorator_list)))
            if kind == "nested":
                owner.children.append((new.key, cut))
                self.nested[(owner.key, node.name)].append(new.key)
            elif kind == "function":
                self.top[(owner.module, node.name)].append(new.key)
                self.top_by_name[node.name].append(new.key)
                if new.registering:
                    owner.children.append((new.key, cut))
            else:
                self.methods_by_name[node.name].append(new.key)
                self.methods_of[in_class.key].append(new.key)
            self._visit_body(node.body, new, None, f"{new.qualname}.<locals>.", cut)
            return
        if isinstance(node, ast.ClassDef):
            for expression in node.decorator_list + node.bases + [
                    keyword.value for keyword in node.keywords]:
                self._expression(expression, owner, cut)
            first = min([item.lineno for item in node.decorator_list] + [node.lineno])
            parent = in_class.key if in_class is not None else (
                owner.key if owner.kind != "module" else None)
            new = self._add(Node(
                key=f"{owner.file}::{prefix}{node.name}", module=owner.module, file=owner.file,
                qualname=f"{prefix}{node.name}", kind="class", name=node.name,
                line=node.lineno, first_line=first, end_line=node.end_lineno, parent=parent,
                base_exprs=list(node.bases)))
            if in_class is None and owner.kind == "module":
                self.top[(owner.module, node.name)].append(new.key)
                self.top_by_name[node.name].append(new.key)
            elif in_class is None:
                owner.children.append((new.key, cut))
                self.nested[(owner.key, node.name)].append(new.key)
            else:
                self.methods_by_name[node.name].append(new.key)
                self.methods_of[in_class.key].append(new.key)
            # The class body runs where the class is defined.
            self._visit_body(node.body, owner, new, f"{new.qualname}.", cut)
            return
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
                return
            if isinstance(node, ast.AnnAssign):
                for expression in (node.target, node.annotation, node.value):
                    if expression is not None:
                        self._expression(expression, owner, cut)
                return
        if isinstance(node, ast.Import):
            for alias in node.names:
                owner.refs.append(("module", alias.name, cut))
            return
        if isinstance(node, ast.ImportFrom):
            base = self._relative(owner.module, node.level, node.module)
            owner.refs.append(("module", base, cut))
            for alias in node.names:
                owner.refs.append(("submodule", f"{base}.{alias.name}", cut))
            return
        for child_node in ast.iter_child_nodes(node):
            if isinstance(child_node, ast.stmt):
                self._visit(child_node, owner, in_class, prefix,
                            self.cut_of.get(id(child_node), cut))
            elif isinstance(child_node, ast.expr):
                self._expression(child_node, owner, cut)
            elif isinstance(child_node, (ast.excepthandler, ast.match_case, ast.withitem,
                                         ast.comprehension, ast.keyword, ast.arguments,
                                         ast.pattern)):
                self._visit(child_node, owner, in_class, prefix, cut)

    def _expression(self, node, owner: Node, cut) -> None:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                owner.refs.append(("name", sub.id, cut))
            elif isinstance(sub, ast.Attribute):
                chain = _chain(sub)
                owner.refs.append(("chain", chain, cut) if chain else ("method", sub.attr, cut))
            elif (isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                  and sub.value.isidentifier()):
                owner.refs.append(("str", sub.value, cut))
            elif (isinstance(sub, ast.Call) and _call_name(sub) in ("import_module", "__import__")
                  and sub.args and isinstance(sub.args[0], ast.Constant)
                  and isinstance(sub.args[0].value, str)):
                owner.refs.append(("module", sub.args[0].value, cut))

    def _resolve_bases(self, node: Node) -> None:
        owner = self.nodes[node.parent] if node.parent and self.nodes[node.parent].kind in (
            FUNCTION_KINDS) else self.nodes[self.module_key(node.module)]
        for expression in node.base_exprs:
            chain = _chain(expression)
            if chain == ("object",):
                continue
            targets = self._resolve_chain(owner, chain) if chain else []
            classes = [key for kind, key in targets
                       if kind == "node" and self.nodes[key].kind == "class"]
            if classes:
                node.base_keys.extend(classes)
            else:
                node.external_base = True

    # resolution -----------------------------------------------------------
    # Targets: ("node", key) a definition; ("module", name) the value IS that
    # module; ("load", name) that module's body runs (import side effect);
    # ("object", name) a module variable; ("method", name) a method name.
    def _resolve_symbol(self, module: str, symbol: str, depth: int = 0) -> list[tuple]:
        if module not in self.modules:
            return []
        out = [("load", module)]
        submodule = f"{module}.{symbol}"
        if submodule in self.modules:
            out.append(("module", submodule))
        out += [("node", key) for key in self.top.get((module, symbol), [])]
        if depth < 12:
            for binding in self.bindings[module].get(symbol, []):
                out += self._resolve_binding(binding, depth + 1)
        if not any(kind in ("module", "node", "object") for kind, _value in out):
            out.append(("object", f"{module}.{symbol}"))
        return out

    def _resolve_binding(self, binding: tuple, depth: int = 0) -> list[tuple]:
        if binding[0] == "module":
            return [("module", binding[1])] if binding[1] in self.modules else []
        _kind, module, symbol = binding
        return self._resolve_symbol(module, symbol, depth)

    def _resolve_name(self, node: Node, name: str) -> list[tuple]:
        out = []
        scope = node
        while scope is not None:
            if scope.kind in FUNCTION_KINDS:
                out += [("node", key) for key in self.nested.get((scope.key, name), [])]
            scope = self.nodes.get(scope.parent) if scope.parent else None
        out += [("node", key) for key in self.top.get((node.module, name), [])]
        for binding in self.bindings[node.module].get(name, []):
            out += self._resolve_binding(binding)
        return out

    def _resolve_chain(self, node: Node, chain: tuple[str, ...]) -> list[tuple]:
        heads = self._resolve_name(node, chain[0])
        out = list(heads)
        modules = [value for kind, value in heads if kind == "module"]
        # A local variable (no target), a definition or a module variable.
        objects = any(kind in ("node", "object") for kind, _value in heads) or not modules
        for index, attribute in enumerate(chain[1:], 1):
            if objects:
                # Attributes of an object (not of a module) are method names.
                out += [("method", name) for name in chain[index:]]
            if not modules:
                break
            next_modules = []
            for module in modules:
                targets = self._resolve_symbol(module, attribute)
                out += targets
                next_modules += [value for kind, value in targets if kind == "module"]
                objects = objects or any(kind in ("node", "object") for kind, _value in targets)
            modules = next_modules
            objects = objects or not modules
        return out

    def resolve(self, node: Node, kind: str, value) -> list[tuple]:
        cache_key = (node.key, kind, value)
        cached = self._resolved.get(cache_key)
        if cached is not None:
            return cached
        if kind == "name":
            out = self._resolve_name(node, value)
        elif kind == "chain":
            out = self._resolve_chain(node, value)
        elif kind == "method":
            out = [("method", value)]
        elif kind == "str":
            out = [("node", key) for key in self.top_by_name.get(value, [])]
            out.append(("method", value))
        elif kind in ("module", "submodule"):
            out = [("module", value)] if value in self.modules else []
        else:
            out = []
        self._resolved[cache_key] = out
        return out

    # reachability ---------------------------------------------------------
    def reach(self, active_cuts: frozenset[str]) -> dict[str, tuple]:
        reached: dict[str, tuple] = {}
        method_names: dict[str, str] = {}
        live_classes: set[str] = set()
        stack: list[str] = []

        def add(key: str, predecessor, how: str) -> None:
            if key not in reached:
                reached[key] = (predecessor, how)
                stack.append(key)

        def add_module(module: str, predecessor) -> None:
            parts = module.split(".")
            for size in range(1, len(parts) + 1):
                prefix = ".".join(parts[:size])
                if prefix in self.modules:
                    add(self.module_key(prefix), predecessor, "import")

        add_module(ROOT_MODULE, None)
        while stack:
            key = stack.pop()
            node = self.nodes[key]
            if node.kind == "class":
                live_classes.add(key)
                for base in node.base_keys:
                    add(base, key, "base")
                for method_key in self.methods_of.get(key, []):
                    method = self.nodes[method_key]
                    dunder = method.name.startswith("__") and method.name.endswith("__")
                    if (method.name in method_names or dunder or node.external_base
                            or method.registering):
                        add(method_key, key, "method")
            for child_key, cut in node.children:
                if cut not in active_cuts:
                    add(child_key, key, "defines")
            for kind, value, cut in node.refs:
                if cut in active_cuts:
                    continue
                for target_kind, target in self.resolve(node, kind, value):
                    if target_kind == "node":
                        add(target, key, kind)
                    elif target_kind in ("module", "load"):
                        add_module(target, key)
                    elif target_kind == "method" and target not in method_names:
                        method_names[target] = key
                        for method_key in self.methods_by_name.get(target, []):
                            if self.nodes[method_key].parent in live_classes:
                                add(method_key, key, "attr")
        return reached

    # entities -------------------------------------------------------------
    def entity_of(self, key: str) -> str:
        """The reportable definition a node rolls up to."""
        node = self.nodes[key]
        chain = [node]
        while node.parent:
            node = self.nodes[node.parent]
            chain.append(node)
        # outermost definition below a function, or the definition itself
        for index in range(len(chain) - 1, -1, -1):
            if chain[index].kind in FUNCTION_KINDS:
                return chain[index].key
        return chain[0].key if chain[0].kind != "module" else key

    def path_to(self, reached: dict[str, tuple], key: str, limit: int = 12) -> list[str]:
        path = []
        current = key
        while current is not None and len(path) < limit:
            predecessor, how = reached[current]
            node = self.nodes[current]
            path.append(f"{node.file}::{node.qualname}" + (f" [{how}]" if how else ""))
            current = predecessor
        return list(reversed(path))


def static(args) -> int:
    golden = Path(args.golden).resolve()
    code = Path(args.code).resolve()
    trace_dir = _private_dir(golden / "trace")
    started = time.monotonic()
    graph = StaticGraph(code)
    all_cuts = frozenset(cut.id for cut in graph.cuts)
    with_cuts = graph.reach(all_cuts)
    without_cuts = graph.reach(frozenset())
    lifted = {cut.id: graph.reach(all_cuts - {cut.id}) for cut in graph.cuts}
    entities = {}
    for key, node in graph.nodes.items():
        if node.kind == "module" or graph.entity_of(key) != key:
            continue
        record = {
            "file": node.file, "qualname": node.qualname, "kind": node.kind,
            "lines": [node.first_line, node.end_line],
            "n_lines": node.end_line - node.first_line + 1,
            "parent": node.parent,
            "reached": key in with_cuts,
            "reached_without_cuts": key in without_cuts,
        }
        if key in with_cuts:
            record["path"] = graph.path_to(with_cuts, key)
        elif key in without_cuts:
            record["hidden_by"] = sorted(cut for cut, reach in lifted.items() if key in reach)
            record["path_without_cuts"] = graph.path_to(without_cuts, key)
        entities[key] = record
    modules = {
        module: {"file": file, "reached": graph.module_key(module) in with_cuts,
                 "reached_without_cuts": graph.module_key(module) in without_cuts}
        for module, file in sorted(graph.modules.items())
    }
    result = {
        "generated_at": _utc_now(),
        "code": str(code),
        "commit": _commit_of(code),
        "root": ROOT_MODULE,
        "method": STATIC_METHOD_NOTE,
        "cuts": [dataclasses.asdict(cut) for cut in graph.cuts],
        "counts": {
            "entities": len(entities),
            "reached": sum(record["reached"] for record in entities.values()),
            "unreached": sum(not record["reached"] for record in entities.values()),
            "unreached_without_cuts": sum(not record["reached_without_cuts"]
                                          for record in entities.values()),
        },
        "entities": dict(sorted(entities.items())),
        "modules": modules,
        "elapsed_s": round(time.monotonic() - started, 1),
    }
    _write_json(trace_dir / "static_reach.json", result)
    counts = result["counts"]
    print(f"estático: {counts['entities']} definições, {counts['reached']} alcançáveis, "
          f"{counts['unreached']} inalcançáveis com os cortes "
          f"({counts['unreached_without_cuts']} sem caminho nenhum) "
          f"-> {trace_dir / 'static_reach.json'}")
    return 0


# ─── reconcile: deletion_list.json ─────────────────────────────────────

WHOLE_MODULE_CATEGORIES = {
    "legacy_modules": ("backend/scheduler/jit.py", "backend/scheduler/vns.py",
                       "backend/scheduler/window.py", "backend/scheduler/dispatch.py",
                       "backend/scheduler/tool_grouping.py"),
    "cpsat_polish": ("backend/cpo/cpsat_polish.py",),
    "ga_stack": ("backend/cpo/offline_ga.py", "backend/cpo/cached_pipeline.py",
                 "backend/cpo/chromosome.py", "backend/cpo/population.py",
                 "backend/cpo/surrogate.py", "backend/scheduler/cache.py"),
}
FILE_CATEGORIES = {
    "backend/scheduler/scheduler.py": "scheduler_legacy",
    "backend/scheduler/global_jit.py": "global_jit_model",
    "backend/cpo/optimizer.py": "optimizer_search",
    "backend/plans/manual_move.py": "manual_move",
}
CATEGORY_LABELS = {
    "scheduler_legacy": "scheduler.py: cauda do schedule_all e auxiliares antigos",
    "global_jit_model": "global_jit.py: modelo CP-SAT global",
    "legacy_modules": "jit, vns, window, dispatch, tool_grouping",
    "optimizer_search": "optimizer.py: pesquisa de candidatos e deep/max",
    "cpsat_polish": "cpsat_polish",
    "ga_stack": "algoritmo genético e cache",
    "learning": "learning/Optuna (modo smart)",
    "manual_move": "manual_move.py",
    "orphan": "funções órfãs noutros ficheiros (sem caminho a partir da aplicação)",
    "legacy_support": "auxiliares só do motor antigo noutros ficheiros (só pelos cortes C1-C4)",
}
# Functions the plan names as orphans (audits of 11/10): checked one by one.
PLAN_ORPHANS = (
    ("backend/risk/surrogate.py", "train_surrogate"),
    ("backend/risk/slack_analytics.py", "compute_bottleneck"),
    ("backend/scheduler/material_quantities.py", "lot_customer_delays"),
    ("backend/scheduler/material_quantities.py", "output_completion_days"),
    ("backend/scheduler/priority_normalization.py", "build_priority_rotation_candidate"),
    ("backend/scheduler/explainability.py", "_clip_interval"),
    ("backend/scheduler/explainability.py", "_segment_operator_demand"),
    ("backend/scheduler/explainability.py", "_target_operator_demand"),
    ("backend/scheduler/explainability.py", "_resource_indexes"),
    ("backend/scheduler/explainability.py", "_segment_detail"),
    ("backend/scheduler/explainability.py", "_metadata_detail"),
    ("backend/scheduler/explainability.py", "_operator_conflicts"),
    ("backend/scheduler/explainability.py", "_setup_crew_conflicts"),
    ("backend/current_state.py", "validate_current_states"),
    ("backend/scheduler/gates.py", "gate_passed"),
    ("backend/scheduler/validation.py", "validation_counts"),
    ("backend/scheduler/vns.py", "_generate_n4_split_moves"),
    ("backend/scheduler/window.py", "window_dispatch"),
    ("backend/config/planning.py", "effective_internal_deadline_for_op"),
    ("backend/scheduler/scheduler.py", "_compact_segments"),
    ("backend/scheduler/scheduler.py", "_left_shift_lots_into_empty_workdays"),
)
# Live code the plan keeps (Passo 6d), checked against the trace.
PLAN_KEEP = (
    ("backend/scheduler/scheduler.py", "_repair_hard_constraints"),
    ("backend/scheduler/scheduler.py", "_fix_orphan_continuations"),
    ("backend/scheduler/scheduler.py", "normalize_earliest_legal_plan"),
    ("backend/scheduler/scheduler.py", "_remove_redundant_retained_tool_setups"),
    ("backend/scheduler/scheduler.py", "_apply_gap_move_batch"),
)
# (file, first, last, label, functions whose runs say whether the window was exercised)
REQUESTED_WINDOWS = (
    ("backend/scheduler/scheduler.py", 4277, 4951, "cauda do schedule_all (pedido: 4277-4951)",
     ("schedule_all",)),
    ("backend/plans/manual_move.py", 986, 1010, "garfo do manual_move (pedido: 986-1010)",
     ("_allocate_existing_lots", "_replan_around_fixed_lot")),
    ("backend/plans/manual_move.py", 1458, 1473, "garfo do manual_move (pedido: 1458-1473)",
     ("_move_lot", "_reallocation_ignores_target")),
    ("backend/scheduler/global_jit.py", 126, 145, "ramo por partes do solve_global_jit "
     "(pedido: 126-145)", ("solve_global_jit",)),
)


def _category(record: dict) -> str:
    file = record["file"]
    for category, files in WHOLE_MODULE_CATEGORIES.items():
        if file in files:
            return category
    if file.startswith("backend/learning/"):
        return "learning"
    if file in FILE_CATEGORIES:
        return FILE_CATEGORIES[file]
    return "legacy_support" if record.get("reached_without_cuts") else "orphan"


def _test_index(code: Path) -> dict[str, set[str]]:
    """identifier -> test files that mention it (indicative: a word match)."""
    import re

    index: dict[str, set[str]] = collections.defaultdict(set)
    tests = code / "tests"
    if tests.is_dir():
        for path in sorted(tests.rglob("*.py")):
            if "fixtures" in path.parts:
                continue
            for word in set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", path.read_text())):
                index[word].add(str(path.relative_to(code)))
    return index


class LiveIndex:
    """Trace records mapped onto the static definitions."""

    def __init__(self, live: dict, static_result: dict):
        self.live = live
        self.by_qualname: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
        self.entities = static_result["entities"]
        nodes_by_file: dict[str, list[tuple[str, dict]]] = collections.defaultdict(list)
        for key, record in self.entities.items():
            self.by_qualname[(record["file"], record["qualname"])].append(key)
            nodes_by_file[record["file"]].append((key, record))
        self.executed: dict[str, dict] = {}       # entity key -> {"golden": {...}, "probes": {}}
        self.class_body: dict[str, dict] = {}
        self.modules_run: dict[str, dict] = {}
        self.unmapped: list = []
        for file, records in live["functions"].items():
            for qualname, record in records.items():
                if qualname == "<module>":
                    self.modules_run[file] = record
                    continue
                key = self._entity(file, qualname, record["first_lines"], nodes_by_file[file])
                if key is None:
                    self.unmapped.append([file, qualname])
                    continue
                if self.entities[key]["kind"] == "class" and qualname == self.entities[key][
                        "qualname"]:
                    self._merge(self.class_body, key, record)
                    continue
                self._merge(self.executed, key, record)

    @staticmethod
    def _merge(target: dict, key: str, record: dict) -> None:
        entry = target.setdefault(key, {"golden": {}, "probes": {}})
        for group in ("golden", "probes"):
            for mode, flows in record[group].items():
                entry[group][mode] = sorted(set(entry[group].get(mode, [])) | set(flows))

    def _entity(self, file, qualname, first_lines, records):
        parts = qualname.split(".")
        while parts:
            candidate = ".".join(parts)
            keys = self.by_qualname.get((file, candidate))
            if keys:
                if len(keys) == 1:
                    return keys[0]
                exact = [key for key in keys if self.entities[key]["lines"][0] in first_lines]
                return (exact or keys)[0]
            parts.pop()
            while parts and parts[-1] == "<locals>":
                parts.pop()
        # a nested definition rolled up by line containment
        line = min(first_lines)
        containing = [(record["lines"][1] - record["lines"][0], key) for key, record in records
                      if record["lines"][0] <= line <= record["lines"][1]]
        return min(containing)[1] if containing else None

    def ran(self, key: str, include_probes: bool = True) -> bool:
        entry = self.executed.get(key)
        if not entry:
            return False
        return bool(entry["golden"]) or (include_probes and bool(entry["probes"]))


def _flows_text(entry: dict | None) -> str:
    if not entry:
        return "nunca"
    parts = []
    for group in ("golden", "probes"):
        for mode, flows in sorted((entry.get(group) or {}).items()):
            parts.append(f"{mode}: {', '.join(flows)}")
    return "; ".join(parts)


def _lines_in(ranges: list[list[int]], first: int, last: int) -> list[int]:
    out = []
    for start, end in ranges:
        out.extend(range(max(start, first), min(end, last) + 1))
    return out


def reconcile(args) -> int:
    golden = Path(args.golden).resolve()
    code = Path(args.code).resolve()
    trace_dir = golden / "trace"
    live = json.loads((trace_dir / "live_set.json").read_text())
    static_result = json.loads((trace_dir / "static_reach.json").read_text())
    for name, document in (("live_set", live), ("static_reach", static_result)):
        if Path(document["code"]).resolve() != code:
            raise SystemExit(f"{name}.json is for {document['code']}, not {code}")
    index = LiveIndex(live, static_result)
    entities = static_result["entities"]
    tests = _test_index(code)

    def item(key: str, **extra) -> dict:
        record = entities[key]
        name = record["qualname"].rsplit(".", 1)[-1]
        out = {"file": record["file"], "qualname": record["qualname"], "kind": record["kind"],
               "lines": record["lines"], "n_lines": record["n_lines"],
               "category": _category(record),
               "test_files_mentioning_name": len(tests.get(name, ()))}
        if record["reached"]:
            out["static"] = "alcançável"
        elif record["reached_without_cuts"]:
            out["static"] = "só pelos cortes: " + (", ".join(record["hidden_by"]) or "vários")
        else:
            out["static"] = "sem caminho a partir da aplicação"
        out.update(extra)
        return out

    unreached_classes = {key for key, record in entities.items()
                         if record["kind"] == "class" and not record["reached"]}

    def inside_unreached_class(key: str) -> bool:
        parent = entities[key].get("parent")
        while parent:
            if parent in unreached_classes:
                return True
            parent = (entities.get(parent) or {}).get("parent")
        return False

    def class_ran(key: str) -> dict | None:
        merged: dict = {}
        for other, record in entities.items():
            if record.get("parent") == key and other in index.executed:
                LiveIndex._merge(merged, "x", index.executed[other])
        return merged.get("x")

    confirmed, contradictions, probes_only, review = [], [], [], []
    for key, record in sorted(entities.items(), key=lambda pair: (
            pair[1]["file"], pair[1]["lines"][0])):
        if record["reached"]:
            continue
        if inside_unreached_class(key):
            continue
        ran = class_ran(key) if record["kind"] == "class" else index.executed.get(key)
        if ran and (ran["golden"] or ran["probes"]):
            contradictions.append(item(key, executed=ran, reason=(
                "inalcançável pela análise estática mas correu: falha da análise "
                "(despacho dinâmico) ou corte errado; fica")))
        else:
            extra = {}
            module_file = record["file"]
            if module_file in index.modules_run:
                extra["module_imported"] = True
            if key in index.class_body:
                extra["class_body_ran_at_import"] = True
            confirmed.append(item(key, **extra))
    declared_files = {file for files in WHOLE_MODULE_CATEGORIES.values() for file in files}
    for key, record in sorted(entities.items(), key=lambda pair: (
            pair[1]["file"], pair[1]["lines"][0])):
        if not record["reached"]:
            continue
        declared = (record["file"] in declared_files
                    or record["file"].startswith("backend/learning/")
                    or (record["file"], record["qualname"]) in PLAN_ORPHANS)
        if not declared:
            continue
        ran = class_ran(key) if record["kind"] == "class" else index.executed.get(key)
        if ran and ran["golden"]:
            contradictions.append(item(key, executed=ran, path=record.get("path"), reason=(
                "o plano dá como morta mas correu nos fluxos golden: fica")))
        elif ran:
            probes_only.append(item(key, executed=ran, path=record.get("path"), reason=(
                "viva: o Copilot alcança-a (correu nas sondas, não nos fluxos golden). Não é "
                "código morto; só sai com a retirada da funcionalidade (Passo 4)")))
        else:
            reason = ("o plano dá como morta, a análise estática encontra um caminho e o "
                      "rastreio não a viu correr: confirmar o caminho antes de apagar")
            if record["kind"] == "class":
                reason += (" (classe: instanciar uma dataclass não é observável pelo "
                           "rastreio)")
            review.append(item(key, path=record.get("path"), reason=reason))

    # line regions -------------------------------------------------------
    regions = []
    executable_cache: dict[str, list[int]] = {}
    for cut in static_result["cuts"]:
        file = cut["file"]
        executable = executable_cache.setdefault(file, executable_lines(code / file))
        executed_all = live["lines"][file]["executed"]["all"]
        for first, last in cut["spans"]:
            in_region = [line for line in executable if first <= line <= last]
            ran_lines = _lines_in(executed_all, first, last)
            regions.append({
                "cut": cut["id"], "file": file, "function": cut["function"],
                "description": cut["description"], "lines": [first, last],
                "executable_lines": len(in_region), "executed_lines": ran_lines,
                "executed": bool(ran_lines),
            })
    windows = []
    for file, first, last, label, related in REQUESTED_WINDOWS:
        executable = executable_cache.setdefault(file, executable_lines(code / file))
        in_window = [line for line in executable if first <= line <= last]
        legacy = sorted({line for region in regions if region["file"] == file
                         for line in in_window
                         if region["lines"][0] <= line <= region["lines"][1]})
        by_flow = {}
        for flow, ranges in live["lines_by_flow"].get(file, {}).items():
            hit = _lines_in(ranges, first, last)
            if hit:
                by_flow[flow] = _ranges(hit)
        executed = sorted({line for ranges in by_flow.values() for start, end in ranges
                           for line in range(start, end + 1)})
        windows.append({
            "file": file, "window": [first, last], "label": label,
            "executable_lines": in_window,
            "legacy_only_lines": legacy,
            "shared_lines": [line for line in in_window if line not in legacy],
            "executed_lines": executed,
            "executed_legacy_lines": [line for line in executed if line in legacy],
            "executed_by_flow": by_flow,
            "exercised_by": sorted({flow.split("@")[0] for flow in by_flow}),
            "related_functions": {
                name: _flows_text(index.executed.get(
                    (index.by_qualname.get((file, name)) or [None])[0])) for name in related},
        })

    # confirmations ------------------------------------------------------
    def find(file: str, qualname: str) -> str | None:
        keys = index.by_qualname.get((file, qualname))
        return keys[0] if keys else None

    def ran_text(file: str, qualname: str) -> tuple[bool, str]:
        key = find(file, qualname)
        if key is None:
            return False, "definição não encontrada"
        entry = index.executed.get(key)
        return bool(entry and (entry["golden"] or entry["probes"])), _flows_text(entry)

    confirmations = []

    def confirm(claim: str, ok: bool, evidence: str, status: str | None = None) -> None:
        confirmations.append({"claim": claim, "status": status or (
            "confirmado" if ok else "NÃO confirmado"), "evidence": evidence})

    c1 = [region for region in regions if region["cut"] == "C1"]
    head_ran, head_flows = ran_text("backend/scheduler/scheduler.py", "schedule_all")
    confirm("A cauda do schedule_all nunca corre",
            not any(region["executed"] for region in c1) and head_ran,
            f"linhas {c1[0]['lines'][0]}-{c1[0]['lines'][1]}: {c1[0]['executable_lines']} linhas "
            f"com código, 0 executadas; a cabeça do schedule_all correu em {head_flows}"
            if c1 and not c1[0]["executed"] else f"executadas: {c1[0]['executed_lines'][:40]}")
    for window in windows[1:3]:
        legacy_ran = window["executed_legacy_lines"]
        exercised = window["exercised_by"]
        golden_exercise = [flow for flow in exercised if flow not in PROBES]
        if legacy_ran:
            status = None
        elif not exercised:
            status = "confirmado (sem exercício: nenhum fluxo chegou a esta janela)"
        elif all(flow in PROBES for flow in exercised):
            status = "confirmado (exercido só pela sonda, não pelo golden master)"
        else:
            status = "confirmado"
        related = "; ".join(f"{name}: {text}" for name, text in
                            window["related_functions"].items())
        confirm(
            f"manual_move {window['window'][0]}-{window['window'][1]} nunca corre",
            not legacy_ran,
            (f"linhas só do motor antigo {_ranges(window['legacy_only_lines'])}: 0 executadas. "
             f"Linhas partilhadas da janela que correram: "
             f"{_ranges(window['executed_lines']) or 'nenhuma'}; janela exercida por "
             f"{exercised or 'nenhum fluxo'} (golden: {golden_exercise or 'nenhum'}). "
             f"Funções: {related}")
            if not legacy_ran else f"linhas antigas executadas: {legacy_ran}",
            status=status)
    for file, qualname in (("backend/scheduler/global_jit.py", "solve_global_jit"),
                           ("backend/cpo/optimizer.py", "_improve_baseline"),
                           ("backend/cpo/cpsat_polish.py", "cpsat_polish")):
        ran, flows_text = ran_text(file, qualname)
        confirm(f"{qualname} nunca corre", not ran, f"{file}: {flows_text}")
    learning_keys = [key for key, record in entities.items()
                     if record["file"].startswith("backend/learning/")]
    learning_golden = sorted({f"{record['qualname']} ({_flows_text(index.executed[key])})"
                              for key, record in ((k, entities[k]) for k in learning_keys)
                              if key in index.executed and index.executed[key]["golden"]})
    learning_probe = collections.defaultdict(set)
    for key in learning_keys:
        for mode, flows in (index.executed.get(key) or {}).get("probes", {}).items():
            for flow in flows:
                learning_probe[flow].add(entities[key]["qualname"])
    static_paths = sorted({
        " -> ".join(record["path"][-3:]) for key in learning_keys
        for record in (entities[key],) if record["reached"] and len(record.get("path") or []) > 1
        and not record["path"][-2].startswith("backend/learning/")})
    only_smart = (not learning_golden and set(learning_probe) <= {"P6_copilot_smart"})
    confirm(
        "learning só corre pelo modo smart do Copilot",
        only_smart,
        "fluxos golden: " + ("; ".join(learning_golden) or "nenhuma função de learning")
        + ". Sondas: " + "; ".join(f"{flow}: {len(names)} funções ({', '.join(sorted(names)[:6])}"
                                   f"{'…' if len(names) > 6 else ''})"
                                   for flow, names in sorted(learning_probe.items()))
        + ". Entradas estáticas em learning: " + " | ".join(static_paths),
    )
    for qualname in ("_repair_hard_constraints", "_fix_orphan_continuations"):
        key = find("backend/scheduler/scheduler.py", qualname)
        entry = index.executed.get(key) if key else None
        modes = sorted(mode for mode, flows in ((entry or {}).get("golden") or {}).items()
                       if "F3_outage_small" in flows)
        confirm(f"{qualname} corre na avaria pequena (F3_outage_small)",
                bool(modes), f"modos com F3_outage_small: {modes or 'nenhum'}; "
                f"todos os fluxos: {_flows_text(entry)}")

    keep = []
    for file, qualname in PLAN_KEEP:
        key = find(file, qualname)
        keep.append({"file": file, "qualname": qualname,
                     "static": None if key is None else entities[key]["reached"],
                     "executed": _flows_text(index.executed.get(key)) if key else None})
    global_jit_live = [
        {"qualname": record["qualname"], "lines": record["lines"],
         "executed": _flows_text(index.executed.get(key))}
        for key, record in sorted(entities.items(), key=lambda pair: pair[1]["lines"][0])
        if record["file"] == "backend/scheduler/global_jit.py" and record["reached"]]
    orphans = []
    for file, qualname in PLAN_ORPHANS:
        key = find(file, qualname)
        orphans.append({
            "file": file, "qualname": qualname,
            "static": None if key is None else item(key)["static"],
            "executed": _flows_text(index.executed.get(key)) if key else None,
            "verdict": None if key is None else (
                "contradição" if index.ran(key) else
                "confirmada morta" if not entities[key]["reached"] else "rever"),
        })

    by_category = collections.defaultdict(lambda: {"definitions": 0, "lines": 0})
    for entry in confirmed:
        by_category[entry["category"]]["definitions"] += 1
        by_category[entry["category"]]["lines"] += entry["n_lines"]
    by_file = collections.defaultdict(lambda: {"definitions": 0, "lines": 0})
    for entry in confirmed:
        by_file[entry["file"]]["definitions"] += 1
        by_file[entry["file"]]["lines"] += entry["n_lines"]
    module_files = {record["file"] for record in static_result["modules"].values()}
    whole_files = []
    for file in sorted(module_files):
        file_entities = [key for key, record in entities.items() if record["file"] == file]
        if file_entities and all(
                not entities[key]["reached"] and not index.ran(key) for key in file_entities):
            module = next(name for name, record in static_result["modules"].items()
                          if record["file"] == file)
            whole_files.append({"file": file, "module_reached": static_result["modules"][
                module]["reached"], "module_imported_in_trace": file in index.modules_run})
    region_lines = sum(region["executable_lines"] for region in regions
                       if not region["executed"])
    result = {
        "generated_at": _utc_now(),
        "code": str(code),
        "commit": live.get("commit"),
        "rule": ("apagar = inalcançável estaticamente a partir de backend.api.copilot com os "
                 "cortes de dados reais E ausente do live_set (rastreio golden F1-F10 nos dois "
                 "modos, mais as sondas P4/P6)"),
        "inputs": {
            "live_set_sha256": _sha256_file(trace_dir / "live_set.json"),
            "static_reach_sha256": _sha256_file(trace_dir / "static_reach.json"),
        },
        "summary": {
            "confirmed_dead": {"definitions": len(confirmed),
                               "lines": sum(entry["n_lines"] for entry in confirmed)},
            "contradictions": len(contradictions),
            "live_via_probes_only": len(probes_only),
            "needs_review": len(review),
            "dead_regions_inside_live_functions": {
                "regions": sum(not region["executed"] for region in regions),
                "executable_lines": region_lines},
            "by_category": {f"{category} — {CATEGORY_LABELS.get(category, category)}": values
                            for category, values in sorted(by_category.items())},
            "by_file": dict(sorted(by_file.items(), key=lambda pair: -pair[1]["lines"])),
            "whole_files_dead": whole_files,
            "unmapped_trace_records": index.unmapped,
        },
        "confirmations": confirmations,
        "confirmed_dead": confirmed,
        "contradictions": contradictions,
        "live_via_probes_only": probes_only,
        "needs_review": review,
        "dead_line_regions": regions,
        "requested_windows": windows,
        "plan_keep": keep,
        "global_jit_live": global_jit_live,
        "plan_orphans": orphans,
        "modes": {mode: {name: {key: entry.get(key) for key in (
            "status", "sha256", "baseline_sha256_match", "error", "wall_s")}
            for name, entry in values["flows"].items()} for mode, values in live["modes"].items()},
    }
    _write_json(trace_dir / "deletion_list.json", result)
    print_summary(result)
    print(f"-> {trace_dir / 'deletion_list.json'}")
    return 0


def print_summary(result: dict) -> None:
    summary = result["summary"]
    print("Resumo (pt-PT)")
    dead = summary["confirmed_dead"]
    print(f"- Mortas confirmadas: {dead['definitions']} definições, {dead['lines']} linhas "
          "(inalcançáveis estaticamente E nunca vistas no rastreio).")
    regions = summary["dead_regions_inside_live_functions"]
    print(f"- Regiões mortas dentro de funções vivas: {regions['regions']} "
          f"({regions['executable_lines']} linhas com código).")
    print(f"- Contradições (dadas como mortas mas correram nos fluxos golden, ou "
          f"inalcançáveis que correram — ficam): {summary['contradictions']}.")
    print(f"- Vivas só pelas sondas (o plano dá como mortas; o Copilot alcança-as; saem só "
          f"com a retirada da funcionalidade): {summary['live_via_probes_only']}.")
    print(f"- Para rever (o plano dá como mortas, há caminho estático, não correram): "
          f"{summary['needs_review']}.")
    print("- Por categoria:")
    for category, values in summary["by_category"].items():
        print(f"    {category}: {values['definitions']} definições, {values['lines']} linhas")
    print("- Confirmações pedidas:")
    for item in result["confirmations"]:
        print(f"    [{item['status']}] {item['claim']}: {item['evidence'][:400]}")
    for item in result["contradictions"]:
        print(f"  contradição: {item['file']}::{item['qualname']} — "
              f"{_flows_text(item.get('executed'))}")


# ─── Entry point ───────────────────────────────────────────────────────


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["child"]:
        return child(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("run", "merge", "static", "reconcile", "all"))
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    parser.add_argument("--code", required=True, help="code tree (e.g. <golden>/code-5a03230)")
    parser.add_argument("--mode", choices=sorted(MODES), help="run: real or deterministic")
    parser.add_argument("--flows", default="", help="run: comma-separated flow names")
    parser.add_argument("--no-probes", action="store_true", help="run: skip the P4/P6 probes")
    parser.add_argument("--cores", default="", help="run: comma-separated cores")
    parser.add_argument("--force", action="store_true", help="run: replace an existing run")
    parser.add_argument("--label", default="",
                        help="run: write to runs-<mode>-<label> (not read by merge)")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)
    if args.command == "run":
        if not args.mode:
            parser.error("run needs --mode")
        return run_traces(args)
    if args.command == "merge":
        return merge(args)
    if args.command == "static":
        return static(args)
    if args.command == "reconcile":
        return reconcile(args)
    status = 0
    for mode in ("real", "deterministic"):
        args.mode = mode
        status |= run_traces(args)
    return status or merge(args) or static(args) or reconcile(args)


if __name__ == "__main__":
    sys.exit(main())
