#!/usr/bin/env python3
"""Capture the golden master of one code tree (plan Passo 1b).

Every flow of ``flows.py`` runs in its own process, on its own core
(``taskset``), on a fresh copy of the pristine production state, with
``PYTHONHASHSEED=0`` and one BLAS/OpenMP thread. One canonical JSON per flow
and ``SUMMARY.json`` (sha256 per flow, timings) are written to ``--out``.

Commands::

  # once: pristine inputs from the running application (read-only)
  capture.py --build-pristine
  capture.py --set-param F4_manual_move '{"applied": {...}, "refused": {...}}'

  # a commit as a code tree (git archive, outside git's working trees)
  capture.py --archive 5a03230

  # calibration (real budgets): evaluation counts for the deterministic mode
  capture.py --code <golden>/code-5a03230 --out <golden>/captures/calibration --calibrate

  # a capture (deterministic), all flows or the fast subset
  capture.py --code <tree> --out <golden>/captures/<name> [--fast] [--flows A,B]

Everything lives in ``--golden`` (default ``~/incompolinho-private/golden``,
or ``PP1_GOLDEN_DIR``), which holds client data and stays outside git
(chmod 700). The live application is only read: SQLite through the backup
API from a ``mode=ro`` connection, the other files by reading them.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import queue
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import flows as golden_flows  # noqa: E402

LIVE_TREE = golden_flows.LIVE_TREE
DEFAULT_GOLDEN = Path(os.environ.get(
    "PP1_GOLDEN_DIR", str(Path.home() / "incompolinho-private" / "golden")))
PRIVATE_FIXTURES = Path(os.environ.get(
    "PP1_PRIVATE_FIXTURES", str(Path.home() / "incompolinho-private" / "fixtures")))
DATABASES = ("plans", "replan", "audit", "robustness")
DATA_FILES = ("copilot_state.json",)
CONFIG_FILES = ("factory.yaml", "incompol.yaml")
DEFAULT_CORES = "0,2,4,6,8,10"  # one hyper-thread of each P-core (i5-13500)
FLOW_TIMEOUT_S = 4 * 3600


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _private_tree(path: Path) -> None:
    for item in [path, *path.rglob("*")]:
        if item.is_symlink():
            continue
        item.chmod(0o700 if item.is_dir() else 0o600)


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


# ─── Pristine inputs ───────────────────────────────────────────────────


def build_pristine(golden: Path, force: bool) -> Path:
    pristine = golden / "pristine"
    if (pristine / "MANIFEST.json").exists() and not force:
        raise SystemExit(f"{pristine} already exists (built once; --force to rebuild)")
    golden.mkdir(parents=True, exist_ok=True)
    golden.chmod(0o700)
    staging = golden / "pristine.tmp"
    shutil.rmtree(staging, ignore_errors=True)
    for sub in ("data", "config", "fixtures"):
        (staging / sub).mkdir(parents=True)
    captured_at = _utc_now()
    source_data, source_config = LIVE_TREE / "data", LIVE_TREE / "config"
    missing = []
    for name in DATABASES:
        source = source_data / f"{name}.db"
        if not source.exists():
            missing.append(str(source))
            continue
        reader = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        writer = sqlite3.connect(staging / "data" / f"{name}.db")
        try:
            reader.backup(writer)
        finally:
            writer.close()
            reader.close()
        checked = sqlite3.connect(f"file:{staging / 'data' / f'{name}.db'}?mode=ro", uri=True)
        try:
            status = checked.execute("pragma integrity_check").fetchone()[0]
        finally:
            checked.close()
        if status != "ok":
            raise SystemExit(f"integrity_check {name}.db: {status}")
    for name in DATA_FILES:
        source = source_data / name
        if source.exists():
            (staging / "data" / name).write_bytes(source.read_bytes())
        else:
            missing.append(str(source))
    for name in CONFIG_FILES:
        (staging / "config" / name).write_bytes((source_config / name).read_bytes())
    sums = {}
    sums_file = PRIVATE_FIXTURES / "SHA256SUMS"
    if sums_file.exists():
        for line in sums_file.read_text().splitlines():
            value, _, name = line.partition("  ")
            sums[name.strip()] = value.strip()
    for fixture in golden_flows.FIXTURES:
        source = PRIVATE_FIXTURES / f"{fixture}.json.gz"
        target = staging / "fixtures" / source.name
        target.write_bytes(source.read_bytes())
        expected = sums.get(source.name)
        if expected and expected != _sha256(target):
            raise SystemExit(f"{source.name} differs from SHA256SUMS")
    plans = sqlite3.connect(f"file:{staging / 'data' / 'plans.db'}?mode=ro", uri=True)
    try:
        runtime = plans.execute("select snapshot_id, plan_revision from plan_runtime").fetchone()
    finally:
        plans.close()
    manifest = {
        "captured_at": captured_at.isoformat(),
        # The frozen clock of every flow on the production state: the
        # capture instant, later than every stamp already in the data.
        "clock_anchor": captured_at.isoformat(),
        "timezone": "Europe/Lisbon",
        "sources": {"data": str(source_data), "config": str(source_config),
                    "fixtures": str(PRIVATE_FIXTURES)},
        "active_plan": {"snapshot_id": runtime[0], "plan_revision": runtime[1]}
        if runtime else None,
        "fixture_anchors": golden_flows.FIXTURE_ANCHORS,
        "missing": missing,
        "files": {
            str(path.relative_to(staging)): {"sha256": _sha256(path), "bytes": path.stat().st_size}
            for path in sorted(staging.rglob("*")) if path.is_file()
        },
    }
    (staging / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    if pristine.exists():
        shutil.rmtree(pristine)
    staging.rename(pristine)
    _private_tree(pristine)
    return pristine


def verify_pristine(pristine: Path) -> dict:
    manifest = json.loads((pristine / "MANIFEST.json").read_text())
    for relative, entry in manifest["files"].items():
        path = pristine / relative
        if not path.exists() or path.stat().st_size != entry["bytes"]:
            raise SystemExit(f"pristine changed: {relative}")
        if _sha256(path) != entry["sha256"]:
            raise SystemExit(f"pristine changed (sha256): {relative}")
    return manifest


def set_param(golden: Path, key: str, value: str) -> None:
    path = golden / "pristine" / "flow_params.json"
    params = json.loads(path.read_text()) if path.exists() else {}
    params[key] = json.loads(value)
    path.write_text(json.dumps(params, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    path.chmod(0o600)


def archive(golden: Path, commit: str, repo: Path) -> Path:
    full = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", f"{commit}^{{commit}}"],
                          check=True, capture_output=True, text=True).stdout.strip()
    target = golden / f"code-{commit}"
    if target.exists():
        raise SystemExit(f"{target} already exists")
    staging = golden / f"code-{commit}.tmp"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    tar = subprocess.Popen(["git", "-C", str(repo), "archive", full], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-x", "-C", str(staging)], stdin=tar.stdout, check=True)
    if tar.wait() != 0:
        raise SystemExit("git archive failed")
    (staging / ".golden-commit").write_text(full + "\n")
    staging.rename(target)
    _private_tree(target)
    return target


# ─── Capture ───────────────────────────────────────────────────────────


def _code_identity(code: Path) -> dict:
    marker = code / ".golden-commit"
    if marker.exists():
        return {"commit": marker.read_text().strip(), "dirty": False, "kind": "archive"}
    try:
        commit = subprocess.run(["git", "-C", str(code), "rev-parse", "HEAD"], check=True,
                                capture_output=True, text=True).stdout.strip()
        status = subprocess.run(["git", "-C", str(code), "status", "--porcelain"], check=True,
                                capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None, "kind": "tree"}
    return {"commit": commit, "dirty": bool(status.strip()), "kind": "git",
            "status": status.splitlines()}


def _environment(run_dir: Path) -> dict:
    keep = {key: value for key, value in os.environ.items()
            if key in ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "USER", "LOGNAME")}
    return {
        **keep,
        "PP1_DATA_DIR": str(run_dir / "data"),
        "PP1_CONFIG_PATH": str(run_dir / "config" / "factory.yaml"),
        "PP1_AUTO_ROBUSTNESS": "0",
        "PP1_LLM_BACKEND": "none",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }


def _run_flow(flow, *, code, golden, out, mode, calibration, anchor, core, keep_runs, python):
    run_dir = golden / "runs" / out.name / flow.name
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)
    for parent in (golden / "runs", run_dir.parent):
        parent.chmod(0o700)
    pristine = golden / "pristine"
    shutil.copytree(pristine / "data", run_dir / "data")
    shutil.copytree(pristine / "config", run_dir / "config")
    _private_tree(run_dir)
    target = out / f"{flow.name}.json"
    log = out / f"{flow.name}.log"
    command = [
        "taskset", "-c", str(core), python, "-B", str(HERE / "flows.py"),
        "--code", str(code), "--flow", flow.name, "--run-dir", str(run_dir),
        "--pristine", str(pristine), "--out", str(target), "--anchor", anchor, "--mode", mode,
    ]
    if calibration:
        command += ["--calibration", str(calibration)]
    started = time.monotonic()
    with log.open("w") as handle:
        try:
            process = subprocess.run(command, cwd=run_dir, env=_environment(run_dir),
                                     stdout=handle, stderr=subprocess.STDOUT,
                                     timeout=FLOW_TIMEOUT_S, check=False)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            exit_code = "timeout"
    wall = round(time.monotonic() - started, 1)
    entry = {"core": core, "wall_s": wall, "exit_code": exit_code}
    if exit_code == 0 and target.exists():
        written = json.loads(target.read_text())
        entry["sha256"] = written["sha256"]
        entry["status"] = "error" if written["result"].get("error") else "ok"
        if written["result"].get("error"):
            entry["error"] = written["result"]["error"]
    else:
        entry["status"] = "harness_failure"
        entry["log_tail"] = log.read_text()[-3000:] if log.exists() else ""
    if keep_runs or entry["status"] == "harness_failure":
        entry["run_dir"] = str(run_dir)
    else:
        shutil.rmtree(run_dir, ignore_errors=True)
    return entry


def _skipped(flow, out: Path) -> dict:
    result = golden_flows.canonicalize({"flow": flow.name, "group": flow.group,
                                        "skipped": True, "reason": flow.skip_reason})
    sha = golden_flows.digest(result)
    (out / f"{flow.name}.json").write_text(json.dumps(
        {"flow": flow.name, "group": flow.group, "sha256": sha, "result": result,
         "meta": {}}, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return {"status": "skipped", "sha256": sha, "reason": flow.skip_reason, "wall_s": 0.0}


def capture(args) -> int:
    golden = Path(args.golden).resolve()
    code = Path(args.code).resolve()
    out = Path(args.out).resolve()
    if not (code / "backend" / "__init__.py").exists():
        raise SystemExit(f"{code} is not a code tree (no backend/)")
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} already exists and is not empty")
    manifest = verify_pristine(golden / "pristine")
    mode = "calibrate" if args.calibrate else "deterministic"
    calibration = None
    if mode == "deterministic":
        calibration = golden / "calibration.json"
        if not calibration.exists():
            raise SystemExit(f"{calibration} missing: run a --calibrate capture first")
    selected = [flow for flow in golden_flows.FLOWS.values() if not args.fast or flow.fast]
    if args.flows:
        wanted = set(args.flows.split(","))
        unknown = wanted - set(golden_flows.FLOWS)
        if unknown:
            raise SystemExit(f"unknown flows: {sorted(unknown)}")
        selected = [flow for flow in selected if flow.name in wanted]
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o700)
    if golden in out.parents:
        out.parent.chmod(0o700)
    summary = {
        "code": str(code),
        "code_identity": _code_identity(code),
        "mode": mode,
        "fast": bool(args.fast),
        "selected": [flow.name for flow in selected],
        "calibration_sha256": _sha256(calibration) if calibration else None,
        "pristine_manifest_sha256": _sha256(golden / "pristine" / "MANIFEST.json"),
        "flow_params_sha256": _sha256(golden / "pristine" / "flow_params.json")
        if (golden / "pristine" / "flow_params.json").exists() else None,
        "harness_sha256": {name: _sha256(HERE / name) for name in ("flows.py", "capture.py")},
        "slow_factor": golden_flows.SLOW_FACTOR if mode == "deterministic" else 1.0,
        "started_at": _utc_now().isoformat(),
        "flows": {},
    }
    work = queue.Queue()
    for flow in sorted(selected, key=lambda item: (-item.weight, item.name)):
        if flow.skip_reason:
            summary["flows"][flow.name] = _skipped(flow, out)
        else:
            work.put(flow)
    cores = [int(core) for core in args.cores.split(",") if core.strip()]
    lock = threading.Lock()
    started = time.monotonic()

    def worker(core: int) -> None:
        while True:
            try:
                flow = work.get_nowait()
            except queue.Empty:
                return
            entry = _run_flow(
                flow, code=code, golden=golden, out=out, mode=mode, calibration=calibration,
                anchor=manifest["clock_anchor"], core=core, keep_runs=args.keep_runs,
                python=args.python,
            )
            with lock:
                summary["flows"][flow.name] = entry
                print(f"  {flow.name:<24} {entry['status']:<16} {entry['wall_s']:>7.1f} s"
                      f"  core {core}", flush=True)

    threads = [threading.Thread(target=worker, args=(core,)) for core in cores]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    summary["wall_s"] = round(time.monotonic() - started, 1)
    summary["finished_at"] = _utc_now().isoformat()
    summary["flows"] = dict(sorted(summary["flows"].items()))
    if mode == "calibrate":
        calls = {}
        for name in summary["flows"]:
            path = out / f"{name}.json"
            if path.exists():
                written = json.loads(path.read_text())
                calls[name] = {"calls": [
                    {key: call.get(key) for key in ("index", "candidates_evaluated",
                                                    "stop_reason", "status")}
                    for call in written["result"].get("improvement_calls") or []
                ]}
        calibration_out = {"code_identity": summary["code_identity"],
                           "captured": summary["started_at"], "flows": calls}
        (out / "calibration.json").write_text(json.dumps(calibration_out, indent=1,
                                                         sort_keys=True) + "\n")
        target = golden / "calibration.json"
        complete = not args.fast and not args.flows
        if complete and (not target.exists() or args.force_calibration):
            target.write_text(json.dumps(calibration_out, indent=1, sort_keys=True) + "\n")
            target.chmod(0o600)
            summary["calibration_written"] = str(target)
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    _private_tree(out)
    with contextlib.suppress(OSError):
        (golden / "runs" / out.name).rmdir()
    failures = [name for name, entry in summary["flows"].items()
                if entry["status"] == "harness_failure"]
    print(f"captura: {len(summary['flows'])} fluxos em {summary['wall_s']} s -> {out}")
    if failures:
        print(f"FALHA DO HARNESS: {', '.join(failures)}")
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    parser.add_argument("--build-pristine", action="store_true")
    parser.add_argument("--force", action="store_true", help="rebuild an existing pristine")
    parser.add_argument("--set-param", nargs=2, metavar=("FLOW", "JSON"))
    parser.add_argument("--archive", metavar="COMMIT")
    parser.add_argument("--repo", default=str(HERE.parents[1]))
    parser.add_argument("--code")
    parser.add_argument("--out")
    parser.add_argument("--fast", action="store_true", help="only the fast subset")
    parser.add_argument("--flows", default="", help="comma-separated flow names")
    parser.add_argument("--calibrate", action="store_true",
                        help="real budgets; records evaluation counts")
    parser.add_argument("--force-calibration", action="store_true",
                        help="overwrite <golden>/calibration.json")
    parser.add_argument("--cores", default=os.environ.get("PP1_GOLDEN_CORES", DEFAULT_CORES))
    parser.add_argument("--keep-runs", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)
    golden = Path(args.golden).resolve()
    if args.build_pristine:
        print(build_pristine(golden, args.force))
        return 0
    if args.set_param:
        set_param(golden, *args.set_param)
        return 0
    if args.archive:
        print(archive(golden, args.archive, Path(args.repo)))
        return 0
    if not (args.code and args.out):
        parser.error("--code and --out are required for a capture")
    return capture(args)


if __name__ == "__main__":
    sys.exit(main())
