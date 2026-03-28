"""Console API — Spec 11.

GET /api/console?day_idx=0 — Full console data in one call.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from backend.console.action_items import compute_action_items
from backend.console.day_summary import compute_day_summary
from backend.console.expedition_today import compute_expedition_today
from backend.console.machines_today import compute_machines_today
from backend.console.state_phrase import compute_state_phrase
from backend.console.tomorrow_prep import compute_tomorrow_prep
from backend.copilot.state import state

router = APIRouter()


@router.get("/api/console")
async def get_console(day_idx: int = 0):
    """Full console data: state phrase, actions, machines, expedition, tomorrow."""
    if state.engine_data is None or state.config is None:
        raise HTTPException(
            status_code=503,
            detail="Sem dados carregados. Carrega um ISOP primeiro.",
        )

    actions = compute_action_items(
        state.segments, state.lots, state.engine_data, state.config,
    )
    machines = compute_machines_today(
        state.segments, state.engine_data, state.config, day_idx,
    )
    expedition = compute_expedition_today(
        state.segments, state.lots, state.engine_data, day_idx,
    )
    tomorrow = compute_tomorrow_prep(
        state.segments, state.lots, state.engine_data, state.config,
        day_idx + 1,
    )
    summary = compute_day_summary(
        state.segments, state.lots, state.engine_data, state.config,
        day_idx, machines, expedition, actions,
    )
    color, phrase = compute_state_phrase(actions, expedition, machines)

    # Remap ActionItem fields to match frontend ConsoleAction interface
    mapped_actions = [
        {
            "severity": a.severity,
            "title": a.phrase,
            "detail": a.body,
            "suggestion": a.actions[0] if a.actions else None,
            "machine_id": None,
            "deadline": a.deadline,
            "client": a.client,
            "category": a.category,
        }
        for a in actions
    ]

    # Unwrap machines dict → flat array matching ConsoleMachine[]
    machines_list = [
        {
            "machine_id": m["id"],
            "utilization_pct": round(m["util"] * 100, 1),
            "current_tool": m["tools"][0]["id"] if m.get("tools") else None,
            "runs": m.get("tools", []),
            "total_pcs": m.get("total_pcs", 0),
            "setup_count": m.get("setup_count", 0),
        }
        for m in machines.get("machines", [])
    ]

    # Unwrap expedition dict → flat array matching ConsoleExpedition[]
    expedition_list = [
        {
            "client": c["client"],
            "ready": c["ready"],
            "partial": sum(
                1 for o in c.get("orders", []) if o.get("status") == "partial"
            ),
            "not_ready": c["total"] - c["ready"] - sum(
                1 for o in c.get("orders", []) if o.get("status") == "partial"
            ),
            "total": c["total"],
        }
        for c in expedition.get("clients", [])
    ]

    return {
        "state": {"color": color, "phrase": phrase},
        "actions": mapped_actions,
        "machines": machines_list,
        "expedition": expedition_list,
        "tomorrow": tomorrow,
        "summary": summary,
    }
