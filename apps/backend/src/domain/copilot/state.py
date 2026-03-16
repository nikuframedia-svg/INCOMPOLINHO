"""Global copilot state — in-memory singleton for schedule/alerts/rules.

This replaces the LEAN backend's app_state with an equivalent
that works standalone in the Original backend.
"""

from __future__ import annotations

from typing import Any


class CopilotState:
    """In-memory state for copilot context: schedule, alerts, rules, config."""

    def __init__(self) -> None:
        self.isop_data: Any = None
        self.schedule: dict | None = None
        self.alerts: list[dict] | None = None
        self._config: dict = {}
        self._rules: list[dict] = []

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


copilot_state = CopilotState()
