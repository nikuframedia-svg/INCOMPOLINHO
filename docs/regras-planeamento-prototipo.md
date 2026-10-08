# Regras de planeamento do protótipo

## Objetivo operacional

O planeador procura maximizar o OTD e o OTD-D. Quando duas ordens disputam o
mesmo recurso, vence primeiro a referência com rutura mais próxima e depois a
prioridade explícita configurada pelo cliente.

Para o caso validado pela Nikufra, `TP042173-0040-2` tem prioridade explícita
sobre `TP042173-0040-1`. A prioridade é aplicada no construtor global, no
polimento do plano e nas reparações finais, para que uma fase posterior não
desfaça a decisão.

## Regra dos cinco dias úteis

Os cinco dias úteis não representam uma política JIT da fábrica. São uma
aproximação temporária à disponibilidade de matéria-prima enquanto o protótipo
não recebe stocks e aprovisionamentos reais.

- Num artigo normal, a referência é a entrega ao cliente.
- Num artigo subcontratado, a referência é o envio planeado ao fornecedor:
  entrega ao cliente menos lead time útil e buffer de subcontratação.
- A libertação é sempre cinco dias úteis antes da respetiva referência.
- O buffer interno de fim antecipa o objetivo interno, mas não altera a
  libertação de material.
- Antes do limite: a produção não pode começar.
- A partir do limite: a produção deve começar o mais cedo possível quando
  máquina, ferramenta, equipa de setup e operadores estão disponíveis.
- Sábados, domingos, feriados e indisponibilidades não criam capacidade.
- O plano final não pode conter uma produção iniciada antes deste limite.
- Datas calculadas antes de `D0` permanecem negativas para assinalar uma
  necessidade herdada; não são silenciosamente truncadas para o início do ISOP.

O prazo controlável de produção é a entrega ao cliente para artigos normais e o
envio ao fornecedor para artigos subcontratados. OTD/OTD-D continuam a medir a
entrega ao cliente; a conclusão subcontratada só fica disponível depois do lead
time externo. Atrasos de envio têm KPI, detalhe e gate de aprovação próprios.

Em produções gémeas, cada output guarda os seus marcos isolados. Os dois outputs
partilham a matéria-prima do mesmo ciclo: a libertação mais cedo autoriza a
produção comum, que tem de terminar antes do prazo mais cedo. A referência com
necessidade posterior pode assim ser coproduzida antes da sua janela isolada sem
bloquear o ciclo urgente. Em cada ciclo, ambos os outputs têm a mesma quantidade
e o excedente de cada referência abate à procura futura. Eco-lotes efetivos
diferentes bloqueiam o cálculo. Todos os ciclos gémeos produzem os dois outputs
1:1; sem uma procura oposta até cinco dias de entrega, esse output fica marcado
como stock coproduzido. Conta no stock e só fica disponível após o lead SUBC,
quando aplicável, mas não cria uma entrega nem um envio ao subcontratante
fictícios.

## Produzir o mais cedo possível

Depois da construção global, o planeador estabiliza o plano por passagens
determinísticas. Em cada passagem tenta ocupar espaços anteriores com:

- lotes completos que cabem sem fragmentação;
- a parte produtiva que caiba num intervalo parcial, conservando exatamente a
  quantidade restante no segmento de origem;
- continuações da mesma produção, divididas nas fronteiras dos turnos;
- o primeiro instante em que a equipa de setup fica livre, mesmo quando a
  máquina já estava livre antes.

Cada movimento é aceite apenas se conservar quantidades, não piorar entregas,
não criar produção antecipada fora da janela, não aumentar setups e passar a
validação física completa.

Uma fase adicional compara a sequência por rutura e prioridade em todos os
recursos partilhados. O melhor candidato encontrado ao longo do refinamento é
conservado explicitamente; uma compactação posterior não pode repor mais
inversões do que a melhor sequência já obtida.

## Setups e produção

Um setup tem de estar ligado à produção da mesma campanha.

Uma campanha é identificada por molde e afinação: referências independentes no
mesmo molde exigem novo setup ao mudar de SKU; lotes da mesma referência reutilizam
a afinação; um par gémeo confirmado constitui uma única afinação comum.

- Regra normal: a produção começa imediatamente depois do setup.
- Exceção permitida: o setup termina exatamente no fecho da fábrica e a
  produção começa na abertura do dia útil seguinte.
- Mesmo nessa exceção, o setup não pode começar antes da libertação simulada
  da matéria-prima.
- Nesta exceção, a máquina fica comprometida com a ferramenta durante a noite;
  não pode executar outra referência pelo meio.
- Um setup isolado durante o dia, um setup com outra ferramenta intercalada ou
  um setup sem produção posterior são violações bloqueantes.

Grandes e Médias usam equipas de setup independentes. Dentro do mesmo grupo,
o número de setups simultâneos é limitado por `setup_crews_by_group`.

## Explicação de espaços

O Gantt recebe, em cada primeiro bloco produtivo, razões verificáveis para não
começar antes. Entre outras:

- dia não útil;
- máquina inativa, ocupada ou indisponível;
- ferramenta ocupada ou indisponível;
- equipa de setup ocupada;
- capacidade de operadores insuficiente;
- referência concorrente com rutura mais prioritária;
- outra ferramenta intercalada antes da continuação da campanha;
- libertação simulada de matéria-prima ainda não atingida.

Uma oportunidade indica os minutos produtivos que podem realmente ser
antecipados, mesmo quando não cabe o segmento completo. Um intervalo que
obrigaria a trocar de ferramenta ou deixaria um setup desligado da produção não
é apresentado como espaço utilizável.

O planeador, o auditor final e as explicações do Gantt usam o mesmo avaliador de
intervalos. Assim, um espaço não pode ser classificado como livre por um destes
componentes e bloqueado por outro.

## Desempenho do fecho operacional

As oportunidades de antecipação são processadas em varrimentos determinísticos.
Cada movimento continua a ser validado individualmente, mas oportunidades
independentes da mesma fotografia do plano são aproveitadas antes de reconstruir
os índices de recursos. A auditoria detalhada é calculada apenas para o plano
final, não para cada vizinho intermédio do VNS.

## Validações bloqueantes

Antes de um plano ser aceite, são validados:

- sobreposição de máquinas;
- utilização simultânea da mesma ferramenta em máquinas diferentes;
- capacidade diária e indisponibilidades;
- sobreposição das equipas de setup;
- ordem setup-produção e continuidade da campanha;
- conservação integral das quantidades, incluindo produções gémeas;
- início dentro da janela simulada de matéria-prima.
- conclusão até ao envio de subcontratação, ou aprovação explícita do atraso.

## Caso de referência ISOP 17.08

Na validação automatizada do ISOP `ISOP_Nikufra_17.08.xlsx`:

- `TP042173-0040-2` começa primeiro na PRM042, no dia 0;
- não existem ruturas em referências com prioridade explícita;
- não existem produções antes do limite dos cinco dias úteis;
- não existem quantidades em falta, inesperadas ou produzidas em excesso;
- não existem conflitos físicos, setups desligados ou descontinuidades entre
  setup e produção;
- não ficam oportunidades de antecipação fisicamente válidas assinaladas pelo
  auditor final.

## Auditoria do ISOP 01.09

O recálculo integral mais recente obteve:

- 265 de 265 lotes e 4 114 784 de 4 114 784 peças;
- zero conflitos físicos e zero violações da janela de material;
- zero setups antes da disponibilidade simulada de matéria-prima;
- zero oportunidades diretas de antecipação ainda por aplicar;
- zero interrupções de campanhas urgentes por lotes menos urgentes;
- `TP042173-0040-2` antes de `TP042173-0040-1`;
- BFP079/`1064169X100` contínua antes de BFP183/`1661545X070` no caso analisado;
- cinco ordens contraintuitivas remanescentes, todas na PRM042/JDE002.

As cinco ordens remanescentes foram testadas com precedência forçada. Sob os
mesmos objetivos de entrega, são inviáveis: colocar primeiro os lotes JDE002,
muito longos, faria atrasar mais referências curtas. São por isso reportadas
como diagnóstico de capacidade, não como oportunidade de deslocação disponível.

O cálculo foi repetido duas vezes com os mesmos dados e configuração. A
assinatura integral dos 564 segmentos foi idêntica nas duas execuções, o que
confirma que o refinamento não depende de uma escolha aleatória do solver.
