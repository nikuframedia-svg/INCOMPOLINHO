"""Validation and projection of the observed machine state at day 0."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.config.types import FactoryConfig
from backend.types import CommittedSupply, CurrentMachineState, EngineData

VALID_STATES = {"idle", "producing", "setup", "trial", "down"}

_ALIASES = {
    "livre": "idle",
    "a produzir": "producing",
    "produzir": "producing",
    "produção": "producing",
    "setup": "setup",
    "ensaio": "trial",
    "avariada": "down",
    "avaria": "down",
}


def all_machines_free(data: EngineData) -> list[CurrentMachineState]:
    return [
        CurrentMachineState(machine_id=machine.id, status="idle")
        for machine in data.machines
    ]


def validate_current_states(
    raw_states: list[dict[str, Any]],
    data: EngineData,
    config: FactoryConfig,
) -> tuple[list[CurrentMachineState], list[str]]:
    if not isinstance(raw_states, list):
        raise ValueError("O estado atual das máquinas deve ser uma lista.")

    active = {machine.id for machine in data.machines}
    seen: set[str] = set()
    occupied_tools: dict[str, str] = {}
    states: list[CurrentMachineState] = []
    warnings: list[str] = []
    timezone = ZoneInfo(config.timezone)
    horizon_start = _horizon_start(data, config, timezone)
    ops_by_sku = {}
    for op in data.ops:
        ops_by_sku.setdefault(op.sku, []).append(op)

    for position, raw in enumerate(raw_states, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Estado inválido na posição {position}.")
        machine_id = str(raw.get("machine_id", raw.get("machine", ""))).strip()
        status_text = str(raw.get("status", raw.get("state", ""))).strip().lower()
        status = _ALIASES.get(status_text, status_text)
        if machine_id not in active:
            raise ValueError(f"Máquina ativa desconhecida: {machine_id or '(vazia)'}")
        if machine_id in seen:
            raise ValueError(f"Estado repetido para a máquina {machine_id}")
        if status not in VALID_STATES:
            raise ValueError(f"{machine_id}: estado inválido")
        seen.add(machine_id)

        sku = str(raw.get("sku") or "").strip() or None
        tool_id = str(raw.get("tool_id", raw.get("tool")) or "").strip() or None
        expected_end = (
            str(raw.get("expected_end", raw.get("expected_end_at")) or "").strip()
            or None
        )
        remaining_raw = raw.get("remaining_qty", raw.get("quantity_remaining"))
        remaining_qty = None
        if remaining_raw not in (None, ""):
            try:
                remaining_qty = int(remaining_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{machine_id}: quantidade restante inválida") from exc

        if status == "producing":
            if not sku or not tool_id or remaining_qty is None or remaining_qty <= 0:
                raise ValueError(
                    f"{machine_id}: produção exige referência, ferramenta e quantidade restante"
                )
            if not expected_end:
                raise ValueError(f"{machine_id}: indica a hora prevista de fim")
            candidates = [
                op
                for op in ops_by_sku.get(sku, [])
                if op.t == tool_id and machine_id in {op.m, op.alt}
            ]
            if not candidates:
                raise ValueError(
                    f"{machine_id}: {sku}/{tool_id} não é uma combinação compatível no ISOP"
                )
            op = candidates[0]
            end = _parse_timestamp(expected_end, timezone, machine_id)
            if end <= horizon_start:
                raise ValueError(
                    f"{machine_id}: a hora prevista de fim tem de ser posterior "
                    "ao início do horizonte"
                )
            if data.workdays:
                informed_min = max(1.0, (end - horizon_start).total_seconds() / 60)
                calculated_min = remaining_qty / max(0.0001, op.pH * op.oee) * 60
                if abs(informed_min - calculated_min) > max(30, calculated_min * 0.2):
                    warnings.append(
                        f"{machine_id}: a hora prevista difere da duração calculada "
                        f"por Peças/H e OEE ({calculated_min:.0f} min)."
                    )
        elif status in {"setup", "trial"}:
            if not expected_end:
                raise ValueError(f"{machine_id}: indica a hora prevista de fim")
            if not tool_id:
                raise ValueError(f"{machine_id}: {status} exige ferramenta")
            if _parse_timestamp(expected_end, timezone, machine_id) <= horizon_start:
                raise ValueError(
                    f"{machine_id}: a hora prevista de fim tem de ser posterior "
                    "ao início do horizonte"
                )
        elif status == "down" and expected_end:
            if _parse_timestamp(expected_end, timezone, machine_id) <= horizon_start:
                raise ValueError(
                    f"{machine_id}: a hora prevista de fim tem de ser posterior "
                    "ao início do horizonte"
                )

        if status in {"producing", "setup", "trial"} and tool_id:
            previous_machine = occupied_tools.get(tool_id)
            if previous_machine is not None:
                raise ValueError(
                    f"Ferramenta {tool_id} indicada simultaneamente em "
                    f"{previous_machine} e {machine_id}"
                )
            occupied_tools[tool_id] = machine_id

        states.append(
            CurrentMachineState(
                machine_id=machine_id,
                status=status,  # type: ignore[arg-type]
                sku=sku,
                tool_id=tool_id,
                remaining_qty=remaining_qty,
                expected_end=expected_end,
                note=str(raw.get("note", "")),
            )
        )

    missing = sorted(active - seen)
    if missing:
        raise ValueError("Falta indicar o estado de: " + ", ".join(missing))
    return states, warnings


def _parse_timestamp(value: str, timezone: ZoneInfo, machine_id: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{machine_id}: data/hora prevista inválida") from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone)
    return result.astimezone(timezone)


def _horizon_start(
    data: EngineData,
    config: FactoryConfig,
    timezone: ZoneInfo,
) -> datetime:
    if not data.workdays:
        raise ValueError("O estado atual exige um horizonte com datas")
    return datetime.fromisoformat(str(data.workdays[0])[:10]).replace(
        hour=config.shift_a_start // 60,
        minute=config.shift_a_start % 60,
        tzinfo=timezone,
    )


def _available_day(data: EngineData, available_at: str) -> int:
    eta_date = date.fromisoformat(available_at[:10])
    for day_idx, day_text in enumerate(data.workdays):
        if date.fromisoformat(str(day_text)[:10]) >= eta_date:
            return day_idx
    return data.n_days


def apply_current_states(
    data: EngineData,
    states: list[CurrentMachineState],
) -> None:
    """Record current occupancy and future supply without erasing demand."""

    data.current_machine_states = list(states)
    data.committed_supplies = []
    ops_by_sku: dict[str, list[Any]] = {}
    for op in data.ops:
        ops_by_sku.setdefault(op.sku, []).append(op)
    for state in states:
        if state.status != "producing" or not state.sku or not state.remaining_qty:
            continue
        candidates = [
            op
            for op in ops_by_sku.get(state.sku, [])
            if (not state.tool_id or op.t == state.tool_id)
            and state.machine_id in {op.m, op.alt}
        ]
        if not candidates:
            continue
        if not state.expected_end or not state.tool_id:
            continue
        op = candidates[0]
        data.committed_supplies.append(
            CommittedSupply(
                op_id=op.id,
                sku=op.sku,
                qty=int(state.remaining_qty),
                available_at=state.expected_end,
                available_day=_available_day(data, state.expected_end),
                machine_id=state.machine_id,
                tool_id=state.tool_id,
            )
        )


def serialize_current_states(states: list[CurrentMachineState]) -> list[dict[str, Any]]:
    return [asdict(item) for item in states]
