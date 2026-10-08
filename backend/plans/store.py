"""SQLite store for persistent production-plan snapshots."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from threading import RLock
from uuid import uuid4

DEFAULT_DB_PATH = (
    Path(os.environ.get("PP1_DATA_DIR", Path(__file__).resolve().parents[2] / "data")) / "plans.db"
)
logger = logging.getLogger(__name__)
METADATA_COLUMNS = (
    "id,created_at,name,source,origin,note,is_auto,otd,otd_d,tardy_count,setups,gate_status"
)


def _assert_activatable_payload(payload: dict) -> None:
    if (
        not (payload.get("dataset_info") or {}).get("id")
        and not payload.get("segments")
        and not payload.get("lots")
    ):
        return
    from backend.plans.serialize import deserialize_plan_core
    from backend.scheduler.validation import (
        PlanValidationError,
        assert_plan_valid,
        plan_anchor_violations,
    )

    config, engine_data, segments, lots = deserialize_plan_core(payload)
    assert_plan_valid(segments, engine_data, config, lots=lots)
    anchor_errors = plan_anchor_violations(segments, engine_data, config)
    if anchor_errors:
        raise PlanValidationError(anchor_errors)


class PlansStore:
    """Small, thread-safe SQLite store with denormalized list metadata."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = str(db_path or DEFAULT_DB_PATH)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        from backend.runtime_guard import assert_writable

        assert_writable(self._path)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    origin TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    is_auto INTEGER NOT NULL DEFAULT 0,
                    otd REAL,
                    otd_d REAL,
                    tardy_count INTEGER,
                    setups INTEGER,
                    gate_status TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_plans_created
                    ON plans(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_plans_auto_created
                    ON plans(is_auto, created_at DESC);
                CREATE TABLE IF NOT EXISTS load_jobs (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plan_mutations (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plan_runtime (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    snapshot_id TEXT REFERENCES plans(id) ON DELETE RESTRICT,
                    plan_revision INTEGER NOT NULL
                );
                """
            )
            self._conn.commit()
            # Adopt the legacy startup selection exactly once. A later missing
            # or corrupt active snapshot is an error, never a historical restore.
            with self._conn:
                if (
                    self._conn.execute("SELECT 1 FROM plan_runtime WHERE singleton=1").fetchone()
                    is None
                ):
                    legacy = self.latest()
                    self._conn.execute(
                        "INSERT INTO plan_runtime VALUES (1,?,?)",
                        (legacy["id"] if legacy else None,
                         int(legacy["payload"].get("plan_revision", 0)) if legacy else 0),
                    )

    @staticmethod
    def _metadata(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "name": row["name"],
            "source": row["source"],
            "origin": row["origin"],
            "note": row["note"],
            "is_auto": bool(row["is_auto"]),
            "otd": row["otd"],
            "otd_d": row["otd_d"],
            "tardy_count": row["tardy_count"],
            "setups": row["setups"],
            "gate_status": row["gate_status"],
        }

    def save(
        self,
        *,
        name: str,
        source: str,
        origin: str,
        note: str,
        payload: dict,
        score: dict,
        gate_report: dict | None,
        is_auto: bool,
        activate: bool = False,
    ) -> dict:
        from backend.plans.serialize import assert_snapshot_integrity

        assert_snapshot_integrity(payload, origin=origin)
        if activate:
            _assert_activatable_payload(payload)
        plan_id = uuid4().hex
        gate_status = (gate_report or {}).get("status")
        with self._lock, self._conn:
            if activate:
                self._assert_historical_unchanged_locked(payload)
            self._conn.execute(
                """
                INSERT INTO plans (
                    id, name, source, origin, note, is_auto,
                    otd, otd_d, tardy_count, setups, gate_status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    name,
                    source,
                    origin,
                    note,
                    int(is_auto),
                    score.get("otd"),
                    score.get("otd_d"),
                    score.get("tardy_count"),
                    score.get("setups"),
                    gate_status,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            if activate:
                self._activate_locked(plan_id, int(payload.get("plan_revision", 0)))
            row = self._conn.execute(
                f"SELECT {METADATA_COLUMNS} FROM plans WHERE id = ?", (plan_id,)
            ).fetchone()
        return self._metadata(row)

    def list(
        self, limit: int = 100, *, source: str | None = None, exclude_scenarios=False
    ) -> list[dict]:
        safe_limit = max(1, min(int(limit), 500))
        where = "WHERE source = ?" if source is not None else (
            "WHERE source != 'scenario'" if exclude_scenarios else ""
        )
        params = (source, safe_limit) if source is not None else (safe_limit,)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {METADATA_COLUMNS} FROM plans {where} "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._metadata(row) for row in rows]

    def get(self, plan_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        if row is None:
            return None
        return {**self._metadata(row), "payload": json.loads(row["payload_json"])}

    def latest(self, *, include_scenarios: bool = False) -> dict | None:
        """Legacy recovery selection, not the identity of the active plan."""
        from backend.plans.serialize import snapshot_integrity_errors

        with self._lock:
            where = "" if include_scenarios else "WHERE source != 'scenario'"
            rows = self._conn.execute(
                f"SELECT * FROM plans {where} ORDER BY created_at DESC, rowid DESC"
            )
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                    errors = snapshot_integrity_errors(payload, origin=row["origin"])
                except (TypeError, ValueError):
                    errors = ["unreadable payload"]
                if errors:
                    logger.error("Ignoring inconsistent persisted plan %s: %s", row["id"], errors)
                    continue
                return {**self._metadata(row), "payload": payload}
        return None

    def _activate_locked(self, plan_id: str, revision: int) -> None:
        self._conn.execute(
            "UPDATE plan_runtime SET snapshot_id=?,plan_revision=? WHERE singleton=1",
            (plan_id, revision),
        )

    def _assert_historical_unchanged_locked(self, payload: dict) -> None:
        from backend.plans.frozen import historical_schedule_changes

        row = self._conn.execute(
            "SELECT p.payload_json FROM plans p "
            "JOIN plan_runtime r ON r.snapshot_id=p.id WHERE r.singleton=1"
        ).fetchone()
        if row is None:
            return
        changed = historical_schedule_changes(json.loads(row[0]), payload)
        if changed:
            raise ValueError(
                "historical_plan_protected: lotes iniciados antes de hoje "
                f"não podem mudar: {', '.join(changed[:5])}"
            )

    def runtime_identity(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT snapshot_id,plan_revision FROM plan_runtime WHERE singleton=1"
            ).fetchone()
            if row is None:
                raise ValueError("active_plan_invalid: identidade ativa ausente")
            return dict(row)

    def _assert_recalculation_context_locked(self, payload: dict) -> None:
        row = self._conn.execute(
            "SELECT p.payload_json FROM plans p "
            "JOIN plan_runtime r ON r.snapshot_id=p.id WHERE r.singleton=1"
        ).fetchone()
        if row is None:
            return
        before = json.loads(row[0])
        if (before.get("dataset_info") or {}).get("id") != (
            payload.get("dataset_info") or {}
        ).get("id"):
            raise ValueError("recalculation_context: o ISOP mudou")
        # A past date is not execution. Observations and intentional anchors
        # are real constraints and must survive this special recalculation.
        old_data, new_data = before.get("engine_data") or {}, payload.get("engine_data") or {}
        for field in ("plan_anchors", "current_machine_states", "committed_supplies"):
            if old_data.get(field, []) != new_data.get(field, []):
                raise ValueError(f"recalculation_context: restricao alterada: {field}")

    def active(self) -> dict | None:
        from backend.plans.serialize import snapshot_integrity_errors

        with self._lock:
            runtime = self._conn.execute(
                "SELECT snapshot_id,plan_revision FROM plan_runtime WHERE singleton=1"
            ).fetchone()
            if runtime is None:
                raise ValueError("active_plan_invalid: identidade ativa ausente")
            if runtime[0] is None:
                return None
            try:
                plan = self.get(runtime[0])
                if plan is None or plan["source"] == "scenario":
                    raise ValueError("snapshot ausente ou cenario")
                errors = snapshot_integrity_errors(plan["payload"], origin=plan["origin"])
                if errors or int(plan["payload"].get("plan_revision", 0)) != runtime[1]:
                    raise ValueError(str(errors or "revisao divergente"))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"active_plan_invalid: {runtime[0]}: {exc}") from exc
            return plan

    def delete(self, plan_id: str) -> bool:
        with self._lock, self._conn:
            if self._conn.execute(
                "SELECT 1 FROM plan_runtime WHERE snapshot_id=?", (plan_id,)
            ).fetchone():
                raise ValueError("active_plan_protected")
            cursor = self._conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        return cursor.rowcount > 0

    def prune_auto(self, keep: int = 20) -> int:
        with self._lock, self._conn:
            return self._prune_auto_locked(keep)

    def _prune_auto_locked(self, keep: int = 20) -> int:
        cursor = self._conn.execute(
            """
                DELETE FROM plans
                WHERE is_auto = 1
                  AND source != 'scenario'
                  AND id NOT IN (SELECT snapshot_id FROM plan_runtime WHERE snapshot_id IS NOT NULL)
                  AND id NOT IN (
                    SELECT json_extract(payload_json, '$.old_active_snapshot') FROM plan_mutations
                    WHERE status='preparing'
                      AND json_extract(payload_json, '$.old_active_snapshot') IS NOT NULL
                  )
                  AND id NOT IN (
                    SELECT id FROM plans
                    WHERE is_auto = 1
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                  )
                """,
            (max(0, int(keep)),),
        )
        return cursor.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def mutation_receipt(self, operation_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT fingerprint,status,payload_json FROM plan_mutations WHERE id=?",
                (operation_id,),
            ).fetchone()
        if row is None:
            return None
        return {"fingerprint": row[0], "status": row[1], **json.loads(row[2])}

    def pending_mutations(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,payload_json FROM plan_mutations WHERE status='preparing'"
            ).fetchall()
        return [{"id": row[0], **json.loads(row[1])} for row in rows]

    def prepare_mutation(self, operation_id: str, fingerprint: str, journal: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO plan_mutations(id,fingerprint,status,payload_json) VALUES (?,?,?,?)",
                (operation_id, fingerprint, "preparing", json.dumps(journal, ensure_ascii=False)),
            )

    def abort_mutation(self, operation_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM plan_mutations WHERE id=? AND status='preparing'", (operation_id,)
            )

    def commit_mutation(
        self, operation_id: str, payload: dict | None, response, *, source: str,
        recalculate_from_start: bool = False,
    ) -> None:
        from backend.plans.serialize import assert_snapshot_integrity

        if payload is not None:
            assert_snapshot_integrity(payload)
            _assert_activatable_payload(payload)
        score = (payload or {}).get("score") or {}
        gate = (payload or {}).get("gate_report") or {}
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT status,payload_json FROM plan_mutations WHERE id=?", (operation_id,)
            ).fetchone()
            if row is None or row[0] != "preparing":
                raise ValueError("A operacao ja nao pode ser confirmada.")
            journal = json.loads(row[1])
            if recalculate_from_start and journal.get("recalculate_from_start") is not True:
                raise ValueError("recalculation_scope: falta autorizacao interna do recalculo")
            if payload is not None:
                if recalculate_from_start:
                    self._assert_recalculation_context_locked(payload)
                else:
                    self._assert_historical_unchanged_locked(payload)
                plan_id = uuid4().hex
                self._conn.execute(
                    "INSERT INTO plans(id,name,source,origin,note,is_auto,otd,otd_d,tardy_count,"
                    "setups,gate_status,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        plan_id,
                        "Plano aplicado",
                        source,
                        str((payload.get("dataset_info") or {}).get("filename", "")),
                        operation_id,
                        1,
                        score.get("otd"),
                        score.get("otd_d"),
                        score.get("tardy_count"),
                        score.get("setups"),
                        gate.get("status"),
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                self._activate_locked(plan_id, int(payload["plan_revision"]))
            else:
                self._conn.execute(
                    "UPDATE plan_runtime SET plan_revision=? WHERE singleton=1",
                    (json.loads(row[1])["plan_revision"],),
                )
            journal.update(response=response, plan_revision=(payload or journal)["plan_revision"])
            self._conn.execute(
                "UPDATE plan_mutations SET status='committed',payload_json=? WHERE id=?",
                (json.dumps(journal, ensure_ascii=False), operation_id),
            )
            self._prune_auto_locked()

    def load_job(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM load_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def load_jobs(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT payload_json FROM load_jobs").fetchall()
        return [json.loads(row[0]) for row in rows]

    def create_load_job(self, job: dict, fingerprint: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO load_jobs(id,fingerprint,status,payload_json) VALUES (?,?,?,?)",
                (job["id"], fingerprint, job["status"], json.dumps(job, ensure_ascii=False)),
            )

    def load_fingerprint(self, job_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT fingerprint FROM load_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        return row[0] if row else None

    def update_load_job(self, job: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE load_jobs SET status=?,payload_json=? WHERE id=?",
                (job["status"], json.dumps(job, ensure_ascii=False), job["id"]),
            )

    def commit_load(self, job: dict, *, plan_id: str, payload_json: str) -> dict:
        """Validate and persist a snapshot and its receipt in ONE transaction.

        Called only by the load coordinator under the plan mutation lock, after
        validating the base revision. The durable boundary checks the exact
        payload again so a stale gate report cannot activate an invalid plan.
        """
        result = job["result"]
        score = result["score"]
        with self._lock, self._conn:
            previous = self._conn.execute(
                "SELECT status,payload_json FROM load_jobs WHERE id=?",
                (job["id"],),
            ).fetchone()
            if previous is None:
                raise ValueError("O carregamento não existe.")
            if previous[0] == "applied":
                return json.loads(previous[1])
            if previous[0] != "running":
                raise ValueError("O carregamento já não pode ser aplicado.")
            from backend.plans.serialize import assert_snapshot_integrity

            payload = json.loads(payload_json)
            assert_snapshot_integrity(payload, origin=job["filename"])
            _assert_activatable_payload(payload)
            self._conn.execute(
                """INSERT INTO plans (
                    id,name,source,origin,note,is_auto,otd,otd_d,tardy_count,
                    setups,gate_status,payload_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    plan_id,
                    "Plano carregado",
                    "load",
                    job["filename"],
                    f"{job['filename']}; carregamento {job['id']}; estado inicial: all_free",
                    1,
                    score.get("otd"),
                    score.get("otd_d"),
                    score.get("tardy_count"),
                    score.get("setups"),
                    (job.get("gate_report") or {}).get("status"),
                    payload_json,
                ),
            )
            self._conn.execute(
                "UPDATE load_jobs SET status='applied',payload_json=? WHERE id=?",
                (json.dumps(job, ensure_ascii=False), job["id"]),
            )
            self._activate_locked(plan_id, int(payload.get("plan_revision", 0)))
            operation_id = f"load:{job['id']}"
            journal_row = self._conn.execute(
                "SELECT payload_json FROM plan_mutations WHERE id=? AND status='preparing'",
                (operation_id,),
            ).fetchone()
            if journal_row is not None:
                journal = json.loads(journal_row[0])
                journal["response"] = result
                self._conn.execute(
                    "UPDATE plan_mutations SET status='committed',payload_json=? WHERE id=?",
                    (json.dumps(journal, ensure_ascii=False), operation_id),
                )
            self._prune_auto_locked()
        return job
