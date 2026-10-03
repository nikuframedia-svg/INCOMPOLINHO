"""DQA / TrustIndex — Spec 12 §3.

Data quality scoring with automation gate recommendation.
4 dimensions: completeness, validity, consistency, richness.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.config.types import FactoryConfig
from backend.types import EngineData


@dataclass(slots=True)
class DQADimension:
    name: str  # "completeness" | "validity" | "consistency" | "richness"
    score: float  # 0-100
    details: list[str]


@dataclass(slots=True)
class TrustResult:
    score: int  # 0-100
    gate: str  # "full_auto" | "monitoring" | "suggestion" | "manual"
    dimensions: list[DQADimension]
    n_ops: int
    n_issues: int


def _score_completeness(data: EngineData) -> DQADimension:
    """% of ops with essential fields filled."""
    details: list[str] = []
    if not data.ops:
        return DQADimension("completeness", 0.0, ["Sem operações"])

    checks = 0
    passed = 0
    for op in data.ops:
        # pH present and > 0
        checks += 1
        if op.pH > 0:
            passed += 1
        else:
            details.append(f"{op.id}: pH vazio/zero")

        # Client non-empty
        checks += 1
        if op.client:
            passed += 1

        # Designation non-empty
        checks += 1
        if op.designation:
            passed += 1

        # Demand array aligned with n_days
        checks += 1
        if len(op.d) == data.n_days:
            passed += 1
        else:
            details.append(f"{op.id}: len(d)={len(op.d)} != n_days={data.n_days}")

    score = (passed / max(checks, 1)) * 100
    return DQADimension("completeness", round(score, 1), details[:5])


def _score_validity(data: EngineData) -> DQADimension:
    """Fields within valid ranges."""
    details: list[str] = []
    machine_ids = {m.id for m in data.machines}

    if not data.ops:
        return DQADimension("validity", 0.0, ["Sem operações"])

    checks = 0
    passed = 0
    for op in data.ops:
        # pH > 0
        checks += 1
        if op.pH > 0:
            passed += 1

        # OEE in (0, 1]
        checks += 1
        if 0 < op.oee <= 1.0:
            passed += 1
        else:
            details.append(f"{op.id}: oee={op.oee}")

        # sH >= 0
        checks += 1
        if op.sH >= 0:
            passed += 1

        # eco_lot >= 0
        checks += 1
        if op.eco_lot >= 0:
            passed += 1

        # Machine exists
        checks += 1
        if op.m in machine_ids:
            passed += 1
        else:
            details.append(f"{op.id}: máquina {op.m!r} inválida")

        # Alt machine exists if defined
        if op.alt:
            checks += 1
            if op.alt in machine_ids:
                passed += 1
            else:
                details.append(f"{op.id}: alt {op.alt!r} inválida")

    score = (passed / max(checks, 1)) * 100
    return DQADimension("validity", round(score, 1), details[:5])


def _score_consistency(data: EngineData) -> DQADimension:
    """Internal data consistency."""
    details: list[str] = []
    checks = 0
    passed = 0

    op_ids = {op.id for op in data.ops}

    # Twin groups reference valid ops
    for tg in data.twin_groups:
        checks += 1
        if tg.op_id_1 in op_ids and tg.op_id_2 in op_ids:
            passed += 1
        else:
            details.append(f"Twin {tg.tool_id}: ops inválidos")

    # Twin ops on same machine
    op_map = {op.id: op for op in data.ops}
    for tg in data.twin_groups:
        checks += 1
        op1 = op_map.get(tg.op_id_1)
        op2 = op_map.get(tg.op_id_2)
        if op1 and op2 and op1.m == op2.m:
            passed += 1
        elif op1 and op2:
            details.append(f"Twin {tg.tool_id}: máquinas {op1.m} vs {op2.m}")

    # workdays count matches n_days
    checks += 1
    if len(data.workdays) >= data.n_days:
        passed += 1
    else:
        details.append(f"workdays={len(data.workdays)} < n_days={data.n_days}")

    # No duplicate op.id
    checks += 1
    if len(op_ids) == len(data.ops):
        passed += 1
    else:
        details.append(f"{len(data.ops) - len(op_ids)} op.id duplicados")

    if checks == 0:
        return DQADimension("consistency", 100.0, [])

    score = (passed / checks) * 100
    return DQADimension("consistency", round(score, 1), details[:5])


def _score_richness(data: EngineData) -> DQADimension:
    """Optional but valuable data presence."""
    details: list[str] = []
    if not data.ops:
        return DQADimension("richness", 0.0, ["Sem operações"])

    checks = 0
    passed = 0

    # % ops with alt machine
    with_alt = sum(1 for op in data.ops if op.alt)
    checks += 1
    alt_pct = with_alt / len(data.ops)
    if alt_pct > 0.3:
        passed += 1
    else:
        details.append(f"Só {with_alt}/{len(data.ops)} ops com máquina alternativa")

    # % ops with eco_lot > 0
    with_eco = sum(1 for op in data.ops if op.eco_lot > 0)
    checks += 1
    if with_eco / len(data.ops) > 0.5:
        passed += 1

    # Holidays defined
    checks += 1
    if data.holidays:
        passed += 1
    else:
        details.append("Sem feriados definidos")

    # Client demands populated
    checks += 1
    if data.client_demands:
        passed += 1
    else:
        details.append("Sem client_demands")

    score = (passed / max(checks, 1)) * 100
    return DQADimension("richness", round(score, 1), details[:5])


def compute_trust_index(
    data: EngineData,
    config: FactoryConfig | None = None,
) -> TrustResult:
    """Score data quality. Returns 0-100 score + gate recommendation."""
    completeness = _score_completeness(data)
    validity = _score_validity(data)
    consistency = _score_consistency(data)
    richness = _score_richness(data)
    consistency.details.extend(warning for warning in data.input_warnings
                               if warning not in consistency.details)

    # Weighted score
    weighted = (
        completeness.score * 0.25
        + validity.score * 0.30
        + consistency.score * 0.25
        + richness.score * 0.20
    )
    score = round(weighted)

    # Gate thresholds
    if score >= 90:
        gate = "full_auto"
    elif score >= 70:
        gate = "monitoring"
    elif score >= 50:
        gate = "suggestion"
    else:
        gate = "manual"

    dims = [completeness, validity, consistency, richness]
    n_issues = sum(len(d.details) for d in dims)

    return TrustResult(
        score=score,
        gate=gate,
        dimensions=dims,
        n_ops=len(data.ops),
        n_issues=n_issues,
    )
