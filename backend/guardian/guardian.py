"""Guardian — Spec 12 §1.

Input validation (pre-schedule) and output validation (post-schedule).
Never crashes — returns issues list. Drops or fixes bad data.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from backend.config.types import FactoryConfig
from backend.scheduler.types import Segment
from backend.types import EngineData

DEFAULT_OEE = 0.66


@dataclass(slots=True)
class GuardianIssue:
    op_id: str
    field: str
    severity: str  # "drop" | "warn" | "fix"
    message: str


@dataclass(slots=True)
class GuardianResult:
    cleaned: EngineData
    dropped_ops: list[str]
    issues: list[GuardianIssue]
    is_clean: bool


def validate_input(
    data: EngineData,
    config: FactoryConfig | None = None,
) -> GuardianResult:
    """Validate EngineData before scheduling. Returns cleaned copy + issues."""
    issues: list[GuardianIssue] = []
    drop_ids: set[str] = set()
    machine_ids = {m.id for m in data.machines}

    # Detect duplicate op.id
    seen_ids: set[str] = set()
    for op in data.ops:
        if op.id in seen_ids:
            issues.append(GuardianIssue(op.id, "id", "drop", f"op.id duplicado: {op.id}"))
            drop_ids.add(op.id)
        seen_ids.add(op.id)

    for op in data.ops:
        if op.id in drop_ids:
            continue

        # pH <= 0 → drop
        if op.pH <= 0:
            issues.append(GuardianIssue(op.id, "pH", "drop", f"pH={op.pH} inválido (div by zero)"))
            drop_ids.add(op.id)
            continue

        # Machine not in data.machines → drop
        if op.m not in machine_ids:
            issues.append(GuardianIssue(op.id, "m", "drop", f"Máquina {op.m!r} não existe"))
            drop_ids.add(op.id)
            continue

        # eco_lot < 0 → fix
        if op.eco_lot < 0:
            issues.append(GuardianIssue(op.id, "eco_lot", "fix", f"eco_lot={op.eco_lot} → 0"))

        # demand array length mismatch → fix
        if len(op.d) != data.n_days:
            issues.append(
                GuardianIssue(
                    op.id,
                    "d",
                    "fix",
                    f"len(d)={len(op.d)} != n_days={data.n_days}",
                )
            )

        # OEE out of range → fix
        if op.oee <= 0 or op.oee > 1.0:
            issues.append(GuardianIssue(op.id, "oee", "fix", f"oee={op.oee} → {DEFAULT_OEE}"))

        # Negative setup hours → fix
        if op.sH < 0:
            issues.append(GuardianIssue(op.id, "sH", "fix", f"sH={op.sH} → 0"))

        # All demand zero + no backlog → warn
        if all(d == 0 for d in op.d) and op.backlog == 0:
            issues.append(GuardianIssue(op.id, "d", "warn", "Sem demand nem backlog"))

    # Validate twin groups
    op_id_set = seen_ids - drop_ids
    drop_twin_indices: set[int] = set()
    for i, tg in enumerate(data.twin_groups):
        if tg.op_id_1 not in op_id_set or tg.op_id_2 not in op_id_set:
            issues.append(
                GuardianIssue(
                    f"twin:{tg.tool_id}",
                    "twin_group",
                    "drop",
                    f"Twin referencia op inexistente ({tg.op_id_1}, {tg.op_id_2})",
                )
            )
            drop_twin_indices.add(i)
            continue

        # Check machine mismatch
        op1 = next((o for o in data.ops if o.id == tg.op_id_1), None)
        op2 = next((o for o in data.ops if o.id == tg.op_id_2), None)
        if op1 and op2 and op1.m != op2.m:
            issues.append(
                GuardianIssue(
                    f"twin:{tg.tool_id}",
                    "twin_group",
                    "warn",
                    f"Twin com máquinas diferentes: {op1.m} vs {op2.m}",
                )
            )

    # Build cleaned EngineData
    if not issues:
        return GuardianResult(
            cleaned=data,
            dropped_ops=[],
            issues=[],
            is_clean=True,
        )

    cleaned = copy.copy(data)

    # Deep-copy ops to avoid mutating originals
    cleaned.ops = [copy.copy(op) for op in data.ops if op.id not in drop_ids]

    # Apply fixes on remaining ops
    for op in cleaned.ops:
        if op.eco_lot < 0:
            op.eco_lot = 0
        if len(op.d) != data.n_days:
            if len(op.d) < data.n_days:
                op.d = list(op.d) + [0] * (data.n_days - len(op.d))
            else:
                op.d = list(op.d[: data.n_days])
        if op.oee <= 0 or op.oee > 1.0:
            op.oee = DEFAULT_OEE
        if op.sH < 0:
            op.sH = 0

    # Filter twin groups
    if drop_twin_indices:
        cleaned.twin_groups = [
            tg for i, tg in enumerate(data.twin_groups) if i not in drop_twin_indices
        ]

    return GuardianResult(
        cleaned=cleaned,
        dropped_ops=sorted(drop_ids),
        issues=issues,
        is_clean=False,
    )


def validate_output(
    segments: list[Segment],
    data: EngineData,
) -> list[GuardianIssue]:
    """Post-schedule sanity checks on segments."""
    issues: list[GuardianIssue] = []
    machine_ids = {m.id for m in data.machines}

    # Group segments by machine+day for overlap detection
    by_machine_day: dict[tuple[str, int], list[Segment]] = {}

    for seg in segments:
        # Out of horizon
        if seg.day_idx >= data.n_days:
            issues.append(
                GuardianIssue(
                    seg.lot_id,
                    "day_idx",
                    "warn",
                    f"Segment dia {seg.day_idx} >= horizonte {data.n_days}",
                )
            )

        # Outside shift bounds (420=07:00, 1440=00:00)
        if seg.start_min < 420 or seg.end_min > 1440:
            issues.append(
                GuardianIssue(
                    seg.lot_id,
                    "time",
                    "warn",
                    f"Segment fora dos turnos: {seg.start_min}-{seg.end_min}",
                )
            )

        # Orphan machine
        if seg.machine_id not in machine_ids:
            issues.append(
                GuardianIssue(
                    seg.lot_id,
                    "machine_id",
                    "warn",
                    f"Máquina {seg.machine_id!r} não existe",
                )
            )

        # Negative qty
        if seg.qty < 0:
            issues.append(
                GuardianIssue(
                    seg.lot_id,
                    "qty",
                    "warn",
                    f"Produção negativa: {seg.qty}",
                )
            )

        key = (seg.machine_id, seg.day_idx)
        by_machine_day.setdefault(key, []).append(seg)

    # Overlap detection
    for (machine, day), segs in by_machine_day.items():
        sorted_segs = sorted(segs, key=lambda s: s.start_min)
        for i in range(len(sorted_segs) - 1):
            if sorted_segs[i].end_min > sorted_segs[i + 1].start_min:
                issues.append(
                    GuardianIssue(
                        sorted_segs[i].lot_id,
                        "overlap",
                        "warn",
                        f"Sobreposição {machine} dia {day}: "
                        f"{sorted_segs[i].end_min} > {sorted_segs[i + 1].start_min}",
                    )
                )

    return issues
