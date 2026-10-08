"""Detached planning mutations with a recoverable YAML/snapshot commit."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import logging
import os
import tempfile
from dataclasses import fields
from functools import wraps
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool

from backend.api.locks import commit_lock, plan_mutation_lock
from backend.planning_control import planning_checkpoint, planning_scope
from backend.plans.context import is_staging, stage_state
from backend.plans.serialize import (
    planning_state_identity as input_identity,
)
from backend.plans.serialize import (
    serialize_config,
    serialize_snapshot,
    value_fingerprint,
)
from backend.validation import strict_bool, strict_int

logger = logging.getLogger(__name__)
_SERVICES = {"plans_store", "audit_store"}
_APPROVAL_FIELDS = {
    "approve_exceptions",
    "approval_reason",
    "approval_author",
    "confirm_delivery_risk",
}


def clone_state(state):
    from backend.copilot.state import CopilotState

    with commit_lock:
        return CopilotState(
            **{
                item.name: (
                    getattr(state, item.name)
                    if item.name in _SERVICES
                    else copy.deepcopy(getattr(state, item.name))
                )
                for item in fields(CopilotState)
            }
        )


def _config_path() -> Path:
    from backend.config.loader import DEFAULT_CONFIG_PATH

    return Path(DEFAULT_CONFIG_PATH).resolve()


def _rules_path() -> Path:
    from backend.copilot.state import _STATE_PATH

    return Path(_STATE_PATH).resolve()


def _file_identity() -> dict:
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        for path in (_config_path(), _rules_path())
    }


def _atomic_text(path: Path, text: str | None) -> None:
    from backend.runtime_guard import assert_writable

    assert_writable(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        path.unlink(missing_ok=True)
        _sync_directory(path.parent)
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _sync_directory(path: Path) -> None:
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _prepare_files(config, config_path, files):
    """All replacement files reach durable storage before any live rename."""
    from backend.config.loader import save_config
    from backend.runtime_guard import assert_writable

    prepared = []
    try:
        entries = [(Path(entry["path"]), entry["new_text"]) for entry in files]
        if config_path is not None:
            entries.insert(0, (config_path, None))
        for target, text in entries:
            assert_writable(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.prepared-")
            os.close(fd)
            temporary = Path(name)
            prepared.append((target, temporary))
            if target == config_path:
                save_config(config, str(temporary))
            else:
                _atomic_text(temporary, text)
        return prepared
    except BaseException:
        for _, temporary in prepared:
            temporary.unlink(missing_ok=True)
        raise


def recover_pending_mutations(store) -> None:
    """Run before loading configuration; a committed receipt always wins."""
    with commit_lock:
        for journal in store.pending_mutations():
            if journal.get("config_changed"):
                _atomic_text(Path(journal["config_path"]), journal.get("old_config_text"))
            for entry in journal.get("files", []):
                _atomic_text(Path(entry["path"]), entry.get("old_text"))
            store.abort_mutation(journal["id"])


def _receipt(store, operation_id, fingerprint):
    receipt = store.mutation_receipt(operation_id)
    if receipt is not None and receipt["fingerprint"] != fingerprint:
        raise HTTPException(
            409, {"code": "different_input", "message": "O pedido identifica outra alteracao."}
        )
    if receipt is not None and receipt["status"] == "committed":
        return receipt
    return None


def _failed_result(response) -> bool:
    value = response[0] if isinstance(response, tuple) and response else response
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return False
    return isinstance(value, dict) and bool(value.get("error") or value.get("erro"))


def _commit(
    state, staged, origin, file_identity, operation_id, fingerprint, response,
    validators, callbacks,
    *, recalculate_from_start=False,
):
    with commit_lock:
        store = state.get_plans_store()
        receipt = _receipt(store, operation_id, fingerprint)
        if receipt is not None:
            return receipt["response"]
        planning_checkpoint()
        if input_identity(state) != origin or _file_identity() != file_identity:
            raise HTTPException(
                409,
                {
                    "code": "stale_revision",
                    "message": "O plano ou a configuracao mudou durante o calculo.",
                    "current_revision": state.plan_revision,
                },
            )
        for validate in validators:
            try:
                validate()
            except ValueError as exc:
                raise HTTPException(
                    409,
                    {"message": str(exc), "current_revision": state.plan_revision},
                ) from exc
            planning_checkpoint()
        if _failed_result(response):
            return response
        if staged.plan_revision == state.plan_revision and input_identity(staged) == origin:
            return response
        if (staged.gate_report or {}).get("apply_decision") == "blocked":
            raise HTTPException(
                409, {"message": "O plano esta bloqueado.", "gate_report": staged.gate_report}
            )
        staged.plan_revision = state.plan_revision + 1
        if isinstance(response, dict):
            response["plan_revision"] = staged.plan_revision
        payload = serialize_snapshot(staged) if staged.engine_data is not None else None
        response_json = jsonable_encoder(response)
        old_config = serialize_config(state.config) if state.config else None
        new_config = serialize_config(staged.config) if staged.config else None
        config_changed = old_config != new_config
        path = _config_path()
        files = []
        if state.rules != staged.rules:
            rules_path = _rules_path()
            files.append(
                {
                    "path": str(rules_path),
                    "old_text": rules_path.read_text(encoding="utf-8")
                    if rules_path.exists()
                    else None,
                    "new_text": json.dumps(
                        {"rules": staged.rules, "plan_revision": staged.plan_revision},
                        ensure_ascii=False,
                        indent=2,
                    ),
                }
            )
        journal = {
            "config_path": str(path),
            "config_changed": config_changed,
            "old_config_text": path.read_text(encoding="utf-8") if path.exists() else None,
            "old_config": old_config,
            "new_config": new_config,
            "files": files,
            "old_active_snapshot": store.runtime_identity()["snapshot_id"],
            "origin": origin,
            "plan_revision": staged.plan_revision,
            "recalculate_from_start": recalculate_from_start,
        }
        planning_checkpoint()
        store.prepare_mutation(operation_id, fingerprint, journal)
        prepared = []
        try:
            prepared = _prepare_files(staged.config, path if config_changed else None, files)
            for target, temporary in prepared:
                os.replace(temporary, target)
                _sync_directory(target.parent)
            planning_checkpoint()
            scope = {"recalculate_from_start": True} if recalculate_from_start else {}
            store.commit_mutation(operation_id, payload, response_json, source="auto", **scope)
        except BaseException:
            # A lost acknowledgement after COMMIT is not a failed operation.
            committed = _receipt(store, operation_id, fingerprint)
            if committed is None:
                if config_changed:
                    _atomic_text(path, journal["old_config_text"])
                for entry in files:
                    _atomic_text(Path(entry["path"]), entry["old_text"])
                store.abort_mutation(operation_id)
                raise
        finally:
            for _, temporary in prepared:
                temporary.unlink(missing_ok=True)
        object.__setattr__(state, "__dict__", object.__getattribute__(staged, "__dict__").copy())
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.exception(
                    "Post-commit projection failed for %s; durable receipt retained", operation_id
                )
        snapshot = _capture_robustness(state, operation_id)
    # Off the commit lock: other commits never wait on the analysis bookkeeping.
    _submit_robustness(snapshot, operation_id)
    return response


def _capture_robustness(state, operation_id):
    """Detached image of the published revision; it can never fail a commit."""
    try:
        from backend.risk.jobs import capture_auto_snapshot

        return capture_auto_snapshot(state)
    except Exception:
        logger.exception("Automatic robustness snapshot failed after %s", operation_id)
        return None


def _submit_robustness(snapshot, operation_id) -> None:
    """Queue the informational analysis; it can never fail a commit."""
    if snapshot is None:
        return
    try:
        from backend.risk.jobs import submit_auto_snapshot

        submit_auto_snapshot(snapshot)
    except Exception:
        logger.exception("Automatic robustness job not started after %s", operation_id)


def _planning_budget(mode):
    from backend.cpo.optimizer import MODE_CONFIG

    mode = "normal" if mode == "smart" else mode
    if mode not in MODE_CONFIG:
        raise ValueError(f"Unknown mode: {mode}. Use: {list(MODE_CONFIG)}")
    return float(MODE_CONFIG[mode]["time_budget_s"])


def run_sync_mutation(
    state, fn, *, operation_id=None, request_fingerprint=None, planning_mode="normal",
):
    """Synchronous adapter for executors; API writers use the async adapter."""
    if is_staging():
        return fn()
    operation_id = operation_id or uuid4().hex
    fingerprint = request_fingerprint or value_fingerprint(operation_id)
    with commit_lock:
        store = state.get_plans_store()
        receipt = _receipt(store, operation_id, fingerprint)
        if receipt is not None:
            return receipt["response"]
        if store.pending_mutations():
            raise HTTPException(
                503, "Existe uma gravacao interrompida por recuperar. Reinicia o servidor."
            )
        origin, file_identity = input_identity(state), _file_identity()
        staged = clone_state(state)
    # Check until the durable boundary, never turn its late acknowledgement into failure.
    with planning_scope(timeout_s=_planning_budget(planning_mode), check_on_exit=False):
        with stage_state(state, staged) as context:
            try:
                response = fn()
            finally:
                planning_checkpoint()
        return _commit(
            state, staged, origin, file_identity, operation_id, fingerprint, response,
            context.validators, context.callbacks,
        )


def plan_writer(fn=None, *, recalculate_from_start=False):
    """Use existing handlers on isolated state; serialize only capture/commit."""
    if fn is None:
        return lambda handler: plan_writer(handler, recalculate_from_start=recalculate_from_start)
    signature = inspect.signature(fn, eval_str=True)

    @wraps(fn)
    async def wrapped(*args, **kwargs):
        if is_staging():
            return await fn(*args, **kwargs)
        from backend.copilot.state import state as default_state

        state = fn.__globals__.get("state", default_state)
        arguments = signature.bind(*args, **kwargs).arguments
        encoded = jsonable_encoder(arguments)
        body = next(
            (value for key, value in encoded.items() if key in {"body", "request", "updates"}), {}
        )
        request_body = copy.deepcopy(body)
        try:
            for key in ("approve_exceptions", "confirm_delivery_risk", "recalculate"):
                if key in body:
                    strict_bool(body[key], key)
            if "expected_revision" in body:
                strict_int(body["expected_revision"], "expected_revision")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        operation_id = str(
            body.get("request_id")
            or (
                f"replan:{encoded['job_id']}"
                if fn.__name__ == "apply_replan"
                else f"manual:{body['preview_job_id']}"
                if body.get("preview_job_id")
                else f"{fn.__name__}:{body['candidate_id']}"
                if body.get("candidate_id")
                else uuid4().hex
            )
        )
        for value in encoded.values():
            if isinstance(value, dict):
                for key in _APPROVAL_FIELDS | {"request_id"}:
                    value.pop(key, None)
        fingerprint = value_fingerprint({"action": fn.__name__, "arguments": encoded})
        preview_parameters = copy.deepcopy(encoded)
        for value in preview_parameters.values():
            if isinstance(value, dict):
                value.pop("candidate_id", None)
        preview_kind = f"recompute:{fn.__module__}.{fn.__name__}"
        async with plan_mutation_lock:
            with commit_lock:
                store = state.get_plans_store()
                receipt = _receipt(store, operation_id, fingerprint)
                if receipt is not None:
                    return receipt["response"]
                if store.pending_mutations():
                    raise HTTPException(
                        503, "Existe uma gravacao interrompida por recuperar. Reinicia o servidor."
                    )
                origin, file_identity = input_identity(state), _file_identity()
                staged = clone_state(state)

        def calculate():
            from backend.plans.candidates import PreparedPlanWrite, previews
            from backend.scheduler.gates import authorize_application

            candidate = previews.get_prepared_write(
                request_body.get("candidate_id"), preview_kind, origin, preview_parameters,
            )
            if candidate is not None:
                with candidate.lock:
                    prepared = copy.deepcopy(candidate.result)
                if prepared.file_identity != file_identity:
                    raise HTTPException(409, {
                        "code": "stale_preview",
                        "message": "A configuracao persistida mudou. Verifica novamente.",
                    })
                from backend.api.data import _approval_args

                try:
                    approval = authorize_application(
                        prepared.values["gate_report"], **_approval_args(request_body),
                    )
                except ValueError as exc:
                    raise HTTPException(409, {
                        "message": str(exc), "gate_report": prepared.values["gate_report"],
                        **candidate.identity(),
                    }) from exc
                for key, value in prepared.values.items():
                    setattr(staged, key, value)
                if approval is not None:
                    staged.approvals.append({
                        **approval, "action": prepared.approval_action, **candidate.identity(),
                    })
                return prepared.response, [], []
            with stage_state(state, staged) as context:
                context.api_write = True
                context.recalculate_from_start = recalculate_from_start
                response = asyncio.run(fn(*args, **kwargs))
            if context.approval_required is not None:
                if context.validators or context.callbacks:
                    # Do not cache executable closures over a previous request.
                    raise context.approval_required
                values = {
                    item.name: copy.deepcopy(getattr(staged, item.name))
                    for item in fields(staged) if item.name not in _SERVICES
                }
                candidate = previews.put_for_origin(
                    preview_kind, origin, preview_parameters,
                    PreparedPlanWrite(values, response, file_identity, context.approval_action),
                )
                error = context.approval_required
                raise HTTPException(error.status_code, {
                    **error.detail, **candidate.identity(),
                })
            return response, context.validators, context.callbacks

        with planning_scope(timeout_s=_planning_budget("normal"), check_on_exit=False):
            try:
                response, validators, callbacks = await run_in_threadpool(calculate)
            finally:
                planning_checkpoint()
            async with plan_mutation_lock:
                return await run_in_threadpool(
                    _commit, state, staged, origin, file_identity, operation_id, fingerprint,
                    response, validators, callbacks,
                    recalculate_from_start=recalculate_from_start,
                )

    wrapped.__signature__ = signature
    return wrapped
