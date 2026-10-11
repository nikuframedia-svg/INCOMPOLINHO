#!/usr/bin/env python3
"""Compare two golden-master captures (plan Passo 1b).

Usage::

  # a capture against the baseline: exit 1 on any difference
  compare.py <reference> <candidate> [--stability <golden>/stability.json]

  # self-check of the baseline (two captures of the same commit): flows that
  # do not reproduce become "equivalence-only" (só equivalência)
  compare.py --self-check <capture-a> <capture-b> \
      --write-stability <golden>/stability.json [--promote-baseline <golden>/baseline]

Only the flows the candidate captured are compared (``--fast`` captures the
fast subset). A flow is IDÊNTICO when its sha256 matches. A flow listed as
equivalence-only in ``--stability`` is EQUIVALENTE when its coarse facts
(``result.equivalence``: HTTP statuses, revision, validity, lot quantities,
late orders, OTD) match; it never justifies deleting code on its own (plan
§1b). Otherwise the structural differences are printed (path: reference ->
candidate).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MAX_VALUE_CHARS = 160


def _load(capture: Path) -> tuple[dict, dict]:
    summary = json.loads((capture / "SUMMARY.json").read_text())
    return summary, summary.get("flows") or {}


def _result(capture: Path, flow: str) -> dict | None:
    path = capture / f"{flow}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())["result"]


def _short(value) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= MAX_VALUE_CHARS else text[:MAX_VALUE_CHARS] + "…"


def structural_diff(reference, candidate, path="", out=None, limit=40):
    """Differences as ``path: reference -> candidate`` lines (first ``limit``)."""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(reference, dict) and isinstance(candidate, dict):
        for key in sorted(set(reference) | set(candidate)):
            where = f"{path}.{key}" if path else str(key)
            if key not in candidate:
                out.append(f"{where}: {_short(reference[key])} -> (ausente)")
            elif key not in reference:
                out.append(f"{where}: (ausente) -> {_short(candidate[key])}")
            else:
                structural_diff(reference[key], candidate[key], where, out, limit)
            if len(out) >= limit:
                break
        return out
    if isinstance(reference, list) and isinstance(candidate, list):
        if len(reference) != len(candidate):
            out.append(f"{path}: {len(reference)} elementos -> {len(candidate)} elementos")
        for index, (left, right) in enumerate(zip(reference, candidate)):
            label = left.get("label") if isinstance(left, dict) else None
            where = f"{path}[{index}{'=' + label if label else ''}]"
            structural_diff(left, right, where, out, limit)
            if len(out) >= limit:
                break
        return out
    if reference != candidate:
        out.append(f"{path}: {_short(reference)} -> {_short(candidate)}")
    return out


def compare(reference: Path, candidate: Path, stability: dict, max_diffs: int) -> tuple[dict, int]:
    ref_summary, ref_flows = _load(reference)
    cand_summary, cand_flows = _load(candidate)
    problems = 0
    for key, label in (("pristine_manifest_sha256", "entradas (pristine)"),
                       ("calibration_sha256", "calibração"),
                       ("flow_params_sha256", "parâmetros dos fluxos")):
        if ref_summary.get(key) != cand_summary.get(key):
            print(f"ERRO: {label} diferentes entre as capturas; não são comparáveis.")
            problems += 1
    if ref_summary.get("harness_sha256") != cand_summary.get("harness_sha256"):
        print("AVISO: o harness (flows.py/capture.py) mudou desde a referência; uma diferença"
              " pode vir do harness. Recapturar a referência com o harness novo.")
    equivalence_only = set((stability or {}).get("equivalence_only") or {})
    verdicts = {}
    for flow in cand_summary.get("selected") or sorted(cand_flows):
        ref_entry, cand_entry = ref_flows.get(flow), cand_flows.get(flow)
        if ref_entry is None:
            verdicts[flow] = ("SEM REFERÊNCIA", [])
        elif cand_entry is None or cand_entry.get("status") == "harness_failure":
            verdicts[flow] = ("FALHA DO HARNESS", [(cand_entry or {}).get("log_tail", "")[-800:]])
        elif ref_entry.get("sha256") == cand_entry.get("sha256"):
            verdicts[flow] = ("SALTADO" if cand_entry.get("status") == "skipped" else "IDÊNTICO",
                              [])
        else:
            ref_result, cand_result = _result(reference, flow), _result(candidate, flow)
            if flow in equivalence_only and ref_result and cand_result and (
                ref_result.get("equivalence") == cand_result.get("equivalence")
            ):
                verdicts[flow] = ("EQUIVALENTE", [])
            else:
                kind = "DIFERENTE (só equivalência)" if flow in equivalence_only else "DIFERENTE"
                diffs = structural_diff(
                    (ref_result or {}).get("equivalence") if flow in equivalence_only
                    else ref_result,
                    (cand_result or {}).get("equivalence") if flow in equivalence_only
                    else cand_result,
                    limit=max_diffs,
                )
                verdicts[flow] = (kind, diffs)
    for flow, (verdict, details) in verdicts.items():
        cand_entry = cand_flows.get(flow) or {}
        timing = f"{cand_entry.get('wall_s', 0):>7.1f} s" if cand_entry else ""
        print(f"  {flow:<24} {verdict:<28} {timing}")
        for line in details:
            print(f"      {line}")
        if verdict not in ("IDÊNTICO", "EQUIVALENTE", "SALTADO"):
            problems += 1
    return verdicts, problems


def self_check(first: Path, second: Path, target: Path, max_diffs: int,
               promote: Path | None) -> int:
    verdicts, _problems = compare(first, second, {}, max_diffs)
    identical = sorted(flow for flow, (verdict, _d) in verdicts.items()
                       if verdict in ("IDÊNTICO", "SALTADO"))
    equivalence_only, unstable = {}, []
    for flow, (verdict, details) in verdicts.items():
        if verdict in ("IDÊNTICO", "SALTADO"):
            continue
        equivalence_only[flow] = {"first_differences": details[:12]}
        first_result, second_result = _result(first, flow), _result(second, flow)
        if not first_result or not second_result or (
            first_result.get("equivalence") != second_result.get("equivalence")
        ):
            unstable.append(flow)
    stability = {
        "reference": str(first),
        "repeat": str(second),
        "identical": identical,
        "equivalence_only": equivalence_only,
        "unstable_even_in_equivalence": sorted(unstable),
    }
    target.write_text(json.dumps(stability, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    target.chmod(0o600)
    print(f"autoverificação: {len(identical)} idênticos, {len(equivalence_only)} só equivalência"
          f" ({', '.join(sorted(equivalence_only)) or '-'}),"
          f" {len(unstable)} instáveis mesmo em equivalência"
          f" ({', '.join(sorted(unstable)) or '-'}) -> {target}")
    if promote is not None:
        if promote.is_symlink() or promote.exists():
            promote.unlink()
        promote.symlink_to(first)
        print(f"referência: {promote} -> {first}")
    return 1 if unstable else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference", nargs="?")
    parser.add_argument("candidate", nargs="?")
    parser.add_argument("--stability", default="")
    parser.add_argument("--max-diffs", type=int, default=30)
    parser.add_argument("--self-check", nargs=2, metavar=("CAPTURE_A", "CAPTURE_B"))
    parser.add_argument("--write-stability", default="")
    parser.add_argument("--promote-baseline", default="")
    args = parser.parse_args(argv)
    if args.self_check:
        if not args.write_stability:
            parser.error("--self-check needs --write-stability")
        first, second = (Path(item).resolve() for item in args.self_check)
        promote = Path(args.promote_baseline) if args.promote_baseline else None
        return self_check(first, second, Path(args.write_stability), args.max_diffs, promote)
    if not (args.reference and args.candidate):
        parser.error("reference and candidate captures are required")
    stability = {}
    if args.stability and Path(args.stability).exists():
        stability = json.loads(Path(args.stability).read_text())
    reference = Path(args.reference).resolve()
    candidate = Path(args.candidate).resolve()
    print(f"golden master: {candidate} contra {reference}")
    _verdicts, problems = compare(reference, candidate, stability, args.max_diffs)
    print("golden master: " + ("IGUAL" if not problems else f"{problems} problema(s)"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
