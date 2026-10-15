"""Names of plan versions: what each committed write changed, in pt-PT.

Decisão do Luís (15/10/2026): depois de 8 movimentos manuais o planeador não
conseguiu voltar ao plano da manhã, porque todas as versões automáticas se
chamavam «Plano aplicado». Cada versão gravada passa a dizer o que mudou
(«Movido Referência X (PRM043) → 03/12 08:45», «Feriado 07/12 adicionado»,
«Recalcular plano», …). Nunca um id interno de lote.
"""

from __future__ import annotations

FALLBACK_NAME = "Plano aplicado"
UNDO_PREFIX = "Desfeito: "
RESTORE_PREFIX = "Versão reposta: "
MAX_NAME = 160


def day_month(value) -> str:
    """``2026-12-07`` / ``2026-12-07T08:45`` -> ``07/12`` (``07/12 08:45``)."""
    text = str(value or "")
    if len(text) < 10 or text[4] != "-" or text[7] != "-":
        return text
    label = f"{text[8:10]}/{text[5:7]}"
    if len(text) >= 16 and text[10] in "T ":
        label += f" {text[11:16]}"
    return label


def clock(minute) -> str:
    value = max(0, int(round(float(minute))))
    return f"{value // 60:02d}:{value % 60:02d}"


def lot_reference(lot, machine_id: str | None = None, data=None) -> str:
    """``Referência 6800016767A.10 (PRM043)``, never the internal lot id.

    A lot without its SKU takes the one of its operation in ``data``.
    """
    import copy

    from backend.scheduler.canonical import _lot_label

    if not getattr(lot, "sku", None) and data is not None:
        sku = next(
            (op.sku for op in getattr(data, "ops", None) or [] if op.id == lot.op_id), None,
        )
        if sku:
            lot = copy.copy(lot)
            lot.sku = sku
    return _lot_label(lot, machine_id)


def move_label(lot, machine_id: str, workday, start_min, data=None) -> str:
    when = day_month(str(workday)[:10])
    if start_min is not None:
        when += f" {clock(start_min)}"
    return f"Movido {lot_reference(lot, machine_id, data)} → {when}"


def release_label(lots: list, release_all: bool, data=None) -> str:
    if release_all:
        return "Todos os lotes soltos"
    references = [lot_reference(lot, data=data) for lot in lots]
    if not references:
        return "Lote fixado solto"
    if len(references) == 1:
        return f"Lote solto: {references[0]}"
    return f"Lotes soltos: {'; '.join(references)}"


def load_label(filename: str) -> str:
    return f"ISOP {filename} carregado" if filename else "ISOP carregado"


def _dates_label(singular: str, plural: str, dates: list[str], verb: str) -> str:
    dates = sorted(dates)
    if len(dates) == 1:
        return f"{singular} {day_month(dates[0])} {verb}"
    return f"{plural} {day_month(dates[0])}–{day_month(dates[-1])} {verb}s"


def _period(entry: dict) -> str:
    start = entry.get("start_at") or entry.get("from")
    end = entry.get("end_at") or entry.get("to")
    if start and end:
        return f"{day_month(start)}–{day_month(end)}"
    return f"desde {day_month(start)}" if start else ""


def _unavailability_text(entry: dict) -> str:
    category = str(entry.get("category") or "Indisponibilidade").strip()
    if entry.get("resource"):
        who = str(entry["resource"])
    else:
        count = entry.get("count")
        who = " ".join(str(entry.get(key) or "") for key in ("group", "shift")).strip()
        if count:
            who += f" ({count} {'operador' if int(count) == 1 else 'operadores'})"
    return " ".join(part for part in (category, who, _period(entry)) if part)


_UNAVAILABILITY_FIELDS = (
    "machine_unavailability", "tool_unavailability", "operator_unavailability",
)


def _unavailability_parts(before, after) -> list[str]:
    old = {
        str(entry.get("id")): entry
        for name in _UNAVAILABILITY_FIELDS for entry in getattr(before, name, None) or []
    }
    new = {
        str(entry.get("id")): entry
        for name in _UNAVAILABILITY_FIELDS for entry in getattr(after, name, None) or []
    }
    added = [new[key] for key in new if key not in old]
    removed = [old[key] for key in old if key not in new]
    changed = [new[key] for key in new if key in old and new[key] != old[key]]
    total = len(added) + len(removed) + len(changed)
    if total == 0:
        return []
    if total > 1:
        return [f"{total} indisponibilidades alteradas"]
    if added:
        return [_unavailability_text(added[0])]
    if removed:
        return [f"Retirada: {_unavailability_text(removed[0])}"]
    return [f"Alterada: {_unavailability_text(changed[0])}"]


def config_change_label(before, after) -> str | None:
    """A name for a calendar change (holidays, extra days, unavailability).

    ``None`` when nothing recognisable changed: the caller keeps its label.
    """
    if before is None or after is None:
        return None
    parts: list[str] = []
    old_holidays = {str(day) for day in getattr(before, "holidays", None) or []}
    new_holidays = {str(day) for day in getattr(after, "holidays", None) or []}
    if new_holidays - old_holidays:
        parts.append(_dates_label(
            "Feriado", "Feriados", list(new_holidays - old_holidays), "adicionado",
        ))
    if old_holidays - new_holidays:
        parts.append(_dates_label(
            "Feriado", "Feriados", list(old_holidays - new_holidays), "retirado",
        ))
    old_extra = {str(day) for day in getattr(before, "extra_workdays", None) or []}
    new_extra = {str(day) for day in getattr(after, "extra_workdays", None) or []}
    if new_extra - old_extra:
        parts.append(_dates_label(
            "Dia extra", "Dias extra", list(new_extra - old_extra), "adicionado",
        ))
    if old_extra - new_extra:
        parts.append(_dates_label(
            "Dia extra", "Dias extra", list(old_extra - new_extra), "retirado",
        ))
    parts.extend(_unavailability_parts(before, after))
    if not parts:
        return None
    return "; ".join(parts) if len(parts) <= 2 else "Calendário alterado"


def snapshot_name(history: dict | None, before_config=None, after_config=None) -> str:
    """The committed snapshot's name: the endpoint's label, else a recognised
    calendar change, else the write's own default, else «Plano aplicado»."""
    history = history or {}
    name = (
        history.get("label")
        or config_change_label(before_config, after_config)
        or history.get("default_label")
        or FALLBACK_NAME
    )
    name = " ".join(str(name).split())
    return name if len(name) <= MAX_NAME else name[: MAX_NAME - 1] + "…"
