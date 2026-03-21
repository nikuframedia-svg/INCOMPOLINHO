"""Gen Decisions — port of analysis/gen-decisions.ts.

Generates UI-facing replan proposals from blocked operations.
Scores alternative machines using running capacity tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..constants import DAY_CAP
from ..overflow.overflow_helpers import cap_analysis
from ..types import Block, EMachine, EOp, ETool, MoveAction

DecisionSeverity = Literal["critical", "high", "medium", "low"]
DecisionKind = Literal["replan", "blocked"]


@dataclass
class ReplanProposal:
    id: str
    op_id: str
    type: str  # DecisionKind
    severity: str  # DecisionSeverity
    title: str
    desc: str
    reasoning: list[str] = field(default_factory=list)
    impact: dict[str, Any] | None = None
    action: dict[str, str] | None = None


def _fmt_num(n: int) -> str:
    return f"{n:,}"


def gen_decisions(
    ops: list[EOp],
    m_st: dict[str, str],
    t_st: dict[str, str],
    moves: list[MoveAction],
    blocks: list[Block],
    machines: list[EMachine],
    tool_map: dict[str, ETool],
    focus_ids: list[str],
    tools: list[ETool],
) -> list[ReplanProposal]:
    """Generate UI-facing replan proposals for blocked operations."""
    decs: list[ReplanProposal] = []
    cap = cap_analysis(blocks, machines)

    # Running capacity tracker
    run_cap: dict[str, list[dict[str, float]]] = {}
    for m_id, days in cap.items():
        run_cap[m_id] = [{"prod": d.get("prod", 0), "setup": d.get("setup", 0)} for d in days]

    # Collect blocked ops not yet moved
    move_op_ids = {mv.op_id for mv in moves}
    blk_ops: dict[str, Block] = {}
    for b in blocks:
        if b.type == "blocked" and b.op_id not in move_op_ids:
            if b.op_id not in blk_ops:
                blk_ops[b.op_id] = b

    # Sort by severity: stock-zero + high-backlog first
    def _sort_key(b: Block) -> float:
        tool = tool_map.get(b.tool_id)
        op = next((o for o in ops if o.id == b.op_id), None)
        sev = (10 if tool and tool.stk == 0 else 0) + (op.atr if op else 0)
        return -sev  # descending

    sorted_blk = sorted(blk_ops.values(), key=_sort_key)

    for b in sorted_blk:
        tool = tool_map.get(b.tool_id)
        op = next((o for o in ops if o.id == b.op_id), None)
        if not tool or not op:
            continue
        if tool.pH <= 0:
            continue

        total_pcs = sum(max(v, 0) for v in op.d) + max(op.atr, 0)
        total_h = total_pcs / tool.pH
        setup_min_val = tool.sH * 60
        has_stk = tool.stk > 0
        stk_days = tool.stk / (tool.pH * 16) if has_stk else 0

        sev_score = (
            (4 if op.atr > 20000 else 3 if op.atr > 5000 else 2 if op.atr > 0 else 0)
            + (3 if tool.stk == 0 and tool.lt > 0 else 0)
            + (2 if total_pcs > 20000 else 1 if total_pcs > 5000 else 0)
        )
        severity: str = (
            "critical" if sev_score >= 5
            else "high" if sev_score >= 3
            else "medium" if sev_score >= 1
            else "low"
        )
        reasoning: list[str] = []

        if b.reason == "tool_down":
            reasoning.append(f"Ferramenta {b.tool_id} AVARIADA.")
            if op.atr > 0:
                reasoning.append(f"Backlog: {_fmt_num(op.atr)} pcs.")
            decs.append(ReplanProposal(
                id=f"D_{b.op_id}_TF",
                op_id=b.op_id,
                type="blocked",
                severity="critical" if op.atr > 0 else "high",
                title=f"{b.tool_id} avariada",
                desc=f"{b.nm} ({b.sku})",
                reasoning=reasoning,
                impact={"pcsLost": total_pcs, "hrsLost": f"{total_h:.1f}"},
                action=None,
            ))
            continue

        reasoning.append(f"Máquina {b.orig_m} DOWN → {b.tool_id}/{b.sku} afetada.")
        reasoning.append(f"Volume: {_fmt_num(total_pcs)} pcs ({total_h:.1f}h).")

        if not b.has_alt:
            reasoning.append("Sem alternativa (ISOP).")
            if not has_stk:
                reasoning.append("STOCK ZERO → paragem.")
            else:
                reasoning.append(
                    f"Buffer: {_fmt_num(tool.stk)} pcs (≈{stk_days:.1f}d)."
                )
            decs.append(ReplanProposal(
                id=f"D_{b.op_id}_NA",
                op_id=b.op_id,
                type="blocked",
                severity="critical" if not has_stk else severity,
                title=f"{b.tool_id} sem alternativa",
                desc=b.nm,
                reasoning=reasoning,
                impact={
                    "pcsLost": total_pcs,
                    "hrsLost": f"{total_h:.1f}",
                    "stkDays": f"{stk_days:.1f}",
                },
                action=None,
            ))
            continue

        candidates: list[str] = []
        if b.alt_m and m_st.get(b.alt_m) != "down":
            candidates.append(b.alt_m)

        if not candidates:
            reasoning.append(f"Alt. {b.alt_m} TAMBÉM DOWN.")
            decs.append(ReplanProposal(
                id=f"D_{b.op_id}_AD",
                op_id=b.op_id,
                type="blocked",
                severity="critical",
                title=f"{b.tool_id}: ambas DOWN",
                desc=b.nm,
                reasoning=reasoning,
                impact={"pcsLost": total_pcs, "hrsLost": f"{total_h:.1f}"},
                action=None,
            ))
            continue

        # Score candidates using RUNNING capacity
        g_n_days = len(op.d) if op.d else 8
        scored: list[dict] = []
        for c_id in candidates:
            d_load = []
            for di in range(g_n_days):
                dc = (
                    run_cap[c_id][di]
                    if c_id in run_cap and di < len(run_cap[c_id])
                    else {"prod": 0, "setup": 0}
                )
                add_prod = (op.d[di] / tool.pH) * 60 if di < len(op.d) and op.d[di] > 0 else 0
                first_prod_day = next((i for i, v in enumerate(op.d) if v > 0), 0)
                add_setup = setup_min_val if di == first_prod_day or di == 0 else 0
                total = dc["prod"] + dc["setup"] + add_prod + add_setup
                d_load.append({
                    "day": di,
                    "current": dc["prod"] + dc["setup"],
                    "added": add_prod + add_setup,
                    "total": total,
                    "util": total / DAY_CAP if DAY_CAP > 0 else 0,
                })

            peak = max((dl["util"] for dl in d_load), default=0)
            over_days = [dl for dl in d_load if dl["util"] > 1.0]
            shared_mp = (
                tool.mp is not None
                and any(
                    t2.mp == tool.mp
                    and t2.id != tool.id
                    and (t2.m == c_id or t2.alt == c_id)
                    for t2 in tools
                )
            )
            score = (
                peak * 100
                + len(over_days) * 50
                + setup_min_val * 0.1
                - (30 if shared_mp else 0)
            )
            scored.append({
                "mId": c_id,
                "dLoad": d_load,
                "peak": peak,
                "overDays": over_days,
                "sharedMP": shared_mp,
                "score": score,
            })

        scored.sort(key=lambda s: s["score"])
        best = scored[0]

        # Update running capacity with proposed move load
        if best["mId"] in run_cap:
            for di in range(g_n_days):
                if di >= len(run_cap[best["mId"]]):
                    run_cap[best["mId"]].append({"prod": 0, "setup": 0})
                add_prod = (op.d[di] / tool.pH) * 60 if di < len(op.d) and op.d[di] > 0 else 0
                first_prod_day = next((i for i, v in enumerate(op.d) if v > 0), 0)
                add_setup = setup_min_val if di == first_prod_day or di == 0 else 0
                run_cap[best["mId"]][di]["prod"] += add_prod
                run_cap[best["mId"]][di]["setup"] += add_setup

        reasoning.append(f"Alt. disponível: {best['mId']}.")
        if best["overDays"]:
            prior_count = sum(
                1 for d in decs
                if d.action and d.action.get("toM") == best["mId"]
            )
            reasoning.append(
                f"{best['mId']} sobrecarga {len(best['overDays'])}d "
                f"(inclui {prior_count} ops já propostas)."
            )
        else:
            reasoning.append(
                f"Capacidade {best['mId']}: pico {best['peak'] * 100:.0f}% — OK."
            )
        reasoning.append(f"Setup: +{setup_min_val:.0f}min ({tool.sH}h).")
        if best["sharedMP"]:
            reasoning.append(f"MP {tool.mp} partilhada — agrupar.")
        if tool.op > 1:
            reasoning.append(f"Requer {tool.op} operadores.")
        if not has_stk and tool.lt > 0:
            reasoning.append("STOCK ZERO — OTD em risco.")
        reasoning.append(f"→ Mover {b.tool_id} → {best['mId']}.")

        decs.append(ReplanProposal(
            id=f"D_{b.op_id}_RP",
            op_id=b.op_id,
            type="replan",
            severity=severity,
            title=f"{b.tool_id} → {best['mId']}",
            desc=f"{b.nm} ({b.sku})",
            reasoning=reasoning,
            impact={
                "fromM": b.orig_m,
                "toM": best["mId"],
                "setupMin": setup_min_val,
                "pcs": total_pcs,
                "hrs": f"{total_h:.1f}",
                "destPeak": f"{best['peak'] * 100:.0f}",
                "overDays": len(best["overDays"]),
                "ops": tool.op,
                "stockRisk": not has_stk and tool.lt > 0,
                "atr": op.atr,
                "sharedMP": best["sharedMP"],
                "dLoad": best["dLoad"],
            },
            action={"opId": b.op_id, "toM": best["mId"]},
        ))

    # Lote económico warnings
    for b in blocks:
        if b.below_min_batch and b.type == "ok":
            tool = tool_map.get(b.tool_id)
            if not tool:
                continue
            decs.append(ReplanProposal(
                id=f"D_{b.op_id}_LT",
                op_id=b.op_id,
                type="replan",
                severity="low",
                title=f"{b.sku} abaixo lote econ.",
                desc=f"{_fmt_num(b.qty)} < {_fmt_num(tool.lt)} pcs",
                reasoning=[
                    f"Qty {_fmt_num(b.qty)} abaixo lote económico {_fmt_num(tool.lt)}.",
                    "Considerar agrupar com próxima encomenda.",
                ],
                impact={"qty": b.qty, "lotEconomic": tool.lt},
                action=None,
            ))

    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def _sort_decs(d: ReplanProposal) -> tuple:
        type_order = 0 if d.type == "replan" else 1
        return (type_order, sev_order.get(d.severity, 3))

    decs.sort(key=_sort_decs)
    return decs
