"""Replan Proposals — Spec 12 §6.

Proactive improvement suggestions. Heuristic-based, does NOT re-schedule.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from backend.calendar import total_machine_capacity
from backend.config.types import FactoryConfig
from backend.scheduler.jit_policy import production_due_day
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData


@dataclass(slots=True)
class Proposal:
    id: str
    type: str  # "move_to_alt" | "night_shift" | "advance_production" | "merge_runs"
    description: str  # Portuguese
    estimated_impact: str
    affected_lots: list[str]
    machine_from: str | None
    machine_to: str | None
    priority: int  # 1=highest


@dataclass(slots=True)
class ReplanReport:
    proposals: list[Proposal]
    current_tardy: int
    current_setups: int
    summary: str


def generate_proposals(
    segments: list[Segment],
    lots: list[Lot],
    engine_data: EngineData,
    score: dict,
    config: FactoryConfig,
) -> ReplanReport:
    """Generate ranked improvement proposals."""
    day_cap = config.day_capacity_min
    current_tardy = score.get("tardy_count", 0)
    current_setups = score.get("setups", 0)

    proposals: list[Proposal] = []
    pid = 0

    # Build helpers
    op_map = {op.id: op for op in engine_data.ops}
    lot_segs: dict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        lot_segs[seg.lot_id].append(seg)

    machine_day_used: dict[tuple[str, int], float] = defaultdict(float)
    for seg in segments:
        machine_day_used[(seg.machine_id, seg.day_idx)] += seg.prod_min + seg.setup_min

    machine_util: dict[str, float] = defaultdict(float)
    total_used: dict[str, float] = defaultdict(float)
    for seg in segments:
        total_used[seg.machine_id] += seg.prod_min + seg.setup_min
    for m in engine_data.machines:
        total_capacity = total_machine_capacity(
            m.id,
            range(engine_data.n_days),
            engine_data,
            config,
        )
        machine_util[m.id] = total_used.get(m.id, 0) / max(total_capacity, 1)

    # ── A. Move to alt machine ──
    tardy_lots = []
    for lot in lots:
        segs = lot_segs.get(lot.id, [])
        if not segs:
            continue
        completion = max(s.day_idx for s in segs)
        due_day = production_due_day(lot)
        if completion > due_day:
            tardy_lots.append((lot, completion))

    for lot, completion in tardy_lots:
        op = op_map.get(lot.op_id)
        if not op or not op.alt:
            continue

        # Check free capacity on alt machine around EDD
        needed_min = lot.prod_min + lot.setup_min
        due_day = production_due_day(lot)
        free = sum(
            max(0, day_cap - machine_day_used.get((op.alt, d), 0))
            for d in range(max(0, due_day - 2), due_day + 1)
        )

        if free >= needed_min:
            pid += 1
            proposals.append(
                Proposal(
                    id=f"P{pid:03d}",
                    type="move_to_alt",
                    description=(
                        f"Mover {lot.op_id} de {op.m} para {op.alt}. "
                        f"Alt tem {free:.0f} min livres nos dias {due_day - 2}-{due_day}."
                    ),
                    estimated_impact=f"Resolve atraso de {completion - due_day} dia(s)",
                    affected_lots=[lot.id],
                    machine_from=op.m,
                    machine_to=op.alt,
                    priority=1,
                )
            )

    # ── B. Night shift ──
    machine_tardy_count: dict[str, int] = defaultdict(int)
    for lot, _ in tardy_lots:
        segs = lot_segs.get(lot.id, [])
        if segs:
            machine_tardy_count[segs[0].machine_id] += 1

    for m_id, util in machine_util.items():
        if util < 0.90:
            continue
        n_tardy = machine_tardy_count.get(m_id, 0)
        if n_tardy == 0:
            continue

        pid += 1
        proposals.append(
            Proposal(
                id=f"P{pid:03d}",
                type="night_shift",
                description=(
                    f"Turno noite na {m_id} (utilização {util * 100:.0f}%). "
                    f"{n_tardy} lote{'s' if n_tardy > 1 else ''} em atraso nesta máquina."
                ),
                estimated_impact=f"Pode resolver até {n_tardy} atraso(s)",
                affected_lots=[
                    lot.id
                    for lot, _ in tardy_lots
                    if lot_segs.get(lot.id, [{}])[0].machine_id == m_id  # type: ignore[union-attr]
                ][:5],
                machine_from=m_id,
                machine_to=None,
                priority=2,
            )
        )

    # ── C. Merge runs (save setups) ──
    # Find consecutive segments on same machine with same tool that have separate run_ids
    by_machine: dict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        if seg.setup_min > 0:
            by_machine[seg.machine_id].append(seg)

    for m_id, setup_segs in by_machine.items():
        sorted_segs = sorted(setup_segs, key=lambda s: s.day_idx * 10000 + s.start_min)
        for i in range(len(sorted_segs) - 1):
            s1 = sorted_segs[i]
            s2 = sorted_segs[i + 1]
            if s1.tool_id == s2.tool_id and s1.run_id != s2.run_id:
                gap = abs(s2.day_idx - s1.day_idx)
                if gap <= 2:
                    pid += 1
                    proposals.append(
                        Proposal(
                            id=f"P{pid:03d}",
                            type="merge_runs",
                            description=(
                                f"Juntar runs de {s1.tool_id} na {m_id} "
                                f"(dias {s1.day_idx}-{s2.day_idx}). Poupa 1 setup."
                            ),
                            estimated_impact="Poupa 1 setup",
                            affected_lots=[s1.lot_id, s2.lot_id],
                            machine_from=m_id,
                            machine_to=None,
                            priority=3,
                        )
                    )
                    if len([p for p in proposals if p.type == "merge_runs"]) >= 5:
                        break

    # Sort by priority
    proposals.sort(key=lambda p: p.priority)

    if not proposals:
        summary = "Sem propostas de melhoria. Plano está optimizado."
    else:
        n_tardy_fixes = sum(1 for p in proposals if p.type in ("move_to_alt", "night_shift"))
        n_setup_saves = sum(1 for p in proposals if p.type == "merge_runs")
        parts = []
        if n_tardy_fixes:
            parts.append(f"{n_tardy_fixes} proposta{'s' if n_tardy_fixes > 1 else ''} para atrasos")
        if n_setup_saves:
            parts.append(f"{n_setup_saves} oportunidade{'s' if n_setup_saves > 1 else ''} de merge")
        summary = f"{len(proposals)} propostas: {', '.join(parts)}."

    return ReplanReport(
        proposals=proposals,
        current_tardy=current_tardy,
        current_setups=current_setups,
        summary=summary,
    )
