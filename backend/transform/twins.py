"""Twin detection — Spec 01 §5.

Three strategies in priority order:
1. From master_data.yaml (PREFERRED — source of truth)
2. From "Peça Gémea" column in ISOP
3. Auto-detect by same (tool_id, machine_id) with different SKUs
"""

from __future__ import annotations

import logging
from collections import defaultdict

from backend.types import EOp, TwinGroup

logger = logging.getLogger(__name__)


def identify_twins_from_master(
    ops: list[EOp], twins_config: dict[str, list[str]]
) -> list[TwinGroup]:
    """Strategy 1: Use 'twins' section from incompol.yaml as source of truth.

    twins_config format: { "BFP079": ["1064169X100", "1064170X100"], ... }
    """
    groups: list[TwinGroup] = []

    ops_by_sku_tool: dict[tuple[str, str], EOp] = {}
    for op in ops:
        ops_by_sku_tool[(op.sku, op.t)] = op

    for tool_id, sku_pair in twins_config.items():
        if len(sku_pair) != 2:
            logger.warning(
                "Twin config for %s has %d SKUs (expected 2), skipping",
                tool_id,
                len(sku_pair),
            )
            continue

        sku_1, sku_2 = sku_pair
        op_a = ops_by_sku_tool.get((sku_1, tool_id))
        op_b = ops_by_sku_tool.get((sku_2, tool_id))

        if op_a and op_b:
            groups.append(
                TwinGroup(
                    tool_id=tool_id,
                    machine_id=op_a.m,
                    op_id_1=op_a.id,
                    op_id_2=op_b.id,
                    sku_1=sku_1,
                    sku_2=sku_2,
                    eco_lot_1=op_a.eco_lot,
                    eco_lot_2=op_b.eco_lot,
                )
            )
        elif op_a or op_b:
            present = op_a or op_b
            missing = sku_2 if op_a else sku_1
            logger.warning(
                "Twin %s: found %s but missing %s in current ISOP",
                tool_id,
                present.sku,  # type: ignore[union-attr]
                missing,
            )

    return groups


def identify_twins_from_column_with_refs(
    ops: list[EOp], twin_refs: dict[str, str]
) -> list[TwinGroup]:
    """Strategy 2: Use twin_ref mapping {op_id: twin_sku}.

    Args:
        ops: list of merged EOps
        twin_refs: mapping from op.id to twin SKU reference
    """
    groups: list[TwinGroup] = []
    seen: set[str] = set()

    ops_by_sku_machine_tool: dict[tuple[str, str, str], EOp] = {}
    for op in ops:
        ops_by_sku_machine_tool[(op.sku, op.m, op.t)] = op

    for op in ops:
        if op.id in seen:
            continue

        ref_sku = twin_refs.get(op.id, "")
        if not ref_sku:
            continue

        twin = ops_by_sku_machine_tool.get((ref_sku, op.m, op.t))
        if twin and twin.id not in seen:
            groups.append(
                TwinGroup(
                    tool_id=op.t,
                    machine_id=op.m,
                    op_id_1=op.id,
                    op_id_2=twin.id,
                    sku_1=op.sku,
                    sku_2=twin.sku,
                    eco_lot_1=op.eco_lot,
                    eco_lot_2=twin.eco_lot,
                )
            )
            seen.add(op.id)
            seen.add(twin.id)

    return groups


def identify_twins_from_tool_machine(
    ops: list[EOp],
) -> tuple[list[TwinGroup], list[str]]:
    """Strategy 3: Auto-detect by same (tool, machine) with different SKUs.

    - 2 SKUs = twin pair ✓
    - 3+ SKUs = AMBIGUOUS → warning, no twin created
    - Same SKU repeated (multi-client) = NOT a twin (already merged)
    """
    tm: dict[tuple[str, str], list[EOp]] = defaultdict(list)
    for op in ops:
        tm[(op.t, op.m)].append(op)

    groups: list[TwinGroup] = []
    warnings: list[str] = []

    for (tool, machine), group_ops in tm.items():
        skus = list({op.sku for op in group_ops})

        if len(skus) == 2:
            a = next(o for o in group_ops if o.sku == skus[0])
            b = next(o for o in group_ops if o.sku == skus[1])
            groups.append(
                TwinGroup(
                    tool_id=tool,
                    machine_id=machine,
                    op_id_1=a.id,
                    op_id_2=b.id,
                    sku_1=a.sku,
                    sku_2=b.sku,
                    eco_lot_1=a.eco_lot,
                    eco_lot_2=b.eco_lot,
                )
            )
        elif len(skus) >= 3:
            msg = f"AMBIGUOUS: {tool} on {machine} has {len(skus)} SKUs: {skus}"
            warnings.append(msg)
            logger.warning(msg)

    return groups, warnings
