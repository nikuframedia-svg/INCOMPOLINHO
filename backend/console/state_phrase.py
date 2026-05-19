"""State phrase — Spec 11 §2.

One line at the top. Green/yellow/red. The João reads it in 1 second.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.console.action_items import ActionItem


def compute_state_phrase(
    actions: list[ActionItem],
    expedition: dict,
    machines: dict,
) -> tuple[str, str]:
    """Return (color, phrase). color: 'green' | 'yellow' | 'red'."""
    critical = [a for a in actions if a.severity == "critical"]
    warning = [a for a in actions if a.severity == "warning"]

    if critical:
        if len(critical) == 1:
            return "red", critical[0].phrase
        return "red", f"{len(critical)} problemas precisam de decisão hoje."

    if warning:
        if len(warning) == 1:
            return "yellow", warning[0].phrase
        return "yellow", f"{len(warning)} situações precisam da tua atenção."

    n_mach = len([m for m in machines.get("machines", []) if m["util"] > 0])
    total_orders = expedition.get("total_orders", 0)
    total_ready = expedition.get("total_ready", 0)

    parts = [f"{n_mach} máquinas a produzir."]
    if total_orders > 0:
        if total_ready == total_orders:
            parts.append(f"{total_orders} entregas hoje, todas prontas.")
        else:
            parts.append(f"{total_ready}/{total_orders} entregas prontas.")
    parts.append("Sem problemas.")

    return "green", " ".join(parts)
