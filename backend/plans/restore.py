"""Restore persisted plans into the live copilot state."""

from __future__ import annotations

import copy
from datetime import datetime, timezone

from backend.config.loader import validate_config
from backend.config.planning import (
    apply_effective_planning_config,
    enforce_machine_scope,
    synchronize_active_twin_groups,
)
from backend.config.types import (
    JIT_EARLINESS_POLICY,
    JIT_MAX_ANTICIPATION_WORKDAYS,
    JIT_WINDOW_ENFORCEMENT,
    PLANNING_POLICY_VERSION,
)
from backend.dqa import compute_trust_index
from backend.plans.serialize import (
    MODEL_VERSION,
    assert_snapshot_integrity,
    deserialize_snapshot,
    schedule_fingerprint,
    serialize_config,
    value_fingerprint,
)
from backend.scheduler.gates import authorize_application, build_gate_report
from backend.scheduler.scoring import compute_score
from backend.transform.calendars import apply_calendars
from backend.validation import strict_bool, strict_int

UTC = timezone.utc  # noqa: UP017 - Python 3.10 compatibility


def _twin_config_signature(twins: dict[str, list[str]] | None) -> tuple:
    """Return an order-independent signature for active twin definitions."""

    return tuple(
        sorted(
            (str(tool_id), tuple(sorted(str(sku) for sku in skus)))
            for tool_id, skus in (twins or {}).items()
        )
    )


def restore_plan_into_state(
    plan: dict,
    target_state,
    *,
    autosave: bool = False,
    expected_revision: int | None = None,
    approve_exceptions: bool = False,
    approval_reason: str = "",
    approval_author: str = "",
    recover_jit_blocked: bool = False,
    prefer_current_config: bool = False,
    preserve_exact: bool = False,
    recover_existing: bool = False,
    recalculate: bool = False,
) -> dict:
    """Restore a store record and recompute trust/gates with current config.

    A changed factory configuration does not silently invalidate the exact
    snapshot: the plan is restored, but its freshly computed gate report is
    returned to the planner as a warning surface. Active twin classifications
    are the exception: current factory master data always wins and a change
    forces recalculation. Startup may opt into ``recover_jit_blocked`` to
    rebuild old JIT-invalid snapshots from their source data; an explicit user
    restore still rejects them.

    Restoring never optimizes (plan-melhoria §6.6): the saved schedule is
    validated as it is and its diagnostics are returned. A snapshot that is
    incompatible with the current planning model or active twins requires an
    explicit ``recalculate=True`` request; it is never recalculated silently.
    """

    autosave = strict_bool(autosave, "autosave")
    approve_exceptions = strict_bool(approve_exceptions, "approve_exceptions")
    recover_jit_blocked = strict_bool(recover_jit_blocked, "recover_jit_blocked")
    prefer_current_config = strict_bool(prefer_current_config, "prefer_current_config")
    preserve_exact = strict_bool(preserve_exact, "preserve_exact")
    recover_existing = strict_bool(recover_existing, "recover_existing")
    recalculate = strict_bool(recalculate, "recalculate")
    if expected_revision is not None:
        expected_revision = strict_int(expected_revision, "expected_revision")
        if expected_revision != int(target_state.plan_revision):
            raise ValueError("Revisão obsoleta: o plano mudou entretanto.")

    from backend.plans.context import is_staging
    from backend.plans.transactions import run_sync_mutation

    if autosave and not is_staging():
        return run_sync_mutation(
            target_state,
            lambda: restore_plan_into_state(
                plan,
                target_state,
                autosave=True,
                expected_revision=expected_revision,
                approve_exceptions=approve_exceptions,
                approval_reason=approval_reason,
                approval_author=approval_author,
                recover_jit_blocked=recover_jit_blocked,
                prefer_current_config=prefer_current_config,
                preserve_exact=preserve_exact,
                recover_existing=recover_existing,
                recalculate=recalculate,
            ),
        )

    if target_state.config is None:
        raise ValueError("Configuração não carregada; não é possível repor o plano.")

    assert_snapshot_integrity(plan["payload"], origin=plan.get("origin"))
    restored = deserialize_snapshot(plan["payload"])
    engine_data = restored["engine_data"]
    restored_config = restored.get("config")
    snapshot_twins = (
        copy.deepcopy(restored_config.twins)
        if restored_config is not None
        else {twin.tool_id: [twin.sku_1, twin.sku_2] for twin in engine_data.twin_groups}
    )
    current_twins = copy.deepcopy(target_state.config.twins)
    twin_config_changed = _twin_config_signature(snapshot_twins) != _twin_config_signature(
        current_twins
    )
    if restored_config is not None:
        enforce_machine_scope(restored_config, engine_data, restored["result"].segments)
        restored_config.twins = copy.deepcopy(current_twins)
        restored_config.earliness_policy = JIT_EARLINESS_POLICY
        restored_config.material_release_days = JIT_MAX_ANTICIPATION_WORKDAYS
        restored_config.early_window_enforcement = JIT_WINDOW_ENFORCEMENT
        restored_config.jit_enabled = True
        # Snapshots preserve industrial decisions (shifts, OEE, resources and
        # priorities), but execution controls belong to the current planner
        # version.  Restoring these fields from an old plan previously revived
        # a 0.4 s solver budget and disabled compaction after both had been
        # upgraded in the live configuration.
        for field in (
            "global_jit_enabled",
            "global_jit_time_limit_s",
            "vns_enabled",
            "vns_block_moves_enabled",
            "vns_max_iter",
            "compact_enabled",
        ):
            setattr(
                restored_config,
                field,
                copy.deepcopy(getattr(target_state.config, field)),
            )
        config_errors = validate_config(restored_config, engine_data)
        if config_errors:
            raise ValueError("Configuração inválida no snapshot: " + "; ".join(config_errors))
    # On process startup, the persisted factory configuration is the source of
    # truth.  A plan snapshot is historical evidence and must not silently
    # roll back shifts, OEE, priorities or resource settings saved after that
    # plan was created. Explicit restores retain the other snapshot settings,
    # while active twin classifications always come from current master data.
    candidate_config = (
        copy.deepcopy(target_state.config)
        if prefer_current_config
        else restored_config or target_state.config
    )
    enforce_machine_scope(candidate_config, engine_data, restored["result"].segments)
    candidate_config.twins = copy.deepcopy(current_twins)
    config_errors = validate_config(candidate_config, engine_data)
    if config_errors:
        raise ValueError("Configuração inválida no snapshot: " + "; ".join(config_errors))
    snapshot_inputs_exact = restored.get("fingerprints", {}).get("config") == value_fingerprint(
        serialize_config(candidate_config)
    )
    if not (preserve_exact and snapshot_inputs_exact):
        synchronize_active_twin_groups(engine_data, candidate_config.twins)
        apply_effective_planning_config(engine_data, candidate_config)
        apply_calendars(engine_data, candidate_config)
        from backend.simulator.mutations import reapply_calendar_mutations

        reapply_calendar_mutations(
            engine_data,
            list(restored.get("active_mutations", [])),
            candidate_config,
        )

    result = restored["result"]
    legacy_planning_model = (
        restored.get("model_version") != MODEL_VERSION
        or restored.get("planning_policy_version") != PLANNING_POLICY_VERSION
    )
    recalculation_required = legacy_planning_model or twin_config_changed
    if recalculation_required and (preserve_exact or not recalculate):
        raise ValueError("O plano guardado exige recalculo explicito com a politica atual.")
    if recalculate and not preserve_exact:
        from backend.cpo.optimizer import optimize

        result = optimize(
            engine_data,
            mode="quick",
            config=candidate_config,
            audit=True,
        )
        recalculation_warnings = []
        if legacy_planning_model:
            recalculation_warnings.append(
                "O plano guardado usava um modelo de planeamento anterior e foi "
                "recalculado com as regras atuais."
            )
        if twin_config_changed:
            recalculation_warnings.append(
                "A configuração de peças gémeas mudou; o plano guardado foi "
                "recalculado com a lista ativa atual."
            )
        if not recalculation_required:
            recalculation_warnings.append(
                "O plano guardado foi recalculado a pedido antes de ser reposto."
            )
        result.warnings = [*recalculation_warnings, *result.warnings]
    # No hidden repair or optimization of the saved schedule: legacy setup
    # fragments, gaps or campaign placements are reported by the recomputed
    # gate below and require an explicit recalculation (plan-melhoria §6.6).
    result.score = compute_score(
        result.segments,
        result.lots,
        engine_data,
        config=candidate_config,
    )
    # Exact inputs: the same configuration, data and schedule as persisted.
    # Robustness is informational and computed after commit; persisted
    # robustness_* score keys are not carried into the live plan.
    fingerprints = restored.get("fingerprints", {})
    exact_plan_inputs = (
        fingerprints.get("config") == value_fingerprint(serialize_config(candidate_config))
        and fingerprints.get("engine_data") == value_fingerprint(engine_data)
        and fingerprints.get("schedule") == schedule_fingerprint(result.segments, result.lots)
    )
    result.gate_report = build_gate_report(
        result.segments,
        result.lots,
        result.score,
        engine_data,
        candidate_config,
    )
    from backend.scheduler.improvement import attach_improvement_summary

    if not exact_plan_inputs and not (recalculate and not preserve_exact):
        result.improvement_report = {"status": "not_evaluated", "stop_reason": "inputs_changed"}
    attach_improvement_summary(result, engine_data, candidate_config)
    recovered_from_jit = recalculate and not preserve_exact
    if recover_jit_blocked and _is_jit_only_blocked(result.gate_report):
        # Older persisted plans may predate the hard material-release rule.
        # Never revive such a schedule. Reconstruct a valid candidate from the
        # same ISOP/config instead, retaining the legacy record as audit data.
        from backend.cpo.optimizer import optimize

        result = optimize(
            engine_data,
            mode="quick",
            config=candidate_config,
            audit=True,
        )
        result.warnings = [
            "O plano guardado anterior violava a janela de material; "
            "foi recalculado antes de ser reposto.",
            *result.warnings,
        ]
        recovered_from_jit = True
    prior_approvals = list(restored.get("approvals", []))
    if recovered_from_jit or not exact_plan_inputs:
        # The approval belongs to the obsolete schedule, not its replacement.
        prior_approvals = []
    prior = prior_approvals[-1] if prior_approvals else {}
    # Startup recovery republishes an already durable plan; it is not a new
    # planning decision. Keep freshly recomputed diagnostics visible, including
    # a blocked operational gate, without making the service lose its active
    # plan after a scoring-rule upgrade.
    approval = (
        None
        if recover_existing
        else authorize_application(
            result.gate_report,
            approve_exceptions=approve_exceptions or bool(prior),
            approval_reason=approval_reason or str(prior.get("reason", "")),
            approval_author=approval_author or str(prior.get("author", "")),
        )
    )
    trust = compute_trust_index(engine_data, candidate_config)

    payload_dataset = copy.deepcopy(restored.get("dataset_info") or {})
    filename = str(payload_dataset.get("filename") or plan.get("origin") or plan["name"])
    dataset_info = {
        **payload_dataset,
        "id": str(payload_dataset.get("id") or f"plan_{plan['id']}")
        if preserve_exact
        else f"plan_{plan['id']}",
        "filename": filename,
        "uploaded_at": str(
            payload_dataset.get("uploaded_at")
            or plan.get("created_at")
            or datetime.now(UTC).replace(microsecond=0).isoformat()
        ),
        "n_ops": len(engine_data.ops),
        "n_segments": len(result.segments),
        "trust_score": trust.score,
        "trust_gate": trust.gate,
        "otd": result.score.get("otd"),
        "tardy_count": result.score.get("tardy_count"),
        "restored_plan_id": plan["id"],
    }

    # No live state is changed until validation and approval/diagnostic restore have succeeded.
    target_state.config = candidate_config
    target_state.engine_data = engine_data
    target_state.current_machine_states = list(engine_data.current_machine_states)
    target_state.saved_schedule = None
    target_state.saved_mutations = None
    target_state.saved_manual_edits = None
    target_state.saved_engine_data = None
    target_state.saved_config = None
    target_state.saved_plan_revision = None
    target_state.active_mutations = restored["active_mutations"]
    target_state.manual_edits = restored["manual_edits"]
    target_state.learning_info = restored["learning_info"]
    target_state.approvals = prior_approvals
    if approval is not None:
        target_state.approvals.append({**approval, "action": "restore"})
    target_state.plan_revision = max(
        int(target_state.plan_revision),
        int(restored.get("plan_revision", 0)),
    )
    target_state.trust_index = trust
    target_state.dataset_info = dataset_info
    target_state.update_schedule(
        result,
        plan_source="restore" if autosave else None,
        plan_note=f"Reposto de {plan['name']}" if autosave else "",
    )
    if preserve_exact:
        # Booting the same durable state does not create a new revision.
        target_state.plan_revision = int(restored.get("plan_revision", 0))
        if not exact_plan_inputs:
            target_state.plan_revision += 1
            target_state.persist_current_plan(
                name="Configuracao recuperada",
                source="auto",
                is_auto=True,
                note="Identidade atualizada apos alteracao externa da configuracao",
                allow_blocked_recovery=recover_existing,
            )
    elif autosave:
        from backend.config.loader import save_config

        save_config(candidate_config)

    return {
        "plan": {key: value for key, value in plan.items() if key != "payload"},
        "dataset": dataset_info,
        "score": target_state.score,
        "gate_report": result.gate_report,
        "improvement_report": result.improvement_report,
        "plan_revision": target_state.plan_revision,
    }


def _is_jit_only_blocked(report: dict | None) -> bool:
    """Whether a legacy snapshot can safely be rebuilt rather than restored."""

    return bool(
        report
        and report.get("apply_decision") == "blocked"
        and report.get("physical_gate_passed")
        and report.get("coverage_gate_passed")
        and report.get("jit_window_gate_passed") is False
    )
