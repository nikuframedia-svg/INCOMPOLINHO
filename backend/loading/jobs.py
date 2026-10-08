"""One isolated ISOP calculation at a time, coordinated by the API event loop.

The worker never modifies the live singleton. Only the coordinator can publish
a fully prepared state, after the snapshot and receipt have committed together.
Unfinished work is deliberately not resumed across a server restart.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from backend.api.locks import commit_lock, plan_mutation_lock
from backend.config.loader import DEFAULT_CONFIG_PATH, save_config
from backend.copilot.state import CopilotState
from backend.planning_control import PlanningCancelled, PlanningTimeout
from backend.plans.serialize import serialize_config, serialize_snapshot
from backend.plans.store import PlansStore
from backend.scheduler.gates import authorize_application, blocked_application_message
from backend.telemetry import observe_phases, phase

logger = logging.getLogger(__name__)
UTC = timezone.utc  # noqa: UP017 - Python 3.10 compatibility
TERMINAL = {"applied", "blocked", "failed", "cancelled", "stale"}
PHASE_MESSAGES = {
    "preparing": "A ler e validar o ISOP…",
    "prepared": "O ficheiro está pronto para calcular.",
    "queued": "Cálculo em fila…",
    "optimization": "A calcular o plano…",
    "initial_construction": "A construir o plano inicial…",
    "construction": "A construir um plano…",
    "candidate_search": "A comparar candidatos…",
    "normalization": "A ajustar os intervalos livres…",
    "validation": "A validar recursos, quantidades e regras…",
    "analytics": "A preparar os indicadores do plano…",
    "persistence": "A guardar o plano…",
    "awaiting_approval": "O plano aguarda aprovação das exceções.",
    "applied": "O novo plano foi carregado.",
    "blocked": "O plano foi bloqueado pelas regras de planeamento.",
    "failed": "Não foi possível concluir o carregamento.",
    "cancelled": "Carregamento cancelado. O plano anterior foi mantido.",
    "stale": "O plano ou a configuração mudou durante o carregamento.",
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode(),
    ).hexdigest()


class LoadJobError(Exception):
    def __init__(self, status: int, code: str, message: str, **detail):
        super().__init__(message)
        self.status = status
        self.detail = {"code": code, "message": message, **detail}


class LoadCancelled(Exception):
    pass


@dataclass
class LoadInputs:
    origin: dict
    cancel: threading.Event
    engine_data: object | None = None
    config: object | None = None
    trust: object | None = None
    result: object | None = None
    warnings: list[str] = field(default_factory=list)
    auto_confirm: bool = False
    approval: dict | None = None


def parse_upload(content: bytes, config_path: str, master_path: str):
    """Read a detached input in the worker; never expose filesystem paths via API."""
    import yaml

    from backend.config.loader import load_config, validate_config
    from backend.config.planning import (
        apply_effective_planning_config,
        harmonize_imported_twin_eco_lots,
        synchronize_active_twin_groups,
    )
    from backend.dqa import compute_trust_index
    from backend.parser.isop_reader import read_isop
    from backend.transform.calendars import apply_calendars
    from backend.transform.transform import transform

    config = load_config(config_path)
    master = yaml.safe_load(Path(master_path).read_text())
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
        tmp.write(content)
        tmp.flush()
        rows, workdays, has_twin = read_isop(tmp.name)
    engine = transform(rows, workdays, has_twin, master)
    if not engine.ops or not engine.machines:
        raise ValueError("O ISOP não contém operações de produção válidas.")
    if not engine.workdays or engine.n_days <= 0:
        raise ValueError("O ISOP não contém um horizonte de datas válido.")
    synchronize_active_twin_groups(engine, config.twins)
    warnings = harmonize_imported_twin_eco_lots(engine, config)
    engine.input_warnings.extend(
        warning for warning in warnings if warning not in engine.input_warnings
    )
    warnings = list(engine.input_warnings)
    apply_effective_planning_config(engine, config)
    config_errors = validate_config(config, engine)
    if config_errors:
        raise ValueError("Configuração inválida: " + "; ".join(config_errors))
    apply_calendars(engine, config)
    return engine, config, compute_trust_index(engine, config), warnings


class LoadJobManager:
    def __init__(
        self,
        live_state: CopilotState,
        store: PlansStore | None = None,
        *,
        config_path: str = DEFAULT_CONFIG_PATH,
        master_path: str = "config/incompol.yaml",
    ) -> None:
        self.state = live_state
        self.store = store if store is not None else live_state.get_plans_store()
        self.config_path = config_path
        self.master_path = master_path
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="isop-load")
        self.inputs: dict[str, LoadInputs] = {}
        self.tasks: set[asyncio.Task] = set()
        self.active_id: str | None = None
        self.closed = False
        for job in self.store.load_jobs():
            if job["status"] not in TERMINAL:
                job.update(
                    status="failed",
                    phase="failed",
                    updated_at=_now(),
                    message="O servidor reiniciou. Carrega novamente o ficheiro.",
                    error={
                        "code": "interrupted",
                        "message": "Carregamento interrompido pelo reinício do servidor.",
                    },
                )
                self.store.update_load_job(job)

    def _origin(self) -> dict:
        return {
            "revision": self.state.plan_revision,
            "dataset_id": (self.state.dataset_info or {}).get("id"),
            "config": _hash(serialize_config(self.state.config)) if self.state.config else None,
            "files": _hash(
                [
                    hashlib.sha256(Path(path).read_bytes()).hexdigest()
                    for path in (self.config_path, self.master_path)
                ]
            ),
        }

    def get(self, job_id: str) -> dict:
        job = self.store.load_job(job_id)
        if job is None:
            raise LoadJobError(404, "not_found", "O carregamento não foi encontrado.")
        if job["status"] not in TERMINAL:
            started = datetime.fromisoformat(job.get("started_at") or job["created_at"])
            job["elapsed_ms"] = round((datetime.now(UTC) - started).total_seconds() * 1000)
        return job

    def _update(self, job_id: str, **changes) -> dict:
        job = self.get(job_id)
        job.update(changes, updated_at=_now())
        if "phase" in changes and "message" not in changes:
            job["message"] = PHASE_MESSAGES.get(changes["phase"], "A calcular o plano…")
        self.store.update_load_job(job)
        if job["status"] in TERMINAL:
            if self.active_id == job_id:
                self.active_id = None
            self.inputs.pop(job_id, None)
        return job

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def start(
        self,
        content: bytes,
        filename: str,
        request_id: str | None = None,
        *,
        auto_confirm: bool = False,
        approval: dict | None = None,
        expected_revision: int | None = None,
    ) -> dict:
        if self.closed:
            raise LoadJobError(503, "restarting", "O servidor está a reiniciar.")
        try:
            job_id = str(UUID(request_id)) if request_id else str(uuid4())
        except (TypeError, ValueError, AttributeError) as exc:
            raise LoadJobError(
                400, "invalid_id", "Identificador de carregamento inválido."
            ) from exc
        filename = Path(filename or "upload.xlsx").name
        fingerprint = _hash([filename, hashlib.sha256(content).hexdigest(), auto_confirm, approval])
        previous = self.store.load_fingerprint(job_id)
        if previous is not None:
            if previous != fingerprint:
                raise LoadJobError(
                    409, "different_input", "Este identificador já pertence a outro carregamento."
                )
            return self.get(job_id)
        if self.active_id:
            raise LoadJobError(
                409,
                "load_in_progress",
                "Já existe um carregamento em curso.",
                job_id=self.active_id,
            )
        origin = self._origin()
        if expected_revision is not None and expected_revision != origin["revision"]:
            raise LoadJobError(
                409,
                "stale_revision",
                "O plano mudou entretanto.",
                current_revision=origin["revision"],
            )
        now = _now()
        job = {
            "id": job_id,
            "filename": filename,
            "status": "preparing",
            "phase": "preparing",
            "message": PHASE_MESSAGES["preparing"],
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "elapsed_ms": 0,
            "timings_ms": {},
            "base_revision": origin["revision"],
            "prepared": None,
            "gate_report": None,
            "result": None,
            "error": None,
        }
        self.store.create_load_job(job, fingerprint)
        self.active_id = job_id
        inputs = LoadInputs(origin, threading.Event(), auto_confirm=auto_confirm, approval=approval)
        self.inputs[job_id] = inputs
        self._spawn(self._prepare(job_id, content, inputs))
        logger.info("load_id=%s phase=preparing filename=%s", job_id, filename)
        return job

    def _live(self, job_id: str, inputs: LoadInputs) -> bool:
        return (
            not self.closed
            and not inputs.cancel.is_set()
            and self.get(job_id)["status"] not in TERMINAL
        )

    def _check_origin(self, job_id: str, inputs: LoadInputs) -> bool:
        if self._origin() == inputs.origin:
            return True
        self._update(
            job_id,
            status="stale",
            phase="stale",
            error={
                "code": "stale_revision",
                "message": "O plano ou a configuração mudou. Carrega novamente o ficheiro.",
            },
        )
        return False

    def _fail(self, job_id: str, exc: Exception, code: str = "calculation_failed") -> None:
        if self.get(job_id)["status"] in TERMINAL:
            return
        logger.exception("load_id=%s failed code=%s", job_id, code)
        if isinstance(exc, PlanningTimeout):
            self._update(
                job_id, status="failed", phase="failed",
                error={
                    "code": "planning_timeout",
                    "message": "O cálculo do plano excedeu o tempo disponível. "
                    "O plano anterior foi mantido.",
                },
            )
            return
        message = (
            str(exc)
            if isinstance(exc, ValueError)
            else "O carregamento falhou. Consulta os registos com a referência apresentada."
        )
        detail = {"code": code, "message": message}
        if getattr(exc, "violations", None):
            detail["violations"] = exc.violations
        self._update(job_id, status="failed", phase="failed", error=detail)

    async def _prepare(self, job_id: str, content: bytes, inputs: LoadInputs) -> None:
        started = time.perf_counter()
        try:
            if not self._live(job_id, inputs):
                return
            loop = asyncio.get_running_loop()
            parsed = await loop.run_in_executor(
                self.executor,
                parse_upload,
                content,
                self.config_path,
                self.master_path,
            )
            if not self._live(job_id, inputs) or not self._check_origin(job_id, inputs):
                return
            if len(parsed) == 3:
                engine, parsed_config, trust = parsed
                warnings = []
            else:
                engine, parsed_config, trust, warnings = parsed
            inputs.engine_data = engine
            inputs.config = parsed_config
            inputs.trust = trust
            inputs.warnings = list(warnings)
            prepared = {
                "status": "prepared",
                "token": job_id,
                "expected_revision": inputs.origin["revision"],
                "filename": self.get(job_id)["filename"],
                "n_ops": len(engine.ops),
                "trust_index": {"score": trust.score, "gate": trust.gate},
                "machines": [
                    {"id": machine.id, "group": machine.group} for machine in engine.machines
                ],
                "references": sorted({op.sku for op in engine.ops}),
                "tools": sorted({op.t for op in engine.ops}),
                "warnings": warnings,
                "next_step": "Confirmar o cálculo com todas as máquinas inicialmente livres.",
            }
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            self._update(
                job_id,
                status="prepared",
                phase="prepared",
                prepared=prepared,
                timings_ms={"preparing": elapsed},
            )
            logger.info("load_id=%s phase=preparing duration_ms=%.1f", job_id, elapsed)
            if inputs.auto_confirm:
                self.confirm(job_id, inputs.origin["revision"], "all_free")
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self._fail(job_id, exc, "invalid_isop")

    def confirm(self, job_id: str, expected_revision: int, mode: str) -> dict:
        if mode not in {"all_free", "livres"}:
            raise LoadJobError(
                400, "invalid_mode", "O modo manual foi removido. Confirma com mode='all_free'."
            )
        job = self.get(job_id)
        if expected_revision != job["base_revision"]:
            raise LoadJobError(
                409, "stale_revision", "A confirmação refere-se a outra revisão do plano."
            )
        if job["status"] == "preparing":
            raise LoadJobError(409, "not_prepared", "O ficheiro ainda está a ser preparado.")
        if job["status"] != "prepared":
            return job  # includes lost responses and repeat clicks: never re-optimize
        inputs = self.inputs[job_id]
        if not self._check_origin(job_id, inputs):
            return self.get(job_id)
        self._update(job_id, status="queued", phase="queued", started_at=_now(), elapsed_ms=0)
        self._spawn(self._calculate(job_id, inputs))
        return self.get(job_id)

    def approve(self, job_id: str, expected_revision: int, *, reason: str, author: str) -> dict:
        job = self.get(job_id)
        if job["status"] == "applied" or (job["status"] == "running" and job.get("approval")):
            return job
        if job["status"] != "awaiting_approval":
            raise LoadJobError(
                409,
                "not_approvable",
                "Este carregamento não aguarda aprovação.",
                gate_report=job["gate_report"],
            )
        inputs = self.inputs[job_id]
        if expected_revision != job["base_revision"]:
            raise LoadJobError(
                409, "stale_revision", "A aprovação refere-se a outra revisão do plano."
            )
        if not self._check_origin(job_id, inputs):
            return self.get(job_id)
        try:
            approval = authorize_application(
                inputs.result.gate_report,
                approve_exceptions=True,
                approval_reason=reason,
                approval_author=author,
            )
        except ValueError as exc:
            raise LoadJobError(400, "invalid_approval", str(exc)) from exc
        self._update(job_id, status="running", phase="analytics", approval=approval)
        self._spawn(self._apply(job_id, inputs, approval))
        return self.get(job_id)

    def cancel(self, job_id: str) -> dict:
        job = self.get(job_id)
        if job["status"] in TERMINAL:
            return job
        inputs = self.inputs.get(job_id)
        if inputs:
            inputs.cancel.set()
        return self._update(job_id, status="cancelled", phase="cancelled")

    def _progress(self, job_id: str, current: str, completed: str | None, elapsed: float) -> None:
        if self.closed or self.get(job_id)["status"] != "running":
            return
        job = self.get(job_id)
        timings = job["timings_ms"]
        if completed:
            timings[completed] = round(timings.get(completed, 0) + elapsed, 1)
            logger.info("load_id=%s phase=%s duration_ms=%.1f", job_id, completed, elapsed)
        self._update(job_id, phase=current, timings_ms=timings)

    def _observer(self, job_id: str, inputs: LoadInputs, loop):
        stack: list[str] = []

        def observe(name: str, event: str, elapsed: float):
            if inputs.cancel.is_set():
                raise LoadCancelled()
            if event == "start":
                stack.append(name)
            elif stack:
                stack.pop()
            if not self.closed:
                loop.call_soon_threadsafe(
                    self._progress,
                    job_id,
                    stack[-1] if stack else "optimization",
                    name if event == "end" else None,
                    elapsed,
                )

        return observe

    def _worker_started(self, job_id: str, inputs: LoadInputs) -> None:
        if self._live(job_id, inputs):
            self._update(job_id, status="running", phase="optimization")

    async def _calculate(self, job_id: str, inputs: LoadInputs) -> None:
        loop = asyncio.get_running_loop()

        def calculate():
            from backend.cpo import optimize
            from backend.current_state import all_machines_free, apply_current_states
            from backend.transform.calendars import apply_calendars

            if inputs.cancel.is_set():
                raise LoadCancelled()
            loop.call_soon_threadsafe(self._worker_started, job_id, inputs)
            with observe_phases(self._observer(job_id, inputs, loop)):
                apply_current_states(inputs.engine_data, all_machines_free(inputs.engine_data))
                apply_calendars(inputs.engine_data, inputs.config)
                return optimize(
                    inputs.engine_data, mode="normal", audit=True,
                    config=inputs.config, cancel_event=inputs.cancel,
                )

        try:
            if not self._live(job_id, inputs):
                return
            inputs.result = await loop.run_in_executor(self.executor, calculate)
            if not self._live(job_id, inputs) or not self._check_origin(job_id, inputs):
                return
            report = inputs.result.gate_report
            self._update(job_id, gate_report=report)
            decision = (report or {}).get("apply_decision")
            logger.info(
                "load_id=%s decision=%s reasons=%s",
                job_id,
                decision,
                (report or {}).get("approval_reasons"),
            )
            if decision == "blocked" or not report:
                self._update(
                    job_id,
                    status="blocked",
                    phase="blocked",
                    error={"code": "plan_blocked", "message": blocked_application_message(report)},
                )
                return
            approval_args = inputs.approval or {}
            if report.get("requires_approval") and not approval_args.get("approve_exceptions"):
                self._update(job_id, status="awaiting_approval", phase="awaiting_approval")
                return
            try:
                approval = authorize_application(report, **approval_args)
            except ValueError as exc:
                self._update(
                    job_id,
                    status="blocked",
                    phase="blocked",
                    error={"code": "plan_blocked", "message": str(exc)},
                )
                return
            await self._apply(job_id, inputs, approval)
        except PlanningCancelled:
            self.cancel(job_id)
        except (LoadCancelled, asyncio.CancelledError):
            return
        except Exception as exc:
            self._fail(job_id, exc)

    async def _apply(self, job_id: str, inputs: LoadInputs, approval: dict | None) -> None:
        loop = asyncio.get_running_loop()
        job = self.get(job_id)
        audit_store = self.state.audit_store

        def prepare_application():
            from backend.current_state import serialize_current_states
            from backend.plans.serialize import assert_snapshot_integrity

            with observe_phases(self._observer(job_id, inputs, loop)), phase("analytics"):
                result, trust = inputs.result, inputs.trust
                staged = CopilotState(
                    engine_data=inputs.engine_data,
                    config=inputs.config,
                    default_config=copy.deepcopy(inputs.config),
                    plan_revision=inputs.origin["revision"],
                    plans_store=self.store,
                    audit_store=audit_store,
                    trust_index=trust,
                    current_machine_states=list(inputs.engine_data.current_machine_states),
                    warnings=list(inputs.warnings),
                )
                if approval:
                    staged.approvals = [{**approval, "action": "load"}]
                staged.set_dataset_info(job["filename"], result, trust, len(inputs.engine_data.ops))
                staged.dataset_info["load_job_id"] = job_id
                staged.update_schedule(result)
                staged.warnings = list(dict.fromkeys([*inputs.warnings, *staged.warnings]))
                staged.learning_info = {
                    "optimized": True,
                    "mode": "normal",
                    "time_ms": result.time_ms,
                }
                payload = serialize_snapshot(staged)
                assert_snapshot_integrity(payload, origin=job["filename"])
                encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                response = {
                    "status": "ok",
                    "current_state_mode": "all_free",
                    "current_machine_states": serialize_current_states(
                        staged.current_machine_states
                    ),
                    "state_warnings": list(inputs.warnings),
                    "n_ops": len(inputs.engine_data.ops),
                    "n_segments": len(result.segments),
                    "score": result.score,
                    "time_ms": result.time_ms,
                    "trust_index": {"score": trust.score, "gate": trust.gate},
                    "journal_summary": None,
                    "learning": staged.learning_info,
                    "dataset": staged.dataset_info,
                    "gate_report": result.gate_report,
                    "improvement_report": result.improvement_report,
                    "plan_revision": staged.plan_revision,
                }
                return staged, encoded, response

        robustness_snapshot = None
        try:
            if not self._live(job_id, inputs):
                return
            self._update(job_id, phase="analytics")
            staged, encoded, response = await loop.run_in_executor(
                self.executor, prepare_application
            )
            async with plan_mutation_lock:
                with commit_lock:
                    if not self._live(job_id, inputs) or not self._check_origin(job_id, inputs):
                        return
                    # No await between the final origin check, transaction and publication.
                    self._update(job_id, phase="persistence")
                    started = time.perf_counter()
                    receipt = self.get(job_id)
                    receipt.update(
                        status="applied",
                        phase="applied",
                        message=PHASE_MESSAGES["applied"],
                        result=response,
                        updated_at=_now(),
                        error=None,
                    )
                    plan_id = uuid4().hex
                    receipt["plan_id"] = plan_id
                    config_changed = serialize_config(self.state.config) != serialize_config(
                        staged.config
                    )
                    config_path = Path(self.config_path).resolve()
                    operation_id = f"load:{job_id}"
                    journal = {
                        "config_changed": config_changed,
                        "config_path": str(config_path),
                        "old_config_text": config_path.read_text(encoding="utf-8")
                        if config_path.exists() else None,
                        "old_config": serialize_config(self.state.config),
                        "new_config": serialize_config(staged.config),
                        "plan_revision": staged.plan_revision,
                    }
                    self.store.prepare_mutation(operation_id, job_id, journal)
                    try:
                        if config_changed:
                            save_config(staged.config, str(config_path))
                        self.store.commit_load(receipt, plan_id=plan_id, payload_json=encoded)
                    except Exception:
                        # If commit succeeded but its acknowledgement failed, the
                        # durable receipt is authoritative. Publish that same state.
                        committed = self.store.load_job(job_id)
                        if (
                            not committed
                            or committed.get("plan_id") != plan_id
                            or committed["status"] != "applied"
                        ):
                            from backend.plans.transactions import _atomic_text

                            if config_changed:
                                _atomic_text(config_path, journal["old_config_text"])
                            self.store.abort_mutation(operation_id)
                            raise
                        receipt = committed
                        logger.exception(
                            "load_id=%s commit acknowledgement failed; receipt recovered", job_id
                        )
                    staged.rules = self.state.rules
                    object.__setattr__(self.state, "__dict__", staged.__dict__.copy())
                    elapsed = round((time.perf_counter() - started) * 1000, 1)
                    logger.info(
                        "load_id=%s phase=persistence duration_ms=%.1f "
                        "plan_id=%s applied_revision=%s",
                        job_id,
                        elapsed,
                        plan_id,
                        self.state.plan_revision,
                    )
                    self.inputs.pop(job_id, None)
                    if self.active_id == job_id:
                        self.active_id = None
                    # A diagnostic write cannot turn a committed load into a failure.
                    try:
                        receipt["timings_ms"]["persistence"] = elapsed
                        self.store.update_load_job(receipt)
                        self.store.prune_auto(keep=20)
                    except Exception:
                        logger.exception(
                            "load_id=%s post-commit diagnostics/cleanup failed", job_id,
                        )
                    # Informational robustness of the loaded plan; never fails the load.
                    # Only the cheap detached snapshot runs here, under the lock.
                    try:
                        from backend.risk.jobs import capture_auto_snapshot

                        robustness_snapshot = capture_auto_snapshot(self.state)
                    except Exception:
                        robustness_snapshot = None
                        logger.exception(
                            "load_id=%s automatic robustness snapshot failed", job_id,
                        )
            if robustness_snapshot is not None:
                # Fingerprints and the job row are built off the event loop.
                try:
                    from backend.risk.jobs import submit_auto_snapshot

                    await loop.run_in_executor(None, submit_auto_snapshot, robustness_snapshot)
                except Exception:
                    logger.exception(
                        "load_id=%s automatic robustness job not started", job_id,
                    )
        except (LoadCancelled, asyncio.CancelledError):
            return
        except Exception as exc:
            self._fail(job_id, exc, "application_failed")

    async def close(self) -> None:
        self.closed = True
        for job_id, inputs in list(self.inputs.items()):
            inputs.cancel.set()
            if self.get(job_id)["status"] not in TERMINAL:
                self._update(
                    job_id,
                    status="failed",
                    phase="failed",
                    error={
                        "code": "interrupted",
                        "message": "O servidor reiniciou. Carrega novamente o ficheiro.",
                    },
                )
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.executor.shutdown(wait=False, cancel_futures=True)
