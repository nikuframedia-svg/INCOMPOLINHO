"""JSON-safe serialization for complete production-plan snapshots."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any

from backend.config.types import (
    PLANNING_POLICY_VERSION,
    FactoryConfig,
    MachineConfig,
    ShiftConfig,
)
from backend.scheduler.types import (
    Lot,
    OperatorAlert,
    ScheduleResult,
    Segment,
)
from backend.types import (
    ClientDemandEntry,
    CommittedSupply,
    CurrentMachineState,
    EngineData,
    EOp,
    MachineInfo,
    PlanAnchor,
    TwinGroup,
)

SNAPSHOT_VERSION = 4
MODEL_VERSION = "aps-v5"
_SUPPORTED_SNAPSHOT_VERSIONS = {1, 2, 3, SNAPSHOT_VERSION}
_PLAN_FINGERPRINT_KEYS = (
    "segments",
    "lots",
    "score",
    "gate_report",
    "active_mutations",
    "manual_edits",
    "approvals",
    "operator_alerts",
    "journal_entries",
    "solver_status",
    "feasibility",
)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    return value


def _construct(cls: type, raw: dict[str, Any]) -> Any:
    allowed = {item.name for item in fields(cls)}
    return cls(**{key: value for key, value in raw.items() if key in allowed})


def serialize_snapshot(state) -> dict[str, Any]:
    if state.engine_data is None:
        raise ValueError("Sem dados de motor para guardar no plano.")
    config_payload = serialize_config(state.config) if state.config is not None else None
    engine_payload = _jsonable(state.engine_data)
    return _finalize_snapshot(
        _jsonable(
            {
                "version": SNAPSHOT_VERSION,
                "model_version": MODEL_VERSION,
                "planning_policy_version": PLANNING_POLICY_VERSION,
                "plan_revision": int(getattr(state, "plan_revision", 0)),
                "planning_origin": planning_state_identity(state),
                "approvals": list(getattr(state, "approvals", [])),
                "fingerprints": {
                    "config": _fingerprint(config_payload),
                    "engine_data": _fingerprint(engine_payload),
                },
                "config": config_payload,
                "engine_data": engine_payload,
                "segments": state.segments,
                "lots": state.lots,
                "score": state.score,
                "warnings": state.warnings,
                "operator_alerts": state.operator_alerts or [],
                "journal_entries": state.journal_entries,
                "gate_report": state.gate_report,
                "improvement_report": getattr(state, "improvement_report", None),
                "solver_status": getattr(state, "solver_status", None),
                "feasibility": getattr(state, "feasibility", None),
                "active_mutations": state.active_mutations,
                "manual_edits": state.manual_edits,
                "learning_info": state.learning_info,
                "dataset_info": state.dataset_info,
            }
        )
    )


def serialize_result_snapshot(
    engine_data: EngineData,
    config: FactoryConfig,
    result: ScheduleResult,
    *,
    plan_revision: int,
    dataset_info: dict | None = None,
    approvals: list[dict] | None = None,
) -> dict[str, Any]:
    """Serialize a detached candidate without mutating the live state."""

    config_payload = serialize_config(config)
    engine_payload = _jsonable(engine_data)
    if result.preserved_lot_proofs is not None:
        engine_payload["preserved_lot_proofs"] = dict(result.preserved_lot_proofs)
    return _finalize_snapshot(
        _jsonable(
            {
                "version": SNAPSHOT_VERSION,
                "model_version": MODEL_VERSION,
                "planning_policy_version": PLANNING_POLICY_VERSION,
                "plan_revision": int(plan_revision),
                "approvals": approvals or [],
                "fingerprints": {
                    "config": _fingerprint(config_payload),
                    "engine_data": _fingerprint(engine_payload),
                },
                "config": config_payload,
                "engine_data": engine_payload,
                "segments": result.segments,
                "lots": result.lots,
                "score": result.score,
                "warnings": result.warnings,
                "operator_alerts": result.operator_alerts,
                "journal_entries": result.journal,
                "gate_report": result.gate_report,
                "improvement_report": result.improvement_report,
                "solver_status": result.solver_status,
                "feasibility": result.feasibility,
                "active_mutations": [],
                "manual_edits": [],
                "learning_info": None,
                "dataset_info": dataset_info,
            }
        )
    )


def _fingerprint(value: Any) -> str:
    canonical = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def value_fingerprint(value: Any) -> str:
    """Return the canonical snapshot fingerprint for one JSON-safe value."""

    return _fingerprint(value)


def schedule_fingerprint(segments: Any, lots: Any) -> str:
    """Identify the exact executable schedule (segments and lots)."""

    return _fingerprint({"segments": segments, "lots": lots})


def planning_model_identity() -> dict[str, str | int]:
    from backend.plans.manual_move import ALLOCATION_MODEL_VERSION
    from backend.scheduler.improvement import CONTRACT_VERSION, PROTECTED_CONTEXT_VERSION
    from backend.scheduler.transfer_consolidation import TRANSFER_SEARCH_VERSION

    return {
        "model": MODEL_VERSION,
        "planning_policy": PLANNING_POLICY_VERSION,
        "improvement_contract": CONTRACT_VERSION,
        "manual_allocation": ALLOCATION_MODEL_VERSION,
        "protected_context": PROTECTED_CONTEXT_VERSION,
        "transfer_search": TRANSFER_SEARCH_VERSION,
    }


def planning_state_identity(state) -> dict:
    """Exact application origin; unlike delivery comparison, omit no resources."""
    return {
        "dataset_id": str((state.dataset_info or {}).get("id", "")),
        "base_revision": int(state.plan_revision),
        "inputs": {
            "config": value_fingerprint(serialize_config(state.config) if state.config else None),
            "engine_data": value_fingerprint(state.engine_data),
        },
        "schedule": schedule_fingerprint(state.segments, state.lots),
        "mutations": value_fingerprint(state.active_mutations),
        "rules": value_fingerprint(state.rules),
        "manual_edits": value_fingerprint(state.manual_edits),
        "model": planning_model_identity(),
    }


def _plan_fingerprint(payload: dict[str, Any]) -> str:
    content = {key: payload.get(key) for key in _PLAN_FINGERPRINT_KEYS}
    # Old v4 snapshots did not store this optional evidence; keep their hashes valid.
    if "improvement_report" in payload:
        content["improvement_report"] = payload["improvement_report"]
    if "planning_origin" in payload:
        content["planning_origin"] = payload["planning_origin"]
    return _fingerprint(content)


def planning_input_fingerprints(
    engine_data: EngineData,
    config: FactoryConfig | None,
) -> dict[str, str]:
    """Return stable fingerprints for comparing detached planning inputs."""

    engine_payload = _jsonable(engine_data)
    referenced_machines = {
        machine_id
        for op in engine_payload.get("ops", [])
        for machine_id in (op.get("m"), op.get("alt"))
        if machine_id
    }
    # Replan preparation materialises active, config-only machines in
    # EngineData. A machine with no associated operation cannot change the
    # candidate and must not disable the delivery floor against the baseline.
    engine_payload["machines"] = sorted(
        (
            machine
            for machine in engine_payload.get("machines", [])
            if machine.get("id") in referenced_machines
        ),
        key=lambda machine: str(machine.get("id", "")),
    )
    return {
        "config": _fingerprint(serialize_config(config) if config is not None else None),
        "engine_data": _fingerprint(engine_payload),
        "planning_policy": PLANNING_POLICY_VERSION,
    }


def _dataset_fingerprint(engine_payload: dict[str, Any]) -> str:
    """Identify the source data independently from calculated plan segments."""

    return _fingerprint(
        {
            "workdays": engine_payload.get("workdays", []),
            "n_days": engine_payload.get("n_days", 0),
            "ops": [
                {
                    key: op.get(key)
                    for key in (
                        "id",
                        "sku",
                        "client",
                        "designation",
                        "m",
                        "t",
                        "pH",
                        "eco_lot",
                        "stk",
                        "backlog",
                        "wip",
                        "d",
                    )
                }
                for op in engine_payload.get("ops", [])
            ],
            "client_demands": engine_payload.get("client_demands", {}),
        }
    )


def _finalize_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach self-verifying metadata without masking a stale dataset header."""

    engine_payload = payload.get("engine_data") or {}
    dataset_info = dict(payload.get("dataset_info") or {})
    actual_n_ops = len(engine_payload.get("ops", []))
    recorded_n_ops = dataset_info.get("n_ops")
    if recorded_n_ops is not None and int(recorded_n_ops) != actual_n_ops:
        raise ValueError(
            "Snapshot incoerente: os metadados indicam "
            f"{recorded_n_ops} operações, mas o motor contém {actual_n_ops}."
        )
    if dataset_info:
        dataset_info["n_ops"] = actual_n_ops
        dataset_info.setdefault(
            "source_fingerprint",
            _dataset_fingerprint(engine_payload),
        )
        payload["dataset_info"] = dataset_info
    payload["dataset_fingerprint"] = _dataset_fingerprint(engine_payload)
    payload["fingerprints"] = {
        "config": _fingerprint(payload.get("config")),
        "engine_data": _fingerprint(engine_payload),
        "schedule": schedule_fingerprint(
            payload.get("segments", []), payload.get("lots", [])
        ),
        "plan": _plan_fingerprint(payload),
    }
    return payload


def snapshot_integrity_errors(
    payload: dict[str, Any],
    *,
    origin: str | None = None,
) -> list[str]:
    """Return reasons why a persisted snapshot cannot be trusted."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload inválido"]
    try:
        version = int(payload.get("version", 0))
    except (TypeError, ValueError):
        return ["versão inválida"]
    if version not in _SUPPORTED_SNAPSHOT_VERSIONS:
        errors.append(f"versão não suportada: {version}")

    engine_payload = payload.get("engine_data")
    if not isinstance(engine_payload, dict):
        errors.append("dados do motor ausentes")
        return errors

    if version >= 2:
        fingerprints = payload.get("fingerprints")
        if not isinstance(fingerprints, dict):
            errors.append("fingerprints ausentes")
        else:
            expected_config = _fingerprint(payload.get("config"))
            expected_engine = _fingerprint(engine_payload)
            if fingerprints.get("config") != expected_config:
                errors.append("fingerprint da configuração não confere")
            if fingerprints.get("engine_data") != expected_engine:
                errors.append("fingerprint dos dados do motor não confere")
            if version >= 4:
                expected_schedule = schedule_fingerprint(
                    payload.get("segments", []), payload.get("lots", [])
                )
                expected_plan = _plan_fingerprint(payload)
                if fingerprints.get("schedule") != expected_schedule:
                    errors.append("fingerprint do plano executável não confere")
                if fingerprints.get("plan") != expected_plan:
                    errors.append("fingerprint do conteúdo do plano não confere")

        stored_dataset_fingerprint = payload.get("dataset_fingerprint")
        if stored_dataset_fingerprint and stored_dataset_fingerprint != _dataset_fingerprint(
            engine_payload
        ):
            errors.append("fingerprint do conjunto de dados não confere")

    dataset_info = payload.get("dataset_info") or {}
    if isinstance(dataset_info, dict):
        recorded_n_ops = dataset_info.get("n_ops")
        actual_n_ops = len(engine_payload.get("ops", []))
        if recorded_n_ops is not None:
            try:
                if int(recorded_n_ops) != actual_n_ops:
                    errors.append(
                        f"metadados indicam {recorded_n_ops} operações, motor contém {actual_n_ops}"
                    )
            except (TypeError, ValueError):
                errors.append("número de operações inválido nos metadados")

        payload_filename = str(dataset_info.get("filename") or "").strip()
        if origin and payload_filename:
            if Path(origin).name != Path(payload_filename).name:
                errors.append("ficheiro de origem não corresponde ao snapshot")
    elif dataset_info:
        errors.append("metadados do conjunto de dados inválidos")

    lot_ids = {
        str(item.get("id"))
        for item in payload.get("lots", [])
        if isinstance(item, dict) and item.get("id") is not None
    }
    segment_lot_ids = {
        str(item.get("lot_id"))
        for item in payload.get("segments", [])
        if isinstance(item, dict) and item.get("lot_id") is not None
    }
    unknown_lots = segment_lot_ids - lot_ids
    if unknown_lots:
        errors.append(f"{len(unknown_lots)} lote(s) de segmento inexistentes")
    return errors


def assert_snapshot_integrity(
    payload: dict[str, Any],
    *,
    origin: str | None = None,
) -> None:
    errors = snapshot_integrity_errors(payload, origin=origin)
    if errors:
        raise ValueError("Snapshot inconsistente: " + "; ".join(errors))


def serialize_config(config: FactoryConfig) -> dict[str, Any]:
    """Serialize tuple-keyed factory config without losing group/shift keys."""

    raw = asdict(config)
    raw["operators"] = {
        f"{group}|{shift}": count for (group, shift), count in config.operators.items()
    }
    return _jsonable(raw)


def deserialize_config(raw: dict[str, Any] | None) -> FactoryConfig | None:
    if not raw:
        return None
    # Number normalization must not alter the snapshot covered by fingerprints.
    raw = copy.deepcopy(raw)
    values = dict(raw)
    values["shifts"] = [_construct(ShiftConfig, item) for item in raw.get("shifts", [])]
    values["machines"] = {
        machine_id: _construct(MachineConfig, item)
        for machine_id, item in raw.get("machines", {}).items()
    }
    operators: dict[tuple[str, str], int] = {}
    for key, count in raw.get("operators", {}).items():
        parts = str(key).split("|", 1)
        if len(parts) == 2:
            from backend.validation import strict_int

            operators[(parts[0], parts[1])] = strict_int(count, f"operators.{key}")
    if operators:
        values["operators"] = operators
    from backend.config.loader import normalize_config_numbers

    config = _construct(FactoryConfig, values)
    normalize_config_numbers(config)
    return config


def serialize_simulation_snapshot(
    state,
    simulation,
    mutations: list[dict],
    *,
    baseline_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a persistent scenario without changing the active plan."""

    payload = (
        copy.deepcopy(baseline_payload)
        if baseline_payload is not None
        else serialize_snapshot(state)
    )
    payload.update(
        {
            "config": (
                serialize_config(simulation.mutated_config)
                if getattr(simulation, "mutated_config", None) is not None
                else payload.get("config")
            ),
            "engine_data": _jsonable(getattr(simulation, "mutated_data", state.engine_data)),
            "segments": _jsonable(simulation.segments),
            "lots": _jsonable(simulation.lots),
            "score": _jsonable(simulation.score),
            "warnings": _jsonable(getattr(simulation, "warnings", [])),
            "operator_alerts": _jsonable(
                getattr(simulation, "operator_alerts", [])
            ),
            "journal_entries": None,
            "gate_report": _jsonable(simulation.gate_report),
            "improvement_report": _jsonable(getattr(simulation, "improvement_report", None)),
            "active_mutations": _jsonable(mutations),
            "manual_edits": [],
            # An approval belongs to the exact production plan on which it was
            # recorded. A detached what-if candidate must be approved afresh.
            "approvals": [],
        }
    )
    return _finalize_snapshot(payload)


def deserialize_engine_data(raw: dict[str, Any]) -> EngineData:
    client_demands = {
        op_id: [_construct(ClientDemandEntry, entry) for entry in entries]
        for op_id, entries in raw.get("client_demands", {}).items()
    }
    values = dict(raw)
    values["ops"] = [_construct(EOp, item) for item in raw.get("ops", [])]
    values["machines"] = [_construct(MachineInfo, item) for item in raw.get("machines", [])]
    values["twin_groups"] = [_construct(TwinGroup, item) for item in raw.get("twin_groups", [])]
    values["client_demands"] = client_demands
    values["machine_blocked_days"] = {
        resource: set(days) for resource, days in raw.get("machine_blocked_days", {}).items()
    }
    values["tool_blocked_days"] = {
        resource: set(days) for resource, days in raw.get("tool_blocked_days", {}).items()
    }
    values["current_machine_states"] = [
        _construct(CurrentMachineState, item) for item in raw.get("current_machine_states", [])
    ]
    values["committed_supplies"] = [
        _construct(CommittedSupply, item) for item in raw.get("committed_supplies", [])
    ]
    values["plan_anchors"] = [_construct(PlanAnchor, item) for item in raw.get("plan_anchors", [])]
    return _construct(EngineData, values)


def _restore_twin_outputs(values: dict[str, Any]) -> dict[str, Any]:
    restored = dict(values)
    if restored.get("twin_outputs") is not None:
        restored["twin_outputs"] = [tuple(item) for item in restored["twin_outputs"]]
    return restored


def deserialize_plan_core(
    payload: dict[str, Any],
) -> tuple[FactoryConfig | None, EngineData, list[Segment], list[Lot]]:
    """Restore the production inputs without unrelated display/audit metadata."""
    assert_snapshot_integrity(payload)
    version = int(payload.get("version", 0))
    if version not in _SUPPORTED_SNAPSHOT_VERSIONS:
        raise ValueError(f"Versão de snapshot não suportada: {version}.")

    engine_data = deserialize_engine_data(payload["engine_data"])
    segments = [
        _construct(Segment, _restore_twin_outputs(item)) for item in payload.get("segments", [])
    ]
    lots = [_construct(Lot, _restore_twin_outputs(item)) for item in payload.get("lots", [])]
    sku_by_op = {op.id: op.sku for op in engine_data.ops}
    for lot in lots:
        if not lot.sku:
            lot.sku = sku_by_op.get(lot.op_id, "")
    return deserialize_config(payload.get("config")), engine_data, segments, lots


def deserialize_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    config, engine_data, segments, lots = deserialize_plan_core(payload)
    version = int(payload.get("version", 0))
    alerts = [_construct(OperatorAlert, item) for item in payload.get("operator_alerts", [])]
    result = ScheduleResult(
        segments=segments,
        lots=lots,
        score=dict(payload.get("score", {})),
        time_ms=0,
        warnings=list(payload.get("warnings", [])),
        operator_alerts=alerts,
        audit_trail=None,
        journal=payload.get("journal_entries"),
        gate_report=copy.deepcopy(payload.get("gate_report")),
        improvement_report=copy.deepcopy(payload.get("improvement_report")),
        solver_status=payload.get("solver_status"),
        feasibility=payload.get("feasibility"),
        preserved_lot_proofs=dict(engine_data.preserved_lot_proofs),
    )
    return {
        "config": config,
        "engine_data": engine_data,
        "result": result,
        "active_mutations": list(payload.get("active_mutations", [])),
        "manual_edits": list(payload.get("manual_edits", [])),
        "learning_info": payload.get("learning_info"),
        "dataset_info": payload.get("dataset_info"),
        "plan_revision": int(payload.get("plan_revision", 0)),
        "approvals": list(payload.get("approvals", [])),
        "fingerprints": dict(payload.get("fingerprints", {})),
        "model_version": str(payload.get("model_version", "aps-v1")),
        "planning_policy_version": str(
            payload.get("planning_policy_version", "legacy-expedition-release")
        ),
        "migrated_from_version": version if version < SNAPSHOT_VERSION else None,
    }
