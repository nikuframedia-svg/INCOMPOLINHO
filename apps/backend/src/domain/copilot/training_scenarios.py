"""Scenario generation functions for PP1 copilot training data.

Each function generates training examples for a specific category.

NOTE: This file exceeds the 400-LOC guideline intentionally.
Scenario generators depend heavily on training_templates data
and splitting would reduce readability without benefit.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from .training_templates import (
    CAPACITY_SCENARIOS,
    DECISION_EXPLANATIONS,
    GOVERNANCE_QA,
    INFEASIBILITY_EXPLANATIONS,
    MACHINES,
    REFUSAL_SCENARIOS,
    REFUSAL_VARIATIONS,
    REPLAN_STRATEGIES,
    REPLAN_ZONES,
    REPLANNING_SCENARIOS,
    STATE_QA,
    SYSTEM_PROMPT,
    TRUSTINDEX_QA,
    TWIN_PAIRS,
    _msg,
    _tool_call_msg,
)

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
    for q in [
        "Recalcula o plano.",
        "Actualiza o scheduling com as novas regras.",
        "Preciso de um novo plano — recalcula tudo.",
    ]:
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

        examples.append(_msg(SYSTEM_PROMPT, f"Diz-me tudo sobre a referência {sku}.", answer))
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

    for s in CAPACITY_SCENARIOS:
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

    for s in REPLANNING_SCENARIOS:
        examples.append(_msg(SYSTEM_PROMPT, s["q"], s["a"]))

    # Zone-based replanning
    for zone, period, desc in REPLAN_ZONES:
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
    for strat_type, name, desc in REPLAN_STRATEGIES:
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

    for lh, rh, name, tool, machine in TWIN_PAIRS:
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"A {lh} e a {rh} são peças gémeas?",
                f"Sim, {lh} e {rh} ({name}) são peças gémeas. Usam a ferramenta {tool} na {machine} e são produzidas SIMULTANEAMENTE. "
                f"Quantidade = max(procura_LH, procura_RH). Tempo máquina = UMA quantidade (não dobro). "
                f"Excedente da peça com menor procura → stock.",
            )
        )

    for lh, rh, name, tool, machine in TWIN_PAIRS:
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"A {lh} tem encomenda dia 5 e a {rh} dia 8. Como emparelham?",
                f"Emparelhamento cross-EDD: a 1ª encomenda da {lh} (dia 5) emparelha com a 1ª da {rh} (dia 8). "
                f"EDD merged = min(5, 8) = dia 5. Produz-se no deadline mais cedo. "
                f"A {rh} do dia 8 fica com stock antecipado.",
            )
        )

    for lh, rh, name, tool, machine in TWIN_PAIRS:
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"Preciso de 3000 peças da {lh} e 5000 da {rh}. Quanto tempo demora?",
                f"Peças gémeas: quantidade = max(3000, 5000) = 5000. Produz 5000 de AMBAS. "
                f"Tempo = 5000 / (pH × OEE). A {lh} fica com 2000 peças de excedente → stock. "
                f"NÃO é 8000 total — é 5000 uma vez (co-produção simultânea).",
            )
        )

    for lh, rh, name, tool, machine in TWIN_PAIRS[:2]:
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"A {lh} diz que é gémea da {rh} mas a {rh} não referencia a {lh}.",
                "Anomalia de peça gémea detectada: relação unidireccional. "
                "O twin-validator marca TWIN_VALIDATION_ANOMALY. A co-produção NÃO é aplicada — "
                "para co-produzir, a relação tem de ser bidireccional (A→B E B→A).",
            )
        )

    for lh, rh, name, tool, machine in TWIN_PAIRS[:2]:
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"Posso mover a {lh} para PRM039 e deixar a {rh} na {machine}?",
                f"**NÃO recomendado.** {lh} e {rh} são gémeas — produção simultânea na mesma máquina. "
                f"Separar perde a vantagem de co-produção (tempo = 1x em vez de 2x). "
                f"O twinPartnerMap impede split automático de pares gémeos.",
            )
        )

    for lh, rh, name, tool, machine in TWIN_PAIRS[:2]:
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

    for q, a in STATE_QA:
        examples.append(_msg(SYSTEM_PROMPT, q, a))

    return examples[:50]


# ─── Category 7: Correct refusals (30 examples) ─────────────────────────────


def _gen_refusals() -> list[dict]:
    examples = []

    for q, a in REFUSAL_SCENARIOS:
        examples.append(_msg(SYSTEM_PROMPT, q, a))

    for q, a in REFUSAL_VARIATIONS:
        examples.append(_msg(SYSTEM_PROMPT, q, a))

    return examples[:30]


# ─── Category 8: Governance decisions (40 examples) ─────────────────────────


def _gen_governance() -> list[dict]:
    examples = []

    for dtype, explanation in DECISION_EXPLANATIONS.items():
        examples.append(
            _msg(
                SYSTEM_PROMPT, f"O que significa a decisão {dtype}?", f"**{dtype}**: {explanation}"
            )
        )

    for reason, explanation in INFEASIBILITY_EXPLANATIONS.items():
        examples.append(
            _msg(
                SYSTEM_PROMPT,
                f"O plano mostra {reason}. O que aconteceu?",
                f"**{reason}**: {explanation}\nO motor tentou todas as alternativas (3 Tiers de overflow) antes de declarar infeasibility.",
            )
        )

    for q, a in GOVERNANCE_QA:
        examples.append(_msg(SYSTEM_PROMPT, q, a))

    for q, a in TRUSTINDEX_QA:
        examples.append(_msg(SYSTEM_PROMPT, q, a))

    return examples[:40]
