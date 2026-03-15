"""PP1 LLM Layer — OpenAI GPT-4o with function calling."""

import json
import os

from openai import OpenAI

# Tool definitions for OpenAI function calling
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "adicionar_maquina",
            "description": "Adicionar uma nova máquina de prensagem ao sistema. Usar quando o utilizador quer registar uma nova prensa.",
            "parameters": {
                "type": "object",
                "properties": {
                    "machine_id": {
                        "type": "string",
                        "description": "Identificador da máquina (ex: PRM050)",
                    },
                    "shifts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Turnos disponíveis (ex: ['manha', 'tarde', 'noite'])",
                    },
                },
                "required": ["machine_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "definir_lote_economico",
            "description": "Definir ou alterar o lote económico mínimo de uma referência. O lote económico é a quantidade mínima que compensa produzir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref_id": {
                        "type": "string",
                        "description": "Referência do artigo (ex: 1064169X100)",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Quantidade mínima do lote económico",
                    },
                },
                "required": ["ref_id", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agrupar_material",
            "description": "Agrupar referências que partilham matéria-prima na mesma máquina. Usado quando duas ou mais referências usam os mesmos rolos/material.",
            "parameters": {
                "type": "object",
                "properties": {
                    "refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista de referências que partilham material (ex: ['1092262X100', '1065170X100'])",
                    },
                    "machine": {
                        "type": "string",
                        "description": "Máquina onde devem ser produzidas (ex: PRM019)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Razão para o agrupamento (ex: 'partilham rolos de aço 1.5mm')",
                    },
                },
                "required": ["refs", "machine"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mover_referencia",
            "description": "Mover uma referência para outra máquina. Alterar a alocação de máquina de uma referência.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref_id": {"type": "string", "description": "Referência do artigo"},
                    "machine": {"type": "string", "description": "Nova máquina (ex: PRM031)"},
                },
                "required": ["ref_id", "machine"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "definir_buffer_producao",
            "description": "Definir quantos dias antes da entrega a produção deve estar concluída. Default é 2 dias.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Número de dias de buffer antes da entrega",
                    }
                },
                "required": ["days"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recalcular_plano",
            "description": "Recalcular o plano de produção com todas as alterações aplicadas. Chamar depois de fazer alterações.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explicar_referencia",
            "description": "Obter informação detalhada sobre uma referência específica: stock, cobertura, prioridade, plano de produção.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref_id": {"type": "string", "description": "Referência do artigo a explicar"}
                },
                "required": ["ref_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ver_carga_maquinas",
            "description": "Ver a carga e utilização de todas as máquinas. Mostra horas agendadas, capacidade e taxa de utilização.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ver_alertas",
            "description": "Ver todos os alertas activos: atrasos (prioridade máxima), urgentes (amanhã), atenção (2 dias).",
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["all", "atraso", "red", "yellow"],
                        "description": "Filtrar por severidade. 'all' mostra todos.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remover_maquina",
            "description": "Marcar uma máquina como indisponível (ex: avaria, manutenção).",
            "parameters": {
                "type": "object",
                "properties": {
                    "machine_id": {
                        "type": "string",
                        "description": "Identificador da máquina a remover",
                    }
                },
                "required": ["machine_id"],
            },
        },
    },
]


SYSTEM_PROMPT = """Tu és o assistente de planeamento de produção da PP1 — ProdPlan ONE, instalado na fábrica Incompol (estampagem metálica, componentes automóveis).

O teu papel:
- Ajudar o planeador de produção a gerir o plano
- Explicar decisões de scheduling em português simples
- Executar alterações ao plano quando pedidas (adicionar máquinas, alterar lotes, agrupar materiais, etc.)
- Alertar para problemas (atrasos, rupturas, carga excessiva)

Regras da fábrica que SEMPRE respeitas:
1. Produção just-in-time: produzir 1-2 dias antes da data de necessidade, nunca muito antes (ocupa espaço e imobiliza matéria-prima)
2. Lote económico: nunca produzir abaixo do lote económico, mesmo que a necessidade seja menor
3. Peças gémeas: referências com peça gémea partilham ferramenta, podem ser sequenciadas na mesma máquina
4. Matéria-prima partilhada: referências que partilham MP devem ser produzidas na mesma máquina quando possível
5. Prioridades: ATRASO (já em falta) > Vermelho (amanhã) > Amarelo (2 dias) > Normal

Máquinas disponíveis: PRM019, PRM031, PRM039, PRM042, PRM043 (prensas de estampagem)
Turnos: manhã (06:00-14:00) + tarde (14:00-22:00) = 16h/dia

Quando fazes alterações, SEMPRE chama recalcular_plano depois para actualizar o Gantt e alertas.

Responde SEMPRE em português de Portugal. Sê directo, sem rodeios. Usa linguagem de fábrica, não académica."""


class LLMEngine:
    def __init__(self, scheduler, api_key: str = None):
        self.scheduler = scheduler
        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self.conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def _execute_tool(self, function_name: str, arguments: dict) -> str:
        """Execute a tool call and return result."""
        try:
            if function_name == "adicionar_maquina":
                return self.scheduler.add_machine(arguments["machine_id"], arguments.get("shifts"))
            elif function_name == "definir_lote_economico":
                return self.scheduler.set_economic_lot(arguments["ref_id"], arguments["quantity"])
            elif function_name == "agrupar_material":
                return self.scheduler.add_material_affinity(
                    arguments["refs"], arguments["machine"], arguments.get("reason", "")
                )
            elif function_name == "mover_referencia":
                return self.scheduler.set_machine_override(
                    arguments["ref_id"], arguments["machine"]
                )
            elif function_name == "definir_buffer_producao":
                return self.scheduler.set_buffer_days(arguments["days"])
            elif function_name == "recalcular_plano":
                result = self.scheduler.schedule_all()
                return json.dumps(result, indent=2, ensure_ascii=False)
            elif function_name == "explicar_referencia":
                return self.scheduler.explain_ref(arguments["ref_id"])
            elif function_name == "ver_carga_maquinas":
                return self.scheduler.get_machine_load()
            elif function_name == "ver_alertas":
                severity = arguments.get("severity", "all")
                alerts = self.scheduler.get_alerts_json()
                if severity != "all":
                    alerts = [a for a in alerts if a["severity"] == severity]
                return json.dumps(alerts[:20], indent=2, ensure_ascii=False)
            elif function_name == "remover_maquina":
                return self.scheduler.remove_machine(arguments["machine_id"])
            else:
                return f"Função desconhecida: {function_name}"
        except Exception as e:
            return f"Erro ao executar {function_name}: {str(e)}"

    def chat(self, user_message: str) -> dict:
        """Process a user message and return response with any tool calls made."""
        self.conversation_history.append({"role": "user", "content": user_message})

        tool_calls_made = []
        max_iterations = 5

        for _ in range(max_iterations):
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=self.conversation_history,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.3,
            )

            message = response.choices[0].message

            # Add assistant message to history
            self.conversation_history.append(message)

            if message.tool_calls:
                # Process tool calls
                for tool_call in message.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments)

                    result = self._execute_tool(fn_name, fn_args)
                    tool_calls_made.append(
                        {
                            "function": fn_name,
                            "arguments": fn_args,
                            "result": result,
                        }
                    )

                    self.conversation_history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result,
                        }
                    )
            else:
                # No more tool calls, return final response
                return {
                    "response": message.content,
                    "tool_calls": tool_calls_made,
                    "schedule_updated": any(
                        tc["function"] == "recalcular_plano" for tc in tool_calls_made
                    ),
                }

        # Max iterations reached
        return {
            "response": message.content if message.content else "Operação concluída.",
            "tool_calls": tool_calls_made,
            "schedule_updated": any(tc["function"] == "recalcular_plano" for tc in tool_calls_made),
        }
