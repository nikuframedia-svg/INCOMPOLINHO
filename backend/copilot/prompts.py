"""System prompt builder — Spec 10.

Builds the Portuguese system prompt for the LLM, including current state.
"""

from __future__ import annotations

from backend.copilot.state import CopilotState

SYSTEM_BASE = """\
Tu és o assistente de planeamento de produção da Incompol (PP1).
O João, o planeador, fala-te em português. Tu respondes em português.

REGRAS:
1. NUNCA inventar dados. Usa SEMPRE as tools para consultar ou calcular.
2. NUNCA fazer cálculos de produção tu mesmo. As tools chamam o kernel real.
3. Quando o João pede para ver algo, usa a tool de consulta/visualização.
4. Quando pede para mudar algo, usa a tool de acção/master data.
5. Quando pede para simular, usa simular_cenario ou simular_overtime.
6. Explica as decisões do scheduler usando explicar_decisao (precisa de recalcular_plano primeiro).
7. Se não tiveres dados carregados, diz ao João para carregar o ISOP primeiro.

FERRAMENTAS DISPONÍVEIS:
- Consulta: ver_producao_dia, ver_carga_maquinas, ver_alertas, ver_score, ver_config, explicar_referencia, explicar_decisao, explicar_logica, ver_encomendas, ver_historico, ver_stress, e_se
- Acção: recalcular_plano, mover_referencia, adicionar_regra, remover_regra, alterar_config, simular_cenario, simular_overtime, check_ctp, simular_avaria, monte_carlo
- Master Data: adicionar_maquina, editar_maquina, adicionar_ferramenta, editar_ferramenta, adicionar_twin, remover_twin, adicionar_feriado, remover_feriado, editar_turno, adicionar_turno
- Visualização: visualizar_stock, visualizar_carga_temporal, visualizar_risco_heatmap, visualizar_encomendas, visualizar_expedicao, visualizar_gantt, visualizar_comparacao, visualizar_learning, visualizar_atrasos, visualizar_workforce, visualizar_cobertura, visualizar_propostas
"""


def build_system_prompt(state: CopilotState) -> str:
    """Build system prompt with current state context."""
    parts = [SYSTEM_BASE]

    if state.engine_data is not None:
        parts.append(f"\nESTADO ACTUAL:")
        parts.append(f"- {len(state.engine_data.ops)} operações carregadas")
        parts.append(f"- {len(state.segments)} segmentos planeados")
        parts.append(f"- {len(state.lots)} lots")

        if state.score:
            s = state.score
            parts.append(f"- OTD: {s.get('otd', '?')}%")
            parts.append(f"- OTD-D: {s.get('otd_d', '?')}%")
            parts.append(f"- Tardy: {s.get('tardy_count', '?')}")
            parts.append(f"- Setups: {s.get('setups', '?')}")
            parts.append(f"- Earliness média: {s.get('earliness_avg_days', '?')}d")

        if state.trust_index:
            t = state.trust_index
            t_score = getattr(t, 'score', None)
            t_gate = getattr(t, 'gate', None)
            if t_score is not None:
                parts.append(f"- Trust Index: {t_score}/100 (gate: {t_gate})")
                if t_score < 70:
                    parts.append("  ⚠ DADOS COM PROBLEMAS — confiança baixa. Alerta o João.")

        if state.journal_entries:
            n_warns = len([e for e in state.journal_entries if e.get("severity") in ("warn", "error")])
            if n_warns:
                parts.append(f"- {n_warns} journal warnings")
            parts.append(f"- {len(state.journal_entries)} journal entries")
        elif state.warnings:
            parts.append(f"- {len(state.warnings)} warnings")
    else:
        parts.append("\nSEM DADOS CARREGADOS. Pede ao João para carregar o ISOP.")

    if state.rules:
        parts.append(f"\nREGRAS ACTIVAS ({len(state.rules)}):")
        for r in state.rules:
            parts.append(f"  - [{r.get('tipo', '?')}] {r.get('descricao', '?')}")

    return "\n".join(parts)
