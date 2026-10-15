"""Persistent background jobs for long re-planning operations."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.api.locks import commit_lock
from backend.copilot.state import CopilotState, state
from backend.planning_control import (
    PlanningCancelled,
    PlanningStopped,
    PlanningTimeout,
    closing_reserve,
    planning_checkpoint,
    planning_scope,
    remaining_time,
)
from backend.plans.frozen import (
    _current_planning_day,
    _frozen_started_lots,
    _protected_plan,
    assert_fresh_calculation,
    boundary_label,
    candidate_history_changes,
    compact_preserving_started_lots,
    elapsed_on_planning_day,
    improve_preserving_protected_lots,
    optimize_preserving_started_lots,
    planning_boundary,
    preserved_lots_warning,
    released_anchor_ledger,
    released_anchor_notices_missing,
    with_current_material,
    with_released_anchor_notices,
    without_calculation_notes,
)

UTC = timezone.utc  # noqa: UP017 - Python 3.10 compatibility
DEFAULT_DB_PATH = (
    Path(os.environ.get("PP1_DATA_DIR", Path(__file__).resolve().parents[2] / "data")) / "replan.db"
)
DEFAULT_RETENTION_LIMIT = 100
logger = logging.getLogger(__name__)

REPLAN_TOTAL_BUDGET_S = 80.0
# Time the bounded local calendar repair leaves for the complete constructor
# (optimize_preserving_started_lots) when the repair cannot finish. The
# constructor's own scope keeps a closing reserve (10 s) for merging and
# validation, so its first complete candidate gets this minus 10 s. Measured
# on revision 124 (11/10/2026, per-delivery campaigns, 1 core): the residual
# build takes 6-11 s and the first validated candidate ~13-17 s, slower with
# other calculations on the machine; 25 s left only ~15 s and timed out.
LOCAL_REPAIR_OPTIMIZER_RESERVE_S = 35.0
# The quick repair only adjusts the segments a calendar edit invalidated. A
# wider edit (revision 124: an outage of PRM031 for three weeks invalidates 40
# segments, PRM019 for a week 11) goes straight to the complete constructor,
# which then has the whole budget. A work bound, not a time bound: the same
# edit of the same plan always takes the same path.
LOCAL_REPAIR_MAX_INVALID_SEGMENTS = 10

# Failed jobs carry a stable code and plain Portuguese text. Raw exception text
# (often English, e.g. "Planning deadline expired") never reaches the screen.
FAILURE_TEXTS = {
    "planning_timeout": (
        "Tempo de cálculo esgotado sem um plano válido",
        "Não foi possível concluir e validar um plano novo dentro do tempo "
        "disponível. Isto não prova que a alteração seja impossível. O plano e "
        "a configuração não foram alterados.",
    ),
    "invalid_plan": (
        "Não foi possível obter um plano válido",
        "O plano calculado com esta alteração não cumpre as regras físicas da "
        "fábrica. O plano e a configuração não foram alterados.",
    ),
    "blocked": (
        "O plano proposto não pode ser aplicado",
        "O plano proposto tem conflitos físicos ou peças em falta. O plano e a "
        "configuração não foram alterados.",
    ),
    # Not a physical conflict: the candidate would change production that
    # already started (AGENTS §2 rule 4, §5), which the commit refuses.
    "history_protected": (
        "O plano proposto alteraria produção já iniciada",
        "O plano calculado alteraria produção já iniciada, que está protegida, e "
        "por isso não pode ser aplicado. O plano e a configuração não foram "
        "alterados. Pode iniciar novamente.",
    ),
    "internal_error": (
        "Não foi possível concluir o replaneamento",
        "Ocorreu um erro interno durante o cálculo. O plano e a configuração "
        "não foram alterados. Tente novamente; se repetir, avise o suporte.",
    ),
    "interrupted": (
        "Replaneamento interrompido; pode iniciar novamente.",
        "O replaneamento foi interrompido (o servidor reiniciou ou o cálculo "
        "parou). O plano e a configuração não foram alterados. Pode iniciar "
        "novamente.",
    ),
}


class _BlockedCandidate(ValueError):
    """The candidate failed the physical/coverage gate; its text is Portuguese."""

    def __init__(self, message: str, violations: list[dict] | None = None) -> None:
        super().__init__(message)
        self.violations = list(violations or [])


class _ProtectedHistoryChanged(ValueError):
    """A candidate would change started production (AGENTS §2 rule 4, §5).

    Never offered: a quick-repair candidate falls back to the complete
    constructor; a final candidate fails the job with ``history_protected``.
    """

    def __init__(self, lot_ids: list[str]) -> None:
        self.lot_ids = list(lot_ids)
        super().__init__(f"started production changed: {', '.join(self.lot_ids[:5])}")


PROTECTED_HISTORY_TEXT = FAILURE_TEXTS["history_protected"][1]


def _violation_causes(exc, data=None, lots=None) -> list[str]:
    """The refusal causes shown under the failure (``plans.refusal``)."""

    from backend.plans.refusal import refusal_causes, violations_of

    return refusal_causes(violations_of(exc), data, lots=lots)


def _baseline_needs_material_rebuild(restored_baseline: dict) -> bool:
    """A plan built before per-delivery material windows cannot be reused.

    Persisting it again is refused by the material contract (plans/store.py),
    so a calendar edit must rebuild instead of treating it as an unchanged
    baseline and failing at commit.  The single legacy rule lives in
    ``canonical.legacy_material_plan``.
    """
    from backend.scheduler.canonical import legacy_material_plan

    return legacy_material_plan(
        restored_baseline["result"].lots,
        restored_baseline["engine_data"],
        restored_baseline["config"],
    )


# The rebuild note of a job and the restore note of a legacy plan.
LEGACY_MATERIAL_PREFIXES = (
    "O plano ativo foi calculado antes de o material",
    "Este plano foi calculado antes de o material",
)


def _without_stale_legacy_warnings(warnings, lots, current: list[str]) -> list[str]:
    """Drop a carried-over "recalculado de raiz" note from a current plan.

    ``current``: the notes this calculation wrote, always kept. Since
    material version 3 no plan needs a rebuild (``legacy_material_plan``),
    so a carried-over note is always stale.
    """
    from backend.scheduler.canonical import legacy_material_plan

    if legacy_material_plan(lots, None, None):
        return list(warnings)
    return [
        warning for warning in warnings
        if warning in current or not warning.startswith(LEGACY_MATERIAL_PREFIXES)
    ]


class _WideCalendarEdit(Exception):
    """The edit invalidates too much of the plan for the quick repair."""


def _invalidated_segments(error) -> int:
    """Segments a calendar edit invalidated (0 when the error names none)."""

    return len({
        (item.get("lot_id"), item.get("machine_id"), item.get("day_idx"), item.get("start_min"))
        for item in getattr(error, "violations", None) or []
        if isinstance(item, dict) and item.get("lot_id") is not None
    })


def _valid_delivery_floor(baseline, engine_data, config):
    """Keep the current plan as a delivery floor independently of compaction."""
    from backend.scheduler.scoring import compute_score
    from backend.scheduler.validation import PlanValidationError, assert_plan_valid

    try:
        assert_plan_valid(baseline.segments, engine_data, config, lots=baseline.lots)
    except PlanValidationError:
        return None
    floor = copy.deepcopy(baseline)
    floor.score = compute_score(floor.segments, floor.lots, engine_data, config=config)
    return floor


def _late_with_idle_capacity(plan, engine_data, config, planning_day: int, now=None) -> bool:
    """Whether a late delivery of ``plan`` has idle capacity before its deadline.

    A missed subcontract dispatch counts too (``dispatch_targets``): finishing
    before it stays the planner's aim although it is no late delivery
    (Luís, 14/10/2026).

    The cheap read-only check of ``scheduler.idle_capacity`` (tens of ms).
    Only then can the complete constructor recover a delivery the compaction
    leaves late; a structural shortage (no idle capacity) gives it nothing to
    find, and its time is better left to the compaction (rehearsal of
    13/10/2026 on revision 128: the reserve with only a structural late order
    cost 3 setups and 6 orders ready later). A failing check reserves nothing.
    ``now``: the job's instant (only time after it is free today).
    """
    from backend.scheduler.idle_capacity import late_with_idle_capacity

    try:
        return bool(late_with_idle_capacity(
            plan.segments, plan.lots, engine_data, config, planning_day=planning_day, now=now,
            dispatch_targets=True,
        ))
    except Exception:  # informational check: the job goes on as before
        logger.exception("Idle-capacity check failed in the replan job")
        return False


def _prefer_no_loss_plan(candidate, reference, engine_data):
    """Compare unchanged-input plans with the same automatic-improvement rule."""
    from backend.scheduler.improvement import (
        improvement_better,
        improvement_key,
        lot_changes,
        no_loss_verdict,
        plan_facts,
        tool_transfers,
    )

    candidate_facts = plan_facts(candidate.segments, candidate.lots, engine_data, candidate.score)
    reference_facts = plan_facts(reference.segments, reference.lots, engine_data, reference.score)
    if not no_loss_verdict(candidate_facts, reference_facts).admissible:
        return False
    changed, displacement = lot_changes(candidate.segments, reference.segments)
    if {lot.id for lot in candidate.lots} != {lot.id for lot in reference.lots}:
        # Anticipation is a per-lot comparison; with different lot sizing it
        # is undefined, so it ties and the remaining criteria decide.
        candidate_facts.anticipation = reference_facts.anticipation = ()

    def key(plan, facts, changed_lots, displacement_min):
        return improvement_key(
            facts, transfers=tool_transfers(plan.segments),
            changed_lots=changed_lots, displacement_min=displacement_min,
        )

    return improvement_better(
        key(candidate, candidate_facts, changed, displacement),
        key(reference, reference_facts, 0, 0.0),
    )

_REPLAN_TRANSACTION_FIELDS = (
    "engine_data",
    "config",
    "current_machine_states",
    "segments",
    "lots",
    "score",
    "warnings",
    "gate_report",
    "improvement_report",
    "solver_status",
    "feasibility",
    "plan_revision",
    "approvals",
    "journal_entries",
    "operator_alerts",
    "manual_edits",
    "active_mutations",
    "dataset_info",
    "schedule_id",
    "stock_projections",
    "expedition",
    "risk_result",
    "late_deliveries",
    "coverage",
    "order_tracking",
    "stress_map",
)


def canonical_replan_fingerprint(
    *,
    dataset_id: str,
    base_revision: int,
    request: dict,
    base_input_fingerprints: dict | None = None,
) -> str:
    """Return a stable identity for one effective re-plan request."""

    payload = {
        "dataset_id": str(dataset_id),
        "base_revision": int(base_revision),
        "request": request,
    }
    if base_input_fingerprints is not None:
        payload["base_input_fingerprints"] = base_input_fingerprints
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def replan_base_fingerprints(snapshot: dict) -> dict:
    """Bind a job to its actual inputs even if a restart reuses a revision."""
    from backend.plans.serialize import value_fingerprint

    fingerprints = snapshot["fingerprints"]
    return {key: fingerprints[key] for key in ("config", "engine_data", "schedule")} | {
        "active_mutations": value_fingerprint(snapshot.get("active_mutations", [])),
        "origin": copy.deepcopy(snapshot.get("planning_origin")),
    }


def _result_snapshot(engine_data, config, result, *, plan_revision, dataset_info, mutations):
    from backend.plans.serialize import serialize_snapshot
    from backend.scheduler.canonical import result_validation_data

    engine_data = result_validation_data(engine_data, result)

    staged = CopilotState(
        engine_data=engine_data,
        config=config,
        plan_revision=plan_revision,
        dataset_info=copy.deepcopy(dataset_info),
        active_mutations=copy.deepcopy(mutations),
        segments=result.segments,
        lots=result.lots,
        score=result.score,
        warnings=result.warnings,
        operator_alerts=result.operator_alerts,
        journal_entries=result.journal,
        gate_report=result.gate_report,
        improvement_report=result.improvement_report,
        solver_status=result.solver_status,
        feasibility=result.feasibility,
    )
    return serialize_snapshot(staged)


def _allow_unchanged_resource_relaxation(report: dict) -> dict:
    """Permit an identical active plan after a proven non-tightening calendar edit."""

    if not report.get("physical_gate_passed") or not report.get("coverage_gate_passed"):
        return report
    inherited = list(report.get("approval_reasons") or [])
    report["inherited_active_plan_exceptions"] = inherited
    report["configuration_only_relaxation"] = True
    report["status"] = "applicable"
    report["apply_decision"] = "auto_applicable"
    report["requires_approval"] = False
    return report


class ReplanJobStore:
    _metadata_columns = (
        "id,created_at,updated_at,status,progress,phase,message,reason,dataset_id,"
        "base_revision,request_fingerprint,base_input_fingerprints_json,worker_id,"
        "worker_pid,result_json,warnings_json,error,code,causes_json"
    )
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        retention_limit: int = DEFAULT_RETENTION_LIMIT,
        worker_id: str | None = None,
        worker_pid: int | None = None,
    ) -> None:
        self.path = str(path or DEFAULT_DB_PATH)
        self.retention_limit = max(1, int(retention_limit))
        self.worker_id = worker_id or uuid4().hex
        self.worker_pid = int(worker_pid if worker_pid is not None else os.getpid())
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        from backend.runtime_guard import assert_writable

        assert_writable(self.path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS replan_jobs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    message TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    base_revision INTEGER NOT NULL DEFAULT 0,
                    request_fingerprint TEXT,
                    base_input_fingerprints_json TEXT,
                    worker_id TEXT,
                    worker_pid INTEGER,
                    result_json TEXT,
                    candidate_json TEXT,
                    warnings_json TEXT,
                    error TEXT,
                    code TEXT,
                    causes_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_replan_created
                    ON replan_jobs(created_at DESC);
                """
            )
            columns = {
                row["name"]
                for row in self.conn.execute("PRAGMA table_info(replan_jobs)").fetchall()
            }
            if "base_revision" not in columns:
                self.conn.execute(
                    "ALTER TABLE replan_jobs ADD COLUMN base_revision INTEGER NOT NULL DEFAULT 0"
                )
            if "candidate_json" not in columns:
                self.conn.execute("ALTER TABLE replan_jobs ADD COLUMN candidate_json TEXT")
            if "request_fingerprint" not in columns:
                self.conn.execute("ALTER TABLE replan_jobs ADD COLUMN request_fingerprint TEXT")
            if "worker_id" not in columns:
                self.conn.execute("ALTER TABLE replan_jobs ADD COLUMN worker_id TEXT")
            if "worker_pid" not in columns:
                self.conn.execute("ALTER TABLE replan_jobs ADD COLUMN worker_pid INTEGER")
            if "code" not in columns:
                self.conn.execute("ALTER TABLE replan_jobs ADD COLUMN code TEXT")
            if "causes_json" not in columns:
                self.conn.execute("ALTER TABLE replan_jobs ADD COLUMN causes_json TEXT")
            if "base_input_fingerprints_json" not in columns:
                self.conn.execute(
                    "ALTER TABLE replan_jobs ADD COLUMN base_input_fingerprints_json TEXT"
                )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_replan_fingerprint "
                "ON replan_jobs(dataset_id,base_revision,request_fingerprint)"
            )
            self.conn.commit()

    @staticmethod
    def _pid_is_alive(pid: int | None) -> bool:
        if pid is None or int(pid) <= 0:
            return False
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _row_is_interrupted(self, row: sqlite3.Row) -> bool:
        if row["status"] not in {"queued", "running"}:
            return False
        if row["worker_id"] == self.worker_id:
            return False
        return not self._pid_is_alive(row["worker_pid"])

    def serialize(self, row: sqlite3.Row) -> dict:
        interrupted = self._row_is_interrupted(row)
        payload = {
            "id": row["id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "status": "failed" if interrupted else row["status"],
            "progress": row["progress"],
            "phase": "interrupted" if interrupted else row["phase"],
            "message": (
                FAILURE_TEXTS["interrupted"][0]
                if interrupted
                else row["message"]
            ),
            "reason": row["reason"],
            "dataset_id": row["dataset_id"],
            "base_revision": int(row["base_revision"]),
            "request_fingerprint": row["request_fingerprint"],
            "base_input_fingerprints": (
                json.loads(row["base_input_fingerprints_json"])
                if row["base_input_fingerprints_json"]
                else None
            ),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "warnings": json.loads(row["warnings_json"]) if row["warnings_json"] else [],
            "error": (
                row["error"]
                or (FAILURE_TEXTS["interrupted"][1] if interrupted else None)
            ),
            "code": "interrupted" if interrupted else row["code"],
            "causes": (
                [] if interrupted or not row["causes_json"] else json.loads(row["causes_json"])
            ),
            "stale": interrupted,
            "interrupted": interrupted,
        }
        if interrupted:
            payload["stored_status"] = row["status"]
        return payload

    def _prune_locked(self) -> None:
        rows = self.conn.execute(
            "SELECT id,status,worker_id,worker_pid FROM replan_jobs "
            "ORDER BY created_at DESC,rowid DESC"
        ).fetchall()
        protected = [
            row
            for row in rows
            if row["status"] in {"queued", "running"} and not self._row_is_interrupted(row)
        ]
        protected_ids = {row["id"] for row in protected}
        removable = [row for row in rows if row["id"] not in protected_ids]
        keep_removable = max(0, self.retention_limit - len(protected))
        expired_ids = [row["id"] for row in removable[keep_removable:]]
        if expired_ids:
            placeholders = ",".join("?" for _ in expired_ids)
            self.conn.execute(
                f"DELETE FROM replan_jobs WHERE id IN ({placeholders})",  # noqa: S608
                expired_ids,
            )

    def create(
        self,
        reason: str,
        dataset_id: str,
        base_revision: int = 0,
        request_fingerprint: str | None = None,
        base_input_fingerprints: dict | None = None,
    ) -> dict:
        job, _created = self.create_or_get(
            reason,
            dataset_id,
            base_revision,
            request_fingerprint=request_fingerprint,
            base_input_fingerprints=base_input_fingerprints,
        )
        return job

    def create_or_get(
        self,
        reason: str,
        dataset_id: str,
        base_revision: int = 0,
        *,
        request_fingerprint: str | None = None,
        base_input_fingerprints: dict | None = None,
    ) -> tuple[dict, bool]:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        job_id = uuid4().hex
        with self.lock:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                if request_fingerprint:
                    rows = self.conn.execute(
                        f"SELECT {self._metadata_columns} FROM replan_jobs WHERE dataset_id=? "
                        "AND base_revision=? AND request_fingerprint=? "
                        "AND status IN ('queued','running','ready') "
                        "ORDER BY created_at DESC,rowid DESC",
                        (dataset_id, int(base_revision), request_fingerprint),
                    ).fetchall()
                    for row in rows:
                        stored_fingerprints = (
                            json.loads(row["base_input_fingerprints_json"])
                            if row["base_input_fingerprints_json"]
                            else None
                        )
                        if (
                            not self._row_is_interrupted(row)
                            and stored_fingerprints == base_input_fingerprints
                        ):
                            self.conn.commit()
                            return self.serialize(row), False
                self.conn.execute(
                    "INSERT INTO replan_jobs "
                    "(id,created_at,updated_at,status,progress,phase,message,reason,"
                    "dataset_id,base_revision,request_fingerprint,worker_id,worker_pid,"
                    "base_input_fingerprints_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        now,
                        now,
                        "queued",
                        0,
                        "queued",
                        "Replaneamento em fila",
                        reason,
                        dataset_id,
                        int(base_revision),
                        request_fingerprint,
                        self.worker_id,
                        self.worker_pid,
                        json.dumps(base_input_fingerprints) if base_input_fingerprints else None,
                    ),
                )
                self._prune_locked()
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        job = self.get(job_id)
        if job is None:  # pragma: no cover - defensive database boundary
            raise RuntimeError("Não foi possível persistir o trabalho de replaneamento.")
        return job, True

    def update(self, job_id: str, **changes) -> dict | None:
        allowed = {
            "status",
            "progress",
            "phase",
            "message",
            "result",
            "warnings",
            "error",
            "code",
            "causes",
            "candidate",
            "base_input_fingerprints",
        }
        values = {key: value for key, value in changes.items() if key in allowed}
        if "result" in values:
            values["result_json"] = json.dumps(values.pop("result"), ensure_ascii=False)
        if "warnings" in values:
            values["warnings_json"] = json.dumps(values.pop("warnings"), ensure_ascii=False)
        if "causes" in values:
            values["causes_json"] = json.dumps(values.pop("causes"), ensure_ascii=False)
        if "candidate" in values:
            values["candidate_json"] = json.dumps(
                values.pop("candidate"),
                ensure_ascii=False,
            )
        if "base_input_fingerprints" in values:
            values["base_input_fingerprints_json"] = json.dumps(
                values.pop("base_input_fingerprints"),
                ensure_ascii=False,
            )
        values["updated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
        columns = ", ".join(f"{key}=?" for key in values)
        with self.lock, self.conn:
            self.conn.execute(
                f"UPDATE replan_jobs SET {columns} "  # noqa: S608
                "WHERE id=? AND status NOT IN ('cancelled','completed','failed')",
                (*values.values(), job_id),
            )
            self.conn.commit()
        return self.get(job_id)

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            row = self.conn.execute(
                f"SELECT {self._metadata_columns} FROM replan_jobs WHERE id=?", (job_id,)
            ).fetchone()
        return self.serialize(row) if row else None

    def get_candidate(self, job_id: str) -> dict | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT candidate_json FROM replan_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        if row is None or not row["candidate_json"]:
            return None
        return json.loads(row["candidate_json"])

    def list_jobs(
        self,
        *,
        dataset_id: str,
        base_revision: int,
        pending: bool | None = None,
    ) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                f"SELECT {self._metadata_columns} FROM replan_jobs "
                "WHERE dataset_id=? AND base_revision=? "
                "ORDER BY created_at DESC,rowid DESC",
                (dataset_id, int(base_revision)),
            ).fetchall()
        jobs = [self.serialize(row) for row in rows]
        if pending is None:
            return jobs
        pending_statuses = {"queued", "running", "ready"}
        return [job for job in jobs if (job["status"] in pending_statuses) is pending]

    def cancel(self, job_id: str) -> dict | None:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        with self.lock, self.conn:
            row = self.conn.execute(
                "SELECT id FROM replan_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            self.conn.execute(
                "UPDATE replan_jobs SET status='cancelled', phase='cancelled', "
                "message='Replaneamento cancelado pelo utilizador', error=NULL, "
                "updated_at=? WHERE id=? AND status IN ('queued','running','ready')",
                (now, job_id),
            )
            self._prune_locked()
            self.conn.commit()
        return self.get(job_id)


class ReplanJobManager:
    def __init__(self, store: ReplanJobStore | None = None) -> None:
        self.store = store or ReplanJobStore()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="replan")
        self.commit_lock = commit_lock

    def start(
        self,
        *,
        engine_data,
        config,
        dataset_id: str,
        base_revision: int,
        reason: str,
        dataset_info: dict | None = None,
        preparation_warnings: list[str] | None = None,
        baseline_snapshot: dict | None = None,
        prefer_unchanged_baseline: bool = False,
        allow_unchanged_baseline_apply: bool = False,
        reoptimize_relaxed_baseline: bool = False,
        request_fingerprint: str | None = None,
        base_input_fingerprints: dict | None = None,
    ) -> dict:
        if baseline_snapshot is not None:
            captured_fingerprints = replan_base_fingerprints(baseline_snapshot)
            if (
                base_input_fingerprints is not None
                and base_input_fingerprints != captured_fingerprints
            ):
                raise ValueError("Os dados de base do replaneamento são inconsistentes.")
            base_input_fingerprints = captured_fingerprints
        job, created = self.store.create_or_get(
            reason,
            dataset_id,
            base_revision,
            request_fingerprint=request_fingerprint,
            base_input_fingerprints=base_input_fingerprints,
        )
        if not created:
            return {**job, "deduplicated": True}
        try:
            self.executor.submit(
                self._run,
                job["id"],
                copy.deepcopy(engine_data),
                copy.deepcopy(config),
                dataset_id,
                base_revision,
                reason,
                copy.deepcopy(dataset_info),
                list(preparation_warnings or []),
                copy.deepcopy(baseline_snapshot),
                bool(prefer_unchanged_baseline),
                bool(allow_unchanged_baseline_apply),
                bool(reoptimize_relaxed_baseline),
            )
        except Exception:
            logger.exception("Replan job %s could not be submitted", job["id"])
            self._fail(job["id"], "internal_error")
            raise
        return {**job, "deduplicated": False}

    def cancel(self, job_id: str) -> dict:
        with self.commit_lock:
            committed = self._committed_job(job_id)
            if committed is not None:
                return committed
            job = self.store.cancel(job_id)
        if job is None:
            raise ValueError(f"Trabalho {job_id} não existe.")
        return job

    def _committed_job(self, job_id: str) -> dict | None:
        """A durable application receipt wins over a failed status projection."""
        plans_store = state.plans_store
        if plans_store is None:
            return None
        for operation_id in (f"replan:{job_id}", f"replan-sync:{job_id}"):
            receipt = plans_store.mutation_receipt(operation_id)
            if receipt is None or receipt["status"] != "committed":
                continue
            response = receipt["response"]
            job = response.get("job", response)
            if job.get("id") == job_id and job.get("status") == "completed":
                return copy.deepcopy(job)
        return None

    def get(self, job_id: str) -> dict | None:
        return self._committed_job(job_id) or self.store.get(job_id)

    def list_jobs(self, *, dataset_id: str, base_revision: int, pending=None) -> list[dict]:
        jobs = [
            self._committed_job(job["id"]) or job
            for job in self.store.list_jobs(dataset_id=dataset_id, base_revision=base_revision)
        ]
        if pending is None:
            return jobs
        return [job for job in jobs if (job["status"] in {"queued", "running", "ready"}) is pending]

    def _is_cancelled(self, job_id: str) -> bool:
        job = self.store.get(job_id)
        return job is None or job["status"] in {"cancelled", "completed", "failed"}

    def _fail(
        self, job_id: str, code: str, error: str | None = None, causes: list[str] | None = None,
    ) -> None:
        message, default_error = FAILURE_TEXTS[code]
        self.store.update(
            job_id,
            status="failed",
            phase="failed",
            code=code,
            message=message,
            error=error or default_error,
            causes=list(causes or []),
        )

    @staticmethod
    def _optional_budget(optimizer_reserve_s: float = 0.0) -> float:
        """Budget for an optional pass inside the outer deadline (AGENTS §6).

        Always keeps the closing reserve; ``optimizer_reserve_s`` also keeps
        time for the complete constructor when the pass has no valid fallback.
        """
        return max(
            0.0,
            remaining_time(REPLAN_TOTAL_BUDGET_S)
            - closing_reserve(REPLAN_TOTAL_BUDGET_S)
            - optimizer_reserve_s,
        )

    @staticmethod
    def _local_calendar_repair(baseline, engine_data, config, freeze_day, budget_s, now=None):
        """Repair only the segments a calendar edit invalidated, within its budget.

        Only movable work is repaired (AGENTS §2 rule 4, §5): the production
        started before ``freeze_day``, the run mounted at that boundary, its
        mount suppliers and honoured anchors stay reserved and are spliced
        back unchanged (``frozen.repair_preserving_protected_lots``); the rest
        of a started lot is repaired as the same lot, never re-sized. The
        canonical normalisation keeps that rest where it is, as the
        improvement cycle's compaction does; the hard-constraint repair still
        moves it when the edit invalidates it.

        Works on a copy; the caller validates and compares the result. Raises
        PlanningTimeout when its own scope expires so the caller can fall back
        to the complete constructor with the remaining outer budget.
        """
        from backend.plans.frozen import repair_preserving_protected_lots
        from backend.scheduler.alternative_repair import repair_alternative_machine_delivery
        from backend.scheduler.campaign_tail import (
            campaign_tail_warnings,
            repair_short_runs_after_merged_campaigns,
        )
        from backend.scheduler.jit_policy import calendar_holidays
        from backend.scheduler.scheduler import (
            _fix_orphan_continuations,
            _repair_hard_constraints,
            normalize_earliest_legal_plan,
        )

        alternative_moves = False
        tail_warnings: list[str] = []

        def repair(segments, lots, started_rests):
            nonlocal alternative_moves
            holidays = calendar_holidays(engine_data, -14, engine_data.n_days + 60)
            segments = _repair_hard_constraints(segments, engine_data, config, holidays)
            segments = _fix_orphan_continuations(segments)
            segments = normalize_earliest_legal_plan(
                segments, lots, engine_data, config, protected_lot_ids=started_rests,
            )
            alternative = repair_alternative_machine_delivery(
                segments, lots, engine_data, config,
            )
            segments, lots = alternative.segments, alternative.lots
            if alternative.moves:
                alternative_moves = True
                segments = normalize_earliest_legal_plan(
                    segments, lots, engine_data, config, protected_lot_ids=started_rests,
                )
            campaign_tail = repair_short_runs_after_merged_campaigns(
                segments, lots, engine_data, config,
            )
            if campaign_tail.moves:
                segments = campaign_tail.segments
                tail_warnings.extend(campaign_tail_warnings(campaign_tail))
            return segments, lots

        with planning_scope(timeout_s=budget_s):
            repaired = repair_preserving_protected_lots(
                baseline, engine_data, config, freeze_day, repair, now=now,
            )
        for warning in tail_warnings:
            if warning not in repaired.warnings:
                repaired.warnings.append(warning)
        return repaired, alternative_moves

    def _rebuild_after_capacity_release(
        self, job_id, engine_data, config, baseline, compacted, history_changes, now=None,
    ):
        """The complete constructor when compaction leaves a delivery late with idle capacity.

        Runs in the remaining optional budget (the compaction left it a
        reserve) and is taken only when the single comparator prefers it to
        the compacted plan with no individual order losing
        (``_prefer_no_loss_plan``) and it keeps the started production. On
        timeout or failure returns ``None``: the compacted plan stays.
        """
        from backend.cpo import optimize

        try:
            with planning_scope(timeout_s=self._optional_budget()):
                rebuilt = optimize_preserving_started_lots(
                    engine_data, config, baseline,
                    mode="normal", audit=True, optimizer=optimize, now=now,
                )
        except PlanningTimeout:
            planning_checkpoint()
            logger.info("Replan %s: constructor after capacity release stopped by its budget",
                        job_id)
            return None
        except (RuntimeError, TypeError, ValueError):
            logger.info("Replan %s: constructor after capacity release failed", job_id,
                        exc_info=True)
            return None
        if history_changes(rebuilt) or not _prefer_no_loss_plan(rebuilt, compacted, engine_data):
            return None
        rebuilt.warnings = [
            *rebuilt.warnings,
            "Capacidade libertada: o recálculo completo deu um plano melhor do que "
            "reorganizar o plano ativo.",
        ]
        return rebuilt

    def _continue_compaction(self, job_id, engine_data, config, compacted, now=None):
        """A second compaction pass from ``compacted`` in the remaining budget.

        Every accepted move is already validated and no-loss, so the first
        pass is kept on timeout, failure or a delivery regression.
        """
        from backend.scheduler.priority import delivery_not_worse

        try:
            with planning_scope(timeout_s=self._optional_budget()):
                again = compact_preserving_started_lots(
                    engine_data, config, copy.deepcopy(compacted), now=now,
                )
        except PlanningTimeout:
            planning_checkpoint()
            return compacted
        except (RuntimeError, TypeError, ValueError):
            logger.info("Replan %s: second compaction rejected", job_id, exc_info=True)
            return compacted
        return again if delivery_not_worse(again.score, compacted.score) else compacted

    def _run(self, job_id: str, *args, **kwargs) -> None:
        from backend import calendar as factory_calendar

        # One "now" for the whole job (AGENTS §2 rule 4, 13/10/2026): the
        # planning day, today's elapsed minutes, the protection, the
        # idle-capacity check and, at apply, the commit guard use it.
        now = factory_calendar.factory_now(None)
        try:
            with planning_scope(
                timeout_s=REPLAN_TOTAL_BUDGET_S,
                cancelled=lambda: self._is_cancelled(job_id),
            ), factory_calendar.fixed_factory_clock(now):
                with released_anchor_ledger():
                    self._run_planning(job_id, *args, now=now, **kwargs)
        except PlanningCancelled:
            # Also raised at scope exit after the job already failed; the store
            # never overwrites a terminal status.
            self.store.update(
                job_id,
                status="cancelled",
                phase="cancelled",
                message="Replaneamento cancelado",
                error=None,
            )
        except PlanningStopped:
            logger.exception("Replan job %s exhausted its planning budget", job_id)
            self._fail(job_id, "planning_timeout")

    def _run_planning(
        self,
        job_id: str,
        engine_data,
        config,
        dataset_id: str,
        base_revision: int,
        reason: str,
        dataset_info: dict | None,
        preparation_warnings: list[str] | None = None,
        baseline_snapshot: dict | None = None,
        prefer_unchanged_baseline: bool = False,
        allow_unchanged_baseline_apply: bool = False,
        reoptimize_relaxed_baseline: bool = False,
        now: datetime | None = None,
    ) -> None:
        from backend.config.planning import synchronize_active_twin_groups
        from backend.config.types import PLANNING_POLICY_VERSION
        from backend.cpo import optimize
        from backend.plans.serialize import (
            MODEL_VERSION,
            deserialize_snapshot,
            planning_input_fingerprints,
        )
        from backend.scheduler.gates import blocked_application_message, build_gate_report
        from backend.scheduler.operators import compute_operator_alerts
        from backend.scheduler.priority import delivery_not_worse
        from backend.scheduler.scoring import compute_score
        from backend.scheduler.validation import PlanValidationError, assert_plan_valid
        from backend.simulator.mutations import reapply_calendar_mutations
        from backend.transform.calendars import apply_calendars

        try:
            job_record = self.store.get(job_id) or {}
            if not job_record.get("base_input_fingerprints"):
                # Calculation-only compatibility: legacy origins cannot apply.
                # Public API jobs capture the complete origin in start().
                self.store.update(
                    job_id,
                    base_input_fingerprints={
                        "legacy": planning_input_fingerprints(engine_data, config)
                    },
                )
            synchronize_active_twin_groups(engine_data, config.twins)
            baseline_result = None
            historical_baseline_result = None
            baseline_comparable = False
            baseline_model_compatible = False
            active_mutations = []
            rebuild_warnings: list[str] = []
            # Last complete plan known valid for the NEW inputs. Optional
            # passes (compaction, constructor) never discard it (AGENTS §6).
            valid_fallback = None
            if baseline_snapshot is not None:
                restored_baseline = deserialize_snapshot(baseline_snapshot)
                active_mutations = copy.deepcopy(restored_baseline.get("active_mutations", []))
                historical_baseline_result = restored_baseline["result"]
                # Notes of how the active plan was calculated are not true of
                # this calculation, whichever plan it keeps.
                historical_baseline_result.warnings = without_calculation_notes(
                    historical_baseline_result.warnings,
                )
                baseline_model_compatible = (
                    restored_baseline.get("model_version") == MODEL_VERSION
                    and restored_baseline.get("planning_policy_version") == PLANNING_POLICY_VERSION
                )
                if baseline_model_compatible and _baseline_needs_material_rebuild(
                    restored_baseline
                ):
                    baseline_model_compatible = False
                    from backend.scheduler.canonical import legacy_material_reason

                    reason = legacy_material_reason(historical_baseline_result.lots)
                    rebuild_warnings.append(
                        f"O plano ativo foi calculado {reason}; por isso foi "
                        "recalculado de raiz."
                    )
                baseline_comparable = baseline_model_compatible and planning_input_fingerprints(
                    restored_baseline["engine_data"],
                    restored_baseline["config"],
                ) == planning_input_fingerprints(engine_data, config)
                if baseline_comparable or (
                    (prefer_unchanged_baseline or reoptimize_relaxed_baseline)
                    and baseline_model_compatible
                ):
                    baseline_result = restored_baseline["result"]
            if self._is_cancelled(job_id):
                return
            self.store.update(
                job_id,
                status="running",
                progress=10,
                phase="preparing",
                message="A preparar dados e calendários",
            )
            if self._is_cancelled(job_id):
                return
            apply_calendars(engine_data, config)
            reapply_calendar_mutations(engine_data, active_mutations, config)
            if now is None:
                from backend.calendar import factory_now

                now = factory_now(config)
            freeze_day = _current_planning_day(engine_data, config, now)
            now_min = elapsed_on_planning_day(freeze_day, engine_data, config, now)
            # The plan's history boundary (AGENTS §2 rule 4): every validation
            # of this job's plans, its apply and its commit judge the inputs
            # only from this instant on (``scheduler.history``).
            from backend.scheduler.canonical import stored_history_boundary

            engine_data.history_boundary = stored_history_boundary(
                planning_boundary(freeze_day, now_min),
            )
            frozen_segments, frozen_lots = _frozen_started_lots(
                historical_baseline_result, freeze_day, now_min,
            )

            def history_changes(candidate) -> list[str]:
                # The commit guard, before a candidate is offered.
                return candidate_history_changes(
                    baseline_snapshot, candidate, engine_data, config,
                    freeze_day=freeze_day, now=now,
                )

            baseline_score = None
            selected_source = "optimized"
            result = None
            if reoptimize_relaxed_baseline and baseline_result is not None:
                original_baseline_score = dict(baseline_result.score or {})
                # Releasing capacity keeps the active plan legal: it is the
                # fallback if compaction and the constructor cannot finish.
                valid_fallback = _valid_delivery_floor(baseline_result, engine_data, config)
                # A late delivery with idle capacity before its deadline: the
                # compaction keeps time for the complete constructor, which
                # may find what it cannot.
                rebuild_reserve = (
                    LOCAL_REPAIR_OPTIMIZER_RESERVE_S
                    if valid_fallback is not None
                    and _late_with_idle_capacity(
                        valid_fallback, engine_data, config, freeze_day, now,
                    )
                    else 0.0
                )
                self.store.update(
                    job_id,
                    progress=45,
                    phase="compacting",
                    message="A reorganizar o plano com a capacidade libertada",
                )
                try:
                    with planning_scope(timeout_s=self._optional_budget(rebuild_reserve)):
                        compacted = compact_preserving_started_lots(
                            engine_data,
                            config,
                            copy.deepcopy(baseline_result),
                            now=now,
                        )
                    if not delivery_not_worse(
                        compacted.score,
                        original_baseline_score,
                    ):
                        raise ValueError(
                            "A compactação piorava o compromisso de entrega."
                        )
                except PlanningTimeout:
                    planning_checkpoint()
                    logger.info("Replan %s: compaction stopped by its budget", job_id)
                    result = None
                except (RuntimeError, TypeError, ValueError):
                    logger.info("Replan %s: compaction rejected", job_id, exc_info=True)
                    result = None
                else:
                    baseline_score = original_baseline_score
                    result = compacted
                    selected_source = "compacted_baseline_after_capacity_release"
                    if rebuild_reserve and _late_with_idle_capacity(
                        compacted, engine_data, config, freeze_day, now,
                    ):
                        self.store.update(
                            job_id,
                            progress=55,
                            phase="optimizing",
                            message="A procurar o melhor plano completo",
                        )
                        rebuilt = self._rebuild_after_capacity_release(
                            job_id, engine_data, config, historical_baseline_result,
                            compacted, history_changes, now,
                        )
                        if rebuilt is not None:
                            result = rebuilt
                            selected_source = "optimized_after_capacity_release"
                    elif rebuild_reserve:
                        # Nothing left for the constructor to recover: the
                        # compaction goes on with the time kept for it.
                        result = self._continue_compaction(
                            job_id, engine_data, config, compacted, now,
                        )
            if prefer_unchanged_baseline and baseline_result is not None:
                original_baseline_score = dict(baseline_result.score or {})
                self.store.update(
                    job_id,
                    progress=55,
                    phase="validating",
                    message="A confirmar se o plano atual continua válido",
                )
                try:
                    assert_plan_valid(
                        baseline_result.segments,
                        engine_data,
                        config,
                        lots=baseline_result.lots,
                    )
                except (TypeError, ValueError) as invalid:
                    self.store.update(
                        job_id,
                        progress=65,
                        phase="repairing",
                        message="A ajustar apenas os segmentos afetados",
                    )
                    local_budget = self._optional_budget(LOCAL_REPAIR_OPTIMIZER_RESERVE_S)
                    invalidated = _invalidated_segments(invalid)
                    try:
                        if invalidated > LOCAL_REPAIR_MAX_INVALID_SEGMENTS:
                            raise _WideCalendarEdit(invalidated)
                        if local_budget <= 0:
                            raise PlanningTimeout("No budget left for local repair.")
                        repaired, alternative_moves = self._local_calendar_repair(
                            baseline_result,
                            engine_data,
                            config,
                            freeze_day,
                            local_budget,
                            now,
                        )
                        assert_plan_valid(
                            repaired.segments,
                            engine_data,
                            config,
                            lots=repaired.lots,
                        )
                        # The commit refuses a change to started production;
                        # such a candidate is never offered (the complete
                        # constructor replans around it instead).
                        changed = history_changes(repaired)
                        if changed:
                            raise _ProtectedHistoryChanged(changed)
                        repaired.score = compute_score(
                            repaired.segments,
                            repaired.lots,
                            engine_data,
                            config=config,
                        )
                        if not delivery_not_worse(
                            repaired.score,
                            original_baseline_score,
                        ):
                            raise ValueError("O ajuste rápido piorava o compromisso de entrega.")
                        repaired.operator_alerts = compute_operator_alerts(
                            repaired.segments,
                            engine_data,
                            config=config,
                        )
                    except _WideCalendarEdit:
                        logger.info(
                            "Replan %s: %d segments invalidated; complete constructor",
                            job_id, invalidated,
                        )
                        baseline_result = None
                        rebuild_warnings.append(
                            f"A alteração afeta {invalidated} "
                            f"{'segmento' if invalidated == 1 else 'segmentos'} do plano "
                            "ativo; o plano foi recalculado por completo."
                        )
                    except PlanningTimeout:
                        # Only the local scope expired: the outer deadline or a
                        # cancellation still stop the job here.
                        planning_checkpoint()
                        logger.info(
                            "Replan %s: local calendar repair stopped by its %.1f s budget",
                            job_id, local_budget,
                        )
                        baseline_result = None
                        rebuild_warnings.append(
                            "O ajuste rápido não terminou a tempo; o plano foi "
                            "recalculado por completo."
                        )
                    except (RuntimeError, TypeError, ValueError):
                        logger.info("Replan %s: local calendar repair rejected", job_id,
                                    exc_info=True)
                        baseline_result = None
                    else:
                        repaired.warnings = [
                            *list(repaired.warnings),
                            "Calendário aplicado com um ajuste rápido do plano ativo.",
                        ]
                        if alternative_moves:
                            repaired.warnings.append(
                                "Máquinas alternativas: entregas recuperadas no plano "
                                "ativo com uma máquina alternativa."
                            )
                        baseline_score = original_baseline_score
                        result = repaired
                        selected_source = "repaired_baseline_calendar"
                else:
                    from backend.scheduler.shift_exchange import repair_shift_capacity_exchange

                    # The active plan is valid for the new calendar: an optional
                    # shift exchange may improve it but never replaces it.
                    try:
                        with planning_scope(timeout_s=self._optional_budget()):
                            exchanged = repair_shift_capacity_exchange(
                                copy.deepcopy(baseline_result.segments),
                                copy.deepcopy(baseline_result.lots),
                                engine_data,
                                config,
                            )
                    except PlanningTimeout:
                        planning_checkpoint()
                        exchanged = None
                    exchange_applied = exchanged is not None and (
                        exchanged != baseline_result.segments
                    )
                    if exchange_applied:
                        exchange = copy.copy(baseline_result)
                        exchange.segments = exchanged
                        if history_changes(exchange):
                            # Never offered: started production stays as it is.
                            exchange_applied = False
                    if exchange_applied:
                        baseline_result.segments = exchanged
                        baseline_result.warnings.append(
                            "Troca entre turnos validada após atualizar o calendário."
                        )
                        selected_source = "calendar_compatible_shift_exchange"
                    baseline_result.score = compute_score(
                        baseline_result.segments,
                        baseline_result.lots,
                        engine_data,
                        config=config,
                    )
                    baseline_score = dict(baseline_result.score)
                    result = baseline_result
                    if not exchange_applied:
                        selected_source = "unchanged_baseline_calendar_compatible"

            if result is None:
                self.store.update(
                    job_id,
                    progress=35,
                    phase="optimizing",
                    message="A procurar o melhor plano completo",
                )
                try:
                    with planning_scope(
                        timeout_s=self._optional_budget()
                    ):
                        result = optimize_preserving_started_lots(
                            engine_data, config, historical_baseline_result,
                            mode="normal", audit=True, optimizer=optimize, now=now,
                        )
                except (PlanningTimeout, PlanValidationError):
                    if valid_fallback is None:
                        raise
                    # The active plan stays valid for the new inputs: an
                    # unfinished or invalid rebuild never discards it.
                    planning_checkpoint()
                    logger.info("Replan %s: constructor failed; keeping the valid plan",
                                job_id, exc_info=True)
                    result = valid_fallback
                    baseline_score = dict(valid_fallback.score)
                    selected_source = "unchanged_baseline_after_capacity_release"
                    result.warnings.append(
                        "O recálculo completo não terminou; foi mantido o plano ativo, "
                        "que continua válido com a alteração."
                    )
                if self._is_cancelled(job_id):
                    return

            # Notes about an earlier calculation travel with a kept plan; the
            # legacy-material note is true only of the calculation that wrote
            # it, never of a plan already under the current material contract.
            result.warnings = _without_stale_legacy_warnings(
                result.warnings, result.lots, rebuild_warnings,
            )
            if rebuild_warnings and selected_source == "optimized":
                result.warnings = [*rebuild_warnings, *list(result.warnings)]
            if frozen_lots and selected_source in {"optimized", "optimized_after_capacity_release"}:
                from backend.scheduler.canonical import result_validation_data

                engine_data = result_validation_data(engine_data, result)

            if (
                baseline_comparable
                and baseline_result is not None
                and result is not baseline_result
            ):
                original_floor = _valid_delivery_floor(
                    baseline_result, engine_data, config
                )
                try:
                    with planning_scope(
                        timeout_s=self._optional_budget()
                    ):
                        baseline_result = compact_preserving_started_lots(
                            engine_data, config, baseline_result, now=now,
                        )
                except PlanningTimeout:
                    planning_checkpoint()
                    baseline_result = original_floor
                except PlanValidationError:
                    baseline_result = original_floor
                    if original_floor is None:
                        result.warnings.append(
                            "O plano ativo deixou de ser uma referência válida após "
                            "a alteração de recursos; foi conservado o candidato novo."
                        )
                else:
                    baseline_result.score = compute_score(
                        baseline_result.segments,
                        baseline_result.lots,
                        engine_data,
                        config=config,
                    )
                    if original_floor is not None and not _prefer_no_loss_plan(
                        baseline_result, original_floor, engine_data,
                    ):
                        baseline_result = original_floor
                if baseline_result is not None:
                    baseline_score = dict(baseline_result.score)
                    if not _prefer_no_loss_plan(result, baseline_result, engine_data):
                        baseline_result.warnings = [
                            *list(baseline_result.warnings),
                            (
                                "Foi mantido o melhor plano de base: o recálculo "
                                "não demonstrou uma melhoria sem perdas por encomenda."
                            ),
                        ]
                        result = baseline_result
                        selected_source = "normalized_baseline_delivery_floor"
            result.operator_alerts = compute_operator_alerts(
                result.segments,
                engine_data,
                config=config,
            )
            operational_keys = (
                "left_shift_opportunities",
                "lower_priority_campaign_interruptions",
                "avoidable_priority_order_anomalies",
            )
            operational_metrics = (result.gate_report or {}).get("metrics", {})
            # Lots started on earlier days keep the closeout off. During the
            # planning day (lots started before "now", or minutes already
            # gone) it runs on the residual with them and the elapsed time
            # reserved, as the calculation itself did (AGENTS §2 rule 4).
            closeout_allowed = not _frozen_started_lots(
                historical_baseline_result, freeze_day,
            )[1]
            protected_closeout = bool(frozen_lots) or now_min > 0
            if selected_source == "optimized" and closeout_allowed and any(
                int(operational_metrics.get(key, 0)) for key in operational_keys
            ):
                self.store.update(
                    job_id,
                    progress=72,
                    phase="operational_closeout",
                    message="A concluir prioridades e compactação do plano",
                )
                # Additional improvement is advisory. Never mutate the last
                # complete candidate until the entire repair validates.
                trial = copy.deepcopy(result)
                try:
                    with planning_scope(
                        timeout_s=self._optional_budget()
                    ):
                        # Priority and gap closeout goes through the single
                        # no-loss improvement cycle (plan-melhoria §5): no
                        # order may lose, no setup may be added.
                        from backend.scheduler.improvement import improve_plan

                        if protected_closeout:
                            # The stored plan enters here as the closeout's
                            # baseline: its upgraded lots record their
                            # productions at this calculation's boundary, as
                            # every other entry point does, so the rests and
                            # originals spliced back are judged
                            # (``validation.lot_split_violations``).
                            protected = _protected_plan(
                                with_current_material(
                                    historical_baseline_result, engine_data, config,
                                    planning_boundary(freeze_day, now_min),
                                ),
                                freeze_day, engine_data, config, now=now,
                            )
                            trial, improvement = improve_preserving_protected_lots(
                                trial, engine_data, copy.deepcopy(engine_data), config,
                                protected.segments, protected.lots, freeze_day,
                                time_budget_s=float(remaining_time(60.0) or 0.0),
                                partial=protected.partial, now=now,
                                cut=protected.cut, pinned=protected.pinned,
                            )
                        else:
                            trial.segments, trial.lots, improvement = improve_plan(
                                trial.segments, trial.lots, engine_data, config,
                            )
                        if improvement.get("moves_accepted"):
                            assert_plan_valid(trial.segments, engine_data, config, lots=trial.lots)
                            trial.score = compute_score(
                                trial.segments, trial.lots, engine_data, config=config
                            )
                            trial.gate_report = build_gate_report(
                                trial.segments, trial.lots, trial.score, engine_data, config,
                            )
                            trial.operator_alerts = compute_operator_alerts(
                                trial.segments, engine_data, config=config
                            )
                            planning_checkpoint()
                            result = copy.deepcopy(trial)
                            selected_source = "optimized_priority_repaired"
                        result.improvement_report = {
                            **(getattr(result, "improvement_report", None) or {}),
                            **improvement,
                        }
                except PlanningTimeout:
                    planning_checkpoint()
            assert_plan_valid(
                result.segments,
                engine_data,
                config,
                lots=result.lots,
            )
            # Last line of defence: a candidate the commit would refuse for
            # changing started production is never offered (no HTTP 500 later).
            changed_history = history_changes(result)
            if changed_history:
                raise _ProtectedHistoryChanged(changed_history)
            if frozen_lots:
                frozen_warning = preserved_lots_warning(
                    len(frozen_lots), freeze_day,
                    boundary_label(freeze_day, now_min, engine_data),
                )
                result.warnings = [
                    warning for warning in result.warnings
                    if not warning.startswith("Plano anterior preservado:")
                    or warning == frozen_warning
                ]
                if frozen_warning not in result.warnings:
                    result.warnings.append(frozen_warning)
            can_reuse_optimizer_gate = bool(
                result.gate_report
                and "physical_gate_passed" in result.gate_report
                and "coverage_gate_passed" in result.gate_report
                and selected_source in {"optimized", "optimized_priority_repaired"}
            )
            if not can_reuse_optimizer_gate:
                result.gate_report = build_gate_report(
                    result.segments,
                    result.lots,
                    result.score,
                    engine_data,
                    config,
                )
            unchanged_resource_relaxation = bool(
                allow_unchanged_baseline_apply
                and historical_baseline_result is not None
                and result.segments == historical_baseline_result.segments
                and result.lots == historical_baseline_result.lots
            )
            if unchanged_resource_relaxation:
                result.gate_report = _allow_unchanged_resource_relaxation(
                    result.gate_report
                )
                result.warnings.append(
                    "A alteração apenas liberta capacidade e mantém integralmente "
                    "o plano ativo; os alertas preexistentes não impedem guardar "
                    "a configuração."
                )
            if preparation_warnings:
                result.warnings = list(preparation_warnings) + list(result.warnings)
            from backend.scheduler.improvement import attach_improvement_summary

            if not baseline_comparable and selected_source in {
                "unchanged_baseline_calendar_compatible",
                "calendar_compatible_shift_exchange", "repaired_baseline_calendar",
                "unchanged_baseline_after_capacity_release",
            }:
                result.improvement_report = {
                    "status": "not_evaluated", "stop_reason": "inputs_changed",
                }
            attach_improvement_summary(result, engine_data, config)
            self.store.update(
                job_id,
                progress=85,
                phase="validating",
                message="A validar recursos, quantidades e exceções",
            )
            physical_or_coverage_invalid = not (
                result.gate_report.get("physical_gate_passed")
                and result.gate_report.get("coverage_gate_passed")
            )
            if physical_or_coverage_invalid:
                raise _BlockedCandidate(
                    blocked_application_message(result.gate_report),
                    (result.gate_report or {}).get("violations"),
                )
            if self._is_cancelled(job_id):
                return
            # A pin released by a calculation the job then discarded is gone
            # from the staging data too: the planner is told (AGENTS §2).
            result = with_released_anchor_notices(
                result, released_anchor_notices_missing(engine_data),
            )
            candidate = _result_snapshot(
                engine_data,
                config,
                result,
                plan_revision=base_revision,
                dataset_info=dataset_info,
                mutations=active_mutations,
            )
            planning_checkpoint()
            self.store.update(
                job_id,
                status="ready",
                progress=100,
                phase="ready",
                message=(
                    blocked_application_message(result.gate_report)
                    if result.gate_report.get("apply_decision") == "blocked"
                    else "Candidato pronto para validação e aplicação"
                ),
                warnings=result.warnings,
                candidate=candidate,
                result={
                    "score": result.score,
                    "gate_report": result.gate_report,
                    "improvement_report": result.improvement_report,
                    "n_segments": len(result.segments),
                    "baseline_comparable": baseline_comparable,
                    "baseline_score": baseline_score,
                    "selected_source": selected_source,
                    "unchanged_resource_relaxation": unchanged_resource_relaxation,
                    # The commit guard reads history at this instant.
                    "planning_now": now.isoformat(),
                },
            )
        except PlanningStopped:
            raise
        except _ProtectedHistoryChanged as exc:
            logger.error(
                "Replan %s: candidate changes started production: %s",
                job_id, ", ".join(exc.lot_ids[:5]),
            )
            self._fail(job_id, "history_protected")
        except _BlockedCandidate as exc:
            logger.exception("Replan job %s produced a blocked candidate", job_id)
            self._fail(
                job_id, "blocked", str(exc) or None,
                causes=_violation_causes(
                    exc, engine_data, (baseline_snapshot or {}).get("lots"),
                ),
            )
        except PlanValidationError as exc:
            from backend.plans.refusal import causes_for_log

            baseline_lots = (baseline_snapshot or {}).get("lots")
            logger.exception(
                "Replan job %s produced no valid plan: %s", job_id,
                causes_for_log(exc, engine_data, baseline_lots),
            )
            self._fail(
                job_id, "invalid_plan",
                causes=_violation_causes(exc, engine_data, baseline_lots),
            )
        except Exception:  # defensive job boundary: never show raw (English) text
            logger.exception("Replan job %s failed unexpectedly", job_id)
            self._fail(job_id, "internal_error")

    def apply(
        self,
        job_id: str,
        *,
        expected_revision: int,
        approve_exceptions: bool = False,
        approval_reason: str = "",
        approval_author: str = "",
    ) -> dict:
        """Atomically apply one ready candidate at most once."""
        from backend.plans.transactions import run_sync_mutation

        with self.commit_lock:
            return run_sync_mutation(
                state,
                lambda: self._apply_locked(
                    job_id,
                    expected_revision=expected_revision,
                    approve_exceptions=approve_exceptions,
                    approval_reason=approval_reason,
                    approval_author=approval_author,
                ),
                operation_id=f"replan-sync:{job_id}",
                request_fingerprint=canonical_replan_fingerprint(
                    dataset_id="",
                    base_revision=expected_revision,
                    request={
                        "job_id": job_id,
                        "approve_exceptions": approve_exceptions,
                        "approval_reason": approval_reason,
                        "approval_author": approval_author,
                    },
                ),
            )

    def _apply_locked(
        self,
        job_id: str,
        *,
        expected_revision: int,
        approve_exceptions: bool = False,
        approval_reason: str = "",
        approval_author: str = "",
    ) -> dict:
        from backend.config.loader import save_config
        from backend.config.planning import validate_active_twin_eco_lots
        from backend.config.types import PLANNING_POLICY_VERSION
        from backend.plans.context import after_commit, before_commit
        from backend.plans.serialize import (
            MODEL_VERSION,
            assert_snapshot_integrity,
            deserialize_snapshot,
            serialize_snapshot,
        )
        from backend.scheduler.gates import authorize_application, build_gate_report
        from backend.scheduler.priority import delivery_not_worse
        from backend.scheduler.scoring import compute_score
        from backend.simulator.mutations import reapply_calendar_mutations
        from backend.transform.calendars import apply_calendars

        job = self.get(job_id)
        if job is None:
            raise ValueError(f"Trabalho {job_id} não existe.")
        if job["status"] == "completed":
            return job
        if job["status"] != "ready":
            raise ValueError("O candidato ainda não está pronto ou já foi aplicado.")
        # A candidate is applied the day it was calculated, while it is
        # recent: the factory moved on since (AGENTS §2 rule 4).
        planning_now = (job.get("result") or {}).get("planning_now")
        assert_fresh_calculation(planning_now, state.config)
        current_id = str((state.dataset_info or {}).get("id", ""))
        if current_id != job["dataset_id"]:
            raise ValueError("O ISOP mudou durante o cálculo; o candidato ficou obsoleto.")
        if int(expected_revision) != int(state.plan_revision) or int(job["base_revision"]) != int(
            state.plan_revision
        ):
            raise ValueError("Revisão obsoleta: o plano mudou durante o cálculo.")
        base_fingerprints = job.get("base_input_fingerprints")
        if (
            not base_fingerprints
            or not base_fingerprints.get("origin")
            or base_fingerprints != replan_base_fingerprints(serialize_snapshot(state))
        ):
            raise ValueError("Os dados ou a configuração mudaram; recalcula o candidato.")

        candidate_payload = self.store.get_candidate(job_id)
        if candidate_payload is None:
            raise ValueError("O trabalho não contém um candidato aplicável.")
        assert_snapshot_integrity(candidate_payload)
        restored = deserialize_snapshot(candidate_payload)
        engine_data = restored["engine_data"]
        config = restored["config"]
        result = restored["result"]
        if config is None:
            raise ValueError("O candidato não contém configuração.")
        if (
            restored.get("model_version") != MODEL_VERSION
            or restored.get("planning_policy_version") != PLANNING_POLICY_VERSION
        ):
            raise ValueError(
                "O candidato usa uma política de planeamento anterior; "
                "executa novamente o replaneamento."
            )
        apply_calendars(engine_data, config)
        active_mutations = copy.deepcopy(restored.get("active_mutations", []))
        reapply_calendar_mutations(engine_data, active_mutations, config)
        validate_active_twin_eco_lots(engine_data)
        from backend.calendar import fixed_factory_clock
        from backend.scheduler.improvement import attach_improvement_summary

        # The gates read the job's own instant (the idle-capacity check
        # counts free time after it), as when the candidate was offered.
        with fixed_factory_clock(
            datetime.fromisoformat(planning_now) if planning_now else None,
        ):
            result.score = compute_score(
                result.segments,
                result.lots,
                engine_data,
                config=config,
            )
            result.gate_report = build_gate_report(
                result.segments,
                result.lots,
                result.score,
                engine_data,
                config,
            )
            attach_improvement_summary(result, engine_data, config)
        job_result = job.get("result") or {}
        from backend.plans.context import set_planning_now

        # The commit guard reads today's history at the job's own instant.
        set_planning_now(job_result.get("planning_now"))
        if job_result.get("unchanged_resource_relaxation"):
            candidate_schedule = restored.get("fingerprints", {}).get("schedule")
            base_schedule = (base_fingerprints or {}).get("schedule")
            if not candidate_schedule or candidate_schedule != base_schedule:
                raise ValueError(
                    "A alteração deixou de ser apenas de configuração; recalcula o candidato."
                )
            result.gate_report = _allow_unchanged_resource_relaxation(
                result.gate_report
            )
        baseline_score = job_result.get("baseline_score")
        if (
            job_result.get("baseline_comparable")
            and baseline_score
            and not delivery_not_worse(result.score, baseline_score)
        ):
            raise ValueError(
                "O candidato piora OTD/OTD-D ou os atrasos face ao plano ativo "
                "e não pode substituir esse plano."
            )
        approval = authorize_application(
            result.gate_report,
            approve_exceptions=approve_exceptions,
            approval_reason=approval_reason,
            approval_author=approval_author,
        )

        runtime_snapshot = {
            field: copy.deepcopy(getattr(state, field)) for field in _REPLAN_TRANSACTION_FIELDS
        }
        previous_config = copy.deepcopy(state.config)
        config_persisted = False
        try:
            # The configuration file and durable plan snapshot form the
            # commit. Any failure restores the exact live state and config.
            save_config(config)
            config_persisted = True
            state.engine_data = engine_data
            state.config = config
            state.current_machine_states = list(engine_data.current_machine_states)
            from backend.plans.manual_edits import sync_manual_edits

            sync_manual_edits(state)
            state.active_mutations = active_mutations
            if approval is not None:
                state.approvals.append({**approval, "action": "replan_apply", "job_id": job_id})
            state.update_schedule(
                result,
                plan_source="auto",
                plan_note=job["reason"],
                require_persistence=True,
            )
        except Exception:
            for field, value in runtime_snapshot.items():
                setattr(state, field, value)
            if config_persisted and previous_config is not None:
                try:
                    save_config(previous_config)
                except Exception:
                    logger.exception("Failed to restore config after replan rollback")
            raise
        changes = dict(
            status="completed",
            phase="completed",
            message="Novo plano aplicado",
            result={
                **(job.get("result") or {}),
                "score": result.score,
                "gate_report": result.gate_report,
                "improvement_report": result.improvement_report,
                "plan_revision": state.plan_revision,
            },
        )

        def validate_ready_for_commit():
            latest = self.store.get(job_id)
            if latest is None or latest["status"] != "ready":
                raise ValueError("O candidato foi cancelado ou deixou de estar pronto.")

        before_commit(validate_ready_for_commit)
        after_commit(lambda: self.store.update(job_id, **changes))
        return {**job, **changes}


manager = ReplanJobManager()
