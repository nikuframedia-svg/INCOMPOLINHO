"""Persistent background jobs for fixed-plan robustness batteries."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.risk.robustness import run_robustness_battery

UTC = timezone.utc  # noqa: UP017 - Python 3.10 compatibility
DEFAULT_DB_PATH = Path(
    os.environ.get("PP1_DATA_DIR", Path(__file__).resolve().parents[2] / "data")
) / "robustness.db"
TERMINAL = {"completed", "cancelled", "failed", "interrupted"}


class RobustnessJobStore:
    def __init__(
        self, path: str | Path | None = None, *, worker_id: str | None = None,
        worker_pid: int | None = None,
    ) -> None:
        self._path = str(path or DEFAULT_DB_PATH)
        self.worker_id = worker_id or uuid4().hex
        self.worker_pid = os.getpid() if worker_pid is None else worker_pid
        self.worker_started = self._process_identity(self.worker_pid)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS robustness_jobs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    samples INTEGER NOT NULL,
                    seed INTEGER NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    dataset_fingerprint TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_robustness_jobs_created
                    ON robustness_jobs(created_at DESC);
                """
            )
            columns = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(robustness_jobs)")
            }
            for name, sql_type in (
                ("worker_id", "TEXT"), ("worker_pid", "INTEGER"), ("worker_started", "TEXT"),
            ):
                if name not in columns:
                    self._conn.execute(f"ALTER TABLE robustness_jobs ADD COLUMN {name} {sql_type}")
            self._conn.commit()

    @staticmethod
    def _process_identity(pid: int | None) -> str | None:
        if not pid or pid <= 0:
            return None
        try:
            # The command name can contain spaces and parentheses.
            stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            return f"{boot}:{stat[19]}"
        except (OSError, IndexError):
            return None

    def _interrupted(self, row: sqlite3.Row) -> bool:
        if row["status"] in TERMINAL or row["worker_id"] == self.worker_id:
            return False
        pid = row["worker_pid"]
        if not pid or pid <= 0:
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        identity = self._process_identity(pid)
        return bool(row["worker_started"] and identity and row["worker_started"] != identity)

    def _serialize(self, row: sqlite3.Row) -> dict:
        interrupted = self._interrupted(row)
        payload = {
            "id": row["id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "status": "interrupted" if interrupted else row["status"],
            "profile": row["profile"],
            "samples": row["samples"],
            "seed": row["seed"],
            "progress": row["progress"],
            "dataset_fingerprint": row["dataset_fingerprint"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": "Processo reiniciado durante a análise" if interrupted else row["error"],
        }
        if interrupted:
            payload["stored_status"] = row["status"]
        return payload

    def create(
        self,
        *,
        profile: str,
        samples: int,
        seed: int,
        dataset_fingerprint: str,
    ) -> dict:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        job_id = uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO robustness_jobs "
                "(id,created_at,updated_at,status,profile,samples,seed,progress,"
                "dataset_fingerprint,worker_id,worker_pid,worker_started) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, now, now, "queued", profile, samples, seed, 0, dataset_fingerprint,
                 self.worker_id, self.worker_pid, self.worker_started),
            )
            self._conn.commit()
        return self.get(job_id)

    def update(self, job_id: str, **changes) -> dict | None:
        allowed = {"status", "progress", "result", "error"}
        values = {key: value for key, value in changes.items() if key in allowed}
        if not values:
            return self.get(job_id)
        if "result" in values:
            values["result_json"] = json.dumps(
                values.pop("result"), ensure_ascii=False, separators=(",", ":")
            )
        values["updated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
        columns = ", ".join(
            "status=CASE WHEN status='cancelling' THEN 'cancelled' ELSE ? END"
            if key == "status" and value in {"completed", "failed"} else f"{key}=?"
            for key, value in values.items()
        )
        with self._lock, self._conn:
            # SQL transitions remain safe across separate store connections.
            expected = "status='queued'" if values.get("status") == "running" else (
                "status IN ('queued','running','cancelling')"
            )
            self._conn.execute(
                f"UPDATE robustness_jobs SET {columns} WHERE id=? "  # noqa: S608
                f"AND {expected} AND worker_id=?",
                (*values.values(), job_id, self.worker_id),
            )
            self._conn.commit()
        return self.get(job_id)

    def request_cancel(self, job_id: str) -> dict | None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE robustness_jobs SET status='cancelling',updated_at=? "
                "WHERE id=? AND status IN ('queued','running')",
                (datetime.now(UTC).replace(microsecond=0).isoformat(), job_id),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM robustness_jobs WHERE id=?", (job_id,)
            ).fetchone()
        return self._serialize(row) if row is not None else None

    def latest(self) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM robustness_jobs ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        return self._serialize(row) if row is not None else None


class RobustnessJobManager:
    def __init__(self, store: RobustnessJobStore | None = None) -> None:
        self.store = store or RobustnessJobStore()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="robustness")
        self._cancel: dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    def start(
        self,
        *,
        profile: str,
        samples: int,
        seed: int,
        dataset_fingerprint: str,
        segments,
        lots,
        engine_data,
        config,
    ) -> dict:
        job = self.store.create(
            profile=profile,
            samples=samples,
            seed=seed,
            dataset_fingerprint=dataset_fingerprint,
        )
        cancel_event = threading.Event()
        with self._lock:
            self._cancel[job["id"]] = cancel_event
        try:
            self._executor.submit(
                self._run, job["id"], profile, samples, seed,
                segments, lots, engine_data, config, cancel_event,
            )
        except Exception as exc:
            with self._lock:
                self._cancel.pop(job["id"], None)
            self.store.update(job["id"], status="failed", error=str(exc))
            raise
        return job

    def _run(
        self,
        job_id: str,
        profile: str,
        samples: int,
        seed: int,
        segments,
        lots,
        engine_data,
        config,
        cancel_event: threading.Event,
    ) -> None:
        def cancelled() -> bool:
            current = self.store.get(job_id)
            return cancel_event.is_set() or current is None or current["status"] in {
                "cancelling", "cancelled", "interrupted",
            }

        def progress(done: int, total: int) -> None:
            self.store.update(job_id, progress=round(done / max(total, 1) * 100))

        try:
            current = self.store.update(job_id, status="running", progress=0, error=None)
            if current is None or current["status"] in TERMINAL:
                return
            if cancelled():
                self.store.update(job_id, status="cancelled")
                return
            result = run_robustness_battery(
                segments,
                lots,
                engine_data,
                config,
                n_samples=samples,
                seed=seed,
                profile=profile,
                progress=progress,
                cancelled=cancelled,
            )
            if cancelled():
                self.store.update(job_id, status="cancelled", result=result)
            else:
                self.store.update(job_id, status="completed", progress=100, result=result)
        except Exception as exc:  # pragma: no cover - defensive job boundary
            self.store.update(job_id, status="failed", error=str(exc))
        finally:
            with self._lock:
                self._cancel.pop(job_id, None)

    def cancel(self, job_id: str) -> dict | None:
        job = self.store.request_cancel(job_id)
        if job is None or job["status"] != "cancelling":
            return job
        with self._lock:
            event = self._cancel.get(job_id)
        if event is not None:
            event.set()
        return self.store.get(job_id)


manager = RobustnessJobManager()
