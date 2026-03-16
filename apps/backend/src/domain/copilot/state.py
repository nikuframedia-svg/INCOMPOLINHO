"""Global copilot state — in-memory singleton for schedule/alerts/rules.

This replaces the LEAN backend's app_state with an equivalent
that works standalone in the Original backend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class CopilotState:
    """In-memory state for copilot context: schedule, alerts, rules, config."""

    def __init__(self) -> None:
        self.isop_data: Any = None
        self.isop_date: str | None = None
        self.schedule: dict | None = None
        self.alerts: list[dict] | None = None
        self._config: dict = {}
        self._rules: list[dict] = []

        # ── Decision intelligence fields ──
        self.engine_data: Any = None
        self.decisions: list[Any] = []
        self.kpis: dict[str, Any] | None = None
        self.blocks: list[Any] = []
        self.feasibility_report: Any = None
        self.auto_moves: list[Any] = []
        self.last_schedule_at: str | None = None
        self.solver_used: str = ""
        self.solve_time_s: float = 0.0

    # ── Config & Rules ──

    def get_config(self) -> dict:
        return self._config

    def set_config(self, config: dict) -> None:
        self._config = config

    def get_rules(self) -> list[dict]:
        return self._rules

    def add_rule(self, rule: dict) -> None:
        self._rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        original_len = len(self._rules)
        self._rules = [r for r in self._rules if r.get("id") != rule_id]
        return len(self._rules) < original_len

    # ── Schedule hydration ──

    def update_from_schedule_result(self, result: dict) -> None:
        """Hydrate all fields from a scheduling run result."""
        blocks = result.get("blocks", [])
        self.blocks = [
            b.dict() if hasattr(b, "dict") else (b.model_dump() if hasattr(b, "model_dump") else b)
            for b in blocks
        ]
        self.decisions = [
            d.dict() if hasattr(d, "dict") else (d.model_dump() if hasattr(d, "model_dump") else d)
            for d in result.get("decisions", [])
        ]
        self.auto_moves = [
            m.dict() if hasattr(m, "dict") else (m.model_dump() if hasattr(m, "model_dump") else m)
            for m in result.get("auto_moves", [])
        ]
        self.feasibility_report = result.get("feasibility_report")
        self.kpis = result.get("kpis")
        self.engine_data = result.get("engine_data")
        self.solver_used = result.get("solver_used", "atcs_python")
        self.solve_time_s = result.get("solve_time_s", 0.0)
        self.last_schedule_at = datetime.now().isoformat()

        # Update schedule dict for backward compat with prompts.py
        self.schedule = {
            "blocks": self.blocks,
            "kpis": self.kpis,
            "jobs": self.blocks,  # alias for ver_carga_maquinas
            "machines": list({b.get("machine_id", b.get("machine", "")) for b in self.blocks}),
            "solver_status": "ok",
            "solve_time_seconds": self.solve_time_s,
        }

    def get_context_summary(self) -> dict:
        """Return compact summary for system prompt injection."""
        return {
            "has_isop": self.isop_data is not None,
            "has_schedule": self.schedule is not None,
            "n_blocks": len(self.blocks),
            "n_decisions": len(self.decisions),
            "n_alerts": len(self.alerts) if self.alerts else 0,
            "n_rules": len(self._rules),
            "kpis": self.kpis,
            "solver_used": self.solver_used,
            "solve_time_s": self.solve_time_s,
        }

    def get_decisions_for_sku(self, sku: str) -> list[dict]:
        """Filter decisions by SKU (case-insensitive match on op_id)."""
        sku_lower = sku.lower()
        return [
            d
            for d in self.decisions
            if sku_lower in d.get("op_id", "").lower() or sku_lower in d.get("detail", "").lower()
        ]


copilot_state = CopilotState()
