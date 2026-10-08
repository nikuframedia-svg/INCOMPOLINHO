"""Console API — Spec 11.

GET /api/console?day_idx=0 — Full console data in one call.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime

from fastapi import APIRouter, HTTPException

from backend.api.plan_reads import PlanReadRoute
from backend.console.action_items import compute_action_items
from backend.console.day_summary import compute_day_overview, compute_day_summary
from backend.console.expedition_today import compute_expedition_today
from backend.console.machines_today import compute_machines_today
from backend.console.state_phrase import compute_state_phrase
from backend.console.tomorrow_prep import compute_day_setups, compute_tomorrow_prep
from backend.copilot.state import state
from backend.risk.slack_analytics import select_top_risks

router = APIRouter(route_class=PlanReadRoute)


def _interval_overlaps_date(entry: dict, current_date: str | None) -> bool:
    if not current_date:
        return False
    try:
        target = date.fromisoformat(current_date)
        start = datetime.fromisoformat(
            str(entry.get("start_at") or entry.get("from") or current_date)
        ).date()
        if entry.get("end_at"):
            end_at = datetime.fromisoformat(str(entry["end_at"]))
            # Canonical intervals are end-exclusive. Midnight belongs only to
            # the following day and must not keep the previous stop "current".
            if end_at.hour == end_at.minute == end_at.second == end_at.microsecond == 0:
                return start <= target < end_at.date()
            return start <= target <= end_at.date()
        if entry.get("to"):
            # Legacy date ranges were inclusive and are accepted only while an
            # old snapshot is being migrated.
            return start <= target <= datetime.fromisoformat(str(entry["to"])).date()
        return start <= target
    except (TypeError, ValueError):
        return False


def _risk_rows(top_risks, segments, workdays: list[str]) -> list[dict]:
    """Serialise risks in the given order (already filtered and sorted)."""
    rows = []
    segments_by_lot = {}
    for segment in segments:
        segments_by_lot.setdefault(segment.lot_id, []).append(segment)

    for risk in top_risks:
        row = asdict(risk)
        lot_segments = sorted(
            segments_by_lot.get(risk.lot_id, []),
            key=lambda segment: (segment.day_idx, segment.start_min),
        )
        first = lot_segments[0] if lot_segments else None
        last = lot_segments[-1] if lot_segments else None
        if first is not None:
            row["planned_machine_id"] = first.machine_id
            row["production_day"] = first.day_idx
            row["production_date"] = (
                workdays[first.day_idx] if 0 <= first.day_idx < len(workdays) else None
            )
        if last is not None:
            row["completion_machine_id"] = last.machine_id
            row["completion_date"] = (
                workdays[last.day_idx] if 0 <= last.day_idx < len(workdays) else None
            )
        rows.append(row)
    return rows


@router.get("/api/console")
async def get_console(day_idx: int = 0):
    """Full console data: state phrase, actions, machines, expedition, tomorrow."""
    if state.engine_data is None or state.config is None:
        raise HTTPException(
            status_code=503,
            detail="Sem dados carregados. Carrega um ISOP primeiro.",
        )

    actions = compute_action_items(
        state.segments,
        state.lots,
        state.engine_data,
        state.config,
        day_idx=day_idx,
    )
    machines = compute_machines_today(
        state.segments,
        state.engine_data,
        state.config,
        day_idx,
    )
    expedition = compute_expedition_today(
        state.segments,
        state.lots,
        state.engine_data,
        day_idx,
    )
    tomorrow = compute_tomorrow_prep(
        state.segments,
        state.lots,
        state.engine_data,
        state.config,
        day_idx + 1,
    )
    setups_today = compute_day_setups(state.segments, day_idx, state.engine_data)
    summary = compute_day_summary(
        state.segments,
        state.lots,
        state.engine_data,
        state.config,
        day_idx,
        machines,
        expedition,
        actions,
    )
    color, phrase = compute_state_phrase(actions, expedition, machines)
    current_date = (
        state.engine_data.workdays[day_idx]
        if 0 <= day_idx < len(state.engine_data.workdays)
        else None
    )
    machine_group = state.config.machine_groups
    day_segments = [
        segment for segment in state.segments if segment.day_idx == day_idx
    ]
    production_by_group = []
    for group in sorted(set(machine_group.values())):
        active = sorted(
            {
                segment.machine_id
                for segment in day_segments
                if machine_group.get(segment.machine_id) == group
            }
        )
        production_by_group.append(
            {"group": group, "machines": active, "count": len(active)}
        )

    setups_by_group_shift = []
    for group in sorted(set(machine_group.values())):
        for shift in state.config.shifts:
            group_setups = [
                setup
                for setup in setups_today
                if setup["shift"] == shift.id
                and machine_group.get(setup["machine"]) == group
            ]
            setups_by_group_shift.append(
                {
                    "group": group,
                    "shift": shift.id,
                    "count": len(group_setups),
                }
            )

    machine_unavailability = [
        {
            "resource": entry.get("resource", ""),
            "category": entry.get("category", "Outra"),
            "reason": entry.get("reason", ""),
            "start_at": entry.get("start_at") or entry.get("from"),
            "end_at": entry.get("end_at") or entry.get("to"),
        }
        for entry in state.config.machine_unavailability
        if _interval_overlaps_date(entry, current_date)
    ]
    tool_unavailability = [
        {
            "resource": entry.get("resource", ""),
            "category": entry.get("category", "Outra"),
            "reason": entry.get("reason", ""),
            "start_at": entry.get("start_at") or entry.get("from"),
            "end_at": entry.get("end_at") or entry.get("to"),
        }
        for entry in state.config.tool_unavailability
        if _interval_overlaps_date(entry, current_date)
    ]
    operator_unavailability = [
        {
            "group": entry.get("group", ""),
            "shift": entry.get("shift", ""),
            "count": int(entry.get("count", 1)),
            "reason": entry.get("reason", ""),
            "start_at": entry.get("start_at") or entry.get("from"),
            "end_at": entry.get("end_at") or entry.get("to"),
        }
        for entry in state.config.operator_unavailability
        if _interval_overlaps_date(entry, current_date)
    ]
    trials = [
        {
            "machine_id": item.machine_id,
            "tool_id": item.tool_id,
            "expected_end": item.expected_end,
            "note": item.note,
        }
        for item in state.engine_data.current_machine_states
        if day_idx == 0 and item.status == "trial"
    ]
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
            "group": m.get("group", ""),
            "utilization_pct": round(m["util"] * 100, 1),
            "current_tool": m.get("current_tool")
            or (m["tools"][0]["id"] if m.get("tools") else None),
            "current_state": m.get("current_state"),
            "current_sku": m.get("current_sku"),
            "runs": m.get("runs", []),
            "next_setup_at": (m.get("next_setup") or {}).get("time"),
            "eta_current": m.get("eta_current"),
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
            "partial": sum(1 for o in c.get("orders", []) if o.get("status") == "partial"),
            "not_ready": c["total"]
            - c["ready"]
            - sum(1 for o in c.get("orders", []) if o.get("status") == "partial"),
            "total": c["total"],
        }
        for c in expedition.get("clients", [])
    ]
    expedition_totals = {
        "ready": sum(item["ready"] for item in expedition_list),
        "partial": sum(item["partial"] for item in expedition_list),
        "not_ready": sum(item["not_ready"] for item in expedition_list),
    }

    operational_summary = {
        "production_by_group": production_by_group,
        "setups_by_group_shift": setups_by_group_shift,
        "average_utilization_pct": round(
            sum(item["utilization_pct"] for item in machines_list)
            / max(1, len(machines_list)),
            1,
        ),
        "unavailable": {
            "machines": machine_unavailability,
            "tools": tool_unavailability,
            "operators": operator_unavailability,
        },
        "trials": trials,
        "expedition": expedition_totals,
    }
    day_overview = compute_day_overview(current_date, operational_summary, tomorrow)

    return {
        "date": current_date,
        "state": {"color": color, "phrase": phrase},
        "actions": mapped_actions,
        "machines": machines_list,
        "setups_today": setups_today,
        "top_risks": _risk_rows(
            select_top_risks(
                state.risk_result.lot_risks if state.risk_result else [],
                day_idx,
            ),
            state.segments,
            state.engine_data.workdays,
        ),
        "expedition": expedition_list,
        "tomorrow": tomorrow,
        "summary": summary,
        "operational_summary": operational_summary,
        "day_overview": day_overview,
    }
