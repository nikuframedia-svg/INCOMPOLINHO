"""Transform — PlanState → EngineData.

Port of transform/transform-plan-state.ts + twin-validator.ts.
"""

from __future__ import annotations

from typing import Any

from .constants import KNOWN_FOCUS
from .types import (
    ClientDemandEntry,
    EMachine,
    EngineData,
    EOp,
    ETool,
    TwinAnomalyEntry,
    TwinGroup,
    TwinValidationReport,
)
from .utils import infer_workdays_from_labels, mark_holidays

# ── NP → Demand conversion ──


def extract_stock_from_raw_np(daily: list[int | None]) -> int:
    """Extract initial stock = last positive NP before the first negative."""
    last_positive = 0
    for v in daily:
        if v is None:
            continue
        if v < 0:
            break
        last_positive = v
    return last_positive


def raw_np_to_order_demand(daily: list[int | None], stock: int = 0) -> list[int]:
    """Convert raw NP values to order-based demand.

    RULES (from CLAUDE.md):
    - Positive NP = stock available (not demand)
    - Negative NP = independent order, abs(value) = qty to produce
    - NOT cumulative — each negative cell is a separate order
    - Empty/null = no data
    """
    result: list[int] = []
    for v in daily:
        if v is None or v >= 0:
            result.append(0)
        else:
            result.append(abs(v))
    return result


def deltaize_cumulative_np(daily: list[int | None]) -> list[int]:
    """Convert cumulative NP to daily deltas (legacy mode)."""
    result: list[int] = []
    prev = 0
    for v in daily:
        curr = v if v is not None else 0
        delta = max(prev - curr, 0)
        result.append(delta)
        prev = curr
    return result


def raw_np_to_daily_demand(daily: list[int | None]) -> list[int]:
    """Raw NP with forward-fill (legacy 'daily' mode)."""
    return [max(-(v or 0), 0) for v in daily]


# ── Twin validation ──


def validate_twin_references(
    ops: list[dict[str, Any]],
) -> TwinValidationReport:
    """Validate twin (peça gémea) references.

    7 validation rules:
    1. No self-reference
    2. Counterpart exists
    3. Bidirectional link (A→B AND B→A)
    4. Machine match
    5. Tool match
    6. pH match
    7. Operator count match
    """
    anomalies: list[TwinAnomalyEntry] = []
    valid_groups: list[TwinGroup] = []
    by_code: dict[str, int] = {}
    processed_pairs: set[str] = set()

    # Build lookup by SKU → list of ops
    sku_map: dict[str, list[dict]] = {}
    for op in ops:
        sku = op.get("sku", "")
        sku_map.setdefault(sku, []).append(op)

    twin_refs = [op for op in ops if op.get("twin")]
    total_twin_refs = len(twin_refs)

    for op in twin_refs:
        op_id = op.get("id", "")
        sku = op.get("sku", "")
        twin_sku = op.get("twin", "")
        machine = op.get("m", "")
        tool = op.get("t", "")

        # R1: Self-reference
        if twin_sku == sku:
            _add_anomaly(
                anomalies,
                by_code,
                op_id,
                sku,
                twin_sku,
                "self_reference",
                "Twin references itself",
                machine,
                tool,
            )
            continue

        # R2: Counterpart exists
        counterparts = sku_map.get(twin_sku, [])
        if not counterparts:
            _add_anomaly(
                anomalies,
                by_code,
                op_id,
                sku,
                twin_sku,
                "counterpart_missing",
                f"Counterpart SKU {twin_sku} not found",
                machine,
                tool,
            )
            continue

        # Find matching counterpart on same machine
        counterpart = None
        for cp in counterparts:
            if cp.get("m") == machine:
                counterpart = cp
                break
        if counterpart is None:
            counterpart = counterparts[0]

        # R3: Bidirectional
        if counterpart.get("twin") != sku:
            _add_anomaly(
                anomalies,
                by_code,
                op_id,
                sku,
                twin_sku,
                "one_way_link",
                f"Counterpart {twin_sku} does not reference back to {sku}",
                machine,
                tool,
                counterpart.get("m"),
                counterpart.get("t"),
            )
            continue

        # Avoid double-processing
        pair_key = "|".join(sorted([op_id, counterpart.get("id", "")]))
        if pair_key in processed_pairs:
            continue
        processed_pairs.add(pair_key)

        # R4: Machine match
        if counterpart.get("m") != machine:
            _add_anomaly(
                anomalies,
                by_code,
                op_id,
                sku,
                twin_sku,
                "machine_mismatch",
                f"Machine mismatch: {machine} vs {counterpart.get('m')}",
                machine,
                tool,
                counterpart.get("m"),
                counterpart.get("t"),
            )
            continue

        # R5: Tool match
        if counterpart.get("t") != tool:
            _add_anomaly(
                anomalies,
                by_code,
                op_id,
                sku,
                twin_sku,
                "tool_mismatch",
                f"Tool mismatch: {tool} vs {counterpart.get('t')}",
                machine,
                tool,
                counterpart.get("m"),
                counterpart.get("t"),
            )
            continue

        # R6/R7: pH and operator match
        op_ph = op.get("pH", 0)
        cp_ph = counterpart.get("pH", 0)
        if op_ph != cp_ph:
            _add_anomaly(
                anomalies,
                by_code,
                op_id,
                sku,
                twin_sku,
                "rate_mismatch",
                f"pH mismatch: {op_ph} vs {cp_ph}",
                machine,
                tool,
            )
            continue

        op_people = op.get("op", 1)
        cp_people = counterpart.get("op", 1)
        if op_people != cp_people:
            _add_anomaly(
                anomalies,
                by_code,
                op_id,
                sku,
                twin_sku,
                "people_mismatch",
                f"Operators mismatch: {op_people} vs {cp_people}",
                machine,
                tool,
            )
            continue

        # Valid group
        valid_groups.append(
            TwinGroup(
                op_id1=op_id,
                op_id2=counterpart.get("id", ""),
                sku1=sku,
                sku2=twin_sku,
                machine=machine,
                tool=tool,
                pH=op_ph,
                operators=op_people,
                lot_economic_differs=op.get("lt", 0) != counterpart.get("lt", 0),
                lead_time_differs=op.get("ltDays") != counterpart.get("ltDays"),
            )
        )

    return TwinValidationReport(
        total_twin_refs=total_twin_refs,
        valid_groups=len(valid_groups),
        invalid_refs=len(anomalies),
        anomalies=anomalies,
        by_code=by_code,
        twin_groups=valid_groups,
    )


def _add_anomaly(
    anomalies: list,
    by_code: dict,
    op_id: str,
    sku: str,
    twin_sku: str,
    code: str,
    detail: str,
    machine: str,
    tool: str,
    cp_machine: str | None = None,
    cp_tool: str | None = None,
) -> None:
    anomalies.append(
        TwinAnomalyEntry(
            op_id=op_id,
            sku=sku,
            twin_sku=twin_sku,
            code=code,
            detail=detail,
            machine=machine,
            tool=tool,
            counterpart_machine=cp_machine,
            counterpart_tool=cp_tool,
        )
    )
    by_code[code] = by_code.get(code, 0) + 1


# ── Per-client demand extraction (before merge) ──


def _extract_client_demands(
    raw_operations: list[dict[str, Any]],
    n_days: int,
) -> dict[str, list[ClientDemandEntry]]:
    """Extract per-client demand BEFORE multi-client merge.

    Each raw operation has a single client. After merge, client info is lost
    (comma-separated string). This preserves the per-client breakdown for
    the stock projection page.
    """
    result: dict[str, list[ClientDemandEntry]] = {}

    for op in raw_operations:
        sku = op.get("sku", "")
        if not sku:
            continue
        cl = op.get("cl") or op.get("customer_code") or ""
        cl_nm = op.get("clNm") or op.get("customer_name") or cl
        raw_d = op.get("d", [])

        # Convert raw NP to demand: negative = demand (abs value), else 0
        demand: list[int] = []
        for i in range(n_days):
            v = raw_d[i] if i < len(raw_d) else None
            if v is not None and v < 0:
                demand.append(abs(v))
            else:
                demand.append(0)

        if sum(demand) == 0:
            continue

        if sku not in result:
            result[sku] = []
        result[sku].append(
            ClientDemandEntry(
                client_code=cl or "Desconhecido",
                client_name=cl_nm or cl or "Desconhecido",
                sku=sku,
                d=demand,
            )
        )

    return result


# ── Multi-client merge ──


def _merge_multi_client_ops(operations: list[dict[str, Any]], n_days: int) -> list[dict[str, Any]]:
    """Merge ISOP rows with same (SKU, machine, tool) but different clients.

    The factory stamps a part ONCE regardless of how many clients ordered it.
    Multiple ISOP rows for the same SKU+machine+tool should be merged:
    - Demand: sum day-by-day
    - Stock / twin / pH / op / setup: keep from first row
    - Clients: accumulate into comma-separated string
    """
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []

    for op in operations:
        sku = op.get("sku", "")
        m = op.get("m", "")
        t = op.get("t", "")
        key = (sku, m, t)

        if key not in merged:
            # First occurrence — clone the dict
            merged[key] = dict(op)
            # Ensure demand list is a fresh copy padded to n_days
            d = list(op.get("d", []))
            while len(d) < n_days:
                d.append(None)
            merged[key]["d"] = d
            order.append(key)
        else:
            # Subsequent occurrence — merge demand day-by-day
            existing = merged[key]
            new_d = op.get("d", [])
            ex_d = existing["d"]
            for i in range(min(len(new_d), n_days)):
                v = new_d[i]
                if v is not None:
                    if ex_d[i] is None:
                        ex_d[i] = v
                    else:
                        ex_d[i] = ex_d[i] + v
            # Accumulate client codes
            new_cl = op.get("cl") or op.get("customer_code") or ""
            old_cl = existing.get("cl") or ""
            if new_cl and new_cl not in old_cl:
                existing["cl"] = f"{old_cl},{new_cl}" if old_cl else new_cl
            # Keep max atraso
            existing["atr"] = max(existing.get("atr", 0), op.get("atr", 0))

    return [merged[k] for k in order]


# ── Main transform ──


def transform_plan_state(
    plan_state: dict[str, Any],
    demand_semantics: str = "raw_np",
    order_based: bool = True,
    pre_start_days: int = 0,
) -> EngineData:
    """Transform PlanState dict → EngineData.

    Port of transformPlanState() from TS.
    """
    raw_operations = plan_state.get("operations", [])
    dates = plan_state.get("dates", [])
    dnames = plan_state.get("dnames", [])
    n_days = len(dates)

    # Preserve per-client demand BEFORE merge (for stock projection page)
    client_demands = _extract_client_demands(raw_operations, n_days)

    # Merge multi-client rows: same (SKU, machine, tool) → single op
    operations = _merge_multi_client_ops(raw_operations, n_days)

    # Build machines
    machine_ids: set[str] = set()
    for op in operations:
        m = op.get("m", "")
        if m:
            machine_ids.add(m)
    machines = [
        EMachine(
            id=mid,
            area="Médias" if mid == "PRM042" else "Grandes",
            focus=mid in KNOWN_FOCUS,
        )
        for mid in sorted(machine_ids)
    ]

    # Build tools and ops
    tool_map: dict[str, ETool] = {}
    ops: list[EOp] = []

    for op_raw in operations:
        tool_id = op_raw.get("t", "")
        machine_id = op_raw.get("m", "")

        # Build tool if not seen
        if tool_id and tool_id not in tool_map:
            tool_map[tool_id] = ETool(
                id=tool_id,
                m=machine_id,
                alt=op_raw.get("alt") or "-",
                sH=op_raw.get("sH", 0.75),
                pH=op_raw.get("pH", 100),
                op=op_raw.get("op", 1),
                lt=op_raw.get("eco", 0),
                stk=0,  # Stock-A disabled per CLAUDE.md
                mp=op_raw.get("mp"),
                nm=op_raw.get("nm", ""),
                calco=op_raw.get("calco"),
                oee=op_raw.get("oee"),
            )

        # Transform demand based on semantics
        raw_d = op_raw.get("d", [])
        # Pad to n_days
        while len(raw_d) < n_days:
            raw_d.append(None)

        if demand_semantics == "raw_np":
            stock = extract_stock_from_raw_np(raw_d)
            demand = raw_np_to_order_demand(raw_d, stock)
        elif demand_semantics == "cumulative_np":
            stock = 0
            demand = deltaize_cumulative_np(raw_d)
        else:  # daily
            stock = 0
            demand = raw_np_to_daily_demand(raw_d)

        ops.append(
            EOp(
                id=op_raw.get("id", f"{tool_id}-{machine_id}"),
                t=tool_id,
                m=machine_id,
                sku=op_raw.get("sku", ""),
                nm=op_raw.get("nm", ""),
                atr=op_raw.get("atr", 0),
                d=demand,
                lt_days=op_raw.get("ltDays") or op_raw.get("lead_time_days"),
                cl=op_raw.get("cl") or op_raw.get("customer_code"),
                cl_nm=op_raw.get("clNm") or op_raw.get("customer_name"),
                pa=op_raw.get("pa") or op_raw.get("parent_sku"),
                stk=stock if demand_semantics == "raw_np" else op_raw.get("stk", 0),
                twin=op_raw.get("twin"),
            )
        )

    # Workdays
    workdays = infer_workdays_from_labels(dnames, n_days)
    workdays = mark_holidays(workdays, dates)

    # Twin validation (use merged ops for pH/op lookup)
    twin_report = validate_twin_references([_op_to_dict(op, operations) for op in ops])

    # Focus IDs
    focus_ids = [m.id for m in machines if m.focus]

    return EngineData(
        machines=machines,
        tools=list(tool_map.values()),
        ops=ops,
        dates=dates[:n_days],
        dnames=dnames[:n_days],
        tool_map=tool_map,
        focus_ids=focus_ids,
        workdays=workdays,
        n_days=n_days,
        m_st={m.id: "running" for m in machines},
        t_st={tid: "running" for tid in tool_map},
        twin_groups=twin_report.twin_groups,
        twin_validation_report=twin_report,
        order_based=order_based,
        pre_start_days=pre_start_days if pre_start_days > 0 else None,
        client_demands=client_demands,
    )


def _op_to_dict(eop: EOp, raw_ops: list[dict]) -> dict:
    """Convert EOp back to dict for twin validation (needs pH, op fields)."""
    # Find matching raw op for pH/op fields
    for raw in raw_ops:
        if raw.get("id") == eop.id or (raw.get("sku") == eop.sku and raw.get("m") == eop.m):
            return {
                "id": eop.id,
                "sku": eop.sku,
                "m": eop.m,
                "t": eop.t,
                "twin": eop.twin,
                "pH": raw.get("pH", 100),
                "op": raw.get("op", 1),
                "lt": raw.get("eco", 0),
                "ltDays": eop.lt_days,
            }
    return {
        "id": eop.id,
        "sku": eop.sku,
        "m": eop.m,
        "t": eop.t,
        "twin": eop.twin,
        "pH": 100,
        "op": 1,
    }
