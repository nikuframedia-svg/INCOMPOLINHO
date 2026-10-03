"""Transform orchestrator — Spec 01 §3.

Converts RawRows → EngineData via merge, twin detection, and enrichment.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.config.types import OUT_OF_SCOPE_MACHINES
from backend.parser.isop_reader import extract_stock_and_demand
from backend.transform.client_demands import extract_client_demands
from backend.transform.merge import merge_multi_client
from backend.transform.twins import (
    identify_twins_from_column_with_refs,
    identify_twins_from_master,
    identify_twins_from_tool_machine,
)
from backend.types import EngineData, EOp, MachineInfo, RawRow

logger = logging.getLogger(__name__)

# Fallback values when no master_data is provided
_DEFAULT_GROUP = "Grandes"
_DEFAULT_DAY_CAPACITY = 1020


def transform(
    rows: list[RawRow],
    workdays: list[str],
    has_twin_col: bool,
    master_data: dict[str, Any] | None,
) -> EngineData:
    """Transform raw ISOP rows into EngineData.

    Args:
        rows: raw rows from isop_reader
        workdays: list of date strings
        has_twin_col: whether ISOP has "Peça Gémea" column
        master_data: contents of incompol.yaml (or None)
    """
    excluded = [row for row in rows if row.machine_id.upper() in OUT_OF_SCOPE_MACHINES]
    if excluded:
        raise ValueError(
            "PRM020 fora do âmbito da análise: "
            f"{len(excluded)} linha(s) do ISOP, incluindo {excluded[0].sku}. "
            "Corrija a máquina no ISOP; a procura não foi descartada."
        )
    # 1. Extract client demands BEFORE merge (for expedição view)
    client_demands = extract_client_demands(rows, workdays)

    # 2. Convert raw rows to EOps (with master data enrichment)
    twin_refs: dict[str, str] = {}  # op_id → twin_sku (from column)
    ops: list[EOp] = []
    for r in rows:
        eop = _raw_to_eop(r, master_data)
        ops.append(eop)
        if has_twin_col and r.twin_ref:
            twin_refs[eop.id] = r.twin_ref

    # 3. Merge multi-client (same sku+machine+tool)
    ops = merge_multi_client(ops)
    routes_by_sku: dict[str, list[EOp]] = {}
    for op in ops:
        routes_by_sku.setdefault(op.sku, []).append(op)
    ambiguous = {
        sku: routes
        for sku, routes in routes_by_sku.items()
        if len(routes) > 1
    }
    if ambiguous:
        details = "; ".join(
            f"{sku}: " + ", ".join(f"{op.m}/{op.t}" for op in routes)
            for sku, routes in sorted(ambiguous.items())
        )
        raise ValueError(
            "Cada SKU deve ter uma única rota de produção; rotas ambíguas: "
            + details
        )

    input_warnings = [warning for row in rows for warning in row.warnings]
    # 4. Twin detection — priority: YAML > column > tool+machine
    if master_data and "twins" in master_data:
        twin_groups = identify_twins_from_master(ops, master_data["twins"])
        logger.info("Twins from master_data: %d groups", len(twin_groups))
    elif has_twin_col and twin_refs:
        twin_groups = identify_twins_from_column_with_refs(ops, twin_refs)
        logger.info("Twins from ISOP column: %d groups", len(twin_groups))
    else:
        twin_groups, warnings = identify_twins_from_tool_machine(ops)
        input_warnings.extend(warnings)
        logger.info("Twins auto-detected: %d groups, %d warnings", len(twin_groups), len(warnings))

    # 5. Build machine list
    machines = _build_machines(ops, master_data)

    # 6. Holidays — convert date strings to workday indices
    holidays = _resolve_holidays(workdays, master_data)
    explicit_holidays = _resolve_explicit_holidays(workdays, master_data)

    return EngineData(
        ops=ops,
        machines=machines,
        twin_groups=twin_groups,
        client_demands=client_demands,
        workdays=workdays,
        n_days=len(workdays),
        holidays=holidays,
        calendar_base_holidays=list(holidays),
        calendar_explicit_holidays=explicit_holidays,
        input_warnings=input_warnings,
    )


def _raw_to_eop(raw: RawRow, master_data: dict[str, Any] | None) -> EOp:
    """Convert a single RawRow to EOp with master data enrichment."""
    if raw.pieces_per_hour <= 0 or raw.operators < 1:
        raise ValueError(f"{raw.sku}: cadencia e numero de operadores devem ser positivos.")
    stk, demand = extract_stock_and_demand(raw.np_values)

    # Setup hours: from YAML (not ISOP)
    setup_map: dict[str, float] = {}
    if master_data:
        setup_map = master_data.get("setup_hours", {})
    sH = setup_map.get(raw.tool_id, setup_map.get("_default", 0.5))

    # Alt machine: from YAML
    alt_map: dict[str, dict[str, str]] = {}
    if master_data:
        alt_map = master_data.get("alt_machines", {})
    alt_info = alt_map.get(raw.tool_id)
    alt = alt_info["alt"] if alt_info else None
    if alt in OUT_OF_SCOPE_MACHINES:
        raise ValueError(
            f"{raw.tool_id}: PRM020 fora do âmbito como máquina alternativa."
        )

    # OEE default
    oee = 0.66
    if master_data:
        oee = master_data.get("factory", {}).get("oee_default", 0.66)

    return EOp(
        id=f"{raw.tool_id}_{raw.machine_id}_{raw.sku}",
        sku=raw.sku,
        client=raw.client_name,
        designation=raw.designation,
        m=raw.machine_id,
        t=raw.tool_id,
        pH=raw.pieces_per_hour,
        sH=sH,
        operators=raw.operators,
        eco_lot=raw.eco_lot,
        alt=alt,
        stk=stk,
        backlog=raw.backlog,
        d=demand,
        oee=oee,
        wip=raw.wip,
    )


def _resolve_holidays(workdays: list[str], master_data: dict[str, Any] | None) -> list[int]:
    """Convert holiday date strings from YAML to workday indices.

    Also auto-detects weekends (Saturday=5, Sunday=6) as holidays.
    """
    from datetime import date as dt_date

    indices_set: set[int] = set()

    # Auto-detect weekends
    for i, d in enumerate(workdays):
        try:
            if dt_date.fromisoformat(d).weekday() >= 5:
                indices_set.add(i)
        except ValueError:
            pass

    indices_set.update(_resolve_explicit_holidays(workdays, master_data))

    return sorted(indices_set)


def _resolve_explicit_holidays(
    workdays: list[str], master_data: dict[str, Any] | None
) -> list[int]:
    """Convert only explicit master-data holidays to workday indices."""
    if not master_data:
        return []
    workday_set = {d: i for i, d in enumerate(workdays)}
    return sorted(
        {
            workday_set[str(holiday)]
            for holiday in master_data.get("holidays", [])
            if str(holiday) in workday_set
        }
    )


def _build_machines(ops: list[EOp], master_data: dict[str, Any] | None) -> list[MachineInfo]:
    """Build machine list from ops + YAML machine config."""
    machine_config: dict[str, dict[str, Any]] = {}
    if master_data:
        machine_config = master_data.get("machines", {})

    seen: set[str] = set()
    machines: list[MachineInfo] = []

    for op in ops:
        if op.m not in seen:
            seen.add(op.m)
            cfg = machine_config.get(op.m, {})
            group = cfg.get("group", _DEFAULT_GROUP)
            capacity = cfg.get("day_capacity_min")
            if capacity is None:
                capacity = _DEFAULT_DAY_CAPACITY
            machines.append(MachineInfo(id=op.m, group=group, day_capacity=capacity))

    return machines
