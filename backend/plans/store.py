"""SQLite store for persistent production-plan snapshots."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from threading import RLock
from uuid import uuid4

from backend.scheduler.validation import PlanValidationError

DEFAULT_DB_PATH = (
    Path(os.environ.get("PP1_DATA_DIR", Path(__file__).resolve().parents[2] / "data")) / "plans.db"
)
logger = logging.getLogger(__name__)
METADATA_COLUMNS = (
    "id,created_at,name,source,origin,note,is_auto,otd,otd_d,tardy_count,setups,gate_status,"
    "previous_snapshot_id,kind"
)
# «Desfazer» walks back at least this many versions; retention never prunes
# them (decisão de 15/10/2026).
HISTORY_KEEP_STEPS = 30
AUTO_KEEP = 20


class LegacyMaterialPlanError(PlanValidationError):
    """A plan saved before per-delivery material windows cannot be reactivated.

    It is not a physical conflict list for the planner to read: the plan must
    be rebuilt with the current rules (explicit recalculation). Callers route
    on ``code``/``requires_recalculation``; ``violations`` keeps the evidence.
    """

    code = "legacy_material_plan"
    requires_recalculation = True

    def __init__(self, violations: list[dict], reason: str | None = None) -> None:
        super().__init__(violations)
        reason = reason or "antes de o material passar a ser libertado por entrega"
        self.args = (
            f"Este plano foi calculado {reason} e já não cumpre as regras atuais. "
            "Use «Recalcular plano» para o reconstruir com as regras atuais; o "
            "plano guardado continua disponível no histórico.",
        )


class HistoricalPlanProtectedError(ValueError):
    """A plan would change production that started before the boundary (AGENTS §2, rule 4).

    Protected history, not a physical conflict: the plan as calculated cannot
    replace the active one, which stays untouched. ``lot_ids`` keeps the
    evidence; the message names references and machines, never lot ids.
    """

    code = "historical_plan_protected"

    def __init__(self, lot_ids: list[str], labels: list[str] | None = None) -> None:
        self.lot_ids = list(lot_ids)
        self.labels = list(labels or [])
        shown = "; ".join(self.labels[:5]) + ("; …" if len(self.labels) > 5 else "")
        super().__init__(
            "O plano proposto alteraria a produção anterior a hoje ou já feita hoje, "
            f"que está protegida{f' ({shown})' if shown else ''}."
        )

    @property
    def causes(self) -> list[str]:
        """Plain causes for ``plans/refusal.py`` (decisão de 15/10/2026)."""
        from backend.plans.refusal import MAX_CAUSES

        causes = [
            f"{label}: a produção já começou ou é anterior a agora e ficaria diferente."
            for label in self.labels[:MAX_CAUSES]
        ]
        if len(self.labels) > MAX_CAUSES:
            extra = len(self.labels) - MAX_CAUSES
            causes.append(f"… e mais {extra} {'lote' if extra == 1 else 'lotes'}.")
        return causes


class RecalculationContextChanged(ValueError):
    """«Recalcular plano»: its inputs changed while it was being calculated.

    A stale calculation, not a fault: the ISOP or a fixed constraint
    (manual positions, observed machine states, committed supply) is no
    longer the one the recalculation started from, so the plan as calculated
    cannot replace the active one, which stays untouched.
    """

    code = "recalculation_context"
    _LABELS = {
        "dataset": "o ISOP",
        "plan_anchors": "as posições manuais",
        "current_machine_states": "o estado observado das máquinas",
        "committed_supplies": "a oferta já comprometida",
    }

    def __init__(self, changed: str) -> None:
        self.changed = changed
        super().__init__(
            "Os dados de partida do recálculo mudaram durante o cálculo "
            f"({self._LABELS.get(changed, changed)})."
        )


def _lot_labels(lot_ids: list[str], *payloads: dict) -> list[str]:
    """``Referência 8718696125 (PRM042)`` for each lot id, from a snapshot."""

    lots: dict[str, dict] = {}
    for payload in reversed(payloads):
        lots.update({str(lot.get("id")): lot for lot in payload.get("lots") or []})
    labels = []
    for lot_id in lot_ids:
        lot = lots.get(str(lot_id))
        if lot is None:
            labels.append("um lote que já não existe no plano proposto")
            continue
        references = list(dict.fromkeys(
            str(output[1] or output[0]) for output in lot.get("twin_outputs") or []
        )) or [str(lot.get("sku") or lot.get("op_id") or "")]
        machine, tool = lot.get("machine_id"), lot.get("tool_id")
        labels.append(
            f"Referência {' + '.join(references)}" + (f" · {tool}" if tool else "")
            + (f" ({machine})" if machine else "")
        )
    return labels


def _assert_activatable_payload(payload: dict) -> None:
    if (
        not (payload.get("dataset_info") or {}).get("id")
        and not payload.get("segments")
        and not payload.get("lots")
    ):
        return
    from backend.plans.serialize import deserialize_plan_core
    from backend.scheduler.validation import assert_plan_valid, plan_anchor_violations

    config, engine_data, segments, lots = deserialize_plan_core(payload)
    assert_plan_valid(segments, engine_data, config, lots=lots)
    from backend.scheduler.canonical import source_contract_violations

    material_errors = source_contract_violations(
        segments, lots, engine_data, config, require_current_material=True,
    )
    if material_errors:
        from backend.scheduler.canonical import legacy_material_plan, legacy_material_reason

        if legacy_material_plan(lots, engine_data, config):
            raise LegacyMaterialPlanError(material_errors, legacy_material_reason(lots))
        raise PlanValidationError(material_errors)
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
            # Version history (decisão de 15/10/2026): the snapshot active
            # before each version, what «Desfazer» would put back and the name
            # of the change it undoes. Older rows keep NULL (no «Desfazer»).
            columns = {row[1] for row in self._conn.execute("PRAGMA table_info(plans)")}
            for column, ddl in (
                ("previous_snapshot_id", "TEXT"),
                ("undo_to", "TEXT"),
                ("undo_label", "TEXT"),
                ("kind", "TEXT NOT NULL DEFAULT ''"),
            ):
                if column not in columns:
                    self._conn.execute(f"ALTER TABLE plans ADD COLUMN {column} {ddl}")
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
            "previous_snapshot_id": row["previous_snapshot_id"],
            "kind": row["kind"],
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
        kind: str = "",
        inherit_undo: bool = False,
    ) -> dict:
        """``inherit_undo``: the same plan republished (startup recovery):
        «Desfazer» keeps undoing the change before it, not the republish."""
        from backend.plans.serialize import assert_snapshot_integrity

        assert_snapshot_integrity(payload, origin=origin)
        if activate:
            _assert_activatable_payload(payload)
        plan_id = uuid4().hex
        gate_status = (gate_report or {}).get("status")
        with self._lock, self._conn:
            history = (None, None, None)
            if activate:
                self._assert_historical_unchanged_locked(payload)
                history = self._history_locked(name, inherit=inherit_undo)
            self._conn.execute(
                """
                INSERT INTO plans (
                    id, name, source, origin, note, is_auto,
                    otd, otd_d, tardy_count, setups, gate_status, payload_json,
                    previous_snapshot_id, undo_to, undo_label, kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    *history,
                    kind,
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

    def _history_locked(
        self, name: str, *, undo_restores: str | None = None, inherit: bool = False,
    ) -> tuple[str | None, str | None, str | None]:
        """``(previous_snapshot_id, undo_to, undo_label)`` of a new active version.

        ``previous_snapshot_id`` is the version active before it. «Desfazer»
        puts back ``undo_to``: normally that previous version, whose change
        is this one (``undo_label``). An undo (``undo_restores``) or a
        republish (``inherit``) takes the place of the version it puts back,
        so the next «Desfazer» goes further back, never forward.
        """
        row = self._conn.execute(
            "SELECT snapshot_id FROM plan_runtime WHERE singleton=1"
        ).fetchone()
        previous = row[0] if row else None
        source = undo_restores or (previous if inherit else None)
        if source:
            restored = self._conn.execute(
                "SELECT undo_to,undo_label FROM plans WHERE id=?", (source,)
            ).fetchone()
            if restored is None:
                return previous, None, None
            return previous, restored[0], restored[1]
        return previous, previous, name if previous else None

    def undo_target(self) -> dict | None:
        """``{id, label}`` of the version «Desfazer» would put back, if kept.

        ``label`` is the name of the change that would be undone.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT p.undo_to,p.undo_label FROM plans p "
                "JOIN plan_runtime r ON r.snapshot_id=p.id WHERE r.singleton=1"
            ).fetchone()
            if row is None or not row[0]:
                return None
            target = self._conn.execute(
                "SELECT source FROM plans WHERE id=?", (row[0],)
            ).fetchone()
        if target is None or target[0] == "scenario":
            return None
        return {"id": row[0], "label": row[1] or "Plano aplicado"}

    def _activate_locked(self, plan_id: str, revision: int) -> None:
        self._conn.execute(
            "UPDATE plan_runtime SET snapshot_id=?,plan_revision=? WHERE singleton=1",
            (plan_id, revision),
        )

    def _assert_historical_unchanged_locked(
        self, payload: dict, *, now=None, undo_restores: str | None = None,
    ) -> None:
        """``now``: the instant the candidate was calculated at; today's
        production before it is history too (AGENTS §2 rule 4).

        The date of today is the real clock's at commit
        (``frozen.commit_instant``): a candidate calculated on an earlier date
        is refused; its own minute counts only on the same date.
        ``undo_restores``: the version a «Desfazer» puts back.
        """
        refusal = self._protected_changes_locked(payload, now=now, undo_restores=undo_restores)
        if refusal is not None:
            raise refusal

    def protected_changes(self, payload: dict, *, now=None, undo_restores: str | None = None):
        """The refusal that replacing the active plan by ``payload`` would
        meet at commit, or ``None``: the same rule, without raising."""
        with self._lock:
            return self._protected_changes_locked(payload, now=now, undo_restores=undo_restores)

    def _protected_changes_locked(
        self, payload: dict, *, now=None, undo_restores: str | None = None,
    ):
        """``undo_restores``: a «Desfazer» of the active version; the
        record-of-what-ran leeway (``frozen._declared_today``) applies only
        when it names the version the active one replaced."""
        from backend.plans.frozen import commit_instant, historical_schedule_changes

        row = self._conn.execute(
            "SELECT p.payload_json,p.undo_to FROM plans p "
            "JOIN plan_runtime r ON r.snapshot_id=p.id WHERE r.singleton=1"
        ).fetchone()
        if row is None:
            return None
        before = json.loads(row[0])
        today, now = commit_instant(
            now, str((before.get("config") or {}).get("timezone") or "Europe/Lisbon"),
        )
        undo = bool(undo_restores) and undo_restores == row[1]
        changed = historical_schedule_changes(before, payload, today=today, now=now, undo=undo)
        if not changed:
            return None
        return HistoricalPlanProtectedError(changed, _lot_labels(changed, payload, before))

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
            raise RecalculationContextChanged("dataset")
        # A past date is not execution. Observations are real constraints and
        # must survive this special recalculation. Manual anchors are released
        # by it (decisão de 15/10/2026) except the records of what ran
        # (20/10/2026): each anchor may only disappear, never change.
        old_data, new_data = before.get("engine_data") or {}, payload.get("engine_data") or {}
        for field in ("current_machine_states", "committed_supplies"):
            if old_data.get(field, []) != new_data.get(field, []):
                raise RecalculationContextChanged(field)

        def anchors(data: dict) -> list[dict]:
            return [
                {**anchor, "kind": anchor.get("kind") or ""}
                for anchor in data.get("plan_anchors") or [] if isinstance(anchor, dict)
            ]

        old_anchors = anchors(old_data)
        if any(anchor not in old_anchors for anchor in anchors(new_data)):
            raise RecalculationContextChanged("plan_anchors")

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

    def prune_auto(self, keep: int = AUTO_KEEP) -> int:
        with self._lock, self._conn:
            return self._prune_auto_locked(keep)

    def _history_protected_locked(self) -> set[str]:
        """Versions retention never deletes (decisão de 15/10/2026).

        The last ``HISTORY_KEEP_STEPS`` versions behind the active plan, both
        as they happened (``previous_snapshot_id``) and as «Desfazer» walks
        them (``undo_to``); the latest snapshot of each ISOP load (by file);
        the latest «Recalcular plano».
        """
        protected: set[str] = set()
        runtime = self._conn.execute(
            "SELECT snapshot_id FROM plan_runtime WHERE singleton=1"
        ).fetchone()
        frontier = [runtime[0]] if runtime and runtime[0] else []
        for _ in range(HISTORY_KEEP_STEPS + 1):
            frontier = [item for item in dict.fromkeys(frontier) if item not in protected]
            if not frontier:
                break
            protected.update(frontier)
            marks = ",".join("?" * len(frontier))
            frontier = [
                value
                for row in self._conn.execute(
                    f"SELECT previous_snapshot_id,undo_to FROM plans WHERE id IN ({marks})",
                    frontier,
                )
                for value in row
                if value
            ]
        protected.update(
            row[0]
            for row in self._conn.execute(
                "SELECT id FROM plans p WHERE source='load' AND rowid=("
                "SELECT max(rowid) FROM plans q WHERE q.source='load' AND q.origin=p.origin)"
            )
        )
        latest_recalculation = self._conn.execute(
            "SELECT id FROM plans WHERE kind='recalculate' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        if latest_recalculation is not None:
            protected.add(latest_recalculation[0])
        return protected

    def _prune_auto_locked(self, keep: int = AUTO_KEEP) -> int:
        protected = sorted(self._history_protected_locked())
        marks = ",".join("?" * len(protected)) or "''"  # NOT IN (NULL) would keep everything
        cursor = self._conn.execute(
            f"""
                DELETE FROM plans
                WHERE is_auto = 1
                  AND source != 'scenario'
                  AND id NOT IN (SELECT snapshot_id FROM plan_runtime WHERE snapshot_id IS NOT NULL)
                  AND id NOT IN (
                    SELECT json_extract(payload_json, '$.old_active_snapshot') FROM plan_mutations
                    WHERE status='preparing'
                      AND json_extract(payload_json, '$.old_active_snapshot') IS NOT NULL
                  )
                  AND id NOT IN ({marks})
                  AND id NOT IN (
                    SELECT id FROM plans
                    WHERE is_auto = 1
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                  )
                """,
            (*protected, max(0, int(keep))),
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
        recalculate_from_start: bool = False, planning_now=None,
        name: str | None = None, kind: str = "", undo_restores: str | None = None,
    ) -> None:
        """``name``: what the write changed (``history.snapshot_name``);
        ``undo_restores``: the version a «Desfazer» puts back."""
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
                    self._assert_historical_unchanged_locked(
                        payload, now=planning_now, undo_restores=undo_restores,
                    )
                plan_id = uuid4().hex
                name = name or "Plano aplicado"
                if recalculate_from_start and not kind:
                    kind = "recalculate"
                self._conn.execute(
                    "INSERT INTO plans(id,name,source,origin,note,is_auto,otd,otd_d,tardy_count,"
                    "setups,gate_status,payload_json,previous_snapshot_id,undo_to,undo_label,"
                    "kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        plan_id,
                        name,
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
                        *self._history_locked(name, undo_restores=undo_restores),
                        kind,
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
            from backend.plans.history import load_label

            name = load_label(job["filename"])
            self._conn.execute(
                """INSERT INTO plans (
                    id,name,source,origin,note,is_auto,otd,otd_d,tardy_count,
                    setups,gate_status,payload_json,previous_snapshot_id,undo_to,
                    undo_label,kind
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    plan_id,
                    name,
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
                    *self._history_locked(name),
                    "load",
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
