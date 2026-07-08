"""Effective planning configuration applied before scheduling.

The ISOP remains the source of truth for imported master data. User changes
live in FactoryConfig and are projected onto EngineData immediately before
lot sizing so every setting changes the real scheduler input.
"""

from __future__ import annotations

from typing import Any

from backend.config.types import FactoryConfig
from backend.types import EngineData

SKU_RULE_FIELDS = {
    "eco_lot",
    "start_buffer_days",
    "finish_buffer_days",
    "min_campaign_qty",
    "min_campaign_prod_min",
    "max_group_gap_days",
}


def _blank(value: Any) -> bool:
    return value is None or value == ""


def _non_negative_int(value: Any, field: str, sku: str) -> int | None:
    if _blank(value):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{sku}: {field} inválido: {value!r}") from exc
    if parsed < 0:
        raise ValueError(f"{sku}: {field} deve ser >= 0")
    return parsed


def _non_negative_float(value: Any, field: str, sku: str) -> float | None:
    if _blank(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{sku}: {field} inválido: {value!r}") from exc
    if parsed < 0:
        raise ValueError(f"{sku}: {field} deve ser >= 0")
    return parsed


def normalize_sku_planning_rule(sku: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return a validated, compact SKU planning rule."""
    raw = raw or {}
    rule: dict[str, Any] = {}

    if "eco_lot_override" in raw and "eco_lot" not in raw:
        raw = {**raw, "eco_lot": raw.get("eco_lot_override")}

    for field in ("eco_lot", "start_buffer_days", "finish_buffer_days", "min_campaign_qty"):
        parsed = _non_negative_int(raw.get(field), field, sku)
        if parsed is not None:
            rule[field] = parsed

    for field in ("min_campaign_prod_min",):
        parsed_f = _non_negative_float(raw.get(field), field, sku)
        if parsed_f is not None:
            rule[field] = parsed_f

    parsed_gap = _non_negative_int(raw.get("max_group_gap_days"), "max_group_gap_days", sku)
    if parsed_gap is not None:
        rule["max_group_gap_days"] = parsed_gap

    return rule


def normalize_subcontract_rule(sku: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return a validated subcontract rule for one SKU."""
    raw = raw or {}
    enabled = raw.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in {"0", "false", "no", "nao", "não", "off"}

    rule: dict[str, Any] = {"enabled": bool(enabled)}
    company_id = raw.get("company_id") or raw.get("company") or raw.get("empresa")
    if not _blank(company_id):
        rule["company_id"] = str(company_id)

    for field in ("lead_time_days", "external_lead_time_days"):
        parsed = _non_negative_int(raw.get(field), field, sku)
        if parsed is not None:
            rule["lead_time_days"] = parsed
            break

    for field in ("buffer_days", "internal_buffer_days"):
        parsed = _non_negative_int(raw.get(field), field, sku)
        if parsed is not None:
            rule["buffer_days"] = parsed
            break

    return rule


def normalize_subcontract_company(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate one subcontract company entry."""
    company_id = raw.get("id") or raw.get("company_id") or raw.get("name") or raw.get("nome")
    if _blank(company_id):
        raise ValueError("Empresa de subcontratação sem id/nome")
    cid = str(company_id)
    lead = _non_negative_int(
        raw.get("lead_time_days", raw.get("default_lead_time_days", 0)),
        "lead_time_days",
        cid,
    )
    return {
        "id": cid,
        "name": str(raw.get("name") or raw.get("nome") or cid),
        "lead_time_days": lead or 0,
    }


def apply_effective_planning_config(
    engine_data: EngineData,
    config: FactoryConfig | None,
) -> EngineData:
    """Apply user planning rules onto EngineData in-place and return it."""
    if config is None:
        return engine_data

    companies: dict[str, dict[str, Any]] = {}
    for raw_company in config.subcontract_companies:
        if isinstance(raw_company, dict):
            company = normalize_subcontract_company(raw_company)
            companies[company["id"]] = company

    legacy_subcontract = set(config.subcontract_skus or [])

    for op in engine_data.ops:
        isop_eco = op.eco_lot_isop if op.eco_lot_isop is not None else op.eco_lot
        op.eco_lot_isop = int(isop_eco or 0)

        rule = normalize_sku_planning_rule(
            op.sku,
            config.sku_planning_rules.get(op.sku) or {},
        )
        op.eco_lot = int(rule.get("eco_lot", op.eco_lot_isop))
        op.eco_lot_effective = op.eco_lot
        op.start_buffer_days = int(rule.get("start_buffer_days", 0))
        op.finish_buffer_days = int(rule.get("finish_buffer_days", 0))
        op.min_campaign_qty = rule.get("min_campaign_qty")
        op.min_campaign_prod_min = rule.get("min_campaign_prod_min")
        op.max_group_gap_days = rule.get("max_group_gap_days")

        sub_raw = config.sku_subcontracts.get(op.sku)
        if sub_raw is None and op.sku in legacy_subcontract:
            sub_raw = {"enabled": True}
        sub = normalize_subcontract_rule(op.sku, sub_raw) if sub_raw is not None else {}

        if sub.get("enabled"):
            company_id = sub.get("company_id")
            company = companies.get(company_id or "", {})
            lead = sub.get("lead_time_days")
            if lead is None:
                lead = company.get("lead_time_days", 0)
            op.subcontract_company_id = company_id
            op.subcontract_lead_time_days = int(lead or 0)
            op.subcontract_buffer_days = int(sub.get("buffer_days", 0))
        else:
            op.subcontract_company_id = None
            op.subcontract_lead_time_days = 0
            op.subcontract_buffer_days = 0

    return engine_data


def effective_internal_deadline_for_op(op: Any, delivery_day: int) -> int:
    """Return the scheduler deadline after SKU buffers and subcontract lead time."""
    buffer_days = (
        getattr(op, "finish_buffer_days", 0)
        + getattr(op, "subcontract_lead_time_days", 0)
        + getattr(op, "subcontract_buffer_days", 0)
    )
    return max(0, delivery_day - int(buffer_days or 0))


def clean_sku_planning_config(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate a full sku_planning_rules mapping."""
    cleaned: dict[str, dict[str, Any]] = {}
    for sku, rule in (raw or {}).items():
        normalized = normalize_sku_planning_rule(str(sku), rule if isinstance(rule, dict) else {})
        if normalized:
            cleaned[str(sku)] = normalized
    return cleaned


def clean_sku_subcontracts(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate a full sku_subcontracts mapping."""
    cleaned: dict[str, dict[str, Any]] = {}
    for sku, rule in (raw or {}).items():
        if not isinstance(rule, dict):
            continue
        normalized = normalize_subcontract_rule(str(sku), rule)
        if normalized.get("enabled") or len(normalized) > 1:
            cleaned[str(sku)] = normalized
    return cleaned
