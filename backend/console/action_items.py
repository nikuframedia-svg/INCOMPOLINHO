"""Action items — Spec 11 §3.

Real alerts are ACTIONS, not information.
If there's no consequence and no action, it's not an alert.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from backend.analytics.expedition import ExpeditionEntry, compute_expedition
from backend.analytics.order_tracking import readiness_for_entry
from backend.analytics.stock_projection import compute_stock_projections
from backend.config.types import FactoryConfig
from backend.console.tomorrow_prep import check_crew_bottleneck
from backend.scheduler.operators import compute_operator_alerts
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData


@dataclass
class Fix:
    description: str
    buttons: list[str]


@dataclass
class ActionItem:
    severity: str  # "critical" | "warning"
    phrase: str  # 1 sentence for state bar
    body: str  # 2-3 sentences with context
    actions: list[str]  # buttons
    deadline: str  # date or "hoje"/"amanhã"
    client: str  # for aggregation
    category: str  # "delivery" | "stockout" | "operators" | "crew"


# ─── Diagnostics ──────────────────────────────────────────────────────────


def _diagnose_why_short(
    entry: ExpeditionEntry,
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
) -> str:
    """ONE sentence in Portuguese explaining why delivery is short."""
    op = next((o for o in engine_data.ops if o.sku == entry.sku), None)
    if not op:
        return "Referência não está no plano."

    allocation = readiness_for_entry(entry, segments, lots, engine_data)
    ready_day = getattr(entry, "ready_day", None)
    if ready_day is None and allocation is not None:
        ready_day = allocation.ready_day
    if ready_day is not None and ready_day > entry.day_idx:
        late = ready_day - entry.day_idx
        return (
            "Produção desta encomenda fica disponível "
            f"{late} dia{'s' if late > 1 else ''} depois da entrega."
        )
    total = (
        allocation.covered_qty
        if allocation is not None
        else max(0, entry.order_qty - entry.shortfall)
    )
    if ready_day is None and total == 0 and not segments:
        return "Sem produção planeada para esta referência."
    if total < entry.order_qty:
        return (
            f"Produzidas {total:,} de {entry.order_qty:,} até à data. "
            f"Faltam {entry.order_qty - total:,}."
        )

    return "Produção planeada. A acompanhar."


def _find_fix(
    entry: ExpeditionEntry,
    engine_data: EngineData,
    segments: list[Segment],
    config: FactoryConfig,
) -> Fix | None:
    """Find a fix: alt machine or night shift. Returns None if no fix."""
    op = next((o for o in engine_data.ops if o.sku == entry.sku), None)
    if not op or entry.shortfall <= 0:
        return None

    needed_min = entry.shortfall / max(op.pH * (op.oee or 0.66), 1) * 60

    # Option A: alternative machine
    if op.alt:
        day_cap = config.day_capacity_min
        used = sum(
            s.prod_min + s.setup_min
            for s in segments
            if s.machine_id == op.alt and s.day_idx == entry.day_idx
        )
        free = max(0, day_cap - used)

        if free >= needed_min:
            return Fix(
                description=(
                    f"Hipótese: testar {op.alt}, com setup de {op.sH}h. Viabilidade por verificar."
                ),
                buttons=[f"Mover para {op.alt}", "Ver impacto"],
            )

    # Option B: night shift (7h = 420 min)
    if needed_min <= 420:
        return Fix(
            description=(
                f"Hipótese: testar turno noite na {op.m} ({needed_min:.0f} min estimados). "
                "Viabilidade por verificar."
            ),
            buttons=["Simular turno noite", "Ver impacto"],
        )

    return None


def _has_production_before(
    proj,  # StockProjection
    segments: list[Segment],
    lots: list[Lot],
) -> bool:
    """True if there's production for this op before stockout day."""
    if proj.stockout_day is None:
        return True

    lot_to_op = {lot.id: lot.op_id for lot in lots}
    for seg in segments:
        if seg.day_idx < proj.stockout_day:
            # Check regular lots
            if lot_to_op.get(seg.lot_id) == proj.op_id:
                return True
            # Check twin outputs
            if seg.twin_outputs:
                for op_id, _, _ in seg.twin_outputs:
                    if op_id == proj.op_id:
                        return True
    return False


# ─── Aggregation ──────────────────────────────────────────────────────────


def _aggregate_and_cap(items: list[ActionItem]) -> list[ActionItem]:
    """Group by (client, category). Max 7 items. Critical first."""
    if not items:
        return []

    groups: dict[tuple, list[ActionItem]] = defaultdict(list)
    for item in items:
        if item.client:
            key = (item.client, item.category)
        else:
            key = (id(item), item.category)
        groups[key].append(item)

    result = []
    for (client, cat), group in groups.items():
        if len(group) == 1:
            result.append(group[0])
        else:
            worst = "critical" if any(g.severity == "critical" for g in group) else "warning"
            # Only aggregate delivery/stockout by client name
            if isinstance(client, str) and client:
                phrase = f"{client}: {len(group)} entregas em risco esta semana."
            else:
                phrase = group[0].phrase
            result.append(
                ActionItem(
                    severity=worst,
                    phrase=phrase,
                    body="\n".join(g.body for g in group[:3]),
                    actions=group[0].actions,
                    deadline=group[0].deadline,
                    client=client if isinstance(client, str) else "",
                    category=cat,
                )
            )

    result.sort(key=lambda a: (0 if a.severity == "critical" else 1, a.deadline))
    return result[:7]


# ─── Main ─────────────────────────────────────────────────────────────────


def compute_action_items(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    config: FactoryConfig,
    day_idx: int = 0,
) -> list[ActionItem]:
    """Compute actionable alerts. Max 7 items, aggregated by client."""
    raw: list[ActionItem] = []

    # ── A. Deliveries at risk (expedition, day_idx <= 5) ──
    exp = compute_expedition(segments, lots, engine_data)
    for day in exp.days:
        if day.day_idx >= day_idx + 6:
            continue

        for entry in day.entries:
            if entry.coverage_pct >= 100:
                continue
            if day.day_idx < day_idx and entry.ready_day is not None and entry.ready_day < day_idx:
                continue

            cause = _diagnose_why_short(entry, segments, lots, engine_data)
            fix = _find_fix(entry, engine_data, segments, config)

            body_parts = [
                f"Faltam {entry.shortfall:,} peças de {entry.sku} "
                f"para {entry.client}. Entrega {day.date}.",
                cause,
            ]
            if fix:
                body_parts.append(fix.description)

            raw.append(
                ActionItem(
                    severity="critical" if day.day_idx <= day_idx + 1 else "warning",
                    phrase=f"Entrega {entry.client} em risco ({day.date}).",
                    body="\n".join(body_parts),
                    actions=fix.buttons if fix else ["Ver detalhes"],
                    deadline=day.date,
                    client=entry.client,
                    category="delivery",
                )
            )

    # ── B. Stock exhaustion without coverage (stockout_day <= 5) ──
    projs = compute_stock_projections(segments, lots, engine_data)
    for proj in projs:
        if proj.stockout_day is None or proj.stockout_day >= day_idx + 6:
            continue
        current = next((day for day in proj.days if day.day_idx == day_idx), None)
        if proj.stockout_day < day_idx and current is not None and current.stock >= 0:
            continue
        if _has_production_before(proj, segments, lots):
            continue

        demand_until = sum(d.demand for d in proj.days if d.day_idx <= proj.stockout_day)

        stockout_date = ""
        if proj.stockout_day < len(engine_data.workdays):
            stockout_date = engine_data.workdays[proj.stockout_day]

        raw.append(
            ActionItem(
                severity="warning",
                phrase=f"Stock de {proj.sku} esgota dia {proj.stockout_day}.",
                body=(
                    f"Stock actual: {proj.initial_stock:,} pç. "
                    f"Procura até dia {proj.stockout_day}: {demand_until:,} pç.\n"
                    f"Sem produção planeada antes."
                ),
                actions=["Antecipar produção", "Ver stock"],
                deadline=stockout_date,
                client=proj.client,
                category="stockout",
            )
        )

    # ── C. Operator shortages (day_idx <= 1) ──
    op_alerts = compute_operator_alerts(segments, engine_data, config)
    for a in op_alerts:
        if not day_idx <= a.day_idx <= day_idx + 1 or a.deficit <= 0:
            continue

        pl = "m" if a.deficit > 1 else ""
        ps = "es" if a.deficit > 1 else ""
        when = "Hoje" if a.day_idx == day_idx else "Amanhã"

        raw.append(
            ActionItem(
                severity="warning",
                phrase=(
                    f"{when} turno {a.shift}: falta{pl} {a.deficit} operador{ps} {a.machine_group}."
                ),
                body=(
                    f"Turno {a.shift} ({a.machine_group}): "
                    f"{a.required} operadores necessários, "
                    f"{a.available} disponíveis."
                ),
                actions=["Ver plano"],
                deadline=a.date,
                client="",
                category="operators",
            )
        )

    # ── D. Crew bottleneck (tomorrow, day_idx == 1) ──
    crew = check_crew_bottleneck(segments, day_idx=day_idx + 1, config=config)
    for c in crew:
        raw.append(
            ActionItem(
                severity="warning",
                phrase=f"Amanhã {c['time']}: {c['simultaneous']} setups simultâneos.",
                body=(
                    f"Máquinas {', '.join(c['machines'])} precisam de setup "
                    f"ao mesmo tempo.\n"
                    f"Espera estimada: {c['wait_min']} min."
                ),
                actions=["Ver timeline", "Reordenar setups"],
                deadline="amanhã",
                client="",
                category="crew",
            )
        )

    return _aggregate_and_cap(raw)
