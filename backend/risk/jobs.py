"""Persistent background jobs for fixed-plan robustness batteries.

Robustness is information only (AGENTS.md §1). An automatic job runs after
every published plan revision on a deep copy taken under the commit lock; its
result lives only in ``robustness.db`` and never touches the plan, its score,
its gate report or its approval.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import queue
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from backend.risk.robustness import (
    PROFILE_SAMPLES,
    ROBUSTNESS_HORIZON_WORKDAYS,
    ROBUSTNESS_MODEL_VERSION,
    run_robustness_battery,
)

logger = logging.getLogger(__name__)

UTC = timezone.utc  # noqa: UP017 - Python 3.10 compatibility
DEFAULT_DB_PATH = Path(
    os.environ.get("PP1_DATA_DIR", Path(__file__).resolve().parents[2] / "data")
) / "robustness.db"
TERMINAL = {"completed", "cancelled", "failed", "interrupted"}
ACTIVE = ("queued", "running", "cancelling")
TRIGGERS = {"auto", "manual"}
AUTO_PROFILE = "standard"
AUTO_SEED = 42
AUTO_ENV = "PP1_AUTO_ROBUSTNESS"


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
        from backend.runtime_guard import assert_writable

        assert_writable(self._path)
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
                ("trigger", "TEXT"), ("plan_revision", "INTEGER"),
                ("horizon_workdays", "INTEGER"), ("model_version", "INTEGER"),
                ("anchor_day", "INTEGER"), ("input_key", "TEXT"),
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
        result = json.loads(row["result_json"]) if row["result_json"] else None
        stored_result = result if isinstance(result, dict) else {}
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
            # Rows from before the automatic job were always started by hand.
            "trigger": row["trigger"] or "manual",
            "plan_revision": row["plan_revision"],
            "horizon_workdays": (
                row["horizon_workdays"]
                if row["horizon_workdays"] is not None
                else stored_result.get("horizon_workdays")
            ),
            "model_version": (
                row["model_version"]
                if row["model_version"] is not None
                else stored_result.get("model_version")
            ),
            "anchor_day": row["anchor_day"],
            "result": result,
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
        trigger: str = "manual",
        plan_revision: int | None = None,
        horizon_workdays: int | None = ROBUSTNESS_HORIZON_WORKDAYS,
        model_version: int = ROBUSTNESS_MODEL_VERSION,
        anchor_day: int | None = None,
        input_key: str | None = None,
    ) -> dict:
        if trigger not in TRIGGERS:
            raise ValueError(f"Origem de análise inválida: {trigger}")
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        job_id = uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO robustness_jobs "
                "(id,created_at,updated_at,status,profile,samples,seed,progress,"
                "dataset_fingerprint,worker_id,worker_pid,worker_started,"
                "trigger,plan_revision,horizon_workdays,model_version,anchor_day,input_key) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, now, now, "queued", profile, samples, seed, 0, dataset_fingerprint,
                 self.worker_id, self.worker_pid, self.worker_started,
                 trigger, plan_revision, horizon_workdays, model_version, anchor_day, input_key),
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

    def rebind(
        self, job_id: str, *, plan_revision: int | None, dataset_fingerprint: str,
    ) -> dict | None:
        """Point an analysis at a newer revision whose replayed inputs are identical."""

        with self._lock, self._conn:
            updated = self._conn.execute(
                "UPDATE robustness_jobs SET plan_revision=?,dataset_fingerprint=? "
                "WHERE id=? AND status IN ('queued','running','completed')",
                (plan_revision, dataset_fingerprint, job_id),
            ).rowcount
        # Cancelled in the meantime: the caller starts a fresh analysis instead.
        return self.get(job_id) if updated else None

    def input_key(self, job_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT input_key FROM robustness_jobs WHERE id=?", (job_id,)
            ).fetchone()
        return row["input_key"] if row is not None else None

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

    def latest(self, trigger: str | None = None) -> dict | None:
        where, params = ("WHERE trigger=? ", (trigger,)) if trigger == "auto" else (
            ("WHERE trigger IS NULL OR trigger=? ", (trigger,)) if trigger == "manual" else ("", ())
        )
        with self._lock:
            row = self._conn.execute(
                f"SELECT * FROM robustness_jobs {where}"  # noqa: S608 - fixed fragments
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                params,
            ).fetchone()
        return self._serialize(row) if row is not None else None

    def active_ids(self, trigger: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM robustness_jobs WHERE trigger=? AND status IN (?,?,?) "
                "ORDER BY created_at, rowid",
                (trigger, *ACTIVE),
            ).fetchall()
        return [row["id"] for row in rows]


class _DaemonWorker:
    """One daemon thread for automatic jobs: it never holds up process exit."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._closed = False

    def submit(self, fn, *args) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("robustness worker closed")
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name=self._name, daemon=True)
                self._thread.start()
            self._queue.put((fn, args))

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            fn, args = item
            try:
                fn(*args)
            except Exception:  # pragma: no cover - _run already records failures
                logger.exception("Automatic robustness job crashed")

    def shutdown(self, wait_s: float = 0.0) -> None:
        with self._lock:
            self._closed = True
            self._queue.put(None)
            thread = self._thread
        if wait_s > 0 and thread is not None and thread is not threading.current_thread():
            thread.join(wait_s)


class RobustnessJobManager:
    def __init__(self, store: RobustnessJobStore | None = None) -> None:
        self.store = store or RobustnessJobStore()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="robustness")
        # Automatic jobs compete with planning for the GIL: one at a time.
        self._auto_worker = _DaemonWorker("robustness-auto")
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
        trigger: str = "manual",
        plan_revision: int | None = None,
        anchor_day: int | None = None,
        input_key: str | None = None,
    ) -> dict:
        with self._lock:
            if trigger == "auto":
                # Only the newest published revision deserves the worker.
                for job_id in self.store.active_ids("auto"):
                    self.cancel(job_id)
            job = self.store.create(
                profile=profile,
                samples=samples,
                seed=seed,
                dataset_fingerprint=dataset_fingerprint,
                trigger=trigger,
                plan_revision=plan_revision,
                anchor_day=anchor_day,
                input_key=input_key,
            )
            cancel_event = threading.Event()
            self._cancel[job["id"]] = cancel_event
        submit = self._auto_worker.submit if trigger == "auto" else self._executor.submit
        try:
            submit(
                self._run, job["id"], profile, samples, seed,
                segments, lots, engine_data, config, cancel_event, anchor_day,
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
        anchor_day: int | None = None,
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
                anchor_day=anchor_day,
                # Never compete with (and so never influence) a plan search.
                yield_to_planning=True,
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

    def shutdown(self, wait_s: float = 0.0) -> None:
        """Stop running batteries so they never delay a process restart."""

        with self._lock:
            events = list(self._cancel.values())
        for event in events:
            event.set()
        self._auto_worker.shutdown(wait_s)
        self._executor.shutdown(wait=wait_s > 0, cancel_futures=True)


manager = RobustnessJobManager()
try:
    # Runs before the interpreter joins executor threads at exit.
    threading._register_atexit(manager.shutdown)  # noqa: SLF001
except (AttributeError, RuntimeError):  # pragma: no cover - interpreter specific
    pass


def auto_robustness_enabled() -> bool:
    return os.environ.get(AUTO_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True, slots=True)
class AutoSnapshot:
    """A detached, serialized image of one published revision."""

    plan_revision: int
    anchor_day: int
    blob: bytes


def detach_plan(segments, lots, engine_data, config, *extra) -> bytes:
    """Serialize plan objects; about 6x cheaper than ``copy.deepcopy`` on real plans."""

    return pickle.dumps(
        (segments, lots, engine_data, config, *extra), protocol=pickle.HIGHEST_PROTOCOL,
    )


def capture_auto_snapshot(state) -> AutoSnapshot | None:
    """Take the published revision under the commit lock; the only locked work.

    Everything else (fingerprints, dedupe, job row) happens afterwards on the
    caller's thread or a worker, never while other commits wait on the lock.
    """

    if not auto_robustness_enabled():
        return None
    from backend.api.locks import commit_lock
    from backend.copilot.state import state as live_state
    from backend.risk.plan_identity import planning_anchor_day

    # Sandbox and test states never replace the live plan's analysis.
    if state is not live_state:
        return None
    with commit_lock:
        if state.engine_data is None or state.config is None:
            return None
        return AutoSnapshot(
            plan_revision=int(state.plan_revision),
            anchor_day=planning_anchor_day(state.engine_data, state.config),
            blob=detach_plan(
                state.segments, state.lots, state.engine_data, state.config,
                state.dataset_info, state.active_mutations, state.manual_edits,
            ),
        )


def submit_auto_snapshot(
    snapshot: AutoSnapshot | None, *, job_manager: RobustnessJobManager | None = None,
) -> dict | None:
    """Start (or reuse) the automatic analysis of a captured revision.

    Reuse: when the newest automatic job replays exactly the same inputs from
    the same anchor (e.g. a rule edit that left the schedule untouched), it is
    pointed at the newer revision instead of running 500 scenarios again.
    """

    if snapshot is None:
        return None
    from backend.risk.plan_identity import (
        auto_input_key,
        plan_parts,
        robustness_dataset_fingerprint,
    )

    segments, lots, engine_data, config, dataset_info, mutations, edits = pickle.loads(
        snapshot.blob
    )
    view = SimpleNamespace(
        plan_revision=snapshot.plan_revision, dataset_info=dataset_info,
        engine_data=engine_data, config=config, segments=segments, lots=lots,
        active_mutations=mutations, manual_edits=edits,
    )
    parts = plan_parts(segments, lots, engine_data, config)
    fingerprint = robustness_dataset_fingerprint(view, parts=parts)
    input_key = auto_input_key(
        parts, anchor_day=snapshot.anchor_day, profile=AUTO_PROFILE, seed=AUTO_SEED,
    )
    target = job_manager or manager
    with target._lock:  # noqa: SLF001 - dedupe and start are one step
        existing = target.store.latest(trigger="auto")
        if existing is not None:
            if (existing["plan_revision"] or 0) > snapshot.plan_revision:
                logger.info(
                    "Automatic robustness skipped: revision %s is older than %s",
                    snapshot.plan_revision, existing["plan_revision"],
                )
                return None  # a newer revision was already handled
            if (
                existing["status"] in {"queued", "running", "completed"}
                and target.store.input_key(existing["id"]) == input_key
            ):
                if existing["dataset_fingerprint"] == fingerprint:
                    return existing
                rebound = target.store.rebind(
                    existing["id"],
                    plan_revision=snapshot.plan_revision,
                    dataset_fingerprint=fingerprint,
                )
                if rebound is not None:
                    return rebound
        return target.start(
            profile=AUTO_PROFILE,
            samples=PROFILE_SAMPLES[AUTO_PROFILE],
            seed=AUTO_SEED,
            dataset_fingerprint=fingerprint,
            segments=segments,
            lots=lots,
            engine_data=engine_data,
            config=config,
            trigger="auto",
            plan_revision=snapshot.plan_revision,
            anchor_day=snapshot.anchor_day,
            input_key=input_key,
        )


def enqueue_after_commit(state, *, job_manager: RobustnessJobManager | None = None) -> dict | None:
    """Start the informational analysis of the plan revision just published.

    Called by commit paths after publication (and at startup). The battery
    reads a detached copy taken under the commit lock and writes only to
    ``robustness.db``. Returns the job for this revision, or None when disabled
    or not applicable. Callers that hold the commit lock or run on the event
    loop use ``capture_auto_snapshot`` + ``submit_auto_snapshot`` instead.
    """

    return submit_auto_snapshot(capture_auto_snapshot(state), job_manager=job_manager)


_refresh_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="robustness-refresh")
_refresh_lock = threading.Lock()
_refresh_pending = False


def refresh_pending() -> bool:
    return _refresh_pending


def request_refresh(state) -> bool:
    """Queue a fresh automatic job from a request thread without doing the work.

    Used when the planning anchor moved (a new day) since the newest automatic
    job of this revision. Returns False when a refresh is already pending.
    """

    global _refresh_pending
    with _refresh_lock:
        if _refresh_pending:
            return False
        _refresh_pending = True

    def refresh() -> None:
        global _refresh_pending
        try:
            enqueue_after_commit(state)
        except Exception:
            logger.exception("Automatic robustness refresh failed")
        finally:
            with _refresh_lock:
                _refresh_pending = False

    try:
        _refresh_pool.submit(refresh)
    except RuntimeError:  # interpreter shutting down
        with _refresh_lock:
            _refresh_pending = False
        return False
    return True
