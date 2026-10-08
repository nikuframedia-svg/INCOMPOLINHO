"""Copilot state — Spec 10.

Singleton holding the current schedule, engine data, config, and rules.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from backend.audit.store import AuditStore
from backend.config.types import FactoryConfig
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.types import CurrentMachineState

UTC = timezone.utc  # noqa: UP017 - Python 3.10 compatibility
logger = logging.getLogger(__name__)

_STATE_PATH = str(Path(os.environ.get("PP1_DATA_DIR", "data")) / "copilot_state.json")


def _compute_stress(segments, lots, engine_data):
    """Lazy import + call for stress map."""
    from backend.scheduler.stress import compute_stress_map

    return compute_stress_map(
        segments,
        lots,
        engine_data.n_days,
        n_holidays=len(getattr(engine_data, "holidays", []) or []),
    )


@dataclass
class CopilotState:
    """Mutable copilot session state."""

    def __getattribute__(self, name):
        from backend.plans.context import redirected_state

        target = redirected_state(self)
        return getattr(target, name) if target is not None else object.__getattribute__(self, name)

    def __setattr__(self, name, value):
        from backend.plans.context import redirected_state

        target = redirected_state(self)
        object.__setattr__(target if target is not None else self, name, value)

    # Core data (populated via load_isop or externally)
    engine_data: object | None = None  # EngineData (avoid circular import)
    config: FactoryConfig | None = None

    # Pristine config snapshot from the loaded ISOP — used to reset presets
    # to a known baseline so they don't accumulate each other's overrides.
    default_config: FactoryConfig | None = None

    # Schedule results
    segments: list[Segment] = field(default_factory=list)
    lots: list[Lot] = field(default_factory=list)
    score: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    gate_report: dict | None = None
    improvement_report: dict | None = None
    solver_status: str | None = None
    feasibility: dict | None = None
    # Optimistic-concurrency token. It never decreases during the process.
    plan_revision: int = 0
    approvals: list[dict] = field(default_factory=list)

    # Journal (Spec 12)
    journal_entries: list[dict] | None = None

    # DQA (Spec 12)
    trust_index: object | None = None

    # Pre-computed analytics (refreshed on every schedule update)
    stock_projections: list | None = None
    expedition: object | None = None
    risk_result: object | None = None
    late_deliveries: object | None = None
    coverage: object | None = None
    order_tracking: list | None = None
    stress_map: list | None = None
    operator_alerts: list | None = None

    # Audit
    schedule_id: str = ""
    audit_store: AuditStore | None = None

    # Persistent production-plan snapshots (created lazily).
    plans_store: object | None = None

    # Learning optimization info (persisted from smart_schedule)
    learning_info: dict | None = None

    # Metadata for the currently loaded ISOP/dataset.
    dataset_info: dict[str, object] | None = None
    # Two-stage ISOP load and the observed start-of-day reality.
    prepared_load: dict[str, object] | None = None
    current_machine_states: list[CurrentMachineState] = field(default_factory=list)

    # User rules
    rules: list[dict] = field(default_factory=list)

    # Simulation revert snapshot
    saved_schedule: ScheduleResult | None = None
    saved_mutations: list[dict] | None = None
    saved_manual_edits: list[dict] | None = None
    saved_engine_data: object | None = None
    saved_config: FactoryConfig | None = None
    saved_plan_revision: int | None = None

    # Active what-if mutations (simulate-apply / ctp-apply). Persisted so a
    # subsequent recalculation (e.g. applying a preset) keeps them applied.
    # Each entry: {"type": str, "params": dict}
    active_mutations: list[dict] = field(default_factory=list)

    # Direct lot moves currently applied to the visible plan.
    manual_edits: list[dict] = field(default_factory=list)

    def clear_runtime_for_new_dataset(self) -> None:
        """Clear transient state that must not leak between uploaded ISOPs."""
        self.saved_schedule = None
        self.saved_mutations = None
        self.saved_manual_edits = None
        self.saved_engine_data = None
        self.saved_config = None
        self.saved_plan_revision = None
        self.active_mutations = []
        self.manual_edits = []
        self.learning_info = None
        self.trust_index = None
        self.dataset_info = None
        self.prepared_load = None
        self.current_machine_states = []
        self.approvals = []
        self.gate_report = None
        self.improvement_report = None
        self.solver_status = None
        self.feasibility = None
        self._clear_analytics()

    def _clear_analytics(self) -> None:
        """Clear derived analytics before computing them for a new schedule."""
        self.stock_projections = None
        self.expedition = None
        self.risk_result = None
        self.late_deliveries = None
        self.coverage = None
        self.order_tracking = None
        self.stress_map = None

    def set_dataset_info(
        self,
        filename: str,
        result: ScheduleResult,
        trust,
        n_ops: int,
    ) -> dict[str, object]:
        """Record metadata for the active uploaded ISOP."""
        self.dataset_info = {
            "id": uuid4().hex,
            "filename": Path(filename or "upload.xlsx").name,
            "uploaded_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "n_ops": n_ops,
            "n_segments": len(result.segments),
            "trust_score": trust.score,
            "trust_gate": trust.gate,
            "otd": result.score.get("otd"),
            "tardy_count": result.score.get("tardy_count"),
        }
        return self.dataset_info

    def save_current(self) -> None:
        """Save current schedule for revert after simulation apply."""
        self.saved_schedule = ScheduleResult(
            segments=copy.deepcopy(self.segments),
            lots=copy.deepcopy(self.lots),
            score=copy.deepcopy(self.score),
            warnings=copy.deepcopy(self.warnings),
            operator_alerts=copy.deepcopy(self.operator_alerts or []),
            time_ms=0,
            audit_trail=None,
            journal=copy.deepcopy(self.journal_entries),
            gate_report=copy.deepcopy(self.gate_report),
            improvement_report=copy.deepcopy(self.improvement_report),
            solver_status=self.solver_status,
            feasibility=copy.deepcopy(self.feasibility),
        )
        self.saved_mutations = copy.deepcopy(self.active_mutations)
        self.saved_manual_edits = copy.deepcopy(self.manual_edits)
        self.saved_engine_data = copy.deepcopy(self.engine_data)
        self.saved_config = copy.deepcopy(self.config)
        self.saved_plan_revision = int(self.plan_revision)

    def update_schedule(
        self,
        result: ScheduleResult,
        *,
        plan_source: str | None = None,
        plan_note: str = "",
        plan_name: str | None = None,
        require_persistence: bool = True,
    ) -> None:
        """Update state and optionally persist an automatic plan snapshot."""
        if self.engine_data is not None and result.preserved_lot_proofs is not None:
            self.engine_data.preserved_lot_proofs = dict(result.preserved_lot_proofs)
        self.segments = result.segments
        self.lots = result.lots
        self.score = result.score
        self.warnings = result.warnings
        self.journal_entries = result.journal
        self.operator_alerts = result.operator_alerts
        self.gate_report = result.gate_report
        self.improvement_report = copy.deepcopy(result.improvement_report)
        self.solver_status = result.solver_status
        self.feasibility = result.feasibility
        self.plan_revision += 1
        if self.dataset_info is not None:
            self.dataset_info.update(
                {
                    "n_ops": len(getattr(self.engine_data, "ops", []) or []),
                    "n_segments": len(result.segments),
                    "otd": result.score.get("otd"),
                    "tardy_count": result.score.get("tardy_count"),
                }
            )

        from backend.plans.context import is_staging

        if result.audit_trail and not is_staging():
            if not self.audit_store:
                self.audit_store = AuditStore()
            self.schedule_id = self.audit_store.save_trail(
                result.audit_trail,
                result.score,
            )

        # Pre-compute all analytics
        self._refresh_analytics()

        gate_blocked = bool(
            result.gate_report and result.gate_report.get("apply_decision") == "blocked"
        )
        if plan_source and self.dataset_info is not None and not gate_blocked and not is_staging():
            try:
                self.persist_current_plan(
                    name=plan_name or self._automatic_plan_name(plan_source),
                    source=plan_source,
                    note=plan_note,
                    is_auto=True,
                )
            except Exception:
                logger.exception("Failed to persist %s plan snapshot", plan_source)
                if require_persistence:
                    raise
        elif plan_source and gate_blocked:
            logger.warning(
                "Blocked plan from %s was not persisted (gate status: %s)",
                plan_source,
                result.gate_report.get("status"),
            )

    @staticmethod
    def _automatic_plan_name(source: str) -> str:
        return {
            "load": "Plano carregado",
            "auto": "Replaneamento automático",
            "simulation_apply": "Cenário aplicado",
            "manual_edit": "Edição manual",
            "restore": "Plano reposto",
        }.get(source, "Snapshot automático")

    def get_plans_store(self):
        """Return the lazily-created persistent plans store."""
        if self.plans_store is None:
            from backend.plans.store import PlansStore

            self.plans_store = PlansStore()
        return self.plans_store

    def persist_current_plan(
        self,
        *,
        name: str,
        source: str,
        note: str = "",
        is_auto: bool,
        allow_blocked_recovery: bool = False,
    ) -> dict:
        """Persist the exact current engine + schedule state."""
        from backend.plans.context import is_staging
        from backend.plans.serialize import serialize_snapshot

        if is_staging():
            return {"id": None, "name": name, "source": source}

        if self.engine_data is None:
            raise ValueError("Sem plano carregado para guardar.")
        if (
            not allow_blocked_recovery
            and self.gate_report
            and self.gate_report.get("apply_decision") == "blocked"
        ):
            raise ValueError(
                "Não é possível guardar um plano bloqueado pelos controlos operacionais."
            )
        origin = str((self.dataset_info or {}).get("filename", ""))
        store = self.get_plans_store()
        saved = store.save(
            name=name,
            source=source,
            origin=origin,
            note=note,
            payload=serialize_snapshot(self),
            score=self.score,
            gate_report=self.gate_report,
            is_auto=is_auto,
            activate=is_auto,
        )
        if is_auto:
            try:
                store.prune_auto(keep=20)
            except Exception:
                # The new snapshot is already durable. Retention cleanup is
                # maintenance and must not turn a successful commit into a
                # reported failure.
                logger.exception("Failed to prune automatic plan snapshots")
        return saved

    def _refresh_analytics(self) -> None:
        """Pre-compute all analytics over current segments/lots.

        Each analytics is isolated — a failure in one does not block the others.
        """
        self._clear_analytics()
        if self.engine_data is None:
            return

        from backend.analytics.coverage_audit import compute_coverage_audit
        from backend.analytics.expedition import compute_expedition
        from backend.analytics.late_delivery import analyze_late_deliveries
        from backend.analytics.order_tracking import compute_order_tracking
        from backend.analytics.stock_projection import compute_stock_projections
        from backend.calendar import current_factory_day
        from backend.planning_control import PlanningStopped, planning_checkpoint
        from backend.risk import compute_risk

        analytics = [
            ("expedition", lambda: compute_expedition(
                self.segments, self.lots, self.engine_data,
                start_day=current_factory_day(self.engine_data, self.config),
            )),
            (
                "stock_projections",
                lambda: compute_stock_projections(
                    self.segments,
                    self.lots,
                    self.engine_data,
                    buffer_days=self.score.get("buffer_days", 0),
                ),
            ),
            (
                "order_tracking",
                lambda: compute_order_tracking(self.segments, self.lots, self.engine_data),
            ),
            (
                "risk_result",
                lambda: compute_risk(
                    self.segments, self.lots, self.engine_data, config=self.config
                ),
            ),
            (
                "late_deliveries",
                lambda: analyze_late_deliveries(
                    self.segments,
                    self.lots,
                    self.engine_data,
                    self.config,
                ),
            ),
            (
                "coverage",
                lambda: compute_coverage_audit(self.segments, self.lots, self.engine_data),
            ),
            ("stress_map", lambda: _compute_stress(self.segments, self.lots, self.engine_data)),
        ]

        for name, fn in analytics:
            planning_checkpoint()
            try:
                value = fn()
                planning_checkpoint()
                setattr(self, name, value)
            except PlanningStopped:
                raise
            except Exception:
                logger.exception("Failed to compute %s", name)

    def add_rule(self, rule: dict) -> str:
        """Add a user rule. Returns rule id."""
        from backend.plans.context import is_staging
        from backend.plans.transactions import run_sync_mutation

        if not is_staging():
            return run_sync_mutation(self, lambda: self.add_rule(rule))
        rule_id = str(uuid4())
        self.rules.append({**copy.deepcopy(rule), "id": rule_id})
        return rule_id

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by id. Returns True if found."""
        from backend.plans.context import is_staging
        from backend.plans.transactions import run_sync_mutation

        if not is_staging():
            return run_sync_mutation(self, lambda: self.remove_rule(rule_id))
        for index, rule in enumerate(self.rules):
            if rule.get("id") == rule_id:
                del self.rules[index]
                return True
        return False

    def _save_rules(self) -> None:
        """Persist rules to JSON file."""
        from backend.plans.transactions import _atomic_text

        _atomic_text(
            Path(_STATE_PATH), json.dumps({"rules": self.rules}, ensure_ascii=False, indent=2)
        )

    def _load_rules(self) -> None:
        """Load rules from JSON file if exists."""
        p = Path(_STATE_PATH)
        if p.exists():
            with open(p) as f:
                data = json.load(f)
            self.rules = data.get("rules", [])
            if self.engine_data is None:
                self.plan_revision = self.get_plans_store().runtime_identity()["plan_revision"]
            normalized = copy.deepcopy(self.rules)
            reserved = {r.get("id") for r in normalized}
            seen = set()
            for index, rule in enumerate(normalized):
                old_id = rule.get("id")
                if not old_id or old_id in seen:
                    salt = 0
                    while True:
                        replacement = str(
                            uuid5(
                                NAMESPACE_URL,
                                json.dumps([old_id, index, rule, salt], sort_keys=True),
                            )
                        )
                        if replacement not in reserved:
                            break
                        salt += 1
                    rule["id"] = replacement
                    reserved.add(replacement)
                seen.add(rule["id"])
            if normalized != self.rules:
                from backend.plans.transactions import run_sync_mutation

                run_sync_mutation(self, lambda: setattr(self, "rules", normalized))


# Singleton instance
state = CopilotState()
