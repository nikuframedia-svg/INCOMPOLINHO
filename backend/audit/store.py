"""Audit Store — Spec 07 §6.

SQLite persistence for audit trails.
"""

from __future__ import annotations

import json
import os
import sqlite3
from threading import RLock

from .types import AuditTrail

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "audit.db")
DEFAULT_DB_PATH = os.path.join(
    os.environ.get("PP1_DATA_DIR", os.path.dirname(DEFAULT_DB_PATH)), "audit.db"
)


class AuditStore:
    """SQLite-backed audit trail storage."""

    def __init__(self, db_path: str | None = None) -> None:
        self._path = db_path or DEFAULT_DB_PATH
        if self._path != ":memory:":
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._lock = RLock()
        # FastAPI executes synchronous endpoints in worker threads.  The
        # singleton CopilotState therefore shares this store across threads.
        # Access is serialized below so the single connection remains safe.
        from backend.runtime_guard import assert_writable

        assert_writable(self._path)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT (datetime('now')),
                    score_json TEXT,
                    n_decisions INTEGER,
                    label TEXT
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT,
                    schedule_id TEXT,
                    phase TEXT,
                    subject_id TEXT,
                    action TEXT,
                    chosen TEXT,
                    rule TEXT,
                    binding_constraint TEXT,
                    alternatives_json TEXT,
                    explanation_pt TEXT,
                    FOREIGN KEY (schedule_id) REFERENCES schedules(id)
                );
                CREATE INDEX IF NOT EXISTS idx_decisions_schedule
                    ON decisions(schedule_id);
                CREATE INDEX IF NOT EXISTS idx_decisions_subject
                    ON decisions(subject_id);
            """)
            self._conn.commit()

    def save_trail(
        self,
        trail: AuditTrail,
        score: dict,
        label: str = "",
    ) -> str:
        """Save an audit trail. Returns the schedule_id."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO schedules VALUES (?, datetime('now'), ?, ?, ?)",
                (trail.schedule_id, json.dumps(score), trail.total_decisions, label),
            )
            # A schedule id identifies one exact trail. Re-saving it must
            # replace, rather than append to, its decisions.
            self._conn.execute(
                "DELETE FROM decisions WHERE schedule_id=?",
                (trail.schedule_id,),
            )
            for d in trail.decisions:
                alts_json = json.dumps(
                    [{"value": a.value, "reason": a.reason} for a in d.alternatives]
                )
                self._conn.execute(
                    "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        d.id,
                        trail.schedule_id,
                        d.phase,
                        d.subject_id,
                        d.action,
                        d.chosen,
                        d.rule,
                        d.binding_constraint,
                        alts_json,
                        d.explanation_pt,
                    ),
                )
        return trail.schedule_id

    def load_decisions(
        self,
        schedule_id: str,
        subject_id: str | None = None,
    ) -> list[dict]:
        """Load decisions for a schedule, optionally filtered by subject."""
        with self._lock:
            if subject_id:
                rows = self._conn.execute(
                    "SELECT * FROM decisions WHERE schedule_id=? AND subject_id=?",
                    (schedule_id, subject_id),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM decisions WHERE schedule_id=?",
                    (schedule_id,),
                ).fetchall()

        cols = [
            "id",
            "schedule_id",
            "phase",
            "subject_id",
            "action",
            "chosen",
            "rule",
            "binding_constraint",
            "alternatives_json",
            "explanation_pt",
        ]
        return [dict(zip(cols, r)) for r in rows]

    def list_schedules(self, limit: int = 20) -> list[dict]:
        """List recent schedules."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, created_at, score_json, n_decisions, label "
                "FROM schedules ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "created_at": r[1],
                "score": json.loads(r[2]) if r[2] else {},
                "n_decisions": r[3],
                "label": r[4],
            }
            for r in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
