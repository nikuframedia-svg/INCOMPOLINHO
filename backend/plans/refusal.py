"""One refusal format: what was refused and its concrete causes.

Decision of 15/10/2026 (Luís, after the manual-move tests at Incompol): a
refused change never reaches the planner as a bare count ("Plano inválido:
1 conflito.") or as a raw browser alert. Every refusal that comes from the
physical validation carries ``causes``: short pt-PT sentences built from the
validator's own conflicts, with day, time and reference (never the internal
lot id), naming the lots the planner pinned by hand (manual edits). The
validator's conflicts were already computed; this module only stops them from
being thrown away.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import HTTPException

MAX_CAUSES = 5
LOG_CAUSES = 3
# Quantity and ISOP-contract checks: listed after the physical conflicts
# (machine, tool, setup crew, operators, calendar), which say why a change
# does not fit. Stable sort: otherwise the validator's order is kept.
_BOOKKEEPING_KINDS = frozenset({
    "source_contract", "source_missing_quantity", "source_overproduced_quantity",
    "source_overproduced_qty",
    "missing_lots", "missing_quantity", "unexpected_lots", "duplicate_production",
    "duplicate_twin_output", "twin_output_mismatch",
})


def _clock(minute: Any) -> str | None:
    try:
        value = int(round(float(minute)))
    except (TypeError, ValueError):
        return None
    value = max(0, min(value, 24 * 60))
    return f"{value // 60:02d}:{value % 60:02d}"


def _anchor_starts(data) -> dict[str, str]:
    """``{lot_id: "03/12 17:30"}`` of the lots pinned by a manual edit."""

    starts: dict[str, str] = {}
    for anchor in getattr(data, "plan_anchors", None) or []:
        lot_id = getattr(anchor, "lot_id", None)
        start_at = getattr(anchor, "start_at", None)
        if not lot_id:
            continue
        text = ""
        if start_at is not None:
            raw = str(start_at)
            # "2026-12-03T17:30" -> "03/12 17:30"
            if len(raw) >= 16 and raw[4] == "-" and raw[10] in "T ":
                text = f"{raw[8:10]}/{raw[5:7]} {raw[11:16]}"
        starts[str(lot_id)] = text
    return starts


def _lot_text(lot_id: Any, lots_by_id: dict) -> str | None:
    """``Referência 8718696125 (PRM042)``; ``None`` for an unknown lot.

    Same wording as ``canonical._lot_label``; a snapshot lot (dict) is read
    the same way, so a job can use its stored baseline.
    """

    lot = lots_by_id.get(str(lot_id)) if lot_id else None
    if lot is None:
        return None
    if isinstance(lot, dict):
        outputs = lot.get("twin_outputs") or []
        sku, op_id, machine = lot.get("sku"), lot.get("op_id"), lot.get("machine_id")
    else:
        outputs = getattr(lot, "twin_outputs", None) or []
        sku, op_id = getattr(lot, "sku", None), getattr(lot, "op_id", None)
        machine = getattr(lot, "machine_id", None)
    references = list(dict.fromkeys(
        str(output[1] or output[0]) for output in outputs if len(output) >= 2
    )) or [str(sku or op_id or "")]
    reference = " + ".join(item for item in references if item)
    if not reference:
        return None
    return f"Referência {reference}" + (f" ({machine})" if machine else "")


def _where(violation: dict, message: str, data, lots_by_id: dict) -> str:
    """`` — dia 51 (03/12), 20:48–23:50, Referência X (PRM043)``: what the message lacks."""

    from backend.scheduler.validation import day_label

    parts: list[str] = []
    day = violation.get("day_idx")
    if day is not None and "dia " not in message:
        try:
            parts.append(day_label(int(day), data))
        except (TypeError, ValueError):
            pass
    start, end = _clock(violation.get("start_min")), _clock(violation.get("end_min"))
    if start and end and start not in message:
        parts.append(f"{start}–{end}")
    lot = _lot_text(violation.get("lot_id"), lots_by_id)
    if lot and lot.split(" (")[0].removeprefix("Referência ") not in message:
        parts.append(lot)
    return f" — {', '.join(parts)}" if parts else ""


def violation_cause(
    violation: dict,
    data=None,
    pinned: dict[str, str] | None = None,
    lots_by_id: dict | None = None,
    subject: str | None = None,
) -> str:
    """One conflict as a plain sentence, naming lots pinned by hand.

    ``subject``: the lot being changed (a requested move); it is the
    planner's request, not an earlier manual change, so it is never named
    as one.
    """

    lots_by_id = lots_by_id or {}
    message = str(violation.get("message") or "").strip().rstrip(".")
    if not message:
        machine = str(violation.get("machine_id") or "").strip()
        message = f"Conflito na {machine}" if machine else "Conflito no plano"
    sentence = message + _where(violation, message, data, lots_by_id)
    pinned = pinned if pinned is not None else _anchor_starts(data)
    other = violation.get("other") if isinstance(violation.get("other"), dict) else {}
    # A reservation (``frozen._install_frozen_reservations``) names its lot.
    holder = (
        violation.get("unavailability")
        if isinstance(violation.get("unavailability"), dict) else {}
    )
    own = str(violation.get("lot_id") or "")
    for lot_id in dict.fromkeys(
        str(item)
        for item in (own, other.get("lot_id"), holder.get("lot_id"))
        if item
    ):
        if lot_id not in pinned or lot_id == subject:
            continue
        when = pinned[lot_id]
        if lot_id == own:
            # The conflicting lot is itself a manual change: say so once, never
            # that it "clashes" with itself; a broken pin already says it.
            if violation.get("kind") != "plan_anchor":
                sentence += "; este lote é uma alteração manual" + (
                    f" (fixado para {when})" if when else ""
                )
            continue
        label = _lot_text(lot_id, lots_by_id)
        sentence += (
            "; choca com a alteração manual "
            + (f"da {label}" if label else "de um lote")
            + (f" (fixada para {when})" if when else "")
        )
    return sentence + "."


def _lots_by_id(lots) -> dict:
    return {
        str(lot.get("id") if isinstance(lot, dict) else getattr(lot, "id", "")): lot
        for lot in lots or []
    }


def refusal_causes(
    violations: Iterable[dict] | None,
    data=None,
    *,
    lots=None,
    subject: str | None = None,
    limit: int = MAX_CAUSES,
) -> list[str]:
    """Distinct causes in validator order, at most ``limit`` (+ remainder)."""

    pinned = _anchor_starts(data)
    lots_by_id = _lots_by_id(lots)
    causes: list[str] = []
    total = 0
    ordered = sorted(
        (item for item in violations or [] if isinstance(item, dict)),
        key=lambda item: item.get("kind") in _BOOKKEEPING_KINDS,
    )
    distinct: set[str] = set()
    for violation in ordered:
        cause = violation_cause(violation, data, pinned, lots_by_id, subject)
        if cause in distinct:
            continue
        distinct.add(cause)
        total += 1
        if len(causes) < limit:
            causes.append(cause)
    if total > len(causes):
        extra = total - len(causes)
        causes.append(f"… e mais {extra} {'conflito' if extra == 1 else 'conflitos'}.")
    return causes


def violations_of(exc: BaseException | None) -> list[dict]:
    violations = getattr(exc, "violations", None) or []
    return [item for item in violations if isinstance(item, dict)]


def causes_for_log(exc_or_violations, data=None, lots=None) -> str:
    """First causes on one line, for the server log (never only the count)."""

    violations = (
        exc_or_violations if isinstance(exc_or_violations, list)
        else violations_of(exc_or_violations)
    )
    return " | ".join(refusal_causes(violations, data, lots=lots, limit=LOG_CAUSES))


def refusal_detail(
    exc: BaseException,
    *,
    data=None,
    lots=None,
    message: str | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    """``{code, message, causes[, violations]}`` for an HTTP or job response."""

    violations = violations_of(exc)
    detail: dict[str, Any] = {
        "code": code or getattr(exc, "code", None) or ("invalid_plan" if violations else "refused"),
        "message": message if message is not None else str(exc),
        "causes": (
            refusal_causes(violations, data, lots=lots)
            or list(getattr(exc, "causes", None) or [])
        ),
    }
    if violations:
        detail["violations"] = violations
    return detail


def refusal_http(status: int, exc: BaseException) -> HTTPException:
    """The HTTP refusal for ``exc``: structured when it carries conflicts.

    A plain error keeps its plain-string detail, exactly as before.
    """
    from fastapi import HTTPException

    if violations_of(exc) or getattr(exc, "causes", None):
        from backend.copilot.state import state

        return HTTPException(
            status, refusal_detail(exc, data=state.engine_data, lots=state.lots),
        )
    return HTTPException(status, str(exc))
