#!/usr/bin/env python3
"""Real rehearsal step of the publication gate (plan, safety rule 2).

The reference code (the golden baseline's code tree) and the candidate run
the same actions on fresh copies of the pristine production state, with real
budgets and the real clock (``run.sh`` + ``rehearse.py``): «Recalcular
plano», the PRM031 breakdown (full rebuild), the small breakdown (PRM031
shift A on 19/10, local repair) and a Gantt move. Each action runs in its own
process; the reference and the candidate of one action run at the same time,
one core each, so both see the same machine load.

The move is the golden master's applied F4 move (``F4_manual_move.applied``
in the private ``<pristine>/flow_params.json``), so the rehearsal measures a
move that is applied; without it ``rehearse.py`` picks lots itself, and on
revision 124 none of its picks is accepted.

Verdict (exit 0 OK, 1 FALHOU; the last line starts with ``ensaio:``):

* every run finishes (no ``FATAL``);
* the candidate has the same outcome as the reference (HTTP and job
  statuses, the replan source, which move attempt was applied);
* time: candidate <= reference x (1 + ``--max-slowdown``) + ``--slack-s``
  for every action (the slack absorbs sub-second noise of short actions);
* every request of the candidate's recalculation finishes under
  ``--recalc-limit-s`` (the 60 s deadline of the screen).

One run is not a p95 (AGENTS §7): a failure here asks for a repeat and a
look at the timings, not for a conclusion.

Usage::

  gate_rehearsal.py --reference <code> --candidate <code> \
      --pristine <golden>/pristine --out <dir> \
      [--actions recalc,outage31,outageshift,move] [--cores 0,2,4,6]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ACTIONS = "recalc,outage31,outageshift,move"
DEFAULT_CORES = "0,2,4,6"  # P-cores (i5-13500), one hyper-thread each
RUN_TIMEOUT_S = 1800
LIVE_TREE = Path(os.environ.get("PP1_LIVE_TREE", "/home/luis/projects/INCOMPOLINHO")).resolve()


def _duration(action: str, result: dict) -> float | None:
    if action == "move":
        attempts = result.get("attempts") or []
        if not attempts:
            return None
        return round(sum(float(item.get("total_s") or item.get("preview_s") or 0.0)
                         for item in attempts), 2)
    value = result.get("total_s")
    return float(value) if value is not None else None


def _outcome(action: str, result: dict):
    if action == "recalc":
        return [result.get("first_status"), result.get("second_status")]
    if action == "move":
        return [[item.get("lot_id"), item.get("status"), item.get("apply_status")]
                for item in result.get("attempts") or []]
    return [result.get("start_status"), result.get("status"), result.get("apply_status"),
            result.get("selected_source")]


def _move_option(pristine: Path) -> list[str]:
    """``--move LOT,DAY,START`` from the golden master's applied F4 move."""
    path = pristine / "flow_params.json"
    if not path.exists():
        return []
    applied = (json.loads(path.read_text()).get("F4_manual_move") or {}).get("applied")
    if not applied:
        return []
    return ["--move", f"{applied['lot_id']},{int(applied['target_day'])},"
                      f"{int(applied['target_start_min'])}"]


def _run(code: Path, tag: str, action: str, core: int, pristine: Path, out: Path,
         keep: bool) -> dict:
    command = ["bash", str(HERE / "run.sh"), str(pristine), str(code), tag, action, str(core),
               str(out)]
    if action == "move":
        command += _move_option(pristine)
    try:
        exit_code = subprocess.run(command, timeout=RUN_TIMEOUT_S, check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                                   ).returncode
    except subprocess.TimeoutExpired:
        exit_code = "timeout"
    finally:
        if not keep:
            shutil.rmtree(out / f"rt_{tag}", ignore_errors=True)
    path = out / f"{tag}.json"
    if not path.exists():
        return {"exit": exit_code, "fatal": "sem resultado"}
    data = json.loads(path.read_text())
    if "FATAL" in data:
        return {"exit": exit_code, "fatal": data["FATAL"]}
    result = data.get(action) or {}
    return {"exit": exit_code, "result": result, "startup_s": data.get("startup_s")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reference", required=True, help="reference code tree")
    parser.add_argument("--candidate", required=True, help="candidate code tree")
    parser.add_argument("--pristine", required=True, help="pristine copy (data/, config/)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--actions", default=DEFAULT_ACTIONS)
    parser.add_argument("--cores", default=os.environ.get("PP1_REHEARSAL_CORES", DEFAULT_CORES))
    parser.add_argument("--max-slowdown", type=float, default=0.10)
    parser.add_argument("--slack-s", type=float, default=1.0)
    parser.add_argument("--recalc-limit-s", type=float, default=60.0)
    parser.add_argument("--keep-runs", action="store_true", help="keep the runtime copies")
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    if out == LIVE_TREE or LIVE_TREE in out.parents:
        raise SystemExit(f"{out} fica dentro da árvore viva")
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o700)
    trees = {"referencia": Path(args.reference).resolve(),
             "candidato": Path(args.candidate).resolve()}
    for tree in trees.values():
        if not (tree / "backend" / "__init__.py").exists():
            raise SystemExit(f"{tree} is not a code tree (no backend/)")
    actions = [item for item in args.actions.split(",") if item]
    cores = [int(core) for core in args.cores.split(",") if core.strip()]
    if len(cores) < 2:
        raise SystemExit("--cores needs at least two cores (reference and candidate together)")
    pairs_per_wave = len(cores) // 2
    runs: dict[tuple[str, str], dict] = {}
    for start in range(0, len(actions), pairs_per_wave):
        wave = actions[start:start + pairs_per_wave]
        threads = []
        for index, action in enumerate(wave):
            for offset, (name, tree) in enumerate(trees.items()):
                core = cores[2 * index + offset]

                def work(name=name, tree=tree, action=action, core=core):
                    runs[(name, action)] = _run(tree, f"{name}-{action}", action, core,
                                                Path(args.pristine).resolve(), out,
                                                args.keep_runs)

                threads.append(threading.Thread(target=work))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    failures, rows = [], []
    for action in actions:
        reference, candidate = runs[("referencia", action)], runs[("candidato", action)]
        row = {"action": action}
        for name, run in (("referencia", reference), ("candidato", candidate)):
            if run.get("fatal"):
                failures.append(f"{action}: {name} não terminou ({run['fatal'][:200]})")
        if reference.get("fatal") or candidate.get("fatal"):
            rows.append(row)
            continue
        ref_result, cand_result = reference["result"], candidate["result"]
        row["reference_s"] = _duration(action, ref_result)
        row["candidate_s"] = _duration(action, cand_result)
        row["reference_outcome"] = _outcome(action, ref_result)
        row["candidate_outcome"] = _outcome(action, cand_result)
        if row["reference_outcome"] != row["candidate_outcome"]:
            failures.append(f"{action}: resultado diferente {row['reference_outcome']} ->"
                            f" {row['candidate_outcome']}")
        if row["reference_s"] is None or row["candidate_s"] is None:
            failures.append(f"{action}: sem tempo medido")
        else:
            limit = row["reference_s"] * (1 + args.max_slowdown) + args.slack_s
            row["limit_s"] = round(limit, 2)
            if row["candidate_s"] > limit:
                failures.append(f"{action}: {row['candidate_s']} s > {row['limit_s']} s"
                                f" (referência {row['reference_s']} s +"
                                f" {args.max_slowdown:.0%} + {args.slack_s} s)")
        if action == "recalc":
            requests = [value for value in (cand_result.get("first_s"),
                                            cand_result.get("second_s")) if value is not None]
            row["candidate_requests_s"] = requests
            slow = [value for value in requests if value >= args.recalc_limit_s]
            if slow:
                failures.append(f"recalc: pedido com {max(slow)} s (limite"
                                f" {args.recalc_limit_s} s)")
        rows.append(row)

    report = {"reference": str(trees["referencia"]), "candidate": str(trees["candidato"]),
              "thresholds": {"max_slowdown": args.max_slowdown, "slack_s": args.slack_s,
                             "recalc_limit_s": args.recalc_limit_s},
              "rows": rows, "failures": failures}
    target = out / "REHEARSAL.json"
    target.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str) + "\n")
    target.chmod(0o600)
    for row in rows:
        print(f"  {row['action']:<12} referência {row.get('reference_s')} s"
              f"  candidato {row.get('candidate_s')} s  limite {row.get('limit_s')} s")
    for failure in failures:
        print(f"  FALHA: {failure}")
    times = ", ".join(f"{row['action']} {row.get('candidate_s')}/{row.get('reference_s')} s"
                      for row in rows)
    print(f"ensaio: {'OK' if not failures else 'FALHOU'} ({times}) -> {target}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
