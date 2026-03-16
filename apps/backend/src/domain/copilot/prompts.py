"""System prompt builder for the copilot — dynamic context injection."""

from __future__ import annotations

from .state import copilot_state

SYSTEM_BASE = """Tu és o assistente de planeamento da fábrica Incompol (NIKUFRA.AI).
Ajudas o planeador a gerir o plano de produção: regras, alertas, carga de máquinas, prioridades.

REGRAS:
- Responde SEMPRE em português de Portugal.
- Sê conciso e directo.
- Usa os tools disponíveis para executar acções — não te limites a explicar.
- Quando alterares regras ou configuração, recalcula o plano automaticamente.
- Nunca inventes dados. Se não tens informação, diz que precisas do ISOP carregado.

FÁBRICA:
- 5 prensas: PRM019, PRM031, PRM039, PRM042, PRM043 (PRM020 fora de uso)
- 59 ferramentas, ~94 SKUs, 14 clientes
- Turnos: A (07:00-15:30), B (15:30-00:00), Noite (só emergência)
- 4 Constraints: SetupCrew, ToolTimeline, CalcoTimeline, OperatorPool
"""


def build_system_prompt() -> str:
    """Build system prompt with current factory state."""
    parts = [SYSTEM_BASE]

    if copilot_state.schedule is not None:
        gantt = copilot_state.schedule
        kpis = gantt.get("kpis", {})
        parts.append(f"""
ESTADO ACTUAL DO PLANO:
- Jobs: {kpis.get("total_jobs", "?")}
- Peças total: {kpis.get("total_qty", "?")}
- OTD: {kpis.get("otd_pct", "?")}%
- Solver: {gantt.get("solver_status", "?")}
- Tempo solver: {gantt.get("solve_time_seconds", "?")}s
""")

    alerts = copilot_state.alerts or []
    if alerts:
        top = alerts[:5]
        alert_lines = "\n".join(
            f"  - [{a.get('severity', '?').upper()}] {a.get('message', '?')}" for a in top
        )
        parts.append(f"TOP ALERTAS:\n{alert_lines}")

    rules = copilot_state.get_rules()
    if rules:
        rule_lines = "\n".join(
            f"  - {r.get('name', r.get('id', '?'))} (enabled={r.get('enabled', True)})"
            for r in rules
        )
        parts.append(f"REGRAS ACTIVAS:\n{rule_lines}")

    if copilot_state.isop_data is not None:
        isop = copilot_state.isop_data
        if isinstance(isop, dict):
            parts.append(f"""
DADOS ISOP:
- SKUs: {len(isop.get("skus", {}))}
- Encomendas: {isop.get("total_orders", "?")}
- Máquinas: {isop.get("machines", "?")}
- Ferramentas: {isop.get("total_tools", "?")}
""")

    return "\n".join(parts)
