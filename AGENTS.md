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

**Janela por entrega (decidido entre 07/10 e 10/10/2026).** Quando o
carry-forward atribui um lote económico a várias entregas, cada entrega
conserva o seu `R`: a quantidade atribuída a uma entrega só pode ser preparada
ou produzida a partir do seu próprio `R`. O excedente económico liberta-se com
a última entrega coberta. O lote é dimensionado uma vez (§3); partes
libertadas em datas diferentes são execuções físicas distintas.
Subcontratação: cada parte é expedida por entrega e fica pronta para o cliente
na sua própria conclusão mais o lead útil, não na conclusão do lote.

**Gémeas por entrega (decidido pelo Luís a 11/10/2026, Fase B2).** Cada lado
de um ciclo gémeo regista um output por entrega que as suas peças cobrem
(carry-forward), com as datas dessa entrega. Só as duas entregas que formam
o ciclo (no máximo uma por lado, com no máximo 5 dias entre elas) partilham
`R_ciclo = min(R)` (`cycle_material_release_day`); a quantidade feita para
entregas futuras não é produzida antes do `R` próprio dessas entregas. O
excedente económico de um lado liberta-se com o `R` próprio da última entrega
coberta desse lado, nunca com o `R_ciclo` (mesmo quando essa entrega é a do
par). Um lado sem nenhuma entrega coberta no ciclo é stock coproduzido: fica
registado (com as datas da entrega que controla o ciclo, só para
rastreabilidade) mas nunca liberta material; o ciclo segue a curva do outro
lado. Num dia `d`, o ciclo pode fazer tantos ciclos quanto o maior dos dois
lados libertados até `d`, sem contar stock coproduzido (cada ciclo faz uma
peça de cada lado; as do outro lado são coproduzidas). As
partes de um lote gémeo são os incrementos dessa curva; o tempo é sempre o de
uma execução (o maior dos dois lados, nunca a soma) e o lote económico
continua HARD por SKU. A prontidão é por lado e por entrega, como em qualquer
lote. Versão do contrato de material: `QUANTITY_MATERIAL_VERSION = 2`
(`lot_sizing.py`); planos guardados na versão 1 (ou sem versão) leem-se pelo
modelo registado, mas só se reativam se cumprirem as janelas atuais; caso
contrário pedem «Recalcular plano» (`canonical.legacy_material_plan`). Ao
repor um plano destes (incluindo no arranque) o plano mantém-se como foi
guardado e leva um aviso simples a pedir «Recalcular plano»
(`restore.legacy_material_warning`).

Regras do motor por entrega (propostas e aceites pelo Luís a 10/10/2026):

1. **Material já libertado, ferramenta continua.** Se o material da parte
   seguinte do lote já foi libertado quando a parte anterior acaba, a
   ferramenta montada continua a produzir, sem novo setup.
2. **Ferramenta montada vs. lote mais urgente.** A ferramenta montada continua
   mesmo havendo um lote mais urgente para a máquina, desde que esse lote perca
   menos de 60 min (a mesma tolerância do §1.3; dentro dela, os setups
   desempatam antes dos minutos exatos). Com 60 min ou mais, passa o urgente.
   A perda mede-se sobre todas as partes que faltam ao lote urgente, na sua
   melhor máquina, contra a posição que tinha **antes de começar a cadeia de
   continuações**: vários passos pequenos nunca somam 60 min ou mais. Nenhuma
   entrega do lote urgente pode ficar atrasada ou mais atrasada.
3. **Mudar de máquina leva o lote inteiro**, com todas as suas partes; um lote
   nunca fica repartido entre máquinas.
4. **Lote começado:** só congela o que já começou. As partes futuras continuam
   otimizáveis e o lote nunca é redimensionado. Implementado a 11/10/2026
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

Construtor por partes (`quantity_dispatch.py`, B1a):

- **Prioridade de uma parte:** `lot_priority_key` com a quantidade da entrega
  ao cliente que a parte serve (operação + dia, somada sobre todos os lotes),
  não a fatia da parte; só contam as entregas com o mesmo prazo de produção
  da parte. Uma parte com uma fatia de uma entrega grande não espera atrás de
  uma entrega mais pequena do mesmo dia.
- **Entregas primeiro, mesmo dia:** uma parte menos urgente com prazo igual
  ou anterior passa à frente quando isso salva a sua entrega e nenhuma
  entrega fica mais atrasada (nem a do lote que ultrapassa, nem as das partes
  ordenadas entre elas). A cadeia de continuações para quando se aplica.
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
tempo absoluto sobre todos os lotes da operação. O motivo de aprovação
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
- Dimensionar o lote económico efetivo e carry-forward uma vez. Um movimento
  altera alocação, não inventa novos lotes, compromissos ou quantidades.
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
  (`api/data._recalculation_needs_rebuild`).
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
  (`improvement.order_service`) e envios para subcontratação depois de `H`
  com tempo de turno livre (`calendar.free_shift_intervals`; hoje só depois
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
  Recusa imediata, antes de planear, com mensagem simples:
  dia de produção sem material libertado, afinação que começaria antes de
  `earliest_allowed_start` (ex.: produção às 07:00 do dia de libertação com a
  afinação no fim do dia anterior), e plano de um contrato de material
  anterior (`LegacyMaterialPlanError`, 409 `legacy_material_plan`, tanto ao
  iniciar a verificação como ao aplicar). Esse plano mostra o aviso no topo
  do ecrã (`plan-view.plan_notices`).
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
