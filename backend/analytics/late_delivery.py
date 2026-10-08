"""Late Delivery Analysis — Spec 12 §4.

Root cause classification for ALL tardy lots.
Categories: capacity, setup_overhead, priority_conflict, lead_time, tool_contention.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from backend.calendar import available_machine_capacity, total_machine_capacity
from backend.config.types import FactoryConfig
from backend.scheduler.jit_policy import (
    add_workdays,
    calendar_holidays,
    expedition_day,
    lot_demand_output_milestones,
    lot_output_milestones,
    production_due_day,
)
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData


@dataclass(slots=True)
class TardyAnalysis:
    lot_id: str
    op_id: str
    sku: str
    machine_id: str
    edd: int
    completion_day: int
    delay_days: int
    root_cause: (
        str  # "capacity" | "setup_overhead" | "priority_conflict" | "lead_time" | "tool_contention"
    )
    explanation: str  # Portuguese
    capacity_gap_min: float
    competing_lots: list[str]
    customer_ready_day: int | None = None
    production_due_day: int | None = None
    subcontract_dispatch_day: int | None = None


@dataclass(slots=True)
class LateDeliveryReport:
    tardy_count: int
    avg_delay: float
    by_cause: dict[str, int]
    analyses: list[TardyAnalysis]
    worst_machine: str | None
    suggestion: str


def analyze_late_deliveries(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    config: FactoryConfig | None = None,
) -> LateDeliveryReport:
    """Classify root causes for all tardy lots."""
    # Build lot → segments mapping
    lot_segs: dict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        lot_segs[seg.lot_id].append(seg)

    # Build machine+day utilization
    machine_day_used: dict[tuple[str, int], float] = defaultdict(float)
    for seg in segments:
        machine_day_used[(seg.machine_id, seg.day_idx)] += seg.prod_min + seg.setup_min

    # Build machine+day lot list (for priority conflict detection)
    machine_day_lots: dict[tuple[str, int], list[str]] = defaultdict(list)
    for seg in segments:
        key = (seg.machine_id, seg.day_idx)
        if seg.lot_id not in machine_day_lots[key]:
            machine_day_lots[key].append(seg.lot_id)

    lot_map = {lot.id: lot for lot in lots}
    max_lead = max(
        (
            int(output.get("subcontract_lead_time_days", 0) or 0)
            for lot in lots
            for output in lot_output_milestones(lot)
        ),
        default=0,
    )
    holidays = calendar_holidays(
        engine_data,
        min((segment.day_idx for segment in segments), default=0) - 14,
        engine_data.n_days + max_lead * 2 + 14,
    )
    analyses: list[TardyAnalysis] = []

    for lot in lots:
        segs = lot_segs.get(lot.id, [])
        if not segs:
            continue

        completion_day = max(s.day_idx for s in segs)
        output_readiness = [
            (
                add_workdays(
                    completion_day,
                    int(output.get("subcontract_lead_time_days", 0) or 0),
                    holidays,
                )
                if bool(output.get("is_subcontracted"))
                else completion_day,
                int(output.get("customer_delivery_day", expedition_day(lot))),
                output,
            )
            for output in lot_demand_output_milestones(lot)
        ]
        customer_ready_day, customer_delivery_day, controlling_output = min(
            output_readiness,
            key=lambda item: (
                -(item[0] - item[1]),
                item[1],
                str(item[2].get("op_id", lot.op_id)),
            ),
            default=(completion_day, expedition_day(lot), {}),
        )
        if customer_ready_day <= customer_delivery_day:
            continue  # not tardy

        delay = customer_ready_day - customer_delivery_day
        machine = segs[0].machine_id
        op_id = str(controlling_output.get("op_id", lot.op_id))
        sku = str(controlling_output.get("sku", lot.sku or op_id))
        controlling_production_due = int(
            controlling_output.get(
                "production_due_day",
                production_due_day(lot, holidays),
            )
        )

        cause, explanation, gap, competing = _classify(
            lot,
            segs,
            completion_day,
            controlling_production_due,
            machine,
            machine_day_used,
            machine_day_lots,
            lot_map,
            engine_data,
            config,
        )

        analyses.append(
            TardyAnalysis(
                lot_id=lot.id,
                op_id=op_id,
                sku=sku,
                machine_id=machine,
                edd=customer_delivery_day,
                completion_day=completion_day,
                delay_days=delay,
                root_cause=cause,
                explanation=explanation,
                capacity_gap_min=gap,
                competing_lots=competing,
                customer_ready_day=customer_ready_day,
                production_due_day=controlling_production_due,
                subcontract_dispatch_day=(
                    int(controlling_output["subcontract_dispatch_day"])
                    if controlling_output.get("subcontract_dispatch_day") is not None
                    else None
                ),
            )
        )

    # Aggregate
    by_cause: dict[str, int] = defaultdict(int)
    machine_tardy: dict[str, int] = defaultdict(int)
    for a in analyses:
        by_cause[a.root_cause] += 1
        machine_tardy[a.machine_id] += 1

    worst = max(machine_tardy, key=machine_tardy.get) if machine_tardy else None
    avg_delay = (
        round(sum(a.delay_days for a in analyses) / len(analyses), 2)
        if analyses
        else 0.0
    )

    if not analyses:
        suggestion = "Sem atrasos. Plano cumpre todas as entregas."
    elif worst:
        suggestion = (
            f"{len(analyses)} lote{'s' if len(analyses) > 1 else ''} em atraso. "
            f"Máquina mais afectada: {worst} ({machine_tardy[worst]} atrasos). "
            f"Causa principal: {max(by_cause, key=by_cause.get)}."
        )
    else:
        suggestion = f"{len(analyses)} lotes em atraso."

    return LateDeliveryReport(
        tardy_count=len(analyses),
        avg_delay=avg_delay,
        by_cause=dict(by_cause),
        analyses=analyses,
        worst_machine=worst,
        suggestion=suggestion,
    )


def _classify(
    lot: Lot,
    segs: list[Segment],
    completion_day: int,
    delivery_day: int,
    machine: str,
    machine_day_used: dict[tuple[str, int], float],
    machine_day_lots: dict[tuple[str, int], list[str]],
    lot_map: dict[str, Lot],
    engine_data: EngineData,
    config: FactoryConfig | None,
) -> tuple[str, str, float, list[str]]:
    """Classify root cause. Returns (cause, explanation, gap_min, competing_lots)."""

    total_prod = lot.prod_min
    total_setup = lot.setup_min
    total_time = total_prod + total_setup

    # 1. Lead time: impossible even with full capacity
    capacity_until_deadline = total_machine_capacity(
        machine,
        range(0, max(0, delivery_day + 1)),
        engine_data,
        config,
    )
    if total_time > capacity_until_deadline:
        return (
            "lead_time",
            f"Produção e setup ({total_time:.0f} min) excedem a capacidade "
            f"até ao deadline ({capacity_until_deadline:.0f} min).",
            total_time - capacity_until_deadline,
            [],
        )

    # 2. Setup overhead: setup > 20% of total run time
    if total_time > 0 and total_setup / total_time > 0.20:
        return (
            "setup_overhead",
            f"Setup ({total_setup:.0f} min) representa "
            f"{total_setup / total_time * 100:.0f}% do tempo total.",
            total_setup,
            [],
        )

    # 3. Capacity: machine utilization near EDD > 95%
    edd_window = range(max(0, delivery_day - 2), delivery_day + 1)
    window_util = []
    for day_idx in edd_window:
        capacity = available_machine_capacity(machine, day_idx, engine_data, config)
        window_util.append(
            machine_day_used.get((machine, day_idx), 0) / capacity
            if capacity > 0
            else 0.0
        )
    avg_util = sum(window_util) / max(len(window_util), 1)
    if avg_util > 0.95:
        gap = sum(
            max(
                0,
                machine_day_used.get((machine, d), 0)
                - available_machine_capacity(machine, d, engine_data, config),
            )
            for d in edd_window
        )
        return (
            "capacity",
            f"Máquina {machine} a {avg_util * 100:.0f}% nos dias "
            f"{min(edd_window)}-{max(edd_window)}. Sem espaço.",
            gap,
            [],
        )

    # 4. Priority conflict: another lot with lower EDD on same machine in window
    competing: list[str] = []
    for d in edd_window:
        for other_id in machine_day_lots.get((machine, d), []):
            if other_id == lot.id:
                continue
            other = lot_map.get(other_id)
            if other and production_due_day(other) < delivery_day:
                competing.append(other_id)

    if competing:
        return (
            "priority_conflict",
            f"{len(competing)} lote{'s' if len(competing) > 1 else ''} "
            "com prazo de produção anterior "
            f"na {machine} deslocaram este lote.",
            0.0,
            competing[:5],
        )

    # 5. Tool contention fallback would need a full segment scan; keep capacity as default.
    return (
        "capacity",
        f"Capacidade insuficiente na {machine} para cumprir o prazo de produção "
        f"D{delivery_day}.",
        0.0,
        [],
    )
