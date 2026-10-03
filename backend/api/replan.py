"""Immediate-return API for long re-planning operations."""

from __future__ import annotations

import copy
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from backend.api.locks import commit_lock, plan_mutation_lock
from backend.config.loader import normalize_setup_families, validate_config
from backend.config.shifts import (
    clear_legacy_common_machine_capacity_overrides,
    normalize_shift_updates,
)
from backend.config.types import OUT_OF_SCOPE_MACHINES, MachineConfig
from backend.config.unavailability import (
    UnavailabilityConflict,
    add_unavailability_entry,
    remove_unavailability_entry,
    update_unavailability_entry,
)
from backend.copilot.state import state
from backend.plans.serialize import serialize_snapshot
from backend.plans.transactions import plan_writer
from backend.replan.jobs import canonical_replan_fingerprint, manager, replan_base_fingerprints
from backend.types import MachineInfo
from backend.validation import finite_float, strict_int

router = APIRouter(prefix="/api/data/replan-jobs", tags=["replan"])

_CALENDAR_ONLY_UPDATES = {
    "unavailability_additions",
    "unavailability_removals",
    "unavailability_updates",
}


def _unavailability_edit_effect(
    previous_kind: str,
    previous: dict,
    current_kind: str | None,
    current: dict | None,
) -> str:
    """Classify an edit as capacity-neutral, relaxing, or tightening/mixed."""

    if current is None or current_kind != previous_kind:
        return "tightens"
    try:
        previous_start = datetime.fromisoformat(str(previous.get("start_at", "")))
        current_start = datetime.fromisoformat(str(current.get("start_at", "")))
    except (TypeError, ValueError):
        return "tightens"
    previous_end_raw = str(previous.get("end_at", "") or "")
    current_end_raw = str(current.get("end_at", "") or "")
    try:
        previous_end = datetime.fromisoformat(previous_end_raw) if previous_end_raw else None
        current_end = datetime.fromisoformat(current_end_raw) if current_end_raw else None
    except ValueError:
        return "tightens"
    interval_is_subset = (
        current_start >= previous_start
        and (previous_end is None or (current_end is not None and current_end <= previous_end))
    )
    if previous_kind == "operator":
        if (
            str(previous.get("group", "")) != str(current.get("group", ""))
            or str(previous.get("shift", "")) != str(current.get("shift", ""))
        ):
            return "tightens"
        try:
            count_is_not_higher = int(current.get("count", 0)) <= int(
                previous.get("count", 0)
            )
        except (TypeError, ValueError):
            return "tightens"
        if not (interval_is_subset and count_is_not_higher):
            return "tightens"
        unchanged = (
            current_start == previous_start
            and current_end == previous_end
            and int(current.get("count", 0)) == int(previous.get("count", 0))
        )
        return "same" if unchanged else "relaxes"
    if str(previous.get("resource", "")) != str(current.get("resource", "")):
        return "tightens"
    if not interval_is_subset:
        return "tightens"
    unchanged = current_start == previous_start and current_end == previous_end
    return "same" if unchanged else "relaxes"


def _sync_active_machines(candidate, candidate_data) -> list[str]:
    """Keep inactive-machine demand visible while resolving active alternatives."""

    warnings: list[str] = []
    configured_active_ids = {
        machine_id
        for machine_id, machine in candidate.machines.items()
        if machine.active
    }
    known_engine_machines = {machine.id for machine in candidate_data.machines}
    # Legacy configurations may not list every machine imported from the ISOP.
    # The rest of the scheduler treats an unconfigured imported machine as active.
    active_machine_ids = configured_active_ids | {
        machine_id
        for machine_id in known_engine_machines
        if machine_id not in candidate.machines
    }
    for machine_id in configured_active_ids:
        if machine_id not in known_engine_machines:
            machine_cfg = candidate.machines[machine_id]
            candidate_data.machines.append(
                MachineInfo(
                    id=machine_id,
                    group=machine_cfg.group,
                    day_capacity=candidate.day_capacity_min,
                )
            )

    unschedulable_ops = []
    for op in candidate_data.ops:
        primary_active = op.m in active_machine_ids
        alt_active = bool(op.alt and op.alt in active_machine_ids)
        if not primary_active and alt_active:
            inactive_primary = op.m
            op.m = str(op.alt)
            op.alt = inactive_primary if inactive_primary in active_machine_ids else None
        elif op.alt not in active_machine_ids:
            op.alt = None
        if op.m not in active_machine_ids:
            unschedulable_ops.append(op)
    if unschedulable_ops:
        affected_ids = ", ".join(op.id for op in unschedulable_ops[:5])
        suffix = "..." if len(unschedulable_ops) > 5 else ""
        warnings.append(
            f"{len(unschedulable_ops)} operação(ões) sem máquina ativa foram "
            f"mantidas como procura não planeada: {affected_ids}{suffix}"
        )
    ops_by_id = {op.id: op for op in candidate_data.ops}
    synced_twin_groups = []
    dropped_twins = []
    for twin_group in candidate_data.twin_groups:
        first = ops_by_id.get(twin_group.op_id_1)
        second = ops_by_id.get(twin_group.op_id_2)
        if first is None or second is None:
            dropped_twins.append(twin_group)
            continue
        twin_group.machine_id = first.m
        synced_twin_groups.append(twin_group)
    candidate_data.twin_groups = synced_twin_groups
    if dropped_twins:
        warnings.append(
            f"{len(dropped_twins)} grupo(s) de peças gémeas sem máquina ativa foram excluídos."
        )
    return warnings


@router.post("")
async def start_replan(body: dict):
    if "expected_revision" not in body:
        raise HTTPException(400, "expected_revision é obrigatório.")
    try:
        expected_revision = strict_int(body["expected_revision"], "expected_revision")
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "expected_revision deve ser um inteiro.") from exc
    async with plan_mutation_lock:
        with commit_lock:
            if state.engine_data is None or state.config is None or state.dataset_info is None:
                raise HTTPException(503, "Sem plano carregado.")
            if expected_revision != state.plan_revision:
                raise HTTPException(
                    409,
                    {
                        "message": "Revisão obsoleta: o plano mudou entretanto.",
                        "current_revision": state.plan_revision,
                    },
                )
            candidate = copy.deepcopy(state.config)
            candidate_data = copy.deepcopy(state.engine_data)
            dataset_info = copy.deepcopy(state.dataset_info)
            base_revision = int(state.plan_revision)
            baseline_snapshot = serialize_snapshot(state)
    base_input_fingerprints = replan_base_fingerprints(baseline_snapshot)
    previous_day_capacity = candidate.day_capacity_min
    updates = body.get("config_updates", {})
    calendar_capacity_tightened = False
    calendar_capacity_relaxed = False
    operator_capacity_tightened = False
    if not isinstance(updates, dict):
        raise HTTPException(400, "config_updates deve ser um objeto.")
    additions = updates.get("unavailability_additions", [])
    removals = updates.get("unavailability_removals", [])
    replacements = updates.get("unavailability_updates", [])
    for field, value in (
        ("unavailability_additions", additions),
        ("unavailability_removals", removals),
        ("unavailability_updates", replacements),
    ):
        if not isinstance(value, list):
            raise HTTPException(400, f"{field} deve ser uma lista.")

    removal_ids = [str(value).strip() for value in removals]
    replacement_ids = [
        str(value.get("id", "")).strip() if isinstance(value, dict) else ""
        for value in replacements
    ]
    if any(not entry_id for entry_id in removal_ids + replacement_ids):
        raise HTTPException(400, "O ID da indisponibilidade é obrigatório.")
    targeted_ids = removal_ids + replacement_ids
    if len(targeted_ids) != len(set(targeted_ids)):
        raise HTTPException(400, "Cada indisponibilidade só pode ser alterada uma vez por pedido.")

    original_entries = {
        str(entry.get("id", "")): (kind, copy.deepcopy(entry))
        for kind, entries in (
            ("machine", candidate.machine_unavailability),
            ("tool", candidate.tool_unavailability),
            ("operator", candidate.operator_unavailability),
        )
        for entry in entries
    }
    calendar_capacity_relaxed = bool(removal_ids)
    for entry_id in removal_ids:
        removed = remove_unavailability_entry(candidate, entry_id)
        if removed is None:
            raise HTTPException(404, f"Indisponibilidade {entry_id} não existe.")
    for raw_entry in replacements:
        if not isinstance(raw_entry, dict):
            raise HTTPException(400, "Alteração de indisponibilidade inválida.")
        entry_id = str(raw_entry.get("id", "")).strip()
        next_kind = str(raw_entry.get("kind", raw_entry.get("type", ""))).lower()
        try:
            update_unavailability_entry(candidate, candidate_data, entry_id, raw_entry)
        except UnavailabilityConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        previous_kind, previous_entry = original_entries[entry_id]
        current_kind = next_kind.rstrip("s") or previous_kind
        current_entry = next(
            (
                entry
                for kind, entries in (
                    ("machine", candidate.machine_unavailability),
                    ("tool", candidate.tool_unavailability),
                    ("operator", candidate.operator_unavailability),
                )
                if kind == current_kind
                for entry in entries
                if str(entry.get("id", "")) == entry_id
            ),
            None,
        )
        edit_effect = _unavailability_edit_effect(
            previous_kind,
            previous_entry,
            current_kind,
            current_entry,
        )
        edit_tightens = edit_effect == "tightens"
        calendar_capacity_tightened = calendar_capacity_tightened or edit_tightens
        calendar_capacity_relaxed = calendar_capacity_relaxed or (
            edit_effect == "relaxes"
        )
        operator_capacity_tightened = operator_capacity_tightened or (
            edit_tightens and current_kind == "operator"
        )
    for raw_entry in additions:
        if not isinstance(raw_entry, dict):
            raise HTTPException(400, "Nova indisponibilidade inválida.")
        addition_kind = str(
            raw_entry.get("kind", raw_entry.get("type", ""))
        ).lower().rstrip("s")
        calendar_capacity_tightened = True
        operator_capacity_tightened = operator_capacity_tightened or (
            addition_kind == "operator"
        )
        try:
            add_unavailability_entry(candidate, candidate_data, raw_entry)
        except UnavailabilityConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    for key, value in updates.items():
        if key in _CALENDAR_ONLY_UPDATES:
            continue
        if key == "machine_additions":
            if not isinstance(value, list):
                raise HTTPException(400, "machine_additions deve ser uma lista.")
            for raw_machine in value:
                if not isinstance(raw_machine, dict):
                    raise HTTPException(400, "Nova máquina inválida.")
                machine_id = str(raw_machine.get("id", "")).strip().upper()
                group = str(raw_machine.get("group", "")).strip()
                active = raw_machine.get("active", True)
                if not machine_id:
                    raise HTTPException(400, "O identificador da máquina é obrigatório.")
                if machine_id in OUT_OF_SCOPE_MACHINES:
                    raise HTTPException(400, f"{machine_id} está fora do âmbito da análise.")
                if machine_id in candidate.machines:
                    raise HTTPException(400, f"Máquina {machine_id} já existe.")
                if group not in {"Grandes", "Medias"}:
                    raise HTTPException(400, f"Grupo inválido para {machine_id}.")
                if not isinstance(active, bool):
                    raise HTTPException(400, f"Estado inválido para {machine_id}.")
                candidate.machines[machine_id] = MachineConfig(
                    id=machine_id,
                    group=group,
                    active=active,
                )
                if active:
                    candidate_data.machines.append(
                        MachineInfo(
                            id=machine_id,
                            group=group,
                            day_capacity=candidate.day_capacity_min,
                        )
                    )
            continue
        if key == "tool_additions":
            if not isinstance(value, list):
                raise HTTPException(400, "tool_additions deve ser uma lista.")
            for raw_tool in value:
                if not isinstance(raw_tool, dict):
                    raise HTTPException(400, "Nova ferramenta inválida.")
                tool_id = str(raw_tool.get("id", "")).strip().upper()
                primary = str(raw_tool.get("primary", "")).strip().upper()
                alt = str(raw_tool.get("alt", "") or "").strip().upper() or None
                try:
                    setup_hours = finite_float(raw_tool.get("setup_hours", 0.5), "setup_hours")
                except (TypeError, ValueError) as exc:
                    raise HTTPException(400, "O setup deve ser indicado em horas.") from exc
                if not tool_id or not primary:
                    raise HTTPException(
                        400,
                        "A ferramenta e a máquina principal são obrigatórias.",
                    )
                if tool_id in candidate.tools:
                    raise HTTPException(400, f"Ferramenta {tool_id} já existe.")
                if primary not in candidate.machines:
                    raise HTTPException(400, f"Máquina principal {primary} não existe.")
                if alt and alt not in candidate.machines:
                    raise HTTPException(400, f"Máquina alternativa {alt} não existe.")
                if not 0 <= setup_hours <= 8:
                    raise HTTPException(400, "O setup deve estar entre 0 e 8 horas.")
                candidate.tools[tool_id] = {
                    "primary": primary,
                    "alt": alt,
                    "setup_hours": setup_hours,
                }
            continue
        if key == "machine_oee":
            if not isinstance(value, dict):
                raise HTTPException(400, "machine_oee deve ser um objeto.")
            for machine_id, oee in value.items():
                if machine_id not in candidate.machines:
                    raise HTTPException(400, f"Máquina {machine_id} não existe.")
                try:
                    candidate.machines[machine_id].oee = (
                        None if oee in (None, "") else finite_float(oee, "oee")
                    )
                except (TypeError, ValueError) as exc:
                    raise HTTPException(
                        400,
                        f"OEE inválido para {machine_id}.",
                    ) from exc
            continue
        if key == "setup_families":
            if not isinstance(value, dict):
                raise HTTPException(400, "setup_families deve ser um objeto.")
            candidate.setup_families = normalize_setup_families(value)
            continue
        if key == "machine_groups":
            if not isinstance(value, dict):
                raise HTTPException(400, "machine_groups deve ser um objeto.")
            for machine_id, group in value.items():
                if machine_id not in candidate.machines:
                    raise HTTPException(400, f"Máquina {machine_id} não existe.")
                if str(group) not in {"Grandes", "Medias"}:
                    raise HTTPException(400, f"Grupo inválido para {machine_id}.")
                candidate.machines[machine_id].group = str(group)
                for machine in candidate_data.machines:
                    if machine.id == machine_id:
                        machine.group = str(group)
            continue
        if key == "machine_active":
            if not isinstance(value, dict):
                raise HTTPException(400, "machine_active deve ser um objeto.")
            for machine_id, active in value.items():
                if machine_id not in candidate.machines:
                    raise HTTPException(400, f"Máquina {machine_id} não existe.")
                if not isinstance(active, bool):
                    raise HTTPException(
                        400,
                        f"Estado inválido para {machine_id}: usa verdadeiro ou falso.",
                    )
                candidate.machines[machine_id].active = active
            continue
        if key == "tool_updates":
            if not isinstance(value, dict):
                raise HTTPException(400, "tool_updates deve ser um objeto.")
            for tool_id, raw_update in value.items():
                if tool_id not in candidate.tools:
                    raise HTTPException(400, f"Ferramenta {tool_id} não existe.")
                if not isinstance(raw_update, dict):
                    raise HTTPException(400, f"Alteração inválida para {tool_id}.")
                tool = candidate.tools[tool_id]
                if "setup_hours" in raw_update:
                    try:
                        setup_hours = finite_float(raw_update["setup_hours"], "setup_hours")
                    except (TypeError, ValueError) as exc:
                        raise HTTPException(
                            400,
                            f"Tempo de setup inválido para {tool_id}.",
                        ) from exc
                    if not 0 <= setup_hours <= 8:
                        raise HTTPException(
                            400,
                            f"O setup de {tool_id} deve estar entre 0 e 8 horas.",
                        )
                    tool["setup_hours"] = setup_hours
                    for op in candidate_data.ops:
                        if op.t == tool_id:
                            op.sH = setup_hours
                if "alt" in raw_update:
                    alt = str(raw_update["alt"] or "").strip() or None
                    if alt and alt not in candidate.machines:
                        raise HTTPException(400, f"Máquina alternativa {alt} não existe.")
                    tool["alt"] = alt
                    for op in candidate_data.ops:
                        if op.t == tool_id:
                            op.alt = alt
            continue
        if key == "shifts":
            try:
                candidate.shifts = normalize_shift_updates(value)
                clear_legacy_common_machine_capacity_overrides(
                    candidate,
                    previous_day_capacity,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            continue
        if key != "setup_crews_by_group":
            raise HTTPException(400, f"Parâmetro desconhecido: {key}")
        if not isinstance(value, dict):
            raise HTTPException(400, "setup_crews_by_group deve ser um objeto.")
        try:
            candidate.setup_crews_by_group = {
                str(group): strict_int(count, f"setup_crews.{group}")
                for group, count in value.items()
            }
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                400,
                "As equipas de setup devem ser números inteiros.",
            ) from exc
    errors = validate_config(candidate, candidate_data)
    if errors:
        raise HTTPException(400, {"message": "Configuração inválida", "errors": errors})
    state_warnings: list[str] = []
    state_warnings.extend(_sync_active_machines(candidate, candidate_data))
    if "current_machine_states" in body:
        raise HTTPException(
            400,
            "O estado inicial manual foi removido. Replaneia sem current_machine_states.",
        )
    dataset_id = str(dataset_info["id"])
    reason = str(body.get("reason", "Replaneamento pedido pelo utilizador"))
    request_fingerprint = canonical_replan_fingerprint(
        dataset_id=dataset_id,
        base_revision=base_revision,
        base_input_fingerprints=base_input_fingerprints,
        request={
            "reason": reason,
            "config_updates": updates,
        },
    )
    job = manager.start(
        engine_data=candidate_data,
        config=candidate,
        dataset_id=dataset_id,
        base_revision=base_revision,
        reason=reason,
        dataset_info=dataset_info,
        preparation_warnings=state_warnings,
        baseline_snapshot=baseline_snapshot,
        base_input_fingerprints=base_input_fingerprints,
        prefer_unchanged_baseline=(
            bool(updates)
            and set(updates).issubset(_CALENDAR_ONLY_UPDATES)
            and not operator_capacity_tightened
            and not calendar_capacity_relaxed
        ),
        allow_unchanged_baseline_apply=(
            bool(targeted_ids)
            and not additions
            and not calendar_capacity_tightened
            and not calendar_capacity_relaxed
        ),
        reoptimize_relaxed_baseline=calendar_capacity_relaxed,
        request_fingerprint=request_fingerprint,
    )
    return {
        "status": "queued",
        "deduplicated": bool(job.get("deduplicated")),
        "job": job,
    }


@router.get("")
async def list_replans(pending: bool | None = Query(default=None)):
    if state.dataset_info is None:
        raise HTTPException(503, "Sem plano carregado.")
    dataset_id = str(state.dataset_info.get("id", ""))
    jobs = manager.list_jobs(
        dataset_id=dataset_id,
        base_revision=state.plan_revision,
        pending=pending,
    )
    return {
        "dataset_id": dataset_id,
        "base_revision": state.plan_revision,
        "jobs": jobs,
    }


@router.get("/{job_id}")
async def get_replan(job_id: str):
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(404, f"Trabalho {job_id} não existe.")
    return {"job": job}


@router.post("/{job_id}/cancel")
async def cancel_replan(job_id: str):
    async with plan_mutation_lock:
        try:
            job = manager.cancel(job_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
    return {"job": job}


@router.post("/{job_id}/apply")
@plan_writer
async def apply_replan(job_id: str, body: dict):
    if "expected_revision" not in body:
        raise HTTPException(400, "expected_revision é obrigatório.")
    try:
        expected_revision = strict_int(body["expected_revision"], "expected_revision")
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "expected_revision deve ser um inteiro.") from exc
    async with plan_mutation_lock:
        try:
            job = manager.apply(
                job_id,
                expected_revision=expected_revision,
                approve_exceptions=bool(
                    body.get(
                        "approve_exceptions",
                        body.get("confirm_delivery_risk", False),
                    )
                ),
                approval_reason=str(
                    body.get("approval_reason", body.get("reason", ""))
                ),
                approval_author=str(
                    body.get("approval_author", body.get("author", ""))
                ),
            )
        except ValueError as exc:
            raise HTTPException(
                409,
                {
                    "message": str(exc),
                    "current_revision": state.plan_revision,
                },
            ) from exc
    return {
        "status": "applied",
        "job": job,
        "plan_revision": state.plan_revision,
    }
