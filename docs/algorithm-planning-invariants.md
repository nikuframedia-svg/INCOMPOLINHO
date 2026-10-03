# Invariantes do planeamento

## Objetivo operacional

O planeador maximiza primeiro o cumprimento das entregas e a prioridade de
ruptura. A janela de cinco dias úteis representa apenas a disponibilidade
simulada de matéria-prima: antes dessa data a produção é proibida; depois da
libertação, a produção deve ocupar o primeiro intervalo fisicamente viável.

A referência da janela é a entrega ao cliente para um artigo normal e o envio
planeado ao fornecedor para um artigo subcontratado. Este envio é a entrega
menos o lead time útil do fornecedor e o buffer de subcontratação. O prazo
controlável de produção coincide com essa referência nos subcontratados.
OTD/OTD-D permanecem métricas da entrega ao cliente e incluem o lead externo.

Marcos anteriores a `D0` não são truncados. Num lote gémeo, os outputs partilham
a matéria-prima do ciclo: o início mínimo é a menor libertação dos outputs e o
fim máximo é o menor prazo de produção. A libertação isolada de um output
posterior não atrasa a produção da necessidade urgente.

## Ordem e antecipação

- Uma referência com rutura anterior precede referências com menor urgência.
- Uma prioridade explícita resolve empates antes dos objetivos agregados.
- As passagens de dias vazios e gaps parciais procuram um ponto fixo no âmbito
  declarado. Se o orçamento ou o limite de pesquisa impedir o fecho, o relatório
  indica pesquisa parcial; não afirma ausência global de antecipações.
- As horas candidatas a início incluem o momento em que a equipa de setup fica
  livre, também quando está ocupada com trabalho já iniciado (reservado) noutra
  máquina do grupo: uma produção espera pela equipa no mesmo dia em vez de
  passar para o dia seguinte.
- Cada fragmento antecipado conserva `prod_min`, quantidades e outputs gémeos;
  o resíduo de arredondamento permanece no último fragmento.
- Uma antecipação só é aceite quando não piora nenhuma encomenda individual,
  a janela de material, recursos físicos, operadores, setups ou contenção de
  ferramentas (ver "Melhoria automática sem perdas").

## Setups

- A identidade de setup é `(molde, SKU)` para referências independentes e
  `(molde, par de SKUs)` para gémeas confirmadas. Mudar de referência no mesmo
  molde exige afinação completa.
- Um setup pertence ao mesmo `run` da produção que prepara.
- Scheduler e movimentos usam a mesma verificação de montagem anterior em
  `setup_identity.retained_setup_at`: identidade de afinação compatível, sem
  produção com outro molde na máquina nem uso do molde noutra máquina no intervalo.
  Um fragmento do próprio setup em análise não prova montagem anterior.
- Uma preparação repartida entre turnos é indivisível para essa decisão:
  conserva-se inteira quando necessária e retira-se inteira quando redundante.
  Preparação parcial não equivale a afinação concluída. Retirar uma preparação
  liberta tempo real; uma posição manual conserva a hora pedida, e os restantes
  avanços continuam a passar pela normalização com recursos e pelo contrato sem perdas.
- O setup e a produção que prepara respeitam a mesma data de libertação de
  material. Não é permitido preparar a máquina antes da janela dos cinco dias.
- Não pode existir troca de ferramenta entre o setup e essa produção.
- Um setup pode terminar no fecho da fábrica e a produção começar na primeira
  abertura útil seguinte. Nesse intervalo a ferramenta permanece montada e a
  máquina não pode ser usada por outra referência.
- Setup depois da produção, setup duplicado ou setup sem produção são violações
  físicas bloqueantes.

## Operadores

A capacidade simultânea de operadores por grupo e turno é uma restrição física
do plano: `validate_plan` reporta `operator_capacity` e um candidato que a
exceda é rejeitado como qualquer outra violação física. Ausências registadas
reduzem essa capacidade nos calendários; retirá-las devolve a capacidade em
todos os recálculos. Nenhuma reparação ou melhoria pode criar um excesso.

Os operadores de produção contam apenas durante os minutos produtivos. Num
segmento que começa por setup, esse intervalo é debitado à equipa de setup e os
operadores de produção só passam a ser necessários quando a preparação termina.

Pausas entre turnos são tempo fechado, não capacidade. A cronologia fabril
comprime essas pausas ao comparar segmentos, evitando falsos conflitos entre o
fim de um dia e a abertura do seguinte quando os turnos não são contíguos.

## Melhoria automática sem perdas

Depois de existir um candidato completo e válido, um ciclo único
(`backend/scheduler/improvement.py::improve_plan`) incorpora as melhorias que
não custam nada a ninguém. As rotinas existentes (antecipação, inversões de
prioridade, fim de campanha, máquina alternativa, troca entre turnos) apenas
propõem planos completos; um avaliador comum decide.

Uma proposta só é incorporada automaticamente quando, em simultâneo:

- é fisicamente válida e conserva lotes, quantidades e outputs gémeos;
- nenhuma encomenda (identidade estável, duplicados separados; sem detalhe de
  cliente usam-se os marcos canónicos da procura) perde quantidade no prazo ou
  ganha atraso, nem ao cliente nem na fábrica;
- nenhum marco de expedição para subcontratação atrasa;
- o número de setups físicos e os minutos de setup não aumentam (fragmentos do
  mesmo setup contam uma vez; reinstalação noutra máquina conta);
- é estritamente melhor pela ordem fixa: prioridade de entrega, setups, minutos
  de setup, transferências de ferramenta, custo temporal de produção, lotes
  alterados, deslocação temporal.

A comparação é feita contra o último candidato aceite e contra a referência da
fase. Um OTD agregado melhor nunca compensa uma encomenda individual pior.

Deixaram de existir excepções de aceitação: o fim de campanha já não aceita
+1 dia de atraso agregado nem reserva o turno final; a correcção de inversões
de prioridade já não aceita +1 setup; a máquina alternativa e a troca entre
turnos já não acrescentam setups. Famílias de setup descrevem compatibilidade
física, não autorizam perdas. Estas propostas continuam a ser descritas como
contrapartidas (`applied: false`) e só podem ser aplicadas pelo percurso de
pré-visualização e confirmação existente.

Uma rotina própria propõe manter cada ferramenta na mesma máquina quando ela
salta entre máquinas (A → B → A): o bloco volta para a máquina onde a
ferramenta já está e os trabalhos deslocados podem ir para a máquina que ele
deixa. Só é aceite sem perdas e com menos transferências; as que ficam têm uma
explicação (máquina mais lenta, atraso de uma encomenda, lote protegido,
pesquisa limitada) no relatório de gates e no Gantt. Depois de cada mudança em
grupo aceite corre logo a antecipação; se o tempo acabar antes, é devolvido o
último plano compactado — nunca um plano com tempo libertado por usar.

O ciclo corre só sobre lotes não iniciados e não ancorados; lotes históricos e
posições manuais ficam reservados e intactos (o avaliador rejeita qualquer
proposta que os altere). O relatório
`improvement_report` indica `completed` (concluído no âmbito declarado — nunca
prova de óptimo global), `partial` (orçamento ou limite) ou `not_evaluated`.

No movimento manual, o ciclo avalia o candidato completo, depois de juntar o
lote pedido e o histórico. A hora e a máquina pedidas continuam fixas. Os
caminhos de recurso não recriam lotes e passam pelo mesmo contrato antes de
devolver a pré-visualização. Uma verificação anterior só é reutilizada se a
assinatura física corresponder exatamente ao candidato completo atual. Sem
tempo para melhorar, o relatório indica `not_evaluated`; não copia uma
conclusão de outro estado. O orçamento exterior de 60 segundos não é reiniciado.

Quando a compactação de fecho ou a validação do resultado combinado obriga
a recuar, o registo de propostas acompanha esse recuo. Um movimento retirado
do candidato não pode continuar a constar como aceite na sua explicação.

Repor um plano guardado nunca optimiza: o snapshot é validado tal como está.
Um snapshot incompatível (modelo de planeamento anterior, gémeas alteradas) ou
com conflitos exige recálculo explícito (`recalculate=true`).

## Inviabilidade

Quando todas as entregas não cabem na janela de material, o solver devolve um
plano `best_effort` e um diagnóstico de capacidade. Não antecipa produção para
antes da libertação de material para esconder a falta de capacidade.

No ISOP Nikufra de 17.08, o modelo estrito prova inviabilidade com cinco dias
úteis e calcula um limite inferior de dez dias úteis. O principal recurso
limitante é a combinação PRM042/JDE002.

No ISOP de 01.09, o plano completo conserva 265/265 lotes e 4 114 784 peças,
com OTD 98,9% e OTD-D 99,7%. Os três atrasos remanescentes resultam do mesmo
défice estrutural de capacidade: dois lotes JDE002 longos na PRM042 e uma
necessidade já vencida no início do horizonte.

A validação final repetiu o cálculo integral duas vezes. As duas execuções
produziram os mesmos 564 segmentos e a mesma assinatura SHA-256
`dc9a20203e2edbc92248670e960af2d4bb3953f207813f592d3b3cffe6a58fab`.

## Validação obrigatória

Todos os caminhos que tornam um snapshot ativo (carregamento, gravação direta
e confirmação de alterações) validam o plano executável contra os dados e a
configuração desse snapshot na fronteira de persistência. Um relatório de
aprovação antigo não substitui esta verificação. Se falhar, o ponteiro do plano
ativo, o snapshot e o recibo da operação não são confirmados.

Lotes anteriores ao dia atual são planeamento passado protegido. A aplicação
não tem registos de execução que permitam afirmar que essa produção aconteceu.
Uma alteração posterior não pode reescrever silenciosamente esses horários nem
usar anotações antigas como prova da causa de uma lacuna.

Para um plano aceite como candidato operacional devem ser zero:

- violações da janela de matéria-prima;
- atrasos de envio para subcontratação sem aprovação explícita;
- oportunidades `left_shift_available` ainda por aplicar (lacunas antes de
  lotes históricos ou ancorados são explicadas em
  `protected_left_shift_detail` e não contam);
- interrupções de uma campanha por uma referência libertada menos urgente;
- sobreposições de máquina, ferramenta e equipas de setup;
- produção em indisponibilidades;
- setups destacados ou descontínuos;
- quantidades em falta, duplicadas ou em excesso.

Recálculos com os mesmos dados e configuração devem produzir a mesma assinatura
de segmentos e os mesmos indicadores.

O relatório de gates publica `left_shift_opportunities`,
`lower_priority_campaign_interruptions` e `priority_order_anomalies`, com o
detalhe dos lotes e recursos. Os dois primeiros impedem aplicação automática.
O terceiro é diagnóstico: uma ordem aparentemente invertida pode ser necessária
para evitar que um lote longo faça atrasar várias referências curtas. Só conta
como evitável (`permutable`) uma rotação válida sem perdas; se a correcção
exigir um setup extra, o estado é `setup_tradeoff` (decisão do planeador).

Na revisão final devem ser executados todos os testes backend e frontend, o
build de produção, a análise estática e `git diff --check`. Os totais pertencem
ao relatório da execução, não a este contrato, para não ficarem desatualizados.
