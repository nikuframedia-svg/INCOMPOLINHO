# INCOMPOLINHO — contrato de planeamento e de trabalho

Contrato interno, revisto em 02/10/2026. Aplica-se ao repositório inteiro.
Pedido orientador: **produzir o mais cedo possível dentro da janela de cinco
dias úteis, com lógica verificável no Gantt e baixo consumo de compute**.

## Fontes e estado

- Este ficheiro define o contrato a respeitar em alterações futuras. Não afirma
  que o código atual já o implementa integralmente.
- [Auditoria e plano](docs/plano-solver-2026-10-02.md) distinguem comportamento
  observado, defeitos reproduzidos, decisões confirmadas e implementação proposta.
- [Pesquisa](docs/auditoria-solver-2026-10-02/pesquisa.md) fundamenta a escolha
  algorítmica; [30 pedidos](docs/auditoria-solver-2026-10-02/ultimos-30-pedidos.md)
  preservam a origem dos requisitos.
- Instruções explícitas do utilizador prevalecem. `CLAUDE.md`, `logic.md`,
  `plansistem.logic` e documentos anteriores contêm descrições históricas:
  não copiar deles objetivos contraditórios, resultados antigos ou constantes
  que já são configuráveis. Em particular, não reintroduzir produção tardia/JIT
  como objetivo, GA como caminho operacional ou a promessa de OTD 100% universal.

## 1. Prioridades: admissibilidade antes da otimização

1. **Admissibilidade obrigatória:** conservar procura, produção, identidades,
   recursos, calendários, material, histórico protegido e posições manuais.
   **Desde 13/10/2026 também o lote económico numa só produção (§2), regra
   dura acima da entrega a tempo** (decisão do Luís): a verificação
   `lot_split` está nas métricas duras do gate. Se o lote atrasa outra
   encomenda, move-se o lote inteiro; nunca se parte para salvar uma entrega.
   Custo 1: pode atrasar uma entrega quando o lote não cabe inteiro antes do
   prazo e a janela por entrega a salvava. Visto num ensaio de 13/10
   (revisão 128, avaria grande da PRM031 a 16/10): uma entrega do dia 21
   (BFP188, 800 peças) ficou pronta no dia 22. No ensaio final de 14/10
   (avaria da PRM031 de 19/10 a 09/11) não houve atraso novo: só a encomenda
   que já estava atrasada (CF589). Custo 2: mais stock e produção mais cedo
   (sem limite de cobertura, §2), medido por cenário:
   - carga de ISOP nova de 13/10 (ensaio de 14/10 numa cópia da revisão
     128): stock +39% em peças × dias (40,5 → 56,3 milhões) e 44 entregas
     prontas com mais de 30 dias de antecedência (antes 0); 445 → 178
     setups; 1 encomenda atrasada antes e depois;
   - recálculo F1 do golden master (base 6c303e9): stock +39% (42,4 → 59,1
     milhões) e 52 entregas com mais de 30 dias (antes 0); 478 → 184 setups.
   Um plano fisicamente inválido nunca é candidato operacional.
2. **Compromissos de entrega:** respeitar os prazos quando viáveis. Ao melhorar
   um plano válido do mesmo cenário, nenhuma encomenda individual pode perder
   quantidade no prazo ou ganhar atraso; preservar também os marcos externos.
   Um KPI agregado não compensa uma encomenda prejudicada.
   **Entrega medida por encomenda no comparador (decidido a 11/10/2026,
   Fase B3).** Entre planos admissíveis, a entrega ordena-se por encomenda,
   lida da mesma prontidão `material_quantities.delivery_readiness` (via
   `improvement.order_service`): prioridades explícitas das encomendas
   atrasadas, depois número de encomendas atrasadas, encomendas nunca
   prontas, total de dias de atraso das encomendas e só depois falhas e
   faltas de OTD-D e expedição para subcontratação
   (`priority.delivery_priority_key` com `priority.order_delivery_metrics`).
   O atraso por lote (`tardy_count`, `total_tardiness`, OTD de lotes) é só
   indicador: um ganho nele não paga um plano mais tarde. O ciclo de
   melhoria, as reparações de máquina alternativa, a troca de turno e as
   ordenações do CPO usam esta medida; um score sem as métricas por
   encomenda (`priority.with_order_delivery`) é comparado pela regra antiga
   dos dois lados, nunca misturado.
3. **Primeiro objetivo entre candidatos admissíveis: antecipação real.**
   Escolher o primeiro início produtivo viável após a libertação de material,
   considerando todas as máquinas elegíveis e os recursos partilhados. Entre
   lotes concorrentes, usar a prioridade comercial canónica, não a conveniência
   de uma campanha. Conclusão produtiva desempata inícios iguais.
   Confirmado em 03/10/2026: com o mesmo prazo e a mesma rutura, a maior
   quantidade a entregar tem prioridade (`lot_priority_key`); o id do lote é
   só o desempate final estável.
   **Tolerância (05/10/2026):** diferenças inferiores a 60 min não decidem
   entre lotes. Um lote só pode começar ou acabar 1 h ou mais tarde se um lote
   mais urgente ganhar pelo menos 1 h. Cada melhoria é comparada com o plano
   atual e com o de partida (`policy.anticipation_compare`,
   `improvement.improvement_better`, `improvement.regresses_reference`).
   **Setups dentro da tolerância (regra 2, decidida a 10/10/2026, contrato
   v3):** quando nenhum lote muda 60 min ou mais, decidem primeiro menos
   setups físicos e depois menos minutos de setup; só então os minutos exatos
   (`policy.tolerant_tiebreak`). Assim, uma ferramenta montada continua a
   produzir mesmo havendo um lote mais urgente à espera da máquina, desde que
   esse lote perca menos de 60 min; com 60 min ou mais, o lote urgente passa
   à frente e paga-se o setup. A regra de não perda por encomenda (ponto 2)
   continua acima de tudo (`improvement.CONTRACT_VERSION = 3`,
   `policy.POLICY_VERSION = per-output-earliest-lexicographic-tolerant-setups-v3`).
   **Medida por entrega (Fase B3, policy v3):** a antecipação mede-se por
   output, não por lote. Num lote que cobre várias entregas do mesmo lado,
   cada entrega é um elemento próprio: as suas peças são atribuídas FIFO por
   quantidade acumulada (a regra de `delivery_readiness`), começa no
   primeiro minuto produtivo que faz peças suas e acaba quando a última peça
   sua fica feita, isto é, na sua prontidão. O excedente económico e o stock
   coproduzido não são elementos nem mexem na janela de nenhuma entrega.
   Os elementos ordenam-se pela prioridade da própria entrega
   (`priority.output_priority_key`, com a quantidade da entrega ao cliente).
   Um lote com no máximo uma entrega por lado continua a ser um só elemento,
   como na v2 (`policy.output_windows`, `policy.anticipation_key`). As
   pré-verificações das vizinhanças (N1–N4 e lote inteiro) usam este mesmo
   vetor, restrito aos lotes que movem.
4. **Objetivos seguintes:** menos setups físicos/minutos (já decididos dentro da
   tolerância, ponto 3), menos transferências, menor alteração do plano. Não
   podem fazer perder uma antecipação de 60 min ou mais.
5. **Decisão explícita de 02/10/2026:** uma antecipação pode aumentar o número
   ou os minutos de setup se preservar entregas e restrições físicas. Esta
   decisão substitui a antiga proibição automática de setups adicionais.
   Mais setups, por si só, não rejeitam uma antecipação nem exigem aprovação
   adicional. Se o objetivo temporal empatar, preferir menos setups/minutos.
   Removido do contrato na versão 2 (`improvement.CONTRACT_VERSION`). Filtros
   que permanecem por serem de outra natureza: `transfer_consolidation` só
   propõe reduções de setups/transferências (foco da vizinhança, não veta as
   outras); `campaign_tail` é a exceção configurada por família de setup;
   `_repair_interrupted_tool_campaigns` exige setups iguais como prova de
   conservação de uma rotação física.
6. **Robustez é só informação. Decidido em 07/10/2026.** Nunca ordena
   candidatos, nunca bloqueia nem pede aprovação e nunca altera o plano.
   Depois de cada gravação do plano corre sozinha em segundo plano (modelo v5,
   perfil `standard`, 500 cenários) sobre os próximos 10 dias úteis a partir
   de hoje ou do dia de congelamento; pausa enquanto há planeamento a correr.
   `PP1_AUTO_ROBUSTNESS=0` desliga o cálculo automático. Planos que antes
   paravam só por "robustez não avaliada" (incluindo movimentos manuais com
   validações limpas) passam a aplicar-se diretamente.

Não criar exceções algorítmicas por BFP, SKU, cliente, data, imagem ou ID de lote.
Esses valores só pertencem aos dados mestre e às fixtures de regressão.
Não mudar silenciosamente o contrato para resolver uma ocorrência.

## 2. Datas e janela de material

Usar o calendário da fábrica e o fuso configurado, atualmente Europe/Lisbon.
Índice de coluna, dia de calendário, dia útil e minuto produtivo são conceitos
distintos. Não subtrair cinco índices nem cinco períodos de 24 horas para obter
cinco dias úteis. Intervalos de recursos são `[início, fim)`.

Para cada necessidade/output:

- `C`: compromisso de entrega ao cliente, imutável durante a alocação.
- Artigo normal: prazo controlável `U = C`; referência de material `M = C`.
- Subcontratado: último envio compatível com cliente `H = C - lead útil`;
  envio planeado `P = H - buffer útil`; `U = M = P`.
- Libertação simulada `R = M - 5 dias úteis`.
- Alvo interno `I = U - buffer interno`: nunca substituir `C` ou `R` por `I`.
- Setup e produção não podem começar antes de `R`. Execução também respeita
  D0, a data de recálculo e todas as reservas/fixações aplicáveis.
- Preservar marcos negativos para diagnosticar procura vencida; não inventar
  produção executada em datas anteriores ao início permitido.
- O limite de cinco dias é uma antecedência máxima de material; não é uma
  ordem para esperar nem um horizonte de otimização limitado a cinco dias.

Num ciclo gémeo confirmado, a regra industrial existente partilha material
entre as duas entregas que formam o ciclo (a que o controla e a sua par):
`R_ciclo = min(R_outputs)` e `U_ciclo = min(U_outputs)`. Conservar os marcos
individuais; não aplicar inadvertidamente `max(R_outputs)` de um modelo genérico.
Stock coproduzido não cria encomenda ou expedição fictícia.

**Lote económico = mínimo, nunca múltiplos (decidido pelo Luís a 14/10/2026,
com a resposta da Incompol).** «Produz-se pelo menos o lote económico; se a
necessidade é maior, produz-se essa quantidade, nunca o dobro do lote
económico.» Estado: implementado a 14/10/2026 como contrato de material
versão 4 (`lot_sizing.QUANTITY_MATERIAL_VERSION = 4`,
`MINIMUM_ECO_LOT_VERSION`).

- Quantidade do lote = `max(lote económico, necessidade)`
  (`lot_sizing._apply_eco_lot`). A necessidade é a de sempre: a falta da
  entrega que abre o lote, depois do stock e do excedente do lote anterior
  (carry-forward). Sem olhar para entregas seguintes (só as regras de
  campanha por SKU, se configuradas).
- Gémeas: cada lado pede a sua necessidade (pelo menos o seu lote
  económico); o ciclo faz a maior das duas, sem arredondar, e os dois lados
  recebem a mesma quantidade (o lado que precisa de menos fica com
  excedente).
- Tudo o resto da regra de 13/10 fica igual: uma produção por lote, janela de
  material só na primeira entrega, subcontratação com o lote inteiro.
- Motivo: a regra «arredondar sempre para cima ao múltiplo do lote
  económico» estava no sistema desde o início e nunca veio da Incompol
  (exemplo: entrega de 27 641 com lote de 23 040 produzia 46 080).
- Consequência: quando uma entrega pede mais do que o lote económico deixa
  de sobrar excedente, e a entrega seguinte abre um lote novo (um setup).
  No ISOP de 13/10 (revisões 128/129, «Recalcular» desde D0, modo normal):
  187 lotes e 178 setups como antes, 1 encomenda atrasada como antes, peças
  a mais (excedente) 391 791 → 384 057; 19 lotes mudam de tamanho (ex.:
  JDE002 TP042173-0060-1 de 28 000 = 2 × 14 000 para 17 500).
- Planos anteriores (versões 0-3, lotes arredondados): continuam legíveis e
  válidos pela regra com que foram feitos (`create_lots(quantity_material=3)`
  arredonda; `lot_sizing.rounded_sizing`). O «Recalcular plano» reconstrói-os
  (`api/data.stored_plan_needs_rebuild`: qualquer lote das versões 1-3; os
  instantâneos da versão 0, sem outputs por entrega, compactam como antes), em
  vez de compactar. Um replaneamento (avaria, feriado, operadores, cenário)
  num plano assim mantém os lotes começados com o tamanho antigo (regra 4:
  nunca redimensionar; passam à libertação da versão 3,
  `WHOLE_LOT_MATERIAL_VERSION`) e dimensiona o resto pela regra nova; esses
  lotes antigos são oferta já comprometida, creditados por inteiro e nunca
  contados como sobreprodução (`lot_sizing.older_sizing_lots`,
  `credit_committed_lots`, lidos por `canonical.source_contract_violations`
  e `validation.demand_coverage_metrics`). Um movimento manual ou uma
  reparação local não redimensionam nada: o plano fica na versão em que
  estava até ao «Recalcular». Ensaio na cópia da revisão 129 (14/10, às
  10:00 e às 15:39; avaria da PRM043 e feriado de 23/10, modo normal):
  planos válidos, 11-12 lotes começados com o tamanho antigo, 0 peças em
  excesso ou em falta face à procura, 0 alterações ao histórico, cerca de
  50 s.
- Comparador sem perdas: o atraso de envio para subcontratação conta-se uma
  vez por entrega (`improvement.subcontract_lateness`, o maior atraso das
  suas porções), não por porção. Com a regra nova uma entrega que dois lotes
  arredondados serviam pode ser servida por um só; contada por porção, a
  porção que faltava lia-se como «nunca sai» e o comparador recusava um
  replaneamento melhor (revisão 127, capacidade libertada às 15:39: entregas
  HAN002 dos dias 35, 42 e 70).

**Lote económico = uma produção (decidido pelo Luís a 13/10/2026, a pedido
da Incompol; substitui a «Janela por entrega» e as «Gémeas por entrega»
abaixo).** Estado: implementado a 13/10/2026 como contrato de material
versão 3 (`lot_sizing.WHOLE_LOT_MATERIAL_VERSION = 3`; a versão 4 de 14/10
mantém esta libertação e só muda o tamanho do lote, acima).

- Sempre que se produz um SKU, produz-se pelo menos o seu lote económico, numa
  só produção: um setup, e a produção continua pelos turnos, noites, fins de
  semana e dias seguintes sem novo setup. O lote económico cumpre-se sempre.
- A janela de material de 5 dias úteis aplica-se só à primeira entrega que
  essa produção serve: o `R` do lote é o `R` dessa entrega. As outras entregas
  que o lote cobre (carry-forward) e o excedente económico não têm janela
  própria: considera-se que há matéria-prima para o lote económico inteiro.
- Um lote nunca é partido em produções separadas. Se ele atrasar outra
  encomenda, move-se o lote inteiro (mais cedo, mais tarde ou para a máquina
  alternativa); nunca se interrompe para meter outra ferramenta pelo meio.
  Só uma avaria ou bloqueio real obriga a retomar o mesmo lote com novo setup;
  o resto mantém o `R` do lote.
- Gémeas: o ciclo usa `R_ciclo`, o `R` da primeira entrega servida por
  qualquer dos dois lados (em todos os dados reais igual ao menor `R` do
  lote); o tempo continua a ser o de uma execução.
- A prontidão para o cliente (OTD, OTD-D, atrasos) continua a medir-se por
  entrega (`delivery_readiness`), e a antecipação por entrega (§1.3). Na
  subcontratação cada entrega sai com o lote inteiro (decisão abaixo), mas o
  atraso mede-se pelo stock (decisão de 14/10/2026, abaixo).
- Motivo: a janela por entrega partia cada lote económico em várias produções
  pequenas (setups de cerca de 180 para cerca de 470 por plano, de 3 para 9 por
  dia útil). Esta é a regra que o sistema usava até 07/10/2026.
- Respostas do Luís (13/10/2026) às perguntas que estavam abertas:
  - O lote económico numa só produção vem antes da entrega a tempo: se o lote
    atrasa outra encomenda, move-se o lote inteiro; nunca se parte para a
    salvar (a verificação `lot_split` é regra dura do gate, §1.1). Quando
    falta capacidade, isso pode atrasar uma entrega quando o lote não cabe
    inteiro antes do prazo (visto num ensaio de 13/10, §1.1), e o stock e a
    antecipação sobem.
  - Sem limite máximo de cobertura: um ano de stock é aceitável.
  - Um lote interrompido por avaria retoma com o mesmo material (`R` do lote).
  - Gémeas: `R_ciclo`.
  - **Subcontratação (decidido a 13/10, implementado a 14/10/2026):** o lote
    económico inteiro vai ao subcontratado de uma só vez, quando o lote acaba,
    e o motor aponta para o lote acabar até ao último envio `H` da sua
    primeira entrega (o `H` do lote, `latest_subcontract_dispatch_day`, já é
    o da primeira entrega). Está no avaliador único
    (`material_quantities.whole_lot_subcontract`, `_whole_lot_dispatch`):
    num lote da versão 3 cada output subcontratado tem `factory_day` = dia
    da última peça do lote (o envio; `missing_day` enquanto o lote não está
    todo feito, excedente incluído); nas `delivery_portions` cada peça desse
    lote sai nesse dia (`whole_lot_dispatch`, `available_day`). Desde
    14/10/2026 o envio é só o alvo do motor; a entrega fica pronta quando as
    suas peças são feitas (abaixo). O lado feito em casa de um
    ciclo gémeo continua pronto com as suas peças; um lote passado à versão
    3 a partir das versões 1-2 (`material_upgraded_from`) pode ainda ter as
    produções separadas do contrato antigo e mantém o envio por entrega até
    ao «Recalcular plano»; se uma âncora manual o mantém (com os lotes da
    mesma ferramenta montada que o alimentam,
    `frozen._protected_lots(mount_suppliers=True)`), mantém-no em cada
    «Recalcular» até a âncora ser removida. Leem-no sem regra própria:
    o score (`subcontract_dispatch_misses`), o comparador sem perdas e o
    gatilho do replaneamento por capacidade libertada (conta o resto do
    lote).
    **Atraso pelo stock (decidido pelo Luís a 14/10/2026, sem opção para
    ligar/desligar):** uma entrega subcontratada só está atrasada se faltarem
    peças no stock mostrado em Entregas (cada peça conta no dia em que é
    feita na fábrica), como qualquer referência, em todo o sistema:
    encomendas a tempo, OTD/OTD-D, motivos de aprovação, riscos e ações do
    Hoje, relatório de atrasos e aviso de capacidade livre. No avaliador
    único `customer_ready_day` = dia em que as peças da entrega são feitas
    (sem somar o prazo do subcontratado); `factory_day` continua a ser o
    envio (o lote inteiro sai quando acaba). O motor continua a apontar para
    acabar 5 dias úteis antes da entrega (`production_due_day`; score
    `subcontract_dispatch_misses`, comparador sem perdas
    `improvement.subcontract_lateness`, e o replaneamento por capacidade
    libertada conta envios falhados como casos de capacidade livre,
    `late_with_idle_capacity(dispatch_targets=True)`), mas falhar isso não
    é atraso e não aparece no ecrã: saem o motivo `subcontract_dispatch_risk`
    (revisões antigas: «critério antigo»), a lista «envios para
    subcontratação em atraso», os cartões «Envios sub. em atraso», o aviso
    do movimento manual e as viagens `subcontract_trips`. Caso real: a
    CF589MMA1A02.20 (829 pç para 16/10 feitas a 13/10) deixa de estar
    atrasada e de pedir aprovação. O ecrã de Entregas/Stock trata a
    referência como qualquer outra (+N no dia em que é produzida, −N no dia
    da entrega), marca-a com um «S» (`subcontract_due_workdays`) e a rutura
    segue esse stock. O tooltip do Gantt diz «Subcontratado — acabar até
    DD/MM» (o `production_due_day` do lado subcontratado).
    Revisão 128 recalculada: todos os lotes subcontratados (HAN002, JTE003,
    gémeas BFP178/BFP186) saem no fim do lote; num lote HAN002 que cobre
    duas semanas a primeira entrega deixa de sair antes de o lote acabar.

Implementação (13/10/2026):

- Dimensionamento (`lot_sizing.py`): os outputs por entrega das versões 1-2
  mantêm-se (um por entrega coberta, excedente no fim); na versão 3 todos
  levam `material_release_day = R` do lote (`_inherit_lot_release`: o menor
  `R` das entregas; nas gémeas `R_ciclo` das duas que formam o ciclo) e
  guardam o `R` próprio da entrega em `delivery_material_release_day`, só
  para rastreabilidade. `redate_lot_outputs` volta a datar ambos pelo
  calendário atual.
- Material (`material_quantities.whole_lot_release`): um lote da versão 3 é
  uma só parte, libertada inteira no `R` do lote (`released_quantity`,
  `next_release_day`, `material_portions`). Todos os lotes da versão 3 vão
  ao construtor por partes (`quantity_dispatch.has_quantity_releases`),
  nunca ao motor antigo.
- Verificação física (`validation.lot_split_violations`, tipo `lot_split`,
  métrica `lot_split_violations` no gate; as quebras vêm de
  `validation._BreakFinder`). Um lote da versão 3 é inválido quando, na sua
  máquina, entre dois dos seus segmentos:
  - há outro trabalho (`interleaved`);
  - há nova afinação depois de já ter produzido (`remount`);
  - não há nada, a ferramenta continua montada, mas há tempo de turno livre
    pelo meio (`pause`, revisão de 13/10): a mesma definição de tempo livre
    da regra «Continua» (`calendar.free_shift_intervals`: dias úteis, dentro
    dos turnos, fora de indisponibilidades da máquina e da ferramenta, com
    operadores do grupo, sem a ferramenta noutra máquina, pelo menos
    `MIN_FREE_INTERVAL_MIN` = 30 min). Noites, fins de semana, feriados e
    avarias não são pausas.

  Uma avaria ou bloqueio da máquina ou da ferramenta só desculpa as duas
  primeiras quando cobre parte do tempo de trabalho entre as duas partes
  (`validation._working_gap`, `_block_in_working_time`): um bloqueio curto à
  noite, num fim de semana ou fora do intervalo não desculpa nada (antes
  bastava qualquer bloqueio entre as duas partes). Nunca se julga uma quebra
  cuja parte anterior é histórico: começou antes da fronteira do plano (o
  minuto atual da regra 4, `ScheduleResult.history_boundary`, a mesma regra
  de `scheduler/history.py`, nunca o dia do relógio) ou é a parte começada do
  resto de um lote no problema residual (`_protected_context`). Assim o resto
  de um lote começado hoje pode seguir outro trabalho, por exemplo quando a
  regra «Continua» corta a execução montada e entra uma encomenda que vence
  hoje (com o dia do relógio esse plano era recusado como `lot_split`). No
  problema residual a produção congelada é ela própria um bloqueio de
  máquina e ferramenta. Sem fronteira (carregar um ISOP, «Recalcular plano»
  desde D0) tudo é julgado. Um cenário e uma promessa (CTP) levam a
  fronteira da sua simulação (`SimulateResponse.history_boundary`, também
  nos dados do cenário guardado), nunca a do plano de que partem: sem ela,
  aplicar CTP ou cenário na revisão 128 (13/10) era recusado, porque um lote
  HAN002 de um contrato anterior «passava de 1 para 2 produções» com a
  parte de D0 julgada como nova. Um movimento manual não tem fronteira
  própria: é julgado, e as produções permitidas dos lotes passados à versão
  3 contadas, com a fronteira guardada no plano. Desde D0 a pausa ou o corte
  da regra 4 de um plano guardado (o resto depois de uma encomenda urgente,
  de uma avaria retirada entretanto, de uma ausência de operadores) é uma
  segunda produção: o «Recalcular plano» reconstrói então os lotes em vez de
  compactar (`api/data.stored_plan_needs_rebuild`; revisão de 13/10:
  compactar recusava o plano como `lot_split`). O verificador do
  contrato confirma também que nenhum lote da versão 3 produz ou prepara
  antes do `R` do lote (`canonical.source_contract_violations`).
- Planos antigos: um plano das versões 0, 1 ou 2 continua válido (as suas
  produções começam no `R` do lote ou depois) e nunca pede «Recalcular
  plano» (`canonical.legacy_material_plan` devolve sempre falso). Ao
  replanear, reparar, compactar ou mover um lote num plano das versões 1-2,
  os lotes passam à versão 3 tal como estão
  (`lot_sizing.upgrade_plan_material`, `frozen.with_current_material`,
  `manual_move._move_lot`): o lote começado congela só o que começou
  (regra 4) e o plano nunca mistura contratos de libertação. Ficam com o
  tamanho arredondado da versão em que foram feitos (versão 3, nunca a 4):
  desde 14/10 o «Recalcular plano» redimensiona-os pela regra do mínimo.
  Esses lotes ficam marcados (`material_upgraded_from`) e podem manter as
  produções separadas que o contrato antigo criou, **mas nunca ganhar
  outra** (revisão de 13/10: um replaneamento partia lotes como BFP082_14 e
  o gate aceitava). Cada
  cálculo regista nos outputs quantas produções o lote tem no plano de que
  parte (`material_upgraded_productions`, escrito por
  `frozen.with_current_material` no início do replaneamento, da reparação,
  da compactação e do movimento manual; `validation.lot_productions`: uma
  por máquina mais as quebras, contadas com a fronteira desse cálculo e sem
  desculpar bloqueios, porque o calendário pode ter mudado). O plano novo é
  inválido se o lote tiver mais produções do que isso (`lot_split` com
  `productions` e `allowed_productions`). Margem conhecida: uma quebra do
  plano guardado desculpada por uma avaria conta como produção permitida.
  O «Recalcular plano» desde o início redimensiona-os sempre
  (`api/data.stored_plan_needs_rebuild`).
- Resto de um lote começado: como o lote inteiro já tem material, o resto
  costuma retomar logo a seguir à parte começada, com a ferramenta ainda
  montada. A validação do problema residual vê essa parte começada como
  histórico (`validation._protected_context`, lotes em
  `residual_lot_remainders`); uma cópia antiga de um lote que não é resto de
  um lote começado continua a não servir de ponte.
- Primeiro ensaio na cópia do plano ativo (13/10, revisão 128, ISOP 13/10,
  recálculo completo): 444 → 178 setups, 0 lotes com mais de uma produção,
  o mesmo atraso (HAN002) e nenhuma encomenda atrasada a mais; 22 entregas
  ficam prontas um pouco mais tarde mas dentro do prazo, 539 mais cedo;
  antecipação média 14,9 dias (máx. 66; 65 entregas com mais de 30 dias).
  Os números do ensaio final de 14/10 (carga de ISOP nova: 445 → 178 setups,
  44 entregas com mais de 30 dias) e do golden master estão em §1.1; diferem
  destes por medirem outro momento e outra contagem. O custo da regra
  (§1.1): mais stock e produção mais cedo, e pode atrasar uma entrega quando
  o lote não cabe inteiro antes do prazo (o lote não se parte para a
  salvar; visto na avaria grande da PRM031 a 16/10 deste ensaio). Com dia de
  planeamento 16/10 (23 lotes começados), avaria na PRM043, feriado novo e
  movimentos manuais dão planos válidos, sem mexer na produção começada.
  Até à regra «Continua» (13/10) o feriado novo de 23/10 ficava com produção:
  a série da BFP082 montada desde 14/10 era congelada inteira e levava o lote
  `_14`, ainda por começar; com ela o feriado fica livre.

**Janela por entrega (versão 1, decidido entre 07/10 e 10/10/2026;
substituído a 13/10/2026, ver acima; histórico).** Quando o carry-forward
atribuía um lote económico a várias entregas, cada entrega conservava o seu
`R`: a quantidade de uma entrega só podia ser preparada ou produzida a partir
do seu próprio `R` e o excedente com a última entrega coberta. Partes
libertadas em datas diferentes eram execuções físicas distintas.

**Gémeas por entrega (versão 2, decidido pelo Luís a 11/10/2026, Fase B2;
substituído a 13/10/2026; histórico).** Cada lado de um ciclo gémeo regista
um output por entrega que as suas peças cobrem (carry-forward), com as datas
dessa entrega; só as duas entregas que formam o ciclo partilham
`R_ciclo = min(R)` (`cycle_material_release_day`). Na versão 2 as entregas
futuras e o excedente esperavam pelo seu próprio `R` e um lado só com stock
coproduzido nunca libertava material (curva de libertação
`material_quantities._twin_curve`). A estrutura dos outputs mantém-se na
versão 3; só a libertação muda. A prontidão é por lado e por entrega.

Regras do motor (propostas e aceites pelo Luís a 10/10/2026; desde a versão
3 de material cada lote é uma só parte, por isso as regras aplicam-se entre
lotes da mesma ferramenta):

1. **Material já libertado, ferramenta continua.** Se o material do lote
   seguinte da mesma ferramenta (na versão 1-2: da parte seguinte do mesmo
   lote) já foi libertado quando o anterior acaba, a ferramenta montada
   continua a produzir, sem novo setup.
2. **Ferramenta montada vs. lote mais urgente.** A ferramenta montada continua
   mesmo havendo um lote mais urgente para a máquina, desde que esse lote perca
   menos de 60 min (a mesma tolerância do §1.3; dentro dela, os setups
   desempatam antes dos minutos exatos). Com 60 min ou mais, passa o urgente.
   A perda mede-se sobre tudo o que falta ao lote urgente, na sua
   melhor máquina, contra a posição que tinha **antes de começar a cadeia de
   continuações**: vários passos pequenos nunca somam 60 min ou mais. Nenhuma
   entrega do lote urgente pode ficar atrasada ou mais atrasada.
3. **Mudar de máquina leva o lote inteiro**; um lote nunca fica repartido
   entre máquinas (nem, desde 13/10/2026, entre produções).
4. **Lote começado:** só congela o que já começou. O resto continua
   otimizável como o mesmo lote, com o `R` do lote, e o lote nunca é
   redimensionado. Implementado a 11/10/2026
   (`plans/frozen._protected_plan`): congela-se a produção antes do dia de
   planeamento e a execução montada nessa fronteira enquanto continua sem novo
   setup (uma avaria ou bloqueio novo para-a aí); o resto do lote vai ao
   problema residual como o mesmo lote, já dimensionado
   (`EngineData.residual_lot_remainders`, com o lote inteiro creditado para o
   dimensionamento não o repetir), na mesma máquina, e o plano completo junta
   as duas partes no lote original. Uma continuação congelada sem setup leva
   sempre consigo o lote que montou a ferramenta (a produção anterior desse
   lote incluída); um lote de um contrato de material anterior, ancorado ou já
   todo feito fica inteiro. A proteção do histórico na gravação compara a
   produção anterior a hoje, a de hoje que começou antes da hora do cálculo
   (com a regra de corte abaixo) e o próprio lote.
   **Fronteira = hora atual (decidido pelo Luís a 13/10/2026).** O motor
   trabalha em dias inteiros, mas um replaneamento durante o dia não pode
   mexer no que já se fez hoje nem pôr trabalho em horas que já passaram
   (caso real: avaria da PRM043 retirada às 15:39 e o plano mostrava a
   máquina a produzir desde as 07:00). Por isso a fronteira da regra 4 é o
   minuto atual da fábrica (Europe/Lisbon, `calendar.factory_now`), não o
   início do dia:
   - Cada cálculo capta **um só "agora"** e usa-o do princípio ao fim:
     trabalhos de replaneamento (avaria posta ou retirada, feriado,
     configuração), gravações pelo servidor (`plans.transactions`, relógio
     fixo com `calendar.fixed_factory_clock`) e movimentos manuais
     (`plans.manual_move.move_lot`). O dia de planeamento, os minutos já
     decorridos, a proteção, a continuidade da regra 4, o aviso de
     capacidade livre e a proteção na gravação leem esse mesmo instante.
     Nos testes injeta-se com `now=` ou `fixed_factory_clock`.
   - Hoje, os segmentos que começam antes do "agora" ficam congelados como os
     dos dias anteriores (`frozen.started_before`); um segmento a decorrer
     nesse minuto fica inteiro, e a execução montada continua a partir do
     último deles com a regra de continuidade acima.
   - Nenhuma produção ou setup novo entra hoje antes do "agora", em nenhuma
     máquina: no problema residual há um bloqueio temporário de máquinas e
     ferramentas de 00:00 até ao "agora" no dia de planeamento
     (`frozen._install_frozen_reservations`, "Tempo já decorrido hoje"),
     nunca gravado na configuração.
   - **Uma só regra para o que já aconteceu** (`scheduler/history.py`):
     o que começa antes do "agora" já aconteceu. Um dado com hora (avaria ou
     indisponibilidade de máquina/ferramenta, ausência ou corte de
     operadores, feriado, elegibilidade, turnos) só julga o plano a partir de
     max(agora, início do dado): uma ausência desde as 07:00 lançada às 10:00
     nada diz da produção das 07:00–10:00, que já se fez. O limite viaja com
     o plano (`ScheduleResult.history_boundary`, guardado nos dados do plano
     como `EngineData.history_boundary`, tal como as provas dos lotes
     preservados) e é lido por
     todas as validações desse plano — no cálculo, ao aplicar e na gravação
     (`scheduler.validation`, `scheduler.operators`). No problema residual
     não há limite: tudo ali é trabalho novo e julgado por inteiro.
   - **Corte em vez de libertar** (`frozen._conflict_cuts`): quando um dado
     novo choca com trabalho protegido (os segmentos já começados hoje e a
     execução montada que continua), o segmento pára em max(agora, início do
     conflito). A parte antes fica exatamente como estava (correu de facto,
     com as peças feitas até esse minuto, arredondadas para baixo); o resto é
     replaneado como resto do mesmo lote (nunca redimensionado; sem setup
     novo se a ferramenta continuar montada e sem outra pelo meio); o que essa
     máquina protegia depois dele sai da proteção. Uma falta de operadores
     não nomeia lote: pára, no "agora", o segmento protegido desse grupo e
     turno que começou por último (desempate: máquina, lote), até a falta
     desaparecer. Um dia que deixou de ser útil (feriado lançado hoje) pára
     do mesmo modo o trabalho protegido desse dia a partir do "agora".
     Um segmento que até esse minuto não fez nenhuma peça (ex.:
     afinação a decorrer) sai inteiro, mas o lote continua começado: todo ele
     é replaneado como resto, com o mesmo tamanho. Na validação do residual,
     a parte começada de um lote cujo resto se replaneia conta como a
     ferramenta montada antes desse resto (`validation._protected_context`;
     antes era ignorada e uma execução libertada a 14/10 às 06:00 falhava
     com "falta afinação").
     Casos ensaiados pela API, com aplicação (cópia da revisão 128, 13/10):
     ausência de 4 (ou 2) operadores de Grandes no turno A desde as 07:00 ou
     desde as 10:00, lançada às 10:00 — pronto e aplicado (antes falhava com
     "regras físicas"); a manhã fica, a PRM019 pára às 10:00 com 1415 peças
     (com 4 ausentes) e a afinação da PRM031 iniciada às 09:45 é refeita mais
     tarde; 1 atraso (como antes), 448–449 setups. Ausência no turno B, ou no
     turno A de 14/10 lançada a 14/10 às 06:00 — pronto (o segundo falhava
     antes nas duas versões). Avaria da PRM043 das 07:00 às 09:00 lançada às
     15:39 — o plano ativo continua válido e mantém-se, em 3 s (antes falhava
     com "produção já iniciada"). Avaria da PRM019 das 09:00 às 12:00 lançada
     às 10:00: o segmento das 08:55 pára às 10:00 (1415 peças) e retoma às
     12:00 sem afinação; das 11:00 às 13:00: pára às 11:00 (2722 peças) e
     retoma às 13:00. Em casos sintéticos: um segmento das 09:00 às 11:30 com
     avaria das 11:00 às 13:00 lançada às 10:00 pára às 11:00 e o resto vem
     depois sem setup novo; uma avaria das 07:00 às 08:00 lançada às 13:00
     deixa a manhã toda (07:00–09:30 e 09:30–12:00) como estava.
   - A proteção na gravação (`frozen.historical_schedule_changes`, na loja
     `plans.store` e antes, em `candidate_history_changes`) lê a mesma regra:
     cada segmento de hoje começado antes do "agora" do cálculo fica igual
     ou pára num minuto não anterior a esse "agora" com as peças desse corte
     (`history.cut_row`); só pode faltar se até esse minuto não fez nenhuma
     peça; nenhuma produção nova antes do "agora"; um lote com produção
     antes do "agora" mantém o tamanho. Aceita portanto exatamente o que a
     libertação produz.
   - **Data e idade do cálculo:** na gravação, a data de hoje é a do relógio
     real (`calendar.wall_factory_now`); o minuto do cálculo só conta se for
     do mesmo dia. Um plano calculado noutro dia é recusado com «O plano foi
     calculado noutro dia; calcule novamente.» Trabalhos de replaneamento e
     pré-visualizações (movimentos manuais, recálculos à espera de
     aprovação) só se aplicam até 15 minutos depois do cálculo («O plano foi
     calculado há mais de 15 minutos; calcule novamente.»); o fluxo normal
     (o trabalho acaba e aplica-se logo) não é afetado.
   - O fecho operacional do trabalho (prioridades e compactação depois do
     construtor) volta a correr durante o dia quando só há lotes começados
     hoje: corre no residual, com o trabalho protegido e o tempo já decorrido
     reservados, como o próprio cálculo. Com lotes começados em dias
     anteriores continua desligado, como antes.
   - «Recalcular plano» continua a recalcular desde D0 (decisão de
     06/10/2026, §5): o seu "agora" é as 00:00 de D0, nada conta como
     decorrido e o plano não leva limite de histórico. Carregar um ISOP de
     raiz não muda.
   - Resultado no caso real (revisão 126 → 127, avaria retirada às 15:39 de
     13/10, pelo caminho real do trabalho): nada novo antes das 15:39 e a
     manhã intacta (antes: 8 segmentos novos antes das 15:39, entre eles a
     PRM043 desde as 07:00, e 3 segmentos da manhã mudados); 0 encomendas
     atrasadas. O caminho depende do tempo (AGENTS §6): no ensaio de 13/10 à
     noite a compactação chegou sem atrasos (472 setups) e o resto do lote
     `_5` de 6800016767A.10 recomeça a 14/10 às 07:00 sem setup novo,
     ficando a PRM043 parada de 13/10 das 15:39 à meia-noite; na verificação
     anterior a compactação deixou um atraso e o construtor completo pôs o
     resto a recomeçar às 15:39 (479 setups). Às 10:00 o construtor completo
     põe o resto às 10:00 (479 setups); às 06:00 o plano é igual ao de antes.
   **«Continua» (decidido pelo Luís a 13/10/2026):** a execução montada só
   continua enquanto, entre um segmento e o seguinte da mesma máquina, não
   houver tempo de turno livre no calendário atual
   (`frozen.free_working_time_between`, com a mesma definição de tempo livre
   do aviso de capacidade livre: `calendar.free_shift_intervals`). Noites,
   fins de semana, feriados, tempo já decorrido (dias antes de hoje e, hoje,
   até à hora atual da fábrica), turnos sem operadores do grupo,
   indisponibilidades da máquina ou da ferramenta e folgas de menos de
   `calendar.MIN_FREE_INTERVAL_MIN` (30 min) não a interrompem; tempo de turno
   livre corta-a, e
   o resto do lote vai ao problema residual como o mesmo lote, na mesma
   máquina. Retirada uma avaria, o buraco que ela deixou passa a ser tempo
   livre e o resto pode ser antecipado; logo a seguir à fronteira, com a
   ferramenta ainda montada, não paga setup novo. Caso real: revisão 127
   (avaria da PRM043 retirada; o bloco de 19/10 ficava preso e a máquina
   parada de 13 a 18/10 com duas encomendas atrasadas). **Movimentos manuais (12/10/2026)**
   seguem a mesma regra (`plans/manual_move._move_protection`, sobre
   `_protected_plan` sem o lote movido): o lote movido é decisão do planeador e
   sai da proteção; o resto de um lote começado é realocado como o mesmo lote,
   nunca redimensionado; depois de cada caminho (posições fixas, realocação,
   lote fixo primeiro, melhoria) a produção congelada tem de estar fisicamente
   igual (`_keeps_frozen`), senão o candidato é recusado. Mover um lote já
   começado continua recusado. Caminho por quantidades no §6.
   **Calendário e ajuste rápido (11/10/2026).** As datas das entregas de um
   lote começado seguem o calendário atual: um feriado ou dia extra novo
   volta a datá-las (`U`, `I`, `R`, `R_ciclo`, envio para subcontratação)
   exatamente como o dimensionamento as dataria hoje
   (`lot_sizing.redate_lot_outputs`); o tamanho, as entregas cobertas
   (operação, quantidade, dia do cliente) e o excedente não mudam, e a
   verificação de contrato continua a comparar o lote com o dimensionado a
   partir dos dados atuais. O ajuste rápido de uma alteração de calendário
   (avaria, indisponibilidade) só trabalha a parte móvel
   (`frozen.repair_preserving_protected_lots`): a produção congelada fica
   reservada e volta igual; o resto de um lote começado é reparado como o
   mesmo lote, mas a normalização canónica deixa-o onde está, como a
   compactação do ciclo de melhoria. As datas de lote do resto são as da sua
   primeira entrega por fazer: não o ordenam como o plano completo ordena o
   lote nem pelas entregas que cada execução serve (na avaria pequena da
   PRM031, revisão 124, punham uma execução para o dia 46 atrás de outra para
   o dia 47). Só a reparação das restrições físicas o move, quando a
   alteração o invalida. Nenhum candidato que mude produção iniciada é
   oferecido: o ajuste rápido cai para o construtor completo e um candidato
   final assim falha o trabalho com o código `history_protected` (não
   `blocked`, que é conflito físico).

Construtor por partes (`quantity_dispatch.py`, B1a). Desde a versão 3 de
material cada lote é uma só parte (o lote inteiro, numa produção); as regras
abaixo valem entre lotes, e as partes múltiplas só existem em lotes das
versões 1-2:

- **Prioridade de uma parte:** `lot_priority_key` com a quantidade da entrega
  ao cliente que a parte serve (operação + dia, somada sobre todos os lotes),
  não a fatia da parte; só contam as entregas com o mesmo prazo de produção
  da parte. Uma parte com uma fatia de uma entrega grande não espera atrás de
  uma entrega mais pequena do mesmo dia.
- **Entregas primeiro, mesmo dia:** uma parte menos urgente com prazo igual
  ou anterior passa à frente quando isso salva a sua entrega e nenhuma
  entrega fica mais atrasada (nem a do lote que ultrapassa, nem as das partes
  ordenadas entre elas). A cadeia de continuações para quando se aplica.
  Num lote da versão 3, que não deixa entrar ninguém a meio, vale também
  para encomendas com prazo posterior: se o lote inteiro a atrasaria, ela
  passa à frente e o lote move-se inteiro para depois dela, desde que
  nenhuma entrega do lote fique mais atrasada (13/10/2026; nas revisões 90,
  124 e 128 o plano não muda).
- **Ferramenta retida:** uma inserção num intervalo de ferramenta retida só
  se aceita se nenhuma entrega das partes que recoloca, nem das partes ainda
  por colocar desses lotes, nem do lote inserido (incluindo as suas partes
  seguintes), ficar mais atrasada. Cumprido isso, aceita-se sempre que uma
  entrega do lote inserido fique mais cedo. Sem esse ganho, decide o mesmo
  comparador do avaliador (`policy.tolerant_better`, §1.3) sobre todas as
  partes que a inserção mexe, por ordem de urgência da parte: uma parte só
  pode perder 60 min ou mais se outra mais urgente ganhar o mesmo; dentro da
  tolerância decidem menos setups (a inserção obriga a remontar a ferramenta
  retida) e só depois os minutos exatos (`quantity_dispatch._break_accepted`).
  Assim o construtor nunca faz uma inserção que o ciclo de melhoria
  desfaria, nem recusa uma que ele faria.
- Se o construtor por campanhas falhar, usa-se o anterior (uma execução por
  parte) e o plano leva um aviso simples; o mesmo quando o fecho de setups
  retidos é rejeitado pela validação.

**Um só avaliador de prontidão (10/10/2026).** Stock, OTD-D, encomendas,
expedição, subcontratação, atrasos, riscos, tooltip, propostas, CTP,
robustez e o ciclo de melhoria usam `material_quantities.delivery_readiness`.
As peças são fungíveis por referência: a prontidão de cada encomenda é FIFO por
tempo absoluto sobre todos os lotes da operação. Subcontratadas incluídas:
cada peça conta no dia em que é feita (14/10/2026, §2); o envio de um lote
da versão 3 (sai inteiro quando acaba, `whole_lot_subcontract`) é só o alvo
do motor. O motivo de aprovação
`delivery_risk` é por encomenda; `tardy_count` ("Lotes no prazo") é só
indicador. Um teste estático proíbe outra regra "fim do lote" nas vistas.

## 3. Procura, quantidades e duração

- Cada célula NP negativa do ISOP é uma encomenda independente. Repetições
  contam; não deduplicar valores nem calcular deltas entre células.
- Conservar o detalhe por cliente antes das agregações. Não descontar duas
  vezes o stock que já está refletido na primeira necessidade líquida.
- Ignorar `Prz.Fabrico` e `STOCK-A` como fontes de procura. PRM020 está fora
  do âmbito: diagnosticar a importação incompatível, nunca perder procura
  silenciosamente ou criar capacidade nessa máquina.
- Dimensionar o lote económico efetivo e carry-forward uma vez. O lote
  económico é um mínimo: lote = `max(lote económico, necessidade)`, nunca um
  múltiplo (Luís, 14/10/2026, §2). Um movimento altera alocação, não inventa
  novos lotes, compromissos ou quantidades.
- Gémeas produzem simultaneamente quantidades positivas iguais em cada ciclo;
  eco-lots efetivos incompatíveis bloqueiam. Não usar LCM para esconder isso.
- Recalcular duração/setup ao trocar de máquina: elegibilidade, pH, OEE e
  configuração efetiva dessa máquina. O ciclo gémeo consome uma execução,
  determinada pelo maior tempo dos outputs, não a soma dos tempos.
- Segmentos partidos conservam a quantidade total e os minutos produtivos;
  o arredondamento deixa o resíduo no último fragmento. Nunca criar produção
  com duração zero, truncar peças para caber ou somar a mesma oferta duas vezes.

## 4. Recursos e setups físicos

- Uma máquina não executa dois trabalhos simultaneamente. Uma ferramenta
  física não pode ocupar duas máquinas simultaneamente.
- Setup usa a equipa do grupo; produção usa operadores do grupo/turno apenas
  nos minutos produtivos. Ausências, capacidade zero, turnos, pausas, feriados,
  dias extra e indisponibilidades são limites reais.
- Identidade de preparação: ferramenta + afinação de referência/família
  configurada, ou ferramenta + par gémeo confirmado. Mesmo molde com outra
  afinação pode exigir setup; mesmo ID de campanha não prova retenção.
- Só dispensar preparação quando a cronologia prova montagem compatível e
  completa, sem troca de afinação nem utilização remota do molde no intervalo.
  Fragmentos anteriores a uma quebra de montagem não se somam aos posteriores.
- Setup repartido por fechos/turnos mantém uma identidade física. Durante
  uma espera com ferramenta montada, as reservas necessárias permanecem.
  Remover setup redundante liberta minutos reais e desencadeia nova procura
  de antecipação; não alterar apenas a faixa desenhada no Gantt.
- Produção pode atravessar fronteiras legais mediante segmentação;
  interrupções por outra ferramenta exigem prova de desmontagem/reinstalação.
- **Decisão de 03/10/2026:** um setup novo e o seu primeiro minuto produtivo
  ficam na mesma janela de turno; o alocador não inicia um setup que só
  terminaria no turno ou dia seguinte. Setups repartidos já existentes num
  plano (histórico, importação) continuam válidos e mantêm a identidade.

## 5. Histórico, candidatos e Gantt

- Distinguir planeamento passado protegido de execução real. A aplicação não
  deve afirmar execução só porque passou a data planeada.
- **Decisão de 06/10/2026:** o comando explícito "Recalcular plano" revê o
  ISOP completo desde D0, incluindo produção passada apenas planeada. Nesse
  comando, a data decorrida não congela lotes nem gera reservas de capacidade;
  provas antigas derivadas exclusivamente da data são retiradas da cópia de
  cálculo. Mantêm-se âncoras manuais, estados observados das máquinas e oferta
  já comprometida. Outras alterações operacionais e reposições conservam a
  proteção por data existente. Esta exceção é interna ao coordenador, não um
  parâmetro de cliente que permita contornar a validação. O orçamento atual
  permanece inalterado; recalcular continua sujeito às aprovações existentes.
  **Confirmado em 07/10/2026, com risco aceite:** com um ISOP anterior a hoje,
  o recálculo pode colocar produção em dias já passados e a gravação normal
  seguinte protege-a como histórico (contraria o §2 sobre não inventar
  execução). Mitigações: o ecrã avisa antes de recalcular com ISOP antigo
  (`frontend/src/lib/recalcGuard.ts`); o teste
  `test_accepted_risk_recalculation_then_ordinary_write_freezes_past_placement`
  documenta a sequência. Se lotes protegidos ficarem com durações de uma
  configuração anterior (ex.: OEE alterado), o recálculo reconstrói os lotes
  com o optimizador completo em vez de compactar
  (`api/data.stored_plan_needs_rebuild`). O mesmo com lotes das versões 1-2
  (§2), desde 14/10/2026 com qualquer lote das versões 1-3 (arredondado a
  múltiplos do lote económico; a compactação não redimensiona) e com um
  lote que, julgado desde D0, tem mais de uma produção (corte da regra 4
  durante o dia): a compactação não junta as partes.
  **Consequência operacional (ensaio de 13/10/2026, aceite por este §5):**
  a reconstrução também refaz o que já se fez hoje e, com um ISOP antigo, os
  dias anteriores; a compactação mantinha-os na prática. No primeiro
  «Recalcular» de um plano das versões 1-2 (revisão 128) foram substituídas
  5 linhas da manhã que já tinham feito peças (às 10:00), 14 às 15:39, e a
  14/10 às 07:00 com o ISOP de 13/10 29 linhas de 13/10, embora o ecrã diga
  «os dias anteriores são considerados já produzidos». Recomendação: fazer
  a primeira conversão com um ISOP novo, ou com «Recalcular» antes das
  07:00; depois de um corte da regra 4, preferir um replaneamento normal ao
  «Recalcular».
- **Hora atual (13/10/2026):** fora de «Recalcular plano», o passado
  protegido acaba no minuto atual da fábrica, não no início de hoje: o que
  começou hoje antes do cálculo fica como está e nada novo é posto em horas
  que já passaram (§2, regra 4, «Fronteira = hora atual»). A gravação
  confirma-o com o instante do próprio cálculo. Limites conhecidos
  (documentados, não corrigidos):
  - A vista do plano ainda usa o dia como histórico
    (`plans/explanations.py`): lotes começados esta manhã não aparecem como
    históricos e podem ter a dica "podia começar mais cedo". Só visual.
  - «Anular» dentro do mesmo dia (`plans/restore.py`) passa pela proteção ao
    minuto: repor uma versão anterior que difere do plano atual antes do
    "agora" é recusado. Está de acordo com a regra, mas é uma mudança.
  - Entre o cálculo e a aplicação (até 15 minutos, ver §2) um candidato pode
    ainda reescrever produção do plano ativo desse intervalo.
  - Um segmento que pára sem nenhuma peça feita (afinação a decorrer) sai
    inteiro: a afinação é refeita mais tarde (conservador).
  - Um lote que não pode ser replaneado sozinho (ancorado, de um contrato de
    material anterior) não é cortado: fica inteiro; se um dado novo chocar
    com ele o trabalho falha como antes.
  - Elegibilidade (ferramenta/máquina) mudada com um lote começado: a parte
    feita fica como histórico, mas o resto continua preso à máquina do lote
    (regra 3), por isso o plano pode não ter solução.
- Preservar lotes protegidos integralmente e âncoras manuais. Um bloqueio por
  histórico/âncora não é um bloqueio de máquina, material ou operadores.
- **Decisão pendente (11/10/2026, à espera do Luís):** retirar um feriado (ou
  acrescentar um dia extra) dentro da janela de material de uma entrega já
  parcialmente produzida antes de hoje põe o seu `R` depois dessa produção; a
  gravação recusa, porque o histórico é julgado com a janela atual. Até haver
  decisão, essa alteração continua recusada.
- Replanear apenas produção móvel, mas validar contra o contexto completo:
  reservas, montagem herdada, produção preservada e compromissos de origem.
- Um candidato referencia dataset, revisão, configuração, calendário, versão
  de política e assinatura física. Alterações desses elementos invalidam-no.
- Aplicar exatamente o candidato apresentado, sem resolver de novo. Revalidar
  na fronteira de persistência; commit, revisão e recibo têm de ser atómicos.
  Restaurar um snapshot não otimiza implicitamente.
- O Gantt apresenta os segmentos persistidos; setup, início produtivo e fim
  são campos distintos. As datas cliente/produção/material não são aliases.
- Explicar uma espera com evidência do snapshot atual. Distinguir restrição
  física, material, proteção, contrapartida e pesquisa incompleta. Não deduzir
  causalidade de uma nota antiga, de um OEE isolado ou da ausência de candidato.
- Reutilizar os detalhes e relatórios existentes; não adicionar cartões,
  legendas ou funcionalidades para mascarar um defeito de planeamento.
- **Atraso com capacidade livre (13/10/2026, só informação):**
  `scheduler/idle_capacity.late_with_idle_capacity` procura entregas atrasadas
  (`improvement.order_service`; subcontratadas pelo stock, 14/10/2026) com
  tempo de turno livre (`calendar.free_shift_intervals`; hoje só depois
  da hora atual) numa máquina elegível ativa entre `max(hoje, R)` e o prazo
  de produção. Um caso por lote (gémeas juntas). Na máquina do lote conta o
  que falta; numa alternativa conta o lote inteiro (regra 3); peças que só
  ficam prontas no fim do lote contam o resto do lote; um lote com produção
  até hoje inclusive só conta a sua máquina (regra 4). Fica em
  `gate_report.idle_capacity_late` e num aviso simples no topo do ecrã
  (`plan-view.plan_notices`, «Possível melhoria: …»), que não manda carregar
  em nenhum botão. Nunca bloqueia, ordena nem muda um plano; só decide se um
  replaneamento por capacidade libertada tenta também o construtor completo
  (§6). A falta real de capacidade (PRM042 na revisão 90) não aparece.

## 6. Solver e limites de compute

- Reutilizar OR-Tools CP-SAT e os alocadores existentes. Primeiro construir
  uma solução completa válida; depois melhorar de forma limitada e mensurável.
- Começar por inserção no primeiro intervalo viável e procura em todas as
  máquinas elegíveis; depois trocas locais e pequenos grupos acoplados por
  máquina, ferramenta ou equipa. CP-SAT local trata os casos restantes.
- Vizinhança `priority_rotation` (Fase B3, 11/10/2026): as anomalias por
  entrega da auditoria operacional (`operational_audit.find_output_priority_anomalies`:
  uma execução menos urgente antes de outra mais urgente já libertada, na
  mesma máquina) são propostas ao avaliador como as rotações da própria
  auditoria (só leitura). Corre no início de cada ronda (`leading`), antes
  das outras vizinhanças, porque os movimentos aceites criam anomalias
  novas; uma rotação já proposta sobre a mesma sequência da máquina não é
  reconstruída. O avaliador decide com o contrato de sempre, por isso uma
  rotação que o contrato aceita deixa de ficar como "evitável".
- Geradores propõem; um único avaliador aplica o mesmo contrato a planeamento,
  melhoria, movimento, explicação e persistência. Não duplicar prioridades.
  Os geradores não validam: o avaliador valida cada candidato uma vez (o
  plano residual e, com produção protegida, o plano completo em que o
  resultado é integrado) e o score reutiliza esse veredicto; a rejeição
  fica com o motivo `physical` e os tipos de violação.
- Compactação no ciclo de melhoria (Fase B3): `earliest_legal` (a
  normalização canónica) custa tanto como dezenas de candidatos num ISOP
  real, por isso não corre depois de cada movimento aceite. Corre uma vez
  quando os outros geradores param, numa reserva no fim do orçamento da
  fase (`improvement.CLOSING_COMPACTION_SHARE`, depois a duração medida);
  se for aceite e houver tempo, a pesquisa continua sobre o plano
  compactado. Cada candidato aceite já é completo e validado, por isso um
  orçamento que acaba antes ou durante a compactação devolve o último
  aceite (`closing_compaction` no relatório diz o que aconteceu; no
  «Recalcular plano» interativo não corre, ver nota de 12/10/2026). Um limite
  de avaliações (`max_evaluations`) conta também as da compactação: a
  pesquisa para uma avaliação antes, para a compactação final caber.
- Começar com um worker do solver; medir antes de aumentar. O código atual já
  usa um worker. GA/ML não são o caminho operacional e não são necessários
  para corrigir a falha reproduzida.
- Confirmado em 05/10/2026 (substitui a nota de 03/10): compactação,
  movimento manual, CPO e recálculo dão ao ciclo de melhoria o tempo que resta
  no orçamento do pedido menos a reserva de fecho
  (`planning_control.improvement_time_budget`); na revisão 90 a compactação
  demora ~50 s. Mais pesquisa, não menor latência. (Exceção de 12/10/2026
  para o «Recalcular plano» interativo: margem de resposta, ver abaixo.)
- **Decidido em 12/10/2026 (exceção à nota de 05/10 só para o «Recalcular
  plano» interativo):** o pedido guarda 15 s de margem de resposta
  (`api/data.RECALCULATE_RESPONSE_MARGIN_S`, contexto
  `planning_control.response_margin`): a reserva de fecho passa a margem +
  `CLOSING_WORK_S` (19 s em vez de 10 s) e o deadline de 60 s não muda. Dentro
  dessa margem o ciclo de melhoria não corre a compactação de fecho
  (`closing_compaction: "skipped"` no relatório) e a pesquisa fica com a fase
  inteira. Medido (revisões 123 e 124, 1 núcleo, 3 pares cada): a compactação
  de fecho nunca melhorou o plano em nenhuma execução medida e custava 7–12 s;
  o 409 passou de 51–53 s para 43–45 s (margem 15–17 s), com o plano novo igual
  ou melhor pelo comparador em todos os pares, 0 atrasos. Todos os outros
  chamadores (jobs de replaneamento em segundo plano, movimentos manuais,
  optimizador incluindo `deep`/`max`) mantêm a pesquisa e a compactação como
  antes. Risco aceite: um caso em que essa compactação
  ganharia (por exemplo logo após libertar capacidade) não foi observado.
- Movimento manual com material libertado por quantidades (12/10/2026,
  `plans/manual_move.py`): a realocação usa o mesmo construtor por partes do
  recálculo (`schedule_quantity_releases`) sobre os lotes existentes, sem os
  redimensionar. Esse construtor não lê âncoras, por isso, quando há
  libertações por quantidade (`_reallocation_ignores_target`), salta-se a
  realocação do plano inteiro e vai-se direto ao lote fixo primeiro
  (`_replan_around_fixed_lot`); a melhoria fica com o tempo poupado (~8 s na
  revisão 124; em 320 tentativas, mesmos resultados e os 15 candidatos
  idênticos antes da melhoria; uma verificação inconclusiva demora metade).
  **Corrigido em 14/10/2026** (Incompol: mover JTE001 para 04/12 15:30 dava
  «Verificação inconclusiva»; quase todos os movimentos falhavam): o lote
  movido não é trabalho começado, por isso nunca entra na proteção nem é
  creditado como stock no dia 0 (`frozen._install_frozen_reservations`); isso
  invalidava o contrato da operação (`source_contract`) e desligava a
  melhoria (`reference_invalid`). Agora fica fixado dentro do mesmo construtor
  (`schedule_quantity_releases(pinned=...)`), que coloca os outros lotes à
  volta dele e valida a operação com todos os seus lotes. A afinação do lote
  movido só é dispensada quando a produção começa colada a um segmento já
  começado com a mesma afinação (`_materialize_target(partial_layout=True)`):
  um intervalo vazio nesse esboço não prova a ferramenta montada. Na
  melhoria final o lote movido fica no plano (a âncora mantém o início); se a
  melhoria mexer nos seus segmentos, não é usada. Quando o movimento não é
  possível, a mensagem diz porquê («Não é possível iniciar … : …»);
  «inconclusiva» fica só para falta de tempo sem resposta. Medido na revisão
  142 (`tests/test_manual_move_pinned.py`): o caso da Incompol e os outros 9
  movimentos fisicamente possíveis passam (antes: 9 de 10 «inconclusiva»),
  sem atrasos novos nem lotes partidos; antes do dia de libertação e em
  feriado continuam recusados. Com a melhoria de novo ativa, cada movimento
  usa o orçamento (~50 s, como decidido a 05/10; confirmado pelo Luís a
  14/10: sempre com melhoria). Quando o lote cabe em tempo livre, a melhoria
  pode mexer noutros lotes (12–16 no ensaio) sem baixar atrasos nem setups;
  quando é preciso reorganizar, mexe em 6–17 (sem ela, 24–39). Uma recusa
  por falta de lugar diz «o motor não encontrou lugar»: é o resultado de uma
  tentativa do construtor, não uma prova de impossibilidade.
  Recusa imediata, antes de planear, com mensagem simples:
  dia de produção sem material libertado, afinação que começaria antes de
  `earliest_allowed_start` (ex.: produção às 07:00 do dia de libertação com a
  afinação no fim do dia anterior), e plano de um contrato de material
  anterior (`LegacyMaterialPlanError`, 409 `legacy_material_plan`, tanto ao
  iniciar a verificação como ao aplicar). Desde a versão 3 de material
  (13/10/2026) nenhum plano anterior é recusado assim: os lotes passam à
  versão 3 no início do movimento (§2).
- Decidido em 07/10/2026: a robustez já não consome orçamento do solver nem
  corre dentro de planeamento, melhoria, movimento ou recálculo (§1.6).
- Decidido em 08/10/2026: no modo `normal`, instâncias com 50 ou mais
  operações (qualquer ISOP real) saltam a pesquisa de candidatos e o polimento
  CP-SAT (`advisory_search_max_ops`, `final_source=baseline_search_skipped`);
  o ciclo de melhoria fica com esse tempo. Medido nas revisões 87 e 90: 0 de
  47 candidatos terminavam em 60 s e nenhum era aceite em 180 s; com o gate,
  +8 a +11 s de melhoria, 3 a 7 lotes mais cedo, 0 encomendas piores, setups
  iguais. O gate é por tamanho (determinístico), nunca por tempo; conta as
  operações que chegam ao optimizador (no recálculo, depois de filtrar o
  histórico). `deep`/`max` continuam a pesquisar; `quick` não muda.
- Replaneamento por calendário (11/10/2026): o ajuste rápido só corre quando
  a alteração invalida no máximo `replan.jobs.LOCAL_REPAIR_MAX_INVALID_SEGMENTS`
  segmentos (limite de trabalho, não de tempo); acima disso vai direto ao
  construtor completo. Quando corre, deixa ao construtor
  `LOCAL_REPAIR_OPTIMIZER_RESERVE_S` (35 s, medido na revisão 124).
- Capacidade libertada (13/10/2026): se o plano ativo tem uma entrega
  atrasada com capacidade livre antes do prazo (`jobs._late_with_idle_capacity`,
  o mesmo detetor do aviso), a compactação deixa os mesmos 35 s ao
  construtor. Atrasos só estruturais não reservam nada (ensaio na revisão
  128: a reserva custava 3 setups e 6 encomendas prontas mais tarde). Se
  depois da compactação ainda houver esse caso, corre o construtor completo
  (`optimize_preserving_started_lots`) e fica o melhor pelo comparador único,
  sem perdas por encomenda (`jobs._prefer_no_loss_plan`); se o construtor não
  terminar fica a compactação. Se não, a compactação continua com esse
  tempo. Notas de como um cálculo anterior foi feito
  («A alteração afeta…», «O ajuste rápido…»; `frozen.CALCULATION_NOTE_PREFIXES`)
  não passam para o plano novo.
- Um deadline exterior abrange preparação, pesquisa, fecho, validação e escrita.
  Subfases nunca reiniciam o relógio. Preservar a reserva de fecho existente.
- Guardar o último candidato completo validado fora do solver. Timeout de uma
  fase não o apaga; cancelamento impede commit. Se não houver plano completo
  válido para os inputs atuais, devolver diagnóstico, não um snapshot obsoleto.
- `UNKNOWN`/limite de pesquisa não significam `INFEASIBLE`. Inviabilidade num
  subproblema com restantes lotes fixos não prova inviabilidade global.
- `completed` refere-se ao âmbito descrito. Não prometer ótimo global nem
  determinismo apenas por usar seed fixa e corte de tempo real.

- Auditoria operacional (10/10/2026): métricas baratas sempre calculadas;
  a classificação de inversões tem um limite de trabalho (não de tempo), para o
  mesmo plano dar sempre o mesmo resultado. `not_evaluated` nunca conta como
  aprovado: fica "por avaliar" e pede decisão do planeador.

## 7. Alterações e validação

- **Publicação (decidido em 10/10/2026):** o motor da Incompol só corre código
  que está num commit, depois das suítes completas, de cópia de segurança dos
  dados e de explicação ao Luís. Nunca copiar ficheiros para a árvore de
  produção nem reiniciar o serviço com alterações por guardar; uma só sessão
  mexe na árvore de produção de cada vez. Experiências fazem-se em worktrees
  ou cópias isoladas com `PP1_DATA_DIR`/`PP1_CONFIG_PATH` próprios.
- **Recusas com causas (decidido pelo Luís a 15/10/2026).** Uma alteração
  recusada nunca chega ao planeador só como contagem («Plano inválido: 1
  conflito.») nem num alerta do browser. Todas as recusas que vêm da
  validação física levam `causes`: frases simples feitas a partir dos
  conflitos do próprio validador, com dia, hora e referência (nunca o id
  interno do lote), físicas primeiro, e dizem quando o conflito envolve um
  lote fixado à mão («choca com a alteração manual da Referência …»).
  Um só formato (`plans/refusal.py`: `refusal_http`, `refusal_detail`,
  `refusal_causes`): respostas HTTP `{code, message, causes}`, jobs com
  `causes`, executores de dados mestre com `causes`; os logs guardam as
  primeiras causas, não só a contagem. No ecrã, `RefusalDetails` («Porquê:»)
  por baixo da mensagem. Proibido `HTTPException(4xx, str(exc))` nas APIs e
  `alert(` no frontend (testes em `tests/test_refusal.py` e
  `frontend/tests/refusal.test.tsx`). Casos reais: revisões 154 (mover JTE001
  para 03/12 08:45: a ferramenta JTE003 fica montada entre os dois lotes
  JTE003 fixados à mão) e 156 (feriado 07/12: 43 940 peças em falta, porque
  os lotes fixados à mão ficam com as datas do calendário antigo); sem
  fixações (revisão 148) os dois são aceites.

- **Limpeza pendente (código que já não corre, 13/10/2026).** Desde a versão
  3 de material `canonical.legacy_material_plan` devolve sempre falso, por
  isso ficaram sem efeito: `LegacyMaterialPlanError` (`plans/store.py`),
  `manual_plan._refuse_legacy_material_plan`,
  `restore.legacy_material_warning`, `jobs._baseline_needs_material_rebuild`
  e o ramo que mantém tudo de `_without_stale_legacy_warnings`. O motor
  antigo (construtor global, rasto de auditoria do dispatch, passes finais
  do scheduler) só planeia lotes de planos guardados antes de 08/10/2026
  (versão 0); o «explicar decisão» do copiloto deixou de ter rasto nos
  planos atuais. Fica para um plano de limpeza depois da publicação; não
  apagar sem esse plano nem sem as suítes completas.
- O checkout contém trabalho não consolidado de outras tarefas. Inspecionar
  estado/diff; não resetar, limpar, sobrescrever ou publicar alterações alheias.
- Para auditoria, ler SQLite com `mode=ro` e trabalhar sobre objetos destacados.
  Não substituir o plano ativo por iniciativa de uma análise ou de um teste.
- Testar regras, contraexemplos e quantidades; não testes que só repetem a
  implementação. Manter fixtures reais e versões com identificadores trocados.
- Usar um pequeno oráculo independente para comparar viabilidade/antecipação
  em instâncias reduzidas. O validador comum é necessário, mas não prova que
  o modelo e o validador não partilham o mesmo erro.
- Medir CPU/tempo/RSS, número de candidatos, rejeições e âmbito concluído.
  Uma execução não é um p95 e uma medição local não é um SLA de produção.
- Runtime observado: Python 3.12.3, OR-Tools 9.15.6755. A declaração Python
  `>=3.10` da raiz diverge de `backend/pyproject.toml` e da sintaxe existente;
  alinhar isso na fase de reprodutibilidade, sem atualizar dependências à cegas.

Teste focado desta auditoria: `.venv/bin/python -m pytest -q
tests/test_improvement_contract.py tests/test_alternative_repair.py
tests/test_mounting_evidence.py tests/test_subcontract_release.py
tests/test_candidate_retention.py tests/test_window.py`.

Mapa atual: datas em `scheduler/jit_policy.py`; montagem em
`scheduler/setup_identity.py`; fontes em `scheduler/canonical.py`; validação em
`scheduler/validation.py`; medida canónica de antecipação em
`scheduler/policy.py`; prontidão por entrega em
`scheduler/material_quantities.py` (partes em `scheduler/quantity_dispatch.py`); avaliação e ciclo em `scheduler/improvement.py`;
vizinhanças N1–N3, lote inteiro noutra máquina (`lot_machine_proposals`,
regra 3) e alocador "primeiro intervalo viável" em
`scheduler/alternative_repair.py`; N4 em `scheduler/local_cpsat.py`; proteção em
`plans/frozen.py`; orçamento em `planning_control.py` (todos sob `backend/`).
GA/MAP-Elites só offline em `cpo/offline_ga.py`.

Verificação: fixtures reais congeladas em `tests/fixtures/private/` (fora do
git; manifestos em `tests/fixtures/snapshots/`, criados por
`scripts/freeze_snapshot_fixture.py`); casos §8.1 em
`tests/test_acceptance_cases.py`; oráculos independentes em `tests/oracle.py` e
`tests/oracle_delivery.py` (ordem dos lotes própria, `oracle_lot_order`: não
confia na ordem da lista do plano);
benchmark repetível em `scripts/benchmark_solver.py`.
