"""Shared validation and mutation helpers for persistent unavailability ranges."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from backend.config.loader import _normalize_unavailability

UNAVAILABILITY_ATTRS = {
    "machine": "machine_unavailability",
    "machines": "machine_unavailability",
    "tool": "tool_unavailability",
    "tools": "tool_unavailability",
    "operator": "operator_unavailability",
    "operators": "operator_unavailability",
}


class UnavailabilityConflict(ValueError):
    """Raised when a public unavailability ID is already in use."""


def add_unavailability_entry(
    config,
    engine_data,
    body: dict,
    *,
    id_factory: Callable[[], str] | None = None,
) -> dict:
    """Validate, normalize, and append one range to a detached config."""

    kind = str(body.get("kind", body.get("type", ""))).lower()
    attr = UNAVAILABILITY_ATTRS.get(kind)
    if attr is None:
        raise ValueError("kind deve ser machine, tool ou operator.")

    make_id = id_factory or (lambda: f"u_{uuid4().hex[:12]}")
    entry_id = str(body.get("id") or make_id())
    all_ids = {
        str(entry.get("id", ""))
        for name in set(UNAVAILABILITY_ATTRS.values())
        for entry in getattr(config, name)
    }
    if entry_id in all_ids:
        raise UnavailabilityConflict(f"Indisponibilidade {entry_id} já existe.")

    has_canonical = "start_at" in body or "end_at" in body
    has_legacy = "from" in body or "to" in body
    if has_canonical and has_legacy:
        raise ValueError("Usa start_at/end_at ou from/to, não ambos.")

    entry: dict = {
        "id": entry_id,
        "start_at": str(body.get("start_at", body.get("from", ""))),
        "end_at": str(body.get("end_at", body.get("to", ""))),
        "category": str(body.get("category", "Outra")),
        "reason": str(body.get("reason", "")),
    }
    if has_legacy:
        entry["from"] = str(body.get("from"))
        entry["to"] = str(body.get("to", body.get("from")))
        entry.pop("start_at", None)
        entry.pop("end_at", None)

    if attr == "operator_unavailability":
        group = str(body.get("group", ""))
        shift = str(body.get("shift", ""))
        raw_count = body.get("count", 1)
        try:
            if isinstance(raw_count, bool) or (
                isinstance(raw_count, float) and not raw_count.is_integer()
            ):
                raise ValueError
            count = int(raw_count)
        except (TypeError, ValueError) as exc:
            raise ValueError("count deve ser um inteiro >= 1.") from exc
        if count < 1:
            raise ValueError("count deve ser um inteiro >= 1.")
        if (group, shift) not in config.operators:
            raise ValueError(f"Grupo/turno {group} {shift} não existe.")
        entry.update({"group": group, "shift": shift, "count": count})
    else:
        resource = str(body.get("resource", ""))
        if attr == "machine_unavailability" and resource not in config.machines:
            raise ValueError(f"Máquina {resource} não existe.")
        known_tools = set(config.tools) | {
            str(getattr(op, "t", "")) for op in getattr(engine_data, "ops", [])
        }
        if attr == "tool_unavailability" and resource not in known_tools:
            raise ValueError(f"Ferramenta {resource} não existe.")
        entry["resource"] = resource

    normalized = _normalize_unavailability(
        [entry],
        operators=attr == "operator_unavailability",
        timezone=config.timezone,
        kind={
            "machine_unavailability": "machine",
            "tool_unavailability": "tool",
            "operator_unavailability": "operator",
        }[attr],
    )
    if not normalized:
        raise ValueError("Indisponibilidade inválida.")
    entry = normalized[0]
    getattr(config, attr).append(entry)
    return entry


def remove_unavailability_entry(config, entry_id: str) -> dict | None:
    """Remove one range from a detached config and return the removed entry."""

    for attr in (
        "machine_unavailability",
        "tool_unavailability",
        "operator_unavailability",
    ):
        entries = getattr(config, attr)
        match = next(
            (entry for entry in entries if str(entry.get("id", "")) == entry_id),
            None,
        )
        if match is not None:
            entries.remove(match)
            return match
    return None


def update_unavailability_entry(config, engine_data, entry_id: str, body: dict) -> dict:
    """Atomically replace one range while preserving its public identity."""

    location: tuple[str, int, dict] | None = None
    kind_by_attr = {
        "machine_unavailability": "machine",
        "tool_unavailability": "tool",
        "operator_unavailability": "operator",
    }
    for attr, kind in kind_by_attr.items():
        entries = getattr(config, attr)
        for index, entry in enumerate(entries):
            if str(entry.get("id", "")) == entry_id:
                location = (attr, index, entry)
                current_kind = kind
                break
        if location is not None:
            break
    if location is None:
        raise ValueError(f"Indisponibilidade {entry_id} não existe.")

    attr, index, previous = location
    replacement = dict(body)
    supplied_id = str(replacement.get("id", entry_id))
    if supplied_id != entry_id:
        raise ValueError("O ID da indisponibilidade não pode ser alterado.")
    replacement["id"] = entry_id
    replacement.setdefault("kind", current_kind)

    entries = getattr(config, attr)
    entries.pop(index)
    try:
        return add_unavailability_entry(config, engine_data, replacement)
    except Exception:
        entries.insert(index, previous)
        raise
