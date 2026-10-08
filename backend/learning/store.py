"""Learning Store — Spec 08 §10.

SQLite persistence for learning history.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sqlite3

from .types import ISContext, SchedulerParams, StudyResult

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "learning.db")
DEFAULT_DB_PATH = os.path.join(
    os.environ.get("PP1_DATA_DIR", os.path.dirname(DEFAULT_DB_PATH)), "learning.db"
)


class LearnStore:
    """SQLite-backed learning history storage."""

    def __init__(self, db_path: str | None = None) -> None:
        self._path = db_path or DEFAULT_DB_PATH
        if self._path != ":memory:":
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
        from backend.runtime_guard import assert_writable

        assert_writable(self._path)
        self._conn = sqlite3.connect(self._path)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS studies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT (datetime('now')),
                context_json TEXT,
                best_params_json TEXT,
                reward REAL,
                baseline_reward REAL,
                n_trials INTEGER,
                confidence TEXT,
                isop_label TEXT
            );
        """)
        self._conn.commit()

    def save_study(
        self,
        context: ISContext,
        result: StudyResult,
        label: str = "",
    ) -> int:
        """Save a study result. Returns the row id."""
        cursor = self._conn.execute(
            "INSERT INTO studies "
            "(context_json, best_params_json, reward, baseline_reward, "
            "n_trials, confidence, isop_label) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                json.dumps(dataclasses.asdict(context)),
                json.dumps(result.best_params.to_dict()),
                result.best_reward,
                result.best_reward - result.improvement.get("reward", 0),
                result.n_trials,
                result.confidence,
                label,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def load_history(self, limit: int = 50) -> list[dict]:
        """Load recent studies."""
        rows = self._conn.execute(
            "SELECT created_at, context_json, best_params_json, "
            "reward, baseline_reward, n_trials, confidence, isop_label "
            "FROM studies ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "created_at": r[0],
                "context": json.loads(r[1]) if r[1] else {},
                "best_params": json.loads(r[2]) if r[2] else {},
                "reward": r[3],
                "baseline_reward": r[4],
                "n_trials": r[5],
                "confidence": r[6],
                "isop_label": r[7],
            }
            for r in rows
        ]

    def load_best_params(self) -> SchedulerParams | None:
        """Load best params from history (highest reward)."""
        row = self._conn.execute(
            "SELECT best_params_json FROM studies ORDER BY reward DESC LIMIT 1"
        ).fetchone()
        if row and row[0]:
            return SchedulerParams.from_dict(json.loads(row[0]))
        return None

    def close(self) -> None:
        self._conn.close()
