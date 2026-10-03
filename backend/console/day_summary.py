"""Day summary — textual description of what happens on a given day and why.

Generates Portuguese text describing production, setups, deliveries, and risks.
"""

from __future__ import annotations

from datetime import datetime

from backend.calendar import available_machine_capacity
from backend.config.types import FactoryConfig
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData


def _build_op_lookup(engine_data: EngineData) -> dict:
    """Map op_id → EOp and sku → EOp for quick lookups."""
    by_id = {op.id: op for op in engine_data.ops}
    by_sku = {op.sku: op for op in engine_data.ops}
    return {"by_id": by_id, "by_sku": by_sku}


def _is_alt_machine(seg: Segment, ops: dict) -> str | None:
    """If segment is on alt machine, return the primary machine id."""
    op = ops["by_sku"].get(seg.sku)
    if op and op.m != seg.machine_id and op.alt == seg.machine_id:
        return op.m
    return None


def _twin_detail(seg: Segment) -> str | None:
    """Return twin SKU detail string if segment is twin."""
    if not seg.twin_outputs or len(seg.twin_outputs) < 2:
        return None
    skus = [sku for _, sku, _ in seg.twin_outputs]
    return " + ".join(skus)


def compute_day_summary(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    config: FactoryConfig,
    day_idx: int,
    machines_data: dict,
    expedition_data: dict,
    actions: list,
) -> list[dict]:
    """Build a list of summary lines for a given day.

    Each line: {"text": "...", "color": "red"|"green"|"orange"|"default"}
    """
    lines: list[dict] = []
    day_segs = [s for s in segments if s.day_idx == day_idx]
    ops = _build_op_lookup(engine_data)
    holidays = set(getattr(engine_data, "holidays", []) or [])

    # Buffer day label
    if day_idx < 0:
        buffer_label = "dias" if abs(day_idx) > 1 else "dia"
        lines.append(
            {
                "text": (
                    f"Dia de buffer ({abs(day_idx)} {buffer_label} antes do horizonte). "
                    "Produção antecipada para cumprir deadlines apertados."
                ),
                "color": "orange",
            }
        )

    # Date
    if 0 <= day_idx < len(engine_data.workdays):
        date_str = engine_data.workdays[day_idx]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            dow = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"][dt.weekday()]
            lines.append({"text": f"{dow}, {date_str}", "color": "default"})
        except (ValueError, IndexError):
            lines.append({"text": date_str, "color": "default"})

    # No production — explain why
    if not day_segs:
        if day_idx in holidays:
            lines.append({"text": "Feriado — sem produção.", "color": "orange"})
        elif 0 <= day_idx < len(engine_data.workdays):
            try:
                dt = datetime.strptime(engine_data.workdays[day_idx], "%Y-%m-%d")
                if dt.weekday() >= 5:
                    lines.append({"text": "Fim-de-semana — sem produção.", "color": "default"})
                else:
                    lines.append(
                        {
                            "text": "Sem produção planeada. Capacidade disponível.",
                            "color": "default",
                        }
                    )
            except (ValueError, IndexError):
                lines.append({"text": "Sem produção planeada.", "color": "default"})
        else:
            lines.append({"text": "Sem produção planeada.", "color": "default"})
        return lines

    # --- Production summary ---
    total_pcs = sum(s.qty for s in day_segs)
    active_machines = sorted(set(s.machine_id for s in day_segs))
    total_setups = len({s.run_id for s in day_segs if s.setup_min > 0})

    lines.append(
        {
            "text": (
                f"Produção: {total_pcs:,} peças em {len(active_machines)} "
                f"máquina{'s' if len(active_machines) > 1 else ''}. "
                f"{total_setups} setup{'s' if total_setups != 1 else ''}."
            ),
            "color": "default",
        }
    )

    # --- Per-machine detail with WHY ---
    for m_id in active_machines:
        m_segs = sorted(
            [s for s in day_segs if s.machine_id == m_id],
            key=lambda s: s.start_min,
        )
        m_pcs = sum(s.qty for s in m_segs)
        m_setups = len({s.run_id for s in m_segs if s.setup_min > 0})
        m_used = sum(s.prod_min + s.setup_min for s in m_segs)
        m_capacity = available_machine_capacity(m_id, day_idx, engine_data, config)
        m_util = round(m_used / m_capacity * 100, 1) if m_capacity > 0 else 0

        # Tool sequence with reasons
        tool_parts: list[str] = []
        seen_tools: set[str] = set()
        for s in m_segs:
            if s.tool_id in seen_tools:
                continue
            seen_tools.add(s.tool_id)

            label = s.tool_id
            reasons: list[str] = []

            # Twin detail
            twin = _twin_detail(s)
            if twin:
                reasons.append(f"twin: {twin}")

            # Alt machine
            primary = _is_alt_machine(s, ops)
            if primary:
                reasons.append(f"redir. de {primary}")

            # Operational production due date
            if s.edd >= 0:
                reasons.append(f"prazo produção d{s.edd}")

            if reasons:
                label += f" ({', '.join(reasons)})"

            tool_parts.append(label)

        tool_str = " → ".join(tool_parts)
        line = f"  {m_id}: {m_pcs:,} pç, {m_util}% util."
        if m_setups > 0:
            line += f" {m_setups} setup{'s' if m_setups > 1 else ''}."
        line += f" [{tool_str}]"

        color = "red" if m_util > 95 else "orange" if m_util > 85 else "default"
        lines.append({"text": line, "color": color})

    # --- Deadlines on this day ---
    deadline_segs = [s for s in day_segs if s.edd == day_idx]
    if deadline_segs:
        skus = sorted(set(s.sku for s in deadline_segs if s.sku))
        shown_skus = ", ".join(skus[:5])
        if len(skus) > 5:
            shown_skus += "..."
        lines.append(
            {
                "text": (
                    f"Deadlines hoje: {len(deadline_segs)} "
                    f"lote{'s' if len(deadline_segs) > 1 else ''} ({shown_skus})."
                ),
                "color": "default",
            }
        )

    # --- Expedições (deliveries) ---
    clients = expedition_data.get("clients", [])
    if clients:
        ready_count = sum(c.get("ready", 0) for c in clients)
        total_count = sum(c.get("total", 0) for c in clients)
        not_ready = total_count - ready_count
        if total_count > 0:
            if not_ready == 0:
                lines.append(
                    {
                        "text": (
                            f"Expedições: {total_count} "
                            f"encomenda{'s' if total_count > 1 else ''}, todas prontas."
                        ),
                        "color": "green",
                    }
                )
            else:
                lines.append(
                    {
                        "text": f"Expedições: {not_ready} de {total_count} encomendas NÃO prontas.",
                        "color": "red",
                    }
                )
                for c in clients:
                    c_not_ready = c["total"] - c.get("ready", 0)
                    if c_not_ready > 0:
                        lines.append(
                            {
                                "text": (
                                    f"  {c['client']}: {c_not_ready} "
                                    f"encomenda{'s' if c_not_ready > 1 else ''} em falta."
                                ),
                                "color": "red",
                            }
                        )

    # --- Alerts (only from actions relevant to today) ---
    for a in actions:
        if a.category == "delivery" and a.severity == "critical":
            lines.append({"text": f"CRÍTICO: {a.phrase}", "color": "red"})
        elif a.category == "operators":
            lines.append({"text": f"ALERTA: {a.phrase}", "color": "red"})
        elif a.category == "crew":
            lines.append({"text": f"ALERTA: {a.phrase}", "color": "orange"})

    # --- High utilization warnings (only if not already flagged in machine lines) ---
    for m in machines_data.get("machines", []):
        util = m.get("util", 0) * 100
        if util > 95:
            lines.append(
                {
                    "text": (
                        f"RISCO: {m['id']} a {util:.0f}% utilização — capacidade quase esgotada."
                    ),
                    "color": "red",
                }
            )

    return lines


def compute_day_overview(
    current_date: str | None,
    operational_summary: dict,
    tomorrow: dict | None,
) -> dict:
    """Structured overview for the Hoje screen.

    This is additive to the legacy console payload: clients that still read
    summary/operational_summary/tomorrow can ignore it.
    """
    unavailable = operational_summary.get("unavailable", {})
    unavailable_count = sum(
        len(unavailable.get(kind, []) or [])
        for kind in ("machines", "tools", "operators")
    )
    tomorrow_setups = (tomorrow or {}).get("setups", []) or []
    tomorrow_operators = (tomorrow or {}).get("operators", []) or []
    tomorrow_problems = (tomorrow or {}).get("problems", []) or []
    tomorrow_operator_deficit = sum(
        max(0, int(item.get("deficit", 0) or 0))
        for item in tomorrow_operators
    )

    return {
        "today": {
            "date": current_date,
            "production_by_group": operational_summary.get("production_by_group", []),
            "setups_by_group_shift": operational_summary.get("setups_by_group_shift", []),
            "average_utilization_pct": operational_summary.get("average_utilization_pct", 0),
            "unavailable_count": unavailable_count,
            "trial_count": len(operational_summary.get("trials", []) or []),
            "expedition": operational_summary.get(
                "expedition",
                {"ready": 0, "partial": 0, "not_ready": 0},
            ),
        },
        "tomorrow": {
            "date": (tomorrow or {}).get("date"),
            "setups_count": len(tomorrow_setups),
            "operator_deficit": tomorrow_operator_deficit,
            "problems_count": len(tomorrow_problems),
            "expeditions_summary": (tomorrow or {}).get("expeditions_summary") or "",
        },
    }
