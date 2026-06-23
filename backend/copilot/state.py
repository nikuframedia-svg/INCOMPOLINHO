"""Copilot state — Spec 10.

Singleton holding the current schedule, engine data, config, and rules.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from backend.audit.store import AuditStore
from backend.config.types import FactoryConfig
from backend.scheduler.types import Lot, ScheduleResult, Segment

logger = logging.getLogger(__name__)

_STATE_PATH = "data/copilot_state.json"


def _compute_stress(segments, lots, engine_data):
    """Lazy import + call for stress map."""
    from backend.scheduler.stress import compute_stress_map
    return compute_stress_map(
        segments, lots, engine_data.n_days,
        n_holidays=len(getattr(engine_data, 'holidays', []) or []),
    )


@dataclass
class RevertSnapshot:
    """Exact state snapshot used by the frontend Reverter banner."""

    kind: str
    config: FactoryConfig | None
    schedule: ScheduleResult
    active_mutations: list[dict]
    active_simulation_summary: list[str] = field(default_factory=list)
    engine_data: object | None = None


@dataclass
class CopilotState:
    """Mutable copilot session state."""

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

    # Learning optimization info (persisted from smart_schedule)
    learning_info: dict | None = None

    # User rules
    rules: list[dict] = field(default_factory=list)

    # Revert snapshots. Kept separate so simulation revert cannot undo config,
    # and config revert cannot erase an active what-if scenario.
    simulation_snapshot: RevertSnapshot | None = None
    config_snapshot: RevertSnapshot | None = None

    # Legacy single-slot fields kept for older callers/tests.
    saved_schedule: ScheduleResult | None = None
    saved_snapshot: RevertSnapshot | None = None

    # Active what-if mutations (simulate-apply / ctp-apply). Persisted so a
    # subsequent recalculation (e.g. applying a preset) keeps them applied.
    # Each entry: {"type": str, "params": dict}
    active_mutations: list[dict] = field(default_factory=list)
    active_simulation_summary: list[str] = field(default_factory=list)

    def save_current(self, kind: str = "simulation") -> None:
        """Save current config and schedule for exact revert."""
        schedule = ScheduleResult(
            segments=copy.deepcopy(self.segments),
            lots=copy.deepcopy(self.lots),
            score=copy.deepcopy(self.score),
            warnings=copy.deepcopy(self.warnings),
            operator_alerts=copy.deepcopy(self.operator_alerts or []),
            time_ms=0,
            audit_trail=None,
            journal=copy.deepcopy(self.journal_entries),
        )
        snapshot = RevertSnapshot(
            kind=kind,
            config=copy.deepcopy(self.config),
            schedule=schedule,
            active_mutations=copy.deepcopy(self.active_mutations),
            active_simulation_summary=copy.deepcopy(self.active_simulation_summary),
            engine_data=copy.deepcopy(self.engine_data),
        )
        if kind == "config":
            self.config_snapshot = snapshot
        else:
            self.simulation_snapshot = snapshot
        self.saved_schedule = schedule
        self.saved_snapshot = snapshot

    def restore_saved(self, kind: str | None = None) -> str:
        """Restore a saved snapshot. Returns the restored snapshot kind."""
        snapshot: RevertSnapshot | None
        if kind == "simulation":
            snapshot = self.simulation_snapshot
        elif kind == "config":
            snapshot = self.config_snapshot
        else:
            snapshot = self.saved_snapshot or self.simulation_snapshot or self.config_snapshot

        if snapshot:
            if snapshot.kind == "config":
                self.config = copy.deepcopy(snapshot.config)
                self.engine_data = copy.deepcopy(snapshot.engine_data)
            self.active_mutations = copy.deepcopy(snapshot.active_mutations)
            self.active_simulation_summary = copy.deepcopy(snapshot.active_simulation_summary)
            self.update_schedule(copy.deepcopy(snapshot.schedule))
            restored_kind = snapshot.kind
            if restored_kind == "config":
                self.config_snapshot = None
            else:
                self.simulation_snapshot = None
        elif self.saved_schedule:
            self.update_schedule(copy.deepcopy(self.saved_schedule))
            self.active_mutations = []
            self.active_simulation_summary = []
            restored_kind = "simulation"
        else:
            raise ValueError("Nada para reverter.")

        if self.saved_snapshot and self.saved_snapshot.kind == restored_kind:
            self.saved_schedule = None
            self.saved_snapshot = None
        return restored_kind

    def clear_revert(self) -> None:
        self.simulation_snapshot = None
        self.config_snapshot = None
        self.saved_schedule = None
        self.saved_snapshot = None

    def update_schedule(self, result: ScheduleResult) -> None:
        """Update state from a ScheduleResult. Saves audit trail if present."""
        self.segments = result.segments
        self.lots = result.lots
        self.score = result.score
        self.warnings = result.warnings
        self.journal_entries = result.journal
        self.operator_alerts = result.operator_alerts

        if result.audit_trail:
            if not self.audit_store:
                self.audit_store = AuditStore()
            self.schedule_id = self.audit_store.save_trail(
                result.audit_trail, result.score,
            )

        # Pre-compute all analytics
        self._refresh_analytics()

    def _refresh_analytics(self) -> None:
        """Pre-compute all analytics over current segments/lots.

        Each analytics is isolated — a failure in one does not block the others.
        """
        if self.engine_data is None or not self.segments:
            return

        from backend.analytics.coverage_audit import compute_coverage_audit
        from backend.analytics.expedition import compute_expedition
        from backend.analytics.late_delivery import analyze_late_deliveries
        from backend.analytics.order_tracking import compute_order_tracking
        from backend.analytics.stock_projection import compute_stock_projections
        from backend.risk import compute_risk

        analytics = [
            ("expedition", lambda: compute_expedition(self.segments, self.lots, self.engine_data)),
            ("stock_projections", lambda: compute_stock_projections(
                self.segments, self.lots, self.engine_data,
                buffer_days=self.score.get("buffer_days", 0),
            )),
            ("order_tracking", lambda: compute_order_tracking(self.segments, self.lots, self.engine_data)),
            ("risk_result", lambda: compute_risk(self.segments, self.lots, self.engine_data)),
            ("late_deliveries", lambda: analyze_late_deliveries(
                self.segments, self.lots, self.engine_data, self.config,
            )),
            ("coverage", lambda: compute_coverage_audit(self.segments, self.lots, self.engine_data)),
            ("stress_map", lambda: _compute_stress(self.segments, self.lots, self.engine_data)),
        ]

        for name, fn in analytics:
            try:
                setattr(self, name, fn())
            except Exception:
                logger.exception("Failed to compute %s", name)

    def add_rule(self, rule: dict) -> str:
        """Add a user rule. Returns rule id."""
        rule_id = f"rule_{len(self.rules) + 1}"
        rule["id"] = rule_id
        self.rules.append(rule)
        self._save_rules()
        return rule_id

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by id. Returns True if found."""
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.get("id") != rule_id]
        if len(self.rules) < before:
            self._save_rules()
            return True
        return False

    def _save_rules(self) -> None:
        """Persist rules to JSON file."""
        p = Path(_STATE_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump({"rules": self.rules}, f, ensure_ascii=False, indent=2)

    def _load_rules(self) -> None:
        """Load rules from JSON file if exists."""
        p = Path(_STATE_PATH)
        if p.exists():
            with open(p) as f:
                data = json.load(f)
            self.rules = data.get("rules", [])


# Singleton instance
state = CopilotState()
