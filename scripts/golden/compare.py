#!/usr/bin/env python3
"""Compare two golden-master captures (plan Passo 1b).

Usage::

  # a capture against the baseline: exit 1 on any difference
  compare.py <reference> <candidate> [--stability <golden>/stability.json]
      [--allow-subset] [--allow-harness-change]

  # self-check of the baseline (two captures of the same commit): flows that
  # do not reproduce become "equivalence-only" (só equivalência)
  compare.py --self-check <capture-a> <capture-b> \
      --write-stability <golden>/stability.json [--promote-baseline <golden>/baseline]

Exit codes: 0 every reference flow compared and equal; 1 any problem; 3 no
problem but incomplete (a declared subset, ``--allow-subset``: not enough to
publish).

Checks, each a failure:

* inputs (pristine manifest, calibration, flow parameters) differ: the
  captures are not comparable;
* the harness that made the captures differs (``flows.py``, ``capture.py``,
  ``compare.py``, ``gate.sh``): a difference could come from the harness.
  ``--allow-harness-change`` makes it a warning, for a deliberate harness
  change (which then needs a new baseline);
* a reference flow the candidate did not capture (EM FALTA), unless the
  candidate is a declared subset (``--fast``/``--flows``), its harness still
  knows the flow and ``--allow-subset`` is given (NÃO CAPTURADO, incomplete);
* a candidate flow with no reference (SEM REFERÊNCIA), or whose run is not a
  golden capture (FALHA DO HARNESS: crash, timeout, uncalibrated
  ``improve_plan`` call);
* the ``improve_plan`` calls (site and occurrence) differ from the
  reference's (CHAMADAS DE MELHORIA MUDARAM): the evaluation caps are given
  per call site, so the plans are no longer comparable call by call;
* the sha256 differs (DIFERENTE). A flow listed as equivalence-only in
  ``--stability`` is EQUIVALENTE when its coarse facts
  (``result.equivalence``: HTTP statuses, revision, validity, lot
  quantities, late orders, OTD) match; it never justifies deleting code on
  its own (plan §1b). The structural differences are printed
  (path: reference -> candidate).

The self-check compares two full captures of the same commit with the same
inputs and harness. It promotes the first one to ``--promote-baseline`` (and
writes ``--write-stability``) only when nothing is wrong and no flow is
unstable even in equivalence; otherwise it only writes ``STABILITY.json``
next to the first capture, and exits 1.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MAX_VALUE_CHARS = 160
# Listed first: what the flow did, then the database it left.
FIRST_KEYS = ("steps", "improvement_calls", "error", "db")
_PLACEHOLDER = re.compile(r"<id-\d+>")
EXIT_OK, EXIT_PROBLEMS, EXIT_INCOMPLETE = 0, 1, 3
OK_VERDICTS = ("IDÊNTICO", "EQUIVALENTE", "SALTADO")
INPUT_KEYS = (("pristine_manifest_sha256", "entradas (pristine)"),
              ("calibration_sha256", "calibração"),
              ("flow_params_sha256", "parâmetros dos fluxos"))


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


def _key_order(key) -> tuple:
    return (FIRST_KEYS.index(key) if key in FIRST_KEYS else len(FIRST_KEYS), str(key))


def structural_diff(reference, candidate, path="", out=None, limit=40):
    """Differences as ``path: reference -> candidate`` lines (first ``limit``).

    Only for reading: the verdict is the sha256. Random identifiers are
    numbered ``<id-N>`` in order of first appearance, so one change shifts
    the numbers of everything after it; the listing treats any two
    placeholders as equal, to show the real differences first. The steps are
    listed before the database."""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(reference, dict) and isinstance(candidate, dict):
        for key in sorted(set(reference) | set(candidate), key=_key_order):
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
    if isinstance(reference, str) and isinstance(candidate, str):
        if _PLACEHOLDER.sub("<id>", reference) == _PLACEHOLDER.sub("<id>", candidate):
            return out
    if reference != candidate:
        out.append(f"{path}: {_short(reference)} -> {_short(candidate)}")
    return out


def _call_sites(result: dict | None) -> list[str]:
    return [f"{call.get('site')}#{call.get('occurrence')}"
            for call in (result or {}).get("improvement_calls") or []]


def _is_subset(summary: dict) -> bool:
    return bool(summary.get("fast") or summary.get("flows_filter"))


def summary_problems(ref_summary: dict, cand_summary: dict, *,
                     allow_harness_change: bool) -> tuple[list[str], list[str]]:
    """(errors, warnings) about the two captures as a whole."""
    errors, warnings = [], []
    for key, label in INPUT_KEYS:
        if ref_summary.get(key) != cand_summary.get(key):
            errors.append(f"{label} diferentes entre as capturas; não são comparáveis.")
    ref_harness = ref_summary.get("harness_sha256") or {}
    cand_harness = cand_summary.get("harness_sha256") or {}
    changed = sorted(name for name in set(ref_harness) | set(cand_harness)
                     if ref_harness.get(name) != cand_harness.get(name))
    if changed:
        message = (f"o harness mudou desde a referência ({', '.join(changed)}); uma diferença"
                   " pode vir do harness.")
        if allow_harness_change:
            warnings.append(message + " Permitido (--allow-harness-change): recapturar a"
                                      " referência com o harness novo.")
        else:
            errors.append(message + " Recapturar a referência com o harness novo, ou"
                                    " --allow-harness-change para uma mudança deliberada.")
    if ref_summary.get("mode") != cand_summary.get("mode"):
        errors.append(f"modos diferentes: {ref_summary.get('mode')} -> {cand_summary.get('mode')}")
    if ref_summary.get("site_aliases") or cand_summary.get("site_aliases"):
        warnings.append(f"aliases de chamadores: {cand_summary.get('site_aliases') or []}")
    return errors, warnings


def compare(reference: Path, candidate: Path, stability: dict, max_diffs: int, *,
            allow_subset: bool = False, allow_harness_change: bool = False,
            quiet: bool = False) -> tuple[dict, int, int, list[str]]:
    """Returns (verdicts, problems, incomplete, summary errors)."""
    ref_summary, ref_flows = _load(reference)
    cand_summary, cand_flows = _load(candidate)
    errors, warnings = summary_problems(ref_summary, cand_summary,
                                        allow_harness_change=allow_harness_change)
    if not quiet:
        for message in errors:
            print(f"ERRO: {message}")
        for message in warnings:
            print(f"AVISO: {message}")
    problems, incomplete = len(errors), 0
    equivalence_only = set((stability or {}).get("equivalence_only") or {})
    registry = set(cand_summary.get("registry") or cand_summary.get("selected") or cand_flows)
    subset = _is_subset(cand_summary)
    names = sorted(set(ref_flows) | set(cand_summary.get("selected") or ()) | set(cand_flows))
    verdicts = {}
    for flow in names:
        ref_entry, cand_entry = ref_flows.get(flow), cand_flows.get(flow)
        if cand_entry is None:
            if allow_subset and subset and flow in registry:
                verdicts[flow] = ("NÃO CAPTURADO", [])
            else:
                why = ("o harness do candidato já não tem este fluxo" if flow not in registry
                       else "o candidato não o capturou")
                verdicts[flow] = ("EM FALTA", [why])
        elif ref_entry is None:
            verdicts[flow] = ("SEM REFERÊNCIA", [])
        elif cand_entry.get("status") == "harness_failure":
            details = list(cand_entry.get("harness_errors") or [])
            if not details:
                details = [(cand_entry.get("log_tail") or "")[-800:]]
            verdicts[flow] = ("FALHA DO HARNESS", details)
        elif ref_entry.get("sha256") == cand_entry.get("sha256"):
            verdicts[flow] = ("SALTADO" if cand_entry.get("status") == "skipped" else "IDÊNTICO",
                              [])
        else:
            ref_result, cand_result = _result(reference, flow), _result(candidate, flow)
            ref_sites, cand_sites = _call_sites(ref_result), _call_sites(cand_result)
            if ref_sites != cand_sites:
                verdicts[flow] = ("CHAMADAS DE MELHORIA MUDARAM", [
                    f"improve_plan: {', '.join(ref_sites) or 'nenhuma'} ->"
                    f" {', '.join(cand_sites) or 'nenhuma'}",
                    *structural_diff(ref_result, cand_result, limit=max_diffs)])
            elif flow in equivalence_only and ref_result and cand_result and (
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
        if not quiet:
            print(f"  {flow:<26} {verdict:<30} {timing}")
            for line in details:
                print(f"      {line}")
        if verdict == "NÃO CAPTURADO":
            incomplete += 1
        elif verdict not in OK_VERDICTS:
            problems += 1
    return verdicts, problems, incomplete, errors


def _promotion_refusals(first: Path, second: Path, errors: list[str], unstable: list[str],
                        verdicts: dict) -> list[str]:
    reasons = []
    first_summary, _ = _load(first)
    second_summary, _ = _load(second)
    for label, summary in (("A", first_summary), ("B", second_summary)):
        if summary.get("mode") != "deterministic":
            reasons.append(f"captura {label} não é determinística")
        if _is_subset(summary):
            reasons.append(f"captura {label} é um subconjunto (--fast/--flows)")
        if summary.get("legacy_index_caps"):
            reasons.append(f"captura {label} usou limites por ordem (migração)")
        if summary.get("site_aliases"):
            reasons.append(f"captura {label} usou aliases de chamadores")
        identity = summary.get("code_identity") or {}
        if identity.get("dirty") is not False or not identity.get("commit"):
            reasons.append(f"captura {label}: código sem commit identificado ou com alterações")
    if (first_summary.get("code_identity") or {}).get("commit") != (
            second_summary.get("code_identity") or {}).get("commit"):
        reasons.append("as duas capturas são de commits diferentes")
    if set(first_summary.get("registry") or ()) != set(first_summary.get("flows") or {}):
        reasons.append("a captura A não tem todos os fluxos do harness")
    bad = sorted(flow for flow, (verdict, _d) in verdicts.items()
                 if verdict in ("EM FALTA", "SEM REFERÊNCIA", "FALHA DO HARNESS",
                                "CHAMADAS DE MELHORIA MUDARAM", "NÃO CAPTURADO"))
    if bad:
        reasons.append(f"fluxos sem comparação válida: {', '.join(bad)}")
    reasons += [f"não comparáveis: {message}" for message in errors]
    if unstable:
        reasons.append(f"instáveis mesmo em equivalência: {', '.join(unstable)}")
    return reasons


def self_check(first: Path, second: Path, target: Path, max_diffs: int,
               promote: Path | None) -> int:
    verdicts, _problems, _incomplete, errors = compare(first, second, {}, max_diffs)
    identical = sorted(flow for flow, (verdict, _d) in verdicts.items()
                       if verdict in ("IDÊNTICO", "SALTADO"))
    equivalence_only, unstable = {}, []
    for flow, (verdict, details) in verdicts.items():
        if verdict in ("IDÊNTICO", "SALTADO"):
            continue
        equivalence_only[flow] = {"verdict": verdict, "first_differences": details[:12]}
        first_result, second_result = _result(first, flow), _result(second, flow)
        if not first_result or not second_result or (
            first_result.get("equivalence") != second_result.get("equivalence")
        ):
            unstable.append(flow)
    refusals = _promotion_refusals(first, second, errors, sorted(unstable), verdicts)
    stability = {
        "reference": str(first),
        "repeat": str(second),
        "identical": identical,
        "equivalence_only": equivalence_only,
        "unstable_even_in_equivalence": sorted(unstable),
        "summary_errors": errors,
        "promotable": not refusals,
        "refusals": refusals,
    }
    text = json.dumps(stability, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    local = first / "STABILITY.json"
    local.write_text(text)
    local.chmod(0o600)
    print(f"autoverificação: {len(identical)} idênticos, {len(equivalence_only)} só equivalência"
          f" ({', '.join(sorted(equivalence_only)) or '-'}),"
          f" {len(unstable)} instáveis mesmo em equivalência"
          f" ({', '.join(sorted(unstable)) or '-'}) -> {local}")
    if refusals:
        print("NÃO PROMOVIDA a referência:")
        for reason in refusals:
            print(f"  - {reason}")
        return EXIT_PROBLEMS
    target.write_text(text)
    target.chmod(0o600)
    print(f"estabilidade: {target}")
    if promote is not None:
        if promote.is_symlink() or promote.exists():
            promote.unlink()
        promote.symlink_to(first)
        print(f"referência: {promote} -> {first}")
    return EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference", nargs="?")
    parser.add_argument("candidate", nargs="?")
    parser.add_argument("--stability", default="")
    parser.add_argument("--max-diffs", type=int, default=30)
    parser.add_argument("--allow-subset", action="store_true",
                        help="a declared subset (--fast/--flows) ends INCOMPLETO (exit 3)")
    parser.add_argument("--allow-harness-change", action="store_true",
                        help="a different harness is a warning instead of a failure")
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
    if args.stability:
        path = Path(args.stability)
        if not path.exists():
            print(f"ERRO: {path} não existe")
            return EXIT_PROBLEMS
        stability = json.loads(path.read_text())
    reference = Path(args.reference).resolve()
    candidate = Path(args.candidate).resolve()
    print(f"golden master: {candidate} contra {reference}")
    _verdicts, problems, incomplete, _errors = compare(
        reference, candidate, stability, args.max_diffs, allow_subset=args.allow_subset,
        allow_harness_change=args.allow_harness_change)
    if problems:
        print(f"golden master: {problems} problema(s)")
        return EXIT_PROBLEMS
    if incomplete:
        print(f"golden master: INCOMPLETO ({incomplete} fluxo(s) da referência não capturados;"
              " igual no que foi capturado)")
        return EXIT_INCOMPLETE
    print("golden master: IGUAL")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
