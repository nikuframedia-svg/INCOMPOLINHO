"""Training data generator for the PP1 scheduling copilot.

Extracts real factory data from the Incompol codebase and generates
JSONL training examples for QLoRA fine-tuning (Qwen2.5-14B).

Categories:
  1. Tool calling (50 examples)
  2. Reference explanations (60 examples)
  3. Capacity conflicts (60 examples)
  4. Replanning scenarios (50 examples)
  5. Twin parts (30 examples)
  6. Alerts & state (50 examples)
  7. Correct refusals (30 examples)
  8. Governance decisions (40 examples)

Usage:
  python -m apps.backend.src.domain.copilot.training_data_generator
"""

from __future__ import annotations

import json
import os
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# ─── System prompt (frozen for training) ─────────────────────────────────────

SYSTEM_PROMPT = """Tu és o assistente de planeamento da fábrica Incompol (NIKUFRA.AI).
Ajudas o planeador a gerir o plano de produção: regras, alertas, carga de máquinas, prioridades.

REGRAS:
- Responde SEMPRE em português de Portugal.
- Sê conciso e directo.
- Usa os tools disponíveis para executar acções — não te limites a explicar.
- Quando alterares regras ou configuração, recalcula o plano automaticamente.
- Nunca inventes dados. Se não tens informação, diz que precisas do ISOP carregado.

FÁBRICA INCOMPOL:
- 5 prensas activas, 59 ferramentas, ~94 SKUs, 14 clientes
- PRM020 está FORA DE USO — ignorar sempre

MÁQUINAS (capacidade diária = 1020 min, OEE = 0.66, cap. efectiva = 673 min):
- PRM019: Grandes, 21 SKUs — prensa principal
- PRM031: Grandes, 20 SKUs — dedicada Faurecia (Tier 1, prioridade máxima)
- PRM039: Grandes, 28 SKUs — maior variedade de ferramentas
- PRM042: Médias, 11 SKUs — SEM ALTERNATIVA (única máquina de médias)
- PRM043: Grandes, 14 SKUs — complementar

TURNOS:
- Turno A: 07:00–15:30 (S0=420min, T1=930min)
- Turno B: 15:30–00:00 (T1=930min, S1=1440min)
- Turno Noite: 00:00–07:00 — SÓ EMERGÊNCIA (sinalizar, nunca criar automaticamente)

OPERADORES POR TURNO:
- Grandes (PRM019, PRM031, PRM039, PRM043): A=6 operadores, B=5 operadores
- Médias (PRM042): A=9 operadores, B=4 operadores

4 CONSTRAINTS:
1. SetupCrew (HARD): Apenas 1 setup de ferramenta em toda a fábrica ao mesmo tempo
2. ToolTimeline (HARD): Uma ferramenta só pode estar numa máquina de cada vez
3. CalcoTimeline (HARD): Um calço só pode estar num sítio de cada vez (MAIS restritivo que ferramenta)
4. OperatorPool (ADVISORY): Avisa quando capacidade excedida mas NUNCA bloqueia

PEÇAS GÉMEAS (CO-PRODUÇÃO):
- Mesma ferramenta + máquina → produção SIMULTÂNEA de ambas
- Quantidade = max(|NP_A|, |NP_B|) para AMBAS as peças
- Tempo máquina = UMA quantidade (não o dobro)

REPLANEAMENTO (4 camadas):
1. Right-shift (<30min) 2. Match-up (30min–2h) 3. Parcial (>2h) 4. Regeneração total
Zonas: frozen (0–5d), slushy (5d–2sem), liquid (resto)

OTD-DELIVERY (OBRIGATÓRIO = 100%):
- Em CADA dia com procura, produção acumulada >= procura acumulada
- Qualquer falha é BUG — motor resolve com 3 Tiers de overflow"""

# ─── Real factory data ────────────────────────────────────────────────────────

MACHINES = {
    "PRM019": {"area": "Grandes", "skus": 21, "role": "prensa principal"},
    "PRM031": {"area": "Grandes", "skus": 20, "role": "dedicada Faurecia"},
    "PRM039": {"area": "Grandes", "skus": 28, "role": "maior variedade"},
    "PRM042": {"area": "Médias", "skus": 11, "role": "SEM ALTERNATIVA"},
    "PRM043": {"area": "Grandes", "skus": 14, "role": "complementar"},
}

CLIENTS = [
    "Faurecia",
    "Gestamp",
    "Sodecia",
    "Kirchhoff",
    "Magna",
    "Benteler",
    "Martinrea",
    "CIE",
    "Snop",
    "Aludec",
    "Brose",
    "Metalogalva",
    "Simoldes",
    "Tower",
]

DECISION_TYPES = [
    "BACKWARD_SCHEDULE",
    "LOAD_LEVEL",
    "OVERFLOW_ROUTE",
    "ADVANCE_PRODUCTION",
    "DATA_MISSING",
    "INFEASIBILITY_DECLARED",
    "DEADLINE_CONSTRAINT",
    "OPERATOR_REALLOCATION",
    "ALTERNATIVE_MACHINE",
    "TOOL_DOWN",
    "MACHINE_DOWN",
    "FAILURE_DETECTED",
    "FAILURE_MITIGATION",
    "FAILURE_UNRECOVERABLE",
    "SHIPPING_CUTOFF",
    "PRODUCTION_START",
    "CAPACITY_COMPUTATION",
    "SCORING_DECISION",
    "OPERATOR_CAPACITY_WARNING",
    "AUTO_REPLAN_ADVANCE",
    "AUTO_REPLAN_MOVE",
    "AUTO_REPLAN_SPLIT",
    "AUTO_REPLAN_OVERTIME",
    "AUTO_REPLAN_THIRD_SHIFT",
    "TWIN_VALIDATION_ANOMALY",
    "WORKFORCE_FORECAST_D1",
    "WORKFORCE_COVERAGE_MISSING",
    "LABOR_GROUP_UNMAPPED",
]

INFEASIBILITY_REASONS = [
    "SETUP_CREW_EXHAUSTED",
    "OPERATOR_CAPACITY",
    "TOOL_CONFLICT",
    "CALCO_CONFLICT",
    "DEADLINE_VIOLATION",
    "MACHINE_DOWN",
    "CAPACITY_OVERFLOW",
    "DATA_MISSING",
    "MACHINE_PARTIAL_DOWN",
    "TOOL_DOWN_TEMPORAL",
    "SHIPPING_CUTOFF_VIOLATION",
]

REMEDIATION_TYPES = [
    "THIRD_SHIFT",
    "EXTRA_OPERATORS",
    "OVERTIME",
    "SPLIT_OPERATION",
    "ADVANCE_PRODUCTION",
    "TRANSFER_ALT_MACHINE",
    "FORMAL_RISK_ACCEPTANCE",
]


def _load_fixture() -> dict[str, Any]:
    """Load nikufra_data.json fixture."""
    paths = [
        Path(__file__).resolve().parents[4]
        / "frontend"
        / "public"
        / "fixtures"
        / "nikufra"
        / "nikufra_data.json",
        Path("apps/frontend/public/fixtures/nikufra/nikufra_data.json"),
    ]
    for p in paths:
        if p.exists():
            with open(p) as f:
                return json.load(f)
    return {"tools": [], "machines": [], "dates": []}


def _msg(system: str, user: str, assistant: str) -> dict:
    """Build a training example in OpenAI messages format."""
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
    }


def _tool_call_msg(
    system: str, user: str, tool_name: str, tool_args: dict, result_text: str
) -> dict:
    """Build a training example with tool calling."""
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(tool_args, ensure_ascii=False),
                        },
                    }
                ],
            },
            {"role": "tool", "content": json.dumps({"result": result_text}, ensure_ascii=False)},
            {"role": "assistant", "content": result_text},
        ]
    }


# ─── Category 1: Tool calling (50 examples) ─────────────────────────────────


def _gen_tool_calling(fixture: dict) -> list[dict]:
    examples = []
    tools = fixture.get("tools", [])

    # explicar_referencia — 10 examples
    for tool in tools[:10]:
        sku = tool["skus"][0] if tool.get("skus") else "REF001"
        name = tool["nm"][0] if tool.get("nm") else "Peça"
        machine = tool.get("m", "PRM019")
        ph = tool.get("pH", 500)
        setup = tool.get("s", 1.0)

        questions = [
            f"Que informação tens sobre a referência {sku}?",
            f"Explica-me a ref {sku}.",
            f"Quero saber detalhes da {sku}.",
        ]
        answer = (
            f"A referência {sku} ({name}) é produzida na máquina {machine} "
            f"com uma cadência de {ph} peças/hora. O setup da ferramenta {tool['id']} "
            f"demora {setup}h. "
        )
        if tool.get("alt") and tool["alt"] != "-":
            answer += f"Máquina alternativa: {tool['alt']}. "

        examples.append(
            _tool_call_msg(
                SYSTEM_PROMPT,
                random.choice(questions),
                "explicar_referencia",
                {"sku": sku},
                answer,
            )
        )

    # ver_alertas — 8 examples
    severities = ["atraso", "red", "yellow", "all"]
    alert_questions = [
        ("Que alertas temos hoje?", "all"),
        ("Há alguma referência em atraso?", "atraso"),
        ("Mostra-me os alertas vermelhos.", "red"),
        ("Que alertas amarelos existem?", "yellow"),
        ("Temos algum problema urgente de stock?", "red"),
        ("Quais são os alertas mais graves?", "atraso"),
        ("Há peças em falta para amanhã?", "red"),
        ("Resume os alertas de produção.", "all"),
    ]
    for q, sev in alert_questions:
        examples.append(
            _tool_call_msg(
                SYSTEM_PROMPT,
                q,
                "ver_alertas",
                {"severity": sev},
                f"Consultei os alertas com filtro '{sev}'. Vou apresentar os resultados.",
            )
        )

    # ver_carga_maquinas — 7 examples
    load_questions = [
        ("Como está a carga das máquinas?", {}),
        ("A PRM019 está muito carregada?", {"machine_id": "PRM019"}),
        ("Qual a carga da PRM031?", {"machine_id": "PRM031"}),
        ("A PRM042 tem capacidade livre?", {"machine_id": "PRM042"}),
        ("Mostra-me a ocupação de todas as prensas.", {}),
        ("Que máquina tem mais folga?", {}),
        ("A PRM039 aguenta mais trabalho?", {"machine_id": "PRM039"}),
    ]
    for q, args in load_questions:
        examples.append(
            _tool_call_msg(
                SYSTEM_PROMPT,
                q,
                "ver_carga_maquinas",
                args,
                "Aqui está a informação de carga solicitada.",
            )
        )

    # mover_referencia — 8 examples
    move_scenarios = [
        ("Move a ref 262 para a PRM039.", "262", "PRM039", "pedido do planeador"),
        ("Preciso de tirar a 170 da PRM031.", "170", "PRM019", "descongestionar PRM031"),
        (
            "A PRM019 está sobrecarregada, move a 1065170X100 para alternativa.",
            "1065170X100",
            "PRM039",
            "overflow PRM019",
        ),
        ("Transfere a produção da ref 450 para PRM043.", "450", "PRM043", "balancear carga"),
        (
            "Faurecia pediu prioridade — move a ref 300 da PRM039 para PRM031.",
            "300",
            "PRM031",
            "prioridade Faurecia",
        ),
        (
            "A ferramenta BFP090 precisa de manutenção na PRM019, move SKUs.",
            "BFP090_SKU",
            "PRM039",
            "manutenção ferramenta",
        ),
        (
            "Quero a ref 580 na PRM043 para ficar perto da gémea.",
            "580",
            "PRM043",
            "co-produção com gémea",
        ),
        (
            "Move tudo o que puder da PRM031 para outras máquinas.",
            "BATCH",
            "PRM039",
            "libertação PRM031",
        ),
    ]
    for q, sku, target, reason in move_scenarios:
        examples.append(
            _tool_call_msg(
                SYSTEM_PROMPT,
                q,
                "mover_referencia",
                {"sku": sku, "target_machine": target, "reason": reason},
                f"Referência {sku} movida para {target}. Razão: {reason}.",
            )
        )

    # adicionar_regra — 5 examples
    rule_scenarios = [
        (
            "Adiciona uma regra: se a carga da PRM019 ultrapassar 90%, alerta.",
            {
                "id": "prm019_overload",
                "name": "Alerta sobrecarga PRM019",
                "condition_type": "machine_load_above",
                "action_type": "alert",
            },
        ),
        (
            "Cria uma regra para priorizar Faurecia sempre.",
            {
                "id": "faurecia_priority",
                "name": "Prioridade Faurecia",
                "condition_type": "client_equals",
                "action_type": "set_priority",
            },
        ),
        (
            "Quero uma regra: ref com atraso > 3 dias passa a urgente.",
            {
                "id": "atraso_urgente",
                "name": "Atraso → Urgente",
                "condition_type": "atraso_above",
                "action_type": "set_priority",
            },
        ),
        (
            "Adiciona regra para nunca agendar PRM042 no turno da noite.",
            {
                "id": "prm042_no_night",
                "name": "PRM042 sem noite",
                "condition_type": "machine_shift",
                "action_type": "block_shift",
            },
        ),
        (
            "Cria regra: SKUs com lote < 500 peças agrupar por ferramenta.",
            {
                "id": "small_lot_group",
                "name": "Agrupar lotes pequenos",
                "condition_type": "lot_below",
                "action_type": "group_by_tool",
            },
        ),
    ]
    for q, args in rule_scenarios:
        examples.append(
            _tool_call_msg(
                SYSTEM_PROMPT,
                q,
                "adicionar_regra",
                args,
                f"Regra '{args['name']}' criada com sucesso.",
            )
        )

    # sugerir_melhorias — 5 examples
    improve_questions = [
        ("Que melhorias sugeres para o plano actual?", "all"),
        ("Como posso melhorar o OTD?", "otd"),
        ("Há forma de reduzir setups?", "setup"),
        ("A carga está equilibrada entre máquinas?", "load_balance"),
        ("O que posso optimizar no scheduling?", "all"),
    ]
    for q, focus in improve_questions:
        examples.append(
            _tool_call_msg(
                SYSTEM_PROMPT,
                q,
                "sugerir_melhorias",
                {"focus": focus},
                "Analisei o plano e tenho sugestões de melhoria.",
            )
        )

    # agrupar_material — 4 examples
    group_scenarios = [
        (
            "Agrupa as refs 262 e 170 na PRM019 — usam a mesma matéria-prima.",
            ["262", "170"],
            "PRM019",
        ),
        ("Junta estas SKUs na PRM039: 450, 451, 452.", ["450", "451", "452"], "PRM039"),
        ("Agrupa referências da Faurecia na PRM031.", ["F001", "F002", "F003"], "PRM031"),
        ("Quero as refs 580 e 581 juntas na PRM043.", ["580", "581"], "PRM043"),
    ]
    for q, skus, machine in group_scenarios:
        examples.append(
            _tool_call_msg(
                SYSTEM_PROMPT,
                q,
                "agrupar_material",
                {"sku_list": skus, "machine_id": machine, "reason": "matéria-prima comum"},
                f"Regra de agrupamento criada para {len(skus)} referências em {machine}.",
            )
        )

    # recalcular_plano — 3 examples
    recalc_questions = [
        "Recalcula o plano.",
        "Actualiza o scheduling com as novas regras.",
        "Preciso de um novo plano — recalcula tudo.",
    ]
    for q in recalc_questions:
        examples.append(
            _tool_call_msg(
                SYSTEM_PROMPT,
                q,
                "recalcular_plano",
                {},
                "Recálculo disponível via frontend (scheduling é client-side). As regras foram guardadas e serão aplicadas na próxima execução.",
            )
        )

    return examples


# ─── Category 2: Reference explanations (60 examples) ───────────────────────


def _gen_reference_explanations(fixture: dict) -> list[dict]:
    examples = []
    tools = fixture.get("tools", [])

    for tool in tools[:30]:
        sku = tool["skus"][0] if tool.get("skus") else "REF"
        name = tool["nm"][0] if tool.get("nm") else "Peça"
        machine = tool.get("m", "PRM019")
        alt = tool.get("alt", "-")
        ph = tool.get("pH", 500)
        setup_h = tool.get("s", 1.0)
        lt = tool.get("lt", 0)
        op = tool.get("op", 1)

        # Question about SKU
        answer = (
            f"**{sku}** — {name}\n"
            f"- Máquina: {machine}\n"
            f"- Ferramenta: {tool['id']} (setup: {setup_h}h)\n"
            f"- Cadência: {ph} peças/hora\n"
            f"- Operadores: {op}\n"
        )
        if alt and alt != "-":
            answer += f"- Alternativa: {alt}\n"
        if lt > 0:
            answer += f"- Lote económico: {lt} peças\n"

        # Two variants per tool
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"Diz-me tudo sobre a referência {sku}.",
                answer,
            )
        )
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"Em que máquina se faz a {name}?",
                f"A {name} (ref {sku}) é produzida na {machine} com a ferramenta {tool['id']}."
                + (f" Alternativa: {alt}." if alt and alt != "-" else " Sem máquina alternativa."),
            )
        )

    return examples


# ─── Category 3: Capacity conflicts (60 examples) ───────────────────────────


def _gen_capacity_conflicts() -> list[dict]:
    examples = []
    today = date(2026, 3, 16)

    scenarios = [
        {
            "q": "A PRM019 está a 110% de capacidade — que faço?",
            "a": "A PRM019 está em overflow. Opções:\n1. **Mover referências** para PRM039 (máquina alternativa para maioria dos SKUs da PRM019)\n2. **Antecipar produção** — produzir nos dias anteriores com folga\n3. **Overtime** — até 450 min/máquina/dia extra\nRecomendo começar por mover as refs com alternativa na PRM039.",
        },
        {
            "q": "PRM042 não tem alternativa e está sobrecarregada.",
            "a": "A PRM042 é a única máquina de médias — não há alternativa. Opções limitadas:\n1. **Overtime** (até 450 min/dia)\n2. **Turno noite de emergência** (sinalizar, requer aprovação)\n3. **Antecipar produção** nos dias anteriores com folga\n4. **Split operation** — dividir lotes maiores se outra máquina puder fazer parte\nATENÇÃO: PRM042 com 11 SKUs sem alternativa é um bottleneck crítico.",
        },
        {
            "q": "Temos 3 setups ao mesmo tempo — é possível?",
            "a": "**NÃO.** O constraint SetupCrew é HARD: apenas 1 setup em toda a fábrica ao mesmo tempo. 3 setups simultâneos é impossível. O motor sequencia automaticamente os setups. Se isto está a causar atrasos, considere:\n1. Reduzir número de changeovers (agrupar por ferramenta)\n2. Antecipar setups nos tempos mortos",
        },
        {
            "q": "A ferramenta BFP090 precisa de estar na PRM019 e PRM039 ao mesmo tempo.",
            "a": "**Impossível.** O constraint ToolTimeline é HARD: uma ferramenta só pode estar numa máquina de cada vez. A BFP090 tem de ser sequenciada — primeiro numa máquina, depois na outra. Se ambas as máquinas precisam dela no mesmo dia, é uma situação de TOOL_CONFLICT e o motor declara infeasibility.",
        },
        {
            "q": "Posso meter o calço C005 na PRM019 e PRM031 ao mesmo tempo?",
            "a": "**Não.** O CalcoTimeline é HARD e MAIS restritivo que ToolTimeline: um calço só pode estar num sítio de cada vez, sem excepção de mesma máquina. O calço C005 tem de ser usado sequencialmente.",
        },
        {
            "q": "Quantos operadores preciso no turno B da PRM019?",
            "a": "No turno B (15:30–00:00), a PRM019 pertence ao grupo Grandes, que tem 5 operadores disponíveis. Se a carga exceder a capacidade, o sistema emite um OPERATOR_CAPACITY_WARNING mas **nunca bloqueia** o scheduling — é apenas advisory.",
        },
    ]

    # Generate 60 from 6 base scenarios × 10 machine/day variations
    for s in scenarios:
        examples.append(_msg(SYSTEM_PROMPT, s["q"], s["a"]))

    # Machine-specific overload scenarios
    for machine, info in MACHINES.items():
        for days_ahead in [1, 2, 3, 5, 7]:
            target_date = today + timedelta(days=days_ahead)
            load_pct = random.randint(85, 130)
            q = f"A {machine} está a {load_pct}% no dia {target_date.strftime('%d/%m')}."

            if load_pct <= 95:
                a = f"A {machine} está dentro da capacidade ({load_pct}%). Sem acção necessária."
            elif load_pct <= 105:
                a = (
                    f"A {machine} está no limite ({load_pct}%). Considere antecipar alguma produção "
                    f"ou usar overtime (até 450 min extra/dia) se necessário."
                )
            else:
                if machine == "PRM042":
                    a = (
                        f"A {machine} está em overflow ({load_pct}%) e é a ÚNICA máquina de médias. "
                        f"Opções: overtime, turno noite (emergência), ou antecipar produção."
                    )
                else:
                    alts = [
                        m for m in MACHINES if m != machine and MACHINES[m]["area"] == info["area"]
                    ]
                    a = (
                        f"A {machine} está em overflow ({load_pct}%). Mover refs para "
                        f"{', '.join(alts[:2])} ou antecipar produção."
                    )
            examples.append(_msg(SYSTEM_PROMPT, q, a))

    return examples[:60]


# ─── Category 4: Replanning scenarios (50 examples) ─────────────────────────


def _gen_replanning() -> list[dict]:
    examples = []

    scenarios = [
        {
            "q": "A PRM031 avariou — vai estar parada 20 minutos.",
            "a": "20 minutos → **Right-shift** (camada 1). O motor desloca os blocos seguintes 20 min para a frente. Impacto mínimo. Sem necessidade de replaneamento completo.",
        },
        {
            "q": "A PRM039 vai estar em manutenção 1 hora.",
            "a": "1 hora → **Match-up** (camada 2). O motor reagenda a zona afectada da PRM039, movendo blocos para cobrir o gap. Pode ser necessário ajustar 2-3 blocos seguintes.",
        },
        {
            "q": "A PRM019 precisa de manutenção de 4 horas amanhã.",
            "a": "4 horas → **Parcial** (camada 3). Recalcula parte do plano. 4h = ~240 min de capacidade perdida na PRM019. O motor vai:\n1. Mover refs com alternativa para PRM039/PRM043\n2. Antecipar produção urgente para hoje\n3. Overtime se necessário\nSe amanhã está na zona frozen (0-5 dias), requer atenção especial.",
        },
        {
            "q": "Incêndio na fábrica — todas as máquinas paradas pelo menos 2 dias.",
            "a": "Catástrofe → **Regeneração total** (camada 4). Recalcula TODO o plano com o novo horizonte. 2 dias = ~2040 min perdidos por máquina. Prioridades:\n1. Contactar clientes Tier 1 (Faurecia)\n2. Replanear por urgência de deadline\n3. Activar overtime máximo e turno noite quando reabrir\n4. Aceitar formalmente atrasos (FORMAL_RISK_ACCEPTANCE) para refs não críticas",
        },
        {
            "q": "Chegou um pedido urgente da Faurecia — 5000 peças da ref 300 para sexta.",
            "a": "Pedido urgente Faurecia → prioridade máxima. Passos:\n1. A PRM031 é dedicada Faurecia — verificar se há slot\n2. Se PRM031 cheia, liberar espaço movendo refs não-Faurecia\n3. O motor faz AUTO_REPLAN_ADVANCE + AUTO_REPLAN_MOVE\n4. 5000 peças a ~500 pç/h = ~15h de produção com OEE\n5. Pode precisar de overtime ou antecipar outros blocos",
        },
        {
            "q": "A ferramenta BFP082 partiu — não temos substituição por 3 dias.",
            "a": "Ferramenta indisponível 3 dias → TOOL_DOWN. O motor:\n1. Marca TOOL_DOWN_TEMPORAL para os 3 dias\n2. Se há máquina alternativa, move produção\n3. Se não, os blocos ficam INFEASIBLE com razão TOOL_DOWN_TEMPORAL\n4. Considerar produção antecipada das refs afectadas nos dias anteriores",
        },
    ]

    for s in scenarios:
        examples.append(_msg(SYSTEM_PROMPT, s["q"], s["a"]))

    # Zone-based replanning
    zones = [
        ("frozen", "0-5 dias", "cuidado — alterações mínimas, operadores já alocados"),
        ("slushy", "5 dias a 2 semanas", "flexibilidade moderada — pode mover blocos"),
        ("liquid", "mais de 2 semanas", "total flexibilidade — replaneamento livre"),
    ]
    for zone, period, desc in zones:
        for machine in list(MACHINES.keys())[:3]:
            q = f"Preciso de mover produção na {machine} que está na zona {zone} ({period})."
            a = f"Zona {zone} ({period}): {desc}. "
            if zone == "frozen":
                a += f"Na {machine}, alterações na zona frozen requerem justificação forte. Considere overtime ou turno noite em vez de mover blocos."
            elif zone == "slushy":
                a += f"Na {machine}, pode mover blocos com cuidado. Verificar impacto em deadlines e constraints."
            else:
                a += f"Na {machine}, replaneamento livre. O motor optimiza automaticamente."
            examples.append(_msg(SYSTEM_PROMPT, q, a))

    # Auto-replan strategies
    strategies = [
        (
            "ADVANCE_PRODUCTION",
            "antecipar produção",
            "Produzir mais cedo para evitar overflow no dia crítico",
        ),
        (
            "MOVE_ALT_MACHINE",
            "mover para alternativa",
            "Transferir para máquina alternativa com capacidade",
        ),
        ("SPLIT_OPERATION", "dividir operação", "Min 30% na original, min 60 min de déficit"),
        ("OVERTIME", "overtime", "Até 450 min/máquina/dia, 2700 min total/dia"),
        ("THIRD_SHIFT", "turno noite", "Activação GLOBAL — todas as máquinas, só emergência"),
    ]
    for strat_type, name, desc in strategies:
        for i in range(4):
            machine = list(MACHINES.keys())[i % 5]
            q = f"O motor sugeriu {name} na {machine}. Explica."
            a = f"**{strat_type}** — {desc}.\nAplicado à {machine} ({MACHINES[machine]['role']}). "
            if strat_type == "THIRD_SHIFT":
                a += "ATENÇÃO: turno noite é activação GLOBAL para todas as máquinas, não individual."
            elif strat_type == "SPLIT_OPERATION":
                a += "Regra: mínimo 30% do lote fica na máquina original, e só se aplica quando déficit > 60 min."
            examples.append(_msg(SYSTEM_PROMPT, q, a))

    return examples[:50]


# ─── Category 5: Twin parts (30 examples) ───────────────────────────────────


def _gen_twin_parts() -> list[dict]:
    examples = []

    twin_pairs = [
        ("REF_LH_001", "REF_RH_001", "Bracket LH/RH", "BFP100", "PRM019"),
        ("REF_LH_002", "REF_RH_002", "Support LH/RH", "BFP101", "PRM031"),
        ("REF_LH_003", "REF_RH_003", "Link LH/RH", "BFP102", "PRM039"),
        ("REF_LH_004", "REF_RH_004", "Arm LH/RH", "BFP103", "PRM043"),
    ]

    # Basic twin explanation
    for lh, rh, name, tool, machine in twin_pairs:
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"A {lh} e a {rh} são peças gémeas?",
                f"Sim, {lh} e {rh} ({name}) são peças gémeas. Usam a ferramenta {tool} na {machine} e são produzidas SIMULTANEAMENTE. "
                f"Quantidade = max(procura_LH, procura_RH). Tempo máquina = UMA quantidade (não dobro). "
                f"Excedente da peça com menor procura → stock.",
            )
        )

    # Cross-EDD pairing
    for lh, rh, name, tool, machine in twin_pairs:
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"A {lh} tem encomenda dia 5 e a {rh} dia 8. Como emparelham?",
                f"Emparelhamento cross-EDD: a 1ª encomenda da {lh} (dia 5) emparelha com a 1ª da {rh} (dia 8). "
                f"EDD merged = min(5, 8) = dia 5. Produz-se no deadline mais cedo. "
                f"A {rh} do dia 8 fica com stock antecipado.",
            )
        )

    # Quantity logic
    for lh, rh, name, tool, machine in twin_pairs:
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"Preciso de 3000 peças da {lh} e 5000 da {rh}. Quanto tempo demora?",
                f"Peças gémeas: quantidade = max(3000, 5000) = 5000. Produz 5000 de AMBAS. "
                f"Tempo = 5000 / (pH × OEE). A {lh} fica com 2000 peças de excedente → stock. "
                f"NÃO é 8000 total — é 5000 uma vez (co-produção simultânea).",
            )
        )

    # Anomalies
    for lh, rh, name, tool, machine in twin_pairs[:2]:
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"A {lh} diz que é gémea da {rh} mas a {rh} não referencia a {lh}.",
                "Anomalia de peça gémea detectada: relação unidireccional. "
                "O twin-validator marca TWIN_VALIDATION_ANOMALY. A co-produção NÃO é aplicada — "
                "para co-produzir, a relação tem de ser bidireccional (A→B E B→A).",
            )
        )

    # Cannot split twins
    for lh, rh, name, tool, machine in twin_pairs[:2]:
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"Posso mover a {lh} para PRM039 e deixar a {rh} na {machine}?",
                f"**NÃO recomendado.** {lh} e {rh} são gémeas — produção simultânea na mesma máquina. "
                f"Separar perde a vantagem de co-produção (tempo = 1x em vez de 2x). "
                f"O twinPartnerMap impede split automático de pares gémeos.",
            )
        )

    # When one twin has no demand
    for lh, rh, name, tool, machine in twin_pairs[:2]:
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"A {lh} tem encomenda mas a {rh} não. Produz-se a {rh}?",
                f"Se a {lh} tem procura, a máquina produz ambas (co-produção). "
                f"Mesmo sem encomenda, a {rh} sai da prensa — fica como stock. "
                f"Quantidade = procura da {lh} (max com 0 da {rh} = procura da {lh}).",
            )
        )

    return examples[:30]


# ─── Category 6: Alerts & state (50 examples) ───────────────────────────────


def _gen_alerts_state(fixture: dict) -> list[dict]:
    examples = []
    today = date(2026, 3, 16)
    tools = fixture.get("tools", [])

    # Atraso alert explanation
    for tool in tools[:8]:
        sku = tool["skus"][0] if tool.get("skus") else "REF"
        name = tool["nm"][0] if tool.get("nm") else "Peça"
        machine = tool.get("m", "PRM019")
        atraso = random.randint(500, 5000)

        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"A ref {sku} está em atraso. O que aconteceu?",
                f"A ref {sku} ({name}) na {machine} tem atraso de {atraso} peças. "
                f"Isto significa que a entrega JÁ FALHOU — há cliente(s) à espera. "
                f"Prioridade: produzir IMEDIATAMENTE. Verificar se há capacidade na {machine} "
                f"ou alternativa para recuperar o atraso.",
            )
        )

    # Red alert (tomorrow)
    for tool in tools[:8]:
        sku = tool["skus"][0] if tool.get("skus") else "REF"
        name = tool["nm"][0] if tool.get("nm") else "Peça"
        shortage = random.randint(1000, 8000)

        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"Faltam {shortage} peças da {sku} para amanhã!",
                f"Alerta VERMELHO: faltam {shortage} peças da {sku} ({name}) para entrega amanhã ({(today + timedelta(days=1)).strftime('%d/%m')}). "
                f"Acções imediatas:\n1. Verificar stock actual\n2. Calcular horas de produção: {shortage} / pH\n3. Overtime se necessário (max 450 min/máq/dia)\n4. Se impossível, notificar cliente HOJE",
            )
        )

    # Yellow alert (2-3 days)
    for tool in tools[:6]:
        sku = tool["skus"][0] if tool.get("skus") else "REF"
        name = tool["nm"][0] if tool.get("nm") else "Peça"
        shortage = random.randint(500, 3000)
        days = random.choice([2, 3])
        deadline = today + timedelta(days=days)

        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"Prevejo falta de {shortage} peças da {sku} no dia {deadline.strftime('%d/%m')}.",
                f"Alerta AMARELO: faltam {shortage} peças da {sku} ({name}) para {deadline.strftime('%d/%m')} "
                f"({days} dias). Há tempo para reagir:\n1. Antecipar produção se houver capacidade\n2. Verificar alternativas de máquina\n3. Ajustar prioridades no plano",
            )
        )

    # State questions
    state_qa = [
        (
            "Quantos SKUs temos no ISOP?",
            "O sistema tem ~94 SKUs activos no ISOP, distribuídos por 5 máquinas e 59 ferramentas.",
        ),
        (
            "Quantas máquinas estão activas?",
            "5 máquinas activas: PRM019, PRM031, PRM039, PRM042, PRM043. PRM020 está fora de uso.",
        ),
        (
            "Qual a capacidade diária total?",
            "Capacidade bruta: 5 × 1020 min = 5100 min/dia. Com OEE 0.66: 5 × 673 = 3365 min efectivos/dia.",
        ),
        (
            "Quantos clientes servimos?",
            "14 clientes. Faurecia é Tier 1 (automóvel) com prioridade máxima na PRM031.",
        ),
        (
            "Que turnos temos?",
            "Turno A: 07:00–15:30 (510 min). Turno B: 15:30–00:00 (510 min). Total: 1020 min/dia. Turno noite: só emergência.",
        ),
        (
            "Qual a ocupação ideal?",
            "Abaixo de 85% é confortável. 85-95% é carga pesada. Acima de 95% é risco crítico (RISK_CRITICAL_THRESHOLD). Acima de 100% é overflow.",
        ),
        (
            "O que é o OEE?",
            "OEE = Overall Equipment Effectiveness = 0.66 (66%). Capacidade efectiva = 1020 × 0.66 = 673 min por máquina por dia.",
        ),
        (
            "Quantas ferramentas existem?",
            "59 ferramentas no total (44 originais + 15 adicionais). Setup varia de 0.5h a 1.5h por ferramenta.",
        ),
    ]
    for q, a in state_qa:
        examples.append(_msg(SYSTEM_PROMPT, q, a))

    return examples[:50]


# ─── Category 7: Correct refusals (30 examples) ─────────────────────────────


def _gen_refusals() -> list[dict]:
    examples = []

    refusal_scenarios = [
        (
            "Mete 3 ferramentas na PRM042 ao mesmo tempo.",
            "Impossível. Cada máquina só pode ter UMA ferramenta montada de cada vez. Trocar ferramenta requer setup (0.5–1.5h) e o SetupCrew constraint limita a 1 setup em toda a fábrica ao mesmo tempo.",
        ),
        (
            "Agenda 10.000 peças da ref 262 para daqui a 1 hora.",
            "Não consigo garantir isso. A 500 peças/hora com OEE 0.66, 10.000 peças demoram ~30h de produção. Seria necessário mais de 3 dias de um turno completo. Posso verificar a capacidade disponível e sugerir a data mais cedo possível.",
        ),
        (
            "Ignora o constraint de SetupCrew — é urgente.",
            "O SetupCrew é um constraint HARD — não pode ser violado. Representa uma limitação FÍSICA (só há uma equipa de setup na fábrica). Mesmo em urgência, não é possível fazer 2 setups ao mesmo tempo. Posso optimizar a sequência de setups para minimizar o impacto.",
        ),
        (
            "Move a ref 500 para a PRM020.",
            "A PRM020 está FORA DE USO. Não é possível agendar produção nesta máquina. Alternativas: PRM019, PRM031, PRM039, PRM043 (grandes) ou PRM042 (médias).",
        ),
        (
            "Desactiva todos os constraints — quero ver o plano sem limites.",
            "Os constraints HARD (SetupCrew, ToolTimeline, CalcoTimeline) representam limitações FÍSICAS reais. Desactivá-los produziria um plano impossível de executar. O OperatorPool já é advisory (apenas avisa). Posso relaxar parâmetros como overtime ou activar turno noite para dar mais capacidade.",
        ),
        (
            "Quantas peças a Faurecia encomendou esta semana?",
            "Não tenho o ISOP carregado com dados actuais. Preciso que carregues o ficheiro ISOP para consultar encomendas. Sem dados, não invento valores.",
        ),
        (
            "Qual o stock da ref 999?",
            "A referência 999 não existe no sistema. Verifica o código — os SKUs válidos estão no ISOP carregado. Se é uma referência nova, precisa de ser adicionada ao master data.",
        ),
        (
            "Faz o plano de produção para o mês inteiro.",
            "O scheduling client-side trabalha tipicamente com horizonte de 8–15 dias. Um mês inteiro (22+ dias úteis) com 94 SKUs e 59 ferramentas pode exceder a capacidade do solver. Recomendo planear em janelas de 2 semanas e ir ajustando.",
        ),
        (
            "Põe a PRM042 a fazer peças grandes.",
            "A PRM042 é a única máquina de médias — não está configurada para peças grandes. As ferramentas de peças grandes não são compatíveis. As máquinas de grandes são: PRM019, PRM031, PRM039, PRM043.",
        ),
        (
            "Garante 100% OTD sem overtime.",
            "OTD 100% é obrigatório. Se a capacidade normal não é suficiente, o motor usa automaticamente: antecipação, máquinas alternativas, split de operações. Se ainda não chega, overtime (até 450 min/máq/dia) pode ser necessário. Não posso garantir 100% OTD sem a flexibilidade que o overtime dá.",
        ),
        (
            "Agenda produção no domingo.",
            "O sistema trabalha com dias úteis. Produção ao domingo requer configuração especial de calendário. Se é urgente, posso sinalizar a necessidade de turno extra mas não o posso agendar automaticamente.",
        ),
        (
            "Que preço devo cobrar ao cliente?",
            "Questões de preço/comerciais estão fora do meu âmbito. Sou especializado em planeamento de produção: máquinas, ferramentas, capacidade, deadlines. Para pricing, consulta o departamento comercial.",
        ),
        (
            "Apaga todo o histórico de decisões.",
            "O Decision Ledger é imutável por design (governance). Cada decisão registada é um registo permanente com custo, motivo e contrafactual. Não é possível apagar — é uma funcionalidade de auditoria, não uma limitação técnica.",
        ),
        (
            "Reduz o OEE para 0.30 para ter mais folga no plano.",
            "Reduzir o OEE artificialmente distorceria o plano. O OEE=0.66 reflecte a eficiência REAL da fábrica. Com OEE=0.30, o plano pensaria que cada máquina tem ~306 min/dia em vez de 673 min, e iria sobredimensionar overtime/turnos. O plano deve reflectir a realidade.",
        ),
        (
            "Quero que a IA decida sozinha sem aprovação humana.",
            "O nível de autonomia depende do TrustIndex (TI). Com TI ≥ 0.90: Full Auto. Com TI 0.70–0.90: Monitoring. Com TI 0.50–0.70: Suggestion only. Abaixo de 0.50: Manual. Decisões L3+ requerem contrafactual e aprovação (governance).",
        ),
    ]

    for q, a in refusal_scenarios:
        examples.append(_msg(SYSTEM_PROMPT, q, a))

    # Duplicate with slight variations
    variations = [
        ("Usa a PRM020.", "A PRM020 está FORA DE USO. Não posso agendar nada nesta máquina."),
        (
            "Agenda 2 setups ao mesmo tempo.",
            "Impossível — SetupCrew é HARD: apenas 1 setup em toda a fábrica ao mesmo tempo.",
        ),
        (
            "Qual o email do gerente?",
            "Não tenho acesso a contactos. O meu foco é planeamento de produção.",
        ),
        (
            "Calcula o salário dos operadores.",
            "Fora do meu âmbito. Trato de scheduling, não de RH/payroll.",
        ),
        (
            "Mete a PRM031 a fazer peças da PRM042.",
            "A PRM031 é de grandes, PRM042 de médias. As ferramentas não são compatíveis entre tipos de máquina.",
        ),
        (
            "Desliga o OTD — não preciso de 100%.",
            "OTD-Delivery = 100% é OBRIGATÓRIO e invariante frozen. Não pode ser desactivado. É um requisito de negócio inviolável.",
        ),
        (
            "Agenda 50 horas de overtime num dia.",
            "Overtime máximo: 450 min/máquina/dia (~7.5h). 50h ultrapassa qualquer limite razoável.",
        ),
        (
            "Ignora os deadlines da Faurecia.",
            "Faurecia é Tier 1 com prioridade absoluta. Ignorar deadlines Faurecia viola a regra de negócio mais importante da fábrica.",
        ),
        (
            "Quanto tempo demora a enviar a encomenda por correio?",
            "Logística e expedição estão fora do meu âmbito. Trato do planeamento de produção até à saída da prensa.",
        ),
        (
            "Põe as 94 referências todas na PRM019.",
            "A PRM019 tem 21 SKUs configurados e não pode receber ferramentas de outras máquinas incompatíveis. Além disso, iria sobrecarregar a capacidade: 673 min/dia é insuficiente para 94 refs.",
        ),
        (
            "Faz previsão de vendas para o próximo trimestre.",
            "Previsão de vendas (forecasting) está fora do meu âmbito. O PP1 planeia com base nas encomendas confirmadas do ISOP.",
        ),
        (
            "Cria um relatório financeiro.",
            "Relatórios financeiros estão fora do âmbito do planeamento de produção.",
        ),
        (
            "Muda o turno A para começar às 6:00.",
            "Os turnos são configurações frozen da fábrica: A 07:00–15:30, B 15:30–00:00. Alterar requer aprovação do director de produção e impacta operadores, contratos, e toda a lógica de scheduling.",
        ),
        (
            "Ignora as peças gémeas — produz só uma.",
            "Se a ferramenta produz peças gémeas, AMBAS saem da prensa — é uma limitação física do molde. Não é possível produzir apenas uma.",
        ),
        (
            "Apaga a ref 262 do sistema.",
            "Não apago referências do master data. Se a ref 262 foi descontinuada, deve ser marcada como inactiva pelo gestor de produto.",
        ),
    ]
    for q, a in variations:
        examples.append(_msg(SYSTEM_PROMPT, q, a))

    return examples[:30]


# ─── Category 8: Governance decisions (40 examples) ─────────────────────────


def _gen_governance() -> list[dict]:
    examples = []

    # Decision types explanation
    decision_explanations = {
        "BACKWARD_SCHEDULE": "Cálculo de datas mais cedo possível (earliest starts) — executado sempre no pipeline.",
        "LOAD_LEVEL": "Nivelamento de carga — move produção para TRÁS (dias anteriores), nunca para a frente.",
        "OVERFLOW_ROUTE": "Routing de overflow — move produção para máquina alternativa quando há excesso.",
        "ADVANCE_PRODUCTION": "Antecipação — produzir antes do deadline para evitar overflow.",
        "INFEASIBILITY_DECLARED": "Declaração formal de impossibilidade — registada no relatório de feasibility.",
        "DEADLINE_CONSTRAINT": "Restrição de deadline — bloco está limitado pela data de entrega.",
        "OPERATOR_CAPACITY_WARNING": "Aviso de capacidade de operadores — ADVISORY, nunca bloqueia.",
        "TOOL_DOWN": "Ferramenta indisponível — bloqueia produção nas máquinas que a usam.",
        "MACHINE_DOWN": "Máquina parada — nenhuma produção possível nesta máquina.",
        "TWIN_VALIDATION_ANOMALY": "Anomalia de peça gémea — relação unidireccional ou dados inconsistentes.",
        "AUTO_REPLAN_ADVANCE": "Replan automático: antecipou produção para resolver overflow.",
        "AUTO_REPLAN_MOVE": "Replan automático: moveu produção para máquina alternativa.",
        "AUTO_REPLAN_SPLIT": "Replan automático: dividiu operação entre máquinas (min 30% na original).",
        "AUTO_REPLAN_OVERTIME": "Replan automático: activou overtime (max 450 min/máq/dia).",
        "AUTO_REPLAN_THIRD_SHIFT": "Replan automático: activou turno noite (GLOBAL, todas as máquinas).",
    }

    for dtype, explanation in decision_explanations.items():
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"O que significa a decisão {dtype}?",
                f"**{dtype}**: {explanation}",
            )
        )

    # Infeasibility reasons
    infeasibility_explanations = {
        "SETUP_CREW_EXHAUSTED": "A equipa de setup está ocupada — não há mais setups possíveis neste slot.",
        "TOOL_CONFLICT": "Duas máquinas precisam da mesma ferramenta ao mesmo tempo — constraint HARD.",
        "CALCO_CONFLICT": "Dois sítios precisam do mesmo calço — constraint HARD, mais restritivo que ferramenta.",
        "DEADLINE_VIOLATION": "Impossível produzir a tempo para o deadline — todas as opções esgotadas.",
        "CAPACITY_OVERFLOW": "Capacidade excedida — mesmo com overtime e alternativas, não cabe.",
        "SHIPPING_CUTOFF_VIOLATION": "Produção não pode terminar antes do cutoff de expedição.",
    }

    for reason, explanation in infeasibility_explanations.items():
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"O plano mostra {reason}. O que aconteceu?",
                f"**{reason}**: {explanation}\nO motor tentou todas as alternativas (3 Tiers de overflow) antes de declarar infeasibility.",
            )
        )

    # Governance levels
    governance_qa = [
        (
            "O que é governance L0?",
            "**L0 — Logging**: Todas as decisões são registadas automaticamente. Sem validação adicional.",
        ),
        (
            "Explica governance L3.",
            "**L3 — Contrafactual**: Além de logging + validação + preview (L0-L2), L3 exige: custo explícito do desvio, contrafactual (o que aconteceria sem esta decisão), e motivo declarado.",
        ),
        (
            "Quando é necessária aprovação?",
            "**L4+** — Aprovação requerida. L4: 1 aprovador. L5: multi-aprovação. Aplica-se a decisões com alto impacto (ex: ignorar deadline Tier 1, activar turno noite, overtime > threshold).",
        ),
        (
            "O que é o Decision Ledger?",
            "O Decision Ledger é o registo IMUTÁVEL de todas as decisões. Cada entrada tem: tipo, custo, motivo (técnico/comercial/conveniência/hierárquico), timestamp, e contrafactual para L3+. Nunca pode ser editado ou apagado.",
        ),
        (
            "O que é o Firewall?",
            "O Decision Integrity Firewall NÃO impede decisões — torna-as CARAS e VISÍVEIS. Cada desvio do óptimo tem: custo explícito (calculado deterministicamente, NUNCA pelo LLM), motivo declarado, categoria de incentivo, e registo imutável.",
        ),
    ]
    for q, a in governance_qa:
        examples.append(_msg(SYSTEM_PROMPT, q, a))

    # TrustIndex
    ti_qa = [
        (
            "O que é o TrustIndex?",
            "TI = 0.15×C + 0.20×V + 0.15×F + 0.20×K + 0.15×P + 0.15×A. Gates: ≥0.90 Full Auto | ≥0.70 Monitoring | ≥0.50 Suggestion | <0.50 Manual.",
        ),
        (
            "Qual o nível de autonomia actual?",
            "Depende do TrustIndex. Com TI alto (≥0.90), o sistema pode operar em Full Auto. Abaixo disso, cada decisão significativa requer review ou aprovação humana.",
        ),
    ]
    for q, a in ti_qa:
        examples.append(_msg(SYSTEM_PROMPT, q, a))

    return examples[:40]


# ─── Main generator ──────────────────────────────────────────────────────────


def generate_all(output_dir: str = "data/training") -> tuple[int, int]:
    """Generate all training data and write JSONL files.

    Returns (train_count, eval_count).
    """
    fixture = _load_fixture()

    all_examples: list[dict] = []
    all_examples.extend(_gen_tool_calling(fixture))
    all_examples.extend(_gen_reference_explanations(fixture))
    all_examples.extend(_gen_capacity_conflicts())
    all_examples.extend(_gen_replanning())
    all_examples.extend(_gen_twin_parts())
    all_examples.extend(_gen_alerts_state(fixture))
    all_examples.extend(_gen_refusals())
    all_examples.extend(_gen_governance())

    # Shuffle
    random.seed(42)
    random.shuffle(all_examples)

    # Split 90/10
    split_idx = int(len(all_examples) * 0.9)
    train = all_examples[:split_idx]
    eval_data = all_examples[split_idx:]

    # Write
    os.makedirs(output_dir, exist_ok=True)
    train_path = os.path.join(output_dir, "dados_treino.jsonl")
    eval_path = os.path.join(output_dir, "dados_eval.jsonl")
    prompt_path = os.path.join(output_dir, "system_prompt.txt")

    with open(train_path, "w", encoding="utf-8") as f:
        for ex in train:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    with open(eval_path, "w", encoding="utf-8") as f:
        for ex in eval_data:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(SYSTEM_PROMPT)

    return len(train), len(eval_data)


if __name__ == "__main__":
    train_n, eval_n = generate_all()
    print(f"Generated {train_n} training + {eval_n} eval examples")
    print(f"Total: {train_n + eval_n}")
    print("Output: data/training/dados_treino.jsonl, dados_eval.jsonl, system_prompt.txt")
