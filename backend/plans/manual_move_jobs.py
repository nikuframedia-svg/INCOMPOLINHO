"""Background preview jobs for manual production moves."""

from __future__ import annotations

import copy
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

from backend.planning_control import PlanningCancelled, PlanningTimeout
from backend.plans.candidates import result_fingerprint
from backend.plans.manual_move import (
    ManualMoveError,
    ManualMoveInconclusive,
    ManualMoveResult,
    move_lot,
)
from backend.plans.serialize import planning_input_fingerprints

UTC = timezone.utc  # noqa: UP017 - Python 3.10 compatibility
logger = logging.getLogger(__name__)
_TERMINAL_STATUSES = {"ready", "applied", "failed", "cancelled"}
_MAX_RETAINED_JOBS = 100


class _JobCancelled(Exception):
    """Internal cooperative cancellation signal."""


class ManualMoveJobManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="manual-move",
        )
        self.jobs: dict[str, dict] = {}
        self.candidates: dict[str, ManualMoveResult] = {}
        self.cancel_events: dict[str, threading.Event] = {}
        self.futures: dict[str, Future] = {}

    def _prune_locked(self) -> None:
        excess = len(self.jobs) - _MAX_RETAINED_JOBS
        if excess <= 0:
            return
        removable = sorted(
            (
                job_id
                for job_id, job in self.jobs.items()
                if job["status"] in _TERMINAL_STATUSES
            ),
            key=lambda job_id: self.jobs[job_id]["created_at"],
        )
        for job_id in removable[:excess]:
            self.jobs.pop(job_id, None)
            self.candidates.pop(job_id, None)
            self.cancel_events.pop(job_id, None)
            self.futures.pop(job_id, None)

    def start(
        self,
        *,
        segments,
        lots,
        score,
        engine_data,
        config,
        dataset_id: str,
        base_revision: int,
        lot_id: str,
        target_day: int,
        target_machine: str | None,
        target_start_min: int | None,
        reason: str,
        author: str,
        origin: dict | None = None,
    ) -> dict:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        job_id = uuid4().hex
        job = {
            "id": job_id,
            "created_at": now,
            "updated_at": now,
            "status": "queued",
            "progress": 0,
            "phase": "queued",
            "message": "Verificação em fila",
            "dataset_id": dataset_id,
            "base_revision": int(base_revision),
            "input_fingerprints": planning_input_fingerprints(engine_data, config),
            "origin": copy.deepcopy(origin),
            "score_previous": copy.deepcopy(score),
            "error": None,
        }
        cancel_event = threading.Event()
        with self.lock:
            self.jobs[job_id] = job
            self.cancel_events[job_id] = cancel_event
            self._prune_locked()
        future = self.executor.submit(
            self._run,
            job_id,
            cancel_event,
            copy.deepcopy(segments),
            copy.deepcopy(lots),
            copy.deepcopy(score),
            copy.deepcopy(engine_data),
            copy.deepcopy(config),
            lot_id,
            target_day,
            target_machine,
            target_start_min,
            reason,
            author,
        )
        with self.lock:
            self.futures[job_id] = future
        return self.get(job_id) or job

    def _update(self, job_id: str, **changes) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return
            if (
                job["status"] == "cancelled"
                and changes.get("status") != "cancelled"
            ):
                return
            job.update(changes)
            job["updated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()

    def _run(
        self,
        job_id: str,
        cancel_event: threading.Event,
        segments,
        lots,
        score,
        engine_data,
        config,
        lot_id: str,
        target_day: int,
        target_machine: str | None,
        target_start_min: int | None,
        reason: str,
        author: str,
    ) -> None:
        if cancel_event.is_set():
            return
        self._update(
            job_id,
            status="running",
            progress=10,
            phase="scheduling",
            message="A reorganizar o restante plano",
        )

        def progress(phase: str, percent: int, message: str) -> None:
            if cancel_event.is_set():
                raise _JobCancelled
            self._update(
                job_id,
                status="running",
                progress=percent,
                phase=phase,
                message=message,
            )

        try:
            candidate = move_lot(
                segments,
                lots,
                score,
                engine_data,
                config,
                lot_id=lot_id,
                target_day=target_day,
                target_machine=target_machine,
                target_start_min=target_start_min,
                reason=reason,
                author=author,
                optimization_mode="quick",
                progress=progress,
                cancel_event=cancel_event,
            )
            if cancel_event.is_set():
                raise _JobCancelled
            with self.lock:
                self.candidates[job_id] = copy.deepcopy(candidate)
                self.jobs[job_id]["candidate_fingerprint"] = result_fingerprint(candidate)
            self._update(
                job_id,
                status="ready",
                progress=100,
                phase="ready",
                message="Riscos verificados",
            )
        except (_JobCancelled, PlanningCancelled):
            self._update(
                job_id,
                status="cancelled",
                phase="cancelled",
                message="Verificação cancelada",
            )
        except PlanningTimeout:
            self._update(
                job_id,
                status="failed",
                progress=100,
                phase="failed",
                message="Verificação inconclusiva",
                error=(
                    "A verificação atingiu o limite de tempo. Não foi demonstrada "
                    "a impossibilidade do movimento; o plano não foi alterado."
                ),
            )
        except ManualMoveInconclusive as exc:
            self._update(
                job_id, status="failed", progress=100, phase="failed",
                message="Verificação inconclusiva", error=str(exc),
            )
        except ManualMoveError as exc:
            detail = str(exc)
            violations = (exc.gate_report or {}).get("violations") or []
            if violations and isinstance(violations[0], dict):
                explanation = str(violations[0].get("message", "")).strip()
                if explanation and explanation not in detail:
                    detail = f"{detail} {explanation}"
            self._update(
                job_id,
                status="failed",
                progress=100,
                phase="failed",
                message="Não foi possível verificar o movimento",
                error=detail,
                gate_report=exc.gate_report,
            )
        except Exception as exc:  # pragma: no cover - defensive job boundary
            self._update(
                job_id,
                status="failed",
                progress=100,
                phase="failed",
                message="Não foi possível verificar o movimento",
                error=str(exc),
            )
            logger.exception("Unexpected manual-move preview failure")

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            public = {
                key: copy.deepcopy(value)
                for key, value in job.items()
                if key != "score_previous"
            }
            return public

    def result(
        self,
        job_id: str,
        *,
        dataset_id: str,
        plan_revision: int,
        input_fingerprints: dict | None = None,
        origin: dict | None = None,
    ) -> tuple[ManualMoveResult, dict]:
        with self.lock:
            job = self.jobs.get(job_id)
            candidate = self.candidates.get(job_id)
            if job is None:
                raise ValueError("A verificação deste movimento não existe.")
            if job["status"] == "cancelled":
                raise ValueError("A verificação deste movimento foi cancelada.")
            if job["status"] != "ready" or candidate is None:
                raise ValueError("A verificação deste movimento ainda não está pronta.")
            if job["dataset_id"] != dataset_id:
                raise ValueError("O ISOP mudou durante a verificação.")
            if int(job["base_revision"]) != int(plan_revision):
                raise ValueError("O plano mudou durante a verificação; verifica novamente.")
            if input_fingerprints is not None and job["input_fingerprints"] != input_fingerprints:
                raise ValueError("Os dados ou a configuracao mudaram; verifica novamente.")
            if not origin or job.get("origin") != origin:
                raise ValueError("O plano, regras ou modelo mudaram; verifica novamente.")
            if job.get("candidate_fingerprint") != result_fingerprint(candidate):
                raise ValueError("O candidato mudou desde a verificacao; verifica novamente.")
            return copy.deepcopy(candidate), copy.deepcopy(job["score_previous"])

    def cancel(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job["status"] in _TERMINAL_STATUSES:
                return self.get(job_id)
            cancel_event = self.cancel_events.get(job_id)
            if cancel_event is not None:
                cancel_event.set()
            future = self.futures.get(job_id)
            if future is not None:
                future.cancel()
            job.update(
                {
                    "status": "cancelled",
                    "phase": "cancelled",
                    "message": "Verificação cancelada",
                    "updated_at": datetime.now(UTC)
                    .replace(microsecond=0)
                    .isoformat(),
                }
            )
            self.candidates.pop(job_id, None)
            return self.get(job_id)

    def mark_applied(self, job_id: str) -> None:
        self._update(
            job_id,
            status="applied",
            progress=100,
            phase="applied",
            message="Movimento aplicado",
        )


manager = ManualMoveJobManager()
