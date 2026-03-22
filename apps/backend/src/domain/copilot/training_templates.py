"""Training templates and factory data for the PP1 scheduling copilot.

Contains system prompts, factory constants, scenario data, and message
formatting helpers used by the training data generator.
"""

from __future__ import annotations

import json
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

# ─── Scenario data constants ─────────────────────────────────────────────────

CAPACITY_SCENARIOS = [
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

REPLANNING_SCENARIOS = [
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

REPLAN_ZONES = [
    ("frozen", "0-5 dias", "cuidado — alterações mínimas, operadores já alocados"),
    ("slushy", "5 dias a 2 semanas", "flexibilidade moderada — pode mover blocos"),
    ("liquid", "mais de 2 semanas", "total flexibilidade — replaneamento livre"),
]

REPLAN_STRATEGIES = [
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

TWIN_PAIRS = [
    ("REF_LH_001", "REF_RH_001", "Bracket LH/RH", "BFP100", "PRM019"),
    ("REF_LH_002", "REF_RH_002", "Support LH/RH", "BFP101", "PRM031"),
    ("REF_LH_003", "REF_RH_003", "Link LH/RH", "BFP102", "PRM039"),
    ("REF_LH_004", "REF_RH_004", "Arm LH/RH", "BFP103", "PRM043"),
]

STATE_QA = [
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

REFUSAL_SCENARIOS = [
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

REFUSAL_VARIATIONS = [
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

DECISION_EXPLANATIONS = {
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

INFEASIBILITY_EXPLANATIONS = {
    "SETUP_CREW_EXHAUSTED": "A equipa de setup está ocupada — não há mais setups possíveis neste slot.",
    "TOOL_CONFLICT": "Duas máquinas precisam da mesma ferramenta ao mesmo tempo — constraint HARD.",
    "CALCO_CONFLICT": "Dois sítios precisam do mesmo calço — constraint HARD, mais restritivo que ferramenta.",
    "DEADLINE_VIOLATION": "Impossível produzir a tempo para o deadline — todas as opções esgotadas.",
    "CAPACITY_OVERFLOW": "Capacidade excedida — mesmo com overtime e alternativas, não cabe.",
    "SHIPPING_CUTOFF_VIOLATION": "Produção não pode terminar antes do cutoff de expedição.",
}

GOVERNANCE_QA = [
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

TRUSTINDEX_QA = [
    (
        "O que é o TrustIndex?",
        "TI = 0.15×C + 0.20×V + 0.15×F + 0.20×K + 0.15×P + 0.15×A. Gates: ≥0.90 Full Auto | ≥0.70 Monitoring | ≥0.50 Suggestion | <0.50 Manual.",
    ),
    (
        "Qual o nível de autonomia actual?",
        "Depende do TrustIndex. Com TI alto (≥0.90), o sistema pode operar em Full Auto. Abaixo disso, cada decisão significativa requer review ou aprovação humana.",
    ),
]


# ─── Helpers ──────────────────────────────────────────────────────────────────


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
