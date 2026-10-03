"""Tool schemas for LLM function calling — Spec 10.

40 tools in OpenAI function calling format.
Organized: QUERY (10) + ACTION (8) + MASTER (10) + VIZ (12).
"""

from __future__ import annotations


def _fn(name: str, description: str, parameters: dict) -> dict:
    """Helper to build a tool schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": parameters.get("properties", {}),
                "required": parameters.get("required", []),
            },
        },
    }


# ─── QUERY TOOLS (10) ────────────────────────────────────────────────────

QUERY_TOOLS = [
    _fn(
        "ver_producao_dia",
        "Ver produção planeada para um dia específico.",
        {
            "properties": {
                "dia": {"type": "integer", "description": "Índice do dia (0 = primeiro dia útil)."},
            },
            "required": ["dia"],
        },
    ),
    _fn(
        "ver_carga_maquinas",
        "Ver carga (%) de todas as máquinas por dia.",
        {
            "properties": {
                "dia_inicio": {"type": "integer", "description": "Dia início (default 0)."},
                "dia_fim": {"type": "integer", "description": "Dia fim (default todos)."},
            },
        },
    ),
    _fn(
        "ver_alertas",
        "Ver alertas de risco, tardiness e operadores.",
        {
            "properties": {},
        },
    ),
    _fn(
        "ver_score",
        "Ver score actual do plano (OTD, setups, earliness, etc.).",
        {
            "properties": {},
        },
    ),
    _fn(
        "ver_config",
        "Ver configuração actual da fábrica (turnos, máquinas, etc.).",
        {
            "properties": {},
        },
    ),
    _fn(
        "explicar_referencia",
        "Explicar uma referência/SKU: máquina, ferramenta, demand, lots.",
        {
            "properties": {
                "sku": {"type": "string", "description": "SKU da peça."},
            },
            "required": ["sku"],
        },
    ),
    _fn(
        "explicar_decisao",
        "Explicar porque o scheduler tomou uma decisão para um SKU/tool.",
        {
            "properties": {
                "sku": {"type": "string", "description": "SKU da peça (busca tool_id associado)."},
            },
            "required": ["sku"],
        },
    ),
    _fn(
        "explicar_logica",
        "Explicar um conceito do scheduler (JIT, campaigns, eco lot, etc.).",
        {
            "properties": {
                "conceito": {
                    "type": "string",
                    "description": "Conceito a explicar.",
                    "enum": [
                        "jit",
                        "campaign",
                        "eco_lot",
                        "twins",
                        "scoring",
                        "oee",
                        "interleave",
                        "2opt",
                        "lot_sizing",
                        "tool_grouping",
                    ],
                },
            },
            "required": ["conceito"],
        },
    ),
    _fn(
        "ver_encomendas",
        "Ver estado das encomendas por cliente.",
        {
            "properties": {
                "cliente": {"type": "string", "description": "Nome do cliente (opcional, filtra)."},
            },
        },
    ),
    _fn(
        "ver_historico",
        "Ver histórico de estudos de optimização (Optuna).",
        {
            "properties": {
                "limite": {
                    "type": "integer",
                    "description": "Número máximo de resultados (default 20).",
                },
            },
        },
    ),
    _fn(
        "ver_stress",
        "Ver mapa de stress/fragilidade e recomendações.",
        {
            "properties": {},
        },
    ),
    _fn(
        "e_se",
        "Cenário counterfactual: 'E se a ferramenta X fosse para a máquina Y?'",
        {
            "properties": {
                "tipo": {
                    "type": "string",
                    "enum": ["force_machine", "remove_jit"],
                    "description": "Tipo de pergunta counterfactual.",
                },
                "params": {
                    "type": "object",
                    "description": (
                        'Parâmetros (ex: {"tool_id": "BFP079", "machine_id": "PRM039"}).'
                    ),
                },
            },
            "required": ["tipo", "params"],
        },
    ),
]

# ─── ACTION TOOLS (10) ───────────────────────────────────────────────────

ACTION_TOOLS = [
    _fn(
        "recalcular_plano",
        "Recalcular o plano de produção com os dados actuais.",
        {
            "properties": {
                "modo": {
                    "type": "string",
                    "enum": ["quick", "normal", "smart"],
                    "description": (
                        "Modo: quick (rápido), normal (JIT/VNS + CP-SAT local), "
                        "smart (Bayesian + aprendizagem). Default: quick."
                    ),
                },
            },
        },
    ),
    _fn(
        "mover_referencia",
        "Mover uma referência/SKU para outra máquina.",
        {
            "properties": {
                "sku": {"type": "string", "description": "SKU da peça a mover."},
                "maquina_destino": {
                    "type": "string",
                    "description": "ID da máquina destino (ex: PRM039).",
                },
            },
            "required": ["sku", "maquina_destino"],
        },
    ),
    _fn(
        "adicionar_regra",
        "Adicionar uma regra/constraint ao planeamento.",
        {
            "properties": {
                "descricao": {
                    "type": "string",
                    "description": "Descrição da regra em texto livre.",
                },
                "tipo": {
                    "type": "string",
                    "description": "Tipo de regra.",
                    "enum": ["prioridade", "restricao", "preferencia"],
                },
            },
            "required": ["descricao", "tipo"],
        },
    ),
    _fn(
        "remover_regra",
        "Remover uma regra existente.",
        {
            "properties": {
                "regra_id": {"type": "string", "description": "ID da regra a remover."},
            },
            "required": ["regra_id"],
        },
    ),
    _fn(
        "alterar_config",
        "Alterar um parâmetro de configuração do scheduler.",
        {
            "properties": {
                "chave": {
                    "type": "string",
                    "description": "Nome do parâmetro.",
                    "enum": [
                        "oee_default",
                        "jit_buffer_pct",
                        "jit_threshold",
                        "max_run_days",
                        "max_edd_gap",
                        "edd_swap_tolerance",
                        "campaign_window",
                        "urgency_threshold",
                        "interleave_enabled",
                        "weight_earliness",
                        "weight_setups",
                        "weight_balance",
                    ],
                },
                "valor": {"description": "Novo valor (número, boolean, ou string)."},
            },
            "required": ["chave", "valor"],
        },
    ),
    _fn(
        "simular_cenario",
        "Simular um cenário what-if sem alterar o plano actual.",
        {
            "properties": {
                "mutacoes": {
                    "type": "array",
                    "description": "Lista de mutações a aplicar.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "machine_down",
                                    "tool_down",
                                    "oee_change",
                                    "rush_order",
                                    "demand_change",
                                    "cancel_order",
                                    "third_shift",
                                    "overtime",
                                    "add_holiday",
                                    "remove_holiday",
                                    "force_machine",
                                    "change_eco_lot",
                                ],
                            },
                            "params": {"type": "object"},
                        },
                        "required": ["type", "params"],
                    },
                },
            },
            "required": ["mutacoes"],
        },
    ),
    _fn(
        "simular_overtime",
        "Simular horas extra numa máquina.",
        {
            "properties": {
                "maquina": {"type": "string", "description": "ID da máquina (ex: PRM039)."},
                "minutos_extra": {"type": "integer", "description": "Minutos extra por dia."},
            },
            "required": ["maquina", "minutos_extra"],
        },
    ),
    _fn(
        "check_ctp",
        "Verificar se é possível produzir uma quantidade até um deadline (CTP).",
        {
            "properties": {
                "sku": {"type": "string", "description": "SKU da peça."},
                "quantidade": {"type": "integer", "description": "Quantidade a produzir."},
                "dia_deadline": {"type": "integer", "description": "Dia limite (índice)."},
            },
            "required": ["sku", "quantidade", "dia_deadline"],
        },
    ),
    _fn(
        "simular_avaria",
        "Simular avaria/paragem de uma máquina e ver o impacto.",
        {
            "properties": {
                "maquina": {"type": "string", "description": "ID da máquina (ex: PRM019)."},
                "dia_inicio": {
                    "type": "integer",
                    "description": "Primeiro dia da avaria (índice).",
                },
                "duracao_dias": {"type": "integer", "description": "Duração em dias (default 1)."},
            },
            "required": ["maquina", "dia_inicio"],
        },
    ),
    _fn(
        "monte_carlo",
        "Simulação Monte Carlo de risco (~200 cenários aleatórios).",
        {
            "properties": {
                "amostras": {
                    "type": "integer",
                    "description": "Número de simulações (default 200, max 500).",
                },
            },
        },
    ),
]

# ─── MASTER DATA TOOLS (10) ──────────────────────────────────────────────

MASTER_TOOLS = [
    _fn(
        "adicionar_maquina",
        "Adicionar uma nova máquina à fábrica.",
        {
            "properties": {
                "id": {"type": "string", "description": "ID da máquina (ex: PRM050)."},
                "grupo": {"type": "string", "description": "Grupo (Grandes ou Medias)."},
                "activa": {
                    "type": "boolean",
                    "description": "Se a máquina está activa (default true).",
                },
            },
            "required": ["id", "grupo"],
        },
    ),
    _fn(
        "editar_maquina",
        "Editar propriedades de uma máquina existente.",
        {
            "properties": {
                "id": {"type": "string", "description": "ID da máquina."},
                "activa": {"type": "boolean", "description": "Activar/desactivar."},
                "grupo": {"type": "string", "description": "Novo grupo."},
            },
            "required": ["id"],
        },
    ),
    _fn(
        "adicionar_ferramenta",
        "Adicionar uma nova ferramenta.",
        {
            "properties": {
                "id": {"type": "string", "description": "ID da ferramenta (ex: BFP300)."},
                "primary": {"type": "string", "description": "Máquina primária."},
                "alt": {"type": "string", "description": "Máquina alternativa (opcional)."},
                "setup_hours": {"type": "number", "description": "Horas de setup (default 0.5)."},
            },
            "required": ["id", "primary"],
        },
    ),
    _fn(
        "editar_ferramenta",
        "Editar propriedades de uma ferramenta existente.",
        {
            "properties": {
                "id": {"type": "string", "description": "ID da ferramenta."},
                "alt": {
                    "type": "string",
                    "description": "Nova máquina alternativa (ou null para remover).",
                },
                "setup_hours": {"type": "number", "description": "Novas horas de setup."},
            },
            "required": ["id"],
        },
    ),
    _fn(
        "adicionar_twin",
        "Adicionar um par de peças gémeas.",
        {
            "properties": {
                "tool_id": {"type": "string", "description": "ID da ferramenta."},
                "sku_a": {"type": "string", "description": "SKU da peça A."},
                "sku_b": {"type": "string", "description": "SKU da peça B."},
            },
            "required": ["tool_id", "sku_a", "sku_b"],
        },
    ),
    _fn(
        "remover_twin",
        "Remover um par de peças gémeas.",
        {
            "properties": {
                "tool_id": {"type": "string", "description": "ID da ferramenta do par twin."},
            },
            "required": ["tool_id"],
        },
    ),
    _fn(
        "adicionar_feriado",
        "Adicionar um feriado.",
        {
            "properties": {
                "data": {"type": "string", "description": "Data no formato ISO (ex: 2026-12-25)."},
            },
            "required": ["data"],
        },
    ),
    _fn(
        "remover_feriado",
        "Remover um feriado existente.",
        {
            "properties": {
                "data": {"type": "string", "description": "Data no formato ISO (ex: 2026-12-25)."},
            },
            "required": ["data"],
        },
    ),
    _fn(
        "editar_turno",
        "Editar horário de um turno existente.",
        {
            "properties": {
                "turno_id": {"type": "string", "description": "ID do turno (A ou B)."},
                "inicio": {"type": "string", "description": "Nova hora início (HH:MM)."},
                "fim": {"type": "string", "description": "Nova hora fim (HH:MM)."},
            },
            "required": ["turno_id"],
        },
    ),
    _fn(
        "adicionar_turno",
        "Adicionar um novo turno.",
        {
            "properties": {
                "id": {"type": "string", "description": "ID do turno (ex: C)."},
                "inicio": {"type": "string", "description": "Hora início (HH:MM)."},
                "fim": {"type": "string", "description": "Hora fim (HH:MM)."},
                "label": {"type": "string", "description": "Nome do turno (ex: Noite)."},
            },
            "required": ["id", "inicio", "fim"],
        },
    ),
]

# ─── VISUALIZATION TOOLS (12) ────────────────────────────────────────────

VIZ_TOOLS = [
    _fn(
        "visualizar_stock",
        "Visualizar projecção de stock para um SKU.",
        {
            "properties": {
                "sku": {"type": "string", "description": "SKU da peça."},
            },
            "required": ["sku"],
        },
    ),
    _fn(
        "visualizar_carga_temporal",
        "Visualizar carga das máquinas ao longo do tempo.",
        {
            "properties": {
                "dia_inicio": {"type": "integer", "description": "Dia início (default 0)."},
                "dia_fim": {"type": "integer", "description": "Dia fim (default todos)."},
            },
        },
    ),
    _fn(
        "visualizar_risco_heatmap",
        "Visualizar heatmap de risco (máquina × dia).",
        {
            "properties": {},
        },
    ),
    _fn(
        "visualizar_encomendas",
        "Visualizar tabela de encomendas com status.",
        {
            "properties": {
                "cliente": {"type": "string", "description": "Filtrar por cliente (opcional)."},
            },
        },
    ),
    _fn(
        "visualizar_expedicao",
        "Visualizar plano de expedição dia-a-dia.",
        {
            "properties": {
                "dia_inicio": {"type": "integer", "description": "Dia início (default 0)."},
                "dia_fim": {"type": "integer", "description": "Dia fim (default todos)."},
            },
        },
    ),
    _fn(
        "visualizar_gantt",
        "Visualizar diagrama Gantt (timeline por máquina).",
        {
            "properties": {
                "maquina": {"type": "string", "description": "Filtrar por máquina (opcional)."},
                "dia_inicio": {"type": "integer", "description": "Dia início (default 0)."},
                "dia_fim": {"type": "integer", "description": "Dia fim (default 10)."},
            },
        },
    ),
    _fn(
        "visualizar_comparacao",
        "Visualizar comparação entre plano actual e cenário simulado.",
        {
            "properties": {
                "mutacoes": {
                    "type": "array",
                    "description": "Mutações do cenário a comparar.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "params": {"type": "object"},
                        },
                        "required": ["type", "params"],
                    },
                },
            },
            "required": ["mutacoes"],
        },
    ),
    _fn(
        "visualizar_learning",
        "Visualizar histórico de aprendizagem (reward ao longo do tempo).",
        {
            "properties": {},
        },
    ),
    _fn(
        "visualizar_atrasos",
        "Visualizar análise de atrasos com root cause e sugestões.",
        {
            "properties": {},
        },
    ),
    _fn(
        "visualizar_workforce",
        "Visualizar previsão de workforce (operadores necessários por dia).",
        {
            "properties": {
                "window": {"type": "integer", "description": "Janela de dias (default 5)."},
            },
        },
    ),
    _fn(
        "visualizar_cobertura",
        "Visualizar auditoria de cobertura por cliente.",
        {
            "properties": {},
        },
    ),
    _fn(
        "visualizar_propostas",
        "Visualizar propostas de melhoria (replan) sem recalcular.",
        {
            "properties": {},
        },
    ),
]

_MUTATING_TOOLS = {
    "recalcular_plano",
    "mover_referencia",
    "adicionar_regra",
    "remover_regra",
    "alterar_config",
    *(tool["function"]["name"] for tool in MASTER_TOOLS),
}
_MUTATION_CONTROL_PROPERTIES = {
    "expected_revision": {
        "type": "integer",
        "description": "Revisão actual do plano, obtida em ver_score.",
    },
    "approve_exceptions": {
        "type": "boolean",
        "description": "Confirmar explicitamente excepções não físicas.",
    },
    "approval_reason": {
        "type": "string",
        "description": "Motivo da aprovação, obrigatório quando há excepções.",
    },
    "approval_author": {
        "type": "string",
        "description": "Autor da aprovação, obrigatório quando há excepções.",
    },
}
for _tool in ACTION_TOOLS + MASTER_TOOLS:
    if _tool["function"]["name"] not in _MUTATING_TOOLS:
        continue
    _parameters = _tool["function"]["parameters"]
    _parameters["properties"].update(_MUTATION_CONTROL_PROPERTIES)
    if "expected_revision" not in _parameters["required"]:
        _parameters["required"].append("expected_revision")

# All tools combined
TOOLS = QUERY_TOOLS + ACTION_TOOLS + MASTER_TOOLS + VIZ_TOOLS
