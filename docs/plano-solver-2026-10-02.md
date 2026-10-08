# INCOMPOLINHO: auditoria, contrato e plano do solver

Data: 02/10/2026, Europe/Lisbon. Estado: **plano de implementação fundamentado
por auditoria e reproduções; o solver e o plano ativo não foram alterados**.

## 1. Decisão recomendada

Manter OR-Tools CP-SAT, corrigir o contrato de comparação e completar a procura
barata de antecipações. Construir/alocar no primeiro intervalo viável, melhorar
com inserções e trocas locais e usar CP-SAT em pequenos grupos de conflitos.
Aumentar o tempo do solver global, trocar de biblioteca ou dividir ficheiros sem
alinhar os critérios de aceitação não resolve a falha principal encontrada.

**Prioridade operacional: produzir o mais cedo possível após a libertação de
material, dentro da janela de cinco dias úteis, preservando recursos, quantidades
e compromissos de entrega.** As economias de setup e de transferências vêm depois
da antecipação entre candidatos admissíveis.

**Decisão confirmada pelo utilizador nesta conversa:** antecipar pode acrescentar
setup se preservar todas as entregas e restrições físicas. Setups são desempate.
Isto substitui a antiga proibição de aumentar automaticamente o número/minutos
de setup. A fase 1 deve remover esse veto do avaliador e dos geradores que o
reproduzem; não criar um novo pedido de aprovação só por esse aumento.
A reprodução BFP186 continua especialmente útil: melhora mesmo sem setup extra.

O [AGENTS.md](../AGENTS.md) fixa as regras para intervenções futuras. A
[pesquisa detalhada](auditoria-solver-2026-10-02/pesquisa.md) compara alternativas,
fontes e limites de aplicabilidade.

## 2. Âmbito e evidência

O caminho do chat `/home/luis/projects/INCOMPOL` não existe. A auditoria incidiu
no projeto identificado pelo utilizador, `/home/luis/projects/INCOMPOLINHO`.

- Inspecionados 106 turnos de duas conversas deste projeto; extraídos os
  **30 pedidos de utilizador mais recentes**, entre 24/09 e 02/10. Pedidos de
  estado/continuação permanecem identificados, não contam como defeitos novos.
- Código efetivo do working tree, com 118 ficheiros tracked modificados e
  numerosos ficheiros novos antes desta intervenção. O HEAD `4950a9e` é de
  julho; os últimos 30 commits não representam os últimos 30 pedidos.
- Snapshot ativo lido via SQLite em modo read-only: revisão **90**, ID
  `046b5d08b9884672ba2f9cf7e0f024d7`, modelo `aps-v5`, política guardada
  `setup-families-v1`. Hash do payload:
  `2a7d9d7c24be3c5621720ef3e64f538d49f964f74954242822e5a863d4328a0b`.
- Dimensão real desse snapshot: **95 operações de entrada, 5 máquinas,
  202 lotes, 558 segmentos**, 81 datas de 17/09 a 06/12. As contagens históricas
  de 59 ferramentas/~94 SKUs da documentação não substituem esta medição.
- Para 02/10, D15: 49 lotes protegidos, 153 móveis em 152 campanhas móveis.
  Há uma âncora no dataset; já está abrangida pela proteção histórica, pelo
  que o conjunto adicional de âncoras móveis é vazio.

Os relatos anteriores orientam a análise, mas não são tratados como prova de
que o bug ainda existe. As correções de montagem, conservação do candidato após
timeout e transações já presentes são património a preservar.

### 2.1 Reprodução atual: BFP186

Lote `LOT_TWIN_BFP186_47`, campanha `run_BFP186_PRM039_1`:

| Campo | Plano ativo | Candidato auditado |
|---|---|---|
| Data | 20/10/2026 | 20/10/2026 |
| Máquina | PRM043 | PRM039 |
| Início produtivo | 14:55 | 08:30 |
| Ganho no início | — | **385 minutos** |
| Restantes campanhas | Posições atuais | Posições preservadas |
| Física, origem, quantidades e âncoras | Válidas no validador atual | Válidas no validador atual |
| Entregas por encomenda e setups | Referência | Sem perdas/aumento |

A pesquisa verificou **236 combinações campanha/máquina** num único núcleo:
235 não anteciparam e uma antecipou. Uma passagem medida demorou **1,786 s**;
pico de RSS do processo, medido por `/proc/self/status`: **110,0 MiB**.
Uma passagem anterior encontrou o mesmo caso em 1,843 s. Não é um benchmark de
cálculo integral, nem uma prova de ótimo global; usa o alocador atual com os
restantes trabalhos fixos. Todos os objetos foram destacados da base de dados.
O reproducer guardado no documento, que volta a calcular os factos da baseline,
confirmou o mesmo caso em **3,081 s**, com **113,89 MiB**. Conservar ambas as
medições: o resultado é estável nestas verificações; o tempo não é uma garantia.

O snapshot tinha `left_shift_opportunities=0`. A auditoria nas mesmas máquinas
também devolveu zero lacunas. Isso **não cobre a antecipação por máquina
alternativa**. Confundir os âmbitos produz uma falsa sensação de conclusão.

### 2.2 Comparação com o ciclo existente

Uma execução da compactação existente, também limitada por afinidade a um núcleo,
demorou **5,281 s**, com pico **121,98 MiB**. Terminou como
`partial/search_limit`, avaliou oito candidatos de transferência e aceitou zero
movimentos. O relatório de fases observou uma normalização de ~443 ms; esses
tempos são inclusivos e não constituem um perfil completo.

O ganho acima ficou por aplicar mesmo havendo orçamento potencialmente útil.
A primeira intervenção é alargar a geração/seleção de candidatos de antecipação.
Estas amostras não estabelecem p50/p95 nem a RAM necessária ao solver global.
O host expõe 20 CPUs; a afinidade de um núcleo restringe paralelismo, mas não
reproduz a velocidade/cache de um computador industrial mais lento.

Ver evidência JSON (artefacto local não incluído),
benchmark (artefacto local não incluído) e
contraexemplos de comparação (artefacto local não incluído).

## 3. Onde está o problema estrutural

O termo “code slop” é usado aqui para regras contraditórias, percursos acumulados
e responsabilidades pouco claras; tamanho de ficheiro, por si só, não prova bug.

| Prioridade | Evidência no código atual | Consequência | Intervenção |
|---|---|---|---|
| P1 | `alternative_repair.py:151-202`: seleção por risco/inversão e aceitação apenas com `delivery_improves`; `_repair_complete` em 581 | Um lote pontual como BFP186 pode não ser sequer candidato | Enumerar antecipações em todas as máquinas elegíveis, mesmo sem melhoria do KPI de entrega |
| P1 | `improvement.py:314` coloca setups/minutos/transferências antes de `production_time_cost`; `optimizer.py:4238` prefere antecipação antes de setups | Dois avaliadores podem escolher planos opostos | Um contrato, uma comparação e uma versão de política |
| P1 | `improvement.py:307-310` rejeita aumento de setups/minutos antes de comparar o benefício | Contraria a decisão explícita desta conversa | Retirar o veto; manter validação física da preparação e guardas por encomenda |
| P1 | `scoring.py:196-214`: custo `p*S + p²/2`, com duração dependente da máquina | O proxy mistura velocidade e posição temporal | Métrica de antecipação explícita e independente da duração da máquina |
| P1 | `normalize_earliest_legal_plan` em `scheduler.py:3215` preserva a atribuição de máquina; auditoria de lacunas não cobre todas as alternativas | Zero lacunas locais não equivale a antecipação esgotada | Relatório por vizinhança e certificados limitados ao âmbito |
| P1 | `CLAUDE.md:89` ainda manda produzir o mais tarde possível; `RulesPage.tsx:36` mostra preferência de evitar antecipação | Documentação e interface induzem novas alterações contraditórias | Tornar o AGENTS a referência; alinhar textos e remover parâmetros sem efeito após inventário |
| P2 | `optimizer.py` tem 4 926 linhas, `scheduler.py` 4 885; `schedule_all` tem 745 | Orquestração, reparação e política difíceis de seguir | Extrair responsabilidades após testes de caracterização |
| P2 | `global_jit.py:782`, `cpsat_polish.py:187`, `_trust_rank` e `improvement_key` usam objetivos diferentes | Uma fase pode propor algo que a seguinte rejeita por outro critério | Geradores sem autoridade de aceitação; objetivos auxiliares explícitos |
| P2 | `Lot`/`Segment` repetem `edd`, `original_edd`, `delivery_day`, datas cliente, produção e material | Custo de reconciliação e risco de explicação errada | Objeto de marcos canónico; aliases apenas nas fronteiras legadas |
| P2 | `frozen.py:33` protege o lote inteiro se começou antes do dia corrente | Uma lacuna passada pode permanecer por regra de proteção | Explicar a proteção; não reescrever história para melhorar indicadores |
| P2 | `pyproject.toml` da raiz diz Python >=3.10; backend/sintaxe exigem 3.12; dependências sem pin uniforme | Ambiente diferente pode falhar antes do solver | Unificar runtime e lock reprodutível, sem migração de versões neste plano |

Reprodução sintética dos comparadores: com entregas e setups iguais, um candidato
mais cedo com uma transferência adicional é preferido por `_trust_rank` e
preterido por `improvement_key`. Trata-se de teste das funções de comparação,
não de uma simulação física completa.

Contraexemplo do custo temporal: A começa em 100 e demora 60 minutos, terminando
em 160; B começa em 150 e demora 30, terminando em 180. O custo atual é 7 800
para A e 4 950 para B. B começa **e termina mais tarde**, mas recebe custo menor.
Logo, deslocar esse proxy para o primeiro lugar não basta para formalizar o pedido.

Os helpers antigos de GA/earliness em `optimizer.py` não devem ser todos tratados
como ativos: o módulo declara GA/MAP-Elites como experiências offline e a
orquestração já removeu o adiamento tardio. Mapear chamadas antes de remover
código; importar um helper não prova que participe do planeamento operacional.

### 3.1 A decisão sobre setups exige mais do que mudar um comparador

Vistos vetos locais também em `vns.py:63`, `campaign_tail.py:816`,
`transfer_consolidation.py:512/629` e `scheduler.py:3148`. Em
`scheduler.py:2125` existe uma exigência de igualdade de setups noutro percurso.
`priority_normalization.py:640` associa setup adicional a melhoria de entrega.
Na fase 1, classificar e migrar estes filtros: contagem/custo é preferência;
disponibilidade da equipa, duração e identidade da montagem são física e
permanecem obrigatórias. Uma vizinhança especializada em reduzir transferências
pode manter o seu foco, mas não vetar as propostas temporais de outras.

Atualizar em conjunto os testes que codificam a política antiga, as versões de
contrato e os documentos de regras. Não apagar testes de segurança; alterar
apenas a expectativa comercial que o utilizador substituiu explicitamente.

## 4. Contrato único de objetivos

### 4.1 Regras duras

Zero sobreposições de máquina/ferramenta; capacidade cumulativa de operadores e
equipas; calendário e ausências; setup físico correto; libertação de material;
elegibilidade; conservação exata de lotes/outputs; histórico e âncoras.
Todos os candidatos passam na validação do plano completo contra os inputs
canónicos. O Gantt nunca corrige estes problemas só no desenho.

As encomendas são identificadas com a ocorrência, mesmo quando SKU, data e
quantidade coincidem. Para melhorias do mesmo cenário, a comparação por encomenda
conserva quantidade pontual, atraso cliente/fábrica e envios de subcontratação.
Num cenário alterado, o plano antigo não se presume viável; é necessário
revalidá-lo e construir uma nova baseline quando deixa de ser utilizável.

### 4.2 Tornar “mais cedo” mensurável

Proposta para o contrato, a implementar e versionar:

1. Ordenar obrigações/lotes uma vez pela prioridade comercial canónica: prazo
   controlável, rutura, prioridade explícita e desempate estável. Manter o
   dimensionamento fixo durante esta procura.
2. Para cada lote móvel `i`, medir `S_i`, início de **produção**, e `F_i`, fim
   da produção completa, na cronologia real da fábrica. `R_i` é a sua abertura
   mínima executável, considerando material e fronteira de recálculo.
3. Comparar lexicograficamente o vetor
   `E = ((S_1-R_1, F_1-R_1), ..., (S_n-R_n, F_n-R_n))`.
   Assim, prioridades concorrentes têm uma resolução explícita: antecipar um
   lote menos prioritário não justifica adiar o início do mais prioritário.
4. Entre candidatos com entrega/`E` equivalentes, comparar setups físicos,
   minutos de setup, transferências e perturbação do plano.

Esta definição dá primazia ao início produtivo e evita comprar pontuação
simplesmente escolhendo uma máquina com menos minutos de processamento.
Antecipar um fragmento e atrasar muito o fim terá impacto no segundo elemento;
é uma escolha explícita, a validar com os casos de negócio antes de a consolidar.
Uma alternativa baseada na área de quantidade ainda por produzir teria outro
significado — maximizar produção acumulada cedo — e não deve ser introduzida
implicitamente como se fosse a mesma regra.

Não codificar um vetor longo como uma soma de pesos exponenciais. Na comparação
de candidatos usar tuplos. Em CP-SAT local, resolver o primeiro alvo que pode
melhorar mantendo limites para prioridades anteriores; avançar enquanto existir
orçamento. Se uma fase for apenas `FEASIBLE`, manter o melhor valor encontrado
como limite de não regressão, sem dizer que esse objetivo está otimizado.

Planos com falta de capacidade conservam o estado `best_effort` e os atrasos.
A primeira tarefa é recuperar serviço; a antecipação desempata soluções com
serviço admissível. Nunca relaxar `R` nem inventar stock para anunciar OTD 100%.

### 4.3 Datas

| Marco | Artigo normal | Subcontratado |
|---|---|---|
| Cliente `C` | Fonte da encomenda | Fonte da encomenda |
| Último envio `H` | Não aplicável | `C - lead útil` |
| Envio planeado `P` | Não aplicável | `H - buffer útil` |
| Prazo produtivo `U` | `C` | `P` |
| Material `R` | `C - 5 dias úteis` | `P - 5 dias úteis` |
| Alvo interno `I` | `U - buffer interno` | `U - buffer interno` |

Preservar a exceção industrial documentada das gémeas: material comum libertado
pelo output urgente (`min R`), com todos os marcos individuais conservados.
Os cinco dias não definem o tamanho da procura local, o horizonte total nem a
duração máxima de um lote. Um lote demasiado longo pode exigir diagnóstico de
capacidade; não se torna legal só porque o solver ficou sem tempo.

## 5. Algoritmo recomendado para pouco compute

O problema observado é principalmente de **máquinas paralelas não idênticas com
elegibilidade, ferramentas partilhadas, equipas de preparação, operadores,
calendários e lotes gémeos**, com lead externo de subcontratação. Não foi
identificado, neste pipeline ISOP, um grafo geral de múltiplas operações de rota
por OF. Evitar impor uma formulação de job shop multietapa sem esses dados.

A investigação em máquinas paralelas com servidores de setup apoia combinar
heurística construtiva com CP inicializado por essa solução. As condições do
artigo não incluem todas as regras Incompol e os tempos publicados não são
transferíveis para este sistema. [Heinz et al.](https://arxiv.org/html/2305.19888)

### 5.1 Construção por eventos

- Reutilizar primeiro uma baseline válida do mesmo snapshot, se existir.
- Num plano novo, ordenar pela política comercial e inserir cada lote/campanha
  no primeiro intervalo viável entre todas as máquinas elegíveis.
- Candidatos temporais: abertura de turno, libertação de material, fim de
  ocupação de máquina/ferramenta/equipa/operadores, fim de indisponibilidade e
  posições obtidas ao descontar a preparação necessária de um início produtivo.
- Intersectar calendários e perfis de capacidade. Evitar varrer todos os minutos
  do horizonte para cada candidato. Conservar suporte a intervalos fracionários
  e não eliminar fronteiras que possam conter uma solução legal.
- Montagem/afinação retida é estado do recurso, não um atributo suficiente do
  ID de campanha. Avaliar reservas entre setup e produção.

Uma construção greedy é uma boa solução inicial; não é garantia de antecipação
máxima. “Plano ativo” na teoria de RCPSP depende de hipóteses que não se
transferem integralmente para setups, gémeas e alternativas deste projeto.
[Kolisch](https://www.econstor.eu/bitstream/10419/155418/1/manuskript_344.pdf)

### 5.2 Pesquisa incremental com vizinhanças explícitas

| Ordem | Vizinhança | Utilidade |
|---|---|---|
| N0 | Antecipar mantendo restantes lotes e máquina | Fechar lacunas dentro do dia, entre turnos e dias |
| N1 | Inserir campanha/lote móvel em cada máquina elegível | Cobrir BFP186 mesmo cumprindo a entrega |
| N2 | Trocar/reinserir duas campanhas | Corrigir bloqueios simples de prioridade e de operadores |
| N3 | Reorganizar grupo acoplado por ferramenta/equipa/máquina | Cobrir BFP079 e dependências A→B→A |
| N4 | CP-SAT local sobre esse grupo e fronteiras | Resolver os casos que a inserção não consegue |

Começar com grupos de duas a seis campanhas, aproveitando a infraestrutura
existente; o tamanho é limite de procura, não regra industrial. Selecionar por
impacto e custo medido, com cobertura mínima das vizinhanças baratas antes de
gastar o orçamento nas transferências. Depois de cada aceitação, invalidar
apenas vizinhos afetados e voltar a testar intervalos libertados.

Conservar um conjunto de assinaturas visitadas e exigir melhoria estrita no
comparador canónico. A ausência de melhoria numa vizinhança não encerra as
restantes. Rejeições devem registar se o candidato é físico, comercialmente
inadmissível ou apenas pior pelo objetivo.

LNS baseada em conflitos fundamenta libertar um subconjunto relevante e manter
o resto fixo. Não é necessário implementar a maquinaria completa de explicações
do artigo para começar por um grafo de conflitos de recursos.
[Prud'homme, Lorca e Jussien](https://hal.science/hal-01087844v1/document)

### 5.3 CP-SAT local

- Intervalos opcionais para alternativas de máquina, com exatamente uma opção.
- `NoOverlap` para ocupação de máquina e ferramenta física.
- `Cumulative` para operadores e equipas de setup por grupo/turno; capacidade
  variável modelada por reservas fixas e calendário, sem “operadores médios”.
- Setups explícitos e sucessores/estado de montagem; não basta um atraso entre
  operações se a preparação também consome equipa e ferramenta.
- Manter trabalhos fora da vizinhança, incluindo dependências de fronteira e
  futuros usos da ferramenta. Não validar só o pequeno fragmento libertado.
- Passar o incumbent como hint, mas retê-lo também fora do solver. Hint não é
  garantia de solução, de proximidade ou de aceleração.
- Um worker inicialmente, domínio temporal reduzido e limite por chamada
  dentro do deadline exterior. O código já usa um worker; esse ajuste isolado
  não constitui uma melhoria nova.

As receitas oficiais suportam intervalos, recursos cumulativos e transições.
[OR-Tools 9.15 — scheduling](https://github.com/google/or-tools/blob/v9.15/ortools/sat/docs/scheduling.md)

Rolling horizon só deve entrar depois de medir necessidade: usar janelas
sobrepostas e reservas de fronteira, sem cortar lotes longos ou dependências de
subcontratação. Não congelar automaticamente toda a produção futura nem usar
a janela de material como corte rígido de cinco dias do problema.

## 6. Estrutura de código proposta

Extrair gradualmente, mantendo adapters e contratos públicos até migrar os
callers. Os nomes abaixo são proposta; não são módulos já implementados.

| Responsabilidade | Origem atual | Destino/convenção proposta |
|---|---|---|
| Política, admissibilidade e comparação | `priority.py`, `improvement.py`, ranks CPO | `scheduler/policy.py`; versão explícita |
| Marcos canónicos e calendário | `jit_policy.py`, `calendar.py`, `config/shifts.py` | Reutilizar; objeto imutável de marcos e conversões explícitas |
| Identidade/montagem e recursos | `setup_identity.py`, `resources.py`, helpers de alocação | Um estado de recursos consultável |
| Inserção e candidatos temporais | `scheduler.py`, `gap_filling.py`, `manual_move.py` | `scheduler/allocation.py`, com resultado verificável |
| Geração de movimentos | Cinco/seis reparadores atuais | `scheduler/neighborhoods/`; sem comparadores privados |
| Modelo local CP-SAT | `global_jit.py`, `cpsat_polish.py` | Builder reutilizável com âmbito explícito |
| Orquestração/último candidato | CPO + `improve_plan` + fecho | Um coordenador, reaproveitando `planning_control.py` |
| Validação/proveniência | `validation.py`, `canonical.py` | Reutilizar e separar invariantes de ranking |
| Gantt, movimentos e explicações | API, `explainability.py`, frontend | Projeções do mesmo candidato/snapshot |
| Experiências antigas | GA/MAP-Elites/surrogate no CPO | Área offline depois de confirmar referências |

Usar estruturas imutáveis para inputs/contrato e cópias apenas dos candidatos
alterados. Índices por máquina, ferramenta, grupo e intervalo evitam repetidas
varreduras globais. Cache de factos usa assinatura física **e** cenário,
calendário, configuração, proteção e política; invalidar na alteração efetiva.
Não remover a validação final para ganhar velocidade.

## 7. Orçamento e medições

O teto interativo existente de 60 s inclui preparação, cálculo, fecho e escrita,
com até 10 s reservados para concluir. Preservá-lo. Nenhuma subfase reinicia
o prazo. A primeira configuração experimental deve usar um núcleo e medir
memória real do processo; **512 MiB é alvo a avaliar, não requisito já provado**.

Distribuição inicial para benchmark, ajustável por evidência:

| Etapa | Orçamento indicativo dentro de 60 s |
|---|---|
| Snapshot, inputs e baseline | Até 5 s, se reutilizável; medir construção fria separadamente |
| N0/N1 e trocas baratas | Até 5 s iniciais |
| N2/N3/N4 | Tempo restante até ao início da reserva de fecho; 0,25–2 s por subproblema inicialmente |
| Fecho, validação, resposta e commit autorizado | Últimos 10 s reservados |

São hipóteses de tuning, não novos limites de negócio. Se não existir solução
válida, gastar a primeira fase a obtê-la; não fabricar um fallback. A procura
deve melhorar monotonamente o último candidato completo quando há tempo.

Medir em 1 núcleo e depois em 2: frio/quente, input atual, inputs históricos e
cenários de indisponibilidade. Recolher p50/p95 com pelo menos 20 execuções,
RSS, modelo construído, variáveis/intervalos, candidatos por vizinhança, tempo
de construção/solver/validação e relatório de paragem. Não somar timings de
fases inclusivas. Seed fixa não garante determinismo sob interrupção por relógio.

OR-Tools expõe tempo determinístico e workers; o parâmetro `max_memory_in_mb`
não é um teto geral fiável de CP-SAT nesta versão. Medir e, se necessário,
isolar o worker com limites do processo/sistema. Um worker morto devolve erro,
nunca sucesso nem commit parcial.
[Parâmetros oficiais 9.15](https://github.com/google/or-tools/blob/v9.15/ortools/sat/sat_parameters.proto)

## 8. Plano de implementação por entregas verificáveis

| Fase | Trabalho concreto | Condição de saída |
|---|---|---|
| 0 — Evidência | Congelar fixture destacada da revisão 90; guardar versões, datas, proteções e hash; mapear os 30 pedidos | Reproduções independentes da aplicação pública |
| 1 — Política | Introduzir comparador canónico com antecipação explícita; preservar guardas por encomenda; retirar veto a setups adicionais conforme decisão confirmada | CPO, melhoria e movimentos escolhem o mesmo candidato; contraexemplo do custo temporal e antecipação com setup extra cobertos |
| 2 — Falha atual | Incluir lotes pontuais na N1; eliminar dependência de `delivery_improves` como único benefício; reportar âmbito | BFP186 e versões renomeadas antecipam 385 min na fixture, sem perdas; nenhuma exceção de ID |
| 3 — Recursos/fecho | Unificar inserção, montagem e eventos; invalidar vizinhos após mudança; normalizar e validar candidato completo | Retirar um setup ou mover uma campanha aproveita o espaço legal libertado |
| 4 — Procura limitada | Integrar N2/N3/N4, hints e retenção do incumbent; medir antes de alargar rolling horizon | Mais casos resolvidos no mesmo orçamento, sem piorar regras nem retenção após timeout |
| 5 — Organização | Extrair módulos e mover experiências offline; consolidar datas/contagem física de setups; alinhar docs, UI e runtime | Call graph simples; comparador/validador únicos; sem redução de cobertura |
| 6 — Verificação/release | Benchmarks, regressão integral, API/UI, revisão do candidato e rollout controlado | Resultado validado e reversível; publicação/substituição só no âmbito autorizado |

Não estimar a duração pelo número de ficheiros. Fases 1–2 produzem uma correção
pequena demonstrável; 3–5 são refatoração mais ampla e dependem dos perfis e
contraexemplos. Cada fase deve poder ser revista separadamente.

### 8.1 Casos de aceitação

- BFP186 atual: oportunidade em alternativa encontrada mesmo com entrega pontual.
- BFP112: distinguir máquina disponível, equipa disponível, setup e produção.
- BFP082: mesma afinação retida sem setup redundante; remover setup liberta
  os 75 minutos quando o lote é móvel; proteção histórica permanece explícita.
- BFP080: capacidade libertada por outra mudança desencadeia nova pesquisa.
- VUL195/VUL174: reavaliar D8 após a mudança da campanha que o ocupava.
- BFP083: manter âncora e explicar o impedimento sem inventar falta de recursos.
- BFP079: comparar permanecer/transferir no contexto completo; OEE diferente,
  recursos, lotes deslocados e setups considerados, sem preferência por ID.
- BWI003/BFP186: equipa por turno; uma antecipação com setup adicional deve ser
  aceite quando melhora o objetivo canónico sem prejudicar entregas ou física.
- Gémeas, eco-lot e subcontratação: quantidades e `C/H/P/U/R/I` coerentes;
  stock coproduzido não inventa entrega.
- Turno noturno, pausas, feriados, sábado extra, ausência devolvida, capacidade
  zero e fim exclusivo dos bloqueios: mesmo resultado em todos os percursos.
- Timeout em cada fase, cancelamento, falha de escrita, revisão concorrente,
  reaplicação idempotente e reinício: preservar último candidato válido/recibo.

Os exemplos históricos têm datas protegidas no plano atual. Reproduzi-los com
clock e snapshot da época em testes; não libertar histórico real para os fazer
“passar”. Repetir casos com nomes trocados e lotes adicionais.

### 8.2 Oráculo e critérios de conclusão

Para 2–8 lotes e 1–3 máquinas, construir um oráculo independente enumerando
ordens/atribuições e inícios numa grelha pequena, ou um modelo exato sem os
helpers de alocação atuais. Comparar física, objetivo e conservação.
Testes de propriedade: acrescentar um bloqueio não cria capacidade; aumentar
capacidade não invalida o plano anterior; dividir segmentos não altera peças;
renomear IDs não altera viabilidade; melhoria aceite nunca piora o contrato.

Uma resposta de “não é possível” exige prova no modelo/âmbito descrito.
`FEASIBLE` não prova ótimo; `UNKNOWN` não prova inviabilidade. Mesmo
`INFEASIBLE` local só responde com os restantes trabalhos fixos.
[Estados CP-SAT](https://developers.google.com/optimization/cp/cp_solver)

Critério operacional: zero violações físicas/quantitativas/material e zero
oportunidades admissíveis **nas vizinhanças que foram integralmente percorridas**.
Se o orçamento terminar, reportar pesquisa parcial e cobertura; não anunciar
“sempre no primeiro instante globalmente possível”. Essa garantia absoluta para
este problema combinatório não decorre de uma heurística nem de baixo compute.

## 9. O que foi verificado nesta intervenção

- 204 testes existentes passaram: contrato, alternativas, prova de montagem,
  subcontratação, retenção de candidatos e janela. Tempo: 2,20 s; uma warning
  já emitida por FastAPI/Starlette sobre `httpx`.
- Snapshot da revisão 90: zero violações nos validadores executados, incluindo
  origem, conservação e âncoras; zero violações da janela de material.
- OTD guardado 96,5%, OTD-D 99,1%, sete lotes atrasados. Física válida não
  significa entregas perfeitas, e este plano não prova que esses sete atrasos
  sejam globalmente inevitáveis.
- Reprodução local e benchmark acima; nenhuma gravação do plano, recálculo
  publicado, alteração do algoritmo, dependência ou servidor.
- Não executada a suíte integral nem benchmark estatístico de cold-start;
  esses trabalhos pertencem à implementação. Resultados antigos de milhares
  de testes noutras conversas não são apresentados como execuções desta auditoria.

Artefactos: [contrato](../AGENTS.md),
30 pedidos e padrões (artefacto local não incluído),
[fontes e comparação de algoritmos](auditoria-solver-2026-10-02/pesquisa.md),
[reprodução read-only](auditoria-solver-2026-10-02/reproduzir_auditoria.py).

## 10. Execução das fases 1 e 2 (02/10/2026)

Implementado no working tree, sem gravar plano, sem recálculo publicado.

**Fase 1 — política**

- `improvement.py`: `PlanFacts.anticipation` e `anticipation_key` implementam o
  vetor `E` do §4.2 (início e fim produtivos por lote, pela prioridade comercial
  canónica `lot_priority_key`). `improvement_key` = entrega → `E` → setups →
  minutos de setup → transferências → perturbação. O proxy
  `production_time_cost` saiu da comparação. `CONTRACT_VERSION = 2`.
- Veto de setups retirado de `no_loss_verdict` e de
  `_accept_zero_slack_repair`; o ramo "setup_tradeoff" de
  `priority_normalization` deixou de ser atingível e foi removido.
- CPO: `_is_better_candidate`, `_remember_trusted_result`, o beam de
  left-shift e o motivo de rejeição usam o mesmo `E` quando os planos têm os
  mesmos lotes; com lotes diferentes mantém-se o rank por score (o vetor por
  lote não tem significado entre dimensionamentos diferentes). O mesmo
  critério aplica-se em `replan/jobs._prefer_no_loss_plan`.
- `shift_exchange` é aplicado diretamente por CPO, scheduler e recálculo; o
  veto de setups escondia que podia aplicar trocas piores pelo `E`. Passou a
  exigir ganho canónico; trocas admissíveis sem ganho ficam como trade-off
  descrito ("antecipacao atrasa um lote de maior prioridade comercial").
- Mantidos por serem de outra natureza (ver AGENTS §1.5):
  `transfer_consolidation`, `campaign_tail`, igualdade de setups em
  `_repair_interrupted_tool_campaigns`. `vns.py` já ordenava tempo antes de
  setups.

**Fase 2 — vizinhança N1**

- `alternative_repair.anticipation_proposals`: cada campanha móvel, por
  prioridade, em cada máquina elegível, restantes fixas; propõe quando o vetor
  da própria campanha melhora, melhor máquina primeiro; não exige ganho de
  entrega. Respeita a fronteira de recálculo (dias bloqueados em todas as
  máquinas) e nunca move lotes protegidos. Registada como segundo gerador
  (`alternative_anticipation`), logo após a compactação N0.

**Resultado na revisão 90 (D15, 1 núcleo, ciclo real `improve_preserving_protected_lots`)**

- A N1 encontra as duas oportunidades do plano de referência: BFP186
  (`run_BFP186_PRM039_1` → PRM039, início −385 min, o caso da auditoria) e uma
  que a auditoria não mediu: `run_BFP171_PRM031_0__replanned_1` → PRM039, mesmo
  início, fim −240 min.
- Competem pela mesma janela. BFP171_40 é mais prioritário (prazo 40, rutura 40)
  que BFP186_47 (prazo 40, rutura 47); pelo `E` interleaved do §4.2 vence o
  BFP171 e o BFP186 deixa de ter colocação mais cedo. **O critério de saída
  "BFP186 antecipa 385 min" não se verifica no ciclo completo**; verifica-se a
  deteção. Ver §10.1.
- Após a compactação: VUL203_43 −2348 min; BFP079_47 +296 min (menos
  prioritário, prazo 47). Setups físicos 195→196 (+60 min), transferências
  13→13, OTD 96,5 %, OTD-D 99,1 %, 7 atrasados — iguais; 0 violações.
- 9,9 s (orçamento 10 s), paragem `search_limit` em `tool_transfers`, pico
  RSS 122 MiB. Com 30 s: mesmos movimentos. A passagem completa da N1 sobre o
  plano de referência demora ~2,2 s.

### 10.1 Decisão pendente

O §4.2 compara `(S_1, F_1, S_2, F_2, …)`. Neste snapshot isso dá primazia ao
fim do lote mais prioritário sobre o início de um menos prioritário. A
alternativa "todos os inícios primeiro, depois os fins" escolheria o BFP186,
mas é vulnerável a começar um fragmento cedo e acabar muito tarde (aviso do
próprio §4.2). Manteve-se o texto do plano; a escolha é de negócio.

O mesmo rigor aparece entre lotes com o mesmo prazo: o desempate de
`lot_priority_key` (prioridade explícita, alvo, quantidade maior, id) decide.
Exemplo coberto em `test_mounted_preemptive_allocation`: uma transferência que
poupa um setup e antecipa um lote 60 min é rejeitada porque atrasa 30 min outro
lote do mesmo dia com maior quantidade. Confirmar se esse desempate é o
pretendido ou se lotes com o mesmo prazo devem ser comparados em conjunto.

### 10.2 Testes alterados (política antiga substituída)

`test_improvement_contract` (veto e chave), `test_improvement_cycle`,
`test_priority_normalization_setup_tradeoff`, `test_shift_exchange`,
`test_mounted_preemptive_allocation` (prioridade explícita para preservar o
objetivo do teste) e dois testes do CPO (proxies agregados como desempate do
vetor). Novos: `test_anticipation_neighbourhood` (IDs trocados, fronteira,
proteção) e contraexemplo do custo temporal.

## 11. Segunda ronda: diagnóstico global e vizinhanças N2/N3 (02/10/2026)

**Diagnóstico do plano ativo (revisão 90, D15, 153 lotes móveis)**

- Nenhum lote começa antes de `R`. 92 começam no dia útil de `R`, 34 um dia
  depois, 28 a dois ou mais dias.
- Todos os que esperam estão numa máquina elegível sem minutos livres entre
  `R` e o início: a espera vem da sequência, não de lacunas
  (`left_shift_opportunities=0`).
- Os 6 lotes móveis atrasados estão na PRM042 (sem alternativa): procura com
  `U=53` de 11 178 min contra 6 060 min disponíveis entre `R=46` e `U`; o lote
  JDE002 0060-1 sozinho precisa de 6 424 min (> 5 dias úteis). É falta de
  capacidade dentro da janela, não defeito de algoritmo. Só noite, sábado ou
  exceção à janela o resolvem — decisão de negócio.
- Auditoria operacional: uma inversão evitável (VUL203 atrás de BFP079 na
  PRM039), corrigida pelo ciclo.

**Código**

- `alternative_repair.group_reinsertion_proposals(size=k)`: retira k campanhas
  consecutivas de uma máquina e reinsere-as em todas as ordens e máquinas
  elegíveis; só grupos com folga (alguma campanha depois do seu chão).
  Registadas como `pair_reinsertion` (N2) e `triple_reinsertion` (N3).
- Desempenho: `_schedule_run_earliest` projetava e fundia o calendário com
  ~550 reservas do plano em cada janela pedida (88 % do tempo). Agora projeta
  uma vez antes de juntar as reservas; uma vez por vizinhança. Resultados
  idênticos na pesquisa exploratória; N1 1,7→0,3 s, pares 10,0→1,8 s.

**Resultado (ciclo real, 1 núcleo)**

| Orçamento | Movimentos | Lotes alterados | Setups | Transferências | Entregas |
|---|---|---|---|---|---|
| 10 s (atual) | 5 (N0 2, N1 1, N2 2) | 10 | 195→196 | 13→16 | iguais |
| 30 s | 7 (+N3) | 18 | 195→195 | 13→16 | iguais |

Inclui BFP186 −385 min, JTE001 −385, JTE003 −385/−815, BFP202 −278 e, com
30 s, BFP080 (prazo 43) ~−1 975 min. Soma das esperas dos lotes móveis
5 735 h → 5 678 h com 10 s (−1 %): a maior parte da espera é estrutural.
Após o ciclo, pesquisa exploratória exaustiva com 1 e 2 campanhas: zero
ganhos; com 3 campanhas: 3 ganhos (os que N3 aplica com mais orçamento).

Regressos A→B→A restantes (2) são justificados: poupar o setup atrasaria um
lote mais urgente, ou o material do segundo lote ainda não está libertado.

**Pendente:** o limite de 10 s em `frozen.IMPROVEMENT_BUDGET_S` (compactação
após libertar capacidade, movimento manual) e em `cpo.optimizer` impede N3
neste snapshot; o recálculo completo já usa o tempo restante até à reserva de
fecho. Aumentar é decisão de latência. O custo dominante restante é a
compactação N0 após cada movimento (~2–3 s): fase 3.

## 12. Terceira ronda: fases 0, 3, 4, 5 e 6 (03/10/2026)

**Fase 0 — evidência congelada.** `scripts/freeze_snapshot_fixture.py` copia um
snapshot (leitura `mode=ro`) para `tests/fixtures/private/` — fora do git, por
conter dados do cliente — e grava um manifesto sem dados em
`tests/fixtures/snapshots/` (hash, revisão, data, contagens). Congeladas:
revisão 90 (hash `2a7d9d7c…`, igual à auditoria) e as revisões 82, 85 e 87 dos
backups `before-bfp082-idle`, `before-bfp112-early` e `before-bfp079`.
`tests/snapshot_fixture.py` permite repetir com o relógio da época (provas de
proteção posteriores retiradas só da cópia) e renomear lotes/campanhas
preservando a ordem. Os testes saltam se a fixture privada faltar.

**Casos §8.1** (`tests/test_acceptance_cases.py`, relógio da época):

| Caso | Resultado |
|---|---|
| BFP082 (rev. 82, 22/09) | N1 coloca `_8` às 17:29 do dia 5 (−75 min), setup 0 pela montagem do `_0` protegido |
| BFP082 (data real) | protegido; explicado como `historical_lot_locked`, zero oportunidades falsas |
| BFP112 (rev. 85, 21/09) | setup no dia 4 às 11:50, produção 30 min depois — igual à reparação manual |
| BFP083 (rev. 87, 22/09) | âncora mantida; explicação corrigida para `manual_anchor` (antes dizia histórico) |
| BFP080 (rev. 87) | antecipa usando capacidade libertada por outros movimentos |
| BFP079 (rev. 87) | "ficar" vs "transferir" comparados pelo `E` completo; o ciclo encontra um plano canonicamente melhor que a reparação manual |
| VUL195/174 D8 | depois de o BFP079 sair, o D8 é reaproveitado — por lotes mais urgentes (prazo 14), não pelos VUL (15) |
| BFP186 / renomeados (rev. 90) | N1 encontra −385 min; resultado do ciclo domina canonicamente esse candidato |

**Oráculo §8.2** (`tests/oracle.py`, sem helpers de alocação): em 200 instâncias
aleatórias (2–4 lotes, 1–2 máquinas, ferramenta e equipa partilhadas,
montagem retida), o validador aceita sempre a física do oráculo e o ciclo
nunca o ultrapassa. Ótimo atingido: 169/200 inicialmente → 186/200 com grupos
acoplados por ferramenta/equipa → 198/200 com N4, medido contra um oráculo
com a regra de setup do alocador. Ver lacunas abaixo.

**Fase 3 — defeito corrigido:** a compactação N0 no recálculo com histórico
não recebia a fronteira de recálculo e tentava mover trabalho para dias
passados; a proposta inteira era rejeitada (`machine_down/tool_down`). Agora
os lotes móveis recebem `max(R, dia de recálculo)` só para a alocação. No caso
BFP082: 9→0 propostas inválidas, ciclo 2× mais rápido. Compactação por máquina
afetada medida (−18 %) e não adotada.

**Fase 4:** N2/N3 passam a agrupar utilizações consecutivas da mesma máquina,
da mesma ferramenta física e da mesma equipa de setup. N4
(`scheduler/local_cpsat.py`): grupo acoplado até 6 campanhas (+ sucessores
com montagem retida), CP-SAT lexicográfico com intervalos opcionais,
`NoOverlap` por máquina/ferramenta e `Cumulative` por equipa, 1 worker,
0,25 s por solve; o alocador materializa e o avaliador decide.

**Fase 5:** `optimizer.py` 4 926 → 3 594 linhas: GA/MAP-Elites movidos para
`cpo/offline_ga.py`; apagadas 4 reparações LNS e 10 auxiliares sem
chamadores, e as reparações de atraso ("JIT delay") com os 4 testes que só
as testavam (contrariam o contrato; versões disponíveis no commit `HEAD`).
`scheduler/policy.py` com a medida canónica (`POLICY_VERSION`). Página de
Regras corrigida (P01 dizia o contrário do código; P03 apresentava um aviso
como limite). Python ≥3.12 na raiz e no `uv.lock`. Docstrings e
`CLAUDE.md` atualizados.

**Fase 6 — benchmark** (`scripts/benchmark_solver.py`, 20 execuções a frio,
rev. 90, orçamento 10 s; resultados em `execucao/`): p50 11,5 s, p95 11,8 s,
RSS 128 MiB; 1 e 2 núcleos iguais; 2 resultados distintos em 20 (corte por
relógio). Suíte integral verde.

### 12.1 Não feito e porquê

- **Setup repartido por fecho de turno/dia:** o contrato permite-o, o alocador
  exige setup + 1 min de produção na mesma janela de turno. Explica 11 dos 14
  desvios do oráculo (15–75 min). Regra física da fábrica: decisão do
  utilizador antes de mudar o alocador central.
- **Mover alocador e vizinhanças para módulos próprios:** outra sessão tem
  testes que substituem funções em `alternative_repair`; mover em paralelo
  enfraqueceria esses testes sem falhar. Coordenar primeiro.
- **N4 não modela montagem retida** (2/200 casos do oráculo; um com sucessor
  retido de outro grupo).
- **Orçamento de 10 s** na compactação/movimento manual/CPO: o ciclo excede
  ~1,1 s (absorvido pela reserva de fecho). Aumentá-lo é decisão de latência.
- **Rollout:** nada foi publicado nem gravado no plano ativo; requer
  autorização explícita.
- `backend/pyproject.toml` não declara ortools/scikit-learn (o Docker usa
  `requirements.txt`); não alterado para não mexer em dependências.
- **Determinismo:** no modo `normal`, o ciclo do CPO termina perto do teto de
  10 s; sob carga, o relógio corta antes e o resultado muda.
  `test_deterministic_seed` passou a exigir igualdade só quando nenhuma
  execução foi cortada pelo relógio (salta e explica caso contrário). Um
  orçamento determinístico (`max_evaluations`) no CPO resolveria, à custa de
  menos melhoria: decisão pendente.

### 12.2 Decisões do utilizador (03/10/2026)

- Setup novo e primeiro minuto produtivo na mesma janela de turno (regra
  atual do alocador mantida; AGENTS §4 atualizado). Os 11 desvios do oráculo
  que dependiam de setups repartidos deixam de ser desvios do contrato.
- Orçamento do ciclo: 10 s mantidos.
- Desempate com o mesmo prazo e rutura: maior quantidade primeiro (regra atual).
- Commit de todo o working tree, exceto dados reais de cliente: cópias da
  base de dados em `data/` (agora ignoradas) e a cópia integral do plano
  `docs/auditoria-browser-2026-10-02/live-before.json`.

### 12.3 Pré-visualização e decisões de 05/10/2026

- Pré-visualização da compactação do plano ativo (rev. 90, proteção a 05/10),
  sem gravar: 0 violações, nenhuma encomenda prejudicada, OTD/OTD-D iguais.
  A cadeia de movimentos mostrou trocas extremas pela regra estrita (ex.:
  VUL203 +30 min contra BFP192 −2 dias).
- **Tolerância de 60 min** (`ANTICIPATION_TOLERANCE_MIN`, `POLICY_VERSION`
  `earliest-lexicographic-tolerant-v2`): aplicada no ciclo, CPO, recálculo,
  troca de turnos e filtros N1–N4. Com ela, as perdas por movimento ficam
  abaixo de 1 h salvo quando um lote mais urgente ganha ≥1 h. O oráculo passou
  a verificar que nenhum plano enumerado é preferível ao do ciclo.
- **Orçamento:** a outra linha de trabalho ("Bloco 39") substituiu os 10 s
  fixos pelo tempo restante menos a reserva; confirmado pelo utilizador.
  Compactação da rev. 90 ≈ 50 s.
- **Segurança:** o túnel `trycloudflare` expõe a API sem autenticação
  (`/api/data/segments` devolve o plano completo; escrita não testada).
  O utilizador decidiu manter o link aberto por agora; risco registado.

### 12.4 Recálculo integral confirmado em 06/10/2026

O plano ativo na revisão 91 continuava a apresentar as mesmas posições de
vários lotes de setembro. A implementação então publicada congelava 53 lotes
porque tinham segmentos anteriores ao dia corrente da fábrica (D19), não
porque existisse prova de execução. Melhorar apenas o restante plano não
atualizava essas posições no Gantt. A BFP083 tem, adicionalmente, uma âncora
manual em 29/09 às 15:30 na PRM031: não se trata de capacidade física em falta.

Decisão explícita: "Recalcular plano" deve voltar a pesquisar desde D0.
Compactação e otimização integral recebem o mesmo âmbito interno, libertando
apenas a proteção derivada da passagem do tempo. Não se apagam decisões manuais,
observações nem oferta comprometida, nem se inventam registos de execução.
Validação, robustez e relatório final usam o contexto do candidato, não as
provas de proteção antigas do plano substituído. O orçamento não foi alterado.

A persistência exige uma operação preparada pelo coordenador com esse âmbito;
um campo enviado pelo cliente ou colocado no snapshot não o autoriza. Guardar
outros planos, restaurar e os restantes escritores mantêm a proteção existente.
As aprovações continuam a aplicar exatamente o candidato apresentado, sem novo
cálculo; a versão do contexto de proteção invalida candidatos anteriores.

Regressões: `tests/test_full_horizon_recalculation.py`. Ensaio real isolado:
`scripts/full_horizon_acceptance.py` e
`scripts/audit_full_horizon_recalculation.mjs`, com aplicação no navegador,
gravação, igualdade com a pré-visualização e recuperação após reinício.
Esta decisão remove o impedimento de pesquisa do passado; não prova que a
pesquisa limitada encontra todas as antecipações possíveis.

Ensaio pelo botão real, na cópia da revisão 91, aplicado e recuperado como
revisão 92 privada (não corresponde a uma aplicação em produção):

| Caso | Início produtivo obtido | Observação |
|---|---|---|
| BFP082 / 1092262X100, primeira necessidade | 17/09, 09:15 | Entrou na pesquisa desde D0 |
| BFP080 / 1065170X100, prazo D19 | 28/09, 09:15 | Antecipação no próprio dia |
| VUL195 / 8750705018 | 25/09, 09:12 | Antecipado de D11 para D8 |
| VUL174 / 8750792794 | 25/09, 12:53 | Antecipado de D11 para D8 |
| BFP114 / 1694825X040 | 24/09, 22:41 | Dentro da libertação e das regras físicas |
| BFP083, lote gémeo D15 | 29/09, 15:30 | Âncora manual conservada |

O ensaio demorou 51,62 s até à confirmação; é uma execução, não uma média nem
um p95. A melhoria ficou parcial por orçamento. Verificações: quantidades
conservadas, nenhuma encomenda prejudicada, zero conflitos físicos, fixações
preservadas; igualdade dos segmentos/lotes aplicados com o candidato apresentado
e recuperação exata após reinício. Navegador a 390 e 1440 px sem erros JavaScript.

A primeira regressão integral revelou dois testes anteriores dependentes de
`hoje`: cancelamento para obter um plano vazio e transporte do relatório de
melhoria. Ambos falharam também na árvore original, em 06/10. Os respetivos
ensaios passam agora com o relógio explícito em D0 da fixture; não se alterou
o comportamento do simulador nem se relaxou a proteção das outras rotas.

Validação final da árvore isolada: backend integral **2796 passaram, 2
ignorados, 1 xfail** (673 s); os 3 casos adicionais de interrupção/observações
também passaram (13 regressões novas no total). Frontend **22 testes de lógica
e 190 de interface passaram**; Ruff, ESLint, TypeScript e build passaram.

Publicação: backend reiniciado em 06/10/2026 às 12:20 CEST, mantendo portas e
túnel. Navegação pública de leitura nas seis páginas a 390/1440 px passou,
sem erros JavaScript ou API; 75 regressões de recálculo/persistência passaram
novamente na árvore integrada. Backup consistente em
`/tmp/incompolinho-full-horizon-release-backup-20261006/`.
O plano de produção permaneceu na revisão 91, snapshot
`846542ae2b5448238ac2f88217761dd6`, com SHA-256 do payload
`a59b81cefcff12e75818072ce7c7a10fd4c50af1dde1c3737d2407ae8d033e65`
inalterado. A publicação é de código: atualizar o Gantt exige executar e
aprovar o recálculo, não houve substituição automática do plano ativo.

## 13. Pesquisa de candidatos em ISOP real (08/10/2026)

**Problema.** No modo `normal`, a pesquisa de candidatos recebe cerca de 25 %
do tempo depois da construção (8 a 12 s). Cada candidato custa uma construção
completa (5 a 8,5 s), por isso nas revisões 87 e 90 terminavam 0 de 47 em 60 s.
Em 180 s terminavam 6, todos empatados com a base, e nenhum era aceite.
Desligar só a pesquisa não chega: o polimento CP-SAT ocupa a mesma fatia e
também esgota o tempo.

**Decisão.** Instâncias com 50 ou mais operações saltam a pesquisa e o
polimento (`advisory_search_max_ops` em `MODE_CONFIG["normal"]`). O ciclo de
melhoria recebe esse tempo.

**Medição.** Antes e depois, 3 repetições, 60 s, 1 núcleo por corrida:

| Caso | Melhoria | Lotes mais cedo / mais tarde | Antecipação total | Encomendas piores | Setups |
|---|---|---|---|---|---|
| rev90 (recálculo) | +8 a +10 s | 3 / 0 | −202 a −261 min | 0 de 786 | iguais |
| rev87 (horizonte completo) | +10 a +11 s | 4 a 7 / 0 | −202 a −922 min | 0 de 786 | iguais |

O modo `quick` dá exatamente o mesmo plano.

**Pendente.** `validate_plan` consome cerca de 38 % do tempo de construção
(cProfile). É a próxima alavanca, porque também torna cada movimento de
melhoria mais barato.
