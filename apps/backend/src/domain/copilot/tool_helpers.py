"""Copilot engine — helper/utility functions for tool executors."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


class _DateEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return super().default(o)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, cls=_DateEncoder, ensure_ascii=False)


# ─── Rule → Scheduler Bridge ────────────────────────────────────────────────


def _rules_to_user_moves(rules: list[dict]) -> list[dict]:
    """Translate copilot rules into user_moves for auto_route_overflow."""
    moves: list[dict] = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        action = rule.get("action", {})
        condition = rule.get("condition", {})
        if action.get("type") != "move_to_machine":
            continue
        target = action.get("params", {}).get("machine", "")
        if not target:
            continue

        if condition.get("type") == "sku_equals":
            sku = condition.get("params", {}).get("sku", "")
            if sku:
                moves.append({"op_id": sku, "target_machine": target})
        elif condition.get("type") == "sku_in_list":
            for sku in condition.get("params", {}).get("skus", []):
                moves.append({"op_id": sku, "target_machine": target})
    return moves


def _apply_rules_to_ops(ops: list[Any], rules: list[dict]) -> list[Any]:
    """Apply copilot rules that modify ops before scheduling."""
    skip_skus: set[str] = set()
    priority_boosts: dict[str, float] = {}

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        action = rule.get("action", {})
        condition = rule.get("condition", {})
        action_type = action.get("type", "")

        if action_type == "skip_scheduling":
            if condition.get("type") == "sku_equals":
                sku = condition.get("params", {}).get("sku", "")
                if sku:
                    skip_skus.add(sku)
        elif action_type == "set_priority":
            boost = action.get("params", {}).get("boost", 2.0)
            if condition.get("type") == "sku_equals":
                sku = condition.get("params", {}).get("sku", "")
                if sku:
                    priority_boosts[sku] = boost

    if skip_skus:
        ops = [op for op in ops if getattr(op, "sku", getattr(op, "id", "")) not in skip_skus]

    if priority_boosts:
        for op in ops:
            op_sku = getattr(op, "sku", getattr(op, "id", ""))
            if op_sku in priority_boosts and hasattr(op, "w"):
                op.w = getattr(op, "w", 1.0) * priority_boosts[op_sku]

    return ops


def _build_decision_reasoning(decision: dict) -> str:
    """Build human-readable reasoning for a scheduling decision."""
    d_type = decision.get("type", "")
    detail = decision.get("detail", "")

    reasons = {
        "OVERFLOW_ROUTE": "A máquina principal não tinha capacidade. Produção movida para alternativa.",
        "ADVANCE_PRODUCTION": "Produção antecipada para cumprir o prazo — dia anterior com capacidade.",
        "TWIN_MERGE": "Peças gémeas agrupadas para produção simultânea, optimizando tempo de máquina.",
        "TOOL_CONTENTION": "Conflito de ferramenta — duas operações no mesmo período, uma reagendada.",
        "INFEASIBLE": "Impossível alocar dentro das restrições de capacidade e prazo.",
        "BATCH_ADVANCE": "Lote inteiro avançado para resolver conflito de capacidade.",
        "ALT_MACHINE": "Produção movida para máquina alternativa por falta de capacidade na principal.",
    }

    base = reasons.get(d_type, f"Decisão do tipo '{d_type}' — gerada pelo solver CP-SAT.")
    if detail:
        base += f" Detalhe: {detail}"
    return base
