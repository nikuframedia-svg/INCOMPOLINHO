"""Trust-loop gate report for executable production plans."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any

from backend.config.types import FactoryConfig
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import hard_gate_metrics, validate_plan
from backend.types import EngineData

HARD_GATE_KEYS = (
    "setup_crew_overlaps",
    "machine_overlaps",
    "tool_conflicts",
    "day_cap_violations",
    "blocked_machine_segments",
    "blocked_tool_segments",
    "ghost_segments",
    "run_setup_order_violations",
)


def build_gate_report(
    segments: list[Segment],
    lots: list[Lot],
    score: dict[str, Any],
    data: EngineData | None,
    config: FactoryConfig | None,
) -> dict[str, Any]:
    """Build the public APS trust-loop report for a candidate plan."""

    violations = validate_plan(segments, data, config)
    physical_metrics = hard_gate_metrics(violations)
    delivery_metrics = {
        "otd": float(score.get("otd", 0.0) or 0.0),
        "otd_d": float(score.get("otd_d", 0.0) or 0.0),
        "tardy_count": int(score.get("tardy_count", 0) or 0),
        "otd_d_failures": int(score.get("otd_d_failures", 0) or 0),
    }
    window_metrics = {
        "early_window_violations": int(score.get("early_window_violations", 0) or 0),
        "early_window_violation_days": int(score.get("early_window_violation_days", 0) or 0),
    }
    metrics = {**physical_metrics, **delivery_metrics, **window_metrics}

    hard_gate_passed = all(physical_metrics[key] == 0 for key in HARD_GATE_KEYS)
    delivery_gate_passed = (
        delivery_metrics["otd"] >= 100.0
        and delivery_metrics["otd_d"] >= 100.0
        and delivery_metrics["tardy_count"] == 0
        and delivery_metrics["otd_d_failures"] == 0
    )
    # Materials-window gate: only gating in "hard" enforcement. A violation
    # means production needs material earlier than the release proxy allows —
    # a planner condition (infeasible_current_conditions), never bad physics.
    material_gate_passed = not (
        config is not None
        and getattr(config, "earliness_policy", "jit") == "window"
        and getattr(config, "early_window_enforcement", "soft") == "hard"
        and window_metrics["early_window_violations"] > 0
    )

    if hard_gate_passed and delivery_gate_passed and material_gate_passed:
        status = "applicable"
    elif hard_gate_passed:
        status = "infeasible_current_conditions"
    else:
        status = "invalid_physics"

    setup_overlap_detail = [
        _setup_overlap_detail(v) for v in violations if v.get("kind") == "setup_crew_overlap"
    ]
    late_detail = _late_detail(segments, lots, data, config) if data is not None else []

    return {
        "status": status,
        "hard_gate_passed": hard_gate_passed,
        "delivery_gate_passed": delivery_gate_passed,
        "material_gate_passed": material_gate_passed,
        "metrics": metrics,
        "violations": violations,
        "late_detail": late_detail,
        "setup_overlap_detail": setup_overlap_detail,
        "proposals": _build_proposals(metrics, violations, late_detail),
    }


def gate_passed(report: dict[str, Any] | None) -> bool:
    """True when a report allows applying the candidate plan."""

    return bool(report and report.get("status") == "applicable")


def _setup_overlap_detail(violation: dict[str, Any]) -> dict[str, Any]:
    other = violation.get("other") or {}
    return {
        "day_idx": violation.get("overlap_day_idx", violation.get("day_idx")),
        "start_min": violation.get("overlap_start_min", violation.get("start_min")),
        "machine_a": other.get("machine_id"),
        "machine_b": violation.get("machine_id"),
        "lot_a": other.get("lot_id"),
        "lot_b": violation.get("lot_id"),
        "tool_a": other.get("tool_id"),
        "tool_b": violation.get("tool_id"),
        "first_setup_abs_start": violation.get("first_setup_abs_start"),
        "first_setup_abs_end": violation.get("first_setup_abs_end"),
        "second_setup_abs_start": violation.get("second_setup_abs_start"),
        "second_setup_abs_end": violation.get("second_setup_abs_end"),
    }


def _late_detail(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig | None,
) -> list[dict[str, Any]]:
    try:
        from backend.analytics.late_delivery import analyze_late_deliveries

        report = analyze_late_deliveries(segments, lots, data, config)
        return [asdict(item) for item in report.analyses[:25]]
    except Exception:
        return []


def _build_proposals(
    metrics: dict[str, Any],
    violations: list[dict[str, Any]],
    late_detail: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    before = _proposal_metrics(metrics)
    late_machines = Counter(
        str(item.get("machine_id")) for item in late_detail if item.get("machine_id")
    )
    late_lots = [str(item.get("lot_id")) for item in late_detail if item.get("lot_id")]
    late_skus = [str(item.get("sku")) for item in late_detail if item.get("sku")]
    bottleneck_machine = late_machines.most_common(1)[0][0] if late_machines else None

    if metrics.get("setup_crew_overlaps", 0) > 0:
        proposals.append(
            _proposal(
                "sequence_setups",
                "adjust_sequence",
                "Serializar setups na sequencia do turno com uma unica equipa.",
                "Remove setups simultaneos; pode empurrar producao e criar atrasos.",
                before,
                {
                    **before,
                    "setup_crew_overlaps": 0,
                    "hard_gate_passed": True,
                },
                affected_machines=_machines_from_setup_violations(violations),
                rejection_reasons=[
                    "cria atraso",
                    "mantem overlap de setup crew",
                    "cria conflito de ferramenta",
                    "cria violacao de capacidade",
                ],
            )
        )
        proposals.append(
            _proposal(
                "advance_before_setup_peak",
                "advance_lot",
                "Antecipar lotes que colidem no pico de setups.",
                "Liberta a janela critica antecipando carga para uma janela executavel.",
                before,
                {
                    **before,
                    "setup_crew_overlaps": 0,
                    "hard_gate_passed": True,
                },
                affected_machines=_machines_from_setup_violations(violations),
                rejection_reasons=[
                    "nao existe janela anterior livre",
                    "cria atraso noutro SKU",
                    "cria conflito de ferramenta",
                ],
            )
        )

    if metrics.get("day_cap_violations", 0) > 0 or metrics.get("tardy_count", 0) > 0:
        proposals.append(
            _proposal(
                "overtime_capacity",
                "overtime",
                (
                    f"Testar horas extra na {bottleneck_machine}."
                    if bottleneck_machine
                    else "Testar horas extra nas maquinas com carga/atraso."
                ),
                "Aumenta capacidade diaria mantendo a regra de uma equipa de setup.",
                before,
                _delivery_target(before),
                affected_machines=[bottleneck_machine] if bottleneck_machine else [],
                affected_lots=late_lots[:8],
                affected_skus=_unique(late_skus)[:8],
                rejection_reasons=[
                    "OTD/OTD-D continuam abaixo de 100",
                    "cria overlap de setup crew",
                    "cria conflito de ferramenta",
                    "excede capacidade diaria ajustada",
                ],
            )
        )

    if metrics.get("tool_conflicts", 0) > 0 or metrics.get("machine_overlaps", 0) > 0:
        proposals.append(
            _proposal(
                "move_alt_machine",
                "move_to_alt",
                "Mover lote para maquina alternativa validada pela ferramenta.",
                "Remove conflito fisico se houver janela livre na alternativa.",
                before,
                {
                    **before,
                    "machine_overlaps": 0,
                    "tool_conflicts": 0,
                    "hard_gate_passed": True,
                },
                affected_machines=_machines_from_physical_violations(violations),
                rejection_reasons=[
                    "alternativa sem janela livre",
                    "ferramenta indisponivel na alternativa",
                    "cria atraso",
                ],
            )
        )

    if late_detail:
        proposals.append(
            _proposal(
                "subcontract_late_sku",
                "subcontract",
                "Subcontratar SKU/lote atrasado com lead time explicito.",
                "Antecipa entrega externa e reduz carga interna.",
                before,
                _delivery_target(before),
                affected_lots=late_lots[:8],
                affected_skus=_unique(late_skus)[:8],
                affected_machines=list(late_machines)[:8],
                rejection_reasons=[
                    "lead time externo nao recupera EDD",
                    "OTD/OTD-D continuam abaixo de 100",
                    "plano interno remanescente falha hard gates",
                ],
            )
        )
        proposals.append(
            _proposal(
                "advance_late_lot",
                "advance_lot",
                "Antecipar lote/SKU atrasado para janela anterior.",
                "Reduz atraso sem aumentar capacidade se existir janela livre.",
                before,
                _delivery_target(before),
                affected_lots=late_lots[:8],
                affected_skus=_unique(late_skus)[:8],
                affected_machines=list(late_machines)[:8],
                rejection_reasons=[
                    "nao existe janela anterior livre",
                    "cria stock cedo excessivo",
                    "cria conflito de ferramenta",
                    "cria atraso noutro lote",
                ],
            )
        )

    if any(v.get("kind") in {"machine_down", "tool_down"} for v in violations):
        proposals.append(
            _proposal(
                "advance_blocked_resource",
                "advance_lot",
                "Antecipar producao antes da paragem de maquina/ferramenta.",
                "Evita produzir em recurso bloqueado sem esconder o bloqueio.",
                before,
                {
                    **before,
                    "blocked_machine_segments": 0,
                    "blocked_tool_segments": 0,
                    "hard_gate_passed": True,
                },
                affected_machines=_machines_from_physical_violations(violations),
                rejection_reasons=[
                    "nao existe janela antes da paragem",
                    "cria atraso",
                    "cria overlap de setup crew",
                ],
            )
        )

    return proposals


def _proposal(
    proposal_id: str,
    proposal_type: str,
    description: str,
    expected_impact: str,
    before: dict[str, Any],
    after_target: dict[str, Any],
    *,
    affected_lots: list[str] | None = None,
    affected_skus: list[str] | None = None,
    affected_machines: list[str] | None = None,
    rejection_reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": proposal_id,
        "type": proposal_type,
        "description": description,
        "expected_impact": expected_impact,
        "before": before,
        "after_target": after_target,
        "affected_lots": affected_lots or [],
        "affected_skus": affected_skus or [],
        "affected_machines": [m for m in (affected_machines or []) if m],
        "requires_validation": True,
        "rejection_reasons": rejection_reasons or [],
    }


def _proposal_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "setup_crew_overlaps",
        "machine_overlaps",
        "tool_conflicts",
        "day_cap_violations",
        "blocked_machine_segments",
        "blocked_tool_segments",
        "ghost_segments",
        "otd",
        "otd_d",
        "tardy_count",
        "otd_d_failures",
    )
    return {key: metrics.get(key, 0) for key in keys}


def _delivery_target(before: dict[str, Any]) -> dict[str, Any]:
    return {
        **before,
        "otd": 100.0,
        "otd_d": 100.0,
        "tardy_count": 0,
        "otd_d_failures": 0,
        "delivery_gate_passed": True,
    }


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _machines_from_setup_violations(violations: list[dict[str, Any]]) -> list[str]:
    machines: list[str] = []
    for violation in violations:
        if violation.get("kind") != "setup_crew_overlap":
            continue
        for machine in (
            (violation.get("other") or {}).get("machine_id"),
            violation.get("machine_id"),
        ):
            if machine:
                machines.append(str(machine))
    return _unique(machines)


def _machines_from_physical_violations(violations: list[dict[str, Any]]) -> list[str]:
    machines: list[str] = []
    for violation in violations:
        for machine in (
            (violation.get("other") or {}).get("machine_id"),
            violation.get("machine_id"),
        ):
            if machine:
                machines.append(str(machine))
    return _unique(machines)
