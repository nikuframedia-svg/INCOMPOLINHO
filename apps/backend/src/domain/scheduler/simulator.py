"""Scenario Simulator — unified replan + what-if.

Accepts a list of mutations (disruptions, demand changes, capacity changes),
applies them to EngineData, re-runs schedule_all(), and returns delta vs baseline.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any

from ..scheduling.types import Block, EngineData
from .scheduler import schedule_all

# ── Mutation types ──


@dataclass
class SimMutation:
    type: str
    params: dict[str, Any] = field(default_factory=dict)


# ── Response types ──


@dataclass
class DeltaReport:
    otd_before: float
    otd_after: float
    otd_d_before: float
    otd_d_after: float
    overflow_before: int
    overflow_after: int
    tardiness_before: float
    tardiness_after: float
    blocks_changed: int
    blocks_unchanged: int
    blocks_new: int
    blocks_removed: int
    util_before: dict[str, float]
    util_after: dict[str, float]
    setups_before: int
    setups_after: int


@dataclass
class MutationImpact:
    mutation_idx: int
    type: str
    description: str
    ops_affected: int
    blocks_affected: int
    otd_d_impact: float
    severity: str  # "none" | "low" | "medium" | "high" | "critical"


@dataclass
class BlockChange:
    op_id: str
    sku: str
    tool_id: str
    action: str  # "moved" | "new" | "removed" | "resized" | "unchanged"
    from_machine: str
    to_machine: str
    from_day: int
    to_day: int
    qty: int
    reason: str


@dataclass
class SimResult:
    blocks: list[Block]
    score: dict[str, Any]
    time_ms: float
    delta: DeltaReport
    mutation_impacts: list[MutationImpact]
    block_changes: list[BlockChange]
    summary: list[str]


# ── Core simulation function ──


def simulate(
    engine_data: EngineData,
    mutations: list[SimMutation],
    settings: dict[str, Any] | None = None,
) -> SimResult:
    """Run scenario simulation.

    1. Schedule baseline
    2. Deep-copy + mutate engine_data
    3. Schedule scenario
    4. Compute delta, block changes, per-mutation impact (if <= 5)
    5. Generate PT summary
    """
    t0 = time.perf_counter()
    settings = settings or {}

    # 1. Baseline schedule
    baseline = schedule_all(engine_data, settings)
    baseline_score = baseline.score or {}

    # 2. Apply all mutations to a copy
    mutated = copy.deepcopy(engine_data)
    mutation_log: list[tuple[int, SimMutation, list[str]]] = []
    for i, mut in enumerate(mutations):
        affected = _apply_mutation(mutated, mut)
        mutation_log.append((i, mut, affected))

    # Handle dispatch rule override
    eff_settings = dict(settings)
    for mut in mutations:
        if mut.type == "change_dispatch_rule":
            eff_settings["dispatchRule"] = mut.params.get("rule", "ATCS")

    # 3. Schedule scenario
    scenario = schedule_all(mutated, eff_settings)
    scenario_score = scenario.score or {}

    # 4. Compute delta
    delta = _compute_delta(
        baseline_score,
        scenario_score,
        baseline.blocks,
        scenario.blocks,
        engine_data,
    )

    # 5. Block-level changes
    block_changes = _compute_block_changes(baseline.blocks, scenario.blocks, mutations)

    # 6. Per-mutation impact (only if <= 5 — performance guard)
    impacts: list[MutationImpact] = []
    if 0 < len(mutations) <= 5:
        baseline_otd_d = baseline_score.get("otd_delivery", 100.0)
        for i, mut in enumerate(mutations):
            solo_data = copy.deepcopy(engine_data)
            affected = _apply_mutation(solo_data, mut)
            solo_settings = dict(settings)
            if mut.type == "change_dispatch_rule":
                solo_settings["dispatchRule"] = mut.params.get("rule", "ATCS")
            solo_result = schedule_all(solo_data, solo_settings)
            solo_score = solo_result.score or {}
            solo_otd_d = solo_score.get("otd_delivery", 100.0)
            solo_overflow = solo_score.get("overflows", 0)
            severity = _classify_severity(baseline_otd_d, solo_otd_d, solo_overflow)
            impacts.append(
                MutationImpact(
                    mutation_idx=i,
                    type=mut.type,
                    description=_describe_mutation(mut, engine_data),
                    ops_affected=len(affected),
                    blocks_affected=_count_changed_blocks(baseline.blocks, solo_result.blocks),
                    otd_d_impact=round(solo_otd_d - baseline_otd_d, 2),
                    severity=severity,
                )
            )

    # 7. Summary
    summary = _generate_summary(mutations, delta, impacts, engine_data)

    elapsed = time.perf_counter() - t0
    return SimResult(
        blocks=scenario.blocks,
        score=scenario_score,
        time_ms=round(elapsed * 1000, 1),
        delta=delta,
        mutation_impacts=impacts,
        block_changes=block_changes,
        summary=summary,
    )


# ── Mutation application ──

_MACHINE_LABOR = {
    "PRM019": "Grandes",
    "PRM031": "Grandes",
    "PRM039": "Grandes",
    "PRM043": "Grandes",
    "PRM042": "Medias",
}


def _apply_mutation(data: EngineData, mut: SimMutation) -> list[str]:
    """Apply a single mutation to EngineData in-place. Returns affected op_ids."""
    p = mut.params
    affected: list[str] = []

    if mut.type == "machine_down":
        mid = p["machine_id"]
        start = p.get("start_day", 0)
        end = p.get("end_day", start)
        cap = p.get("capacity_factor", 0.0)
        if cap == 0.0:
            data.m_st[mid] = "down"
        for op in data.ops:
            if op.m == mid:
                affected.append(op.id)

    elif mut.type == "tool_down":
        tid = p["tool_id"]
        data.t_st[tid] = "down"
        for op in data.ops:
            if op.t == tid:
                affected.append(op.id)

    elif mut.type == "operator_shortage":
        labor_group = p["labor_group"]
        for op in data.ops:
            if _MACHINE_LABOR.get(op.m) == labor_group:
                affected.append(op.id)
        # Workforce config reduction (advisory)
        if data.workforce_config and data.workforce_config.labor_groups:
            reduction = p.get("reduction", 1)
            windows = data.workforce_config.labor_groups.get(labor_group, [])
            for w in windows:
                w.capacity = max(0, w.capacity - reduction)

    elif mut.type == "oee_change":
        target = p.get("tool_id", "__all__")
        new_oee = p["new_oee"]
        for tid, tool in data.tool_map.items():
            if target == "__all__" or tid == target:
                tool.oee = new_oee
                for op in data.ops:
                    if op.t == tid:
                        affected.append(op.id)

    elif mut.type == "rush_order":
        sku = p["sku"]
        qty = int(p["qty"])
        deadline = int(p["deadline_day"])
        existing = next((o for o in data.ops if o.sku == sku), None)
        if existing:
            if deadline < len(existing.d):
                existing.d[deadline] += qty
            affected.append(existing.id)
        # If SKU not found, we can't create a new op without tool info
        # The frontend should only offer existing SKUs

    elif mut.type == "demand_change":
        target = p.get("op_id") or p.get("sku")
        factor = float(p["factor"])
        for op in data.ops:
            if op.id == target or op.sku == target:
                op.d = [round(v * factor) for v in op.d]
                affected.append(op.id)

    elif mut.type == "cancel_order":
        target = p.get("op_id") or p.get("sku")
        from_day = int(p.get("from_day", 0))
        to_day = int(p.get("to_day", data.n_days - 1))
        for op in data.ops:
            if op.id == target or op.sku == target:
                for d in range(from_day, min(to_day + 1, len(op.d))):
                    op.d[d] = 0
                affected.append(op.id)

    elif mut.type == "third_shift":
        data.third_shift = True
        for op in data.ops:
            affected.append(op.id)

    elif mut.type == "overtime":
        # Overtime is advisory — the scheduler sees third_shift as capacity boost
        # For simplicity, enable third_shift as proxy
        mid = p.get("machine_id", "__all__")
        for op in data.ops:
            if mid == "__all__" or op.m == mid:
                affected.append(op.id)

    elif mut.type == "add_holiday":
        day_idx = int(p["day_idx"])
        if day_idx < len(data.workdays):
            data.workdays[day_idx] = False
        for op in data.ops:
            if day_idx < len(op.d) and op.d[day_idx] != 0:
                affected.append(op.id)

    elif mut.type == "remove_holiday":
        day_idx = int(p["day_idx"])
        if day_idx < len(data.workdays):
            data.workdays[day_idx] = True

    elif mut.type == "force_move":
        op_id = p["op_id"]
        to_machine = p["to_machine"]
        for op in data.ops:
            if op.id == op_id:
                op.m = to_machine
                affected.append(op.id)

    elif mut.type == "change_dispatch_rule":
        # Handled in simulate() via settings override
        for op in data.ops:
            affected.append(op.id)

    return list(set(affected))


# ── Delta computation ──

DAY_CAP = 1020  # minutes per day (2 shifts)


def _compute_delta(
    baseline_score: dict[str, Any],
    scenario_score: dict[str, Any],
    baseline_blocks: list[Block],
    scenario_blocks: list[Block],
    engine_data: EngineData,
) -> DeltaReport:
    base_ok = {(b.op_id, b.machine_id, b.day_idx) for b in baseline_blocks if b.type == "ok"}
    scen_ok = {(b.op_id, b.machine_id, b.day_idx) for b in scenario_blocks if b.type == "ok"}

    n_workdays = sum(1 for w in engine_data.workdays if w)
    cap_per_m = n_workdays * DAY_CAP

    def _util(blocks: list[Block]) -> dict[str, float]:
        used: dict[str, float] = {}
        for b in blocks:
            if b.type == "ok":
                used[b.machine_id] = used.get(b.machine_id, 0) + b.prod_min + b.setup_min
        return {
            mid: round(mins / cap_per_m * 100, 1) if cap_per_m > 0 else 0
            for mid, mins in used.items()
        }

    return DeltaReport(
        otd_before=baseline_score.get("otd", 100.0),
        otd_after=scenario_score.get("otd", 100.0),
        otd_d_before=baseline_score.get("otd_delivery", 100.0),
        otd_d_after=scenario_score.get("otd_delivery", 100.0),
        overflow_before=baseline_score.get("overflows", 0),
        overflow_after=scenario_score.get("overflows", 0),
        tardiness_before=baseline_score.get("tardiness_days", 0.0),
        tardiness_after=scenario_score.get("tardiness_days", 0.0),
        blocks_changed=len(base_ok - scen_ok),
        blocks_unchanged=len(base_ok & scen_ok),
        blocks_new=len(scen_ok - base_ok),
        blocks_removed=len(base_ok - scen_ok),
        util_before=_util(baseline_blocks),
        util_after=_util(scenario_blocks),
        setups_before=baseline_score.get("setup_count", 0),
        setups_after=scenario_score.get("setup_count", 0),
    )


# ── Block-level change tracking ──


def _compute_block_changes(
    baseline: list[Block],
    scenario: list[Block],
    mutations: list[SimMutation],
) -> list[BlockChange]:
    changes: list[BlockChange] = []

    # Index baseline by (op_id, edd_day)
    base_map: dict[tuple[str, int], Block] = {}
    for b in baseline:
        if b.type == "ok":
            key = (b.op_id, b.edd_day if b.edd_day is not None else -1)
            base_map[key] = b

    scen_keys_seen: set[tuple[str, int]] = set()

    for sb in scenario:
        if sb.type != "ok":
            continue
        key = (sb.op_id, sb.edd_day if sb.edd_day is not None else -1)
        scen_keys_seen.add(key)
        bb = base_map.get(key)

        if bb is None:
            changes.append(
                BlockChange(
                    op_id=sb.op_id,
                    sku=sb.sku,
                    tool_id=sb.tool_id,
                    action="new",
                    from_machine="",
                    to_machine=sb.machine_id,
                    from_day=-1,
                    to_day=sb.day_idx,
                    qty=sb.qty,
                    reason=_find_mutation_reason(sb.op_id, mutations),
                )
            )
        elif bb.machine_id != sb.machine_id or bb.day_idx != sb.day_idx:
            changes.append(
                BlockChange(
                    op_id=sb.op_id,
                    sku=sb.sku,
                    tool_id=sb.tool_id,
                    action="moved",
                    from_machine=bb.machine_id,
                    to_machine=sb.machine_id,
                    from_day=bb.day_idx,
                    to_day=sb.day_idx,
                    qty=sb.qty,
                    reason=_find_mutation_reason(sb.op_id, mutations),
                )
            )
        elif abs(bb.qty - sb.qty) > 1:
            changes.append(
                BlockChange(
                    op_id=sb.op_id,
                    sku=sb.sku,
                    tool_id=sb.tool_id,
                    action="resized",
                    from_machine=bb.machine_id,
                    to_machine=sb.machine_id,
                    from_day=bb.day_idx,
                    to_day=sb.day_idx,
                    qty=sb.qty,
                    reason="Quantidade ajustada",
                )
            )

    # Removed blocks
    for key, bb in base_map.items():
        if key not in scen_keys_seen:
            changes.append(
                BlockChange(
                    op_id=bb.op_id,
                    sku=bb.sku,
                    tool_id=bb.tool_id,
                    action="removed",
                    from_machine=bb.machine_id,
                    to_machine="",
                    from_day=bb.day_idx,
                    to_day=-1,
                    qty=bb.qty,
                    reason=_find_mutation_reason(bb.op_id, mutations),
                )
            )

    return changes


# ── Summary generation (Portuguese) ──


def _generate_summary(
    mutations: list[SimMutation],
    delta: DeltaReport,
    impacts: list[MutationImpact],
    engine_data: EngineData,
) -> list[str]:
    lines: list[str] = []

    for imp in impacts:
        if imp.severity == "none":
            lines.append(f"{imp.description} — sem impacto no plano")
        elif imp.severity == "low":
            lines.append(f"{imp.description} — {imp.ops_affected} ops afectadas, OTD-D mantém-se")
        elif imp.severity in ("medium", "high"):
            verb = "cai" if imp.otd_d_impact < 0 else "sobe"
            lines.append(f"{imp.description} — OTD-D {verb} {abs(imp.otd_d_impact):.1f}%")
        elif imp.severity == "critical":
            lines.append(f"{imp.description} — {imp.ops_affected} operações em risco")

    if delta.otd_d_after >= 100:
        lines.append(f"Resultado final: OTD-D {delta.otd_d_after:.1f}% — plano viável")
    elif delta.otd_d_after >= 98:
        lines.append(
            f"Resultado: OTD-D {delta.otd_d_after:.1f}% "
            f"(era {delta.otd_d_before:.1f}%) — impacto controlável"
        )
    else:
        lines.append(
            f"Resultado: OTD-D {delta.otd_d_after:.1f}% "
            f"(era {delta.otd_d_before:.1f}%) — necessária acção correctiva"
        )

    if delta.overflow_after > 0:
        lines.append(
            f"Overflow: {delta.overflow_after} min ({delta.overflow_after / DAY_CAP:.1f} dias)"
        )

    parts = []
    if delta.blocks_changed > 0:
        parts.append(f"{delta.blocks_changed} movidos")
    if delta.blocks_new > 0:
        parts.append(f"{delta.blocks_new} novos")
    if delta.blocks_removed > 0:
        parts.append(f"{delta.blocks_removed} removidos")
    if parts:
        lines.append(f"Blocos alterados: {', '.join(parts)}")

    return lines


# ── Helpers ──


def _describe_mutation(mut: SimMutation, engine_data: EngineData) -> str:
    p = mut.params
    if mut.type == "machine_down":
        return f"{p['machine_id']} parada dias {p.get('start_day', 0)}-{p.get('end_day', 0)}"
    if mut.type == "tool_down":
        return f"Ferramenta {p['tool_id']} avariada"
    if mut.type == "operator_shortage":
        return f"Falta de {p.get('reduction', 1)} operadores ({p['labor_group']})"
    if mut.type == "oee_change":
        target = p.get("tool_id", "todas")
        return f"OEE → {p['new_oee']:.0%} ({target})"
    if mut.type == "rush_order":
        return f"Rush: {p['qty']:,} pç de {p['sku']} até dia {p['deadline_day']}"
    if mut.type == "demand_change":
        target = p.get("op_id") or p.get("sku", "?")
        return f"Demanda {target} ×{p['factor']:.1f}"
    if mut.type == "cancel_order":
        target = p.get("op_id") or p.get("sku", "?")
        return f"Cancelamento {target}"
    if mut.type == "third_shift":
        return "3º turno activado"
    if mut.type == "overtime":
        m = p.get("machine_id", "todas")
        return f"Horas extra ({m})"
    if mut.type == "add_holiday":
        return f"Feriado dia {p['day_idx']}"
    if mut.type == "remove_holiday":
        return f"Dia extra (dia {p['day_idx']})"
    if mut.type == "force_move":
        return f"Mover {p['op_id']} → {p['to_machine']}"
    if mut.type == "change_dispatch_rule":
        return f"Regra dispatch: {p.get('rule', '?')}"
    return f"{mut.type}: {p}"


def _classify_severity(otd_d_before: float, otd_d_after: float, overflow: int) -> str:
    drop = otd_d_before - otd_d_after
    if overflow > 1000:
        return "critical"
    if drop > 5:
        return "critical"
    if drop > 2:
        return "high"
    if drop > 0.5:
        return "medium"
    if drop > 0:
        return "low"
    return "none"


def _count_changed_blocks(baseline: list[Block], scenario: list[Block]) -> int:
    base_keys = {(b.op_id, b.machine_id, b.day_idx) for b in baseline if b.type == "ok"}
    scen_keys = {(b.op_id, b.machine_id, b.day_idx) for b in scenario if b.type == "ok"}
    return len(base_keys.symmetric_difference(scen_keys))


def _find_mutation_reason(op_id: str, mutations: list[SimMutation]) -> str:
    for mut in mutations:
        p = mut.params
        if mut.type == "machine_down":
            return f"Máquina {p.get('machine_id', '?')} parada"
        if mut.type == "rush_order":
            return f"Rush order {p.get('sku', '?')}"
        if mut.type == "force_move" and p.get("op_id") == op_id:
            return "Movido manualmente"
    return "Reagendado"
