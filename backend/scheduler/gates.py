"""Trust-loop gate report for executable production plans.

Deliveries are judged per order (AGENTS §1.2): ``delivery_risk`` is raised
when an order is late or an OTD-D checkpoint fails, both read from the same
delivery portions (``material_quantities.delivery_portions``) as orders,
stock and the improvement no-loss check. The lot metric (``tardy_count``,
``otd``: "Lotes no prazo") is reported but does not decide approval. An
operational audit that ran out of time is "por avaliar", never a pass.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.config.types import FactoryConfig
from backend.scheduler.jit_policy import (
    calendar_holidays,
    window_violation_details,
    workdays_between,
)
from backend.scheduler.material_quantities import delivery_portions
from backend.scheduler.operational_audit import build_operational_audit
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import (
    coverage_metrics,
    coverage_violations,
    demand_coverage_metrics,
    demand_coverage_violations,
    hard_gate_metrics,
    plan_anchor_violations,
    validate_plan,
)
from backend.telemetry import measured
from backend.types import EngineData

logger = logging.getLogger(__name__)
UTC = timezone.utc  # noqa: UP017 - Python 3.10 compatibility
HARD_GATE_KEYS = (
    "setup_crew_overlaps",
    "machine_overlaps",
    "tool_conflicts",
    "day_cap_violations",
    "blocked_machine_segments",
    "blocked_tool_segments",
    "operator_capacity_violations",
    "ghost_segments",
    "outside_shift_segments",
    "unknown_machine_segments",
    "unknown_tool_segments",
    "ineligible_machine_segments",
    "ineligible_tool_segments",
    "lot_production_minute_violations",
    "source_contract_violations",
    "run_setup_order_violations",
    "detached_setup_violations",
    "setup_production_discontinuity_violations",
    "missing_tool_change_setup_violations",
    "insufficient_tool_change_setup_violations",
    "plan_anchor_violations",
    "missing_lots",
    "missing_qty",
    "unexpected_lots",
    "overproduced_qty",
    "duplicate_twin_output_qty",
    "twin_output_mismatches",
    "source_missing_qty",
    "source_overproduced_qty",
)
MATERIAL_GATE_KEYS = ("setup_before_material_violations",)


@measured("validation")
def build_gate_report(
    segments: list[Segment],
    lots: list[Lot],
    score: dict[str, Any],
    data: EngineData | None,
    config: FactoryConfig | None,
    *,
    operational_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the public APS trust-loop report for a candidate plan."""

    violations = validate_plan(segments, data, config, lots=lots)
    violations.extend(plan_anchor_violations(segments, data, config))
    violations.extend(coverage_violations(segments, lots))
    source_coverage = (
        demand_coverage_metrics(data, lots, config)
        if data is not None and data.ops
        else {}
    )
    if data is not None and data.ops:
        violations.extend(demand_coverage_violations(data, lots, config))
    physical_metrics = hard_gate_metrics(violations)
    coverage = coverage_metrics(segments, lots)
    coverage.update(source_coverage)
    physical_metrics.update(
        {key: int(coverage[key]) for key in HARD_GATE_KEYS if key in coverage}
    )
    delivery_metrics = {
        "otd": float(score.get("otd", 0.0) or 0.0),
        "otd_d": float(score.get("otd_d", 0.0) or 0.0),
        "tardy_count": int(score.get("tardy_count", 0) or 0),
        "otd_d_failures": int(score.get("otd_d_failures", 0) or 0),
        "otd_d_checkpoints": int(score.get("otd_d_checkpoints", 0) or 0),
        "otd_d_cumulative_shortfall_qty": int(
            score.get("otd_d_cumulative_shortfall_qty", 0) or 0
        ),
        "otd_d_final_shortfall_qty": int(
            score.get("otd_d_final_shortfall_qty", 0) or 0
        ),
        "production_due_misses": int(score.get("production_due_misses", 0) or 0),
        "production_due_late_workdays": int(
            score.get("production_due_late_workdays", 0) or 0
        ),
        "subcontract_dispatch_total": int(
            score.get("subcontract_dispatch_total", 0) or 0
        ),
        "subcontract_dispatch_misses": int(
            score.get("subcontract_dispatch_misses", 0) or 0
        ),
        "subcontract_dispatch_late_workdays": int(
            score.get("subcontract_dispatch_late_workdays", 0) or 0
        ),
        "subcontract_dispatch_max_late_workdays": int(
            score.get("subcontract_dispatch_max_late_workdays", 0) or 0
        ),
        "subcontract_dispatch_otd": float(
            score.get("subcontract_dispatch_otd", 100.0) or 0.0
        ),
    }
    window_metrics = {
        "early_window_violations": int(score.get("early_window_violations", 0) or 0),
        "early_window_violation_days": int(score.get("early_window_violation_days", 0) or 0),
        "early_window_violation_workdays": int(
            score.get("early_window_violation_workdays", 0) or 0
        ),
        "start_anticipation_avg_workdays": float(
            score.get("start_anticipation_avg_workdays", 0.0) or 0.0
        ),
        "start_anticipation_max_workdays": int(
            score.get("start_anticipation_max_workdays", 0) or 0
        ),
        "latest_start_gap_avg_min": float(
            score.get("latest_start_gap_avg_min", 0.0) or 0.0
        ),
        "latest_start_gap_max_min": float(
            score.get("latest_start_gap_max_min", 0.0) or 0.0
        ),
    }
    audit_result = (
        operational_audit
        if operational_audit is not None
        else build_operational_audit(segments, lots, data, config)
        if data is not None
        else {
            "left_shift_opportunities": 0,
            "lower_priority_campaign_interruptions": 0,
            "priority_order_anomalies": 0,
            "avoidable_priority_order_anomalies": 0,
            "released_tool_priority_inversions": 0,
            "left_shift_detail": [],
            "protected_left_shift_detail": [],
            "campaign_interruption_detail": [],
            "priority_order_detail": [],
        }
    )
    operational_metrics = {
        key: int(audit_result[key])
        for key in (
            "left_shift_opportunities",
            "lower_priority_campaign_interruptions",
            "priority_order_anomalies",
            "avoidable_priority_order_anomalies",
            "released_tool_priority_inversions",
        )
    }
    # An audit that ran out of time is pending ("por avaliar"), never a pass.
    # Audits stored before the status field existed were complete.
    operational_audit_status = str(audit_result.get("status") or "evaluated")
    operational_audit_evaluated = operational_audit_status != "not_evaluated"
    service = _order_service(segments, lots, data) if data is not None else None
    order_metrics, late_order_detail = (
        _order_delivery(segments, lots, data, service) if data is not None else ({}, [])
    )
    metrics = {
        **physical_metrics,
        **delivery_metrics,
        **order_metrics,
        **window_metrics,
        **operational_metrics,
    }

    physical_gate_passed = all(int(metrics.get(key, 0)) == 0 for key in HARD_GATE_KEYS)
    operator_capacity_gate_passed = (
        int(metrics.get("operator_capacity_violations", 0)) == 0
    )
    coverage_gate_passed = all(
        int(coverage.get(key, 0)) == 0
        for key in (
            "missing_lots",
            "missing_qty",
            "unexpected_lots",
            "overproduced_qty",
            "duplicate_twin_output_qty",
            "twin_output_mismatches",
            "source_missing_qty",
            "source_overproduced_qty",
        )
    )
    # Deliveries are judged per order (AGENTS §1.2): pieces of a SKU are
    # fungible, so a lot finishing after its own delivery is no risk when
    # another lot's pieces serve that order in time. ``tardy_count``/``otd``
    # stay the lot metric ("Lotes no prazo") and never decide approval when
    # the order view is available.
    if order_metrics:
        delivery_gate_passed = (
            int(order_metrics["orders_late"]) == 0
            and delivery_metrics["otd_d"] >= 100.0
            and delivery_metrics["otd_d_failures"] == 0
        )
    else:
        delivery_gate_passed = (
            delivery_metrics["otd"] >= 100.0
            and delivery_metrics["otd_d"] >= 100.0
            and delivery_metrics["tardy_count"] == 0
            and delivery_metrics["otd_d_failures"] == 0
        )
    subcontract_dispatch_gate_passed = (
        delivery_metrics["subcontract_dispatch_misses"] == 0
    )
    jit_window_gate_passed = window_metrics["early_window_violations"] == 0
    material_gate_passed = all(
        int(metrics.get(key, 0)) == 0 for key in MATERIAL_GATE_KEYS
    )
    operational_sequence_clean = (
        operational_metrics["left_shift_opportunities"] == 0
        and operational_metrics["lower_priority_campaign_interruptions"] == 0
        and operational_metrics["avoidable_priority_order_anomalies"] == 0
        and operational_metrics["released_tool_priority_inversions"] == 0
    )
    operational_gate_passed = (
        operational_sequence_clean and operational_audit_evaluated
    )
    hard_gate_passed = physical_gate_passed

    approval_reasons: list[str] = []
    if not delivery_gate_passed:
        approval_reasons.append("delivery_risk")
    if not subcontract_dispatch_gate_passed:
        approval_reasons.append("subcontract_dispatch_risk")
    if not jit_window_gate_passed:
        approval_reasons.append("jit_window_blocked")
    if not material_gate_passed:
        approval_reasons.append("material_release_blocked")
    if not operator_capacity_gate_passed:
        approval_reasons.append("operator_capacity_shortage")
    if not operational_sequence_clean:
        approval_reasons.append("operational_sequence_review")
    if not operational_audit_evaluated:
        approval_reasons.append("operational_sequence_not_evaluated")

    if (
        not physical_gate_passed
        or not coverage_gate_passed
        or not jit_window_gate_passed
        or not material_gate_passed
    ):
        apply_decision = "blocked"
    elif approval_reasons:
        apply_decision = "approval_required"
    else:
        apply_decision = "auto_applicable"
    requires_approval = apply_decision == "approval_required"

    if apply_decision == "auto_applicable":
        status = "applicable"
    elif apply_decision == "approval_required":
        status = "best_effort"
    elif not jit_window_gate_passed or not material_gate_passed:
        status = "jit_window_blocked"
    else:
        status = "invalid_physics"

    setup_overlap_detail = [
        _setup_overlap_detail(v) for v in violations if v.get("kind") == "setup_crew_overlap"
    ]
    late_detail = _late_detail(segments, lots, data, config) if data is not None else []
    # Late-lot proposals only make sense when an order is actually late.
    proposal_late_detail = late_detail if not delivery_gate_passed else []
    jit_window_detail = (
        _with_calendar_dates(
            window_violation_details(
                segments,
                lots,
                calendar_holidays(
                    data,
                    min((segment.day_idx for segment in segments), default=0) - 7,
                    data.n_days + 7,
                ),
            ),
            data,
        )
        if data is not None
        else []
    )
    subcontract_dispatch_detail = (
        _subcontract_dispatch_detail(segments, lots, data)
        if data is not None
        else []
    )
    idle_capacity_late = (
        _idle_capacity_late(segments, lots, data, config, service)
        if data is not None
        else []
    )

    return {
        "status": status,
        "apply_decision": apply_decision,
        "requires_approval": requires_approval,
        "approval_reasons": approval_reasons,
        "hard_gate_passed": hard_gate_passed and material_gate_passed,
        "physical_gate_passed": physical_gate_passed,
        "operator_capacity_gate_passed": operator_capacity_gate_passed,
        "coverage_gate_passed": coverage_gate_passed,
        "delivery_gate_passed": delivery_gate_passed,
        "subcontract_dispatch_gate_passed": subcontract_dispatch_gate_passed,
        "jit_window_gate_passed": jit_window_gate_passed,
        # Robustness is informational only (computed after commit, outside
        # the plan); the field stays for schema compatibility.
        "robustness_gate_passed": None,
        "material_gate_passed": material_gate_passed,
        "operational_gate_passed": operational_gate_passed,
        "operational_audit_status": operational_audit_status,
        "metrics": metrics,
        "violations": violations,
        "late_detail": late_detail,
        "late_order_detail": late_order_detail,
        "jit_window_detail": jit_window_detail,
        "subcontract_dispatch_detail": subcontract_dispatch_detail,
        # Informational only: late deliveries with idle machine time before
        # their deadline (the plan can be improved); never decides approval.
        "idle_capacity_late": idle_capacity_late,
        "setup_overlap_detail": setup_overlap_detail,
        "operational_audit": audit_result,
        "proposals": _build_proposals(metrics, violations, proposal_late_detail),
    }


def gate_passed(report: dict[str, Any] | None) -> bool:
    """True only when a report can be applied without human approval."""

    return bool(
        report
        and report.get("apply_decision", "auto_applicable") == "auto_applicable"
        and report.get("physical_gate_passed")
    )


def physically_valid(report: dict[str, Any] | None) -> bool:
    """True when no approval could hide a physical/conservation conflict."""

    return bool(
        report
        and report.get("physical_gate_passed")
        and report.get("coverage_gate_passed")
        and report.get("apply_decision") != "blocked"
    )


def blocked_application_message(report: dict[str, Any] | None) -> str:
    """Explain why a plan candidate cannot be applied."""

    if not report:
        return "O candidato não pode substituir o plano atual."
    if not report.get("physical_gate_passed"):
        operator_conflicts = int(
            (report.get("metrics") or {}).get("operator_capacity_violations") or 0
        )
        if operator_conflicts:
            return (
                "O candidato excede a capacidade disponível de operadores em "
                f"{operator_conflicts} intervalo(s) e não pode substituir o plano."
            )
        return "O candidato tem conflitos físicos e não pode substituir o plano."
    if not report.get("coverage_gate_passed"):
        return "O candidato tem inconsistências de quantidades e não pode substituir o plano."

    reasons = set(report.get("approval_reasons") or [])
    metrics = report.get("metrics") or {}
    parts: list[str] = []
    if (
        report.get("status") == "jit_window_blocked"
        or report.get("jit_window_gate_passed") is False
        or report.get("material_gate_passed") is False
        or "jit_window_blocked" in reasons
        or "material_release_blocked" in reasons
    ):
        violations = int(metrics.get("early_window_violations") or 0)
        if violations > 0:
            parts.append(
                "O candidato foi bloqueado por "
                f"{violations} produção(ões) antecipada(s) fora da janela JIT "
                "dos 5 dias úteis antes da respetiva referência de material."
            )
        else:
            parts.append(
                "O candidato foi bloqueado por produções antecipadas fora da janela "
                "JIT dos 5 dias úteis antes da respetiva referência de material."
            )
    if report.get("operational_audit_status") == "not_evaluated":
        parts.append(
            "Há demasiadas inversões de prioridade para as verificar todas "
            "automaticamente; este ponto fica por avaliar e o plano precisa de "
            "decisão do planeador."
        )
    if not report.get("operational_gate_passed", True) and (
        "operational_sequence_review" in reasons
        or report.get("operational_audit_status") != "not_evaluated"
    ):
        opportunities = int(metrics.get("left_shift_opportunities") or 0)
        interruptions = int(
            metrics.get("lower_priority_campaign_interruptions") or 0
        )
        priority_inversions = int(
            metrics.get("avoidable_priority_order_anomalies") or 0
        )
        tool_priority_inversions = int(
            metrics.get("released_tool_priority_inversions") or 0
        )
        parts.append(
            "O candidato ainda contém "
            f"{opportunities} intervalo(s) produtivo(s) evitável(eis) e "
            f"{interruptions} interrupção(ões) de campanha e "
            f"{priority_inversions} inversão(ões) de prioridade evitável(eis) e "
            f"{tool_priority_inversions} inversão(ões) numa ferramenta partilhada."
        )
    if parts:
        return " ".join(parts)
    return "O candidato foi bloqueado pelas regras de aplicação do plano."


class ApplicationBlocked(ValueError):
    """The candidate breaks a physical or quantity rule: no approval can apply it."""

    code = "blocked"

    def __init__(self, message: str, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = report


class ApprovalRequired(ValueError):
    """The candidate is physically valid but needs the planner's explicit approval.

    Not a physical conflict: callers say that an approval is missing (or
    incomplete: ``incomplete`` when it came without reason or author), never
    that the plan has conflicts. The message is plain Portuguese; the reason
    codes stay machine-readable in ``approval_reasons``.
    """

    code = "approval_required"

    def __init__(
        self, message: str, report: dict[str, Any] | None = None, *, incomplete: bool = False,
    ) -> None:
        super().__init__(message)
        self.report = report
        self.approval_reasons = list((report or {}).get("approval_reasons") or [])
        self.incomplete = incomplete


# Plain Portuguese for each approval reason of ``build_gate_report``.
APPROVAL_REASON_TEXTS = {
    "delivery_risk": "há encomendas em risco de atraso",
    "subcontract_dispatch_risk": "há envios para subcontratação em risco",
    "jit_window_blocked": "há produção antes da libertação do material",
    "material_release_blocked": "há produção sem material libertado",
    "operator_capacity_shortage": "falta capacidade de operadores",
    "operational_sequence_review": (
        "a sequência das máquinas tem intervalos ou inversões de prioridade "
        "que o planeador deve rever"
    ),
    "operational_sequence_not_evaluated": (
        "a sequência das máquinas ficou por avaliar e precisa de decisão do planeador"
    ),
}


# A reason without its own text never shows its internal code.
UNKNOWN_APPROVAL_REASON_TEXT = "há uma exceção que o planeador deve rever"


def approval_reasons_text(reasons) -> str:
    """``há encomendas em risco de atraso; falta capacidade de operadores``."""

    texts = [
        APPROVAL_REASON_TEXTS.get(str(reason), UNKNOWN_APPROVAL_REASON_TEXT)
        for reason in reasons or []
    ]
    return "; ".join(dict.fromkeys(texts))


def approval_required_message(report: dict[str, Any] | None) -> str:
    """Why a physically valid plan waits for the planner, in plain Portuguese."""

    reasons = approval_reasons_text((report or {}).get("approval_reasons"))
    return (
        "O plano só pode ser aplicado com aprovação explícita do planeador"
        + (f": {reasons}." if reasons else ".")
    )


def application_refusal_detail(
    exc: BaseException, *, gate_report: bool = True,
) -> dict[str, Any] | None:
    """The 409 detail of a refusal of ``authorize_application``, else ``None``.

    Every route answers an apply refusal the same way: a stable ``code``
    (``approval_required`` or ``blocked``) and a plain Portuguese ``message``
    that never shows an internal reason code; the reason codes stay
    machine-readable in ``approval_reasons``. ``gate_report=False`` leaves
    the report out when the response already carries it.
    """

    if isinstance(exc, ApprovalRequired):
        detail: dict[str, Any] = {
            "code": exc.code,
            "message": str(exc),
            "requires_approval": True,
            "approval_reasons": list(exc.approval_reasons),
        }
        report = exc.report
    elif isinstance(exc, ApplicationBlocked):
        detail = {"code": exc.code, "message": str(exc), "requires_approval": False}
        report = exc.report
    else:
        return None
    if gate_report:
        detail["gate_report"] = report
    return detail


def authorize_application(
    report: dict[str, Any] | None,
    *,
    approve_exceptions: bool = False,
    approval_reason: str = "",
    approval_author: str = "",
) -> dict[str, Any] | None:
    """Validate the shared apply contract and return an approval audit record.

    Raises ``ApplicationBlocked`` for a physical or quantity conflict and
    ``ApprovalRequired`` when only the planner's approval is missing or
    incomplete (both are ``ValueError``).
    """

    if not physically_valid(report):
        raise ApplicationBlocked(blocked_application_message(report), report)
    if not report or not report.get("requires_approval"):
        return None
    if not approve_exceptions:
        raise ApprovalRequired(approval_required_message(report), report)
    if not approval_reason.strip() or not approval_author.strip():
        raise ApprovalRequired("A aprovação exige motivo e autor.", report, incomplete=True)
    return {
        "approved_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "author": approval_author.strip(),
        "reason": approval_reason.strip(),
        "approval_reasons": list(report.get("approval_reasons", [])),
    }


LATE_ORDER_DETAIL_LIMIT = 50


def _order_service(segments: list[Segment], lots: list[Lot], data: EngineData):
    # Local import: improvement must stay free to import gate helpers later.
    from backend.scheduler.improvement import order_service

    return order_service(segments, lots, data)


def _order_delivery(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    service=None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Order-level service, from the same allocation as the no-loss criterion.

    Every demand entry counts, including ones already past due. An order is
    late when it is not fully covered by its due day (``tardiness > 0``); one
    that is never fully covered has no ready day (``None`` instead of inf).
    ``orders_late`` (with OTD-D, read from the same delivery portions)
    decides ``delivery_risk``; ``score['otd']``/``tardy_count`` stay the lot
    metric and are informational.
    """

    if service is None:
        service = _order_service(segments, lots, data)
    produced_by_sku = _production_by_sku(segments)
    planned_machine = {op.sku: op.m for op in data.ops if getattr(op, "m", None)}
    late: list[dict[str, Any]] = []
    for (sku, client, due_day, order_qty, _np, _occ), item in service.items():
        if item.tardiness <= 0:
            continue
        never = item.tardiness == float("inf")
        late_days = None if never else int(item.tardiness)
        late.append(
            {
                "client": client,
                "sku": sku,
                "machine_id": _order_machine(
                    produced_by_sku.get(sku, []),
                    None if never else int(due_day) + late_days,
                    planned_machine.get(sku),
                ),
                "order_qty": int(order_qty),
                "covered_qty": int(item.covered_qty),
                "shortfall_qty": max(0, int(order_qty) - int(item.covered_qty)),
                "due_day": int(due_day),
                "ready_day": None if never else int(due_day) + late_days,
                "late_days": late_days,
            }
        )
    late.sort(
        key=lambda row: (
            row["late_days"] is not None,
            -(row["late_days"] or 0),
            row["due_day"],
            row["client"],
            row["sku"],
        )
    )
    total = len(service)
    on_time = total - len(late)
    metrics = {
        "orders_total": total,
        "orders_on_time": on_time,
        "orders_late": len(late),
        "order_otd": round(100.0 * on_time / total, 1) if total else 100.0,
    }
    return metrics, late[:LATE_ORDER_DETAIL_LIMIT]


def _production_by_sku(segments: list[Segment]) -> dict[str, list[tuple[int, str, int]]]:
    """(day, machine, qty) produced per SKU, twin outputs included."""

    produced: dict[str, list[tuple[int, str, int]]] = {}
    for segment in segments:
        outputs = segment.twin_outputs or [("", segment.sku, segment.qty)]
        for _op_id, sku, qty in outputs:
            if int(qty or 0) > 0 and sku:
                produced.setdefault(sku, []).append(
                    (int(segment.day_idx), str(segment.machine_id), int(qty))
                )
    return produced


def _order_machine(
    production: list[tuple[int, str, int]],
    ready_day: int | None,
    fallback: str | None,
) -> str | None:
    """Machine that produces the order: the one with most of the SKU's output.

    Counts production up to the order's ready day (all of it when the order is
    never covered). With no production at all, the SKU's planned machine.
    """

    by_machine: dict[str, int] = {}
    for day, machine, qty in production:
        if ready_day is None or day <= ready_day:
            by_machine[machine] = by_machine.get(machine, 0) + qty
    if not by_machine:
        return fallback
    return min(by_machine, key=lambda machine: (-by_machine[machine], machine))


def _with_calendar_dates(details: list[dict], data: EngineData) -> list[dict]:
    """Add stable ISO labels, including buffer days before the visible horizon."""

    workdays = list(data.workdays or [])
    first_date: date | None = None
    if workdays:
        try:
            first_date = date.fromisoformat(str(workdays[0])[:10])
        except ValueError:
            first_date = None

    def label(day_idx: int) -> str | None:
        if 0 <= day_idx < len(workdays):
            return str(workdays[day_idx])[:10]
        if first_date is not None:
            try:
                return (first_date + timedelta(days=day_idx)).isoformat()
            except OverflowError:
                return None
        return None

    result: list[dict] = []
    for item in details:
        enriched = dict(item)
        for day_field in (
            "delivery_day",
            "customer_delivery_day",
            "start_day",
            "earliest_allowed_start_day",
            "material_reference_day",
            "material_release_day",
            "production_due_day",
            "latest_subcontract_dispatch_day",
            "subcontract_dispatch_day",
            "completion_day",
        ):
            value = item.get(day_field)
            if value is None:
                continue
            date_field = day_field.removesuffix("_day") + "_date"
            enriched[date_field] = label(int(value))
        result.append(enriched)
    return result


def _subcontract_dispatch_detail(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
) -> list[dict[str, Any]]:
    """Subcontracted deliveries that leave after their planned dispatch.

    Each delivery is judged by when its own pieces are finished, whichever
    lot of the operation makes them (``delivery_portions``), never by the
    end of the economic lot. ``lot_id`` is the lot that completes it.
    """
    holidays = calendar_holidays(data, -60, data.n_days + 60)
    lots_by_id = {lot.id: lot for lot in lots}
    details: list[dict[str, Any]] = []
    for portion in delivery_portions(lots, segments, data):
        if not portion.is_demand or not portion.is_subcontracted:
            continue
        dispatch = portion.planned_dispatch_day
        completion = portion.factory_day
        if completion <= dispatch:
            continue
        source = portion.source
        lot_id = portion.completing_lot_id or source.lot_id
        lot = lots_by_id.get(lot_id) or lots_by_id[source.lot_id]
        details.append(
            {
                "lot_id": lot_id,
                "lot_ids": portion.lot_ids,
                "op_id": portion.op_id,
                "sku": portion.sku,
                "qty": portion.qty,
                "subcontract_company_id": source.output.get(
                    "subcontract_company_id",
                    lot.subcontract_company_id,
                ),
                "customer_delivery_day": portion.customer_delivery_day,
                "latest_subcontract_dispatch_day": portion.latest_subcontract_dispatch_day,
                "subcontract_dispatch_day": dispatch,
                "production_due_day": portion.production_due_day,
                "completion_day": completion,
                "customer_ready_day": portion.customer_ready_day,
                "late_workdays": workdays_between(
                    dispatch,
                    completion,
                    holidays,
                ),
            }
        )
    details.sort(
        key=lambda item: (
            -int(item["late_workdays"]),
            int(item["subcontract_dispatch_day"]),
            str(item["lot_id"]),
        )
    )
    return _with_calendar_dates(details, data)


def _idle_capacity_late(
    segments: list[Segment],
    lots: list[Lot],
    data: EngineData,
    config: FactoryConfig | None,
    service,
) -> list[dict[str, Any]]:
    """Late deliveries with idle capacity (``idle_capacity``), with dates.

    Read-only and informational: a failure is logged and gives no cases, so
    it can never stop a plan.
    """
    from backend.scheduler.idle_capacity import late_with_idle_capacity

    try:
        cases = late_with_idle_capacity(segments, lots, data, config, service=service)
    except Exception:  # informational check, never blocks a plan
        logger.exception("Idle-capacity check failed")
        return []
    return _with_calendar_dates(cases, data)


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

    late_deliveries = (
        int(metrics.get("orders_late", 0) or 0) > 0
        or int(metrics.get("otd_d_failures", 0) or 0) > 0
        if "orders_late" in metrics
        else int(metrics.get("tardy_count", 0) or 0) > 0
    )
    if metrics.get("day_cap_violations", 0) > 0 or late_deliveries:
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
                    "lead time externo nao recupera a entrega ao cliente",
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
